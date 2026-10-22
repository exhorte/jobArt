"""Déduplication prudente des annonces (4 niveaux). Dans le doute, on garde les annonces séparées.

Niveau 1 : identifiant d'annonce fourni par la source (même source).
Niveau 2 : URL normalisée (originale ou `sameAs` déclarée par la source) — toutes sources.
Niveau 3 : identité = entreprise normalisée + titre normalisé + localisation compatible (entreprise connue des deux côtés).
Niveau 4 : similarité de chaînes/contenu (titre très proche, ou titre proche + descriptions quasi identiques).

Garde-fous :
* deux annonces d'une MÊME source ne sont jamais fusionnées par identité/similarité (une source publie parfois dix
  postes au même intitulé dans des villes différentes) ;
* villes connues et différentes → annonces distinctes ; dates de publication éloignées (> 45 j) → republication distincte ;
* si plusieurs candidats sont à égalité → ambigu → aucune fusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collectors.base import NormalizedJob
from ..models import JobOffer, JobOfferSource, JobSource, OfferUrlKey
from .geo import LOCATION_WORDS
from .text import jaccard, normalize_company, normalize_text, normalize_title, token_set

EXACT_TITLE = 1.0
SIMILAR_TITLE = 0.92
FUZZY_TITLE = 0.80
CONTENT_JACCARD = 0.75
MAX_PUBLICATION_GAP_DAYS = 45


@dataclass(frozen=True)
class Identity:
    title: str  # titre normalisé
    company: str | None  # entreprise normalisée (None si inconnue)
    city: str | None  # ville normalisée
    country: str | None
    description_tokens: frozenset[str]


def build_identity(job: NormalizedJob) -> Identity:
    return Identity(
        title=normalize_title(job.title, location_words=LOCATION_WORDS),
        company=normalize_company(job.company_name),
        city=normalize_text(job.city) or None,
        country=(job.country or "").upper() or None,
        description_tokens=frozenset(token_set(job.description or "")),
    )


@dataclass
class Match:
    offer: JobOffer | None = None
    reason: str | None = None  # source_job_id | source_url | url | same_as | identity | similarity | content
    cross_source: bool = False  # True : l'annonce existait déjà via une AUTRE source (doublon inter-sources)
    ambiguous: list[JobOffer] = field(default_factory=list)


def _location_compatible(a: Identity, b_city: str | None, b_country: str | None) -> bool:
    if a.city and b_city:
        return a.city == normalize_text(b_city)
    if a.country and b_country:
        return a.country == b_country.upper()
    return True


def _dates_compatible(a_pub, b_pub) -> bool:
    if a_pub is None or b_pub is None:
        return True
    return abs((a_pub - b_pub).days) <= MAX_PUBLICATION_GAP_DAYS


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def classify_pair(
    *,
    title_a: str,
    title_b: str,
    desc_a: frozenset[str] | set[str],
    desc_b: frozenset[str] | set[str],
) -> tuple[str | None, float]:
    """(raison, similarité) pour deux annonces au titre/entreprise/lieu déjà jugés compatibles."""
    sim = _title_similarity(title_a, title_b)
    if sim >= EXACT_TITLE:
        return "identity", sim
    if sim >= SIMILAR_TITLE:
        return "similarity", sim
    if sim >= FUZZY_TITLE and len(desc_a) >= 60 and len(desc_b) >= 60 and jaccard(set(desc_a), set(desc_b)) >= CONTENT_JACCARD:
        return "content", sim
    return None, sim


def find_match(
    session: Session,
    source: JobSource,
    job: NormalizedJob,
    *,
    url_key_: str,
    alias_keys: list[str],
    identity: Identity,
) -> Match:
    # --- niveau 1 : identifiant de la source
    if job.source_job_id:
        row = session.scalar(
            select(JobOfferSource).where(
                JobOfferSource.job_source_id == source.id, JobOfferSource.source_job_id == job.source_job_id
            )
        )
        if row:
            return Match(row.offer, "source_job_id", cross_source=False)
    # --- niveau 2 : URL (même source, puis toutes sources, puis `sameAs`)
    row = session.scalar(
        select(JobOfferSource).where(JobOfferSource.job_source_id == source.id, JobOfferSource.original_url_key == url_key_)
    )
    if row:
        return Match(row.offer, "source_url", cross_source=False)
    for key, reason in [(url_key_, "url"), *[(k, "same_as") for k in alias_keys]]:
        hit = session.get(OfferUrlKey, key)
        if hit:
            offer = session.get(JobOffer, hit.job_offer_id)
            if offer:
                same_source = any(s.job_source_id == source.id for s in offer.sources)
                return Match(offer, reason, cross_source=not same_source)
    # --- niveaux 3 et 4 : identité / similarité (entreprise connue obligatoire)
    if not identity.company:
        return Match()
    candidates = session.scalars(select(JobOffer).where(JobOffer.normalized_company == identity.company)).all()
    scored: list[tuple[int, float, str, JobOffer]] = []
    rank = {"identity": 3, "similarity": 2, "content": 1}
    for cand in candidates:
        if any(s.job_source_id == source.id for s in cand.sources):
            continue  # annonce distincte de la même source
        if not _location_compatible(identity, cand.city, cand.country):
            continue
        if not _dates_compatible(job.published_at, cand.published_at):
            continue
        reason, sim = classify_pair(
            title_a=identity.title,
            title_b=cand.normalized_title,
            desc_a=identity.description_tokens,
            desc_b=frozenset(token_set(cand.description or "")),
        )
        if reason:
            scored.append((rank[reason], sim, reason, cand))
    if not scored:
        return Match()
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    best = scored[0]
    ties = [s for s in scored if (s[0], round(s[1], 3)) == (best[0], round(best[1], 3))]
    if len(ties) > 1:
        return Match(ambiguous=[t[3] for t in ties])
    return Match(best[3], best[2], cross_source=True)


# --------------------------------------------------------------------------- rapprochement a posteriori
def find_identity_duplicate(session: Session, offer: JobOffer) -> JobOffer | None:
    """Cherche une AUTRE annonce enregistrée qui est le même poste (utile quand `offer` vient d'obtenir son entreprise).

    Mêmes garde-fous que `find_match` ; renvoie None si absent ou ambigu.
    """
    if not offer.normalized_company:
        return None
    my_sources = {s.job_source_id for s in offer.sources}
    ident_title = offer.normalized_title
    my_tokens = frozenset(token_set(offer.description or ""))
    me = Identity(ident_title, offer.normalized_company, normalize_text(offer.city) or None, offer.country, my_tokens)
    best: list[tuple[int, float, JobOffer]] = []
    rank = {"identity": 3, "similarity": 2, "content": 1}
    for cand in session.scalars(
        select(JobOffer).where(JobOffer.normalized_company == offer.normalized_company, JobOffer.id != offer.id)
    ):
        if my_sources & {s.job_source_id for s in cand.sources}:
            continue
        if not _location_compatible(me, cand.city, cand.country) or not _dates_compatible(offer.published_at, cand.published_at):
            continue
        reason, sim = classify_pair(
            title_a=ident_title, title_b=cand.normalized_title, desc_a=my_tokens, desc_b=frozenset(token_set(cand.description or ""))
        )
        if reason:
            best.append((rank[reason], sim, cand))
    if not best:
        return None
    best.sort(key=lambda t: (t[0], t[1]), reverse=True)
    if len(best) > 1 and (best[0][0], round(best[0][1], 3)) == (best[1][0], round(best[1][1], 3)):
        return None
    return best[0][2]
