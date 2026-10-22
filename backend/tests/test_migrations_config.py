"""Migrations Alembic, initialisation (bootstrap) et cohérence des fichiers de configuration YAML."""

from __future__ import annotations

import argparse
import pathlib
from datetime import date
from typing import Any
from urllib.parse import urlparse

import pytest
import yaml
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select

from alembic import command
from jobart.collectors.registry import CONNECTORS
from jobart.core.config import REPO_ROOT, Settings
from jobart.core.db import Database
from jobart.models import Base, JobSource, SchedulerState, SearchProfile
from jobart.schemas.profiles import ProfileCreate
from jobart.services.bootstrap import bootstrap, load_employers, seed_profiles, sync_sources
from jobart.services.scoring import DEFAULT_WEIGHTS

BACKEND = pathlib.Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "config"


def load(name: str) -> dict[str, Any]:
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------ migrations
@pytest.fixture()
def alembic_cfg(tmp_path: pathlib.Path) -> tuple[Config, str]:
    url = f"sqlite:///{tmp_path / 'migr.sqlite'}"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.cmd_opts = argparse.Namespace(x=[f"url={url}"])
    return cfg, url


def table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_the_whole_schema_without_drift(alembic_cfg: tuple[Config, str]) -> None:
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")
    assert table_names(url) == set(Base.metadata.tables) | {"alembic_version"}
    command.check(cfg)  # lève une exception si les modèles et la migration divergent


def test_downgrade_then_upgrade_again(alembic_cfg: tuple[Config, str]) -> None:
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert table_names(url) == {"alembic_version"}
    command.upgrade(cfg, "head")
    assert set(Base.metadata.tables) <= table_names(url)


def test_single_migration_head() -> None:
    from alembic.script import ScriptDirectory

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1  # pas de branches divergentes


# ------------------------------------------------------------------------------------------------ bootstrap
def test_bootstrap_is_idempotent(db: Database, settings: Settings) -> None:
    def run() -> dict[str, Any]:
        with db.session() as s:
            return bootstrap(s, sources_path=settings.sources_config_path, profiles_path=settings.profiles_config_path)

    first = run()
    second = run()
    assert first["sources"]["created"] > 0 and first["profiles_seeded"] > 0
    assert second["sources"]["created"] == 0 and second["profiles_seeded"] == 0
    with db.session() as s:
        keys = [k for k in s.scalars(select(JobSource.source_key))]
        assert len(keys) == len(set(keys)) == len(load("sources.yaml")["sources"])
        assert s.get(SchedulerState, 1) is not None and s.get(SchedulerState, 1).enabled is False  # veille désactivée par défaut


def test_bootstrap_keeps_user_choices(db: Database, settings: Settings) -> None:
    with db.session() as s:
        bootstrap(s, sources_path=settings.sources_config_path, profiles_path=settings.profiles_config_path)
    with db.session() as s:
        s.scalar(select(JobSource).where(JobSource.source_key == "emploi_dakar")).enabled = False  # choix de l'utilisateur
        s.add(SearchProfile(name="Mon profil", countries=["SN"]))
        for p in s.scalars(select(SearchProfile).where(SearchProfile.name != "Mon profil")):
            s.delete(p)
    with db.session() as s:
        info = bootstrap(s, sources_path=settings.sources_config_path, profiles_path=settings.profiles_config_path)
    assert info["profiles_seeded"] == 0  # la table n'est pas vide : les profils par défaut ne reviennent pas
    with db.session() as s:
        assert s.scalar(select(JobSource.enabled).where(JobSource.source_key == "emploi_dakar")) is False
        assert s.scalars(select(SearchProfile.name)).all() == ["Mon profil"]


def test_sync_downgrades_implemented_source_without_connector(db: Database, tmp_path: pathlib.Path) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(
        yaml.safe_dump({"sources": [{
            "key": "fantome", "connector": "fantome", "name": "Fantôme", "base_url": "https://fantome.example/",
            "implementation": "implemented", "enabled": True, "collection_method": "html",
        }]}),
        encoding="utf-8",
    )
    with db.session() as s:
        counts = sync_sources(s, path)
    assert counts["warnings"] == 1
    with db.session() as s:
        src = s.scalar(select(JobSource).where(JobSource.source_key == "fantome"))
        assert src.implementation == "deferred" and src.enabled is False  # jamais activable sans connecteur


