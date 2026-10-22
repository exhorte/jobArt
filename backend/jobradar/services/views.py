"""Lecture : requêtes filtrées d'annonces, état des sources, tableau de bord. Aucune donnée n'est inventée :
les indicateurs sont calculés à partir de la base, sinon vides."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.orm import Session

from ..collectors.registry import CONNECTORS
from ..core.errors import ErrorType
from ..models import (
    JobOffer,
    JobOfferSource,
    JobSource,
    OfferScore,
    OfferStatus,
    SavedJob,
    SearchProfile,
    SearchRun,
    SearchRunSource,
    UserStatus,
)
from ..schemas.offers import FreshnessOut, OfferDetail, OfferListItem, OfferSourceOut, ScoreOut
from ..schemas.sources import SourceOut
from .freshness import age_info
from .text import normalize_text

_ACCESS_ERRORS = {ErrorType.NETWORK, ErrorType.TIMEOUT, ErrorType.UNAVAILABLE, ErrorType.BLOCKED, ErrorType.ROBOTS, ErrorType.RATE_LIMITED}

STATE_LABELS = {
    "active": "Active",
    "disabled": "Désactivée",
    "to_verify": "À vérifier",
    "unreachable": "Inaccessible",
    "error": "En erreur",
    "excluded": "Exclue",
}


# --------------------------------------------------------------------------- sources
def compute_source_state(src: JobSource) -> str:
    """active | disabled | to_verify | unreachable | error | excluded (voir page Sources)."""
    if src.implementation == "excluded":
        return "excluded"
    if src.implementation != "implemented" or src.source_key not in CONNECTORS and src.source_type != "manual":
        return "unreachable" if src.verification_status == "inaccessible" else "to_verify"
    if src.source_type == "manual":
        return "active" if src.enabled else "disabled"
    if not src.enabled:
        return "disabled"
    last_test_failed = src.last_check_ok is False and (src.last_run_at is None or (src.last_checked_at and src.last_checked_at >= src.last_run_at))
    if last_test_failed or src.last_run_status == "failed":
        return "unreachable" if src.last_error_type in _ACCESS_ERRORS else "error"
    if src.last_run_at is None and src.last_checked_at is None:
        return "to_verify"  # jamais testée ni exécutée dans cette installation
    return "active"


def source_to_out(session: Session, src: JobSource) -> SourceOut:
    offers_count = session.scalar(select(func.count(func.distinct(JobOfferSource.job_offer_id))).where(JobOfferSource.job_source_id == src.id)) or 0
    errors_count = session.scalar(
        select(func.count()).select_from(SearchRunSource).where(SearchRunSource.job_source_id == src.id, SearchRunSource.status == "failed")
    ) or 0
    last_found = session.scalar(
        select(SearchRunSource.offers_found)
        .where(SearchRunSource.job_source_id == src.id, SearchRunSource.status == "success")
        .order_by(SearchRunSource.id.desc())
        .limit(1)
    )
    state = compute_source_state(src)
    cfg = dict(src.configuration or {})
    return SourceOut(
        key=src.source_key,
        name=src.name,
        base_url=src.base_url,
        source_type=src.source_type,
        market=src.market,
        countries=list(src.countries or []),
        enabled=src.enabled,
        collection_method=src.collection_method,
        verification_status=src.verification_status,
        implementation=src.implementation,
        can_collect=src.source_key in CONNECTORS and src.implementation == "implemented",
        decision_reason=src.decision_reason,
        tos_note=src.tos_note,
        doc_status=src.doc_status,
        state=state,
        state_label=STATE_LABELS[state],
        last_checked_at=src.last_checked_at,
        last_check_ok=src.last_check_ok,
        last_success_at=src.last_success_at,
        last_run_at=src.last_run_at,
        last_run_status=src.last_run_status,
        last_error=src.last_error,
        last_error_type=src.last_error_type,
        offers_count=offers_count,
        errors_count=errors_count,
        last_run_offers_found=last_found,
        min_interval_minutes=int(cfg["min_interval_minutes"]) if cfg.get("min_interval_minutes") else None,
        configuration=cfg,
    )


# --------------------------------------------------------------------------- annonces
@dataclass
class OfferFilters:
    q: str | None = None
    country: str | None = None
    city: str | None = None
    sources: list[str] = field(default_factory=list)
    company: str | None = None
    contract_types: list[str] = field(default_factory=list)
    work_modes: list[str] = field(default_factory=list)
    user_statuses: list[str] = field(default_factory=list)
    lifecycle: list[str] = field(default_factory=list)
    profile_id: int | None = None
    min_score: float | None = None
    max_score: float | None = None
    published_from: datetime | None = None
    published_to: datetime | None = None
    first_seen_from: datetime | None = None
    first_seen_to: datetime | None = None
    remote_eligibility: list[str] = field(default_factory=list)
    include_ignored: bool = False
    sort: str = "recent"  # recent | relevance | company | detected
    order: str = "desc"


def _score_expr(f: OfferFilters):
    return OfferScore.score if f.profile_id is not None else JobOffer.best_score


def build_offer_query(f: OfferFilters) -> Select[Any]:
    score_col = _score_expr(f)
    user_status = func.coalesce(SavedJob.user_status, UserStatus.NEW.value)
    stmt = select(JobOffer, score_col.label("score"), user_status.label("user_status")).outerjoin(
        SavedJob, SavedJob.job_offer_id == JobOffer.id
    )
    if f.profile_id is not None:
        stmt = stmt.outerjoin(OfferScore, and_(OfferScore.job_offer_id == JobOffer.id, OfferScore.profile_id == f.profile_id))

    conds = []
    if f.q:
        for term in f.q.split():
            nt = normalize_text(term)
            like = f"%{term}%"
            parts = [JobOffer.description.ilike(like)]
            if nt:
                parts += [JobOffer.normalized_title.contains(nt), JobOffer.normalized_company.contains(nt)]
            conds.append(or_(*parts))
    if f.country:
        conds.append(JobOffer.country == f.country.upper())
    if f.city:
        conds.append(func.lower(JobOffer.city) == f.city.lower())
    if f.company:
        nc = normalize_text(f.company)
        conds.append(JobOffer.normalized_company.contains(nc) if nc else JobOffer.company_name.ilike(f"%{f.company}%"))
    if f.sources:
        conds.append(
            exists().where(
                JobOfferSource.job_offer_id == JobOffer.id,
                JobOfferSource.job_source_id.in_(select(JobSource.id).where(JobSource.source_key.in_(f.sources))),
            )
        )
    if f.contract_types:
        conds.append(JobOffer.contract_type.in_(f.contract_types))
    if f.work_modes:
        conds.append(JobOffer.work_mode.in_(f.work_modes))
    if f.lifecycle:
        conds.append(JobOffer.status.in_(f.lifecycle))
    if f.remote_eligibility:
        conds.append(JobOffer.remote_eligibility.in_(f.remote_eligibility))
    if f.user_statuses:
        conds.append(user_status.in_(f.user_statuses))
    elif not f.include_ignored:
        conds.append(user_status != UserStatus.IGNORED.value)
    if f.min_score is not None:
        conds.append(score_col >= f.min_score)
    if f.max_score is not None:
        conds.append(score_col <= f.max_score)
    if f.published_from:
        conds.append(JobOffer.published_at >= f.published_from)
    if f.published_to:
        conds.append(JobOffer.published_at <= f.published_to)
    if f.first_seen_from:
        conds.append(JobOffer.first_seen_at >= f.first_seen_from)
    if f.first_seen_to:
        conds.append(JobOffer.first_seen_at <= f.first_seen_to)
    if conds:
        stmt = stmt.where(and_(*conds))

    desc = f.order != "asc"
    effective_date = func.coalesce(JobOffer.published_at, JobOffer.first_seen_at)
    if f.sort == "relevance":
        keys = [score_col.desc().nulls_last() if desc else score_col.asc().nulls_last(), effective_date.desc()]
    elif f.sort == "company":
        keys = [
            case((JobOffer.normalized_company.is_(None), 1), else_=0),
            JobOffer.normalized_company.desc() if f.order == "desc" else JobOffer.normalized_company.asc(),
            JobOffer.normalized_title.asc(),
        ]
    elif f.sort == "detected":
        keys = [JobOffer.first_seen_at.desc() if desc else JobOffer.first_seen_at.asc()]
    else:  # recent : date de publication déclarée, à défaut première détection
        keys = [effective_date.desc() if desc else effective_date.asc()]
    return stmt.order_by(*keys, JobOffer.id.desc())


def _sources_by_offer(session: Session, offer_ids: list[int]) -> dict[int, list[tuple[JobOfferSource, JobSource]]]:
    out: dict[int, list[tuple[JobOfferSource, JobSource]]] = {i: [] for i in offer_ids}
    if not offer_ids:
        return out
    rows = session.execute(
        select(JobOfferSource, JobSource)
        .join(JobSource, JobSource.id == JobOfferSource.job_source_id)
        .where(JobOfferSource.job_offer_id.in_(offer_ids))
        .order_by(JobOfferSource.id)
    )
    for link, src in rows:
        out[link.job_offer_id].append((link, src))
    return out


def to_list_items(session: Session, rows: list[tuple[JobOffer, float | None, str]], *, now: datetime, profile_id: int | None) -> list[OfferListItem]:
    ids = [o.id for o, _s, _u in rows]
    sources = _sources_by_offer(session, ids)
    names = {p.id: p.name for p in session.scalars(select(SearchProfile))}
    items: list[OfferListItem] = []
    for offer, score, user_status in rows:
        links = sources.get(offer.id, [])
        age = age_info(published_at=offer.published_at, first_seen_at=offer.first_seen_at, now=now)
        pid = profile_id if profile_id is not None else offer.best_profile_id
        items.append(
            OfferListItem(
                id=offer.id,
                title=offer.title,
                company_name=offer.company_name,
                location=offer.location,
                country=offer.country,
                city=offer.city,
                work_mode=offer.work_mode,
                contract_type=offer.contract_type,
                experience_level=offer.experience_level,
                published_at=offer.published_at,
                first_seen_at=offer.first_seen_at,
                last_seen_at=offer.last_seen_at,
                application_deadline=offer.application_deadline,
                lifecycle_status=offer.status,
                freshness=FreshnessOut(age_days=age.age_days, label=age.label, first_seen_age_days=age.first_seen_age_days),
                score=score,
                score_profile_id=pid if score is not None else None,
                score_profile_name=names.get(pid) if score is not None else None,
                user_status=user_status,
                primary_url=links[0][0].original_url if links else offer.canonical_url,
                sources=[{"key": s.source_key, "name": s.name, "url": link.original_url} for link, s in links],
                estimated_fields=list(offer.estimated_fields or []),
                remote_eligibility=offer.remote_eligibility,
                salary_min=offer.salary_min,
                salary_max=offer.salary_max,
                salary_currency=offer.salary_currency,
                salary_period=offer.salary_period,
            )
        )
    return items


def offer_detail(session: Session, offer: JobOffer, *, now: datetime) -> OfferDetail:
    saved = session.get(SavedJob, offer.id)
    user_status = saved.user_status if saved else UserStatus.NEW.value
    score = offer.best_score
    base = to_list_items(session, [(offer, score, user_status)], now=now, profile_id=None)[0]
    links = _sources_by_offer(session, [offer.id])[offer.id]
    names = {p.id: p.name for p in session.scalars(select(SearchProfile))}
    scores = [
        ScoreOut(
            profile_id=s.profile_id,
            profile_name=names.get(s.profile_id, "?"),
            score=s.score,
            breakdown=s.breakdown,
            explanation=s.explanation,
            computed_at=s.computed_at,
        )
        for s in sorted(offer.scores, key=lambda x: -x.score)
    ]
    source_links = []
    for link, src in links:
        meta = link.raw_metadata or {}
        source_links.append(
            OfferSourceOut(
                source_key=src.source_key,
                source_name=src.name,
                original_url=link.original_url,
                source_job_id=link.source_job_id,
                published_at=link.source_published_at,
                first_seen_at=link.source_first_seen_at,
                last_seen_at=link.source_last_seen_at,
                status=link.source_status,
                published_text=meta.get("published_text"),
                attribution=meta.get("attribution"),
                same_as_urls=list(meta.get("same_as_urls", [])),
            )
        )
    return OfferDetail(
        **base.model_dump(),
        description=offer.description,
        sector=offer.sector,
        remote_regions=list(offer.remote_regions or []),
        last_verified_at=offer.last_verified_at,
        notes=saved.notes if saved else None,
        saved_at=saved.saved_at if saved else None,
        source_links=source_links,
        scores=scores,
        content_hash=offer.content_hash,
    )


# --------------------------------------------------------------------------- tableau de bord
def dashboard(session: Session, *, now: datetime, scheduler: dict[str, Any]) -> dict[str, Any]:
    total = session.scalar(select(func.count(JobOffer.id))) or 0
    user_status = func.coalesce(SavedJob.user_status, UserStatus.NEW.value)
    base = select(func.count(JobOffer.id)).outerjoin(SavedJob, SavedJob.job_offer_id == JobOffer.id)
    new_offers = session.scalar(base.where(user_status == UserStatus.NEW.value)) or 0
    saved = session.scalar(base.where(user_status == UserStatus.SAVED.value)) or 0
    applied = session.scalar(base.where(user_status == UserStatus.APPLIED.value)) or 0
    recent_cut = now - timedelta(days=7)
    recent = session.scalar(select(func.count(JobOffer.id)).where(JobOffer.first_seen_at >= recent_cut)) or 0
    detected_24h = session.scalar(select(func.count(JobOffer.id)).where(JobOffer.first_seen_at >= now - timedelta(hours=24))) or 0

    sources = session.scalars(select(JobSource).order_by(JobSource.id)).all()
    states = {s.source_key: compute_source_state(s) for s in sources}
    implemented = [s for s in sources if s.source_key in CONNECTORS or s.source_type == "manual"]
    active_sources = sum(1 for s in implemented if s.enabled and states[s.source_key] in {"active", "to_verify"})
    in_error = [
        {"key": s.source_key, "name": s.name, "state": states[s.source_key], "error": s.last_error, "error_type": s.last_error_type}
        for s in implemented
        if states[s.source_key] in {"error", "unreachable"} and s.enabled
    ]
    last_run = session.scalar(select(SearchRun).order_by(SearchRun.id.desc()).limit(1))

    def count_by(col: Any, label: str) -> list[dict[str, Any]]:
        rows = session.execute(select(col, func.count(JobOffer.id)).group_by(col).order_by(func.count(JobOffer.id).desc())).all()
        return [{label: (k if k is not None else "inconnu"), "count": n} for k, n in rows]

    by_source = [
        {"source": name, "key": key, "count": n}
        for key, name, n in session.execute(
            select(JobSource.source_key, JobSource.name, func.count(func.distinct(JobOfferSource.job_offer_id)))
            .join(JobOfferSource, JobOfferSource.job_source_id == JobSource.id)
            .group_by(JobSource.id)
            .order_by(func.count(func.distinct(JobOfferSource.job_offer_id)).desc())
        )
    ]
    by_profile = [
        {"profile": name or "—", "count": n}
        for name, n in session.execute(
            select(SearchProfile.name, func.count(JobOffer.id))
            .join(JobOffer, JobOffer.best_profile_id == SearchProfile.id)
            .where(JobOffer.best_score >= 50)
            .group_by(SearchProfile.id)
            .order_by(func.count(JobOffer.id).desc())
        )
    ]
    top_rows = session.execute(
        select(JobOffer, JobOffer.best_score, user_status)
        .outerjoin(SavedJob, SavedJob.job_offer_id == JobOffer.id)
        .where(JobOffer.best_score.is_not(None), user_status != UserStatus.IGNORED.value, JobOffer.status != OfferStatus.DEADLINE_PASSED.value)
        .order_by(JobOffer.best_score.desc(), JobOffer.first_seen_at.desc())
        .limit(6)
    ).all()
    recent_rows = session.execute(
        select(JobOffer, JobOffer.best_score, user_status)
        .outerjoin(SavedJob, SavedJob.job_offer_id == JobOffer.id)
        .order_by(JobOffer.first_seen_at.desc(), JobOffer.id.desc())
        .limit(8)
    ).all()
    return {
        "total_offers": total,
        "new_offers": new_offers,
        "saved_offers": saved,
        "applied_offers": applied,
        "recently_detected_7d": recent,
        "detected_24h": detected_24h,
        "active_sources": active_sources,
        "total_connectors": len(implemented),
        "sources_in_error": in_error,
        "last_run": {
            "id": last_run.id,
            "status": last_run.status,
            "started_at": last_run.started_at,
            "finished_at": last_run.finished_at,
            "trigger_type": last_run.trigger_type,
            "offers_found": last_run.offers_found,
            "offers_created": last_run.offers_created,
            "duplicates_detected": last_run.duplicates_detected,
            "sources_failed": last_run.sources_failed,
        }
        if last_run
        else None,
        "scheduler": scheduler,
        "by_source": by_source,
        "by_sector": count_by(JobOffer.sector, "sector"),
        "by_profile": by_profile,
        "by_work_mode": count_by(JobOffer.work_mode, "work_mode"),
        "top_matches": [i.model_dump(mode="json") for i in to_list_items(session, [(o, s, u) for o, s, u in top_rows], now=now, profile_id=None)],
        "recent": [i.model_dump(mode="json") for i in to_list_items(session, [(o, s, u) for o, s, u in recent_rows], now=now, profile_id=None)],
    }
