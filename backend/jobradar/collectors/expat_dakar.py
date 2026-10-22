"""Expat-Dakar — rubrique Emploi (https://www.expat-dakar.com/emploi), petites annonces (groupe Ringier).

Méthode : page de résultats publique `/emploi?q=…` (HTML rendu côté serveur). Le JSON-LD `JobPosting` de la page
fournit date de publication exacte, date limite, type de contrat, description et employeur ; la carte HTML
fournit le titre (le JSON-LD de liste a un titre générique) et le lieu. Aucune page de détail n'est consultée.

Intérêt particulier : `hiringOrganization.sameAs` renvoie parfois vers l'annonce d'origine sur une autre plateforme
(ex. Emploi Dakar) → enregistré dans `same_as_urls` pour la déduplication inter-sources.

Pertinence modeste pour un profil IA/dev (annonces surtout commerciales) mais données de qualité.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from ..core.errors import NormalizationError, ParseError, SourceUnavailable
from ..services.dates import parse_datetime
from ..services.enrich import detect_contract, detect_experience_level, detect_work_mode
from ..services.geo import parse_location
from ..services.text import collapse_ws
from ..services.urls import host_of, validate_job_url
from .base import Connector, HealthResult, NormalizedJob, RawJob, SearchParameters
from .jsonld import find_job_postings, posting_to_fields

LIST_URL = "https://www.expat-dakar.com/emploi"


def parse_results(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    cards: dict[str, dict[str, Any]] = {}
    for art in soup.select("article.tw-sr-card"):
        a = art.select_one("a[data-t-listing]") or art.select_one("a[href*='/annonce/']")
        if not a or not a.get("href"):
            continue
        category = a.get("data-t-listing_category_slug") or ""
        if category and not category.startswith("emploi"):
            continue  # annonces « similaires » d'autres rubriques
        url = a["href"].strip()
        loc = art.select_one(".tw-sr-card__location span")
        chips = [collapse_ws(li.get_text(" ")) for li in art.select("li.tw-sr-chip")]
        date_label = art.select_one(".tw-sr-card__date--list")
        cards[url] = {
            "url": url,
            "listing_id": a.get("data-t-listing_id"),
            "title": collapse_ws(a.get("data-t-listing_title") or ""),
            "location": collapse_ws(loc.get_text(" ")) if loc else None,
            "chips": chips,
            "category": category or None,
            "date_label": collapse_ws(date_label.get_text(" ")) if date_label else None,
        }
    for posting in find_job_postings(html):
        fields = posting_to_fields(posting)
        url = fields.get("url")
        if url and url in cards:
            fields["date_posted"] = fields["date_posted"].isoformat() if isinstance(fields["date_posted"], datetime) else None
            fields["valid_through"] = fields["valid_through"].isoformat() if isinstance(fields["valid_through"], datetime) else None
            cards[url]["ld"] = fields
    return [c for c in cards.values() if c["title"]]


class ExpatDakarConnector(Connector):
    source_key = "expat_dakar"
    source_name = "Expat-Dakar Emploi"
    source_url = "https://www.expat-dakar.com/emploi"
    allowed_hosts = {"expat-dakar.com"}
    forbidden_job_paths = {"/emploi", "/annonces"}

    async def search(self, params: SearchParameters) -> list[RawJob]:
        by_url: dict[str, dict[str, Any]] = {}
        saw_list = False
        for kw in self.queries(params):
            for page in range(1, max(1, params.max_pages) + 1):
                query: dict[str, Any] = {"q": kw}
                if page > 1:
                    query["page"] = page
                # HTTP 404 = « aucun résultat pour cette recherche » (page de résultats complète renvoyée quand même)
                resp = await self.http.get(LIST_URL, params=query, allow_statuses={404})
                html = resp.text
                if resp.status_code == 404 and "Expat-Dakar" not in html:
                    raise SourceUnavailable("HTTP 404 sans page de résultats Expat-Dakar", url=LIST_URL)
                items = parse_results(html)
                saw_list = saw_list or "tw-sr-card" in html or resp.status_code == 404
                for it in items:
                    cur = by_url.setdefault(it["url"], {**it, "queries": []})
                    if kw not in cur["queries"]:
                        cur["queries"].append(kw)
                if not items:
                    break
        if not by_url and not saw_list and params.keywords:
            raise ParseError("liste de résultats non reconnue (structure HTML modifiée ?)", url=LIST_URL)
        return [RawJob(data=i) for i in by_url.values()]

    def normalize(self, raw: RawJob) -> NormalizedJob:
        d = raw.data
        url = validate_job_url(d.get("url"), allowed_hosts=self.allowed_hosts, forbidden_paths=self.forbidden_job_paths)
        title = collapse_ws(d.get("title") or "")
        if not title:
            raise NormalizationError("titre manquant", url=url)
        ld = d.get("ld") or {}
        location = d.get("location")
        city, country = parse_location(location)
        description = ld.get("description")
        same_as = [
            u for u in ld.get("same_as", [])
            if isinstance(u, str) and u.startswith("http") and host_of(u) != "expat-dakar.com" and len(u.split("/", 3)) > 3 and u.split("/", 3)[3].strip("/")
        ]
        chips = d.get("chips") or []
        return NormalizedJob(
            source_key=self.source_key,
            source_job_id=d.get("listing_id"),
            url=url,
            title=title,
            company_name=ld.get("company") or (chips[0] if chips else None),
            description=description,
            location=location,
            city=city,
            country=country or "SN",
            work_mode=detect_work_mode(title, location, description),
            contract_type=ld.get("employment_type") or detect_contract(title),
            experience_level=detect_experience_level(title, description),
            industry=ld.get("industry"),
            published_at=parse_datetime(ld.get("date_posted")),
            application_deadline=parse_datetime(ld.get("valid_through")),
            same_as_urls=same_as,
            raw_metadata={"category": d.get("category"), "queries": d.get("queries", []), "date_label": d.get("date_label")},
        )

    async def health_check(self) -> HealthResult:
        def check(html: str) -> tuple[bool, str, int | None]:
            n = len(parse_results(html))
            return (n > 0, f"{n} annonce(s) dans l'échantillon" if n else "aucune annonce reconnue (structure modifiée ?)", n)

        return await self._health_get(LIST_URL, check=check)
