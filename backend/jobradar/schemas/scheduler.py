"""Schémas de la veille automatique."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SchedulerOut(BaseModel):
    enabled: bool
    interval_minutes: int
    profile_ids: list[int] | None
    source_keys: list[str] | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_run_id: int | None
    last_run_status: str | None = None
    last_error: str | None
    alive: bool  # un processus bat réellement le rappel
    state: str  # disabled | running | stopped
    heartbeat_at: datetime | None
    mode: str
    this_process_is_leader: bool
    min_interval_minutes: int
    max_interval_minutes: int


class SchedulerUpdate(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=30, le=10080)
    profile_ids: list[int] | None = None
    source_keys: list[str] | None = None
