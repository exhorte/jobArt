"""Schémas des annonces."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

UserStatusLiteral = Literal["new", "seen", "saved", "applied", "ignored"]


class OfferSourceOut(BaseModel):
    source_key: str
    source_name: str
    original_url: str
    source_job_id: str | None
    published_at: datetime | None  # date déclarée par CETTE source
    first_seen_at: datetime
    last_seen_at: datetime
    status: str  # listed | missing | closed
    published_text: str | None = None  # date relative affichée par la source, non convertie
    attribution: str | None = None  # mention de source imposée par certaines API
    same_as_urls: list[str] = Field(default_factory=list)


class FreshnessOut(BaseModel):
    age_days: int | None  # d'après la date de publication DÉCLARÉE uniquement
    label: str  # fresh | recent | old | unknown_date
    first_seen_age_days: int


class OfferListItem(BaseModel):
    id: int
    title: str
    company_name: str | None
    location: str | None
    country: str | None
    city: str | None
    work_mode: str | None
    contract_type: str | None
    experience_level: str | None
    published_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    application_deadline: datetime | None
    lifecycle_status: str
    freshness: FreshnessOut
    score: float | None
    score_profile_id: int | None
    score_profile_name: str | None
    user_status: str
    primary_url: str
    sources: list[dict[str, str]]  # [{key, name, url}]
    estimated_fields: list[str]
    remote_eligibility: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_period: str | None


class ScoreOut(BaseModel):
    profile_id: int
    profile_name: str
    score: float
    breakdown: dict[str, Any]
    explanation: dict[str, Any]
    computed_at: datetime


class OfferDetail(OfferListItem):
    description: str | None
    sector: str | None
    remote_regions: list[str]
    last_verified_at: datetime | None
    notes: str | None
    saved_at: datetime | None
    source_links: list[OfferSourceOut]
    scores: list[ScoreOut]
    content_hash: str


class OfferPage(BaseModel):
    items: list[OfferListItem]
    total: int
    page: int
    page_size: int


class OfferStatusUpdate(BaseModel):
    user_status: UserStatusLiteral | None = None
    notes: str | None = Field(default=None, max_length=5000)


class ManualOfferCreate(BaseModel):
    """Ajout manuel d'une annonce (LinkedIn, source bloquée...). Le serveur ne visite JAMAIS l'URL."""

    url: str = Field(min_length=8, max_length=1000)
    title: str = Field(min_length=2, max_length=300)
    company_name: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    contract_type: str | None = None
    work_mode: Literal["onsite", "hybrid", "remote"] | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("l'URL doit commencer par http:// ou https://")
        return v

    @field_validator("title", "company_name", "location")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return " ".join(v.split()) if v else v
