"""Modèle relationnel jobArt (SQLAlchemy 2.0).

Types portables : JSON (JSONB sous PostgreSQL), datetimes toujours UTC et « aware ».
Les champs inconnus restent NULL : on ne fabrique jamais une date, une entreprise, un salaire ou une URL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

JsonType = JSON().with_variant(JSONB(), "postgresql")


class UTCDateTime(TypeDecorator):
    """DateTime(timezone=True) qui refuse les datetimes naïfs et renvoie toujours de l'UTC aware."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime naïf interdit : utiliser des datetimes aware (UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:  # SQLite renvoie des datetimes naïfs
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


# --------------------------------------------------------------------------- énumérations (stockées en texte)
class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"  # toutes les sources ont réussi (zéro résultat compris)
    PARTIAL = "partial"  # au moins une source en échec, au moins une réussie
    FAILED = "failed"  # aucune source n'a réussi
    INTERRUPTED = "interrupted"  # processus arrêté pendant la collecte


class RunSourceStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class TriggerType(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class OfferStatus(StrEnum):
    """Cycle de vie observé (jamais « active » : une URL qui répond ne prouve pas que l'offre est ouverte)."""

    LISTED = "listed"  # vue lors de la dernière observation de sa source
    STALE = "stale"  # plus vue depuis longtemps, sans date limite
    DEADLINE_PASSED = "deadline_passed"  # date limite dépassée : potentiellement expirée
    CLOSED = "closed"  # la source indique explicitement qu'elle est clôturée


class UserStatus(StrEnum):
    NEW = "new"
    SEEN = "seen"
    SAVED = "saved"
    APPLIED = "applied"
    IGNORED = "ignored"


class SourceType(StrEnum):
    JOB_BOARD = "job_board"
    AGGREGATOR = "aggregator"
    EMPLOYER = "employer_career"
    API = "api"
    NEWSLETTER = "newsletter"
    MANUAL = "manual"


# --------------------------------------------------------------------------- profils
class SearchProfile(Base):
    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    countries: Mapped[list[str]] = mapped_column(JsonType, default=list)  # ISO 3166-1 alpha-2
    cities: Mapped[list[str]] = mapped_column(JsonType, default=list)  # la 1re = ville prioritaire
    positive_keywords: Mapped[list[str]] = mapped_column(JsonType, default=list)
    # Groupes de compétences/termes techniques (ex. {"Langages": ["Python"], "IA": ["LLM", "RAG"]}).
    keyword_groups: Mapped[dict[str, list[str]]] = mapped_column(JsonType, default=dict)
    excluded_keywords: Mapped[list[str]] = mapped_column(JsonType, default=list)
    target_roles: Mapped[list[str]] = mapped_column(JsonType, default=list)
    sectors: Mapped[list[str]] = mapped_column(JsonType, default=list)
    contract_types: Mapped[list[str]] = mapped_column(JsonType, default=list)
    work_modes: Mapped[list[str]] = mapped_column(JsonType, default=list)
    experience_levels: Mapped[list[str]] = mapped_column(JsonType, default=list)
    weights: Mapped[dict[str, float] | None] = mapped_column(JsonType)  # surcharge des pondérations
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)


# --------------------------------------------------------------------------- sources
class JobSource(Base):
    __tablename__ = "job_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    base_url: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(String(40))
    market: Mapped[str] = mapped_column(String(20), default="local")  # local | remote
    countries: Mapped[list[str]] = mapped_column(JsonType, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    collection_method: Mapped[str] = mapped_column(String(60))
    # verified | probable | to_verify | inaccessible | excluded (observation, voir docs/source-feasibility.md)
    verification_status: Mapped[str] = mapped_column(String(30), default="to_verify")
    implementation: Mapped[str] = mapped_column(String(20), default="deferred")  # implemented|deferred|excluded
    decision_reason: Mapped[str | None] = mapped_column(Text)
    tos_note: Mapped[str | None] = mapped_column(Text)
    doc_status: Mapped[str | None] = mapped_column(Text)  # statut dans la cartographie du 14/10/2026
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_run_status: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_type: Mapped[str | None] = mapped_column(String(40))
    configuration: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)  # jamais de secret
    # Verrou inter-processus (une seule collecte à la fois par source)
    lock_owner: Mapped[str | None] = mapped_column(String(80))
    lock_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)


