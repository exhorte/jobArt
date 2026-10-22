"""Liste blanche des connecteurs : seuls ces connecteurs peuvent être exécutés, et chacun ne contacte que ses hôtes."""

from __future__ import annotations

from typing import Any

from .africarrieres import AfricarrieresConnector
from .base import Connector
from .concoursn import ConcourSNConnector
from .emploi_dakar import EmploiDakarConnector
from .emploisenegal import EmploiSenegalConnector
from .expat_dakar import ExpatDakarConnector
from .himalayas import HimalayasConnector
from .http import HttpPool, PoliteClient
from .remote4africa import Remote4AfricaConnector
from .remoteok import RemoteOKConnector
from .senjob import SenJobConnector
from .wave import WaveConnector

CONNECTORS: dict[str, type[Connector]] = {
    c.source_key: c
    for c in (
        EmploiDakarConnector,
        EmploiSenegalConnector,
        AfricarrieresConnector,
        SenJobConnector,
        ConcourSNConnector,
        ExpatDakarConnector,
        Remote4AfricaConnector,
        HimalayasConnector,
        RemoteOKConnector,
        WaveConnector,
    )
}


class UnknownConnector(KeyError):
    """La clé ne correspond à aucun connecteur enregistré."""


def build_connector(source_key: str, pool: HttpPool, config: dict[str, Any] | None = None) -> Connector:
    try:
        cls = CONNECTORS[source_key]
    except KeyError as e:
        raise UnknownConnector(source_key) from e
    cfg = dict(config or {})
    client = PoliteClient(
        pool,
        source_key=source_key,
        allowed_hosts=cls.allowed_hosts,
        min_delay=float(cfg["min_delay_seconds"]) if cfg.get("min_delay_seconds") is not None else None,
        respect_robots=bool(cfg.get("respect_robots", True)),
    )
    return cls(client, cfg)
