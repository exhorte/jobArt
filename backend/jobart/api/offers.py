"""Annonces : liste filtrable, détail, suivi utilisateur, ajout manuel (sans jamais visiter l'URL fournie)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..collectors.base import NormalizedJob
from ..core.clock import utcnow
from ..core.errors import NormalizationError
from ..models import JobOffer, JobOfferSource, JobSource, SavedJob, SearchProfile, UserStatus
from ..schemas.offers import ManualOfferCreate, OfferDetail, OfferPage, OfferStatusUpdate
from ..services.enrich import detect_experience_level
from ..services.geo import parse_location
from ..services.ingest import ingest_jobs
from ..services.scoring import ProfileCriteria
from ..services.text import html_to_text
from ..services.urls import host_of, url_key, validate_job_url
from ..services.views import OfferFilters, build_offer_query, offer_detail, to_list_items
from .deps import get_session

router = APIRouter(prefix="/api/offers", tags=["annonces"])
SessionDep = Annotated[Session, Depends(get_session)]
MultiStr = Annotated[list[str] | None, Query()]


@router.get("", response_model=OfferPage)
def list_offers(
    session: SessionDep,
    q: str | None = Query(default=None, max_length=200, description="mots-clés (titre, entreprise, description)"),
    country: str | None = Query(default=None, min_length=2, max_length=2),
    city: str | None = None,
    source: MultiStr = None,
    company: str | None = None,
    contract_type: MultiStr = None,
    work_mode: MultiStr = None,
    status: MultiStr = None,
    lifecycle: MultiStr = None,
    remote_eligibility: MultiStr = None,
    profile_id: int | None = None,
    min_score: float | None = Query(default=None, ge=0, le=100),
    max_score: float | None = Query(default=None, ge=0, le=100),
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    first_seen_from: datetime | None = None,
    first_seen_to: datetime | None = None,
    include_ignored: bool = False,
    sort: Literal["recent", "relevance", "company", "detected"] = "recent",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> OfferPage:
    if profile_id is not None and session.get(SearchProfile, profile_id) is None:
        raise HTTPException(404, "profil introuvable")
    bad_status = [s for s in (status or []) if s not in {u.value for u in UserStatus}]
    if bad_status:
        raise HTTPException(422, f"statut invalide : {', '.join(bad_status)}")
    f = OfferFilters(
        q=q, country=country, city=city, sources=source or [], company=company, contract_types=contract_type or [],
        work_modes=work_mode or [], user_statuses=status or [], lifecycle=lifecycle or [],
        remote_eligibility=remote_eligibility or [], profile_id=profile_id, min_score=min_score, max_score=max_score,
        published_from=published_from, published_to=published_to, first_seen_from=first_seen_from,
        first_seen_to=first_seen_to, include_ignored=include_ignored, sort=sort, order=order,
    )
    stmt = build_offer_query(f)
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).with_only_columns(JobOffer.id).subquery())) or 0
    rows = session.execute(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    items = to_list_items(session, [(o, s, u) for o, s, u in rows], now=utcnow(), profile_id=profile_id)
    return OfferPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{offer_id}", response_model=OfferDetail)
def get_offer(offer_id: int, session: SessionDep) -> OfferDetail:
    offer = session.get(JobOffer, offer_id)
    if offer is None:
        raise HTTPException(404, "annonce introuvable")
    return offer_detail(session, offer, now=utcnow())


@router.patch("/{offer_id}/status", response_model=OfferDetail)
def update_offer_status(offer_id: int, body: OfferStatusUpdate, session: SessionDep) -> OfferDetail:
    offer = session.get(JobOffer, offer_id)
    if offer is None:
        raise HTTPException(404, "annonce introuvable")
    if body.user_status is None and body.notes is None and "notes" not in body.model_fields_set:
        raise HTTPException(422, "rien à modifier : fournir user_status et/ou notes")
    saved = session.get(SavedJob, offer_id)
    now = utcnow()
    if saved is None:
        saved = SavedJob(job_offer_id=offer_id, user_status=UserStatus.NEW.value)
        session.add(saved)
    if body.user_status is not None:
        saved.user_status = body.user_status
        if body.user_status == UserStatus.SAVED.value and saved.saved_at is None:
            saved.saved_at = now
    if "notes" in body.model_fields_set:
        saved.notes = body.notes or None
    saved.updated_at = now
    session.flush()
    session.expire(offer)
    return offer_detail(session, offer, now=now)


@router.post("/manual", response_model=OfferDetail, status_code=201)
def add_manual_offer(body: ManualOfferCreate, session: SessionDep) -> OfferDetail:
    """Enregistre une annonce saisie par l'utilisateur (ex. trouvée sur LinkedIn). Aucune requête n'est émise vers l'URL."""
    source = session.scalar(select(JobSource).where(JobSource.source_key == "manual"))
    if source is None:
        raise HTTPException(500, "source « manuel » absente : relancer l'initialisation")
    try:
        url = validate_job_url(body.url, allowed_hosts={host_of(body.url)})
    except NormalizationError as e:
        raise HTTPException(422, str(e)) from e
    city, country = parse_location(body.location)
    description = html_to_text(body.description) if body.description else None
    now = utcnow()
    job = NormalizedJob(
        source_key="manual", source_job_id=None, url=url, title=body.title, company_name=body.company_name,
        description=description, location=body.location, city=city, country=country,
        work_mode=body.work_mode, contract_type=body.contract_type, experience_level=detect_experience_level(body.title, description),
        raw_metadata={"entered_manually": True},
    )
    profiles = [ProfileCriteria.from_model(p) for p in session.scalars(select(SearchProfile).where(SearchProfile.is_active.is_(True)))]
    ingest_jobs(session, source, [job], profiles, now=now)
    offer = session.scalar(select(JobOffer).where(JobOffer.canonical_url == url))
    if offer is None:  # rapproché d'une annonce existante par URL/identité
        link = session.scalar(select(JobOfferSource).where(JobOfferSource.job_source_id == source.id, JobOfferSource.original_url_key == url_key(url)))
        offer = link.offer if link else None
    if offer is None:
        raise HTTPException(500, "annonce non enregistrée")
    if body.notes and session.get(SavedJob, offer.id) is None:  # ne jamais écraser le suivi déjà saisi
        session.add(SavedJob(job_offer_id=offer.id, user_status=UserStatus.NEW.value, notes=body.notes))
    session.flush()
    return offer_detail(session, offer, now=now)
