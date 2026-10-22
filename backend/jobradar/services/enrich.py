"""Enrichissement déterministe : contrat, mode de travail, expérience, secteur, éligibilité télétravail.

Principe de transparence : une fonction renvoie None quand l'information n'est pas présente dans le texte.
Elle ne « complète » jamais une valeur absente par une valeur par défaut.
"""

from __future__ import annotations

import re

from .text import normalize_text

# --------------------------------------------------------------------------- contrat
CONTRACT_VALUES = ("cdi", "cdd", "stage", "freelance", "alternance", "interim", "full_time", "part_time", "contract")

_CONTRACT_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("stage", re.compile(r"\b(stage|stagiaire|internship|intern|trainee)\b")),
    ("alternance", re.compile(r"\b(alternance|apprentissage|apprenti|work study)\b")),
    ("cdi", re.compile(r"\b(cdi|contrat a duree indeterminee|permanent)\b")),
    ("cdd", re.compile(r"\b(cdd|contrat a duree determinee|fixed term|temporary)\b")),
    ("interim", re.compile(r"\b(interim|mission d interim|temp agency)\b")),
    ("freelance", re.compile(r"\b(freelance|free lance|independant|independent contractor|consultant independant|prestation de services?)\b")),
    ("part_time", re.compile(r"\b(part time|temps partiel|mi temps)\b")),
    ("full_time", re.compile(r"\b(full time|temps plein|fulltime|full_time)\b")),
    ("contract", re.compile(r"\b(contract|contractor|contrat)\b")),
]


def detect_contract(*texts: str | None) -> str | None:
    """Détecte le type de contrat à partir de libellés (le premier texte est prioritaire)."""
    for text in texts:
        norm = normalize_text(text)
        if not norm:
            continue
        for value, pattern in _CONTRACT_RULES:
            if pattern.search(norm):
                return value
    return None


def map_schema_employment_type(value: str | list[str] | None) -> str | None:
    """schema.org `employmentType` (FULL_TIME, CONTRACTOR, INTERN...) → valeurs internes."""
    if not value:
        return None
    items = value if isinstance(value, list) else [value]
    for item in items:
        v = normalize_text(str(item)).replace(" ", "_")
        if v in {"full_time", "fulltime"}:
            return "full_time"
        if v in {"part_time", "parttime"}:
            return "part_time"
        if v in {"intern", "internship"}:
            return "stage"
        if v in {"contractor", "contract", "temporary"}:
            return "contract"
        if v in {"freelance"}:
            return "freelance"
        if v in {"permanent"}:
            return "cdi"
    return None


# --------------------------------------------------------------------------- mode de travail
_REMOTE = re.compile(r"\b(teletravail|tele travail|remote|a distance|work from home|wfh|distanciel|telecommute)\b")
_HYBRID = re.compile(r"\b(hybride|hybrid|teletravail partiel|partial remote)\b")
_ONSITE = re.compile(r"\b(presentiel|on site|onsite|sur site|in office|on premise)\b")
# Dans une description, une simple mention (« télétravail possible ») ne suffit pas à classer le poste en remote.
_REMOTE_STRONG = re.compile(
    r"\b(100 remote|100 a distance|fully remote|full remote|remote first|remote only|entierement a distance|"
    r"teletravail complet|teletravail total|teletravail a 100|poste en teletravail|poste a distance|"
    r"remote position|remote role|work from anywhere)\b"
)
_HYBRID_DESC = re.compile(
    r"\b(hybride|hybrid|teletravail partiel|teletravail possible|possibilite de teletravail|"
    r"jours? de teletravail|teletravail occasionnel|partial remote)\b"
)


def detect_work_mode(title: str | None = None, location: str | None = None, description: str | None = None) -> str | None:
    """Mode de travail. Titre/lieu : motifs larges. Description : uniquement des formulations explicites."""
    for text in (title, location):
        norm = normalize_text(text)
        if not norm:
            continue
        if _HYBRID.search(norm):
            return "hybrid"
        if _REMOTE.search(norm):
            return "remote"
        if _ONSITE.search(norm):
            return "onsite"
    desc = normalize_text((description or "")[:6000])
    if desc:
        if _REMOTE_STRONG.search(desc):
            return "remote"
        if _HYBRID_DESC.search(desc):
            return "hybrid"
        if _ONSITE.search(desc):
            return "onsite"
    return None


