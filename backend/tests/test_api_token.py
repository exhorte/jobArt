"""Jeton d'accès à l'API, secours contre un déploiement ouvert, normalisation de l'URL de base."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from jobart.core.config import Settings
from jobart.core.db import Database
from jobart.main import create_app

TOKEN = "jeton-de-test-0123456789"


@pytest.fixture()
def client_for(db: Database, settings: Settings) -> Iterator[Callable[[str], TestClient]]:
    opened: list[TestClient] = []

    def make(api_token: str) -> TestClient:
        app = create_app(settings.model_copy(update={"api_token": api_token}), database=db)
        client = TestClient(app)
        client.__enter__()
        opened.append(client)
        return client

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def test_sans_jeton_configure_l_api_reste_ouverte(client_for: Callable[[str], TestClient]) -> None:
    client = client_for("")
    assert client.get("/api/meta").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_avec_jeton_les_routes_exigent_l_en_tete(client_for: Callable[[str], TestClient]) -> None:
    client = client_for(TOKEN)
    assert client.get("/api/meta").status_code == 401
    assert client.get("/api/meta").headers["www-authenticate"] == "Bearer"
    assert client.get("/api/meta", headers=bearer("mauvais")).status_code == 401
    assert client.get("/api/meta", headers=bearer(TOKEN[:-1])).status_code == 401
    assert client.get("/api/meta", headers={"Authorization": f"Basic {TOKEN}"}).status_code == 401
    assert client.get("/api/meta", headers=bearer(TOKEN)).status_code == 200


def test_toutes_les_methodes_sont_protegees(client_for: Callable[[str], TestClient]) -> None:
    client = client_for(TOKEN)
    assert client.get("/api/search-profiles").status_code == 401
    assert client.post("/api/search-runs", json={}).status_code == 401
    assert client.patch("/api/settings/scheduler", json={}).status_code == 401
    assert client.delete("/api/search-profiles/1").status_code == 401
    assert client.post("/api/sources/emploi_dakar/collect").status_code == 401
    assert client.get("/api/search-profiles", headers=bearer(TOKEN)).status_code == 200


def test_la_sante_reste_libre_et_la_documentation_est_coupee(client_for: Callable[[str], TestClient]) -> None:
    client = client_for(TOKEN)
    assert client.get("/api/health").status_code == 200
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404


def test_un_deploiement_exige_un_jeton(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError, match="API_TOKEN est obligatoire"):
        Settings(require_api_token=True, api_token="", _env_file=None)  # type: ignore[call-arg]
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(ValidationError, match="API_TOKEN est obligatoire"):
        Settings(_env_file=None)  # type: ignore[call-arg]
    assert Settings(api_token=TOKEN, _env_file=None).api_token == TOKEN  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgresql://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("sqlite:///x.sqlite", "sqlite:///x.sqlite"),
    ],
)
def test_url_de_base_normalisee(given: str, expected: str) -> None:
    assert Settings(database_url=given, _env_file=None).database_url == expected  # type: ignore[call-arg]
