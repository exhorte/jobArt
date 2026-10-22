"""Profils de recherche : CRUD, duplication, activation. Toute modification recalcule les scores en arrière-plan."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.clock import utcnow
from ..core.db import Database
from ..models import SearchProfile
from ..schemas.profiles import ProfileCreate, ProfileOut, ProfileUpdate
from ..services.ingest import rescore_all
from ..services.scoring import ProfileCriteria
from .deps import get_session

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search-profiles", tags=["profils"])
SessionDep = Annotated[Session, Depends(get_session)]


def _out(p: SearchProfile) -> ProfileOut:
    out = ProfileOut.model_validate(p)
    out.effective_weights = ProfileCriteria.from_model(p).effective_weights()
    return out


def _rescore_in_background(db: Database) -> None:
    try:
        with db.session() as s:
            profiles = [ProfileCriteria.from_model(p) for p in s.scalars(select(SearchProfile).where(SearchProfile.is_active.is_(True)))]
            n = rescore_all(s, profiles, utcnow())
        log.info("scores recalculés pour %s annonce(s)", n)
    except Exception:  # pragma: no cover
        log.exception("échec du recalcul des scores")


def _get(session: Session, profile_id: int) -> SearchProfile:
    p = session.get(SearchProfile, profile_id)
    if p is None:
        raise HTTPException(404, "profil introuvable")
    return p


@router.get("", response_model=list[ProfileOut])
def list_profiles(session: SessionDep) -> list[ProfileOut]:
    return [_out(p) for p in session.scalars(select(SearchProfile).order_by(SearchProfile.id))]


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(profile_id: int, session: SessionDep) -> ProfileOut:
    return _out(_get(session, profile_id))


@router.post("", response_model=ProfileOut, status_code=201)
def create_profile(body: ProfileCreate, session: SessionDep, request: Request, tasks: BackgroundTasks) -> ProfileOut:
    if session.scalar(select(SearchProfile.id).where(SearchProfile.name == body.name)):
        raise HTTPException(409, "un profil porte déjà ce nom")
    p = SearchProfile(**body.model_dump())
    session.add(p)
    try:
        session.flush()
    except IntegrityError as e:
        raise HTTPException(409, "un profil porte déjà ce nom") from e
    session.commit()
    tasks.add_task(_rescore_in_background, request.app.state.db)
    return _out(p)


@router.patch("/{profile_id}", response_model=ProfileOut)
def update_profile(profile_id: int, body: ProfileUpdate, session: SessionDep, request: Request, tasks: BackgroundTasks) -> ProfileOut:
    p = _get(session, profile_id)
    try:
        changes = body.validated()
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if "name" in changes and changes["name"] != p.name and session.scalar(select(SearchProfile.id).where(SearchProfile.name == changes["name"])):
        raise HTTPException(409, "un profil porte déjà ce nom")
    for k, v in changes.items():
        setattr(p, k, v)
    session.flush()
    session.commit()
    tasks.add_task(_rescore_in_background, request.app.state.db)
    return _out(p)


@router.post("/{profile_id}/duplicate", response_model=ProfileOut, status_code=201)
def duplicate_profile(profile_id: int, session: SessionDep, request: Request, tasks: BackgroundTasks) -> ProfileOut:
    src = _get(session, profile_id)
    existing = set(session.scalars(select(SearchProfile.name)))
    name, n = f"{src.name} (copie)", 2
    while name in existing:
        name, n = f"{src.name} (copie {n})", n + 1
    p = SearchProfile(
        name=name, description=src.description, countries=list(src.countries), cities=list(src.cities),
        positive_keywords=list(src.positive_keywords), keyword_groups={k: list(v) for k, v in (src.keyword_groups or {}).items()},
        excluded_keywords=list(src.excluded_keywords), target_roles=list(src.target_roles), sectors=list(src.sectors),
        contract_types=list(src.contract_types), work_modes=list(src.work_modes), experience_levels=list(src.experience_levels),
        weights=dict(src.weights) if src.weights else None, is_active=False,  # la copie démarre désactivée
    )
    session.add(p)
    session.flush()
    session.commit()
    tasks.add_task(_rescore_in_background, request.app.state.db)
    return _out(p)


@router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: int, session: SessionDep, request: Request, tasks: BackgroundTasks) -> None:
    p = _get(session, profile_id)
    session.delete(p)
    session.flush()
    session.commit()
    tasks.add_task(_rescore_in_background, request.app.state.db)
