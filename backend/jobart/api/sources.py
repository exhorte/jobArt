"""Sources : liste, activation, test (sans enregistrement), collecte ciblée ; registre des employeurs.

Aucun endpoint n'accepte d'URL fournie par le client : seules les sources/connecteurs enregistrés sont exécutables.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.clock import utcnow
from ..core.config import get_settings
from ..models import JobSource, TriggerType
from ..schemas.sources import EmployerOut, SourceOut, SourceTestOut, SourceToggle
from ..services.bootstrap import load_employers
from ..services.runner import NoSourcesError, RunService, UnknownSourceError
from ..services.views import source_to_out
from .deps import get_runs, get_session

router = APIRouter(prefix="/api", tags=["sources"])
SessionDep = Annotated[Session, Depends(get_session)]
RunsDep = Annotated[RunService, Depends(get_runs)]


def _get_source(session: Session, key: str) -> JobSource:
    src = session.scalar(select(JobSource).where(JobSource.source_key == key))
    if src is None:
        raise HTTPException(404, f"source inconnue : {key}")
    return src


@router.get("/sources", response_model=list[SourceOut])
def list_sources(session: SessionDep) -> list[SourceOut]:
    return [source_to_out(session, s) for s in session.scalars(select(JobSource).order_by(JobSource.id))]


@router.get("/sources/{source_key}", response_model=SourceOut)
def get_source(source_key: str, session: SessionDep) -> SourceOut:
    return source_to_out(session, _get_source(session, source_key))


@router.patch("/sources/{source_key}", response_model=SourceOut)
def toggle_source(source_key: str, body: SourceToggle, session: SessionDep) -> SourceOut:
    src = _get_source(session, source_key)
    if body.enabled and src.implementation != "implemented":
        raise HTTPException(409, "cette source n'a pas de connecteur : elle ne peut pas être activée (voir la raison affichée)")
    src.enabled = body.enabled
    session.flush()
    return source_to_out(session, src)


@router.post("/sources/{source_key}/test", response_model=SourceTestOut)
async def test_source(source_key: str, runs: RunsDep) -> SourceTestOut:
    """Vérifie l'accessibilité de la source (une requête) sans rien enregistrer."""
    try:
        result = await runs.test_source(source_key)
    except UnknownSourceError as e:
        raise HTTPException(404 if "inconnue" in str(e) else 409, str(e)) from e
    return SourceTestOut(**result.model_dump(), checked_at=utcnow())


@router.post("/sources/{source_key}/collect", status_code=202)
async def collect_source(source_key: str, request: Request, runs: RunsDep) -> dict[str, object]:
    """Lance une collecte sur cette seule source (exécution asynchrone : suivre via GET /api/search-runs/{id})."""
    active = await run_in_threadpool(runs.active_run_id)
    if active is not None:
        raise HTTPException(409, f"une collecte est déjà en cours (exécution {active})")
    try:
        run_id = await run_in_threadpool(runs.create_run, trigger=TriggerType.MANUAL, source_keys=[source_key])
    except UnknownSourceError as e:
        raise HTTPException(404 if "inconnue" in str(e) else 409, str(e)) from e
    except NoSourcesError as e:
        raise HTTPException(409, str(e)) from e
    runs.spawn(run_id)
    return {"id": run_id, "status": "queued"}


@router.get("/employers", response_model=list[EmployerOut])
def list_employers() -> list[EmployerOut]:
    """Registre des employeurs cibles (config/employers.yaml) avec le résultat de vérification des URLs."""
    return [EmployerOut(**e) for e in load_employers(get_settings().employers_config_path)]
