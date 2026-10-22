"""Jeton d'accès à l'API : `Authorization: Bearer <API_TOKEN>`.

Le frontend public (Vercel) joint l'API par son proxy serveur, qui ajoute ce jeton. Sans `API_TOKEN` (usage local),
l'API reste ouverte, car elle n'écoute que sur 127.0.0.1. `/api/health` reste libre : sondes Docker et Render.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

OPEN_PATHS = frozenset({"/api/health"})


def require_api_token(request: Request) -> None:
    expected: str = request.app.state.settings.api_token
    if not expected or request.url.path in OPEN_PATHS:
        return
    scheme, _, given = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and hmac.compare_digest(given.strip().encode(), expected.encode()):
        return
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Jeton d'accès invalide ou absent.",
        headers={"WWW-Authenticate": "Bearer"},
    )
