"""Wave — page carrière officielle (https://www.wave.com/en/careers/), employeur fintech sénégalais.

Méthode : la page carrière liste toutes les offres ouvertes (HTML rendu côté serveur : section → `.opening[data-
department][data-office]` → lien `/careers/job/{id}/` + lieu). Il n'y a pas de robots.txt (404 = aucune restriction).
Les offres de Wave sont aussi relayées par Africarrières : cas réel de doublon inter-sources.

La page ne publie pas de date : `published_at` reste NULL (jamais déduite). Les pages de détail ne sont lues que pour
les postes techniques (motifs configurables) et nouveaux, dans la limite du budget.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup

from ..core.errors import NormalizationError, ParseError
from ..services.enrich import detect_contract, detect_experience_level
from ..services.geo import parse_location
from ..services.text import collapse_ws, html_to_text, normalize_text
from ..services.urls import validate_job_url
from .base import Connector, HealthResult, NormalizedJob, RawJob, SearchParameters

CAREERS_URL = "https://www.wave.com/en/careers/"
_ID = re.compile(r"/job/(\d+)/?$")
_DEFAULT_TECH = [
    "engineer", "developer", "developpeur", "ingenieur", "data", "ai ", " ai", "machine learning", "software",
    "devops", "security", "technology", "cto", "scientist", "observability", "it ", "product", "analyst",
]


def parse_openings(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, dict[str, Any]] = {}
    for section in soup.select("div.opening-section"):
        h3 = section.find("h3")
        department = collapse_ws(h3.get_text(" ")) if h3 else None
        for op in section.select("div.opening"):
            a = op.find("a", href=True)
            if not a:
                continue
            m = _ID.search(a["href"])
            if not m or a["href"] in out:
                continue
            loc = op.select_one(".location")
            out[a["href"]] = {
                "url": a["href"].strip(),
                "job_id": m.group(1),
                "title": collapse_ws(a.get_text(" ")),
                "department": department,
                "office_code": op.get("data-office"),
                "location": collapse_ws(loc.get_text(" ")) if loc else None,
            }
    return list(out.values())


def parse_detail(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    content = soup.select_one("div#content")  # corps de l'offre (hors menu/pied de page)
    return {"description": html_to_text(str(content)) if content else None}


class WaveConnector(Connector):
    source_key = "wave_careers"
    source_name = "Wave — site carrière"
    source_url = CAREERS_URL
    allowed_hosts = {"wave.com"}
    supports_keyword_search = False
    forbidden_job_paths = {"/en/careers", "/fr/careers"}

    def _is_tech(self, title: str, department: str | None) -> bool:
        blob = " " + normalize_text(f"{title} {department or ''}") + " "
        patterns = self.cfg("detail_title_patterns", _DEFAULT_TECH)
        return any(p in blob for p in patterns)

    async def search(self, params: SearchParameters) -> list[RawJob]:
        html = await self.http.get_text(CAREERS_URL)
        items = parse_openings(html)
        if not items:
            raise ParseError("aucune offre reconnue sur la page carrière (structure modifiée ?)", url=CAREERS_URL)
        tech_items = [i for i in items if self._is_tech(i["title"], i.get("department"))]

        async def fetch_detail(url: str) -> dict[str, Any] | None:
            detail = parse_detail(await self.http.get_text(url))
            detail["fetched_at"] = datetime.now(UTC).isoformat()
            return detail

        await self.enrich_details(tech_items, params, url_field="url", fetch=fetch_detail)
        return [RawJob(data=i) for i in items]

    def normalize(self, raw: RawJob) -> NormalizedJob:
        d = raw.data
        url = validate_job_url(d.get("url"), allowed_hosts=self.allowed_hosts, forbidden_paths=self.forbidden_job_paths)
        title = collapse_ws(d.get("title") or "")
        if not title:
            raise NormalizationError("titre manquant", url=url)
        location = d.get("location")
        remote = bool(location and normalize_text(location) == "remote")
        city, country = (None, None) if remote else parse_location(location)
        detail = d.get("detail") or {}
        description = detail.get("description")
        eligibility, regions = ("unknown", []) if remote else (None, [])
        return NormalizedJob(
            source_key=self.source_key,
            source_job_id=d.get("job_id"),
            url=url,
            title=title,
            company_name="Wave",
            description=description,
            location=location,
            city=city,
            country=country,
            work_mode="remote" if remote else None,
            contract_type=detect_contract(title),
            experience_level=detect_experience_level(title, description),
            industry="fintech",
            remote_eligibility=eligibility,
            remote_regions=regions,
            verified_at=datetime.fromisoformat(detail["fetched_at"]) if detail.get("fetched_at") else None,
            raw_metadata={"department": d.get("department"), "office_code": d.get("office_code"), "employer_site": True},
        )

    async def health_check(self) -> HealthResult:
        def check(html: str) -> tuple[bool, str, int | None]:
            n = len(parse_openings(html))
            return (n > 0, f"{n} offre(s) listée(s)" if n else "aucune offre reconnue (structure modifiée ?)", n)

        return await self._health_get(CAREERS_URL, check=check)
