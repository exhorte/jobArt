"""Himalayas (https://himalayas.app) — API JSON publique et documentée pour les offres en télétravail.

Méthode officielle : `GET /jobs/api/search?q=…&country=SN&sort=recent&page=N` (sans clé, https://himalayas.app/docs/
remote-jobs-api). Les données sont rafraîchies toutes les 24 h : inutile d'interroger plus souvent (intervalle minimal
configuré dans config/sources.yaml). Attribution obligatoire : l'interface affiche la source et lie vers himalayas.app.

Éligibilité depuis le Sénégal : `locationRestrictions` vide = aucune restriction de pays listée ; liste non vide =
pays exigés (éligible seulement si le Sénégal y figure).
"""

from __future__ import annotations

from typing import Any

from ..core.errors import NormalizationError, ParseError
from ..services.dates import from_epoch
from ..services.enrich import classify_remote_eligibility, detect_contract, map_schema_employment_type
from ..services.text import collapse_ws, html_to_text
from ..services.urls import validate_job_url
from .base import Connector, HealthResult, NormalizedJob, RawJob, SearchParameters

API = "https://himalayas.app/jobs/api/search"
_LEVELS = [
    ("entry", "junior"), ("junior", "junior"), ("mid", "mid"), ("senior", "senior"),
    ("manager", "lead"), ("director", "lead"), ("executive", "lead"), ("lead", "lead"),
]
_LEVEL_ORDER = ["junior", "mid", "senior", "lead"]


def _level(seniority: list[str] | None) -> str | None:
    found: list[str] = []
    for s in seniority or []:
        low = s.lower()
        for needle, level in _LEVELS:
            if needle in low:
                found.append(level)
                break
    return min(found, key=_LEVEL_ORDER.index) if found else None  # niveau le plus bas accepté


class HimalayasConnector(Connector):
    source_key = "himalayas"
    source_name = "Himalayas (API)"
    source_url = "https://himalayas.app/jobs"
    allowed_hosts = {"himalayas.app"}

    async def search(self, params: SearchParameters) -> list[RawJob]:
        country = (params.countries or ["SN"])[0]
        by_guid: dict[str, dict[str, Any]] = {}
        for kw in self.queries(params):
            for page in range(1, max(1, params.max_pages) + 1):
                data = await self.http.get_json(
                    API, params={"q": kw, "country": country, "sort": "recent", "page": page}
                )
                if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                    raise ParseError("réponse API inattendue (clé 'jobs' absente)", url=API)
                for job in data["jobs"]:
                    guid = job.get("guid")
                    if not guid:
                        continue
                    cur = by_guid.setdefault(guid, {"job": job, "queries": [], "listed_for_country": country})
                    if kw not in cur["queries"]:
                        cur["queries"].append(kw)
                if len(data["jobs"]) < int(data.get("limit") or 20):
                    break
        return [RawJob(data=v) for v in by_guid.values()]

    def normalize(self, raw: RawJob) -> NormalizedJob:
        job = raw.data.get("job") or {}
        url = validate_job_url(job.get("guid") or job.get("applicationLink"), allowed_hosts=self.allowed_hosts, forbidden_paths={"/jobs"})
        title = collapse_ws(job.get("title") or "")
        if not title:
            raise NormalizationError("titre manquant", url=url)
        restrictions = [r for r in (job.get("locationRestrictions") or []) if isinstance(r, str)]
        if restrictions:
            eligibility, regions = classify_remote_eligibility(restrictions)
            basis = "locationRestrictions"
        else:
            # aucune restriction de pays publiée par la source (et la requête était filtrée sur le pays)
            eligibility, regions, basis = "eligible", ["aucune restriction de pays listée"], "locationRestrictions_empty"
        employment = job.get("employmentType")
        description = html_to_text(job.get("description")) or collapse_ws(job.get("excerpt") or "") or None
        return NormalizedJob(
            source_key=self.source_key,
            source_job_id=url.split("/companies/", 1)[-1][:190],
            url=url,
            title=title,
            company_name=job.get("companyName") or None,
            description=description,
            location="Télétravail (remote)" + (f" — {', '.join(restrictions[:4])}" if restrictions else ""),
            work_mode="remote",
            contract_type=map_schema_employment_type(employment) or detect_contract(str(employment or "")),
            experience_level=_level(job.get("seniority")),
            salary_min=float(job["minSalary"]) if job.get("minSalary") else None,
            salary_max=float(job["maxSalary"]) if job.get("maxSalary") else None,
            salary_currency=job.get("currency"),
            salary_period=job.get("salaryPeriod") if job.get("salaryPeriod") in {"hourly", "daily", "weekly", "monthly", "yearly", "annual"} else None,
            published_at=from_epoch(job.get("pubDate")),
            application_deadline=from_epoch(job.get("expiryDate")),
            remote_eligibility=eligibility,
            remote_regions=regions,
            raw_metadata={
                "queries": raw.data.get("queries", []),
                "eligibility_basis": basis,
                "salary_period": job.get("salaryPeriod"),
                "categories": (job.get("parentCategories") or [])[:5],
                "timezone_restrictions": job.get("timezoneRestrictions") if len(job.get("timezoneRestrictions") or []) < 20 else "all",
                "deadline_kind": "listing_expiry",
                "attribution": "Source : Himalayas (himalayas.app)",
            },
        )

    async def health_check(self) -> HealthResult:
        def check(payload: Any) -> tuple[bool, str, int | None]:
            if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
                return False, "format de réponse modifié", None
            n = len(payload["jobs"])
            return n > 0, f"{n} offre(s) dans l'échantillon (total {payload.get('totalCount')})", n

        return await self._health_get(API, params={"q": "python", "country": "SN", "sort": "recent"}, check=check, as_json=True)
