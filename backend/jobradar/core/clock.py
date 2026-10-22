"""Horloge UTC unique (facilite les tests : on injecte `now` dans les fonctions pures)."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_aware(dt: datetime | None) -> datetime | None:
    """Rend un datetime conscient du fuseau (UTC si naïf)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
