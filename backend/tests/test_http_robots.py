"""Client HTTP « poli » : robots.txt, hôtes autorisés, anti-bot non contourné, limitation, timeouts, redirections."""

import time

import httpx
import pytest

from jobradar.collectors.http import HttpPool, PoliteClient, looks_like_challenge, parse_robots
from jobradar.core.errors import (
    AccessBlocked,
    NetworkError,
    RateLimited,
    RobotsDisallowed,
    SourceTimeout,
    SourceUnavailable,
)

from .conftest import make_pool, text_response


# ---------------------------------------------------------------- parseur robots.txt (RFC 9309)
def rules(text, token="jobradar"):
    return parse_robots(text, token)


def test_robots_longest_match_wins_and_allow_beats_disallow_on_tie():
    r = rules("User-agent: *\nDisallow: /private/\nAllow: /private/public/\n")
    assert not r.allowed("/private/secret")
    assert r.allowed("/private/public/page")
    tie = rules("User-agent: *\nDisallow: /a\nAllow: /a\n")
    assert tie.allowed("/a")


def test_robots_wildcards_and_end_anchor():
    r = rules("User-agent: *\nDisallow: /*?q=\nDisallow: /*.pdf$\n")
    assert not r.allowed("/jobs?q=dev")
    assert not r.allowed("/doc/file.pdf")
    assert r.allowed("/doc/file.pdf.html")
    assert r.allowed("/jobs/1")


def test_robots_specific_group_overrides_star_and_missing_group_allows():
    text = "User-agent: *\nDisallow: /\n\nUser-agent: JobRadar\nDisallow: /admin/\n"
    r = rules(text, token="JobRadar")
    assert r.allowed("/jobs/1") and not r.allowed("/admin/x")
    assert rules("User-agent: GPTBot\nDisallow: /\n").allowed("/anything")  # aucun groupe applicable


def test_robots_empty_disallow_allows_everything_and_crawl_delay_is_read():
    r = rules("User-agent: *\nDisallow:\nCrawl-delay: 7\n")
    assert r.allowed("/x") and r.crawl_delay == 7


def test_robots_comments_and_multiple_agents_per_group():
    r = rules("# commentaire\nUser-agent: foo\nUser-agent: *   # tous\nDisallow: /x  # privé\n")
    assert not r.allowed("/x/1") and r.allowed("/y")


# ---------------------------------------------------------------- détection de défi anti-robot
def test_challenge_detection_cloudflare_and_plain_403():
    r1 = httpx.Response(403, headers={"content-type": "text/html"}, content=b"<title>Just a moment...</title> cf-chl-bypass")
    r2 = httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html><title>Attention Required! | Cloudflare</title></html>")
    r3 = httpx.Response(403, headers={"content-type": "application/json"}, content=b"{}")
    ok = httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html><title>Offres d'emploi</title></html>")
    assert looks_like_challenge(r1) and looks_like_challenge(r2) and looks_like_challenge(r3)
    assert not looks_like_challenge(ok)


# ---------------------------------------------------------------- PoliteClient
def client_for(handler, hosts=("example.com",), **kw) -> tuple[HttpPool, PoliteClient]:
    pool = make_pool(handler)
    return pool, PoliteClient(pool, source_key="t", allowed_hosts=set(hosts), min_delay=0.0, **kw)


async def test_get_ok_and_robots_missing_means_allowed():
    pool, c = client_for(lambda req: httpx.Response(404) if req.url.path == "/robots.txt" else text_response("<p>ok</p>"))
    try:
        assert (await c.get("https://example.com/jobs/1")).text == "<p>ok</p>"
        assert c.requests_made == 1  # robots.txt n'est pas compté comme requête de collecte
    finally:
        await pool.aclose()


async def test_host_not_allowed_never_contacted():
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return text_response("x")

    pool, c = client_for(handler)
    try:
        with pytest.raises(AccessBlocked, match="hôte non autorisé"):
            await c.get("https://evil.example.org/steal")
        assert seen == []  # aucune requête partie (pas de SSRF)
    finally:
        await pool.aclose()


async def test_robots_disallow_is_respected():
    def handler(req):
        if req.url.path == "/robots.txt":
            return text_response("User-agent: *\nDisallow: /private\n", ctype="text/plain")
        return text_response("secret")

    pool, c = client_for(handler)
    try:
        with pytest.raises(RobotsDisallowed):
            await c.get("https://example.com/private/page")
        assert (await c.get("https://example.com/public")).status_code == 200
    finally:
        await pool.aclose()


