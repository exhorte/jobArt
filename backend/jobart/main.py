"""Application FastAPI jobArt (mono-utilisateur).

Sécurité : en local, pas d'authentification → l'API écoute sur 127.0.0.1 par défaut. Pour l'exposer sur Internet, définir
`API_TOKEN` : toute route sauf `/api/health` exige alors `Authorization: Bearer <API_TOKEN>` (voir `api/security.py`), et la
documentation interactive est coupée. CORS restreint à l'origine du frontend configurée.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import health, offers, profiles, runs, scheduler, sources
from .api.security import require_api_token
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
        dependencies=[Depends(require_api_token)],
        # La dépendance ne couvre pas ces routes : avec un jeton, on coupe la documentation et le schéma.
        docs_url=None if settings.api_token else "/docs",
        redoc_url=None if settings.api_token else "/redoc",
        openapi_url=None if settings.api_token else "/openapi.json",
    )
    app.state.settings = settings  # lu par la dépendance de jeton, y compris hors lifespan
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
