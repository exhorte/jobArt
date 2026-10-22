"""Client HTTP « poli » partagé par les connecteurs.

Garanties (voir docs/architecture.md) :
* seuls les hôtes explicitement autorisés pour la source sont contactés (pas de SSRF, redirections contrôlées) ;
* `robots.txt` est consulté et respecté (jokers `*` et `$`, règle du plus long motif, Crawl-delay) ;
* débit limité par hôte (délai minimal entre deux requêtes) et concurrence globale bornée ;
* timeouts, une seule reprise sur erreur transitoire, taille de réponse bornée ;
* un défi anti-robot / CAPTCHA / 403 est signalé (AccessBlocked) et JAMAIS contourné.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from ..core.errors import (
    AccessBlocked,
    NetworkError,
    ParseError,
    RateLimited,
    RobotsDisallowed,
    SourceTimeout,
    SourceUnavailable,
)
from ..services.urls import host_allowed

log = logging.getLogger(__name__)

_CHALLENGE_BODY = re.compile(
    r"(cf-chl|__cf_chl|just a moment|attention required|checking your browser|verify you are human|"
    r"verifying you are human|captcha-delivery|enable javascript and cookies|access denied|robot check|"
    r"are you a robot|ddos protection by)",
    re.IGNORECASE,
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_CHALLENGE_TITLE = re.compile(
    r"(just a moment|attention required|access denied|verifying you are human|robot check|security check|"
    r"checking your browser)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- robots.txt (RFC 9309)
@dataclass
class RobotsRules:
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow?, motif)
    crawl_delay: float | None = None

    def allowed(self, path_and_query: str) -> bool:
        best_len = -1
        best_allow = True
        for allow, pattern in self.rules:
            if not pattern:  # « Disallow: » vide = tout autorisé
                continue
            if _robots_match(pattern, path_and_query):
                n = len(pattern)
                if n > best_len or (n == best_len and allow):
                    best_len, best_allow = n, allow
        return best_allow


def _robots_match(pattern: str, path: str) -> bool:
    regex = ""
    for i, ch in enumerate(pattern):
        if ch == "*":
            regex += ".*"
        elif ch == "$" and i == len(pattern) - 1:
            regex += "$"
        else:
            regex += re.escape(ch)
    return re.match(regex, path) is not None


def parse_robots(text: str, product_token: str) -> RobotsRules:
    """Sélectionne le groupe du jeton produit (ex. « jobart »), sinon le groupe « * », sinon tout autorisé."""
    token = product_token.lower()
    groups: list[tuple[list[str], RobotsRules]] = []
    agents: list[str] = []
    current: RobotsRules | None = None
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        name, value = (p.strip() for p in line.split(":", 1))
        name = name.lower()
        if name == "user-agent":
            if not last_was_agent:
                agents, current = [], RobotsRules()
                groups.append((agents, current))
            agents.append(value.lower())
            last_was_agent = True
        elif name in {"allow", "disallow"} and current is not None:
            current.rules.append((name == "allow", value))
            last_was_agent = False
        elif name == "crawl-delay" and current is not None:
            try:
                current.crawl_delay = float(value)
            except ValueError:
                pass
            last_was_agent = False
        else:
            last_was_agent = False
    specific = [g for ags, g in groups if any(a != "*" and a in token for a in ags)]
    if specific:
        return specific[0]
    star = [g for ags, g in groups if "*" in ags]
    return star[0] if star else RobotsRules()


def looks_like_challenge(resp: httpx.Response) -> bool:
    """Détecte une page de défi anti-robot (Cloudflare, DataDome...). Sert à s'ARRÊTER, pas à contourner."""
    ctype = resp.headers.get("content-type", "").lower()
    if resp.status_code in {401, 403, 429, 503}:
        if "text" in ctype or "html" in ctype or not ctype:
            body = resp.text[:60000]
            if _CHALLENGE_BODY.search(body):
                return True
        return resp.status_code in {401, 403}
    if resp.status_code == 200 and ("html" in ctype) and len(resp.content) < 400_000:
        m = _TITLE.search(resp.text[:20000])
        if m and _CHALLENGE_TITLE.search(m.group(1)):
            return True
    return False


# --------------------------------------------------------------------------- pool partagé
class HttpPool:
    """Ressources partagées par tous les connecteurs d'un processus (client, robots, limiteur de débit)."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float = 20.0,
        max_response_bytes: int = 6_000_000,
        default_min_delay: float = 1.5,
        max_in_flight: int = 6,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.product_token = re.split(r"[/\s]", user_agent.strip(), maxsplit=1)[0] or "jobart"
        self.max_response_bytes = max_response_bytes
        self.default_min_delay = default_min_delay
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr,en;q=0.8",
            },
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            follow_redirects=False,
            transport=transport,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._sem = asyncio.Semaphore(max_in_flight)
        self._host_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._next_slot: dict[str, float] = {}
        self._robots: dict[str, tuple[float, RobotsRules | None]] = {}
        self._robots_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def wait_turn(self, host: str, delay: float) -> None:
        async with self._host_locks[host]:
            now = time.monotonic()
            wait = self._next_slot.get(host, 0.0) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_slot[host] = time.monotonic() + delay

    async def robots_for(self, url: str) -> RobotsRules | None:
        """Règles robots.txt de l'hôte (None = pas de robots.txt exploitable → tout autorisé, comme le 404 RFC)."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        async with self._robots_locks[origin]:
            cached = self._robots.get(origin)
            if cached and time.monotonic() - cached[0] < 6 * 3600:
                return cached[1]
            rules: RobotsRules | None = None
            try:
                await self.wait_turn(parts.netloc, self.default_min_delay)
                resp = await self.client.get(f"{origin}/robots.txt")
                ctype = resp.headers.get("content-type", "").lower()
                if resp.status_code == 200 and "html" not in ctype:
                    rules = parse_robots(resp.text, self.product_token)
                elif resp.status_code >= 500:
                    # RFC 9309 : erreur serveur → on considère l'accès interdit tant que robots.txt est indisponible
                    rules = RobotsRules(rules=[(False, "/")])
            except httpx.HTTPError as e:
                log.warning("robots.txt injoignable pour %s : %s", origin, e)
                rules = RobotsRules(rules=[(False, "/")])
            self._robots[origin] = (time.monotonic(), rules)
            return rules


