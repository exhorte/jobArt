"""Santé, métadonnées de formulaires et tableau de bord."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import __version__
from ..core.clock import utcnow
from ..jobs.scheduler import SchedulerService
from ..models import OfferStatus, UserStatus
from ..services.enrich import CONTRACT_VALUES, EXPERIENCE_LEVELS, SECTORS
from ..services.geo import COUNTRY_LABELS
from ..services.scoring import COMPONENT_LABELS, DEFAULT_WEIGHTS
from ..services.views import dashboard as build_dashboard
from .deps import get_scheduler, get_session

router = APIRouter(prefix="/api", tags=["système"])
SessionDep = Annotated[Session, Depends(get_session)]
SchedulerDep = Annotated[SchedulerService, Depends(get_scheduler)]


@router.get("/health")
def health(request: Request, session: SessionDep, scheduler: SchedulerDep) -> dict[str, Any]:
    try:
        session.execute(select(text("1")))
        db_status = "ok"
    except Exception as e:  # pragma: no cover - dépend de l'infrastructure
        db_status = f"erreur : {type(e).__name__}"
    sched = scheduler.status()
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "version": __version__,
        "database": db_status,
        "scheduler": {"state": sched["state"], "alive": sched["alive"], "mode": sched["mode"]},
        "time": utcnow(),
    }


@router.get("/meta")
def meta() -> dict[str, Any]:
    """Valeurs autorisées pour les formulaires (profils, filtres)."""
    return {
        "contract_types": list(CONTRACT_VALUES),
        "work_modes": ["onsite", "hybrid", "remote"],
        "experience_levels": list(EXPERIENCE_LEVELS),
        "user_statuses": [s.value for s in UserStatus],
        "lifecycle_statuses": [s.value for s in OfferStatus],
        "countries": COUNTRY_LABELS,
        "sectors": {k: v[0] for k, v in SECTORS.items()},
        "weights": {"default": DEFAULT_WEIGHTS, "labels": COMPONENT_LABELS},
    }


@router.get("/dashboard")
def dashboard(session: SessionDep, scheduler: SchedulerDep) -> dict[str, Any]:
    return build_dashboard(session, now=utcnow(), scheduler=scheduler.status())
