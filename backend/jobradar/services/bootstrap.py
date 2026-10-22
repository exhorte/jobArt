"""Initialisation des données de référence : sources (config/sources.yaml), profils par défaut, état de la veille."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..collectors.registry import CONNECTORS
from ..core.clock import utcnow
from ..models import JobSource, SchedulerState, SearchProfile

log = logging.getLogger(__name__)
DEFAULT_INTERVAL_MINUTES = 360


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} : racine YAML invalide")
    return data


def load_employers(path: Path) -> list[dict[str, Any]]:
    return list(_load_yaml(path).get("employers", [])) if path.exists() else []


def sync_sources(session: Session, path: Path) -> dict[str, int]:
    """Crée/met à jour les JobSource depuis la configuration. L'état `enabled` choisi par l'utilisateur est conservé."""
    entries = _load_yaml(path).get("sources", [])
    counts = {"created": 0, "updated": 0, "warnings": 0}
    for entry in entries:
        key = entry["key"]
        connector = entry.get("connector")
        implementation = entry.get("implementation", "deferred")
        if implementation == "implemented" and connector and connector not in CONNECTORS:
            log.warning("source %s : connecteur %s absent du registre → marquée différée", key, connector)
            implementation = "deferred"
            counts["warnings"] += 1
        src = session.scalar(select(JobSource).where(JobSource.source_key == key))
        values = dict(
            name=entry["name"],
            base_url=entry["base_url"],
            source_type=entry.get("type", "job_board"),
            market=entry.get("market", "local"),
            countries=list(entry.get("countries", [])),
            collection_method=entry.get("collection_method", "unknown"),
            verification_status=entry.get("verification_status", "to_verify"),
            implementation=implementation,
            decision_reason=entry.get("decision_reason"),
            tos_note=entry.get("tos_note"),
            doc_status=entry.get("doc_status"),
            configuration=dict(entry.get("configuration") or {}),
        )
        if src is None:
            src = JobSource(source_key=key, enabled=bool(entry.get("enabled", False)) and implementation == "implemented", **values)
            session.add(src)
            counts["created"] += 1
        else:
            for k, v in values.items():
                setattr(src, k, v)
            if implementation != "implemented":
                src.enabled = False
            counts["updated"] += 1
    session.flush()
    return counts


def seed_profiles(session: Session, path: Path) -> int:
    """Crée les profils par défaut si (et seulement si) aucun profil n'existe."""
    if session.scalar(select(SearchProfile.id).limit(1)) is not None:
        return 0
    data = _load_yaml(path)
    n = 0
    for p in data.get("profiles", []):
        session.add(
            SearchProfile(
                name=p["name"],
                description=p.get("description"),
                countries=list(p.get("countries", [])),
                cities=list(p.get("cities", [])),
                positive_keywords=list(p.get("positive_keywords", [])),
                keyword_groups=dict(p.get("keyword_groups", {})),
                excluded_keywords=list(p.get("excluded_keywords", [])),
                target_roles=list(p.get("target_roles", [])),
                sectors=list(p.get("sectors", [])),
                contract_types=list(p.get("contract_types", [])),
                work_modes=list(p.get("work_modes", [])),
                experience_levels=list(p.get("experience_levels", [])),
                weights=dict(p["weights"]) if p.get("weights") else None,
                is_active=bool(p.get("is_active", True)),
            )
        )
        n += 1
    session.flush()
    return n


def ensure_scheduler_state(session: Session) -> SchedulerState:
    """Ligne unique id=1 (réglages de la veille). Désactivée par défaut : aucun trafic sans action de l'utilisateur."""
    state = session.get(SchedulerState, 1)
    if state is None:
        state = SchedulerState(id=1, enabled=False, interval_minutes=DEFAULT_INTERVAL_MINUTES)
        session.add(state)
        try:
            session.flush()
        except IntegrityError:  # un autre processus l'a créée en même temps
            session.rollback()
            state = session.get(SchedulerState, 1)
    assert state is not None
    return state


def bootstrap(session: Session, *, sources_path: Path, profiles_path: Path, now: datetime | None = None) -> dict[str, Any]:
    return {
        "sources": sync_sources(session, sources_path),
        "profiles_seeded": seed_profiles(session, profiles_path),
        "scheduler": ensure_scheduler_state(session).interval_minutes,
        "at": (now or utcnow()).isoformat(),
    }
