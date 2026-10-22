"""Remote OK (https://remoteok.com) — API JSON publique (https://remoteok.com/api), ~100 offres récentes par appel.

Une seule requête par collecte (flux global, sans recherche) ; filtrage local sur les mots-clés des profils.
Conditions de l'API : lien retour vers l'URL Remote OK et mention de la source (affichées dans l'interface) ;
ne pas utiliser le logo. Le champ `location` est souvent vide : l'éligibilité depuis le Sénégal reste alors « inconnue »
(jamais présumée). Le flux contient des textes mal encodés (mojibake) : réparés à la normalisation.
"""

from __future__ import annotations

from typing import Any

from ..core.errors import NormalizationError, ParseError
from ..services.dates import from_epoch
from ..services.enrich import classify_remote_eligibility, detect_experience_level
from ..services.text import collapse_ws, fix_mojibake, html_to_text, keyword_hits
from ..services.urls import validate_job_url
from .base import Connector, HealthResult, NormalizedJob, RawJob, SearchParameters

API = "https://remoteok.com/api"


class RemoteOKConnector(Connector):
    source_key = "remoteok"
    source_name = "Remote OK (API)"
    source_url = "https://remoteok.com/"
    allowed_hosts = {"remoteok.com"}
    supports_keyword_search = False
    forbidden_job_paths = {"/api", "/remote-jobs"}

    async def search(self, params: SearchParameters) -> list[RawJob]:
        data = await self.http.get_json(API)
        if not isinstance(data, list) or len(data) < 2:
            raise ParseError("réponse API inattendue (liste d'offres absente)", url=API)
        kws = self.queries(params)
        out: list[RawJob] = []
        for job in data[1:]:  # le 1er élément est l'avis légal
            if not isinstance(job, dict) or not job.get("url"):
                continue
            blob = " ".join([str(job.get("position") or ""), " ".join(job.get("tags") or [])])
            hits = keyword_hits(blob, kws) if kws else []
            if kws and not hits:
                continue
            out.append(RawJob(data={"job": job, "queries": hits}))
        return out

    def normalize(self, raw: RawJob) -> NormalizedJob:
        job = raw.data.get("job") or {}
        url = validate_job_url(job.get("url") or job.get("apply_url"), allowed_hosts=self.allowed_hosts, forbidden_paths=self.forbidden_job_paths)
        title = collapse_ws(fix_mojibake(job.get("position")) or "")
        if not title:
            raise NormalizationError("titre manquant", url=url)
        location = collapse_ws(fix_mojibake(job.get("location")) or "") or None
        eligibility, regions = classify_remote_eligibility(location, unmarked="unknown") if location else ("unknown", [])
        description = html_to_text(fix_mojibake(job.get("description")))
        smin, smax = job.get("salary_min"), job.get("salary_max")
        return NormalizedJob(
            source_key=self.source_key,
            source_job_id=str(job.get("id") or job.get("slug") or "")[:190] or None,
            url=url,
            title=title,
            company_name=collapse_ws(fix_mojibake(job.get("company")) or "") or None,
            description=description,
            location=location or "Télétravail (remote)",
            work_mode="remote",
            experience_level=detect_experience_level(title, None),
            salary_min=float(smin) if smin else None,
            salary_max=float(smax) if smax else None,
            salary_currency="USD" if (smin or smax) else None,
            published_at=from_epoch(job.get("epoch")),
            remote_eligibility=eligibility,
            remote_regions=regions,
            raw_metadata={
                "queries": raw.data.get("queries", []),
                "tags": (job.get("tags") or [])[:12],
                "attribution": "Source : Remote OK (remoteok.com)",
                "eligibility_basis": "location" if location else None,
            },
        )

    async def health_check(self) -> HealthResult:
        def check(payload: Any) -> tuple[bool, str, int | None]:
            if not isinstance(payload, list) or len(payload) < 2:
                return False, "format de réponse modifié", None
            return True, f"{len(payload) - 1} offre(s) dans le flux", len(payload) - 1

        return await self._health_get(API, check=check, as_json=True)