def test_seed_profiles_from_empty_file(db: Database, tmp_path: pathlib.Path) -> None:
    path = tmp_path / "p.yaml"
    path.write_text("profiles: []\n", encoding="utf-8")
    with db.session() as s:
        assert seed_profiles(s, path) == 0


# ------------------------------------------------------------------------------------------------ cohérence YAML
def test_sources_yaml_is_consistent() -> None:
    sources = load("sources.yaml")["sources"]
    keys = [s["key"] for s in sources]
    assert len(keys) == len(set(keys)), "clés de source en double"
    for s in sources:
        for field in ("key", "name", "base_url", "implementation", "collection_method"):
            assert s.get(field), f"{s.get('key')}: champ « {field} » manquant"
        assert urlparse(s["base_url"]).scheme in {"http", "https"} or s["implementation"] == "manual", s["key"]
        assert s["implementation"] in {"implemented", "deferred", "excluded", "manual"}, s["key"]
        if s["implementation"] == "implemented":
            if s.get("type") == "manual":  # pseudo-source de l'ajout manuel : pas de connecteur, jamais collectée
                assert not s.get("connector") and s["key"] not in CONNECTORS, s["key"]
            else:
                assert s.get("connector") in CONNECTORS, f"{s['key']}: connecteur absent du registre"
            assert s.get("decision_reason"), f"{s['key']}: la décision doit être justifiée"
        else:
            assert s.get("enabled") is not True, f"{s['key']}: une source sans connecteur ne peut pas être activée"
            if s["implementation"] in {"deferred", "excluded"}:
                assert s.get("decision_reason"), f"{s['key']}: la raison du report/de l'exclusion est obligatoire"
        assert isinstance(s.get("configuration") or {}, dict)
        assert all(not k.lower().endswith(("key", "token", "secret", "password")) for k in (s.get("configuration") or {})), \
            f"{s['key']}: la configuration est publique, jamais de secret"


def test_every_connector_has_a_source_entry_and_matching_host() -> None:
    by_connector = {s.get("connector"): s for s in load("sources.yaml")["sources"] if s.get("connector")}
    assert set(CONNECTORS) == {k for k in by_connector if by_connector[k]["implementation"] == "implemented"}
    for key, cls in CONNECTORS.items():
        assert cls.source_key == key
        host = urlparse(by_connector[key]["base_url"]).hostname or ""
        assert any(host == h or host.endswith("." + h) or h.endswith("." + host) for h in cls.allowed_hosts), \
            f"{key}: l'URL de base ({host}) n'est pas dans la liste blanche {sorted(cls.allowed_hosts)}"


def test_employers_yaml_is_consistent() -> None:
    employers = load_employers(CONFIG / "employers.yaml")
    source_keys = {s["key"] for s in load("sources.yaml")["sources"]}
    keys = [e["key"] for e in employers]
    assert employers and len(keys) == len(set(keys))
    for e in employers:
        assert e.get("name") and e.get("status")
        assert e.get("source_key") is None or e["source_key"] in source_keys, f"{e['key']}: source_key inconnue"
        if e.get("career_url"):
            assert e["career_url"].startswith("https://"), e["key"]  # seulement des URLs réellement vérifiées
        else:
            assert e.get("verification_note"), f"{e['key']}: sans URL, la raison doit être documentée"
        if e.get("checked_on") is not None:
            assert isinstance(e["checked_on"], date), e["key"]


def test_default_profiles_yaml_is_valid() -> None:
    data = load("default_search_profiles.yaml")
    assert set(data["default_weights"]) == set(DEFAULT_WEIGHTS)
    assert sum(data["default_weights"].values()) == 100
    names = [p["name"] for p in data["profiles"]]
    assert names and len(names) == len(set(names))
    for p in data["profiles"]:
        ProfileCreate(**p)  # mêmes règles que l'API (pays ISO, contrats, modes, niveaux, pondérations)
        assert p["positive_keywords"], f"{p['name']}: au moins un mot-clé"
