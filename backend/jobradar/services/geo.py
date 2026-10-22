"""Géographie minimale : pays (fr/en → ISO2) et villes d'Afrique de l'Ouest utiles au MVP.

Volontairement modeste et extensible : ajouter un pays = ajouter une ligne ici (voir docs/architecture.md).
"""

from __future__ import annotations

import re

from .text import normalize_text

# nom normalisé → ISO 3166-1 alpha-2
COUNTRY_BY_NAME: dict[str, str] = {
    "senegal": "SN", "cote d ivoire": "CI", "ivory coast": "CI", "mali": "ML", "burkina faso": "BF",
    "burkina": "BF", "guinee": "GN", "guinea": "GN", "guinee bissau": "GW", "guinea bissau": "GW",
    "mauritanie": "MR", "mauritania": "MR", "ghana": "GH", "nigeria": "NG", "nigeria ": "NG",
    "liberia": "LR", "sierra leone": "SL", "gambie": "GM", "gambia": "GM", "the gambia": "GM",
    "cap vert": "CV", "cape verde": "CV", "benin": "BJ", "togo": "TG", "niger": "NE",
    "cameroun": "CM", "cameroon": "CM", "maroc": "MA", "morocco": "MA", "tunisie": "TN", "tunisia": "TN",
    "algerie": "DZ", "algeria": "DZ", "kenya": "KE", "south africa": "ZA", "afrique du sud": "ZA",
    "france": "FR", "egypt": "EG", "egypte": "EG", "rwanda": "RW", "ethiopia": "ET", "tanzania": "TZ",
    "uganda": "UG", "united states": "US", "usa": "US", "united kingdom": "GB", "uk": "GB",
    "canada": "CA", "germany": "DE", "allemagne": "DE",
}

COUNTRY_LABELS: dict[str, str] = {
    "SN": "Sénégal", "CI": "Côte d'Ivoire", "ML": "Mali", "BF": "Burkina Faso", "GN": "Guinée",
    "GW": "Guinée-Bissau", "MR": "Mauritanie", "GH": "Ghana", "NG": "Nigeria", "LR": "Liberia",
    "SL": "Sierra Leone", "GM": "Gambie", "CV": "Cap-Vert", "BJ": "Bénin", "TG": "Togo", "NE": "Niger",
    "CM": "Cameroun", "MA": "Maroc", "TN": "Tunisie", "DZ": "Algérie", "KE": "Kenya", "ZA": "Afrique du Sud",
    "FR": "France", "EG": "Égypte", "RW": "Rwanda", "ET": "Éthiopie", "TZ": "Tanzanie", "UG": "Ouganda",
    "US": "États-Unis", "GB": "Royaume-Uni", "CA": "Canada", "DE": "Allemagne",
}

# ville normalisée → (nom d'affichage, ISO2)
CITIES: dict[str, tuple[str, str]] = {}


def _add(country: str, *names: str) -> None:
    for n in names:
        CITIES[normalize_text(n)] = (n, country)


_add("SN", "Dakar", "Thiès", "Saint-Louis", "Ziguinchor", "Kaolack", "Mbour", "Diourbel", "Touba", "Louga",
     "Tambacounda", "Kolda", "Sédhiou", "Kédougou", "Matam", "Fatick", "Kaffrine", "Rufisque", "Pikine",
     "Guédiawaye", "Saly", "Diamniadio", "Sandiara", "Richard-Toll", "Mbacké", "Tivaouane", "Bargny",
     "Sébikotane", "Popenguine", "Joal-Fadiouth", "Kayar")
# quartiers/zones de Dakar → ville « Dakar »
DAKAR_AREAS = {normalize_text(n) for n in (
    "Almadies", "Plateau", "Ouakam", "Mermoz", "Sacré-Cœur", "Point E", "Fann", "Yoff", "Ngor", "Médina",
    "Liberté 6", "VDN", "Hann", "Parcelles Assainies", "Grand Yoff", "Sicap", "Mamelles", "Bel-Air",
    "Hlm", "Colobane", "Cité Keur Gorgui", "Keur Gorgui", "Zone B", "Mariste", "Patte d'Oie",
)}
_add("CI", "Abidjan", "Yamoussoukro", "Bouaké", "San-Pédro", "Daloa", "Korhogo")
_add("ML", "Bamako", "Sikasso", "Ségou", "Kayes", "Mopti")
_add("BF", "Ouagadougou", "Bobo-Dioulasso")
_add("GN", "Conakry", "Kankan")
_add("MR", "Nouakchott", "Nouadhibou")
_add("GH", "Accra", "Kumasi", "Tamale", "Takoradi")
_add("NG", "Lagos", "Abuja", "Port Harcourt", "Ibadan", "Kano")
_add("LR", "Monrovia")
_add("SL", "Freetown")
_add("GM", "Banjul", "Serrekunda")
_add("CV", "Praia", "Mindelo")
_add("BJ", "Cotonou", "Porto-Novo")
_add("TG", "Lomé")
_add("NE", "Niamey")
_add("CM", "Douala", "Yaoundé")
_add("MA", "Casablanca", "Rabat")
_add("KE", "Nairobi")
_add("ZA", "Johannesburg", "Cape Town", "Pretoria")
_add("FR", "Paris", "Lyon", "Marseille")

LOCATION_WORDS: set[str] = set(CITIES) | DAKAR_AREAS | set(COUNTRY_BY_NAME)


def country_from_name(name: str | None) -> str | None:
    if not name:
        return None
    n = normalize_text(name)
    if len(n) == 2 and n.upper() in COUNTRY_LABELS:
        return n.upper()
    return COUNTRY_BY_NAME.get(n)


def parse_location(text: str | None) -> tuple[str | None, str | None]:
    """Extrait (ville, pays ISO2) d'un libellé de lieu. Ne devine rien : None si non reconnu.

    Un quartier connu de Dakar (Almadies, Plateau...) donne la ville « Dakar ». Un pays n'est déduit que
    d'un nom de pays explicite ou d'une ville du gazetteer.
    """
    if not text:
        return None, None
    norm = normalize_text(text)
    if not norm:
        return None, None
    country: str | None = None
    for name in sorted(COUNTRY_BY_NAME, key=len, reverse=True):
        if name and re.search(rf"(?:^| ){re.escape(name)}(?: |$)", norm):
            country = COUNTRY_BY_NAME[name]
            break
    city: str | None = None
    for key in sorted(CITIES, key=len, reverse=True):
        if re.search(rf"(?:^| ){re.escape(key)}(?: |$)", norm):
            display, c_country = CITIES[key]
            city = display
            country = country or c_country
            break
    if city is None and any(re.search(rf"(?:^| ){re.escape(a)}(?: |$)", norm) for a in DAKAR_AREAS):
        city, country = "Dakar", country or "SN"
    return city, country
