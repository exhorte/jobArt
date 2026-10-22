"""Contrat commun des connecteurs de sources.

Un connecteur sait :
* `search`   : interroger SA source (réseau) et renvoyer des `RawJob` (données brutes déjà extraites) ;
* `normalize`: transformer un `RawJob` en `NormalizedJob` (pur, sans réseau → testable sur fixtures) ;
* `health_check` / `is_available` : vérifier l'accessibilité sans collecter.

Les connecteurs sont enregistrés explicitement (registry.py) : aucun endpoint n'accepte d'URL arbitraire.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ..core.errors import AccessBlocked, RateLimited, SourceError
from ..services.urls import url_key
from .http import PoliteClient

log = logging.getLogger(__name__)


class SearchParameters(BaseModel):
    """Paramètres de recherche dérivés des profils actifs (union), communs à toutes les sources."""

    keywords: list[str] = Field(default_factory=list)  # ordonnés par priorité
    countries: list[str] = Field(default_factory=lambda: ["SN"])
    cities: list[str] = Field(default_factory=list)
    work_modes: list[str] = Field(default_factory=list)
    max_pages: int = 1  # pages de résultats par requête
    max_queries: int = 8  # requêtes (mots-clés) maximum par collecte
    detail_budget: int = 20  # pages de détail maximum par collecte
    known_urls: set[str] = Field(default_factory=set)  # url_key déjà connues avec détail récent
    fetch_details: bool = True


class RawJob(BaseModel):
    """Annonce telle qu'extraite de la source (champs bruts), avant normalisation."""

    data: dict[str, Any]


class NormalizedJob(BaseModel):
    """Schéma partagé produit par tous les connecteurs. Les champs inconnus restent None / vides."""

    source_key: str
    source_job_id: str | None = None
    url: str  # lien direct vers l'annonce originale (validé)
    title: str
    company_name: str | None = None
    description: str | None = None
    location: str | None = None
    country: str | None = None
    city: str | None = None
    work_mode: str | None = None
    contract_type: str | None = None
    experience_level: str | None = None
    industry: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None  # hourly | daily | monthly | yearly (si déclaré)
    published_at: datetime | None = None  # déclarée par la source
    application_deadline: datetime | None = None
    remote_eligibility: str | None = None  # eligible | restricted | unknown
    remote_regions: list[str] = Field(default_factory=list)
    same_as_urls: list[str] = Field(default_factory=list)  # URLs équivalentes déclarées par la source
    estimated_fields: list[str] = Field(default_factory=list)  # champs déduits (pas déclarés)
    verified_at: datetime | None = None  # page de détail réellement consultée
    published_text: str | None = None  # date relative telle qu'affichée (« il y a 2 jours »), non convertie
    raw_metadata: dict[str, Any] = Field(default_factory=dict)  # sous-ensemble utile, jamais de secret


class HealthResult(BaseModel):
    ok: bool
    status: str  # ok | blocked | unreachable | unavailable | changed | robots
    detail: str = ""
    http_status: int | None = None
    latency_ms: int | None = None
    sample_count: int | None = None  # nombre d'annonces repérées lors du test (sans enregistrement)


