"""Moteur de collecte : exécutions (SearchRun) asynchrones, isolées par source.

Cycle d'une exécution :
  create_run (sync, rapide) → SearchRun « queued » + une ligne SearchRunSource par source → spawn(run_id) en tâche de fond
  execute_run : pour chaque source (concurrence bornée, timeouts) : verrou inter-processus → recherche → normalisation →
  persistance (déduplication, scores) → statistiques. Une erreur sur une source ne touche jamais les autres.
  Fin : agrégats, statut (completed | partial | failed), statuts de cycle de vie des annonces.

Le frontend suit l'avancement via GET /api/search-runs/{id} (aucune requête HTTP ne reste ouverte pendant la collecte).
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import or_, select, update

from ..collectors.base import Connector, HealthResult, NormalizedJob, SearchParameters
from ..collectors.http import HttpPool
from ..collectors.registry import CONNECTORS, UnknownConnector, build_connector
from ..core.clock import utcnow
from ..core.config import Settings
from ..core.db import Database
from ..core.errors import ErrorType, NormalizationError, SourceError
from ..models import (
    JobSource,
    RunSourceStatus,
    RunStatus,
    SearchProfile,
    SearchRun,
    SearchRunSource,
    TriggerType,
)
from .ingest import IngestStats, ingest_jobs, known_detail_url_keys, refresh_offer_statuses
from .scoring import ProfileCriteria

log = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 20


class RunError(Exception):
    """Erreur de demande de collecte (traduite en HTTP 4xx par l'API)."""


class NoSourcesError(RunError):
    pass


class UnknownSourceError(RunError):
    pass


class ProfileNotFound(RunError):
    pass


@dataclass
class SourceTask:
    run_source_id: int
    source_id: int
    source_key: str
    config: dict[str, Any]
    market: str
    countries: list[str]


@dataclass
class RunContext:
    run_id: int
    profiles: list[ProfileCriteria]
    explicit_sources: bool
    tasks: list[SourceTask] = field(default_factory=list)


def source_applies_to_profile(market: str, countries: list[str], profile: ProfileCriteria) -> bool:
    if market == "remote":
        return "remote" in profile.work_modes
    if not profile.countries or "*" in countries:
        return True
    return bool({c.upper() for c in countries} & {c.upper() for c in profile.countries})


def build_search_parameters(profiles: list[ProfileCriteria], config: dict[str, Any]) -> SearchParameters:
    """Union des profils applicables ; mots-clés entrelacés (le 1er de chaque profil d'abord) pour couvrir tous les
    profils même si la source plafonne le nombre de requêtes."""
    keywords: list[str] = []
    seen: set[str] = set()
    longest = max((len(p.positive_keywords) for p in profiles), default=0)
    for i in range(longest):
        for p in profiles:
            if i < len(p.positive_keywords):
                kw = p.positive_keywords[i].strip()
                if kw and kw.lower() not in seen:
                    seen.add(kw.lower())
                    keywords.append(kw)
    countries = list(dict.fromkeys(c.upper() for p in profiles for c in p.countries)) or ["SN"]
    cities = list(dict.fromkeys(c for p in profiles for c in p.cities))
    modes = list(dict.fromkeys(m for p in profiles for m in p.work_modes))
    return SearchParameters(
        keywords=keywords,
        countries=countries,
        cities=cities,
        work_modes=modes,
        max_pages=int(config.get("max_pages", 1)),
        max_queries=int(config.get("max_queries", 8)),
        detail_budget=int(config.get("detail_budget", 20)),
    )


class RunService:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        *,
        owner: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        connector_factory: Callable[[str, HttpPool, dict[str, Any] | None], Connector] = build_connector,
    ) -> None:
        self.db = db
        self.settings = settings
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._transport = transport
        self._factory = connector_factory
        self._pool: HttpPool | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------ ressources
    def pool(self) -> HttpPool:
        if self._pool is None:
            s = self.settings
            self._pool = HttpPool(
                user_agent=s.http_user_agent,
                timeout=s.request_timeout_seconds,
                max_response_bytes=s.max_response_bytes,
                default_min_delay=s.min_request_delay_seconds,
                transport=self._transport,
            )
        return self._pool

    async def shutdown(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None

    # ------------------------------------------------------------------ création
    def create_run(
        self,
        *,
        trigger: TriggerType | str = TriggerType.MANUAL,
        profile_id: int | None = None,
        source_keys: list[str] | None = None,
        profile_ids: list[int] | None = None,
        now: datetime | None = None,
    ) -> int:
        now = now or utcnow()
        with self.db.session() as s:
            if profile_id is not None:
                prof = s.get(SearchProfile, profile_id)
                if prof is None:
                    raise ProfileNotFound(f"profil {profile_id} introuvable")
                profiles = [ProfileCriteria.from_model(prof)]
            else:
                q = select(SearchProfile).where(SearchProfile.is_active.is_(True))
                if profile_ids:
                    q = q.where(SearchProfile.id.in_(profile_ids))
                profiles = [ProfileCriteria.from_model(p) for p in s.scalars(q.order_by(SearchProfile.id))]
            if source_keys:
                found = {x.source_key: x for x in s.scalars(select(JobSource).where(JobSource.source_key.in_(source_keys)))}
                unknown = [k for k in source_keys if k not in found]
                if unknown:
                    raise UnknownSourceError(f"source(s) inconnue(s) : {', '.join(unknown)}")
                not_impl = [k for k, v in found.items() if v.implementation != "implemented" or k not in CONNECTORS]
                if not_impl:
                    raise UnknownSourceError(
                        f"aucun connecteur pour : {', '.join(not_impl)} (voir la raison dans la page Sources)"
                    )
                sources = [found[k] for k in source_keys]
            else:
                sources = [
                    x
                    for x in s.scalars(select(JobSource).where(JobSource.enabled.is_(True)).order_by(JobSource.id))
                    if x.source_key in CONNECTORS and x.implementation == "implemented"
                ]
                if profiles:
                    sources = [x for x in sources if any(source_applies_to_profile(x.market, x.countries, p) for p in profiles)]
            if not sources:
                raise NoSourcesError("aucune source activée concernée par cette recherche")
            run = SearchRun(
                started_at=now,
                heartbeat_at=now,
                trigger_type=str(trigger.value if isinstance(trigger, TriggerType) else trigger),
                status=RunStatus.QUEUED.value,
                profile_id=profile_id,
                owner=self.owner,
                requested_source_keys=[x.source_key for x in sources] if source_keys else None,
                sources_requested=len(sources),
            )
            s.add(run)
            s.flush()
            for src in sources:
                s.add(SearchRunSource(search_run_id=run.id, job_source_id=src.id, status=RunSourceStatus.PENDING.value))
            return run.id

    def spawn(self, run_id: int) -> asyncio.Task[None]:
        task = asyncio.get_running_loop().create_task(self.execute_run(run_id), name=f"search-run-{run_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def active_run_id(self, *, now: datetime | None = None) -> int | None:
        """Identifiant d'une exécution en cours (battement de cœur récent), sinon None."""
        now = now or utcnow()
        cutoff = now - timedelta(seconds=self.settings.run_stale_after_seconds)
        with self.db.session() as s:
            return s.scalar(
                select(SearchRun.id)
                .where(SearchRun.status.in_([RunStatus.QUEUED.value, RunStatus.RUNNING.value]), SearchRun.heartbeat_at >= cutoff)
                .order_by(SearchRun.id.desc())
                .limit(1)
            )

    def has_active_run(self, *, now: datetime | None = None) -> bool:
        now = now or utcnow()
        cutoff = now - timedelta(seconds=self.settings.run_stale_after_seconds)
        with self.db.session() as s:
            return (
                s.scalar(
                    select(SearchRun.id)
                    .where(SearchRun.status.in_([RunStatus.QUEUED.value, RunStatus.RUNNING.value]), SearchRun.heartbeat_at >= cutoff)
                    .limit(1)
                )
                is not None
            )

    def reap_stale_runs(self, *, now: datetime | None = None) -> int:
        """Déclare « interrompues » les exécutions sans battement de cœur récent (processus arrêté/planté)."""
        now = now or utcnow()
        cutoff = now - timedelta(seconds=self.settings.run_stale_after_seconds)
        n = 0
        with self.db.session() as s:
            stale = s.scalars(
                select(SearchRun).where(
                    SearchRun.status.in_([RunStatus.QUEUED.value, RunStatus.RUNNING.value]),
                    or_(SearchRun.heartbeat_at.is_(None), SearchRun.heartbeat_at < cutoff),
                )
            ).all()
            for run in stale:
                run.status = RunStatus.INTERRUPTED.value
                run.finished_at = now
                run.error_summary = "Exécution interrompue : le processus porteur s'est arrêté (reprise au prochain déclenchement)."
                for rs in s.scalars(select(SearchRunSource).where(SearchRunSource.search_run_id == run.id)):
                    if rs.status in (RunSourceStatus.PENDING.value, RunSourceStatus.RUNNING.value):
                        rs.status = RunSourceStatus.FAILED.value
                        rs.error_type = ErrorType.INTERNAL
                        rs.error_message = "interrompue (processus arrêté)"
                        rs.finished_at = now
                n += 1
        return n

    # ------------------------------------------------------------------ exécution
    async def execute_run(self, run_id: int) -> None:
        hb: asyncio.Task[None] | None = None
        try:
            ctx = await asyncio.to_thread(self._begin_run, run_id)
            hb = asyncio.create_task(self._heartbeat(run_id))
            sem = asyncio.Semaphore(self.settings.collect_max_concurrency)
            await asyncio.gather(*[self._run_source(ctx, t, sem) for t in ctx.tasks])
            await asyncio.to_thread(self._finish_run, run_id, None)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self._finish_run, run_id, "Exécution interrompue (arrêt de l'application)."))
            raise
        except Exception as e:  # défaut du moteur lui-même (jamais une erreur de source)
            log.exception("exécution %s : erreur interne", run_id)
            await asyncio.to_thread(self._finish_run, run_id, f"Erreur interne du moteur : {type(e).__name__}: {e}"[:500])
        finally:
            if hb:
                hb.cancel()

    async def _heartbeat(self, run_id: int) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await asyncio.to_thread(self._touch_run, run_id)

    def _touch_run(self, run_id: int) -> None:
        with self.db.session() as s:
            s.execute(update(SearchRun).where(SearchRun.id == run_id).values(heartbeat_at=utcnow()))

    def _begin_run(self, run_id: int) -> RunContext:
        with self.db.session() as s:
            run = s.get(SearchRun, run_id)
            assert run is not None
            run.status = RunStatus.RUNNING.value
            run.heartbeat_at = utcnow()
            explicit = run.requested_source_keys is not None
            if run.profile_id is not None:
                prof = s.get(SearchProfile, run.profile_id)
                profiles = [ProfileCriteria.from_model(prof)] if prof else []
            else:
                active = select(SearchProfile).where(SearchProfile.is_active.is_(True)).order_by(SearchProfile.id)
                profiles = [ProfileCriteria.from_model(p) for p in s.scalars(active)]
            ctx = RunContext(run_id=run_id, profiles=profiles, explicit_sources=explicit)
            for rs in s.scalars(select(SearchRunSource).where(SearchRunSource.search_run_id == run_id).order_by(SearchRunSource.id)):
                src = s.get(JobSource, rs.job_source_id)
                assert src is not None
                ctx.tasks.append(SourceTask(rs.id, src.id, src.source_key, dict(src.configuration or {}), src.market, list(src.countries or [])))
            return ctx

    def _set_source_state(self, run_source_id: int, **values: Any) -> None:
        with self.db.session() as s:
            s.execute(update(SearchRunSource).where(SearchRunSource.id == run_source_id).values(**values))

    def _acquire_lock(self, source_id: int, lock_owner: str) -> bool:
        ttl = timedelta(seconds=self.settings.source_timeout_seconds + 60)
        now = utcnow()
        with self.db.session() as s:
            res = s.execute(
                update(JobSource)
                .where(
                    JobSource.id == source_id,
                    or_(JobSource.lock_owner.is_(None), JobSource.lock_owner == lock_owner, JobSource.lock_expires_at < now),
                )
                .values(lock_owner=lock_owner, lock_expires_at=now + ttl)
            )
            return res.rowcount == 1

    def _release_lock(self, source_id: int, lock_owner: str) -> None:
        with self.db.session() as s:
            s.execute(
                update(JobSource).where(JobSource.id == source_id, JobSource.lock_owner == lock_owner).values(lock_owner=None, lock_expires_at=None)
            )

    def _prepare_source(self, ctx: RunContext, task: SourceTask) -> tuple[SearchParameters | None, str | None]:
        """(paramètres, raison de saut). Charge aussi les URLs dont le détail est déjà connu."""
        if ctx.explicit_sources:
            applicable = ctx.profiles
        else:
            applicable = [p for p in ctx.profiles if source_applies_to_profile(task.market, task.countries, p)]
        if ctx.profiles and not applicable:
            return None, "aucun profil actif concerné par cette source"
        min_interval = int(task.config.get("min_interval_minutes", 0) or 0)
        with self.db.session() as s:
            src = s.get(JobSource, task.source_id)
            assert src is not None
            if min_interval and src.last_success_at and utcnow() - src.last_success_at < timedelta(minutes=min_interval):
                nxt = src.last_success_at + timedelta(minutes=min_interval)
                return None, f"collectée récemment ; intervalle minimal de {min_interval} min imposé par la source (prochaine : {nxt:%H:%M} UTC)"
            params = build_search_parameters(applicable, task.config)
            params.known_urls = known_detail_url_keys(s, src)
        return params, None

    async def _run_source(self, ctx: RunContext, task: SourceTask, sem: asyncio.Semaphore) -> None:
        lock_owner = f"{self.owner}:run{ctx.run_id}"
        async with sem:
            started = utcnow()
            await asyncio.to_thread(self._set_source_state, task.run_source_id, status=RunSourceStatus.RUNNING.value, started_at=started)
            if not await asyncio.to_thread(self._acquire_lock, task.source_id, lock_owner):
                await asyncio.to_thread(
                    self._finalize_source, task, started, RunSourceStatus.SKIPPED, ErrorType.LOCKED,
                    "une autre collecte est déjà en cours sur cette source", None, {}, False,
                )
                return
            connector: Connector | None = None
            try:
                params, skip = await asyncio.to_thread(self._prepare_source, ctx, task)
                if skip or params is None:
                    await asyncio.to_thread(
                        self._finalize_source, task, started, RunSourceStatus.SKIPPED, ErrorType.SKIPPED_RECENT, skip, None, {}, False
                    )
                    return
                connector = self._factory(task.source_key, self.pool(), task.config)
                t0 = time.monotonic()
                raws = await asyncio.wait_for(connector.search(params), timeout=self.settings.source_timeout_seconds)
                jobs: list[NormalizedJob] = []
                rejected: list[str] = []
                for raw in raws:
                    try:
                        jobs.append(connector.normalize(raw))
                    except NormalizationError as e:
                        rejected.append(str(e)[:200])
                    except Exception as e:  # défaut d'un seul enregistrement : isolé
                        rejected.append(f"{type(e).__name__}: {e}"[:200])
                stats = await asyncio.to_thread(self._persist, task.source_id, jobs, ctx.profiles)
                details = {
                    "queries": connector.queries(params),
                    "warnings": connector.warnings[:10],
                    "rejected_samples": rejected[:5],
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "empty": len(raws) == 0,
                }
                stats_dict = {
                    "found": stats.found, "created": stats.created, "updated": stats.updated,
                    "duplicates": stats.duplicates, "rejected": len(rejected),
                }
                await asyncio.to_thread(
                    self._finalize_source, task, started, RunSourceStatus.SUCCESS, None, None, stats_dict, details, True,
                    connector.http.requests_made,
                )
            except asyncio.CancelledError:
                raise
            except SourceError as e:
                log.warning("source %s : %s — %s", task.source_key, e.error_type, e)
                await asyncio.to_thread(
                    self._finalize_source, task, started, RunSourceStatus.FAILED, e.error_type, str(e)[:900], None,
                    {"warnings": (connector.warnings[:10] if connector else [])}, False, (connector.http.requests_made if connector else 0),
                )
            except TimeoutError:
                await asyncio.to_thread(
                    self._finalize_source, task, started, RunSourceStatus.FAILED, ErrorType.TIMEOUT,
                    f"délai global dépassé ({int(self.settings.source_timeout_seconds)} s)", None, {}, False,
                    (connector.http.requests_made if connector else 0),
                )
            except UnknownConnector as e:
                await asyncio.to_thread(
                    self._finalize_source, task, started, RunSourceStatus.FAILED, ErrorType.INTERNAL, f"connecteur introuvable : {e}", None, {}, False
                )
            except Exception as e:  # jamais propagé : les autres sources continuent
                log.exception("source %s : erreur inattendue", task.source_key)
                await asyncio.to_thread(
                    self._finalize_source, task, started, RunSourceStatus.FAILED, ErrorType.INTERNAL,
                    f"{type(e).__name__}: {e}"[:900], None, {}, False,
                )
            finally:
                await asyncio.shield(asyncio.to_thread(self._release_lock, task.source_id, lock_owner))

    def _persist(self, source_id: int, jobs: list[NormalizedJob], profiles: list[ProfileCriteria]) -> IngestStats:
        with self.db.session() as s:
            src = s.get(JobSource, source_id)
            assert src is not None
            return ingest_jobs(s, src, jobs, profiles, now=utcnow())

    def _finalize_source(
        self,
        task: SourceTask,
        started: datetime,
        status: RunSourceStatus,
        error_type: str | None,
        error_message: str | None,
        stats: dict[str, int] | None,
        details: dict[str, Any],
        success: bool,
        requests_made: int = 0,
    ) -> None:
        now = utcnow()
        stats = stats or {}
        with self.db.session() as s:
            s.execute(
                update(SearchRunSource)
                .where(SearchRunSource.id == task.run_source_id)
                .values(
                    status=status.value,
                    finished_at=now,
                    offers_found=stats.get("found", 0),
                    offers_created=stats.get("created", 0),
                    offers_updated=stats.get("updated", 0),
                    duplicates_detected=stats.get("duplicates", 0),
                    offers_rejected=stats.get("rejected", 0),
                    requests_made=requests_made,
                    error_type=error_type,
                    error_message=error_message,
                    details=details,
                )
            )
            src = s.get(JobSource, task.source_id)
            if src is not None and status != RunSourceStatus.SKIPPED:
                src.last_run_at = now
                src.last_run_status = status.value
                if success:
                    src.last_success_at = now
                    src.last_error = None
                    src.last_error_type = None
                    src.last_check_ok = True
                else:
                    src.last_error = error_message
                    src.last_error_type = error_type

    def _finish_run(self, run_id: int, fatal: str | None) -> None:
        now = utcnow()
        with self.db.session() as s:
            run = s.get(SearchRun, run_id)
            if run is None:
                return
            rows = s.scalars(select(SearchRunSource).where(SearchRunSource.search_run_id == run_id)).all()
            for rs in rows:  # sources restées en cours (annulation) → interrompues
                if rs.status in (RunSourceStatus.PENDING.value, RunSourceStatus.RUNNING.value):
                    rs.status = RunSourceStatus.FAILED.value
                    rs.error_type = ErrorType.INTERNAL
                    rs.error_message = fatal or "interrompue"
                    rs.finished_at = now
            ok = [r for r in rows if r.status == RunSourceStatus.SUCCESS.value]
            bad = [r for r in rows if r.status == RunSourceStatus.FAILED.value]
            skipped = [r for r in rows if r.status == RunSourceStatus.SKIPPED.value]
            run.sources_succeeded = len(ok)
            run.sources_failed = len(bad)
            run.offers_found = sum(r.offers_found for r in rows)
            run.offers_created = sum(r.offers_created for r in rows)
            run.offers_updated = sum(r.offers_updated for r in rows)
            run.duplicates_detected = sum(r.duplicates_detected for r in rows)
            run.finished_at = now
            run.heartbeat_at = now
            if fatal and run.status != RunStatus.INTERRUPTED.value:
                run.status = RunStatus.INTERRUPTED.value if "interrompue" in fatal.lower() else RunStatus.FAILED.value
            elif not bad:
                run.status = RunStatus.COMPLETED.value
            elif not ok:
                run.status = RunStatus.FAILED.value
            else:
                run.status = RunStatus.PARTIAL.value
            names = {x.id: x.source_key for x in s.scalars(select(JobSource).where(JobSource.id.in_([r.job_source_id for r in rows])))}
            parts = [f"{names.get(r.job_source_id)}: {r.error_type} — {(r.error_message or '')[:100]}" for r in bad + skipped]
            summary = "; ".join(parts)
            run.error_summary = (fatal + (" | " + summary if summary else "")) if fatal else (summary or None)
            if run.error_summary:
                run.error_summary = run.error_summary[:1500]
            refresh_offer_statuses(s, now)

    # ------------------------------------------------------------------ test d'une source (sans enregistrement)
    async def test_source(self, source_key: str) -> HealthResult:
        with self.db.session() as s:
            src = s.scalar(select(JobSource).where(JobSource.source_key == source_key))
            if src is None:
                raise UnknownSourceError(f"source inconnue : {source_key}")
            if src.implementation != "implemented" or source_key not in CONNECTORS:
                raise UnknownSourceError("aucun connecteur pour cette source (voir la raison dans la page Sources)")
            config = dict(src.configuration or {})
            source_id = src.id
        connector = self._factory(source_key, self.pool(), config)
        try:
            result = await asyncio.wait_for(connector.health_check(), timeout=60)
        except TimeoutError:
            result = HealthResult(ok=False, status="unreachable", detail="délai dépassé pendant le test")
        now = utcnow()

        def save() -> None:
            with self.db.session() as s:
                src = s.get(JobSource, source_id)
                if src is not None:
                    src.last_checked_at = now
                    src.last_check_ok = result.ok
                    if not result.ok:
                        src.last_error = result.detail[:900]
                        src.last_error_type = {"blocked": ErrorType.BLOCKED, "robots": ErrorType.ROBOTS, "unreachable": ErrorType.NETWORK,
                                               "changed": ErrorType.PARSE}.get(result.status, ErrorType.UNAVAILABLE)

        await asyncio.to_thread(save)
        return result
