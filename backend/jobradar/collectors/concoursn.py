"""ConcourSN (https://concoursn.com) — agrégateur éditorial de recrutements et stages au Sénégal.

Méthode : pages de catégorie publiques (`/category/senegal/recrutement-senegal`, `…/stages-senegal`), autorisées par
robots.txt (seuls `/search`, `/api/`, `/dashboard/`… sont exclus), puis page de l'article pour la « fiche
synthétique » (employeur, lieu, date limite) — uniquement pour les annonces nouvelles.

Limites assumées (voir docs/source-feasibility.md) :
* ce n'est pas un job board structuré : un article = une annonce, sans JSON-LD `JobPosting` ;
* l'entreprise n'est lue que dans la fiche déclarée ; à défaut elle est *estimée* depuis le titre
  (« Recrutement X : … », « X recrute … ») et marquée dans `estimated_fields` ;
* la date de la liste est une date sans heure ; les articles « récapitulatif », « résultats » etc. sont écartés ;
* les CGU interdisent l'extraction automatisée des contenus payants de l'Académie : ils ne sont jamais consultés.
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
from ..services.text import collapse_ws, keyword_hits, normalize_text
from ..services.urls import validate_job_url
from .base import Connector, HealthResult, NormalizedJob, RawJob, SearchParameters

ORIGIN = "https://concoursn.com"
_TITLE_COMPANY_ROLE = re.compile(r"^recrutement\s+(?P<company>.+?)\s*:\s*(?P<role>.+)$", re.IGNORECASE)
_TITLE_RECRUTE = re.compile(r"^(?P<company>.+?)\s+recrute(?:nt)?\s+(?P<role>.+)$", re.IGNORECASE)
_SESSION = re.compile(r"\s*\((?:[^)]*?)session\s*\d{4}\)\s*$", re.IGNORECASE)
_LEAD_COUNT = re.compile(r"^\d{1,2}\s+")
_LABELS = {
    "company": re.compile(r"^(entreprise(?:\s*/\s*employeur)?|employeur|organisation|structure recruteuse)\s*:?$", re.IGNORECASE),
    "role": re.compile(r"^(intitul[ée] du poste|poste)\s*:?$", re.IGNORECASE),
    "place": re.compile(r"^(lieu d.affectation|lieu du poste|lieu|localisation|pays)\s*:?$", re.IGNORECASE),
    "deadline": re.compile(r"^(date limite(?: de (?:candidature|d[ée]p[ôo]t))?|date de cl[ôo]ture)\s*:?$", re.IGNORECASE),
    "contract": re.compile(r"^(type de contrat|contrat)\s*:?$", re.IGNORECASE),
}


def parse_category(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, dict[str, Any]] = {}
    for a in soup.select("ul li a[href^='/']"):
        h3 = a.find(["h3", "h2"])
        if h3 is None:
            continue
        href = a["href"].strip()
        paras = [collapse_ws(p.get_text(" ")) for p in a.find_all("p")]
        out[href] = {
            "url": ORIGIN + href,
            "title": collapse_ws(h3.get_text(" ")),
            "excerpt": paras[0] if paras else None,
            "date_label": paras[-1] if len(paras) > 1 else None,
        }
    return list(out.values())


def has_next_page(html: str) -> bool:
    return any(a.get_text(strip=True) == "Suivant" for a in BeautifulSoup(html, "lxml").find_all("a"))


def parse_fiche(article_html: str) -> dict[str, Any]:
    """Extrait la « fiche synthétique » (libellé / valeur sur deux lignes) et le texte de l'article."""
    soup = BeautifulSoup(article_html, "lxml")
    art = soup.select_one("article") or soup
    for tag in art(["script", "style", "nav", "aside", "form"]):
        tag.decompose()
    lines = [collapse_ws(x) for x in art.get_text("\n").split("\n")]
    lines = [x for x in lines if x]
    fiche: dict[str, str] = {}
    for i, line in enumerate(lines):
        head, sep, tail = line.partition(":")
        candidate = head.strip() + (":" if sep else "")
        for key, pattern in _LABELS.items():
            if key in fiche or not (pattern.match(candidate) or pattern.match(head.strip())):
                continue
            value = tail.strip() if sep and tail.strip() else (lines[i + 1] if i + 1 < len(lines) else "")
            if value and not value.endswith(":") and len(value) < 200:
                fiche[key] = value
    text = "\n".join(lines)
    return {"fiche": fiche, "text": text[:6000]}


