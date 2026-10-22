"""Schémas des exécutions de collecte."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RunCreate(BaseModel):
    profile_id: int | None = None
    source_keys: list[str] | None = Field(default=None, max_length=50)


class RunSourceOut(BaseModel):
    source_key: str
    source_name: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    offers_found: int
    offers_created: int
    offers_updated: int
    duplicates_detected: int
    offers_rejected: int
    requests_made: int
    error_type: str | None
    error_message: str | None
    details: dict[str, Any]


class RunOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    trigger_type: str
    status: str
    profile_id: int | None
    profile_name: str | None
    sources_requested: int
    sources_succeeded: int
    sources_failed: int
    offers_found: int
    offers_created: int
    offers_updated: int
    duplicates_detected: int
    error_summary: str | None
    sources: list[RunSourceOut] = Field(default_factory=list)
    source_keys: list[str] = Field(default_factory=list)


class RunPage(BaseModel):
    items: list[RunOut]
    total: int
    page: int
    page_size: int