# --------------------------------------------------------------------------- annonces
class JobOffer(Base):
    __tablename__ = "job_offers"
    __table_args__ = (
        Index("ix_job_offers_identity", "normalized_company", "normalized_title"),
        Index("ix_job_offers_published_at", "published_at"),
        Index("ix_job_offers_first_seen_at", "first_seen_at"),
        Index("ix_job_offers_country_city", "country", "city"),
        Index("ix_job_offers_best_score", "best_score"),
        Index("ix_job_offers_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_url: Mapped[str] = mapped_column(String(1024), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    normalized_title: Mapped[str] = mapped_column(String(500))
    company_name: Mapped[str | None] = mapped_column(String(300))
    normalized_company: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)  # texte brut, non fiable (jamais interprété)
    location: Mapped[str | None] = mapped_column(String(300))
    country: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(120))
    work_mode: Mapped[str | None] = mapped_column(String(20))
    contract_type: Mapped[str | None] = mapped_column(String(30))
    experience_level: Mapped[str | None] = mapped_column(String(20))
    sector: Mapped[str | None] = mapped_column(String(80))
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_currency: Mapped[str | None] = mapped_column(String(8))
    salary_period: Mapped[str | None] = mapped_column(String(12))  # hourly | daily | monthly | yearly (si déclaré)
    remote_eligibility: Mapped[str | None] = mapped_column(String(20))  # eligible | restricted | unknown
    remote_regions: Mapped[list[str]] = mapped_column(JsonType, default=list)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # déclarée par la source, sinon NULL
    application_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(20), default=OfferStatus.LISTED.value)
    content_hash: Mapped[str] = mapped_column(String(64))
    # Champs dont la valeur est une estimation/dérivation (ex. entreprise extraite d'un titre)
    estimated_fields: Mapped[list[str]] = mapped_column(JsonType, default=list)
    best_score: Mapped[float | None] = mapped_column(Float)
    best_profile_id: Mapped[int | None] = mapped_column(ForeignKey("search_profiles.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)

    sources: Mapped[list[JobOfferSource]] = relationship(
        back_populates="offer", cascade="all, delete-orphan", order_by="JobOfferSource.id"
    )
    scores: Mapped[list[OfferScore]] = relationship(back_populates="offer", cascade="all, delete-orphan")
    saved: Mapped[SavedJob | None] = relationship(back_populates="offer", uselist=False, cascade="all, delete-orphan")


class JobOfferSource(Base):
    __tablename__ = "job_offer_sources"
    __table_args__ = (
        UniqueConstraint("job_source_id", "original_url_key", name="uq_job_offer_sources_source_url"),
        UniqueConstraint("job_source_id", "source_job_id", name="uq_job_offer_sources_source_jobid"),
        Index("ix_job_offer_sources_offer", "job_offer_id"),
        Index("ix_job_offer_sources_seen", "job_source_id", "source_last_seen_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_offer_id: Mapped[int] = mapped_column(ForeignKey("job_offers.id", ondelete="CASCADE"))
    job_source_id: Mapped[int] = mapped_column(ForeignKey("job_sources.id", ondelete="CASCADE"))
    original_url: Mapped[str] = mapped_column(String(1024))
    original_url_key: Mapped[str] = mapped_column(String(1024))  # clé de comparaison (voir services/urls.py)
    source_job_id: Mapped[str | None] = mapped_column(String(200))
    source_published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source_first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    source_last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    source_status: Mapped[str] = mapped_column(String(20), default="listed")  # listed | missing | closed
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

    offer: Mapped[JobOffer] = relationship(back_populates="sources")
    source: Mapped[JobSource] = relationship()


class OfferUrlKey(Base):
    """Toutes les URLs connues d'une annonce (originales + `sameAs` déclarées) : déduplication par URL en 1 requête."""

    __tablename__ = "offer_url_keys"

    url_key: Mapped[str] = mapped_column(String(1024), primary_key=True)
    job_offer_id: Mapped[int] = mapped_column(ForeignKey("job_offers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12), default="original")  # original | same_as


class OfferScore(Base):
    __tablename__ = "offer_scores"
    __table_args__ = (UniqueConstraint("job_offer_id", "profile_id", name="uq_offer_scores_offer_profile"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_offer_id: Mapped[int] = mapped_column(ForeignKey("job_offers.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("search_profiles.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    explanation: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)

    offer: Mapped[JobOffer] = relationship(back_populates="scores")


class SavedJob(Base):
    """Suivi mono-utilisateur : une ligne par annonce dès que l'utilisateur change son statut ou ajoute une note."""

    __tablename__ = "saved_jobs"

    job_offer_id: Mapped[int] = mapped_column(ForeignKey("job_offers.id", ondelete="CASCADE"), primary_key=True)
    user_status: Mapped[str] = mapped_column(String(20), default=UserStatus.NEW.value)
    notes: Mapped[str | None] = mapped_column(Text)
    saved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)

    offer: Mapped[JobOffer] = relationship(back_populates="saved")


# --------------------------------------------------------------------------- exécutions
class SearchRun(Base):
    __tablename__ = "search_runs"
    __table_args__ = (Index("ix_search_runs_started_at", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    trigger_type: Mapped[str] = mapped_column(String(20), default=TriggerType.MANUAL.value)
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.QUEUED.value)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("search_profiles.id", ondelete="SET NULL"))
    owner: Mapped[str | None] = mapped_column(String(80))  # identifiant du processus porteur
    requested_source_keys: Mapped[list[str] | None] = mapped_column(JsonType)
    sources_requested: Mapped[int] = mapped_column(Integer, default=0)
    sources_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    sources_failed: Mapped[int] = mapped_column(Integer, default=0)
    offers_found: Mapped[int] = mapped_column(Integer, default=0)
    offers_created: Mapped[int] = mapped_column(Integer, default=0)
    offers_updated: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_detected: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)

    source_results: Mapped[list[SearchRunSource]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="SearchRunSource.id"
    )


class SearchRunSource(Base):
    __tablename__ = "search_run_sources"
    __table_args__ = (UniqueConstraint("search_run_id", "job_source_id", name="uq_search_run_sources_run_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_run_id: Mapped[int] = mapped_column(ForeignKey("search_runs.id", ondelete="CASCADE"), index=True)
    job_source_id: Mapped[int] = mapped_column(ForeignKey("job_sources.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=RunSourceStatus.PENDING.value)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    offers_found: Mapped[int] = mapped_column(Integer, default=0)
    offers_created: Mapped[int] = mapped_column(Integer, default=0)
    offers_updated: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_detected: Mapped[int] = mapped_column(Integer, default=0)
    offers_rejected: Mapped[int] = mapped_column(Integer, default=0)  # rejetées à la normalisation
    requests_made: Mapped[int] = mapped_column(Integer, default=0)
    error_type: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)

    run: Mapped[SearchRun] = relationship(back_populates="source_results")
    source: Mapped[JobSource] = relationship()


# --------------------------------------------------------------------------- planificateur
class SchedulerState(Base):
    """Ligne unique (id=1) : réglages persistants de la veille + bail du planificateur."""

    __tablename__ = "scheduler_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    profile_ids: Mapped[list[int] | None] = mapped_column(JsonType)  # NULL = tous les profils actifs
    source_keys: Mapped[list[str] | None] = mapped_column(JsonType)  # NULL = toutes les sources activées
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_run_id: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(String(80))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)