def split_title(title: str) -> tuple[str | None, str]:
    """(entreprise estimée, intitulé du poste) à partir du titre de l'article."""
    t = collapse_ws(title)
    m = _TITLE_COMPANY_ROLE.match(t) or _TITLE_RECRUTE.match(t)
    if not m:
        return None, t
    role = _SESSION.sub("", m.group("role")).strip()
    role = _LEAD_COUNT.sub("", role).strip() or t
    company = m.group("company").strip()
    return (company or None), role


class ConcourSNConnector(Connector):
    source_key = "concoursn"
    source_name = "ConcourSN"
    source_url = "https://concoursn.com/"
    allowed_hosts = {"concoursn.com"}
    supports_keyword_search = False  # /search est interdit par robots.txt : filtrage local
    forbidden_job_paths = {"/category/senegal/recrutement-senegal", "/category/senegal/stages-senegal", "/fascicules", "/academie"}

    def _categories(self) -> list[str]:
        return self.cfg("categories", ["/category/senegal/recrutement-senegal", "/category/senegal/stages-senegal"])

    def _excluded(self, title: str) -> bool:
        patterns = self.cfg(
            "exclude_title_patterns",
            ["recapitulatif", "resultats", "liste des", "convocation", "calendrier", "admissibilite", "corrige", "sujet", "formation"],
        )
        n = normalize_text(title)
        return any(p in n for p in patterns)

    async def search(self, params: SearchParameters) -> list[RawJob]:
        kws = self.queries(params)
        by_url: dict[str, dict[str, Any]] = {}
        saw_list = False
        for category in self._categories():
            for page in range(1, int(self.cfg("pages", max(1, params.max_pages))) + 1):
                path = category + (f"/page/{page}" if page > 1 else "")
                html = await self.http.get_text(ORIGIN + path)
                items = parse_category(html)
                saw_list = saw_list or bool(items)
                for it in items:
                    if self._excluded(it["title"]):
                        continue
                    hits = keyword_hits(" ".join(filter(None, [it["title"], it.get("excerpt")])), kws) if kws else []
                    if kws and not hits:
                        continue
                    cur = by_url.setdefault(it["url"], {**it, "category": category, "queries": []})
                    cur["queries"] = sorted(set(cur["queries"]) | set(hits))
                if not items or not has_next_page(html):
                    break
        if not by_url and not saw_list:
            raise ParseError("aucun article reconnu dans les catégories (structure modifiée ?)", url=ORIGIN)
        items = list(by_url.values())

        async def fetch_detail(url: str) -> dict[str, Any] | None:
            data = parse_fiche(await self.http.get_text(url))
            data["fetched_at"] = datetime.now(UTC).isoformat()
            return data

        await self.enrich_details(items, params, url_field="url", fetch=fetch_detail)
        return [RawJob(data=i) for i in items]

    def normalize(self, raw: RawJob) -> NormalizedJob:
        d = raw.data
        url = validate_job_url(d.get("url"), allowed_hosts=self.allowed_hosts, forbidden_paths=self.forbidden_job_paths)
        article_title = collapse_ws(d.get("title") or "")
        if not article_title:
            raise NormalizationError("titre manquant", url=url)
        detail = d.get("detail") or {}
        fiche = detail.get("fiche") or {}
        title_company, role = split_title(article_title)
        company = fiche.get("company")
        estimated: list[str] = []
        if not company and title_company:
            company, estimated = title_company, ["company_name"]
        role = fiche.get("role") or role
        place = fiche.get("place")
        city, country = parse_location(place)
        deadline = parse_datetime(fiche.get("deadline"))
        category = d.get("category") or ""
        contract = detect_contract(fiche.get("contract")) or ("stage" if "stages" in category else detect_contract(article_title))
        description = detail.get("text") or d.get("excerpt")
        return NormalizedJob(
            source_key=self.source_key,
            source_job_id=url.rstrip("/").rsplit("/", 1)[-1][:180],
            url=url,
            title=collapse_ws(role)[:480],
            company_name=collapse_ws(company) if company else None,
            description=description,
            location=place,
            city=city,
            country=country or "SN",
            work_mode=detect_work_mode(role, place),
            contract_type=contract,
            experience_level=detect_experience_level(role, description),
            published_at=parse_datetime(d.get("date_label")),
            application_deadline=deadline,
            verified_at=parse_datetime(detail.get("fetched_at")) if detail else None,
            estimated_fields=estimated,
            raw_metadata={
                "article_title": article_title,
                "category": category,
                "queries": d.get("queries", []),
                "description_is_excerpt": not bool(detail),
            },
        )

    async def health_check(self) -> HealthResult:
        def check(html: str) -> tuple[bool, str, int | None]:
            n = len(parse_category(html))
            return (n > 0, f"{n} article(s) dans l'échantillon" if n else "aucun article reconnu (structure modifiée ?)", n)

        return await self._health_get(ORIGIN + self._categories()[0], check=check)
