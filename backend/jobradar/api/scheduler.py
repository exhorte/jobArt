"""Réglages et état réel de la veille automatique."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collectors.registry import CONNECTORS
from ..jobs.scheduler import _UNSET, MAX_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES, SchedulerService
from ..models import JobSource, SearchProfile, SearchRun
from ..schemas.scheduler import SchedulerOut, SchedulerUpdate
from .deps import get_scheduler, get_session

router = APIRouter(prefix="/api/settings/scheduler", tags=["veille"])
SessionDep = Annotated[Session, Depends(get_session)]
SchedulerDep = Annotated[SchedulerService, Depends(get_scheduler)]


def _out(session: Session, sched: SchedulerService) -> SchedulerOut:
    st = sched.status()
    last_status = None
    if st["last_run_id"]:
        run = session.get(SearchRun, st["last_run_id"])
        last_status = run.status if run else None
    return SchedulerOut(**st, last_run_status=last_status, min_interval_minutes=MIN_INTERVAL_MINUTES, max_interval_minutes=MAX_INTERVAL_MINUTES)


@router.get("", response_model=SchedulerOut)
def get_scheduler_settings(session: SessionDep, sched: SchedulerDep) -> SchedulerOut:
    return _out(session, sched)


@router.patch("", response_model=SchedulerOut)
def update_scheduler_settings(body: SchedulerUpdate, session: SessionDep, sched: SchedulerDep) -> SchedulerOut:
    sent = body.model_fields_set
    if body.profile_ids:
        found = set(session.scalars(select(SearchProfile.id).where(SearchProfile.id.in_(body.profile_ids))))
        missing = [i for i in body.profile_ids if i not in found]
        if missing:
            raise HTTPException(404, f"profil(s) introuvable(s) : {missing}")
    if body.source_keys:
        impl = set(session.scalars(select(JobSource.source_key).where(JobSource.source_key.in_(body.source_keys), JobSource.implementation == "implemented")))
        bad = [k for k in body.source_keys if k not in impl or k not in CONNECTORS]
        if bad:
            raise HTTPException(400, f"source(s) sans connecteur : {bad}")
    sched.update_settings(
        enabled=body.enabled,
        interval_minutes=body.interval_minutes,
        profile_ids=body.profile_ids if "profile_ids" in sent else _UNSET,
        source_keys=body.source_keys if "source_keys" in sent else _UNSET,
    )
    return _out(session, sched)
