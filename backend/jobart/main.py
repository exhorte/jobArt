"""Application FastAPI jobArt (mono-utilisateur, usage local).

Sécurité : pas d'authentification (outil personnel local) → l'API écoute sur 127.0.0.1 par défaut ; ne pas l'exposer
sur Internet sans reverse-proxy authentifié (voir README). CORS restreint à l'origine du frontend configurée.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import health, offers, profiles, runs, scheduler, sources
from .core.config import Settings, get_settings
from .core.db import Database
from .core.log import setup_logging
from .jobs.scheduler import SchedulerService
from .services.bootstrap import bootstrap
from .services.runner import RunService

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, database: Database | None = None, run_service: RunService | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = database or Database(settings.database_url)
        app.state.db = db
        app.state.settings = settings
        with db.session() as s:
            info = bootstrap(s, sources_path=settings.sources_config_path, profiles_path=settings.profiles_config_path)
        log.info("initialisation : %s", info)
        runs = run_service or RunService(db, settings)
        sched = SchedulerService(db, runs, settings)
        app.state.runs = runs
        app.state.scheduler = sched
        runs.reap_stale_runs()
        if settings.scheduler_mode == "embedded":
            await sched.start()
        else:
            log.info("SCHEDULER_MODE=off : la veille doit être portée par `python -m jobart.jobs.worker`")
        try:
            yield
        finally:
            if settings.scheduler_mode == "embedded":
                await sched.stop()
            await runs.shutdown()
            if database is None:
                db.dispose()

    app = FastAPI(
        title="jobArt API",
        version=__version__,
        description="Agrégateur personnel d'offres d'emploi : collecte, normalisation, déduplication, score, veille.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    for module in (health, sources, profiles, offers, runs, scheduler):
        app.include_router(module.router)
    return app


app = create_app()