# --------------------------------------------------------------------------- expérience
EXPERIENCE_LEVELS = ("intern", "junior", "mid", "senior", "lead")

_YEARS_RANGE = re.compile(r"(\d{1,2})\s*(?:ans?|years?|yrs?)?\s*(?:a|-|to|et)\s*(\d{1,2})\s*(?:\+\s*)?(?:ans?|years?|yrs?)")
_YEARS_MIN = re.compile(r"(?:min(?:imum)?\s*)?(\d{1,2})\s*\+?\s*(?:ans?|years?|yrs?)(?:\s+d\s*(?:experience|exp))?")
_LEVEL_TITLE: list[tuple[str, re.Pattern[str]]] = [
    ("intern", re.compile(r"\b(stage|stagiaire|intern|internship|trainee|alternance|apprenti)\b")),
    ("lead", re.compile(r"\b(lead|head of|chief|cto|cio|directeur|directrice|director|manager|chef de|responsable|vp)\b")),
    ("senior", re.compile(r"\b(senior|sr|expert|principal|staff|confirme|experimente)\b")),
    ("junior", re.compile(r"\b(junior|jr|debutant|entry level|jeune diplome|graduate)\b")),
    ("mid", re.compile(r"\b(mid level|intermediaire|intermediate)\b")),
]


def _years_to_level(years: float) -> str:
    if years <= 2:
        return "junior"
    if years < 5:
        return "mid"
    return "senior"


def detect_experience_level(title: str | None, description: str | None = None) -> str | None:
    """Niveau d'expérience : mots-clés du titre d'abord, puis années d'expérience citées dans le texte."""
    t = normalize_text(title)
    for level, pattern in _LEVEL_TITLE:
        if t and pattern.search(t):
            return level
    d = normalize_text((description or "")[:6000])
    if not d:
        return None
    m = _YEARS_RANGE.search(d)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if 0 <= lo <= hi <= 40:
            return _years_to_level((lo + hi) / 2)
    m = _YEARS_MIN.search(d)
    if m and "experience" in d[max(0, m.start() - 80): m.end() + 80]:
        years = int(m.group(1))
        if 0 <= years <= 40:
            return _years_to_level(years)
    for level, pattern in _LEVEL_TITLE:
        if level in {"junior", "senior", "mid"} and pattern.search(d):
            return level
    return None


# --------------------------------------------------------------------------- secteur
# clé canonique → (libellé, mots-clés normalisés). Utilisé pour détecter le secteur d'une annonce et pour
# faire correspondre les secteurs libres saisis dans un profil.
SECTORS: dict[str, tuple[str, list[str]]] = {
    "fintech": ("Fintech", ["fintech", "paiement", "paiements", "mobile money", "monnaie electronique", "wallet", "payment", "payments", "wave", "orange money", "intouch", "neero", "paydunya"]),
    "banque": ("Banque", ["banque", "bank", "bancaire", "banking", "microfinance", "bceao", "ecobank", "cbao", "societe generale", "attijariwafa", "bicis", "boa "]),
    "assurance": ("Assurance", ["assurance", "assurances", "insurance", "assureur", "mutuelle", "reassurance"]),
    "telecoms": ("Télécommunications", ["telecom", "telecoms", "telecommunications", "operateur mobile", "sonatel", "orange", "free senegal", "expresso", "tigo", "yas", "reseau mobile", "fibre optique"]),
    "esn": ("ESN / Services informatiques", ["esn", "ssii", "societe de services numeriques", "services informatiques", "conseil it", "it consulting", "alten", "capgemini", "sopra", "atos", "cgi ", "accenture", "software house", "agence digitale", "digital agency", "integrateur"]),
    "startup": ("Startups technologiques", ["startup", "start up", "scale up", "scaleup", "jeune pousse", "incubateur"]),
    "ong": ("ONG / Organisations internationales", ["ong ", "ngo", "nations unies", "united nations", "unicef", "pnud", "undp", "onu", "humanitaire", "fondation", "unesco", "oxfam"]),
    "sante": ("Santé", ["sante", "hopital", "clinique", "pharmacie", "medical", "health"]),
    "energie": ("Énergie / Mines", ["energie", "petrole", "gaz", "mines", "minier", "solaire", "electricite", "senelec"]),
    "commerce": ("Commerce / Distribution", ["distribution", "commerce", "retail", "grande distribution", "e commerce", "ecommerce"]),
}