class Connector(ABC):
    source_key: ClassVar[str]
    source_name: ClassVar[str]
    source_url: ClassVar[str]
    allowed_hosts: ClassVar[set[str]]
    # False : la source n'a pas de recherche par mot-clé → le connecteur filtre localement sur le titre.
    supports_keyword_search: ClassVar[bool] = True
    # Chemins d'index/liste qu'une URL d'annonce ne doit jamais être (voir services.urls.validate_job_url)
    forbidden_job_paths: ClassVar[set[str]] = set()

    def __init__(self, http: PoliteClient, config: dict[str, Any] | None = None) -> None:
        self.http = http
        self.config: dict[str, Any] = config or {}
        # Avertissements non fatals de la collecte en cours (ex. pages de détail inaccessibles)
        self.warnings: list[str] = []

    async def is_available(self) -> bool:
        return (await self.health_check()).ok

    @abstractmethod
    async def search(self, params: SearchParameters) -> list[RawJob]: ...

    @abstractmethod
    def normalize(self, raw: RawJob) -> NormalizedJob: ...

    @abstractmethod
    async def health_check(self) -> HealthResult: ...

    # ---- utilitaires communs
    def cfg(self, name: str, default: Any = None) -> Any:
        return self.config.get(name, default)

    def queries(self, params: SearchParameters) -> list[str]:
        """Mots-clés à interroger : dédupliqués, ordre de priorité conservé, plafonnés."""
        seen: set[str] = set()
        out: list[str] = []
        limit = min(params.max_queries, int(self.cfg("max_queries", params.max_queries)))
        for kw in params.keywords:
            k = kw.strip()
            if k and k.lower() not in seen:
                seen.add(k.lower())
                out.append(k)
            if len(out) >= limit:
                break
        return out

    # ---- enrichissement par pages de détail (uniquement pour les annonces nouvelles, avec budget)
    async def enrich_details(
        self,
        items: list[dict[str, Any]],
        params: SearchParameters,
        *,
        url_field: str,
        fetch: Callable[[str], Awaitable[dict[str, Any] | None]],
        target_key: str = "detail",
    ) -> int:
        """Récupère la page de détail des annonces inconnues, dans la limite de `detail_budget`.

        * une erreur sur UNE page n'interrompt pas la collecte (avertissement) ;
        * un blocage ou une limitation de débit arrête les détails restants (disjoncteur) mais conserve
          les résultats de liste ;
        * les annonces déjà connues avec détail récent (`known_urls`) ne sont pas re-téléchargées.
        """
        if not params.fetch_details:
            return 0
        budget = min(params.detail_budget, int(self.cfg("detail_budget", params.detail_budget)))
        fetched = 0
        for item in items:
            if fetched >= budget:
                remaining = sum(1 for i in items if target_key not in i and url_key(i[url_field]) not in params.known_urls)
                if remaining:
                    self.warnings.append(f"{remaining} annonce(s) sans détail (budget de {budget} pages atteint)")
                break
            url = item.get(url_field)
            if not url or url_key(url) in params.known_urls:
                continue
            try:
                detail = await fetch(url)
            except (AccessBlocked, RateLimited) as e:
                self.warnings.append(f"pages de détail interrompues : {e.error_type}")
                break
            except SourceError as e:
                self.warnings.append(f"détail indisponible ({e.error_type}) : {url}")
                continue
            fetched += 1
            if detail:
                item[target_key] = detail
        return fetched

    async def _health_get(
        self,
        url: str,
        *,
        check: Callable[[Any], tuple[bool, str, int | None]],
        as_json: bool = False,
        params: dict[str, Any] | None = None,
    ) -> HealthResult:
        """Exécute une requête de test et traduit les erreurs de collecte en statut lisible."""
        t0 = time.monotonic()
        try:
            resp = await self.http.get(url, params=params)
            payload = resp.json() if as_json else resp.text
            ok, detail, count = check(payload)
            return HealthResult(
                ok=ok,
                status="ok" if ok else "changed",
                detail=detail,
                http_status=resp.status_code,
                latency_ms=int((time.monotonic() - t0) * 1000),
                sample_count=count,
            )
        except SourceError as e:
            status = {
                "blocked": "blocked",
                "robots_disallowed": "robots",
                "network": "unreachable",
                "timeout": "unreachable",
                "unavailable": "unavailable",
                "rate_limited": "blocked",
                "parse": "changed",
            }.get(e.error_type, "unavailable")
            return HealthResult(ok=False, status=status, detail=str(e), latency_ms=int((time.monotonic() - t0) * 1000))
        except ValueError as e:  # JSON invalide
            return HealthResult(ok=False, status="changed", detail=f"réponse illisible : {e}")
