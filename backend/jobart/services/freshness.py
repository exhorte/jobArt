"""Fraîcheur et statut de cycle de vie d'une annonce (fonctions pures, `now` injecté).

On distingue strictement :
* la date de publication DÉCLARÉE par la source (`published_at`, peut être NULL) ;
* la première détection par jobArt (`first_seen_at`) — jamais présentée comme une date de publication ;
* la dernière observation (`last_seen_at`) et la dernière vérification (`last_verified_at`) ;
* la date limite de candidature (`application_deadline`, peut être NULL) ;
* le statut de cycle de vie (`OfferStatus`).

Une URL qui répond ne prouve pas qu'une offre est ouverte ; une date limite absente ne prouve pas qu'elle est valide
ni expirée. Rien n'est supprimé automatiquement : on change seulement d'étiquette.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models import OfferStatus

STALE_AFTER_DAYS = 14


def compute_status(
    *,
    now: datetime,
    application_deadline: datetime | None,
    sources_missing: bool,
    sources_closed: bool,
) -> OfferStatus:
    """Statut de cycle de vie.

    * `sources_closed`  : toutes les sources ont signalé la clôture explicitement ;
    * `sources_missing` : toutes les sources, collectées avec succès depuis, ne la listent plus (depuis >= N jours) ;
    * date limite dépassée → `deadline_passed` (« potentiellement expirée »).
    """
    if sources_closed:
        return OfferStatus.CLOSED
    if application_deadline is not None and application_deadline < now:
        return OfferStatus.DEADLINE_PASSED
    if sources_missing:
        return OfferStatus.STALE
    return OfferStatus.LISTED


def is_source_missing(
    *, source_last_seen_at: datetime, source_last_success_at: datetime | None, stale_after_days: int = STALE_AFTER_DAYS
) -> bool:
    """Vrai si la source a été collectée avec succès APRÈS la dernière observation + délai (et ne l'a plus listée).

    Si l'application est restée arrêtée plusieurs semaines, rien n'est déclaré obsolète : seule une collecte réussie
    qui ne revoit plus l'annonce compte.
    """
    if source_last_success_at is None:
        return False
    return source_last_success_at - source_last_seen_at >= timedelta(days=stale_after_days)


@dataclass(frozen=True)
class AgeInfo:
    age_days: int | None  # âge selon la date de publication DÉCLARÉE (None si inconnue)
    label: str  # fresh | recent | old | unknown_date
    first_seen_age_days: int


def age_info(*, published_at: datetime | None, first_seen_at: datetime, now: datetime) -> AgeInfo:
    first_seen_age = max(0, (now - first_seen_at).days)
    if published_at is None:
        return AgeInfo(None, "unknown_date", first_seen_age)
    age = max(0, (now - published_at).days)
    label = "fresh" if age <= 7 else "recent" if age <= 30 else "old"
    return AgeInfo(age, label, first_seen_age)
