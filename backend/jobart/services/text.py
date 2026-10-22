"""Normalisation de texte déterministe (accents, casse, ponctuation, marqueurs H/F, formes juridiques)."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")

# « (H/F) », « F/H », « (e) », « (euse) »... Marqueurs sans valeur d'identité.
_GENDER = re.compile(
    r"\(\s*[hfm]\s*/\s*[hfmwd]\s*(?:/\s*[hfmwdx])?\s*\)|\b[hfm]\s*/\s*[hfmwd]\b|\(\s*(?:e|es|euse|trice|ne|rice)\s*\)|\(\s*e\s*\)\s*",
    re.IGNORECASE,
)
_REF_CODE = re.compile(r"\b(?:ref|réf|référence|reference)\s*[:.\-]?\s*[\w\-/]+", re.IGNORECASE)

_COMPANY_SUFFIX_TOKENS = {
    "sarl", "sa", "sas", "sasu", "suarl", "sarlu", "ltd", "llc", "inc", "gmbh", "plc", "limited",
    "group", "groupe", "holding", "senegal", "sn", "cie", "company",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def collapse_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def normalize_text(text: str | None) -> str:
    """minuscules, sans accents, ponctuation → espace, espaces compactés."""
    if not text:
        return ""
    t = strip_accents(html.unescape(text)).lower().replace("’", "'").replace("œ", "oe")
    return collapse_ws(_NON_ALNUM.sub(" ", t))


def strip_gender_markers(title: str) -> str:
    return collapse_ws(_GENDER.sub(" ", title))


def normalize_title(title: str | None, *, location_words: set[str] | None = None) -> str:
    """Titre normalisé pour la déduplication : sans H/F, références, suffixe de lieu (« - Dakar »)."""
    if not title:
        return ""
    t = strip_gender_markers(html.unescape(title))
    t = _REF_CODE.sub(" ", t)
    # suffixe « - Dakar » / « , Dakar » / « – Almadies »
    if location_words:
        m = re.search(r"\s*[-–—,|@]\s*([^-–—,|@]{2,40})\s*$", t)
        if m and normalize_text(m.group(1)) in location_words:
            t = t[: m.start()]
    return normalize_text(t)


def normalize_company(name: str | None) -> str | None:
    if not name:
        return None
    toks = normalize_text(name).split()
    while len(toks) > 1 and toks[-1] in _COMPANY_SUFFIX_TOKENS:
        toks.pop()
    out = " ".join(toks)
    # noms « confidentiels » / génériques : pas d'identité exploitable
    if out in {"confidentiel", "confidential", "anonyme", "non communique", "n a", "na"}:
        return None
    return out or None


def html_to_text(raw: str | None, *, max_chars: int = 20000) -> str | None:
    """Convertit du HTML d'annonce en texte brut. Le contenu reste une donnée non fiable (jamais exécuté)."""
    if not raw:
        return None
    if "<" in raw and ">" in raw:
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(["script", "style", "noscript", "iframe"]):
            tag.decompose()
        for br in soup.find_all(["br", "p", "li", "div", "h1", "h2", "h3", "h4", "tr"]):
            br.append("\n")
        text = soup.get_text()
    else:
        text = html.unescape(raw)
    text = text.replace("‎", "").replace("‏", "").replace("\xa0", " ")
    lines = [collapse_ws(line) for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned[:max_chars] or None


def content_hash(*parts: str | None) -> str:
    """Empreinte stable du contenu significatif d'une annonce (détection de changement + doublons exacts)."""
    joined = "␟".join(normalize_text(p) for p in parts if p)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def token_set(text: str) -> set[str]:
    return {t for t in normalize_text(text).split() if len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def keyword_hits(text: str | None, keywords: list[str] | tuple[str, ...]) -> list[str]:
    """Mots-clés présents dans `text` (mot entier ou tous les mots d'une expression, pluriel simple toléré)."""
    blob = " " + normalize_text(text) + " "
    if not blob.strip():
        return []
    tokens = set(blob.split())
    hits: list[str] = []
    for kw in keywords:
        nk = normalize_text(kw)
        if not nk:
            continue
        if any(f" {nk}{suffix} " in blob for suffix in ("", "s", "x")):
            hits.append(kw)
            continue
        parts = [t for t in nk.split() if len(t) > 1]
        if len(parts) >= 2 and all(t in tokens or f"{t}s" in tokens for t in parts):
            hits.append(kw)
    return hits


def fix_mojibake(text: str | None) -> str | None:
    """Répare un texte UTF-8 mal décodé en latin-1 (« MÃ©xico » → « México »). Sans effet sur un texte sain."""
    if not text or not any(c in text for c in ("Ã", "â", "Â")):
        return text
    try:
        fixed = text.encode("cp1252", errors="strict").decode("utf-8", errors="strict")
        return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            return text.encode("latin-1", errors="strict").decode("utf-8", errors="strict")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
