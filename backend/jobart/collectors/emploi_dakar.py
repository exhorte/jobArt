"""Emploi Dakar (https://www.emploidakar.com) — WordPress + WP Job Manager.

Méthode : endpoint public `jm-ajax/get_listings` (celui qu'utilise la recherche du site, non interdit par
robots.txt) pour la recherche par mots-clés, puis JSON-LD `JobPosting` de la page de l'annonce pour la
description et la date limite (uniquement pour les annonces nouvelles).

Limite de conditions d'utilisation : les CGU du site réservent la « visualisation à titre personnel et privé »
et interdisent l'extraction de leurs bases de données. Voir docs/source-feasibility.md avant tout usage au-delà
du cadre personnel. Débit volontairement faible.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup

from ..core.errors import NormalizationError, ParseError
from ..services.dates import parse_datetime
from ..services.enrich import detect_contract, detect_experience_level, detect_work_mode
from ..services.geo import parse_location
from ..services.text import collapse_ws
from ..services.urls import validate_job_url
from .base import Connector, HealthResult, NormalizedJob, RawJob, SearchParameters
from .jsonld import first_posting_fields

ENDPOINT = "https://www.emploidakar.com/jm-ajax/get_listings/"


def parse_listing_html(html: str) -> list[dict[str, Any]]:
    """Extrait les annonces du fragment HTML renvoyé par get_listings."""
    soup = BeautifulSoup(html, "lxml")
    items: list[dict[str, Any]] = []
    for li in soup.select("li.job_listing"):
        a = li.find("a", href=True)
        h3 = li.select_one("h3")
        if not a or not h3:
            continue
        classes = " ".join(li.get("class", []))
        m = re.search(r"\bpost-(\d+)\b", classes)
        company_el = li.select_one(".company strong") or li.select_one(".company")
        time_el = li.select_one("time")
        type_el = li.select_one(".job-type")
        loc_el = li.select_one(".location")
        items.append(
            {
                "url": a["href"].strip(),
                "post_id": m.group(1) if m else None,
                "title": collapse_ws(h3.get_text(" ")),
                "company": collapse_ws(company_el.get_text(" ")) if company_el else None,
                "location": collapse_ws(loc_el.get_text(" ")) if loc_el else None,
                "job_type": collapse_ws(type_el.get_text(" ")) if type_el else None,
                "date": time_el.get("datetime") if time_el else None,
                "date_label": collapse_ws(time_el.get_text(" ")) if time_el else None,
            }
        )
    return items


class EmploiDakarConnector(Connector):
    source_key = "emploi_dakar"
    source_name = "Emploi Dakar"
    source_url = "https://www.emploidakar.com/"
    allowed_hosts = {"emploidakar.com"}
    forbidden_job_paths = {"/offres-demploi-au-senegal", "/publier-une-offre-demploi", "/gerer-mes-offres"}

    async def _query(self, keyword: str, page: int, per_page: int) -> tuple[list[dict[str, Any]], int]:
        data = await self.http.get_json(
            ENDPOINT,
            # NB : ne pas envoyer orderby/order : le plugin répond alors en HTTP 404 (corps JSON valide).
            params={"search_keywords": keyword, "search_location": "", "per_page": per_page, "page": page},
        )
        if not isinstance(data, dict) or "html" not in data:
            raise ParseError("réponse get_listings inattendue (clé 'html' absente)", url=ENDPOINT)
        return parse_listing_html(data.get("html") or ""), int(data.get("max_num_pages") or 1)

    async def search(self, params: SearchParameters) -> list[RawJob]:
        per_page = int(self.cfg("per_page", 20))
        by_url: dict[str, dict[str, Any]] = {}
        keywords = self.queries(params) or [""]
        for kw in keywords:
            for page in range(1, max(1, params.max_pages) + 1):
                items, max_pages = await self._query(kw, page, per_page)
                for it in items:
                    cur = by_url.setdefault(it["url"], {**it, "queries": []})
                    if kw and kw not in cur["queries"]:
                        cur["queries"].append(kw)
                if page >= max_pages:
                    break
        items = list(by_url.values())

        async def fetch_detail(url: str) -> dict[str, Any] | None:
            html = await self.http.get_text(url)
            fields = first_posting_fields(html)
            if not fields:
                return None
            fields["fetched_at"] = datetime.now(UTC).isoformat()
            return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in fields.items()}

        await self.enrich_details(items, params, url_field="url", fetch=fetch_detail)
        return [RawJob(data=i) for i in items]

    def normalize(self, raw: RawJob) -> NormalizedJob:
        d = raw.data
        url = validate_job_url(d.get("url"), allowed_hosts=self.allowed_hosts, forbidden_paths=self.forbidden_job_paths)
        title = collapse_ws(d.get("title") or "")
        if not title:
            raise NormalizationError("titre manquant", url=url)
        detail = d.get("detail") or {}
        location = d.get("location")
        city, country = parse_location(location)
        description = detail.get("description")
        published = parse_datetime(detail.get("date_posted")) or parse_datetime(d.get("date"))
        contract = detect_contract(d.get("job_type")) or detail.get("employment_type")
        return NormalizedJob(
            source_key=self.source_key,
            source_job_id=d.get("post_id"),
            url=url,
            title=title,
            company_name=d.get("company") or detail.get("company"),
            description=description,
            location=location,
            city=city,
            country=country,
            work_mode=detect_work_mode(title, location, description),
            contract_type=contract,
            experience_level=detect_experience_level(title, description),
            published_at=published,
            application_deadline=parse_datetime(detail.get("valid_through")),
            verified_at=parse_datetime(detail.get("fetched_at")) if detail else None,
            raw_metadata={"job_type": d.get("job_type"), "queries": d.get("queries", []), "date_label": d.get("date_label")},
        )

    async def health_check(self) -> HealthResult:
        def check(payload: Any) -> tuple[bool, str, int | None]:
            if not isinstance(payload, dict) or "html" not in payload:
                return False, "format de réponse modifié (clé 'html' absente)", None
            n = len(parse_listing_html(payload.get("html") or ""))
            return (n > 0, f"{n} annonce(s) dans l'échantillon" if n else "aucune annonce dans l'échantillon", n)

        return await self._health_get(
            ENDPOINT,
            params={"search_keywords": "", "search_location": "", "per_page": 5, "page": 1},
            check=check,
            as_json=True,
        )