# Alias libres (profil) → clés canoniques
_SECTOR_ALIASES: dict[str, str] = {
    "fintech": "fintech", "banque": "banque", "banques": "banque", "banking": "banque", "bank": "banque",
    "assurance": "assurance", "assurances": "assurance", "insurance": "assurance",
    "telecommunications": "telecoms", "telecoms": "telecoms", "telecom": "telecoms", "telecommunication": "telecoms",
    "esn": "esn", "ssii": "esn", "services informatiques": "esn", "service informatique": "esn", "it services": "esn",
    "startups technologiques": "startup", "startup": "startup", "startups": "startup", "start up": "startup",
    "ong": "ong", "sante": "sante", "energie": "energie", "commerce": "commerce",
}


def sector_key_for_profile_sector(value: str) -> str | None:
    return _SECTOR_ALIASES.get(normalize_text(value))


def detect_sectors(*texts: str | None) -> list[str]:
    """Clés de secteurs reconnues dans le texte (entreprise, titre, description)."""
    blob = " " + normalize_text(" ".join(t for t in texts if t)) + " "
    found: list[str] = []
    for key, (_label, words) in SECTORS.items():
        if any(f" {w.strip()} " in blob for w in words if w.strip()):
            found.append(key)
    return found


# --------------------------------------------------------------------------- éligibilité télétravail
_ELIGIBLE_MARKERS = (
    "worldwide", "anywhere", "global", "world wide", "work from anywhere", "all countries", "any country",
    "africa", "emea", "west africa", "senegal", "sub saharan", "sub-saharan", "international", "open to all",
)
_RESTRICTED_MARKERS = (
    "us only", "usa only", "united states", "u s", "canada", "north america", "latam", "latin america",
    "apac", "asia", "india", "europe only", "eu only", "uk only", "united kingdom", "australia", "only",
)
_EU_WORDS = ("europe", "eu", "european union")


def classify_remote_eligibility(
    restrictions: list[str] | str | None,
    *,
    home_country_names: tuple[str, ...] = ("senegal",),
    unmarked: str = "restricted",
) -> tuple[str, list[str]]:
    """Évalue si un poste télétravail est ouvert depuis le Sénégal.

    Retourne (statut, régions citées) avec statut ∈ {eligible, restricted, unknown}.
    `unknown` quand la source ne donne aucune restriction exploitable : on ne présume rien.
    `unmarked` : statut renvoyé pour une liste de lieux sans marqueur explicite (« only », pays fermés...) : « restricted »
    quand la source publie de vraies restrictions de pays, « unknown » quand le lieu est une simple indication.
    """
    if restrictions is None:
        return "unknown", []
    items = restrictions if isinstance(restrictions, list) else [restrictions]
    generic = {"remote", "fully remote", "100 remote", "100% remote", "telecommute", "virtual", "n a", "unspecified"}
    items = [str(i).strip() for i in items if i and str(i).strip() and normalize_text(str(i)) not in generic]
    if not items:
        return "unknown", []
    regions = items[:12]
    norm_items = [normalize_text(i) for i in items]
    blob = " | ".join(norm_items)

    if any(h in n.split() or h in n for n in norm_items for h in home_country_names):
        return "eligible", regions
    if any(m in blob for m in ("worldwide", "anywhere", "world wide", "global", "all countries", "any country", "work from anywhere")):
        return "eligible", regions
    if "africa" in blob or "emea" in blob or "sub saharan" in blob:
        return "eligible", regions
    # liste de pays qui ne contient pas le Sénégal ou mention d'une région fermée
    if any(m in blob for m in ("only", "united states", "usa", "canada", "latam", "latin america", "apac", "asia", "india", "united kingdom", "australia", "north america")):
        return "restricted", regions
    if any(w in blob.split() for w in _EU_WORDS):
        return "restricted", regions
    # une liste de lieux sans Sénégal ni mention ouverte
    return unmarked, regions
