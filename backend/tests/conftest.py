"""Fixtures de test.

Par défaut les tests tournent sur SQLite (fichier temporaire, aucun service externe requis). Pour valider sur
PostgreSQL : `TEST_DATABASE_URL=postgresql+psycopg://... pytest` (le schéma de la base indiquée est recréé à chaque test :
utiliser une base DÉDIÉE aux tests). Aucun test n'accède à Internet sauf ceux marqués `network` (exclus par défaut).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from jobradar.collectors.base import Connector, HealthResult, NormalizedJob, RawJob, SearchParameters
from jobradar.collectors.http import HttpPool, PoliteClient
from jobradar.core.config import REPO_ROOT, Settings
from jobradar.core.db import Database
from jobradar.models import Base, JobSource, SearchProfile
from jobradar.services.bootstrap import bootstrap, ensure_scheduler_state

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str) -> Any:
    return json.loads(fixture_text(name))


@pytest.fixture()
def settings(tmp_path: pathlib.Path) -> Settings:
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'jobradar_test.sqlite'}"
    return Settings(
        database_url=url,
        scheduler_mode="off",
        config_dir=REPO_ROOT / "config",
        min_request_delay_seconds=0.0,
        collect_max_concurrency=3,
        source_timeout_seconds=5.0,
        run_stale_after_seconds=120,
        scheduler_tick_seconds=1,
        scheduler_lease_ttl_seconds=30,
        log_level="WARNING",
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture()
def db(settings: Settings) -> Iterator[Database]:
    database = Database(settings.database_url)
    Base.metadata.drop_all(database.engine)
    Base.metadata.create_all(database.engine)
    yield database
    Base.metadata.drop_all(database.engine)
    database.dispose()


@pytest.fixture()
def session(db: Database) -> Iterator[Any]:
    with db.session() as s:
        yield s


@pytest.fixture()
def seeded(db: Database, settings: Settings) -> Database:
    """Base avec sources (config/sources.yaml), profils par défaut et état de la veille."""
    with db.session() as s:
        bootstrap(s, sources_path=settings.sources_config_path, profiles_path=settings.profiles_config_path)
    return db


def make_source(session, key: str = "src_a", *, enabled: bool = True, market: str = "local", countries: list[str] | None = None,
                config: dict[str, Any] | None = None, implementation: str = "implemented") -> JobSource:
    src = JobSource(
        source_key=key, name=key.upper(), base_url=f"https://{key}.example.com/", source_type="job_board", market=market,
        countries=countries if countries is not None else ["SN"], enabled=enabled, collection_method="html",
        implementation=implementation, configuration=config or {},
    )
    session.add(src)
    session.flush()
    return src


def make_profile(session, name: str = "Test", **kw: Any) -> SearchProfile:
    defaults: dict[str, Any] = dict(
        countries=["SN"], cities=["Dakar"], positive_keywords=["Software Engineer", "Développeur"],
        keyword_groups={"Langages": ["Python", "TypeScript"], "Plateforme": ["Docker", "FastAPI"]},
        excluded_keywords=[], target_roles=["Software Engineer"], sectors=[], contract_types=["cdi", "cdd"],
        work_modes=["onsite", "hybrid", "remote"], experience_levels=["junior", "mid"], is_active=True,
    )
    defaults.update(kw)
    p = SearchProfile(name=name, **defaults)
    session.add(p)
    session.flush()
    return p


def make_job(**kw: Any) -> NormalizedJob:
    base: dict[str, Any] = dict(
        source_key="src_a", source_job_id=kw.pop("source_job_id", None) or uuid.uuid4().hex[:8],
        url="https://src_a.example.com/offres/dev-python-1", title="Développeur Python", company_name="Acme",
        city="Dakar", country="SN", location="Dakar, Sénégal", contract_type="cdi",
    )
    base.update(kw)
    return NormalizedJob(**base)


# ---------------------------------------------------------------- HTTP simulé
def make_pool(handler: Callable[[httpx.Request], httpx.Response], **kw: Any) -> HttpPool:
    return HttpPool(
        user_agent="JobRadar-test/0.1", timeout=5, default_min_delay=0.0,
        transport=httpx.MockTransport(handler), **kw,
    )


def make_client(pool: HttpPool, connector_cls: type[Connector], **kw: Any) -> PoliteClient:
    return PoliteClient(pool, source_key=connector_cls.source_key, allowed_hosts=connector_cls.allowed_hosts, min_delay=0.0, **kw)


def text_response(body: str, status: int = 200, ctype: str = "text/html; charset=utf-8") -> httpx.Response:
    return httpx.Response(status, content=body.encode("utf-8"), headers={"content-type": ctype})


def json_response(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(data).encode("utf-8"), headers={"content-type": "application/json"})


def route(routes: dict[str, Callable[[httpx.Request], httpx.Response] | httpx.Response]) -> Callable[[httpx.Request], httpx.Response]:
    """Transport simulé : `routes` associe un motif regex (sur `host+path`) à une réponse ou fonction. robots.txt → 404."""
    compiled = [(re.compile(p), r) for p, r in routes.items()]

    def handler(request: httpx.Request) -> httpx.Response:
        target = f"{request.url.host}{request.url.path}"
        if request.url.path == "/robots.txt" and not any(p.search(target) for p, _ in compiled):
            return httpx.Response(404, content=b"not found")
        for pattern, resp in compiled:
            if pattern.search(target):
                return resp(request) if callable(resp) else resp
        return httpx.Response(404, content=b"no route in test: " + target.encode())

    return handler


# ---------------------------------------------------------------- faux connecteurs (moteur de collecte)
class FakeConnector(Connector):
    """Connecteur de test : comportement piloté par `config` ({"jobs": [...], "raise": "...", "sleep": s})."""

    source_key = "fake"
    source_name = "Fake"
    source_url = "https://fake.example.com/"
    allowed_hosts = {"fake.example.com"}
    calls: list[str] = []

    async def search(self, params: SearchParameters) -> list[RawJob]:
        import asyncio

        from jobradar.core import errors

        FakeConnector.calls.append(self.config.get("key", "?"))
        if self.config.get("sleep"):
            await asyncio.sleep(float(self.config["sleep"]))
        if exc := self.config.get("raise"):
            raise getattr(errors, exc)("boom (test)")
        if self.config.get("crash"):
            raise RuntimeError("bug inattendu (test)")
        self.http.requests_made += int(self.config.get("requests", 1))
        self.warnings.extend(self.config.get("warnings", []))
        return [RawJob(data=j) for j in self.config.get("jobs", [])]

    def normalize(self, raw: RawJob) -> NormalizedJob:
        from jobradar.core.errors import NormalizationError

        d = dict(raw.data)
        if d.pop("_invalid", False):
            raise NormalizationError("annonce invalide (test)")
        for k in ("published_at", "application_deadline", "verified_at"):  # la configuration est du JSON : dates en ISO
            if isinstance(d.get(k), str):
                d[k] = datetime.fromisoformat(d[k])
        return NormalizedJob(source_key=self.config.get("key", "fake"), **d)

    async def health_check(self) -> HealthResult:
        if self.config.get("raise"):
            return HealthResult(ok=False, status="blocked", detail="bloqué (test)")
        return HealthResult(ok=True, status="ok", detail="ok (test)", sample_count=len(self.config.get("jobs", [])))


def fake_factory(pool: HttpPool, key: str, config: dict[str, Any] | None) -> Connector:
    cfg = dict(config or {})
    cfg["key"] = key
    client = PoliteClient(pool, source_key=key, allowed_hosts={"fake.example.com"}, min_delay=0.0)
    return FakeConnector(client, cfg)


@pytest.fixture(autouse=True)
def _reset_fake_calls() -> None:
    FakeConnector.calls = []


def job_dict(i: int, **kw: Any) -> dict[str, Any]:
    d: dict[str, Any] = dict(
        source_job_id=f"id{i}", url=f"https://fake.example.com/jobs/{i}", title=f"Développeur Python {i}",
        company_name=f"Societe {i}", city="Dakar", country="SN", location="Dakar, Sénégal", contract_type="cdi",
        description="Python FastAPI Docker TypeScript " * 5, published_at=NOW.replace(day=20),
    )
    d.update(kw)
    return d


def json_jobs(start: int, n: int = 3, **kw: Any) -> list[dict[str, Any]]:
    """Annonces simulées sérialisables en JSON (la configuration d'une source est une colonne JSON : dates en ISO)."""
    out = []
    for i in range(start, start + n):
        d = job_dict(i, **kw)
        d["published_at"] = d["published_at"].isoformat()
        out.append(d)
    return out


def sources_in(session) -> dict[str, JobSource]:
    return {s.source_key: s for s in session.scalars(select(JobSource))}


@pytest.fixture()
def state_row(db: Database) -> None:
    with db.session() as s:
        ensure_scheduler_state(s)
