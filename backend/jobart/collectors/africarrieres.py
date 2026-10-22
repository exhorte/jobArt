"""Africarrières (https://africarrieres.com) — réseau panafricain, page pays Sénégal.

Méthode : pages de liste publiques `/{pays}/fr/emplois?q=…` (HTML rendu côté serveur, autorisées par
robots.txt pour les robots génériques ; signal de contenu : ai-train=no, usage ici = veille personnelle), puis
JSON-LD `JobPosting` de la page de l'annonce pour la date de publication exacte, la date limite et la
description — uniquement pour les annonces nouvelles. La liste n'affiche que des dates relatives
(« il y a 2 heures »), jamais converties en date de publication.

Le pays est paramétrable (`country_slug`) pour l'extension régionale.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup

from ..core.errors import NormalizationError
from ..services.dates import is_relative_date, parse_datetime
from ..services.enrich import detect_contract, detect_experience_level, detect_work_mode
from ..services.geo import parse_location
from ..services.text import collapse_ws, normalize_company
from ..services.urls import validate_job_url
from .base import Connector, HealthResult, NormalizedJob, RawJob, SearchParameters
from .jsonld import first_posting_fields


def parse_list_page(html: str, base: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, dict[str, Any]] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith(base) or href.rstrip("/").endswith("/comparer"):
            continue
        slug = href[len(base):].strip("/")
        if not slug or "/" in slug or "?" in slug:
            continue
        h3 = a.find("h3")
        if h3 is None:
            continue
        company_p = h3.find_next_sibling("p")
        meta = company_p.find_next_sibling("div") if company_p else None
        spans = [collapse_ws(s.get_text(" ")) for s in meta.find_all("span", recursive=False)] if meta else []
        spans = [s for s in spans if s]
        when = a.select("p.text-gray-400") or [p for p in a.find_all("p") if p is not company_p]
        out[href] = {
            "url": href,
            "slug": slug,
            "title": collapse_ws(h3.get_text(" ")),
            "company": collapse_ws(company_p.get_text(" ")) if company_p else None,
            "location": spans[0] if spans else None,
            "contract": spans[1] if len(spans) > 1 else None,
            "published_text": collapse_ws(when[-1].get_text(" ")) if when else None,
        }
    return list(out.values())


class AfricarrieresConnector(Connector):
    source_key = "africarrieres_sn"
    source_name = "Africarrières Sénégal"
    source_url = "https://africarrieres.com/senegal/fr/emplois"
    allowed_hosts = {"africarrieres.com"}
    forbidden_job_paths: set[str] = set()

    @property
    def _list_url(self) -> str:
        slug = self.cfg("country_slug", "senegal")
        return f"https://africarrieres.com/{slug}/fr/emplois"

    @property
    def _job_base(self) -> str:
        return self._list_url + "/"

    async def search(self, params: SearchParameters) -> list[RawJob]:
        by_url: dict[str, dict[str, Any]] = {}
        for kw in self.queries(params) or [""]:
            for page in range(1, max(1, params.max_pages) + 1):
                query: dict[str, Any] = {"q": kw} if kw else {}
                if page > 1:
                    query["page"] = page
                html = await self.http.get_text(self._list_url, params=query or None)
                items = parse_list_page(html, self._job_base)
                new = 0
                for it in items:
                    if it["url"] not in by_url:
                        by_url[it["url"]] = {**it, "queries": []}
                        new += 1
                    if kw and kw not in by_url[it["url"]]["queries"]:
                        by_url[it["url"]]["queries"].append(kw)
                if not items:
                    break
                if new == 0 and page > 1:
                    break
        items = list(by_url.values())

        async def fetch_detail(url: str) -> dict[str, Any] | None:
            fields = first_posting_fields(await self.http.get_text(url))
            if not fields:
                return None
            fields["fetched_at"] = datetime.now(UTC).isoformat()
            return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in fields.items()}

        await self.enrich_details(items, params, url_field="url", fetch=fetch_detail)
        return [RawJob(data=i) for i in items]

    def normalize(self, raw: RawJob) -> NormalizedJob:
        d = raw.data
        url = validate_job_url(d.get("url"), allowed_hosts=self.allowed_hosts, forbidden_paths={self._list_url.replace("https://africarrieres.com", "")})
        title = collapse_ws(d.get("title") or "")
        if not title:
            raise NormalizationError("titre manquant", url=url)
        detail = d.get("detail") or {}
        location = detail.get("place") or d.get("location")
        city, country = parse_location(d.get("location") or location)
        company = detail.get("company") or d.get("company")
        company_hidden = normalize_company(company) is None
        published_text = d.get("published_text")
        return NormalizedJob(
            source_key=self.source_key,
            source_job_id=d.get("slug"),
            url=url,
            title=title,
            company_name=None if company_hidden else collapse_ws(company),
            description=detail.get("description"),
            location=location,
            city=city,
            country=country,
            work_mode=detect_work_mode(title, location, detail.get("description")),
            contract_type=detect_contract(d.get("contract")) or detail.get("employment_type"),
            experience_level=detect_experience_level(title, detail.get("description")),
            published_at=parse_datetime(detail.get("date_posted")),
            application_deadline=parse_datetime(detail.get("valid_through")),
            verified_at=parse_datetime(detail.get("fetched_at")) if detail else None,
            published_text=published_text if is_relative_date(published_text) else None,
            raw_metadata={"queries": d.get("queries", []), "company_hidden": company_hidden},
        )

    async def health_check(self) -> HealthResult:
        def check(html: str) -> tuple[bool, str, int | None]:
            n = len(parse_list_page(html, self._job_base))
            if n == 0:
                return False, "aucune carte d'annonce reconnue (structure modifiée ?)", 0
            return True, f"{n} annonce(s) dans l'échantillon", n

        return await self._health_get(self._list_url, check=check)
