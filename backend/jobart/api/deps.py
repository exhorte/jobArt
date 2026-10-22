"""Dépendances FastAPI : session SQLAlchemy par requête, services partagés."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from ..core.db import Database
from ..jobs.scheduler import SchedulerService
from ..services.runner import RunService


def get_session(request: Request) -> Iterator[Session]:
    db: Database = request.app.state.db
    session = db.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_runs(request: Request) -> RunService:
    return request.app.state.runs


def get_scheduler(request: Request) -> SchedulerService:
    return request.app.state.scheduler
