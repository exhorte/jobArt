"""Configuration applicative (variables d'environnement / .env). Aucun secret n'est codé en dur."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/jobradar/core/config.py -> racine du dépôt = parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://jobradar:jobradar@127.0.0.1:54330/jobradar"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    config_dir: Path = REPO_ROOT / "config"

    # "embedded" : l'API héberge le planificateur ; "off" : un worker séparé le porte.
    scheduler_mode: str = "embedded"
    scheduler_tick_seconds: int = 30
    scheduler_lease_ttl_seconds: int = 90

    # Collecte
    http_user_agent: str = "JobRadar/0.1 (personal job watcher; respects robots.txt)"
    collect_max_concurrency: int = Field(default=3, ge=1, le=10)
    request_timeout_seconds: float = Field(default=20.0, gt=0)
    source_timeout_seconds: float = Field(default=240.0, gt=0)
    min_request_delay_seconds: float = Field(default=1.5, ge=0)
    max_response_bytes: int = 6_000_000
    run_stale_after_seconds: int = 900  # un run sans battement de cœur est déclaré interrompu

    @field_validator("scheduler_mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        if v not in {"embedded", "off"}:
            raise ValueError("SCHEDULER_MODE doit valoir 'embedded' ou 'off'")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sources_config_path(self) -> Path:
        return self.config_dir / "sources.yaml"

    @property
    def employers_config_path(self) -> Path:
        return self.config_dir / "employers.yaml"

    @property
    def profiles_config_path(self) -> Path:
        return self.config_dir / "default_search_profiles.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()
