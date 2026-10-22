"""Moteur de collecte (RunService) : isolation des sources, statuts, verrous, intervalle minimal, reprise après arrêt.

Les connecteurs sont remplacés par `FakeConnector` (conftest) : aucune requête réseau. Les sources réelles du YAML servent de
support (clés valides dans le registre) ; leur `configuration` est remplacée par le scénario simulé.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select

from jobart.core.clock import utcnow
from jobart.core.config import Settings
from jobart.core.db import Database
from jobart.core.errors import ErrorType
from jobart.models import JobOffer, JobSource, RunSourceStatus, RunStatus, SearchProfile, SearchRun, SearchRunSource
from jobart.services.runner import (
    NoSourcesError,
    ProfileNotFound,
    RunService,
    UnknownSourceError,
    build_search_parameters,
    source_applies_to_profile,
)
from jobart.services.scoring import ProfileCriteria

from .conftest import FakeConnector, fake_factory
from .conftest import json_jobs as jobs

A, B, C = "emploi_dakar", "emploisenegal", "africarrieres_sn"


def make_service(db: Database, settings: Settings, **kw: Any) -> RunService:
    return RunService(db, settings, owner="test-owner", connector_factory=lambda k, p, c: fake_factory(p, k, c), **kw)


def configure(db: Database, **per_source: dict[str, Any]) -> None:
    """Remplace la configuration des sources (scénario de test) : configure(db, emploi_dakar={"jobs": [...]})."""
    with db.session() as s:
        for key, cfg in per_source.items():
            src = s.scalar(select(JobSource).where(JobSource.source_key == key))
            assert src is not None, key
            src.configuration = dict(cfg)


async def run_once(svc: RunService, **create: Any) -> int:
    run_id = svc.create_run(**create)
    try:
        await svc.execute_run(run_id)
    finally:
        await svc.shutdown()
    return run_id


def snapshot(db: Database, run_id: int) -> tuple[SimpleNamespace, dict[str, SimpleNamespace]]:
    with db.session() as s:
        run = s.get(SearchRun, run_id)
        assert run is not None
        rows = {
            src.source_key: SimpleNamespace(**{c.name: getattr(rs, c.name) for c in SearchRunSource.__table__.columns})
            for rs, src in s.execute(
                select(SearchRunSource, JobSource).join(JobSource, JobSource.id == SearchRunSource.job_source_id).where(SearchRunSource.search_run_id == run_id)
            )
        }
        head = SimpleNamespace(**{c.name: getattr(run, c.name) for c in SearchRun.__table__.columns})
    return head, rows


def source_row(db: Database, key: str) -> SimpleNamespace:
    with db.session() as s:
        src = s.scalar(select(JobSource).where(JobSource.source_key == key))
        assert src is not None
        return SimpleNamespace(**{c.name: getattr(src, c.name) for c in JobSource.__table__.columns})


def count_offers(db: Database) -> int:
    with db.session() as s:
        return s.scalar(select(func.count()).select_from(JobOffer)) or 0


# ------------------------------------------------------------------------------------------------ succès
async def test_success_two_sources(seeded: Database, settings: Settings) -> None:
    configure(seeded, **{A: {"jobs": jobs(1), "requests": 2}, B: {"jobs": jobs(10)}})
    svc = make_service(seeded, settings)
    run_id = await run_once(svc, source_keys=[A, B])

    run, rows = snapshot(seeded, run_id)
    assert run.status == RunStatus.COMPLETED.value
    assert (run.sources_requested, run.sources_succeeded, run.sources_failed) == (2, 2, 0)
    assert run.offers_found == 6 and run.offers_created == 6 and run.finished_at is not None
    assert run.error_summary is None
    assert rows[A].status == RunSourceStatus.SUCCESS.value and rows[A].requests_made == 2
    assert rows[A].offers_found == 3 and rows[A].error_type is None
    assert count_offers(seeded) == 6
    src = source_row(seeded, A)
    assert src.last_success_at is not None and src.last_run_status == "success" and src.last_error is None
    assert src.lock_owner is None  # verrou libéré


async def test_second_run_updates_without_duplicating(seeded: Database, settings: Settings) -> None:
    configure(seeded, **{A: {"jobs": jobs(1)}})
    await run_once(make_service(seeded, settings), source_keys=[A])

    second = await run_once(make_service(seeded, settings), source_keys=[A])  # contenu identique : « inchangées »
    run, rows = snapshot(seeded, second)
    assert run.status == RunStatus.COMPLETED.value
    assert (rows[A].offers_found, rows[A].offers_created, rows[A].offers_updated) == (3, 0, 0)
    assert count_offers(seeded) == 3

    configure(seeded, **{A: {"jobs": jobs(1, description="Python FastAPI Docker, description révisée par la source. " * 5)}})
    third = await run_once(make_service(seeded, settings), source_keys=[A])  # contenu modifié : « mises à jour »
    _, rows = snapshot(seeded, third)
    assert (rows[A].offers_created, rows[A].offers_updated) == (0, 3)
    assert count_offers(seeded) == 3


async def test_zero_results_is_success_not_error(seeded: Database, settings: Settings) -> None:
    configure(seeded, **{A: {"jobs": []}})
    run_id = await run_once(make_service(seeded, settings), source_keys=[A])

    run, rows = snapshot(seeded, run_id)
    assert run.status == RunStatus.COMPLETED.value
    assert rows[A].status == RunSourceStatus.SUCCESS.value and rows[A].offers_found == 0
    assert rows[A].details["empty"] is True
    assert source_row(seeded, A).last_success_at is not None


async def test_invalid_records_are_rejected_individually(seeded: Database, settings: Settings) -> None:
    good = jobs(1, 3)
    good[1]["_invalid"] = True
    configure(seeded, **{A: {"jobs": good, "warnings": ["page 2 vide"]}})
    run_id = await run_once(make_service(seeded, settings), source_keys=[A])

    run, rows = snapshot(seeded, run_id)
    assert run.status == RunStatus.COMPLETED.value
    assert rows[A].offers_found == 2 and rows[A].offers_rejected == 1
    assert rows[A].details["rejected_samples"] and rows[A].details["warnings"] == ["page 2 vide"]
    assert count_offers(seeded) == 2


# ------------------------------------------------------------------------------------------------ échecs
async def test_partial_when_one_source_fails(seeded: Database, settings: Settings) -> None:
    configure(seeded, **{A: {"jobs": jobs(1)}, B: {"raise": "NetworkError"}})
    run_id = await run_once(make_service(seeded, settings), source_keys=[A, B])

    run, rows = snapshot(seeded, run_id)
    assert run.status == RunStatus.PARTIAL.value
    assert (run.sources_succeeded, run.sources_failed) == (1, 1)
    assert rows[A].status == RunSourceStatus.SUCCESS.value
    assert rows[B].status == RunSourceStatus.FAILED.value and rows[B].error_type == ErrorType.NETWORK
    assert "boom" in rows[B].error_message
    assert B in run.error_summary and "network" in run.error_summary
    assert count_offers(seeded) == 3  # la source saine est bien enregistrée
    failed = source_row(seeded, B)
    assert failed.last_run_status == "failed" and failed.last_error_type == ErrorType.NETWORK and failed.last_success_at is None
    assert failed.lock_owner is None


async def test_failed_when_every_source_fails(seeded: Database, settings: Settings) -> None:
    configure(seeded, **{A: {"raise": "AccessBlocked"}, B: {"raise": "SourceUnavailable"}})
    run_id = await run_once(make_service(seeded, settings), source_keys=[A, B])

    run, rows = snapshot(seeded, run_id)
    assert run.status == RunStatus.FAILED.value
    assert (run.sources_succeeded, run.sources_failed) == (0, 2)
    assert rows[A].error_type == ErrorType.BLOCKED and rows[B].error_type == ErrorType.UNAVAILABLE
    assert A in run.error_summary and B in run.error_summary
    assert count_offers(seeded) == 0


async def test_unexpected_crash_is_isolated(seeded: Database, settings: Settings) -> None:
    configure(seeded, **{A: {"crash": True}, B: {"jobs": jobs(1)}, C: {"jobs": jobs(10)}})
    run_id = await run_once(make_service(seeded, settings), source_keys=[A, B, C])

    run, rows = snapshot(seeded, run_id)
    assert run.status == RunStatus.PARTIAL.value
    assert rows[A].status == RunSourceStatus.FAILED.value and rows[A].error_type == ErrorType.INTERNAL
    assert "RuntimeError" in rows[A].error_message
    assert rows[B].status == rows[C].status == RunSourceStatus.SUCCESS.value
    assert count_offers(seeded) == 6


async def test_source_timeout(seeded: Database, settings: Settings) -> None:
    fast = settings.model_copy(update={"source_timeout_seconds": 0.2})
    configure(seeded, **{A: {"sleep": 5}, B: {"jobs": jobs(1)}})
    run_id = await run_once(make_service(seeded, fast), source_keys=[A, B])

    run, rows = snapshot(seeded, run_id)
    assert run.status == RunStatus.PARTIAL.value
    assert rows[A].status == RunSourceStatus.FAILED.value and rows[A].error_type == ErrorType.TIMEOUT
    assert rows[B].status == RunSourceStatus.SUCCESS.value
    assert source_row(seeded, A).lock_owner is None


# ------------------------------------------------------------------------------------------------ verrou
async def test_locked_source_is_skipped(seeded: Database, settings: Settings) -> None:
    configure(seeded, **{A: {"jobs": jobs(1)}, B: {"jobs": jobs(10)}})
    with seeded.session() as s:
        src = s.scalar(select(JobSource).where(JobSource.source_key == A))
        src.lock_owner = "autre-processus"
        src.lock_expires_at = utcnow() + timedelta(minutes=5)
    run_id = await run_once(make_service(seeded, settings), source_keys=[A, B])

    run, rows = snapshot(seeded, run_id)
    assert rows[A].status == RunSourceStatus.SKIPPED.value and rows[A].error_type == ErrorType.LOCKED
    assert rows[B].status == RunSourceStatus.SUCCESS.value
    assert run.status == RunStatus.COMPLETED.value  # un saut n'est pas un échec
    assert A in run.error_summary  # mais il est signalé
    assert FakeConnector.calls == [B]
    assert source_row(seeded, A).lock_owner == "autre-processus"  # le verrou d'autrui n'est pas libéré


async def test_expired_lock_is_taken_over(seeded: Database, settings: Settings) -> None:
    configure(seeded, **{A: {"jobs": jobs(1)}})
    with seeded.session() as s:
        src = s.scalar(select(JobSource).where(JobSource.source_key == A))
        src.lock_owner = "processus-mort"
        src.lock_expires_at = utcnow() - timedelta(minutes=1)
    run_id = await run_once(make_service(seeded, settings), source_keys=[A])

    _, rows = snapshot(seeded, run_id)
    assert rows[A].status == RunSourceStatus.SUCCESS.value
    assert source_row(seeded, A).lock_owner is None


def test_lock_is_exclusive_between_services(seeded: Database, settings: Settings) -> None:
    svc = make_service(seeded, settings)
    sid = source_row(seeded, A).id
    assert svc._acquire_lock(sid, "p1:run1") is True
    assert svc._acquire_lock(sid, "p2:run2") is False
    assert svc._acquire_lock(sid, "p1:run1") is True  # ré-entrant pour le même propriétaire
    svc._release_lock(sid, "p2:run2")  # un non-propriétaire ne libère rien
    assert source_row(seeded, A).lock_owner == "p1:run1"
    svc._release_lock(sid, "p1:run1")
    assert svc._acquire_lock(sid, "p2:run2") is True


# ------------------------------------------------------------------------------------------------ intervalle minimal
async def test_min_interval_skips_recent_source(seeded: Database, settings: Settings) -> None:
    configure(seeded, **{A: {"jobs": jobs(1), "min_interval_minutes": 60}})
    with seeded.session() as s:
        s.scalar(select(JobSource).where(JobSource.source_key == A)).last_success_at = utcnow() - timedelta(minutes=10)
    run_id = await run_once(make_service(seeded, settings), source_keys=[A])

    run, rows = snapshot(seeded, run_id)
    assert rows[A].status == RunSourceStatus.SKIPPED.value and rows[A].error_type == ErrorType.SKIPPED_RECENT
    assert "60 min" in rows[A].error_message
    assert FakeConnector.calls == []
    assert count_offers(seeded) == 0
    assert source_row(seeded, A).last_run_status is None  # un saut ne modifie pas l'état de la source


async def test_min_interval_elapsed_runs(seeded: Database, settings: Settings) -> None:
    configure(seeded, **{A: {"jobs": jobs(1), "min_interval_minutes": 60}})
    with seeded.session() as s:
        s.scalar(select(JobSource).where(JobSource.source_key == A)).last_success_at = utcnow() - timedelta(hours=2)
    run_id = await run_once(make_service(seeded, settings), source_keys=[A])

    _, rows = snapshot(seeded, run_id)
    assert rows[A].status == RunSourceStatus.SUCCESS.value and rows[A].offers_created == 3


# ------------------------------------------------------------------------------------------------ création
def test_create_run_validations(seeded: Database, settings: Settings) -> None:
    svc = make_service(seeded, settings)
    with pytest.raises(UnknownSourceError, match="inconnue"):
        svc.create_run(source_keys=["nexiste_pas"])
    with pytest.raises(UnknownSourceError, match="aucun connecteur"):
        svc.create_run(source_keys=["senejobs"])  # différée : pas de connecteur
    with pytest.raises(ProfileNotFound):
        svc.create_run(profile_id=99999)
    with seeded.session() as s:
        for src in s.scalars(select(JobSource)):
            src.enabled = False
    with pytest.raises(NoSourcesError):
        svc.create_run()


def test_create_run_default_selection_uses_enabled_implemented_sources(seeded: Database, settings: Settings) -> None:
    svc = make_service(seeded, settings)
    run_id = svc.create_run()
    run, rows = snapshot(seeded, run_id)
    assert run.status == RunStatus.QUEUED.value and run.requested_source_keys is None
    assert run.sources_requested == len(rows) > 0
    with seeded.session() as s:
        enabled = {x.source_key for x in s.scalars(select(JobSource).where(JobSource.enabled.is_(True), JobSource.implementation == "implemented"))}
    assert set(rows) <= enabled
    assert "manual" not in rows and "senejobs" not in rows and "linkedin_jobs" not in rows


def test_create_run_for_single_profile_records_it(seeded: Database, settings: Settings) -> None:
    with seeded.session() as s:
        pid = s.scalars(select(SearchProfile.id).order_by(SearchProfile.id)).first()
    run_id = make_service(seeded, settings).create_run(profile_id=pid, source_keys=[A])
    run, _ = snapshot(seeded, run_id)
    assert run.profile_id == pid and run.requested_source_keys == [A] and run.trigger_type == "manual"


# ------------------------------------------------------------------------------------------------ reprise / reaper
def test_reap_stale_runs_marks_interrupted(seeded: Database, settings: Settings) -> None:
    svc = make_service(seeded, settings)
    now = utcnow()
    old = svc.create_run(source_keys=[A, B], now=now - timedelta(hours=1))
    fresh = svc.create_run(source_keys=[C], now=now)
    with seeded.session() as s:
        run = s.get(SearchRun, old)
        run.status = RunStatus.RUNNING.value
        rs = s.scalars(select(SearchRunSource).where(SearchRunSource.search_run_id == old).order_by(SearchRunSource.id)).all()
        rs[0].status = RunSourceStatus.RUNNING.value
        rs[1].status = RunSourceStatus.SUCCESS.value  # déjà terminée : conservée

    assert svc.has_active_run(now=now) is True and svc.active_run_id(now=now) == fresh
    assert svc.reap_stale_runs(now=now) == 1

    run_old, rows = snapshot(seeded, old)
    run_fresh, _ = snapshot(seeded, fresh)
    assert run_old.status == RunStatus.INTERRUPTED.value and run_old.finished_at is not None
    assert "interrompue" in run_old.error_summary.lower()
    assert rows[A].status == RunSourceStatus.FAILED.value and rows[B].status == RunSourceStatus.SUCCESS.value
    assert run_fresh.status == RunStatus.QUEUED.value  # battement récent : intact
    assert svc.reap_stale_runs(now=now) == 0  # idempotent


def test_no_active_run_when_heartbeat_is_stale(seeded: Database, settings: Settings) -> None:
    svc = make_service(seeded, settings)
    now = utcnow()
    svc.create_run(source_keys=[A], now=now - timedelta(hours=2))
    assert svc.has_active_run(now=now) is False and svc.active_run_id(now=now) is None


async def test_cancelled_run_is_marked_interrupted(seeded: Database, settings: Settings) -> None:
    import asyncio

    configure(seeded, **{A: {"sleep": 30}})
    svc = make_service(seeded, settings)
    run_id = svc.create_run(source_keys=[A])
    task = svc.spawn(run_id)
    await asyncio.sleep(0.4)
    await svc.shutdown()  # arrêt de l'application pendant la collecte
    assert task.cancelled() or task.done()

    run, rows = snapshot(seeded, run_id)
    assert run.status == RunStatus.INTERRUPTED.value
    assert rows[A].status == RunSourceStatus.FAILED.value
    assert source_row(seeded, A).lock_owner is None


# ------------------------------------------------------------------------------------------------ test d'une source
async def test_test_source_records_result(seeded: Database, settings: Settings) -> None:
    configure(seeded, **{A: {"jobs": jobs(1)}, B: {"raise": "AccessBlocked"}})
    svc = make_service(seeded, settings)
    ok = await svc.test_source(A)
    ko = await svc.test_source(B)
    await svc.shutdown()

    assert ok.ok and ok.sample_count == 3
    assert not ko.ok and ko.status == "blocked"
    a, b = source_row(seeded, A), source_row(seeded, B)
    assert a.last_check_ok is True and a.last_checked_at is not None
    assert b.last_check_ok is False and b.last_error_type == ErrorType.BLOCKED
    assert count_offers(seeded) == 0  # un test n'enregistre aucune offre


async def test_test_source_rejects_unknown_or_deferred(seeded: Database, settings: Settings) -> None:
    svc = make_service(seeded, settings)
    with pytest.raises(UnknownSourceError):
        await svc.test_source("nexiste_pas")
    with pytest.raises(UnknownSourceError):
        await svc.test_source("senejobs")
    await svc.shutdown()


# ------------------------------------------------------------------------------------------------ fonctions pures
def test_source_applies_to_profile() -> None:
    sn = ProfileCriteria(countries=["SN"], work_modes=["onsite"])
    remote = ProfileCriteria(countries=["SN"], work_modes=["onsite", "remote"])
    assert source_applies_to_profile("local", ["SN"], sn)
    assert not source_applies_to_profile("local", ["CI"], sn)
    assert source_applies_to_profile("local", ["*"], sn)
    assert not source_applies_to_profile("remote", ["*"], sn)  # télétravail non souhaité
    assert source_applies_to_profile("remote", ["*"], remote)
    assert source_applies_to_profile("local", ["CI"], ProfileCriteria())  # profil sans pays : tout


def test_build_search_parameters_interleaves_profiles() -> None:
    p1 = ProfileCriteria(countries=["sn"], cities=["Dakar"], positive_keywords=["Python", "Django"], work_modes=["onsite"])
    p2 = ProfileCriteria(countries=["SN", "CI"], cities=["Dakar", "Abidjan"], positive_keywords=["React", "python", "Vue"], work_modes=["remote"])
    params = build_search_parameters([p1, p2], {"max_pages": 3, "max_queries": 4})
    assert params.keywords == ["Python", "React", "Django", "Vue"]  # 1er de chaque profil d'abord, sans doublon (casse ignorée)
    assert params.countries == ["SN", "CI"] and params.cities == ["Dakar", "Abidjan"]
    assert params.work_modes == ["onsite", "remote"]
    assert (params.max_pages, params.max_queries) == (3, 4)
    assert build_search_parameters([], {}).countries == ["SN"]
