"""Veille automatique : bail multi-processus, réglages persistants, état réel, déclenchements (tick) et rattrapage."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from jobradar.core.clock import utcnow
from jobradar.core.config import Settings
from jobradar.core.db import Database
from jobradar.jobs.scheduler import MAX_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES, SchedulerService
from jobradar.models import JobSource, RunStatus, SchedulerState, SearchRun
from jobradar.services.runner import RunService

from .conftest import fake_factory
from .conftest import json_jobs as _json_jobs

A, B = "emploi_dakar", "emploisenegal"


def jobs(start: int, n: int = 2) -> list[dict[str, Any]]:
    return _json_jobs(start, n)


def make_scheduler(db: Database, settings: Settings, owner: str = "sched-1") -> SchedulerService:
    runs = RunService(db, settings, owner=owner, connector_factory=lambda k, p, c: fake_factory(p, k, c))
    return SchedulerService(db, runs, settings, owner=owner)


def configure(db: Database, **per_source: dict[str, Any]) -> None:
    with db.session() as s:
        for key, cfg in per_source.items():
            s.scalar(select(JobSource).where(JobSource.source_key == key)).configuration = dict(cfg)


def only_enabled(db: Database, *keys: str) -> None:
    with db.session() as s:
        for src in s.scalars(select(JobSource)):
            src.enabled = src.source_key in keys


def set_state(db: Database, **values: Any) -> None:
    with db.session() as s:
        s.execute(update(SchedulerState).where(SchedulerState.id == 1).values(**values))


def runs_in(db: Database) -> list[SearchRun]:
    with db.session() as s:
        return list(s.scalars(select(SearchRun).order_by(SearchRun.id)))


async def drain(sched: SchedulerService) -> None:
    """Attend la fin des collectes lancées par le tick puis libère les ressources."""
    tasks = list(sched.runs._tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await sched.runs.shutdown()


# ------------------------------------------------------------------------------------------------ bail
def test_lease_is_exclusive(seeded: Database, settings: Settings) -> None:
    s1, s2 = make_scheduler(seeded, settings, "p1"), make_scheduler(seeded, settings, "p2")
    now = utcnow()
    assert s1.acquire_lease(now) is True
    assert s2.acquire_lease(now) is False
    assert s1.acquire_lease(now + timedelta(seconds=5)) is True  # renouvellement par le porteur


def test_expired_lease_is_taken_over(seeded: Database, settings: Settings) -> None:
    s1, s2 = make_scheduler(seeded, settings, "p1"), make_scheduler(seeded, settings, "p2")
    now = utcnow()
    assert s1.acquire_lease(now)
    later = now + timedelta(seconds=settings.scheduler_lease_ttl_seconds + 1)  # p1 n'a plus renouvelé
    assert s2.acquire_lease(later) is True
    assert s1.acquire_lease(later) is False


def test_release_lease_only_by_owner(seeded: Database, settings: Settings) -> None:
    s1, s2 = make_scheduler(seeded, settings, "p1"), make_scheduler(seeded, settings, "p2")
    assert s1.acquire_lease(utcnow())
    s2.release_lease()  # sans effet
    assert s1.get_state().lease_owner == "p1"
    s1.release_lease()
    st = s1.get_state()
    assert st.lease_owner is None and st.heartbeat_at is None
    assert s2.acquire_lease(utcnow())


# ------------------------------------------------------------------------------------------------ réglages
def test_default_state_is_disabled(seeded: Database, settings: Settings) -> None:
    st = make_scheduler(seeded, settings).get_state()
    assert st.enabled is False and st.interval_minutes == 360 and st.next_run_at is None


def test_update_settings_enable_disable(seeded: Database, settings: Settings) -> None:
    sched = make_scheduler(seeded, settings)
    now = utcnow()
    st = sched.update_settings(enabled=True, now=now)
    assert st.enabled and st.next_run_at == now  # première collecte au prochain tick
    st = sched.update_settings(enabled=False, now=now)
    assert not st.enabled and st.next_run_at is None


def test_update_settings_interval_and_targets(seeded: Database, settings: Settings) -> None:
    sched = make_scheduler(seeded, settings)
    now = utcnow()
    last = now - timedelta(hours=1)
    sched.update_settings(enabled=True, now=now)
    set_state(seeded, last_run_at=last)

    st = sched.update_settings(interval_minutes=120, profile_ids=[1], source_keys=[A, B], now=now)
    assert st.interval_minutes == 120 and st.next_run_at == last + timedelta(minutes=120)
    assert st.profile_ids == [1] and st.source_keys == [A, B]

    st = sched.update_settings(enabled=None, now=now)  # champs omis : rien ne change
    assert st.profile_ids == [1] and st.source_keys == [A, B]
    st = sched.update_settings(profile_ids=None, source_keys=[], now=now)  # None / vide : retour à « tous »
    assert st.profile_ids is None and st.source_keys is None


@pytest.mark.parametrize("minutes", [0, MIN_INTERVAL_MINUTES - 1, MAX_INTERVAL_MINUTES + 1])
def test_update_settings_rejects_bad_interval(seeded: Database, settings: Settings, minutes: int) -> None:
    with pytest.raises(ValueError, match="intervalle"):
        make_scheduler(seeded, settings).update_settings(interval_minutes=minutes)


# ------------------------------------------------------------------------------------------------ état réel
def test_status_disabled(seeded: Database, settings: Settings) -> None:
    st = make_scheduler(seeded, settings).status()
    assert st["state"] == "disabled" and st["alive"] is False and st["next_run_at"] is None
    assert st["mode"] == "off"


def test_status_enabled_without_process_is_stopped(seeded: Database, settings: Settings) -> None:
    sched = make_scheduler(seeded, settings)
    sched.update_settings(enabled=True)
    st = sched.status()
    assert st["state"] == "stopped" and st["alive"] is False and st["this_process_is_leader"] is False


def test_status_running_needs_fresh_heartbeat_and_lease(seeded: Database, settings: Settings) -> None:
    sched = make_scheduler(seeded, settings)
    sched.update_settings(enabled=True)
    now = utcnow()
    assert sched.acquire_lease(now)
    st = sched.status(now)
    assert st["state"] == "running" and st["alive"] is True and st["this_process_is_leader"] is True
    assert make_scheduler(seeded, settings, "autre").status(now)["this_process_is_leader"] is False

    # le processus s'arrête sans libérer le bail : le battement se périme → « stopped »
    assert sched.status(now + timedelta(minutes=10))["state"] == "stopped"


# ------------------------------------------------------------------------------------------------ tick
async def test_tick_not_leader(seeded: Database, settings: Settings) -> None:
    leader, other = make_scheduler(seeded, settings, "p1"), make_scheduler(seeded, settings, "p2")
    leader.update_settings(enabled=True)
    assert await leader.tick() != "not_leader"
    assert await other.tick() == "not_leader"
    await drain(leader)
    await drain(other)


async def test_tick_disabled_does_nothing(seeded: Database, settings: Settings) -> None:
    sched = make_scheduler(seeded, settings)
    assert await sched.tick() == "disabled"
    assert runs_in(seeded) == []
    await drain(sched)


async def test_tick_idle_before_due(seeded: Database, settings: Settings) -> None:
    sched = make_scheduler(seeded, settings)
    now = utcnow()
    sched.update_settings(enabled=True, now=now)
    set_state(seeded, next_run_at=now + timedelta(hours=2))
    assert await sched.tick(now) == "idle"
    assert runs_in(seeded) == []
    await drain(sched)


async def test_tick_starts_scheduled_run(seeded: Database, settings: Settings) -> None:
    only_enabled(seeded, A, B)
    configure(seeded, **{A: {"jobs": jobs(1)}, B: {"jobs": jobs(10)}})
    sched = make_scheduler(seeded, settings)
    now = utcnow()
    sched.update_settings(enabled=True, interval_minutes=120, now=now)

    result = await sched.tick(now)
    assert result.startswith("started:")
    run_id = int(result.split(":")[1])
    await drain(sched)

    (run,) = runs_in(seeded)
    assert run.id == run_id and run.trigger_type == "scheduled" and run.status == RunStatus.COMPLETED.value
    assert run.offers_created == 4
    st = sched.get_state()
    assert st.last_run_id == run_id and st.last_run_at == now
    assert st.next_run_at == now + timedelta(minutes=120) and st.last_error is None


async def test_tick_respects_configured_targets(seeded: Database, settings: Settings) -> None:
    only_enabled(seeded, A, B)
    configure(seeded, **{A: {"jobs": jobs(1)}, B: {"jobs": jobs(10)}})
    sched = make_scheduler(seeded, settings)
    now = utcnow()
    sched.update_settings(enabled=True, source_keys=[B], now=now)
    await sched.tick(now)
    await drain(sched)

    (run,) = runs_in(seeded)
    assert run.requested_source_keys == [B] and run.offers_created == 2


async def test_tick_reports_busy_when_a_run_is_active(seeded: Database, settings: Settings) -> None:
    only_enabled(seeded, A)
    sched = make_scheduler(seeded, settings)
    now = utcnow()
    sched.update_settings(enabled=True, now=now)
    sched.runs.create_run(source_keys=[A], now=now)  # en file, battement récent
    assert await sched.tick(now) == "busy"
    assert len(runs_in(seeded)) == 1  # aucune seconde collecte
    assert sched.get_state().next_run_at == now  # échéance conservée : reprise au tick suivant
    await drain(sched)


async def test_tick_without_sources_records_error_and_postpones(seeded: Database, settings: Settings) -> None:
    only_enabled(seeded)  # plus aucune source activée
    sched = make_scheduler(seeded, settings)
    now = utcnow()
    sched.update_settings(enabled=True, interval_minutes=60, now=now)

    assert await sched.tick(now) == "no_sources"
    st = sched.get_state()
    assert "aucune source" in st.last_error and st.next_run_at == now + timedelta(minutes=60) and st.last_run_id is None
    assert runs_in(seeded) == []
    await drain(sched)


async def test_tick_catches_up_once_after_downtime(seeded: Database, settings: Settings) -> None:
    only_enabled(seeded, A)
    configure(seeded, **{A: {"jobs": jobs(1)}})
    sched = make_scheduler(seeded, settings)
    now = utcnow()
    sched.update_settings(enabled=True, interval_minutes=60, now=now - timedelta(days=2))
    set_state(seeded, last_run_at=now - timedelta(days=2), next_run_at=now - timedelta(days=2) + timedelta(minutes=60))

    assert (await sched.tick(now)).startswith("started:")  # une seule collecte de rattrapage…
    await drain(sched)
    assert await sched.tick(now + timedelta(seconds=1)) == "idle"  # …pas de rafale
    assert len(runs_in(seeded)) == 1
    assert sched.get_state().next_run_at == now + timedelta(minutes=60)
    await drain(sched)


async def test_tick_computes_missing_next_run(seeded: Database, settings: Settings) -> None:
    sched = make_scheduler(seeded, settings)
    now = utcnow()
    sched.update_settings(enabled=True, interval_minutes=60, now=now)
    set_state(seeded, next_run_at=None, last_run_at=now - timedelta(minutes=10))
    assert await sched.tick(now) == "idle"
    assert sched.get_state().next_run_at == now - timedelta(minutes=10) + timedelta(minutes=60)
    await drain(sched)


async def test_tick_reaps_orphan_runs(seeded: Database, settings: Settings) -> None:
    only_enabled(seeded, A)
    sched = make_scheduler(seeded, settings)
    now = utcnow()
    orphan = sched.runs.create_run(source_keys=[A], now=now - timedelta(hours=3))  # battement périmé
    assert await sched.tick(now) == "disabled"  # veille désactivée : le nettoyage a quand même lieu
    (run,) = runs_in(seeded)
    assert run.id == orphan and run.status == RunStatus.INTERRUPTED.value
    await drain(sched)


async def test_start_and_stop_lifecycle(seeded: Database, settings: Settings) -> None:
    sched = make_scheduler(seeded, settings)
    await sched.start()
    assert sched._scheduler is not None and sched._scheduler.running
    assert sched.acquire_lease(utcnow())
    await sched.stop()
    assert sched._scheduler is None
    st = sched.get_state()
    assert st.lease_owner is None  # bail rendu à l'arrêt propre : un autre processus peut reprendre aussitôt
    await sched.runs.shutdown()


async def test_worker_process_carries_the_scheduler(db: Database, settings: Settings) -> None:
    """Le worker (SCHEDULER_MODE=off côté API) prend le bail, bat le cœur, puis rend le bail à l'arrêt."""
    from jobradar.jobs.worker import run_worker

    observer = make_scheduler(db, settings, "observer")
    stop = asyncio.Event()
    task = asyncio.create_task(run_worker(settings, stop=stop))
    try:
        for _ in range(150):  # le premier tick part ~2 s après le démarrage
            await asyncio.sleep(0.1)
            if observer.status()["alive"]:
                break
        st = observer.status()
        assert st["alive"] is True and st["this_process_is_leader"] is False
        assert observer.get_state().lease_owner not in (None, "observer")
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=15)
    assert observer.get_state().lease_owner is None  # bail rendu : un autre processus peut reprendre aussitôt
    await observer.runs.shutdown()
