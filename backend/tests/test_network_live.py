"""Tests d'intégration en direct (Internet requis) : exclus par défaut, à lancer avec `pytest -m network`.

Une seule requête par source (health_check, avec le client poli : robots.txt respecté, délai entre requêtes). Ils servent à
détecter qu'un site a changé de structure ; un échec ici n'indique pas forcément un défaut du code (site indisponible).
"""

from __future__ import annotations

import pytest

from jobradar.collectors.http import HttpPool
from jobradar.collectors.registry import CONNECTORS, build_connector
from jobradar.core.config import Settings

pytestmark = pytest.mark.network


@pytest.mark.parametrize("source_key", sorted(CONNECTORS))
async def test_source_health_check_live(source_key: str, settings: Settings) -> None:
    pool = HttpPool(user_agent=settings.http_user_agent, timeout=settings.request_timeout_seconds, default_min_delay=1.5)
    try:
        result = await build_connector(source_key, pool, {}).health_check()
    finally:
        await pool.aclose()
    assert result.ok, f"{source_key}: {result.status} — {result.detail}"
