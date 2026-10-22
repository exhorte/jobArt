"""Persistance des annonces normalisées : création, mise à jour, déduplication, scores, statuts.

Toutes les fonctions sont synchrones et prennent une `Session` (appelées depuis un thread par le moteur de collecte).
Règles de fusion :
* même source  : la valeur la plus récente déclarée par la source l'emporte (si non nulle) ;
* autre source : on ne fait que COMPLÉTER les champs manquants (la 1re source reste la référence) ; la date de
  publication retenue est la plus ancienne déclarée ; la date limite la plus proche (prudence) ; en cas de désaccord sur
  l'éligibilité télétravail, « restreint » l'emporte (on ne laisse pas croire qu'une offre est ouverte).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..collectors.base import NormalizedJob
from ..models import JobOffer, JobOfferSource, JobSource, OfferScore, OfferStatus, OfferUrlKey, SavedJob, UserStatus
from .dedupe import Identity, Match, build_identity, find_identity_duplicate, find_match
from .enrich import detect_sectors
from .freshness import STALE_AFTER_DAYS
from .scoring import ProfileCriteria, ScorableOffer, score_offer
from .text import content_hash, normalize_company
from .urls import clean_url, url_key

log = logging.getLogger(__name__)

_USER_STATUS_RANK = {s.value: i for i, s in enumerate([UserStatus.NEW, UserStatus.SEEN, UserStatus.IGNORED, UserStatus.SAVED, UserStatus.APPLIED])}
_PERIODS = {"annual": "yearly", "year": "yearly", "hour": "hourly", "month": "monthly", "day": "daily"}


@dataclass
class IngestStats:
    found: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    duplicates: int = 0  # doublons inter-sources reconnus (nouvelle URL rattachée à une annonce existante)
    merged: int = 0  # annonces déjà enregistrées fusionnées a posteriori
    ambiguous: int = 0  # rapprochements ambigus laissés séparés
    errors: int = 0

    def add(self, other: IngestStats) -> None:
        for f in self.__dataclass_fields__:
            setattr(self, f, getattr(self, f) + getattr(other, f))


# --------------------------------------------------------------------------- helpers
def _empty(v: Any) -> bool:
    return v is None or v == "" or v == []


def _clean_metadata(job: NormalizedJob) -> dict[str, Any]:
    meta: dict[str, Any] = dict(job.raw_metadata or {})
    if job.same_as_urls:
        meta["same_as_urls"] = job.same_as_urls[:5]
    if job.published_text:
        meta["published_text"] = job.published_text
    if job.estimated_fields:
        meta["estimated_fields"] = job.estimated_fields
    meta["detail_fetched"] = job.verified_at is not None
    raw = json.dumps(meta, ensure_ascii=False, default=str)
    if len(raw) > 8000:  # garde-fou de taille
        meta = {k: v for k, v in meta.items() if len(json.dumps(v, default=str)) < 1000}
    return json.loads(json.dumps(meta, ensure_ascii=False, default=str))


def _longer_text(old: str | None, new: str | None) -> str | None:
    if _empty(old):
        return new or None
    if _empty(new):
        return old
    return new if len(new) > len(old) * 1.2 else old


def _merge_eligibility(old: str | None, new: str | None) -> str | None:
    order = {"restricted": 3, "eligible": 2, "unknown": 1, None: 0}
    return old if order.get(old, 0) >= order.get(new, 0) else new


def _compute_hash(o: JobOffer) -> str:
    return content_hash(o.title, o.company_name, o.location, (o.description or "")[:2000], str(o.application_deadline or ""))


def _sector_of(company: str | None, title: str, description: str | None, industry: str | None = None) -> str | None:
    found = detect_sectors(company, title, (description or "")[:4000], industry)
    return found[0] if found else None


def _norm_period(p: str | None) -> str | None:
    return _PERIODS.get(p, p) if p else None


# --------------------------------------------------------------------------- création / mise à jour d'une annonce
def _create_offer(job: NormalizedJob, identity: Identity, now: datetime) -> JobOffer:
    offer = JobOffer(
        canonical_url=clean_url(job.url),
        title=job.title[:500],
        normalized_title=identity.title[:500],
        company_name=(job.company_name or None) and job.company_name[:300],
        normalized_company=identity.company,
        description=job.description,
        location=(job.location or None) and job.location[:300],
        country=job.country,
        city=(job.city or None) and job.city[:120],
        work_mode=job.work_mode,
        contract_type=job.contract_type,
        experience_level=job.experience_level,
        sector=_sector_of(job.company_name, job.title, job.description, job.industry),
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        salary_period=_norm_period(job.salary_period),
        remote_eligibility=job.remote_eligibility,
        remote_regions=list(job.remote_regions),
        published_at=job.published_at,
        application_deadline=job.application_deadline,
        first_seen_at=now,
        last_seen_at=now,
        last_verified_at=job.verified_at,
        status=OfferStatus.LISTED.value,
        content_hash="",
        estimated_fields=list(job.estimated_fields),
    )
    offer.content_hash = _compute_hash(offer)
    return offer


def _update_offer(offer: JobOffer, job: NormalizedJob, identity: Identity, now: datetime, *, same_source: bool) -> bool:
    """Met à jour `offer` avec `job`. Renvoie True si le contenu a changé."""
    before = offer.content_hash
    estimated = set(offer.estimated_fields or [])

    def assign(attr: str, value: Any) -> None:
        if _empty(value):
            return
        cur = getattr(offer, attr)
        if same_source:
            if cur != value:
                setattr(offer, attr, value)
        elif _empty(cur):
            setattr(offer, attr, value)

    # --- champs « estimables » : une valeur déclarée remplace une estimation
    if job.company_name:
        declared = "company_name" not in job.estimated_fields
        if _empty(offer.company_name):
            offer.company_name = job.company_name[:300]
            offer.normalized_company = normalize_company(job.company_name)
            estimated.discard("company_name") if declared else estimated.add("company_name")
        elif declared and "company_name" in estimated:  # une valeur déclarée remplace l'estimation
            offer.company_name = job.company_name[:300]
            offer.normalized_company = normalize_company(job.company_name)
            estimated.discard("company_name")
        elif same_source and declared and offer.company_name != job.company_name:
            offer.company_name = job.company_name[:300]
            offer.normalized_company = normalize_company(job.company_name)
    if same_source and job.title and offer.title != job.title:
        offer.title = job.title[:500]
        offer.normalized_title = identity.title[:500]

    offer.description = _longer_text(offer.description, job.description) if not same_source else (job.description or offer.description)
    for attr in ("location", "country", "city", "work_mode", "contract_type", "experience_level"):
        assign(attr, getattr(job, attr))
    assign("salary_min", job.salary_min)
    assign("salary_max", job.salary_max)
    assign("salary_currency", job.salary_currency)
    assign("salary_period", _norm_period(job.salary_period))
    if job.remote_regions and _empty(offer.remote_regions):
        offer.remote_regions = list(job.remote_regions)
    offer.remote_eligibility = _merge_eligibility(offer.remote_eligibility, job.remote_eligibility) if not same_source else (
        job.remote_eligibility or offer.remote_eligibility
    )
    # dates
    if job.published_at and (offer.published_at is None or job.published_at < offer.published_at):
        offer.published_at = job.published_at
    if job.application_deadline:
        if offer.application_deadline is None:
            offer.application_deadline = job.application_deadline
        elif same_source:
            offer.application_deadline = job.application_deadline
        else:
            offer.application_deadline = min(offer.application_deadline, job.application_deadline)
    if job.verified_at and (offer.last_verified_at is None or job.verified_at > offer.last_verified_at):
        offer.last_verified_at = job.verified_at
    offer.estimated_fields = sorted(estimated)
    offer.sector = _sector_of(offer.company_name, offer.title, offer.description) or offer.sector
    offer.last_seen_at = now
    offer.content_hash = _compute_hash(offer)
    return offer.content_hash != before


def _upsert_source_link(
    session: Session, offer: JobOffer, source: JobSource, job: NormalizedJob, key: str, now: datetime
) -> JobOfferSource:
    link = None
    if job.source_job_id:
        link = session.scalar(
            select(JobOfferSource).where(JobOfferSource.job_source_id == source.id, JobOfferSource.source_job_id == job.source_job_id)
        )
    if link is None:
        link = session.scalar(
            select(JobOfferSource).where(JobOfferSource.job_source_id == source.id, JobOfferSource.original_url_key == key)
        )
    meta = _clean_metadata(job)
    if link is None:
        link = JobOfferSource(
            job_offer_id=offer.id,
            job_source_id=source.id,
            original_url=clean_url(job.url),
            original_url_key=key,
            source_job_id=job.source_job_id,
            source_published_at=job.published_at,
            source_first_seen_at=now,
            source_last_seen_at=now,
            source_status="listed",
            raw_metadata=meta,
        )
        session.add(link)
    else:
        link.job_offer_id = offer.id
        link.original_url = clean_url(job.url)
        link.original_url_key = key
        if job.source_job_id:
            link.source_job_id = job.source_job_id
        if job.published_at:
            link.source_published_at = job.published_at
        link.source_last_seen_at = now
        link.source_status = "listed"
        link.raw_metadata = meta
    return link


def _register_url_keys(session: Session, offer: JobOffer, keys: list[tuple[str, str]]) -> None:
    for key, kind in keys:
        existing = session.get(OfferUrlKey, key)
        if existing is None:
            session.add(OfferUrlKey(url_key=key, job_offer_id=offer.id, kind=kind))
        elif existing.job_offer_id != offer.id and kind == "original":
            existing.job_offer_id = offer.id


# --------------------------------------------------------------------------- scores
def rescore_offer(session: Session, offer: JobOffer, profiles: list[ProfileCriteria], now: datetime) -> None:
    existing = {s.profile_id: s for s in session.scalars(select(OfferScore).where(OfferScore.job_offer_id == offer.id))}
    scorable = ScorableOffer.from_model(offer)
    best: tuple[float, int | None] | None = None
    live_ids = set()
    for profile in profiles:
        if profile.id is None:
            continue
        result = score_offer(scorable, profile, now=now)
        live_ids.add(profile.id)
        row = existing.get(profile.id)
        if row is None:
            session.add(OfferScore(job_offer_id=offer.id, profile_id=profile.id, score=result.score,
                                   breakdown=result.breakdown, explanation=result.explanation, computed_at=now))
        else:
            row.score, row.breakdown, row.explanation, row.computed_at = result.score, result.breakdown, result.explanation, now
        if best is None or result.score > best[0]:
            best = (result.score, profile.id)
    for pid, row in existing.items():
        if pid not in live_ids and profiles:  # profil supprimé/désactivé : score retiré
            session.delete(row)
    offer.best_score, offer.best_profile_id = (best[0], best[1]) if best else (None, None)


def rescore_all(session: Session, profiles: list[ProfileCriteria], now: datetime, *, batch: int = 200) -> int:
    """Recalcule tous les scores (après modification d'un profil). Renvoie le nombre d'annonces traitées."""
    total = 0
    last_id = 0
    while True:
        offers = session.scalars(select(JobOffer).where(JobOffer.id > last_id).order_by(JobOffer.id).limit(batch)).all()
        if not offers:
            break
        for o in offers:
            rescore_offer(session, o, profiles, now)
        session.flush()
        last_id = offers[-1].id
        total += len(offers)
    return total


# --------------------------------------------------------------------------- fusion a posteriori
def merge_offers(session: Session, keep: JobOffer, drop: JobOffer) -> None:
    """Fusionne `drop` dans `keep` (même poste connu via deux sources) sans perdre aucune URL ni le suivi utilisateur."""
    if keep.id == drop.id:
        return
    session.flush()
    session.execute(update(JobOfferSource).where(JobOfferSource.job_offer_id == drop.id).values(job_offer_id=keep.id))
    session.execute(update(OfferUrlKey).where(OfferUrlKey.job_offer_id == drop.id).values(job_offer_id=keep.id))
    # suivi utilisateur : on garde le statut le plus avancé et on concatène les notes
    s_keep = session.get(SavedJob, keep.id)
    s_drop = session.get(SavedJob, drop.id)
    if s_drop is not None:
        if s_keep is None:
            session.execute(update(SavedJob).where(SavedJob.job_offer_id == drop.id).values(job_offer_id=keep.id))
        else:
            if _USER_STATUS_RANK.get(s_drop.user_status, 0) > _USER_STATUS_RANK.get(s_keep.user_status, 0):
                s_keep.user_status = s_drop.user_status
                s_keep.saved_at = s_drop.saved_at or s_keep.saved_at
            if s_drop.notes:
                s_keep.notes = "\n".join(x for x in (s_keep.notes, s_drop.notes) if x)
            session.delete(s_drop)
    session.execute(delete(OfferScore).where(OfferScore.job_offer_id == drop.id))
    session.flush()
    session.expire(keep)
    session.expire(drop)
    # complète `keep` avec ce que `drop` sait en plus
    inherits_estimated_company = _empty(keep.company_name) and not _empty(drop.company_name) and "company_name" in (drop.estimated_fields or [])
    for attr in ("company_name", "description", "location", "country", "city", "work_mode", "contract_type",
                 "experience_level", "salary_min", "salary_max", "salary_currency", "salary_period"):
        if _empty(getattr(keep, attr)) and not _empty(getattr(drop, attr)):
            setattr(keep, attr, getattr(drop, attr))
    if keep.company_name and not keep.normalized_company:
        keep.normalized_company = normalize_company(keep.company_name)
    keep.description = _longer_text(keep.description, drop.description)
    keep.remote_eligibility = _merge_eligibility(keep.remote_eligibility, drop.remote_eligibility)
    if drop.published_at and (keep.published_at is None or drop.published_at < keep.published_at):
        keep.published_at = drop.published_at
    if drop.application_deadline and (keep.application_deadline is None or drop.application_deadline < keep.application_deadline):
        keep.application_deadline = drop.application_deadline
    keep.first_seen_at = min(keep.first_seen_at, drop.first_seen_at)
    keep.last_seen_at = max(keep.last_seen_at, drop.last_seen_at)
    if drop.last_verified_at and (keep.last_verified_at is None or drop.last_verified_at > keep.last_verified_at):
        keep.last_verified_at = drop.last_verified_at
    est = set(keep.estimated_fields or [])
    if inherits_estimated_company:
        est.add("company_name")
    keep.estimated_fields = sorted(est)
    keep.content_hash = _compute_hash(keep)
    session.execute(delete(JobOffer).where(JobOffer.id == drop.id))
    session.flush()
    session.expire(keep)


# --------------------------------------------------------------------------- ingestion d'un lot
def ingest_jobs(
    session: Session,
    source: JobSource,
    jobs: list[NormalizedJob],
    profiles: list[ProfileCriteria],
    *,
    now: datetime,
) -> IngestStats:
    stats = IngestStats()
    touched: dict[int, bool] = {}  # offer_id -> company nouvellement connue (à rapprocher)
    for job in jobs:
        stats.found += 1
        try:
            with session.begin_nested():
                offer, kind, ambiguous = _ingest_one(session, source, job, profiles, now)
            stats.created += kind == "created"
            stats.updated += kind == "updated"
            stats.unchanged += kind == "unchanged"
            stats.duplicates += kind == "duplicate"
            stats.ambiguous += ambiguous
            if offer.normalized_company and kind in {"created", "updated"}:
                touched[offer.id] = True
        except IntegrityError as e:  # course/contrainte : on isole l'annonce, la collecte continue
            stats.errors += 1
            log.warning("ingestion ignorée (intégrité) source=%s url=%s : %s", source.source_key, job.url, str(e.orig)[:160])
    # rapprochement a posteriori (annonces qui viennent d'obtenir leur entreprise)
    for offer_id in list(touched):
        offer = session.get(JobOffer, offer_id)
        if offer is None:
            continue
        dup = find_identity_duplicate(session, offer)
        if dup is not None:
            keep, drop = (offer, dup) if offer.first_seen_at <= dup.first_seen_at else (dup, offer)
            merge_offers(session, keep, drop)
            rescore_offer(session, keep, profiles, now)
            stats.merged += 1
            stats.duplicates += 1
            touched.pop(drop.id, None)
    session.flush()
    return stats


def _ingest_one(
    session: Session, source: JobSource, job: NormalizedJob, profiles: list[ProfileCriteria], now: datetime
) -> tuple[JobOffer, str, bool]:
    """(annonce, nature, ambigu) ; nature ∈ created | updated | unchanged | duplicate (doublon inter-sources)."""
    key = url_key(job.url)
    alias_keys = [k for k in (url_key(u) for u in job.same_as_urls) if k != key]
    identity = build_identity(job)
    match: Match = find_match(session, source, job, url_key_=key, alias_keys=alias_keys, identity=identity)
    if match.offer is not None:
        offer = match.offer
        changed = _update_offer(offer, job, identity, now, same_source=not match.cross_source)
        kind = "duplicate" if match.cross_source else ("updated" if changed else "unchanged")
    else:
        offer = _create_offer(job, identity, now)
        session.add(offer)
        session.flush()
        kind = "created"
    _upsert_source_link(session, offer, source, job, key, now)
    _register_url_keys(session, offer, [(key, "original"), *[(k, "same_as") for k in alias_keys]])
    session.flush()
    rescore_offer(session, offer, profiles, now)
    return offer, kind, bool(match.ambiguous)


# --------------------------------------------------------------------------- statuts de cycle de vie
def refresh_offer_statuses(session: Session, now: datetime, *, stale_after_days: int = STALE_AFTER_DAYS) -> None:
    """Met à jour `source_status` des liens et `status` des annonces (jamais de suppression)."""
    for src in session.scalars(select(JobSource).where(JobSource.last_success_at.is_not(None))):
        threshold = src.last_success_at - timedelta(days=stale_after_days)
        session.execute(
            update(JobOfferSource)
            .where(JobOfferSource.job_source_id == src.id, JobOfferSource.source_status == "listed", JobOfferSource.source_last_seen_at <= threshold)
            .values(source_status="missing")
        )
        session.execute(
            update(JobOfferSource)
            .where(JobOfferSource.job_source_id == src.id, JobOfferSource.source_status == "missing", JobOfferSource.source_last_seen_at > threshold)
            .values(source_status="listed")
        )
    listed_link = exists().where(JobOfferSource.job_offer_id == JobOffer.id, JobOfferSource.source_status == "listed")
    any_link = exists().where(JobOfferSource.job_offer_id == JobOffer.id)
    open_states = (OfferStatus.LISTED.value, OfferStatus.STALE.value, OfferStatus.DEADLINE_PASSED.value)
    session.execute(
        update(JobOffer)
        .where(JobOffer.status.in_(open_states), JobOffer.application_deadline.is_not(None), JobOffer.application_deadline < now)
        .values(status=OfferStatus.DEADLINE_PASSED.value)
    )
    not_expired = (JobOffer.application_deadline.is_(None)) | (JobOffer.application_deadline >= now)
    session.execute(
        update(JobOffer)
        .where(JobOffer.status.in_(open_states), not_expired, any_link, ~listed_link)
        .values(status=OfferStatus.STALE.value)
    )
    session.execute(
        update(JobOffer)
        .where(JobOffer.status.in_((OfferStatus.STALE.value, OfferStatus.DEADLINE_PASSED.value)), not_expired, listed_link)
        .values(status=OfferStatus.LISTED.value)
    )


def known_detail_url_keys(session: Session, source: JobSource) -> set[str]:
    """url_key des annonces de cette source dont la page de détail a déjà été consultée (évite de la re-télécharger)."""
    rows = session.execute(
        select(JobOfferSource.original_url_key)
        .join(JobOffer, JobOffer.id == JobOfferSource.job_offer_id)
        .where(JobOfferSource.job_source_id == source.id, JobOffer.last_verified_at.is_not(None))
    )
    return {r[0] for r in rows}
