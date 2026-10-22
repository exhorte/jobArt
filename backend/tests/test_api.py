"""API HTTP (FastAPI TestClient) : santé, sources, profils, annonces, exécutions, veille.

Les collectes passent par le vrai moteur avec des connecteurs simulés (aucun accès réseau).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from jobart.core.config import Settings
from jobart.core.db import Database
from jobart.main import create_app
from jobart.models import JobSource
from jobart.services.runner import RunService

from .conftest import fake_factory
from .conftest import json_jobs as jobs

A, B = "emploi_dakar", "emploisenegal"


@pytest.fixture()
def client(db: Database, settings: Settings) -> Iterator[TestClient]:
    runs = RunService(db, settings, owner="api-test", connector_factory=lambda k, p, c: fake_factory(p, k, c))
    app = create_app(settings, database=db, run_service=runs)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def configure(db: Database, client: TestClient):
    """configure(emploi_dakar={"jobs": [...]}) : scénario simulé des sources (les sources existent après le démarrage)."""

    def apply(**per_source: dict[str, Any]) -> None:
        with db.session() as s:
            for key, cfg in per_source.items():
                s.scalar(select(JobSource).where(JobSource.source_key == key)).configuration = dict(cfg)

    return apply


def wait_run(client: TestClient, run_id: int, timeout: float = 20) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/search-runs/{run_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"exécution {run_id} non terminée après {timeout} s")


def collect(client: TestClient, **body: Any) -> dict[str, Any]:
    r = client.post("/api/search-runs", json=body)
    assert r.status_code == 202, r.text
    return wait_run(client, r.json()["id"])


@pytest.fixture()
def populated(client: TestClient, configure) -> dict[str, Any]:
    """Trois annonces collectées via l'API sur une source."""
    configure(**{A: {"jobs": jobs(1, 3)}})
    run = collect(client, source_keys=[A])
    assert run["status"] == "completed" and run["offers_created"] == 3
    return run


# ------------------------------------------------------------------------------------------------ système
def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["database"] == "ok" and body["version"]
    assert body["scheduler"]["state"] == "disabled" and body["scheduler"]["mode"] == "off"


def test_meta(client: TestClient) -> None:
    body = client.get("/api/meta").json()
    assert "cdi" in body["contract_types"] and body["work_modes"] == ["onsite", "hybrid", "remote"]
    assert "SN" in body["countries"] and set(body["user_statuses"]) == {"new", "seen", "saved", "applied", "ignored"}
    assert body["weights"]["default"] and body["weights"]["labels"]


def test_dashboard_empty_then_populated(client: TestClient, populated: dict[str, Any]) -> None:
    body = client.get("/api/dashboard").json()
    assert body["total_offers"] == 3 and body["new_offers"] == 3 and body["detected_24h"] == 3
    assert body["last_run"]["status"] == "completed" and body["total_connectors"] >= 10
    assert body["scheduler"]["state"] == "disabled" and len(body["top_matches"]) == 3 and body["by_source"][0]["key"] == A


