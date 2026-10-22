"""Analyse de dates déclarées par les sources (ISO 8601, formats français/anglais, RFC 2822, epoch).

Règles :
* Toujours renvoyer un datetime *aware* en UTC, ou None si la valeur n'est pas exploitable.
* Une heure sans fuseau est interprétée comme UTC (le Sénégal, la Côte d'Ivoire et le Ghana sont en UTC+0).
* Les dates relatives (« il y a 2 jours ») ne sont PAS converties : ce serait fabriquer une date de publication.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .text import normalize_text

_MONTHS = {
    "janvier": 1, "janv": 1, "jan": 1, "january": 1,
    "fevrier": 2, "fevr": 2, "fev": 2, "feb": 2, "february": 2,
    "mars": 3, "mar": 3, "march": 3,
    "avril": 4, "avr": 4, "apr": 4, "april": 4,
    "mai": 5, "may": 5,
    "juin": 6, "jun": 6, "june": 6,
    "juillet": 7, "juil": 7, "jul": 7, "july": 7,
    "aout": 8, "aug": 8, "august": 8,
    "septembre": 9, "sept": 9, "sep": 9, "september": 9,
    "octobre": 10, "oct": 10, "october": 10,
    "novembre": 11, "nov": 11, "november": 11,
    "decembre": 12, "dec": 12, "december": 12,
}

_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?)?$"
)
_RFC2822 = re.compile(r"^[A-Za-z]{3},\s+\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{2}:\d{2}")
_DMY_NUM = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")
_DMY_TXT = re.compile(r"(\d{1,2})(?:er)?\s+([a-z]+)\.?\s+(\d{4})")
_MDY_TXT = re.compile(r"([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})")


def _mk(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> datetime | None:
    try:
        return datetime(y, mo, d, h, mi, s, tzinfo=UTC)
    except ValueError:
        return None


def parse_datetime(value: str | int | float | None) -> datetime | None:
    """Parse une date « absolue » ; renvoie None pour tout ce qui est relatif, vide ou incohérent."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return from_epoch(value)
    text = str(value).strip()
    if not text:
        return None

    m = _ISO.match(text)
    if m:
        y, mo, d, h, mi, s, tz = m.groups()
        base = _mk(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0))
        if base is None:
            return None
        if tz and tz != "Z":
            sign = 1 if tz[0] == "+" else -1
            digits = tz[1:].replace(":", "")
            offset = timedelta(minutes=sign * (int(digits[:2]) * 60 + int(digits[2:4])))
            return base.replace(tzinfo=timezone(offset)).astimezone(UTC)
        return base

    m = _DMY_NUM.match(text)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        return _mk(y, mo, d)

    if _RFC2822.match(text):  # « Fri, 07 Oct 2022 13:33:20 GMT » : avant les formats de date « texte » (perdrait l'heure)
        try:
            dt = parsedate_to_datetime(text)
            return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        except (TypeError, ValueError, IndexError):
            pass

    norm = normalize_text(text)
    m = _DMY_TXT.search(norm)
    if m and m.group(2) in _MONTHS:
        return _mk(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
    m = _MDY_TXT.search(norm)
    if m and m.group(1) in _MONTHS:
        return _mk(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))

    try:  # RFC 2822 (flux RSS)
        dt = parsedate_to_datetime(text)
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError, IndexError):
        pass
    try:  # dernier recours : fromisoformat tolérant (3.11+)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def from_epoch(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    try:
        v = float(value)
        if v > 1e12:  # millisecondes
            v /= 1000.0
        if v <= 0:
            return None
        return datetime.fromtimestamp(v, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None


_RELATIVE = re.compile(r"\b(il y a|ago|aujourd|hier|yesterday|today|just now|a l instant)\b")


def is_relative_date(value: str | None) -> bool:
    """Vrai pour « il y a 2 heures », « Aujourd'hui, 13:17 »... (valeurs volontairement non converties)."""
    return bool(value and _RELATIVE.search(normalize_text(value)))
