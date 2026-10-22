"""Exécutions de collecte : lancement asynchrone (identifiant d'exécution), liste, détail avec résultats par source."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import JobSource, SearchProfile, SearchRun, SearchRunSource, TriggerType
from ..schemas.runs import RunCreate, RunOut, RunPage, RunSourceOut
from ..services.runner import NoSourcesError, ProfileNotFound, RunService, UnknownSourceError
from .deps import get_runs, get_session

router = APIRouter(prefix="/api/search-runs", tags=["collectes"])
SessionDep = Annotated[Session, Depends(get_session)]
RunsDep = Annotated[RunService, Depends(get_runs)]


def _duration_ms(start, end) -> int | None:
    return int((end - start).total_seconds() * 1000) if start and end else None


def run_to_out(session: Session, run: SearchRun, *, with_sources: bool) -> RunOut:
    profile_name = None
    if run.profile_id:
        p = session.get(SearchProfile, run.profile_id)
        profile_name = p.name if p else None
    rows = session.execute(
        select(SearchRunSource, JobSource)
        .join(JobSource, JobSource.id == SearchRunSource.job_source_id)
        .where(SearchRunSource.search_run_id == run.id)
        .order_by(SearchRunSource.id)
    ).all()
    sources = [
        RunSourceOut(
            source_key=src.source_key,
            source_name=src.name,
            status=rs.status,
            started_at=rs.started_at,
            finished_at=rs.finished_at,
            duration_ms=_duration_ms(rs.started_at, rs.finished_at),
            offers_found=rs.offers_found,
            offers_created=rs.offers_created,
            offers_updated=rs.offers_updated,
            duplicates_detected=rs.duplicates_detected,
            offers_rejected=rs.offers_rejected,
            requests_made=rs.requests_made,
            error_type=rs.error_type,
            error_message=rs.error_message,
            details=rs.details or {},
        )
        for rs, src in rows
    ]
    return RunOut(
        id=run.id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=_duration_ms(run.started_at, run.finished_at),
        trigger_type=run.trigger_type,
        status=run.status,
        profile_id=run.profile_id,
        profile_name=profile_name,
        sources_requested=run.sources_requested,
        sources_succeeded=run.sources_succeeded,
        sources_failed=run.sources_failed,
        offers_found=run.offers_found,
        offers_created=run.offers_created,
        offers_updated=run.offers_updated,
        duplicates_detected=run.duplicates_detected,
        error_summary=run.error_summary,
        sources=sources if with_sources else [],
        source_keys=[s.source_key for s in sources],
    )


@router.post("", status_code=202)
async def create_search_run(body: RunCreate, runs: RunsDep) -> dict[str, object]:
    """Crée l'exécution et rend la main immédiatement ; suivre l'avancement avec GET /api/search-runs/{id}."""
    active = await run_in_threadpool(runs.active_run_id)
    if active is not None:
        raise HTTPException(409, detail={"message": f"une collecte est déjà en cours (exécution {active})", "active_run_id": active})
    try:
        run_id = await run_in_threadpool(
            runs.create_run, trigger=TriggerType.MANUAL, profile_id=body.profile_id, source_keys=body.source_keys
        )
    except ProfileNotFound as e:
        raise HTTPException(404, str(e)) from e
    except UnknownSourceError as e:
        raise HTTPException(400, str(e)) from e
    except NoSourcesError as e:
        raise HTTPException(409, str(e)) from e
    runs.spawn(run_id)
    return {"id": run_id, "status": "queued"}


@router.get("", response_model=RunPage)
def list_runs(session: SessionDep, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100)) -> RunPage:
    total = session.scalar(select(func.count(SearchRun.id))) or 0
    runs = session.scalars(select(SearchRun).order_by(SearchRun.id.desc()).limit(page_size).offset((page - 1) * page_size)).all()
    return RunPage(items=[run_to_out(session, r, with_sources=True) for r in runs], total=total, page=page, page_size=page_size)


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: int, session: SessionDep) -> RunOut:
    run = session.get(SearchRun, run_id)
    if run is None:
        raise HTTPException(404, "exécution introuvable")
    return run_to_out(session, run, with_sources=True)
