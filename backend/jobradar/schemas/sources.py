"""Schémas des sources et du registre des employeurs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator


class SourceOut(BaseModel):
    key: str
    name: str
    base_url: str
    source_type: str
    market: str
    countries: list[str]
    enabled: bool
    collection_method: str
    verification_status: str
    implementation: str
    can_collect: bool  # un connecteur existe
    decision_reason: str | None
    tos_note: str | None
    doc_status: str | None
    state: str  # active | disabled | to_verify | unreachable | error | excluded
    state_label: str
    last_checked_at: datetime | None
    last_check_ok: bool | None
    last_success_at: datetime | None
    last_run_at: datetime | None
    last_run_status: str | None
    last_error: str | None
    last_error_type: str | None
    offers_count: int  # annonces rattachées à cette source
    errors_count: int  # collectes en échec
    last_run_offers_found: int | None
    min_interval_minutes: int | None
    configuration: dict[str, Any]


class SourceToggle(BaseModel):
    enabled: bool


class SourceTestOut(BaseModel):
    ok: bool
    status: str
    detail: str
    http_status: int | None = None
    latency_ms: int | None = None
    sample_count: int | None = None
    checked_at: datetime


class EmployerOut(BaseModel):
    key: str
    name: str
    sector: str | None = None
    country: str | None = None
    website: str | None = None
    career_url: str | None = None
    collection_method: str = "none"
    source_key: str | None = None
    status: str = "unverified"
    checked_on: str | None = None
    verification_note: str | None = None

    @field_validator("checked_on", mode="before")
    @classmethod
    def _date_to_str(cls, v: Any) -> Any:
        return v.isoformat() if hasattr(v, "isoformat") else v
