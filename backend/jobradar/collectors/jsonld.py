"""Extraction du JSON-LD schema.org `JobPosting` (utilisé par plusieurs sources : données structurées publiées
par les sites eux-mêmes pour les moteurs de recherche, donc la voie de collecte la plus stable)."""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from ..services.dates import parse_datetime
from ..services.enrich import map_schema_employment_type
from ..services.text import html_to_text

_LD_BLOCK = re.compile(r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def _walk(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for v in node.values():
            if isinstance(v, (dict, list)):
                yield from _walk(v)


def extract_jsonld(html: str) -> list[dict[str, Any]]:
    """Tous les objets JSON-LD de la page (graphes aplatis). Les blocs invalides sont ignorés."""
    out: list[dict[str, Any]] = []
    for m in _LD_BLOCK.finditer(html):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except ValueError:
            try:  # certains sites échappent mal les retours à la ligne
                data = json.loads(raw.replace("\r", " ").replace("\n", " "), strict=False)
            except ValueError:
                continue
        out.extend(_walk(data))
    return out


def _types(obj: dict[str, Any]) -> list[str]:
    t = obj.get("@type")
    if isinstance(t, list):
        return [str(x) for x in t]
    return [str(t)] if t else []


def find_job_postings(html: str) -> list[dict[str, Any]]:
    seen: set[int] = set()
    out = []
    for obj in extract_jsonld(html):
        if "JobPosting" in _types(obj) and id(obj) not in seen:
            seen.add(id(obj))
            out.append(obj)
    return out


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        v = value.strip()
        return v or None
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("@value"))
    return None


def _place_text(job_location: Any) -> tuple[str | None, str | None]:
    """(libellé de lieu, code/nom de pays) d'un `jobLocation` schema.org (objet, liste ou chaîne)."""
    if not job_location:
        return None, None
    loc = job_location[0] if isinstance(job_location, list) and job_location else job_location
    if isinstance(loc, str):
        return loc.strip() or None, None
    if not isinstance(loc, dict):
        return None, None
    addr = loc.get("address")
    if isinstance(addr, str):
        return addr.strip() or None, None
    if isinstance(addr, dict):
        parts = [addr.get("streetAddress"), addr.get("addressLocality"), addr.get("addressRegion")]
        country = addr.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        label = ", ".join(str(p).strip() for p in parts if isinstance(p, str) and p.strip())
        full = ", ".join(x for x in (label, str(country) if country else "") if x)
        return full or None, str(country) if country else None
    return _text(loc.get("name")), None


def posting_to_fields(posting: dict[str, Any]) -> dict[str, Any]:
    """Champs normalisés (bruts mais typés) d'un JobPosting. Aucune valeur n'est inventée."""
    org = posting.get("hiringOrganization")
    company = _text(org) if org else None
    place, country = _place_text(posting.get("jobLocation"))
    reqs = posting.get("applicantLocationRequirements")
    req_names: list[str] = []
    if reqs:
        for r in reqs if isinstance(reqs, list) else [reqs]:
            n = _text(r)
            if n:
                req_names.append(n)
    salary = posting.get("baseSalary")
    s_min = s_max = None
    currency = None
    period = None
    if isinstance(salary, dict):
        currency = salary.get("currency")
        value = salary.get("value")
        if isinstance(value, dict):
            s_min = _num(value.get("minValue") if value.get("minValue") is not None else value.get("value"))
            s_max = _num(value.get("maxValue"))
            period = {"HOUR": "hourly", "DAY": "daily", "WEEK": "weekly", "MONTH": "monthly", "YEAR": "yearly"}.get(
                str(value.get("unitText", "")).upper()
            )
        else:
            s_min = _num(value)
    identifier = posting.get("identifier")
    ident_value = None
    if isinstance(identifier, dict):
        ident_value = _text(identifier.get("value"))
    elif isinstance(identifier, str):
        ident_value = identifier
    same_as = []
    if isinstance(org, dict) and isinstance(org.get("sameAs"), str):
        same_as.append(org["sameAs"])
    return {
        "title": _text(posting.get("title")),
        "description": html_to_text(posting.get("description") if isinstance(posting.get("description"), str) else None),
        "date_posted": parse_datetime(posting.get("datePosted")),
        "valid_through": parse_datetime(posting.get("validThrough")),
        "employment_type": map_schema_employment_type(posting.get("employmentType")),
        "company": company,
        "company_url": org.get("url") if isinstance(org, dict) else None,
        "same_as": same_as,
        "place": place,
        "country": country,
        "telecommute": str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE",
        "applicant_locations": req_names,
        "salary_min": s_min,
        "salary_max": s_max,
        "salary_currency": currency if isinstance(currency, str) else None,
        "salary_period": period,
        "identifier": ident_value,
        "url": posting.get("url") if isinstance(posting.get("url"), str) else None,
        "industry": _text(posting.get("industry")),
        "direct_apply": posting.get("directApply"),
    }


def _num(v: Any) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def first_posting_fields(html: str) -> dict[str, Any] | None:
    postings = find_job_postings(html)
    return posting_to_fields(postings[0]) if postings else None


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")
