"""Logs lisibles et exploitables : horodatage, niveau, logger, message (clé=valeur pour les événements)."""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_jobradar_configured", False):
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s - %(message)s", "%Y-%m-%dT%H:%M:%S%z")
    )
    root.handlers = [handler]
    root.setLevel(level.upper())
    root._jobradar_configured = True  # type: ignore[attr-defined]
    # httpx logge chaque requête en INFO : trop bavard, mais utile en DEBUG.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def kv(**fields: object) -> str:
    """Formate des champs en `clé=valeur` pour des logs structurés simples."""
    return " ".join(f"{k}={v!r}" if isinstance(v, str) and " " in v else f"{k}={v}" for k, v in fields.items())
