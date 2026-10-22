"""SenJob (https://senjob.com/sn/) — job board régional (Sénégal, Côte d'Ivoire, Mali, Burkina, Niger, Guinée…).

Méthode : page de liste publique `offres-d-emploi.php` (HTML rendu côté serveur, tableau `#offresenjobs`) avec le
filtre `kw2` (recherche) ou `Category` (8 = Informatique, Télécoms, Réseaux), puis JSON-LD `JobPosting` de la page
de l'annonce pour le nom de l'employeur et la description — uniquement pour les annonces nouvelles.

Le JSON-LD du site est parfois mal formé (caractères de contrôle) : l'extracteur partagé est tolérant.
La liste n'affiche pas l'employeur : seul un code de compte interne (« alten », « senjobgc ») figure dans une cellule
masquée ; il n'est PAS utilisé comme nom d'entreprise.
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

LIST_URL = "https://senjob.com/sn/offres-d-emploi.php"
_JOB_ID = re.compile(r"_e_(\d+)\.html$")
_ISO_DAY = re.compile(r"(\d{4}-\d{2}-\d{2})")


def parse_list_page(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, dict[str, Any]] = {}
    for a in soup.select('#offresenjobs a[href*="_e_"]'):
        href = a["href"].strip()
        m = _JOB_ID.search(href)
        if not m or href in out:
            continue
        tr = a.find_parent("tr")
        tds = tr.find_all("td", recursive=False) if tr else []
        if len(tds) < 6:
            continue  # ligne imbriquée / bandeau
        text = [collapse_ws(td.get_text(" ")) for td in tds]
        pub = _ISO_DAY.search(text[4])
        exp = _ISO_DAY.search(text[5])
        out[href] = {
            "url": href,
            "job_id": m.group(1),
            "title": text[2],
            "location": text[3] or None,
            "published": pub.group(1) if pub else None,
            "expires": exp.group(1) if exp else None,
            "account_code": re.sub(r"^\d{4}-\d{2}-\d{2}", "", text[0]).strip() or None,
        }
    return list(out.values())


class SenJobConnector(Connector):
    source_key = "senjob_sn"
    source_name = "SenJob Sénégal"
    source_url = "https://senjob.com/sn/offres-d-emploi.php"
    allowed_hosts = {"senjob.com"}
    forbidden_job_paths = {"/sn/offres-d-emploi.php", "/sn/index.php", "/sn/", "/sn"}

    async def search(self, params: SearchParameters) -> list[RawJob]:
        by_url: dict[str, dict[str, Any]] = {}
        saw_table = False

        async def fetch_page(query: dict[str, Any], label: str) -> int:
            nonlocal saw_table
            html = await self.http.get_text(LIST_URL, params=query)
            saw_table = saw_table or "offresenjobs" in html
            items = parse_list_page(html)
            for it in items:
                cur = by_url.setdefault(it["url"], {**it, "queries": []})
                if label not in cur["queries"]:
                    cur["queries"].append(label)
            return len(items)

        for kw in self.queries(params):
            for page in range(1, max(1, params.max_pages) + 1):
                query: dict[str, Any] = {"kw2": kw}
                if page > 1:
                    query["page"] = page
                if not await fetch_page(query, kw):
                    break
        for category in self.cfg("category_ids", []):
            for page in range(1, max(1, params.max_pages) + 1):
                query = {"Category": category}
                if page > 1:
                    query["page"] = page
                if not await fetch_page(query, f"catégorie:{category}"):
                    break

        if not by_url and not saw_table and (params.keywords or self.cfg("category_ids")):
            raise ParseError("tableau des offres introuvable (structure HTML modifiée ?)", url=LIST_URL)
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
        url = validate_job_url(d.get("url"), allowed_hosts=self.allowed_hosts, forbidden_paths=self.forbidden_job_paths)
        title = collapse_ws(d.get("title") or "")
        if not title:
            raise NormalizationError("titre manquant", url=url)
        detail = d.get("detail") or {}
        location = d.get("location")
        city, country = parse_location(location)
        description = detail.get("description")
        company = detail.get("company")
        return NormalizedJob(
            source_key=self.source_key,
            source_job_id=d.get("job_id"),
            url=url,
            title=title,
            company_name=collapse_ws(company) if company else None,
            description=description,
            location=location,
            city=city,
            country=country or "SN",
            work_mode=detect_work_mode(title, location, description),
            contract_type=detect_contract(title),
            experience_level=detect_experience_level(title, description),
            published_at=parse_datetime(d.get("published")),
            application_deadline=parse_datetime(d.get("expires")),
            verified_at=parse_datetime(detail.get("fetched_at")) if detail else None,
            raw_metadata={"account_code": d.get("account_code"), "queries": d.get("queries", [])},
        )

    async def health_check(self) -> HealthResult:
        def check(html: str) -> tuple[bool, str, int | None]:
            n = len(parse_list_page(html))
            return (n > 0, f"{n} annonce(s) dans l'échantillon" if n else "aucune annonce reconnue (structure modifiée ?)", n)

        return await self._health_get(LIST_URL, check=check)