async def test_robots_5xx_means_no_crawl():
    pool, c = client_for(lambda req: httpx.Response(503) if req.url.path == "/robots.txt" else text_response("x"))
    try:
        with pytest.raises(RobotsDisallowed):
            await c.get("https://example.com/jobs/1")
    finally:
        await pool.aclose()


async def test_403_and_challenge_raise_access_blocked_never_bypassed():
    attempts = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        attempts.append(1)
        return httpx.Response(403, headers={"content-type": "text/html"}, content=b"<title>Just a moment...</title>")

    pool, c = client_for(handler)
    try:
        with pytest.raises(AccessBlocked):
            await c.get("https://example.com/jobs")
        assert len(attempts) == 1  # pas de nouvelle tentative contre un anti-bot
    finally:
        await pool.aclose()


async def test_429_raises_rate_limited():
    pool, c = client_for(lambda req: httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(429, headers={"retry-after": "60"}))
    try:
        with pytest.raises(RateLimited, match="Retry-After"):
            await c.get("https://example.com/x")
    finally:
        await pool.aclose()


async def test_404_is_unavailable_unless_explicitly_allowed():
    pool, c = client_for(lambda req: httpx.Response(404, content=b"<html>vide</html>"))
    try:
        with pytest.raises(SourceUnavailable):
            await c.get("https://example.com/missing")
        resp = await c.get("https://example.com/missing", allow_statuses={404})
        assert resp.status_code == 404
    finally:
        await pool.aclose()


async def test_5xx_is_retried_once_then_unavailable():
    calls = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(1)
        return httpx.Response(502)

    pool, c = client_for(handler)
    try:
        with pytest.raises(SourceUnavailable):
            await c.get("https://example.com/x")
        assert len(calls) == 2
    finally:
        await pool.aclose()


async def test_transient_5xx_then_success():
    calls = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(1)
        return httpx.Response(500) if len(calls) == 1 else text_response("ok")

    pool, c = client_for(handler)
    try:
        assert (await c.get("https://example.com/x")).text == "ok"
    finally:
        await pool.aclose()


async def test_timeout_and_network_errors_are_typed():
    def timeout_handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.ReadTimeout("lent", request=req)

    def network_handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.ConnectError("dns", request=req)

    pool, c = client_for(timeout_handler)
    try:
        with pytest.raises(SourceTimeout):
            await c.get("https://example.com/x")
    finally:
        await pool.aclose()
    pool, c = client_for(network_handler)
    try:
        with pytest.raises(NetworkError):
            await c.get("https://example.com/x")
    finally:
        await pool.aclose()


async def test_redirect_to_other_host_is_blocked_and_same_host_is_followed():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        if req.url.path == "/new":
            return text_response("new")
        if req.url.path == "/away":
            return httpx.Response(302, headers={"location": "https://evil.example.org/x"})
        return httpx.Response(404)

    pool, c = client_for(handler)
    try:
        assert (await c.get("https://example.com/old")).text == "new"
        with pytest.raises(AccessBlocked):
            await c.get("https://example.com/away")
    finally:
        await pool.aclose()


async def test_redirect_loop_is_bounded():
    pool, c = client_for(lambda req: httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(302, headers={"location": "/loop"}))
    try:
        with pytest.raises(SourceUnavailable, match="redirections"):
            await c.get("https://example.com/loop")
    finally:
        await pool.aclose()


async def test_rate_limiter_enforces_minimum_delay_per_host():
    stamps = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        stamps.append(time.monotonic())
        return text_response("ok")

    pool = make_pool(handler)
    c = PoliteClient(pool, source_key="t", allowed_hosts={"example.com"}, min_delay=0.15)
    try:
        await c.get("https://example.com/1")
        await c.get("https://example.com/2")
        assert stamps[1] - stamps[0] >= 0.12
    finally:
        await pool.aclose()


async def test_invalid_json_is_a_parse_error():
    from jobradar.core.errors import ParseError

    pool, c = client_for(lambda req: httpx.Response(404) if req.url.path == "/robots.txt" else text_response("<html>pas du json</html>"))
    try:
        with pytest.raises(ParseError):
            await c.get_json("https://example.com/api")
    finally:
        await pool.aclose()
