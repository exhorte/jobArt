"""Remote4Africa (https://remote4africa.com) — offres en télétravail ouvertes aux pays africains.

Méthode : recherche publique `/jobs/search?q=…&countries=SN` (HTML rendu côté serveur, robots.txt : tout autorisé),
puis JSON-LD `JobPosting` de la page de l'offre (date exacte, validité, exigences géographiques `applicantLocation
Requirements`, salaire, employeur) — uniquement pour les offres nouvelles.

Limites : une partie des offres est réservée aux abonnés (le site l'indique) ; jobArt n'accède qu'aux pages publiques
et ne tente aucun contournement. CGU : usage personnel uniquement, pas de rediffusion. Aucune date n'apparaît sur les
cartes de liste de façon exploitable (« Oct 09 », sans année) : seule la date du JSON-LD est utilisée.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup

from ..core.errors import NormalizationError, ParseError
from ..services.dates import parse_datetime
from ..services.enrich import classify_remote_eligibility, detect_contract, detect_experience_level
from ..services.text import collapse_ws
from ..services.urls import validate_job_url
from .base import Connector, HealthResult, NormalizedJob, RawJob, SearchParameters
from .jsonld import first_posting_fields

ORIGIN = "https://remote4africa.com"
SEARCH_URL = ORIGIN + "/jobs/search"


def parse_listing(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, dict[str, Any]] = {}
    for a in soup.select('a[href^="/jobs/"]'):
        href = a["href"].split("?")[0].strip()
        if href.startswith("/jobs/search") or href.rstrip("/") == "/jobs":
            continue
        title = collapse_ws(a.get_text(" "))
        if not title or href in out:
            continue
        company_p = a.find_previous_sibling("p")
        spans = [collapse_ws(s.get_text(" ")) for s in a.parent.find_all("span") if "caption" in " ".join(s.get("class", []))]
        out[href] = {
            "url": ORIGIN + href,
            "slug": href.rsplit("/", 1)[-1],
            "title": title,
            "company": collapse_ws(company_p.get_text(" ")) if company_p else None,
            "chips": [s for s in spans if s],
        }
    return list(out.values())


class Remote4AfricaConnector(Connector):
    source_key = "remote4africa"
    source_name = "Remote4Africa"
    source_url = "https://remote4africa.com/"
    allowed_hosts = {"remote4africa.com"}
    forbidden_job_paths = {"/jobs", "/jobs/search"}

    async def search(self, params: SearchParameters) -> list[RawJob]:
        country = (params.countries or ["SN"])[0]
        by_url: dict[str, dict[str, Any]] = {}
        saw_list = False
        for kw in self.queries(params):
            for page in range(1, max(1, params.max_pages) + 1):
                query: dict[str, Any] = {"q": kw, "countries": country}
                if page > 1:
                    query["page"] = page
                html = await self.http.get_text(SEARCH_URL, params=query)
                items = parse_listing(html)
                saw_list = saw_list or "Showing" in html
                for it in items:
                    cur = by_url.setdefault(it["url"], {**it, "queries": [], "listed_for_country": country})
                    if kw not in cur["queries"]:
                        cur["queries"].append(kw)
                if not items:
                    break
        if not by_url and not saw_list and params.keywords:
            raise ParseError("liste de résultats non reconnue (structure HTML modifiée ?)", url=SEARCH_URL)
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
        description = detail.get("description")
        applicant = detail.get("applicant_locations") or []
        eligibility, regions = classify_remote_eligibility(applicant) if applicant else ("unknown", [])
        basis = "applicantLocationRequirements" if applicant else None
        if eligibility == "unknown" and d.get("listed_for_country"):
            # La source a elle-même filtré sa liste sur ce pays : éligibilité déclarée par le filtre de la source.
            eligibility, regions, basis = "eligible", [f"filtre source : {d['listed_for_country']}"], "source_country_filter"
        salary_currency = detail.get("salary_currency")
        chips = d.get("chips") or []
        return NormalizedJob(
            source_key=self.source_key,
            source_job_id=d.get("slug"),
            url=url,
            title=title,
            company_name=detail.get("company") or d.get("company"),
            description=description,
            location="Télétravail (remote)",
            work_mode="remote",
            contract_type=detail.get("employment_type") or detect_contract(*chips),
            experience_level=detect_experience_level(title, description),
            industry=None,
            salary_min=detail.get("salary_min"),
            salary_max=detail.get("salary_max"),
            salary_currency=salary_currency,
            salary_period=detail.get("salary_period"),
            published_at=parse_datetime(detail.get("date_posted")),
            application_deadline=parse_datetime(detail.get("valid_through")),
            remote_eligibility=eligibility,
            remote_regions=regions,
            verified_at=parse_datetime(detail.get("fetched_at")) if detail else None,
            raw_metadata={"queries": d.get("queries", []), "eligibility_basis": basis, "chips": chips},
        )

    async def health_check(self) -> HealthResult:
        def check(html: str) -> tuple[bool, str, int | None]:
            n = len(parse_listing(html))
            return (n > 0, f"{n} offre(s) dans l'échantillon" if n else "aucune offre reconnue (structure modifiée ?)", n)

        return await self._health_get(SEARCH_URL, params={"q": "developer", "countries": "SN"}, check=check)
