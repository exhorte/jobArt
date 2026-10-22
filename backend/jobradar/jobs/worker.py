"""Processus dédié à la veille automatique : `python -m jobradar.jobs.worker`.

À utiliser avec SCHEDULER_MODE=off côté API (l'API ne porte alors aucun planificateur) : la veille survit à un
redémarrage de l'API. Plusieurs workers (ou un worker + une API en mode « embedded ») ne se gênent pas : un seul détient
le bail en base et déclenche les collectes, les autres reprennent la main si le porteur s'arrête.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from ..core.config import Settings, get_settings
from ..core.db import Database
from ..core.log import setup_logging
from ..services.bootstrap import bootstrap
from ..services.runner import RunService
from .scheduler import SchedulerService

log = logging.getLogger(__name__)


async def run_worker(settings: Settings, *, stop: asyncio.Event | None = None) -> None:
    """Démarre la veille et attend `stop` (signal SIGINT/SIGTERM ou Ctrl+C) ; arrêt propre : bail rendu, collectes annulées."""
    stop = stop or asyncio.Event()
    db = Database(settings.database_url)
    try:
        with db.session() as s:
            info = bootstrap(s, sources_path=settings.sources_config_path, profiles_path=settings.profiles_config_path)
        log.info("initialisation : %s", info)
        runs = RunService(db, settings)
        sched = SchedulerService(db, runs, settings)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):  # Windows : Ctrl+C annule la tâche principale (asyncio.run)
                pass
        await sched.start()
        log.info("worker de veille démarré (owner=%s) ; Ctrl+C pour arrêter", sched.owner)
        try:
            await stop.wait()
        finally:
            log.info("arrêt du worker de veille")
            await sched.stop()
            await runs.shutdown()
    finally:
        db.dispose()


def main() -> int:
    settings = get_settings()
    setup_logging(settings.log_level)
    try:
        asyncio.run(run_worker(settings))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
