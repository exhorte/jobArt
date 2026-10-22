"""Veille automatique (collecte périodique).

Conception (mono-instance clairement assumée, sûre en multi-processus) :
* les réglages (activée ?, intervalle, profils/sources ciblés, prochaine exécution) sont PERSISTANTS en base
  (table scheduler_state, ligne unique) : ils survivent aux redémarrages ;
* un seul processus porte la veille grâce à un BAIL en base (`lease_owner` / `lease_expires_at`, acquisition atomique par
  UPDATE conditionnel). Si plusieurs processus backend démarrent, un seul exécute les déclenchements ;
* un « tick » APScheduler (toutes les 30 s) renouvelle le bail, met à jour le battement de cœur, déclare
  « interrompues » les exécutions orphelines et lance une collecte quand `next_run_at` est dépassé ;
* reprise après redémarrage : si l'échéance est passée pendant l'arrêt, UNE collecte de rattrapage est lancée (pas de rafale) ;
* le lancement manuel est indépendant (RunService.create_run) ; si une exécution est en cours, l'échéance est reportée au
  tick suivant (aucune collecte concurrente incompatible) ;
* l'état affiché est réel : `alive` n'est vrai que si le battement de cœur est récent (sinon « veille activée mais aucun
  processus ne la porte »).
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import or_, update

from ..core.clock import utcnow
from ..core.config import Settings
from ..core.db import Database
from ..models import SchedulerState, TriggerType
from ..services.bootstrap import ensure_scheduler_state
from ..services.runner import NoSourcesError, RunError, RunService

log = logging.getLogger(__name__)

MIN_INTERVAL_MINUTES = 30
MAX_INTERVAL_MINUTES = 7 * 24 * 60
_UNSET: Any = object()


class SchedulerService:
    def __init__(self, db: Database, runs: RunService, settings: Settings, *, owner: str | None = None) -> None:
        self.db = db
        self.runs = runs
        self.settings = settings
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._scheduler: AsyncIOScheduler | None = None

    # ------------------------------------------------------------------ bail
    def acquire_lease(self, now: datetime) -> bool:
        ttl = timedelta(seconds=self.settings.scheduler_lease_ttl_seconds)
        with self.db.session() as s:
            ensure_scheduler_state(s)
            res = s.execute(
                update(SchedulerState)
                .where(
                    SchedulerState.id == 1,
                    or_(
                        SchedulerState.lease_owner.is_(None),
                        SchedulerState.lease_owner == self.owner,
                        SchedulerState.lease_expires_at < now,
                    ),
                )
                .values(lease_owner=self.owner, lease_expires_at=now + ttl, heartbeat_at=now)
            )
            return res.rowcount == 1

    def release_lease(self) -> None:
        with self.db.session() as s:
            s.execute(
                update(SchedulerState)
                .where(SchedulerState.id == 1, SchedulerState.lease_owner == self.owner)
                .values(lease_owner=None, lease_expires_at=None, heartbeat_at=None)
            )

    # ------------------------------------------------------------------ réglages
    def get_state(self) -> SchedulerState:
        with self.db.session() as s:
            st = ensure_scheduler_state(s)
            s.expunge(st)
            return st

    def update_settings(
        self,
        *,
        enabled: bool | None = None,
        interval_minutes: int | None = None,
        profile_ids: list[int] | None | Any = _UNSET,
        source_keys: list[str] | None | Any = _UNSET,
        now: datetime | None = None,
    ) -> SchedulerState:
        now = now or utcnow()
        if interval_minutes is not None and not (MIN_INTERVAL_MINUTES <= interval_minutes <= MAX_INTERVAL_MINUTES):
            raise ValueError(f"intervalle entre {MIN_INTERVAL_MINUTES} minutes et {MAX_INTERVAL_MINUTES} minutes")
        with self.db.session() as s:
            st = ensure_scheduler_state(s)
            if enabled is not None and enabled != st.enabled:
                st.enabled = enabled
                st.next_run_at = now if enabled else None  # activation : première collecte au prochain tick
            if interval_minutes is not None and interval_minutes != st.interval_minutes:
                st.interval_minutes = interval_minutes
                if st.enabled:
                    st.next_run_at = (st.last_run_at + timedelta(minutes=interval_minutes)) if st.last_run_at else now
            if profile_ids is not _UNSET:
                st.profile_ids = list(profile_ids) if profile_ids else None
            if source_keys is not _UNSET:
                st.source_keys = list(source_keys) if source_keys else None
            s.flush()
            s.expunge(st)
            return st

    def status(self, now: datetime | None = None) -> dict[str, Any]:
        """État réel de la veille (jamais « en marche » si aucun processus ne bat)."""
        now = now or utcnow()
        st = self.get_state()
        beat_ok = st.heartbeat_at is not None and now - st.heartbeat_at < timedelta(seconds=max(90, self.settings.scheduler_tick_seconds * 3))
        lease_ok = st.lease_owner is not None and st.lease_expires_at is not None and st.lease_expires_at > now
        alive = bool(beat_ok and lease_ok)
        if not st.enabled:
            state = "disabled"
        elif alive:
            state = "running"
        else:
            state = "stopped"  # activée mais aucun processus ne la porte
        return {
            "enabled": st.enabled,
            "interval_minutes": st.interval_minutes,
            "profile_ids": st.profile_ids,
            "source_keys": st.source_keys,
            "next_run_at": st.next_run_at if st.enabled else None,
            "last_run_at": st.last_run_at,
            "last_run_id": st.last_run_id,
            "last_error": st.last_error,
            "alive": alive,
            "state": state,
            "heartbeat_at": st.heartbeat_at,
            "mode": self.settings.scheduler_mode,
            "this_process_is_leader": st.lease_owner == self.owner and lease_ok,
        }

    # ------------------------------------------------------------------ tick
    async def tick(self, now: datetime | None = None) -> str:
        now = now or utcnow()
        if not await asyncio.to_thread(self.acquire_lease, now):
            return "not_leader"
        await asyncio.to_thread(self.runs.reap_stale_runs, now=now)
        state = await asyncio.to_thread(self.get_state)
        if not state.enabled:
            return "disabled"
        interval = timedelta(minutes=state.interval_minutes)
        next_run = state.next_run_at
        if next_run is None:
            next_run = (state.last_run_at + interval) if state.last_run_at else now
            await asyncio.to_thread(self._set_next_run, next_run)
        if now < next_run:
            return "idle"
        if await asyncio.to_thread(self.runs.has_active_run, now=now):
            return "busy"  # reporté au tick suivant
        try:
            run_id = await asyncio.to_thread(
                self.runs.create_run,
                trigger=TriggerType.SCHEDULED,
                profile_ids=state.profile_ids,
                source_keys=state.source_keys,
                now=now,
            )
        except (NoSourcesError, RunError) as e:
            log.warning("veille : collecte non lancée : %s", e)
            await asyncio.to_thread(self._record_launch, None, now, now + interval, str(e))
            return "no_sources"
        self.runs.spawn(run_id)
        await asyncio.to_thread(self._record_launch, run_id, now, now + interval, None)
        log.info("veille : collecte planifiée lancée run_id=%s (prochaine à %s)", run_id, (now + interval).isoformat())
        return f"started:{run_id}"

    def _set_next_run(self, when: datetime) -> None:
        with self.db.session() as s:
            s.execute(update(SchedulerState).where(SchedulerState.id == 1).values(next_run_at=when))

    def _record_launch(self, run_id: int | None, now: datetime, next_run: datetime, error: str | None) -> None:
        with self.db.session() as s:
            values: dict[str, Any] = {"next_run_at": next_run, "last_error": error}
            if run_id is not None:
                values.update(last_run_at=now, last_run_id=run_id)
            s.execute(update(SchedulerState).where(SchedulerState.id == 1).values(**values))

    async def _safe_tick(self) -> None:
        try:
            await self.tick()
        except Exception:  # un tick raté ne doit jamais tuer le planificateur
            log.exception("veille : tick en erreur")

    # ------------------------------------------------------------------ cycle de vie
    async def start(self) -> None:
        await asyncio.to_thread(self.runs.reap_stale_runs)
        sched = AsyncIOScheduler(timezone="UTC")
        sched.add_job(
            self._safe_tick,
            "interval",
            seconds=self.settings.scheduler_tick_seconds,
            id="jobart-tick",
            max_instances=1,
            coalesce=True,
            next_run_time=utcnow() + timedelta(seconds=2),
        )
        sched.start()
        self._scheduler = sched
        log.info("planificateur démarré owner=%s tick=%ss", self.owner, self.settings.scheduler_tick_seconds)

    async def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        await asyncio.to_thread(self.release_lease)
