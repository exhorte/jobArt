"""Normalisation et validation des URLs d'annonces.

* `clean_url`  : URL affichable/stockée (paramètres de suivi retirés, ancre retirée, schéma/hôte en minuscules).
* `url_key`    : clé de comparaison (sans schéma, sans `www.`, sans slash final, paramètres triés).
* `validate_job_url` : garantit un lien profond vers l'annonce (pas la page d'accueil ni la liste).

On conserve les paramètres porteurs d'identité (`id`, `jobId`, `p`...) : deux annonces différentes ne doivent
jamais se confondre. Seuls les paramètres de suivi connus sont retirés.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from ..core.errors import NormalizationError

_TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_")
_TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "mc_cid", "mc_eid", "igshid", "_ga", "_gl", "_hsenc",
    "_hsmi", "mkt_tok", "trk", "trkid", "trackingid", "refid", "ref_src", "ref_url", "cmpid", "li_fat_id",
    "s_kwcid", "wt.mc_id", "oly_enc_id", "oly_anon_id", "vero_id", "sref", "feature",
}


def _is_tracking(name: str) -> bool:
    n = name.lower()
    return n in _TRACKING_PARAMS or n.startswith(_TRACKING_PREFIXES)


def clean_url(url: str) -> str:
    """Retire ancre et paramètres de suivi ; ne modifie ni le chemin ni les identifiants."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if parts.port and not ((scheme == "http" and parts.port == 80) or (scheme == "https" and parts.port == 443)):
        host = f"{host}:{parts.port}"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)]
    # encodage des pourcents canonique (idempotent) : « é » et « %C3%A9 » désignent la même page
    path = quote(unquote(parts.path or "/"), safe="/:@!$&'()*+,;=-._~")
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def url_key(url: str) -> str:
    """Clé stable pour comparer deux URLs qui désignent la même page."""
    parts = urlsplit(clean_url(url))
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = sorted(parse_qsl(parts.query, keep_blank_values=True))
    return f"{host}{path}" + (f"?{urlencode(query)}" if query else "")


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def host_allowed(url: str, allowed_hosts: set[str] | list[str]) -> bool:
    host = host_of(url)
    allowed = {h.lower().removeprefix("www.") for h in allowed_hosts}
    return host in allowed


def validate_job_url(
    url: str | None,
    *,
    allowed_hosts: set[str] | list[str],
    forbidden_paths: set[str] | None = None,
) -> str:
    """Renvoie l'URL nettoyée ou lève NormalizationError.

    Refuse : URL vide, schéma non http(s), hôte non autorisé pour la source, racine du site, chemin listé dans
    `forbidden_paths` (pages de liste/recherche), `javascript:`/`mailto:`.
    """
    if not url or not url.strip():
        raise NormalizationError("URL d'annonce manquante")
    raw = url.strip()
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise NormalizationError(f"URL non http(s) ou relative : {raw[:120]}")
    if not host_allowed(raw, allowed_hosts):
        raise NormalizationError(f"hôte non autorisé pour cette source : {parts.hostname}")
    cleaned = clean_url(raw)
    path = urlsplit(cleaned).path
    if path in {"", "/"}:
        raise NormalizationError("l'URL pointe vers la page d'accueil, pas vers une annonce")
    bare = path.rstrip("/")
    if forbidden_paths and any(bare == p.rstrip("/") for p in forbidden_paths):
        raise NormalizationError(f"l'URL pointe vers une page de liste/recherche : {path}")
    if len(cleaned) > 1024:
        raise NormalizationError("URL trop longue")
    return cleaned
