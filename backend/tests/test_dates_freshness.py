"""Dates déclarées par les sources et statuts de fraîcheur / cycle de vie."""

from datetime import UTC, datetime, timedelta

import pytest

from jobradar.models import OfferStatus
from jobradar.services.dates import from_epoch, is_relative_date, parse_datetime
from jobradar.services.freshness import age_info, compute_status, is_source_missing

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-10-21T10:37:06+00:00", datetime(2026, 10, 21, 10, 37, 6, tzinfo=UTC)),
        ("2026-10-21T10:37:06Z", datetime(2026, 10, 21, 10, 37, 6, tzinfo=UTC)),
        ("2026-10-21T12:00:00+02:00", datetime(2026, 10, 21, 10, 0, tzinfo=UTC)),  # fuseau converti
        ("2026-10-21 08:56:10", datetime(2026, 10, 21, 8, 56, 10, tzinfo=UTC)),  # naïf = UTC
        ("2026-10-21", datetime(2026, 10, 21, tzinfo=UTC)),
        ("21.10.2026", datetime(2026, 10, 21, tzinfo=UTC)),
        ("Publié le 21 octobre 2026", datetime(2026, 10, 21, tzinfo=UTC)),
        ("1er novembre 2026", datetime(2026, 11, 1, tzinfo=UTC)),
        ("Oct 9, 2026", datetime(2026, 10, 9, tzinfo=UTC)),
        ("Fri, 07 Oct 2022 13:33:20 GMT", datetime(2022, 10, 7, 13, 33, 20, tzinfo=UTC)),
    ],
)
def test_parse_datetime_absolute_formats(value, expected):
    assert parse_datetime(value) == expected


@pytest.mark.parametrize("value", [None, "", "il y a 2 heures", "Aujourd'hui, 13:17", "9. sept., 09:04", "n'importe quoi", "2026-13-45"])
def test_parse_datetime_never_invents_a_date(value):
    assert parse_datetime(value) is None


def test_relative_dates_are_detected_not_converted():
    assert is_relative_date("il y a 3 jours")
    assert is_relative_date("Aujourd'hui, 13:17")
    assert not is_relative_date("21 octobre 2026")


def test_from_epoch_seconds_and_milliseconds():
    assert from_epoch(1792483205) == from_epoch(1792483205000)
    assert from_epoch(0) is None and from_epoch(None) is None


def test_age_info_distinguishes_declared_publication_from_first_seen():
    # pas de date de publication déclarée → âge inconnu, JAMAIS déduit de first_seen_at
    info = age_info(published_at=None, first_seen_at=NOW - timedelta(days=3), now=NOW)
    assert info.age_days is None and info.label == "unknown_date" and info.first_seen_age_days == 3
    assert age_info(published_at=NOW - timedelta(days=2), first_seen_at=NOW, now=NOW).label == "fresh"
    assert age_info(published_at=NOW - timedelta(days=20), first_seen_at=NOW, now=NOW).label == "recent"
    assert age_info(published_at=NOW - timedelta(days=90), first_seen_at=NOW, now=NOW).label == "old"


def test_status_listed_by_default_even_without_deadline():
    # une date limite absente ne rend pas l'annonce expirée
    assert compute_status(now=NOW, application_deadline=None, sources_missing=False, sources_closed=False) == OfferStatus.LISTED


def test_status_deadline_passed_is_potentially_expired_not_deleted():
    past = NOW - timedelta(days=1)
    assert compute_status(now=NOW, application_deadline=past, sources_missing=False, sources_closed=False) == OfferStatus.DEADLINE_PASSED
    future = NOW + timedelta(days=1)
    assert compute_status(now=NOW, application_deadline=future, sources_missing=False, sources_closed=False) == OfferStatus.LISTED


def test_status_stale_and_closed_precedence():
    assert compute_status(now=NOW, application_deadline=None, sources_missing=True, sources_closed=False) == OfferStatus.STALE
    assert compute_status(now=NOW, application_deadline=None, sources_missing=True, sources_closed=True) == OfferStatus.CLOSED


def test_source_missing_only_after_a_successful_collection_that_no_longer_lists_it():
    seen = NOW - timedelta(days=30)
    # application arrêtée depuis 30 jours : aucune collecte réussie depuis → rien n'est déclaré obsolète
    assert not is_source_missing(source_last_seen_at=seen, source_last_success_at=None)
    assert not is_source_missing(source_last_seen_at=seen, source_last_success_at=seen)
    assert is_source_missing(source_last_seen_at=seen, source_last_success_at=NOW)
    assert not is_source_missing(source_last_seen_at=NOW - timedelta(days=3), source_last_success_at=NOW)