def test_cors_only_for_configured_origin(client: TestClient, settings: Settings) -> None:
    ok = client.options("/api/health", headers={"Origin": settings.cors_origin_list[0], "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == settings.cors_origin_list[0]
    bad = client.options("/api/health", headers={"Origin": "https://evil.example.org", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


# ------------------------------------------------------------------------------------------------ sources
def test_list_and_get_sources(client: TestClient) -> None:
    items = client.get("/api/sources").json()
    by_key = {s["key"]: s for s in items}
    assert by_key[A]["can_collect"] is True and by_key[A]["implementation"] == "implemented"
    assert by_key["senejobs"]["can_collect"] is False and by_key["senejobs"]["enabled"] is False
    assert by_key["linkedin_jobs"]["decision_reason"]  # la raison de l'exclusion est exposée
    assert client.get(f"/api/sources/{A}").json()["name"] == by_key[A]["name"]
    assert client.get("/api/sources/nexiste_pas").status_code == 404


def test_toggle_source(client: TestClient) -> None:
    r = client.patch(f"/api/sources/{A}", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert client.patch(f"/api/sources/{A}", json={"enabled": True}).json()["enabled"] is True
    r = client.patch("/api/sources/senejobs", json={"enabled": True})  # sans connecteur : refus explicite
    assert r.status_code == 409
    assert client.patch("/api/sources/nexiste_pas", json={"enabled": True}).status_code == 404
    assert client.patch(f"/api/sources/{A}", json={}).status_code == 422


def test_source_test_endpoint(client: TestClient, configure, db: Database) -> None:
    configure(**{A: {"jobs": jobs(1, 2)}, B: {"raise": "AccessBlocked"}})
    ok = client.post(f"/api/sources/{A}/test")
    assert ok.status_code == 200 and ok.json()["ok"] is True and ok.json()["sample_count"] == 2
    ko = client.post(f"/api/sources/{B}/test").json()
    assert ko["ok"] is False and ko["status"] == "blocked"
    assert client.get(f"/api/sources/{B}").json()["last_check_ok"] is False
    assert client.get("/api/offers").json()["total"] == 0  # un test n'enregistre rien
    assert client.post("/api/sources/senejobs/test").status_code == 409
    assert client.post("/api/sources/nexiste_pas/test").status_code == 404


def test_collect_single_source(client: TestClient, configure) -> None:
    configure(**{A: {"jobs": jobs(1, 2)}})
    r = client.post(f"/api/sources/{A}/collect")
    assert r.status_code == 202 and r.json()["status"] == "queued"
    run = wait_run(client, r.json()["id"])
    assert run["status"] == "completed" and run["source_keys"] == [A] and run["offers_created"] == 2
    assert client.get(f"/api/sources/{A}").json()["offers_count"] == 2
    assert client.post("/api/sources/senejobs/collect").status_code == 409
    assert client.post("/api/sources/nexiste_pas/collect").status_code == 404


def test_employers_registry(client: TestClient) -> None:
    items = client.get("/api/employers").json()
    assert items and all(e["key"] and e["name"] for e in items)


# ------------------------------------------------------------------------------------------------ exécutions
def test_run_lifecycle_and_listing(client: TestClient, configure) -> None:
    configure(**{A: {"jobs": jobs(1, 3)}, B: {"raise": "NetworkError"}})
    run = collect(client, source_keys=[A, B])
    assert run["status"] == "partial" and (run["sources_succeeded"], run["sources_failed"]) == (1, 1)
    by_key = {s["source_key"]: s for s in run["sources"]}
    assert by_key[A]["status"] == "success" and by_key[A]["offers_found"] == 3
    assert by_key[B]["status"] == "failed" and by_key[B]["error_type"] == "network"
    assert run["duration_ms"] is not None and run["trigger_type"] == "manual" and B in run["error_summary"]

    page = client.get("/api/search-runs", params={"page_size": 1}).json()
    assert page["total"] == 1 and page["items"][0]["id"] == run["id"] and page["page_size"] == 1
    assert client.get("/api/search-runs/9999").status_code == 404


def test_run_rejects_bad_requests(client: TestClient, db: Database) -> None:
    assert client.post("/api/search-runs", json={"source_keys": ["nexiste_pas"]}).status_code == 400
    assert client.post("/api/search-runs", json={"source_keys": ["senejobs"]}).status_code == 400
    assert client.post("/api/search-runs", json={"profile_id": 9999}).status_code == 404
    with db.session() as s:
        for src in s.scalars(select(JobSource)):
            src.enabled = False
    assert client.post("/api/search-runs", json={}).status_code == 409  # aucune source activée


def test_only_one_run_at_a_time(client: TestClient, configure) -> None:
    configure(**{A: {"jobs": jobs(1, 1), "sleep": 1.5}})
    first = client.post("/api/search-runs", json={"source_keys": [A]})
    assert first.status_code == 202
    second = client.post("/api/search-runs", json={"source_keys": [A]})
    assert second.status_code == 409 and second.json()["detail"]["active_run_id"] == first.json()["id"]
    assert client.post(f"/api/sources/{A}/collect").status_code == 409
    wait_run(client, first.json()["id"])
    assert client.post("/api/search-runs", json={"source_keys": [A]}).status_code == 202  # libre à nouveau
    wait_run(client, first.json()["id"] + 1)


# ------------------------------------------------------------------------------------------------ annonces
def test_list_offers_pagination_and_score(client: TestClient, populated: dict[str, Any]) -> None:
    page = client.get("/api/offers", params={"page_size": 2, "sort": "relevance"}).json()
    assert page["total"] == 3 and len(page["items"]) == 2 and page["page"] == 1
    item = page["items"][0]
    assert item["score"] is not None and item["user_status"] == "new" and item["primary_url"].startswith("https://")
    assert item["sources"][0]["key"] == A and item["freshness"]["label"] in {"fresh", "recent", "old", "unknown_date"}
    assert len(client.get("/api/offers", params={"page_size": 2, "page": 2}).json()["items"]) == 1
    scores = [o["score"] for o in client.get("/api/offers", params={"sort": "relevance"}).json()["items"]]
    assert scores == sorted(scores, reverse=True)


def test_list_offers_filters(client: TestClient, populated: dict[str, Any]) -> None:
    def total(**params: Any) -> int:
        r = client.get("/api/offers", params=params)
        assert r.status_code == 200, r.text
        return r.json()["total"]

    assert total(q="Python 2") == 1 and total(q="zzzinexistant") == 0
    assert total(source=A) == 3 and total(source=B) == 0
    assert total(country="SN") == 3 and total(country="CI") == 0
    assert total(city="Dakar") == 3 and total(contract_type="cdi") == 3 and total(contract_type="cdd") == 0
    assert total(company="Societe 1") == 1
    assert total(min_score=0) == 3 and total(min_score=100.0, max_score=100.0) <= 3
    assert total(status="new") == 3 and total(status="saved") == 0
    assert total(first_seen_from="2000-01-01T00:00:00Z") == 3 and total(first_seen_to="2000-01-01T00:00:00Z") == 0


def test_list_offers_validation(client: TestClient) -> None:
    assert client.get("/api/offers", params={"status": "bidon"}).status_code == 422
    assert client.get("/api/offers", params={"profile_id": 9999}).status_code == 404
    assert client.get("/api/offers", params={"page_size": 101}).status_code == 422
    assert client.get("/api/offers", params={"page": 0}).status_code == 422
    assert client.get("/api/offers", params={"min_score": 101}).status_code == 422
    assert client.get("/api/offers", params={"sort": "bidon"}).status_code == 422


def test_offer_detail(client: TestClient, populated: dict[str, Any]) -> None:
    first = client.get("/api/offers", params={"sort": "detected", "order": "asc"}).json()["items"][0]
    d = client.get(f"/api/offers/{first['id']}").json()
    assert d["title"] == first["title"] and d["description"] and d["content_hash"]
    assert len(d["source_links"]) == 1 and d["source_links"][0]["source_key"] == A
    assert d["scores"] and {"profile_id", "score", "breakdown", "explanation"} <= set(d["scores"][0])
    assert client.get("/api/offers/999999").status_code == 404


def test_offer_status_and_notes(client: TestClient, populated: dict[str, Any]) -> None:
    oid = client.get("/api/offers").json()["items"][0]["id"]
    r = client.patch(f"/api/offers/{oid}/status", json={"user_status": "saved", "notes": "à relancer vendredi"})
    assert r.status_code == 200
    d = r.json()
    assert d["user_status"] == "saved" and d["saved_at"] is not None and d["notes"] == "à relancer vendredi"
    saved_at = d["saved_at"]

    d = client.patch(f"/api/offers/{oid}/status", json={"user_status": "applied"}).json()
    assert d["user_status"] == "applied" and d["saved_at"] == saved_at and d["notes"] == "à relancer vendredi"
    d = client.patch(f"/api/offers/{oid}/status", json={"notes": None}).json()  # effacement explicite des notes
    assert d["notes"] is None and d["user_status"] == "applied"

    assert client.patch(f"/api/offers/{oid}/status", json={}).status_code == 422
    assert client.patch(f"/api/offers/{oid}/status", json={"user_status": "bidon"}).status_code == 422
    assert client.patch("/api/offers/999999/status", json={"user_status": "seen"}).status_code == 404
    assert client.get("/api/offers", params={"status": "applied"}).json()["total"] == 1
    assert client.get("/api/dashboard").json()["applied_offers"] == 1


def test_ignored_offers_are_hidden_by_default(client: TestClient, populated: dict[str, Any]) -> None:
    oid = client.get("/api/offers").json()["items"][0]["id"]
    client.patch(f"/api/offers/{oid}/status", json={"user_status": "ignored"})
    assert client.get("/api/offers").json()["total"] == 2
    assert client.get("/api/offers", params={"include_ignored": True}).json()["total"] == 3


def test_manual_offer(client: TestClient, db: Database) -> None:
    body = {
        "url": "https://www.linkedin.com/jobs/view/123456789/?trackingId=abc", "title": "  Ingénieur   logiciel Python ",
        "company_name": "Orange Sonatel", "location": "Dakar, Sénégal", "description": "<p>Python, Docker, FastAPI</p>",
        "contract_type": "cdi", "work_mode": "hybrid", "notes": "vu sur LinkedIn",
    }
    r = client.post("/api/offers/manual", json=body)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["title"] == "Ingénieur logiciel Python" and d["company_name"] == "Orange Sonatel"
    assert d["source_links"][0]["source_key"] == "manual" and "trackingId" not in d["primary_url"]
    assert d["description"] == "Python, Docker, FastAPI" and d["notes"] == "vu sur LinkedIn" and d["country"] == "SN"

    again = client.post("/api/offers/manual", json=body)  # même URL : pas de doublon
    assert again.status_code == 201 and again.json()["id"] == d["id"]
    assert client.get("/api/offers").json()["total"] == 1


@pytest.mark.parametrize(
    "patch",
    [{"url": "ftp://exemple.org/offre"}, {"url": "javascript:alert(1)"}, {"url": "https://"}, {"title": "x"}, {"work_mode": "bidon"}],
)
def test_manual_offer_validation(client: TestClient, patch: dict[str, Any]) -> None:
    body = {"url": "https://exemple.org/emploi/1", "title": "Développeur"} | patch
    assert client.post("/api/offers/manual", json=body).status_code == 422


# ------------------------------------------------------------------------------------------------ profils
PROFILE = {
    "name": "Data engineer", "countries": ["sn", "ci"], "cities": ["Dakar"], "positive_keywords": ["Data Engineer", "ETL"],
    "keyword_groups": {"Outils": ["Airflow", "dbt"]}, "contract_types": ["cdi"], "work_modes": ["hybrid"],
    "experience_levels": ["mid"], "weights": {"skills": 40},
}


def test_default_profiles_are_listed(client: TestClient) -> None:
    items = client.get("/api/search-profiles").json()
    assert items and all(p["effective_weights"] for p in items)
    assert client.get(f"/api/search-profiles/{items[0]['id']}").json()["name"] == items[0]["name"]
    assert client.get("/api/search-profiles/99999").status_code == 404


def test_profile_crud(client: TestClient) -> None:
    r = client.post("/api/search-profiles", json=PROFILE)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["countries"] == ["SN", "CI"] and p["is_active"] is True and p["effective_weights"]["skills"] == 40
    assert client.post("/api/search-profiles", json=PROFILE).status_code == 409  # nom déjà pris

    r = client.patch(f"/api/search-profiles/{p['id']}", json={"positive_keywords": ["Spark"], "is_active": False, "cities": []})
    assert r.status_code == 200
    q = r.json()
    assert q["positive_keywords"] == ["Spark"] and q["is_active"] is False and q["cities"] == []
    assert q["countries"] == ["SN", "CI"]  # champs non envoyés : inchangés
    q = client.patch(f"/api/search-profiles/{p['id']}", json={"weights": None}).json()
    assert q["weights"] is None  # remise à zéro explicite

    assert client.delete(f"/api/search-profiles/{p['id']}").status_code == 204
    assert client.get(f"/api/search-profiles/{p['id']}").status_code == 404
    assert client.delete(f"/api/search-profiles/{p['id']}").status_code == 404


@pytest.mark.parametrize(
    "patch",
    [
        {"countries": ["SEN"]}, {"countries": ["1A"]}, {"contract_types": ["bidon"]}, {"work_modes": ["bidon"]},
        {"experience_levels": ["guru"]}, {"weights": {"inconnu": 5}}, {"weights": {"skills": 500}}, {"name": ""},
    ],
)
def test_profile_validation(client: TestClient, patch: dict[str, Any]) -> None:
    assert client.post("/api/search-profiles", json=PROFILE).status_code == 201  # le gabarit de base est valide
    assert client.post("/api/search-profiles", json=PROFILE | {"name": "Autre"} | patch).status_code == 422
    pid = client.get("/api/search-profiles").json()[0]["id"]
    if "name" not in patch:
        assert client.patch(f"/api/search-profiles/{pid}", json=patch).status_code == 422


def test_profile_rename_conflict(client: TestClient) -> None:
    a = client.post("/api/search-profiles", json=PROFILE).json()
    b = client.post("/api/search-profiles", json=PROFILE | {"name": "Autre"}).json()
    assert client.patch(f"/api/search-profiles/{b['id']}", json={"name": a["name"]}).status_code == 409
    assert client.patch(f"/api/search-profiles/{b['id']}", json={"name": "Autre"}).status_code == 200  # même nom : OK


def test_profile_duplicate(client: TestClient) -> None:
    src = client.get("/api/search-profiles").json()[0]
    first = client.post(f"/api/search-profiles/{src['id']}/duplicate")
    second = client.post(f"/api/search-profiles/{src['id']}/duplicate")
    assert first.status_code == second.status_code == 201
    assert first.json()["name"] == f"{src['name']} (copie)" and second.json()["name"] == f"{src['name']} (copie 2)"
    assert first.json()["is_active"] is False and first.json()["positive_keywords"] == src["positive_keywords"]
    assert client.post("/api/search-profiles/99999/duplicate").status_code == 404


def test_new_profile_rescores_existing_offers(client: TestClient, populated: dict[str, Any]) -> None:
    p = client.post("/api/search-profiles", json=PROFILE | {"name": "Python only", "positive_keywords": ["Python"], "keyword_groups": {}}).json()
    items = client.get("/api/offers", params={"profile_id": p["id"], "sort": "relevance"}).json()["items"]
    assert len(items) == 3 and all(o["score"] is not None and o["score_profile_id"] == p["id"] for o in items)
    client.delete(f"/api/search-profiles/{p['id']}")
    d = client.get(f"/api/offers/{items[0]['id']}").json()
    assert all(sc["profile_id"] != p["id"] for sc in d["scores"])  # scores du profil supprimé retirés


# ------------------------------------------------------------------------------------------------ veille
def test_scheduler_settings_roundtrip(client: TestClient) -> None:
    st = client.get("/api/settings/scheduler").json()
    assert st["enabled"] is False and st["state"] == "disabled" and st["interval_minutes"] == 360
    assert (st["min_interval_minutes"], st["max_interval_minutes"]) == (30, 10080)

    st = client.patch("/api/settings/scheduler", json={"enabled": True, "interval_minutes": 60}).json()
    assert st["enabled"] and st["interval_minutes"] == 60 and st["next_run_at"] is not None
    assert st["state"] == "stopped" and st["alive"] is False  # activée, mais aucun processus ne la porte (mode off)
    assert client.get("/api/health").json()["scheduler"]["state"] == "stopped"

    st = client.patch("/api/settings/scheduler", json={"enabled": False}).json()
    assert st["state"] == "disabled" and st["next_run_at"] is None and st["interval_minutes"] == 60


def test_scheduler_targets_and_validation(client: TestClient) -> None:
    pid = client.get("/api/search-profiles").json()[0]["id"]
    st = client.patch("/api/settings/scheduler", json={"profile_ids": [pid], "source_keys": [A]}).json()
    assert st["profile_ids"] == [pid] and st["source_keys"] == [A]
    st = client.patch("/api/settings/scheduler", json={"interval_minutes": 120}).json()
    assert st["source_keys"] == [A]  # champs omis : conservés
    st = client.patch("/api/settings/scheduler", json={"profile_ids": None, "source_keys": None}).json()
    assert st["profile_ids"] is None and st["source_keys"] is None  # null explicite : retour à « tous »

    assert client.patch("/api/settings/scheduler", json={"interval_minutes": 10}).status_code == 422
    assert client.patch("/api/settings/scheduler", json={"interval_minutes": 99999}).status_code == 422
    assert client.patch("/api/settings/scheduler", json={"profile_ids": [99999]}).status_code == 404
    assert client.patch("/api/settings/scheduler", json={"source_keys": ["senejobs"]}).status_code == 400
    assert client.patch("/api/settings/scheduler", json={"source_keys": ["nexiste_pas"]}).status_code == 400
