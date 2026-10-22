"""Taxonomie d'erreurs de collecte.

Chaque erreur porte un `error_type` stable, enregistré dans SearchRunSource.error_type et affiché dans l'UI.
Une collecte réussie avec zéro résultat n'est PAS une erreur (voir RunSourceStatus.SUCCESS + offers_found=0).
"""

from __future__ import annotations


class ErrorType:
    NETWORK = "network"  # DNS, connexion refusée, TLS
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"  # 5xx, 404 sur une page qui devrait exister
    BLOCKED = "blocked"  # 401/403, CAPTCHA, défi anti-robot : on ne contourne pas
    RATE_LIMITED = "rate_limited"  # 429 ou quota local
    ROBOTS = "robots_disallowed"  # robots.txt interdit le chemin
    PARSE = "parse"  # structure HTML/JSON modifiée
    NORMALIZATION = "normalization"  # annonce rejetée (URL invalide, titre vide...)
    LOCKED = "locked"  # une autre collecte est en cours sur la source
    SKIPPED_RECENT = "skipped_recent"  # intervalle minimal entre deux collectes non écoulé
    INTERNAL = "internal"


class SourceError(Exception):
    """Erreur attribuable à une source (isolée : n'interrompt jamais les autres sources)."""

    error_type: str = ErrorType.INTERNAL

    def __init__(self, message: str, *, error_type: str | None = None, url: str | None = None) -> None:
        super().__init__(message)
        if error_type:
            self.error_type = error_type
        self.url = url

    def __str__(self) -> str:  # message + URL pour les logs/UI
        base = super().__str__()
        return f"{base} ({self.url})" if self.url else base


class NetworkError(SourceError):
    error_type = ErrorType.NETWORK


class SourceTimeout(SourceError):
    error_type = ErrorType.TIMEOUT


class SourceUnavailable(SourceError):
    error_type = ErrorType.UNAVAILABLE


class AccessBlocked(SourceError):
    error_type = ErrorType.BLOCKED


class RateLimited(SourceError):
    error_type = ErrorType.RATE_LIMITED


class RobotsDisallowed(SourceError):
    error_type = ErrorType.ROBOTS


class ParseError(SourceError):
    error_type = ErrorType.PARSE


class NormalizationError(SourceError):
    """Annonce individuelle rejetée à la normalisation (la collecte continue)."""

    error_type = ErrorType.NORMALIZATION


class SourceLocked(SourceError):
    error_type = ErrorType.LOCKED


class SourceSkipped(SourceError):
    error_type = ErrorType.SKIPPED_RECENT