# --------------------------------------------------------------------------- client par connecteur
class PoliteClient:
    def __init__(
        self,
        pool: HttpPool,
        *,
        source_key: str,
        allowed_hosts: set[str] | list[str],
        min_delay: float | None = None,
        respect_robots: bool = True,
    ) -> None:
        self.pool = pool
        self.source_key = source_key
        self.allowed_hosts = {h.lower().removeprefix("www.") for h in allowed_hosts}
        self.min_delay = pool.default_min_delay if min_delay is None else min_delay
        self.respect_robots = respect_robots
        self.requests_made = 0

    # ---- vérifications préalables
    def _check_host(self, url: str) -> None:
        if not host_allowed(url, self.allowed_hosts):
            raise AccessBlocked(
                f"hôte non autorisé pour {self.source_key} : {urlsplit(url).hostname}", url=url
            )

    async def _check_robots(self, url: str) -> float:
        rules = await self.pool.robots_for(url)
        if rules is None:
            return self.min_delay
        parts = urlsplit(url)
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        if not rules.allowed(target):
            raise RobotsDisallowed(f"robots.txt interdit {parts.path or '/'}", url=url)
        if rules.crawl_delay:
            return max(self.min_delay, min(rules.crawl_delay, 10.0))
        return self.min_delay

    # ---- requêtes
    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        max_redirects: int = 3,
        allow_statuses: frozenset[int] | set[int] = frozenset(),
    ) -> httpx.Response:
        """GET contrôlé. `allow_statuses` : statuts HTTP d'erreur que la source utilise pour un résultat valide
        (ex. 404 + page de résultats vide) ; le connecteur doit alors valider le contenu. Un défi anti-robot, un 401/403
        ou un 429 restent toujours des erreurs."""
        current = url
        resp: httpx.Response | None = None
        for hop in range(max_redirects + 1):
            self._check_host(current)
            delay = await self._check_robots(current) if self.respect_robots else self.min_delay
            resp = await self._send(current, params if hop == 0 else None, headers, delay)
            if resp.status_code in {301, 302, 303, 307, 308} and resp.headers.get("location"):
                current = urljoin(current, resp.headers["location"])
                continue
            break
        else:
            raise SourceUnavailable("trop de redirections", url=url)
        assert resp is not None
        self._raise_for_status(resp, current, allow_statuses)
        return resp

    async def get_text(self, url: str, **kw: Any) -> str:
        return (await self.get(url, **kw)).text

    async def get_json(self, url: str, **kw: Any) -> Any:
        resp = await self.get(url, **kw)
        try:
            return resp.json()
        except ValueError as e:
            raise ParseError(f"réponse JSON invalide : {e}", url=url) from e

    async def _send(
        self, url: str, params: dict[str, Any] | None, headers: dict[str, str] | None, delay: float
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(2):
            await self.pool.wait_turn(urlsplit(url).netloc, delay)
            try:
                async with self.pool._sem:
                    self.requests_made += 1
                    resp = await self.pool.client.get(url, params=params, headers=headers)
            except httpx.TimeoutException as e:
                last_exc = SourceTimeout(f"délai dépassé ({type(e).__name__})", url=url)
            except httpx.TransportError as e:
                last_exc = NetworkError(f"{type(e).__name__}: {str(e)[:160]}", url=url)
            else:
                if resp.status_code >= 500 and attempt == 0:
                    last_exc = SourceUnavailable(f"HTTP {resp.status_code}", url=url)
                else:
                    if len(resp.content) > self.pool.max_response_bytes:
                        raise ParseError("réponse trop volumineuse", url=url)
                    return resp
            if attempt == 0:
                await asyncio.sleep(min(2.0, delay + 0.5))
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _raise_for_status(resp: httpx.Response, url: str, allow: frozenset[int] | set[int] = frozenset()) -> None:
        code = resp.status_code
        if looks_like_challenge(resp):
            raise AccessBlocked(f"accès refusé / défi anti-robot (HTTP {code}) — non contourné", url=url)
        if code == 429:
            raise RateLimited(f"HTTP 429 (Retry-After: {resp.headers.get('retry-after', 'n/a')})", url=url)
        if code in {401, 403}:
            raise AccessBlocked(f"accès refusé (HTTP {code})", url=url)
        if code in allow:
            return
        if code == 404 or code == 410:
            raise SourceUnavailable(f"HTTP {code} (introuvable)", url=url)
        if code >= 400:
            raise SourceUnavailable(f"HTTP {code}", url=url)
