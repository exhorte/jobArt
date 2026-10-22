"""Score de pertinence déterministe (0-100) d'une annonce par rapport à un profil de recherche.

Fonction pure et testable : `score_offer(offer, profile, now=...) -> ScoreResult`. Aucun LLM, aucun accès réseau/BD.

Pondérations par défaut : métier 30, compétences 25, localisation/éligibilité 15, expérience 10, secteur 10,
contrat/mode de travail 10 (surchargeables par profil ; un poids à 0 désactive le critère).

Règles de transparence :
* un champ absent n'est JAMAIS une correspondance positive (0 point) et est listé dans « informations manquantes » ;
* l'absence de salaire n'est pas un critère : elle ne pénalise rien ;
* le score mesure la proximité avec les critères du profil. Ce n'est PAS une probabilité d'embauche.

score = points obtenus / points possibles selon les critères définis dans le profil, ramené à 100.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .enrich import EXPERIENCE_LEVELS, SECTORS, detect_sectors, sector_key_for_profile_sector
from .text import normalize_text

DEFAULT_WEIGHTS: dict[str, float] = {
    "role": 30.0,
    "skills": 25.0,
    "location": 15.0,
    "experience": 10.0,
    "sector": 10.0,
    "contract_work_mode": 10.0,
}
COMPONENT_LABELS = {
    "role": "Métier",
    "skills": "Compétences techniques",
    "location": "Localisation et éligibilité",
    "experience": "Niveau d'expérience",
    "sector": "Secteur",
    "contract_work_mode": "Contrat et mode de travail",
}
EXCLUDED_IN_DESCRIPTION_PENALTY = 20.0
SCORE_DISCLAIMER = "Score de proximité avec les critères du profil, pas une probabilité d'embauche."

# ---- équivalences FR/EN pour comparer les intitulés
_PHRASES = [
    (r"\bintelligence artificielle\b", "ai"),
    (r"\bartificial intelligence\b", "ai"),
    (r"\bmachine learning\b", "ml"),
    (r"\bapprentissage automatique\b", "ml"),
    (r"\bfull[\s-]?stack\b", "fullstack"),
    (r"\bfront[\s-]?end\b", "frontend"),
    (r"\bback[\s-]?end\b", "backend"),
    (r"\bdata scientist\b", "datascientist"),
    (r"\bdata engineer\b", "dataengineer"),
    (r"\bdata analyst\b", "dataanalyst"),
    (r"\bingenieur donnees\b", "dataengineer"),
    (r"\bdevops\b", "devops"),
    (r"\bmlops\b", "mlops"),
]
_TOKEN_MAP = {
    "developer": "dev", "developers": "dev", "developpeur": "dev", "developpeurs": "dev", "developpeuse": "dev",
    "developpeuses": "dev", "dev": "dev", "programmer": "dev", "programmeur": "dev", "programmeuse": "dev",
    "engineer": "eng", "engineers": "eng", "ingenieur": "eng", "ingenieurs": "eng", "ingenieure": "eng", "ingenieures": "eng",
    "logiciel": "sw", "logiciels": "sw", "software": "sw", "ia": "ai", "web": "web", "donnees": "data",
}
_STOP = {"de", "du", "des", "la", "le", "les", "en", "et", "a", "au", "aux", "d", "l", "of", "the", "and", "for", "to", "h", "f", "m"}


def canon_tokens(text: str | None) -> list[str]:
    n = " " + normalize_text(text) + " "
    for pattern, repl in _PHRASES:
        n = re.sub(pattern, f" {repl} ", n)
    return [_TOKEN_MAP.get(t, t) for t in n.split() if t not in _STOP and len(t) > 0]


# --------------------------------------------------------------------------- entrées / sorties
@dataclass
class ProfileCriteria:
    id: int | None = None
    name: str = ""
    countries: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    positive_keywords: list[str] = field(default_factory=list)
    keyword_groups: dict[str, list[str]] = field(default_factory=dict)
    excluded_keywords: list[str] = field(default_factory=list)
    target_roles: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    contract_types: list[str] = field(default_factory=list)
    work_modes: list[str] = field(default_factory=list)
    experience_levels: list[str] = field(default_factory=list)
    weights: dict[str, float] | None = None

    @classmethod
    def from_model(cls, p: Any) -> ProfileCriteria:
        return cls(
            id=p.id, name=p.name, countries=list(p.countries or []), cities=list(p.cities or []),
            positive_keywords=list(p.positive_keywords or []), keyword_groups=dict(p.keyword_groups or {}),
            excluded_keywords=list(p.excluded_keywords or []), target_roles=list(p.target_roles or []),
            sectors=list(p.sectors or []), contract_types=list(p.contract_types or []),
            work_modes=list(p.work_modes or []), experience_levels=list(p.experience_levels or []),
            weights=dict(p.weights) if p.weights else None,
        )

    def effective_weights(self) -> dict[str, float]:
        w = dict(DEFAULT_WEIGHTS)
        for k, v in (self.weights or {}).items():
            if k in w:
                try:
                    w[k] = max(0.0, float(v))
                except (TypeError, ValueError):
                    pass
        return w


@dataclass
class ScorableOffer:
    title: str
    company_name: str | None = None
    description: str | None = None
    location: str | None = None
    country: str | None = None
    city: str | None = None
    work_mode: str | None = None
    contract_type: str | None = None
    experience_level: str | None = None
    sector: str | None = None
    industry: str | None = None
    remote_eligibility: str | None = None
    remote_regions: list[str] = field(default_factory=list)

    @classmethod
    def from_model(cls, o: Any) -> ScorableOffer:
        return cls(
            title=o.title, company_name=o.company_name, description=o.description, location=o.location,
            country=o.country, city=o.city, work_mode=o.work_mode, contract_type=o.contract_type,
            experience_level=o.experience_level, sector=o.sector, remote_eligibility=o.remote_eligibility,
            remote_regions=list(o.remote_regions or []),
        )


@dataclass
class ScoreResult:
    score: float
    breakdown: dict[str, dict[str, Any]]
    explanation: dict[str, Any]


# --------------------------------------------------------------------------- composantes
def _phrase_in(blob: str, phrase: str) -> bool:
    np_ = normalize_text(phrase)
    return bool(np_) and any(f" {np_}{s} " in blob for s in ("", "s", "x"))


def _role_component(offer: ScorableOffer, profile: ProfileCriteria) -> tuple[float, str, list[str]]:
    candidates = list(dict.fromkeys([*profile.target_roles, *profile.positive_keywords]))
    if not candidates:
        return 0.0, "aucun métier/mot-clé défini dans le profil", []
    title_norm = " " + normalize_text(offer.title) + " "
    title_tokens = set(canon_tokens(offer.title))
    best, best_kw, how = 0.0, None, ""
    for kw in candidates:
        if _phrase_in(title_norm, kw):
            tier, why = 1.0, "expression présente dans le titre"
        else:
            kt = set(canon_tokens(kw))
            if not kt:
                continue
            common = kt & title_tokens
            if kt <= title_tokens and len(kt) >= 1:
                tier, why = 0.85, "tous les termes présents dans le titre"
            elif len(kt) >= 3 and len(common) / len(kt) >= 0.66:
                tier, why = 0.5, "termes principaux présents dans le titre"
            else:
                continue
        if tier > best:
            best, best_kw, how = tier, kw, why
    if best > 0:
        return best, f"« {best_kw} » : {how}", [best_kw] if best_kw else []
    desc = " " + normalize_text((offer.description or "")[:6000]) + " "
    hits = [kw for kw in candidates if _phrase_in(desc, kw)]
    if hits:
        return 0.3, f"« {hits[0]} » trouvé dans la description seulement, pas dans le titre", hits[:3]
    return 0.0, "aucun métier du profil reconnu dans le titre", []


def _skills_component(offer: ScorableOffer, profile: ProfileCriteria) -> tuple[float | None, str, list[str], list[str]]:
    skills = [s for group in profile.keyword_groups.values() for s in group if s and normalize_text(s)]
    if not skills:
        return None, "aucune compétence définie dans le profil", [], []
    text = " " + normalize_text(f"{offer.title} {(offer.description or '')[:8000]}") + " "
    matched = [s for s in dict.fromkeys(skills) if _phrase_in(text, s) and len(normalize_text(s)) >= 2]
    missing: list[str] = []
    if not (offer.description and len(offer.description) >= 40):
        missing.append("description (compétences non évaluables au-delà du titre)")
    target = max(1, min(5, len(set(skills))))
    fraction = min(1.0, len(matched) / target)
    detail = f"{len(matched)} compétence(s) du profil trouvée(s) (objectif {target})" if matched else "aucune compétence du profil trouvée"
    return fraction, detail, matched, missing


def _location_component(offer: ScorableOffer, profile: ProfileCriteria) -> tuple[float | None, str, list[str], list[str], str | None]:
    """(fraction, détail, restrictions, manquants, étiquette compatible)."""
    restrictions: list[str] = []
    missing: list[str] = []
    countries = {c.upper() for c in profile.countries}
    cities_norm = [normalize_text(c) for c in profile.cities]
    remote = offer.work_mode == "remote"
    if not countries and not cities_norm and not profile.work_modes:
        return None, "aucun critère géographique dans le profil", [], [], None

    if remote:
        if "remote" not in profile.work_modes and profile.work_modes:
            return 0.0, "télétravail non souhaité par le profil", [], [], None
        if offer.remote_eligibility == "eligible":
            return 1.0, "télétravail ouvert depuis le Sénégal", [], [], "télétravail éligible"
        if offer.remote_eligibility == "restricted":
            restrictions = [f"restrictions géographiques : {', '.join(offer.remote_regions[:5]) or 'non précisées'}"]
            return 0.0, "télétravail restreint à d'autres zones", restrictions, [], None
        # éligibilité inconnue : on ne présume rien, mais un employeur situé dans le pays du profil reste compatible
        if offer.country and offer.country.upper() in countries:
            return 1.0, "télétravail, employeur/lieu dans le pays du profil", [], [], f"télétravail ({offer.country})"
        missing.append("éligibilité géographique du télétravail")
        return 0.0, "télétravail : éligibilité depuis le Sénégal non précisée", [], missing, None

    if offer.city and normalize_text(offer.city) in cities_norm:
        idx = cities_norm.index(normalize_text(offer.city))
        return (1.0 if idx == 0 else 0.9), f"ville {'prioritaire' if idx == 0 else 'souhaitée'} : {offer.city}", [], [], offer.city
    if offer.country and offer.country.upper() in countries:
        city_note = "différente" if offer.city else "non précisée"
        return 0.6, f"pays du profil ({offer.country}), ville {city_note}", [], ([] if offer.city else ["ville"]), offer.country
    if offer.country or offer.city:
        return 0.0, "lieu hors des zones du profil", [], [], None
    return 0.0, "lieu non précisé", [], ["localisation"], None


def _experience_component(offer: ScorableOffer, profile: ProfileCriteria) -> tuple[float | None, str, list[str]]:
    wanted = [lvl for lvl in profile.experience_levels if lvl in EXPERIENCE_LEVELS]
    if not wanted:
        return None, "aucun niveau d'expérience défini dans le profil", []
    if not offer.experience_level:
        return 0.0, "niveau d'expérience non précisé", ["niveau d'expérience"]
    if offer.experience_level in wanted:
        return 1.0, f"niveau {offer.experience_level} souhaité", []
    pos = EXPERIENCE_LEVELS.index(offer.experience_level)
    if min(abs(pos - EXPERIENCE_LEVELS.index(w)) for w in wanted) == 1:
        return 0.5, f"niveau {offer.experience_level} voisin des niveaux souhaités", []
    return 0.0, f"niveau {offer.experience_level} hors des niveaux souhaités", []


def _sector_component(offer: ScorableOffer, profile: ProfileCriteria) -> tuple[float | None, str, list[str], list[str]]:
    if not profile.sectors:
        return None, "aucun secteur défini dans le profil", [], []
    wanted_keys = {sector_key_for_profile_sector(s) or normalize_text(s) for s in profile.sectors}
    detected = set(detect_sectors(offer.company_name, offer.title, (offer.description or "")[:4000], offer.industry))
    if offer.sector:
        detected.add(offer.sector)
    if not detected:
        return 0.0, "secteur non déterminé", [], ["secteur"]
    common = sorted(wanted_keys & detected)
    labels = [SECTORS[k][0] if k in SECTORS else k for k in common]
    if common:
        return 1.0, f"secteur correspondant : {', '.join(labels)}", labels, []
    names = [SECTORS[k][0] if k in SECTORS else k for k in sorted(detected)]
    return 0.0, f"secteur détecté hors profil : {', '.join(names)}", [], []


def _contract_mode_component(offer: ScorableOffer, profile: ProfileCriteria) -> tuple[float | None, str, list[str]]:
    parts: list[float] = []
    details: list[str] = []
    missing: list[str] = []
    if profile.contract_types:
        if not offer.contract_type:
            parts.append(0.0)
            missing.append("type de contrat")
            details.append("contrat non précisé")
        elif offer.contract_type in profile.contract_types:
            parts.append(1.0)
            details.append(f"contrat {offer.contract_type} accepté")
        else:
            parts.append(0.0)
            details.append(f"contrat {offer.contract_type} hors profil")
    if profile.work_modes:
        if not offer.work_mode:
            parts.append(0.0)
            missing.append("mode de travail")
            details.append("mode de travail non précisé")
        elif offer.work_mode in profile.work_modes:
            parts.append(1.0)
            details.append(f"mode {offer.work_mode} accepté")
        else:
            parts.append(0.0)
            details.append(f"mode {offer.work_mode} hors profil")
    if not parts:
        return None, "aucun critère de contrat/mode dans le profil", []
    return sum(parts) / len(parts), " ; ".join(details), missing


# --------------------------------------------------------------------------- score global
def score_offer(offer: ScorableOffer, profile: ProfileCriteria, *, now: datetime | None = None) -> ScoreResult:
    weights = profile.effective_weights()
    matched_keywords: list[str] = []
    restrictions: list[str] = []
    missing: list[str] = []
    notes: list[str] = []
    comps: dict[str, tuple[float | None, str]] = {}

    role_f, role_d, role_hits = _role_component(offer, profile)
    comps["role"] = (role_f, role_d)
    matched_keywords += role_hits

    skills_f, skills_d, skill_hits, skill_missing = _skills_component(offer, profile)
    comps["skills"] = (skills_f, skills_d)
    matched_keywords += skill_hits
    missing += skill_missing

    loc_f, loc_d, loc_restr, loc_missing, loc_label = _location_component(offer, profile)
    comps["location"] = (loc_f, loc_d)
    restrictions += loc_restr
    missing += loc_missing

    exp_f, exp_d, exp_missing = _experience_component(offer, profile)
    comps["experience"] = (exp_f, exp_d)
    missing += exp_missing

    sec_f, sec_d, sec_labels, sec_missing = _sector_component(offer, profile)
    comps["sector"] = (sec_f, sec_d)
    missing += sec_missing

    cm_f, cm_d, cm_missing = _contract_mode_component(offer, profile)
    comps["contract_work_mode"] = (cm_f, cm_d)
    missing += cm_missing

    breakdown: dict[str, dict[str, Any]] = {}
    earned = 0.0
    possible = 0.0
    for key, (fraction, detail) in comps.items():
        w = weights.get(key, 0.0)
        applicable = fraction is not None and w > 0
        pts = (fraction or 0.0) * w if applicable else 0.0
        if applicable:
            earned += pts
            possible += w
        breakdown[key] = {
            "label": COMPONENT_LABELS[key],
            "points": round(pts, 1),
            "max": round(w if applicable else 0.0, 1),
            "applicable": applicable,
            "detail": detail,
        }

    score = 100.0 * earned / possible if possible > 0 else 0.0

    # Mots exclus : titre/entreprise → 0 ; description → -20 points
    title_blob = " " + normalize_text(f"{offer.title} {offer.company_name or ''}") + " "
    desc_blob = " " + normalize_text((offer.description or "")[:6000]) + " "
    excluded_hits = [k for k in profile.excluded_keywords if _phrase_in(title_blob, k)]
    excluded_desc = [k for k in profile.excluded_keywords if k not in excluded_hits and _phrase_in(desc_blob, k)]
    if excluded_hits:
        score = 0.0
        notes.append(f"Mot-clé exclu dans le titre : {', '.join(excluded_hits)}")
    elif excluded_desc:
        score = max(0.0, score - EXCLUDED_IN_DESCRIPTION_PENALTY)
        notes.append(f"Mot-clé exclu dans la description : {', '.join(excluded_desc)} (−{int(EXCLUDED_IN_DESCRIPTION_PENALTY)} points)")

    explanation = {
        "matched_keywords": list(dict.fromkeys(matched_keywords)),
        "role": comps["role"][1],
        "sector": sec_labels,
        "location": loc_label,
        "restrictions": restrictions,
        "missing": list(dict.fromkeys(missing)),
        "excluded": excluded_hits + excluded_desc,
        "notes": notes + [SCORE_DISCLAIMER],
        "coverage": round(possible, 1),
    }
    return ScoreResult(score=round(min(100.0, max(0.0, score)), 1), breakdown=breakdown, explanation=explanation)


def score_to_int(score: float) -> int:
    return int(math.floor(score + 0.5))
