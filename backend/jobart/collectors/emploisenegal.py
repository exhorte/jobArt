"""Emploi Sénégal (https://www.emploisenegal.com) — famille AfricaTalents (Drupal).

La même plateforme sert Emploi.ci, Emploi Mali, Emploi Burkina, Emploi Guinée, Emploi Mauritanie, Liberia Work…
Le connecteur est donc piloté par la configuration (`host`, `search_path`, `offer_prefix`, `country`) : ajouter un pays
de la région = ajouter une entrée dans config/sources.yaml (après vérification de ses conditions d'accès).

Méthode : pages de résultats publiques `…/recherche-jobs-{pays}?keywords=…` (HTML rendu côté serveur). Les cartes
contiennent titre, entreprise, extrait de description, expérience, contrat, région, compétences et date. Les pages de
détail ne sont pas consultées (leur JSON-LD est invalide et les cartes suffisent).

La recherche par mot-clé du site est ignorée en GET : le connecteur lit la catégorie « Informatique » et les
premières pages générales, puis filtre localement. Les offres « sponsorisées » (classe `featured`) hors sujet sont
écartées.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from ..core.errors import NormalizationError, ParseError
from ..services.dates import parse_datetime
from ..services.enrich import detect_contract, detect_experience_level, detect_work_mode
from ..services.geo import parse_location
from ..services.text import collapse_ws, keyword_hits, normalize_text
from ..services.urls import validate_job_url
from .base import Connector, HealthResult, NormalizedJob, RawJob, SearchParameters

_ID_SUFFIX = re.compile(r"-(\d+)$")


def parse_cards(html: str, origin: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    cards: list[dict[str, Any]] = []
    for card in soup.select("div.card-job"):
        a = card.select_one("h3 a[href]")
        if not a:
            continue
        href = a["href"].strip()
        url = href if href.startswith("http") else origin + href
        fields: dict[str, str] = {}
        for li in card.select(".card-job-detail ul li"):
            strong = li.find("strong")
            label = normalize_text(li.get_text(" ").split(":", 1)[0])
            if strong and label:
                fields[label] = collapse_ws(strong.get_text(" "))
        desc = card.select_one(".card-job-description p")
        company = card.select_one(".card-job-company")
        when = card.select_one("time")
        cards.append(
            {
                "url": url,
                "title": collapse_ws(a.get("title") or a.get_text(" ")),
                "company": collapse_ws(company.get_text(" ")) if company else None,
                "snippet": collapse_ws(desc.get_text(" ")).removesuffix("...").strip() if desc else None,
                "study_level": fields.get("niveau d etudes requis"),
                "experience_text": fields.get("niveau d experience"),
                "contract_text": fields.get("contrat propose"),
                "region_text": fields.get("region de"),
                "skills_text": fields.get("competences cles"),
                "date": when.get("datetime") if when else None,
                "featured": "featured" in (card.get("class") or []),
            }
        )
    return cards


class EmploiSenegalConnector(Connector):
    source_key = "emploisenegal"
    source_name = "Emploi Sénégal"
    source_url = "https://www.emploisenegal.com/"
    allowed_hosts = {"emploisenegal.com"}
    supports_keyword_search = False

    @property
    def _host(self) -> str:
        return self.cfg("host", "www.emploisenegal.com")

    @property
    def _origin(self) -> str:
        return f"https://{self._host}"

    @property
    def _search_url(self) -> str:
        return self._origin + self.cfg("search_path", "/recherche-jobs-senegal")

    @property
    def _offer_prefix(self) -> str:
        return self.cfg("offer_prefix", "/offre-emploi-senegal/")

    async def _page(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        html = await self.http.get_text(self._search_url, params=query or None)
        return parse_cards(html, self._origin)

    async def search(self, params: SearchParameters) -> list[RawJob]:
        """Catégorie informatique (toutes les offres) + pages générales filtrées localement par mots-clés.

        Le paramètre `keywords` du site est ignoré en GET (vérifié le 2026-10-21) : on ne l'envoie donc pas.
        """
        kws = self.queries(params)
        by_url: dict[str, dict[str, Any]] = {}
        saw_cards = False

        def merge(items: list[dict[str, Any]], label: str, *, local_filter: bool) -> None:
            nonlocal saw_cards
            for it in items:
                saw_cards = True
                text = " ".join(filter(None, [it["title"], it.get("snippet"), it.get("skills_text")]))
                hits = keyword_hits(text, kws)
                # Pages générales : on ne garde que les annonces qui correspondent aux mots-clés.
                # Catégorie informatique : tout est conservé, sauf les offres sponsorisées hors sujet.
                if local_filter and not hits:
                    continue
                if it["featured"] and not hits:
                    continue
                cur = by_url.setdefault(it["url"], {**it, "queries": []})
                for tag in hits or [label]:
                    if tag not in cur["queries"]:
                        cur["queries"].append(tag)

        category = self.cfg("it_category_id")
        if category:
            for page in range(int(self.cfg("category_pages", max(1, params.max_pages)))):
                query: dict[str, Any] = {"f[0]": f"im_field_offre_metiers:{category}"}
                if page:
                    query["page"] = page
                items = await self._page(query)
                merge(items, "catégorie:informatique", local_filter=False)
                if not items:
                    break
        if kws:
            for page in range(int(self.cfg("general_pages", 2))):
                items = await self._page({"page": page} if page else {})
                merge(items, "général", local_filter=True)
                if not items:
                    break

        if not by_url and not saw_cards:
            raise ParseError("aucune carte d'annonce reconnue (structure HTML modifiée ?)", url=self._search_url)
        return [RawJob(data=i) for i in by_url.values()]

    def normalize(self, raw: RawJob) -> NormalizedJob:
        d = raw.data
        url = validate_job_url(
            d.get("url"),
            allowed_hosts=self.allowed_hosts,
            forbidden_paths={self.cfg("search_path", "/recherche-jobs-senegal")},
        )
        if self._offer_prefix not in url:
            raise NormalizationError("l'URL n'est pas une page d'annonce", url=url)
        title = collapse_ws(d.get("title") or "")
        if not title:
            raise NormalizationError("titre manquant", url=url)
        m = _ID_SUFFIX.search(url.rstrip("/"))
        region = d.get("region_text")
        city, country = parse_location(region)
        country = country or self.cfg("country", "SN")
        snippet = d.get("snippet")
        contract = d.get("contract_text")
        return NormalizedJob(
            source_key=self.source_key,
            source_job_id=m.group(1) if m else None,
            url=url,
            title=title,
            company_name=d.get("company") or None,
            description=snippet,
            location=region,
            city=city,
            country=country,
            work_mode=detect_work_mode(title, region, snippet),
            contract_type=detect_contract(contract),
            experience_level=detect_experience_level(title, d.get("experience_text") or snippet),
            published_at=parse_datetime(d.get("date")),
            raw_metadata={
                "contract_text": contract,
                "experience_text": d.get("experience_text"),
                "study_level": d.get("study_level"),
                "skills_text": d.get("skills_text"),
                "featured": d.get("featured"),
                "queries": d.get("queries", []),
                "description_is_excerpt": True,
            },
        )

    async def health_check(self) -> HealthResult:
        def check(html: str) -> tuple[bool, str, int | None]:
            n = len(parse_cards(html, self._origin))
            return (n > 0, f"{n} carte(s) dans l'échantillon" if n else "aucune carte reconnue (structure modifiée ?)", n)

        return await self._health_get(self._search_url, check=check)
