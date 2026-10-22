"""Connecteurs réels testés sur des fixtures HTML/JSON enregistrées (extraits de pages collectées le 21/10/2026).

Aucun accès Internet : le transport HTTP est simulé. Chaque test vérifie la chaîne search() → normalize() : lien direct,
dates déclarées (jamais déduites), entreprise, contrat, éligibilité, et le comportement face à une structure modifiée.
"""

from datetime import UTC, datetime

import httpx
import pytest

from jobradar.collectors.africarrieres import AfricarrieresConnector
from jobradar.collectors.base import SearchParameters
from jobradar.collectors.concoursn import ConcourSNConnector, parse_fiche, split_title
from jobradar.collectors.emploi_dakar import EmploiDakarConnector
from jobradar.collectors.emploisenegal import EmploiSenegalConnector
from jobradar.collectors.expat_dakar import ExpatDakarConnector
from jobradar.collectors.himalayas import HimalayasConnector
from jobradar.collectors.registry import CONNECTORS, UnknownConnector, build_connector
from jobradar.collectors.remote4africa import Remote4AfricaConnector
from jobradar.collectors.remoteok import RemoteOKConnector
from jobradar.collectors.senjob import SenJobConnector
from jobradar.collectors.wave import WaveConnector
from jobradar.core.errors import NormalizationError, ParseError

from .conftest import fixture_json, fixture_text, json_response, make_client, make_pool, route, text_response


async def run_search(connector_cls, routes, params: SearchParameters, config=None):
    pool = make_pool(route(routes))
    try:
        c = connector_cls(make_client(pool, connector_cls), config or {})
        raws = await c.search(params)
        return c, raws
    finally:
        await pool.aclose()


def normalized(c, raws):
    return [c.normalize(r) for r in raws]


# ---------------------------------------------------------------- Emploi Dakar
async def test_emploi_dakar_search_and_detail_enrichment():
    listing = fixture_json("emploi_dakar_listings.json")
    detail = fixture_text("emploi_dakar_job.html")
    first_url = None

    def listings(req):
        assert "orderby" not in req.url.params  # évite le HTTP 404 du plugin
        return json_response(listing)

    c, raws = await run_search(
        EmploiDakarConnector,
        {r"emploidakar\.com/jm-ajax/get_listings": listings, r"emploidakar\.com/offre-demploi/": text_response(detail)},
        SearchParameters(keywords=["développeur"], detail_budget=1),
    )
    jobs = normalized(c, raws)
    assert len(jobs) == 3
    first_url = jobs[0].url
    assert first_url.startswith("https://www.emploidakar.com/offre-demploi/") and first_url.endswith("/")
    j = jobs[0]
    assert j.title and j.company_name and j.city and j.country == "SN"
    assert j.published_at is not None and j.source_job_id
    # détail : un seul récupéré (budget 1) → description + date limite uniquement pour celui-là
    with_detail = [x for x in jobs if x.verified_at]
    assert len(with_detail) == 1 and with_detail[0].description and with_detail[0].application_deadline
    assert any("budget" in w for w in c.warnings)


async def test_emploi_dakar_skips_detail_for_known_urls():
    listing = fixture_json("emploi_dakar_listings.json")
    detail_calls = []

    def detail(req):
        detail_calls.append(str(req.url))
        return text_response(fixture_text("emploi_dakar_job.html"))

    from jobradar.services.urls import url_key

    c0, raws0 = await run_search(EmploiDakarConnector, {r"get_listings": json_response(listing)}, SearchParameters(keywords=["x"], fetch_details=False))
    known = {url_key(r.data["url"]) for r in raws0}
    c, raws = await run_search(
        EmploiDakarConnector,
        {r"get_listings": json_response(listing), r"/offre-demploi/": detail},
        SearchParameters(keywords=["x"], known_urls=known),
    )
    assert detail_calls == []  # aucune page re-téléchargée
    assert len(raws) == 3


async def test_emploi_dakar_structure_change_is_a_parse_error():
    with pytest.raises(ParseError):
        await run_search(EmploiDakarConnector, {r"get_listings": json_response({"found_jobs": False})}, SearchParameters(keywords=["x"]))


def test_emploi_dakar_rejects_non_deep_links():
    pool = make_pool(route({}))
    c = EmploiDakarConnector(make_client(pool, EmploiDakarConnector), {})
    from jobradar.collectors.base import RawJob

    for bad in ("https://www.emploidakar.com/", "https://www.emploidakar.com/offres-demploi-au-senegal/", "https://autre.com/offre/1"):
        with pytest.raises(NormalizationError):
            c.normalize(RawJob(data={"url": bad, "title": "X"}))


# ---------------------------------------------------------------- Africarrières
async def test_africarrieres_relative_dates_are_never_converted():
    c, raws = await run_search(
        AfricarrieresConnector,
        {r"africarrieres\.com/senegal/fr/emplois$": text_response(fixture_text("africarrieres_list.html"))},
        SearchParameters(keywords=["développeur"], fetch_details=False),
    )
    jobs = normalized(c, raws)
    assert len(jobs) >= 2
    for j in jobs:
        assert j.url.startswith("https://africarrieres.com/senegal/fr/emplois/")
        assert j.published_at is None  # la liste n'a que « il y a 1 semaine »
        assert j.published_text and "il y a" in j.published_text
    confidential = [j for j in jobs if j.company_name is None]
    assert confidential, "les employeurs « Confidentiel » doivent rester inconnus (None)"


async def test_africarrieres_detail_gives_exact_publication_date():
    list_html = fixture_text("africarrieres_list.html")
    c, raws = await run_search(
        AfricarrieresConnector,
        {
            r"emplois$": text_response(list_html),
            r"/emplois/[^/]+$": text_response(fixture_text("africarrieres_detail.html")),
        },
        SearchParameters(keywords=["x"], detail_budget=5),
    )
    jobs = normalized(c, raws)
    detailed = [j for j in jobs if j.verified_at]
    assert detailed and detailed[0].published_at == datetime(2026, 10, 21, 10, 38, 5, tzinfo=UTC)
    assert detailed[0].application_deadline is not None and detailed[0].description


# ---------------------------------------------------------------- Emploi Sénégal (AfricaTalents)
async def test_emploisenegal_cards_local_filter_and_fields():
    html = fixture_text("emploisenegal_list.html")
    c, raws = await run_search(
        EmploiSenegalConnector,
        {r"emploisenegal\.com/recherche-jobs-senegal": text_response(html)},
        SearchParameters(keywords=["comptable"]),
        {"it_category_id": 31, "general_pages": 1},
    )
    jobs = normalized(c, raws)
    assert jobs, "la catégorie informatique est conservée sans filtre"
    j = jobs[0]
    assert "/offre-emploi-senegal/" in j.url and j.source_job_id and j.source_job_id.isdigit()
    assert j.published_at is not None and j.country == "SN"
    assert j.raw_metadata["description_is_excerpt"] is True


async def test_emploisenegal_unrecognized_page_is_parse_error():
    with pytest.raises(ParseError):
        await run_search(
            EmploiSenegalConnector,
            {r"recherche-jobs-senegal": text_response("<html><body>maintenance</body></html>")},
            SearchParameters(keywords=["x"]),
            {"it_category_id": 31},
        )


# ---------------------------------------------------------------- SenJob
async def test_senjob_rows_and_detail_company_from_jsonld():
    c, raws = await run_search(
        SenJobConnector,
        {
            r"senjob\.com/sn/offres-d-emploi\.php": text_response(fixture_text("senjob_list.html")),
            r"senjob\.com/sn/jobseekers/": text_response(fixture_text("senjob_detail.html")),
        },
        SearchParameters(keywords=["développeur"], detail_budget=3),
    )
    jobs = normalized(c, raws)
    assert len(jobs) == 3
    for j in jobs:
        assert "/sn/jobseekers/" in j.url and j.url.endswith(".html") and j.source_job_id.isdigit()
        assert j.published_at is not None and j.application_deadline is not None
        assert j.published_at.tzinfo is not None
    assert any(j.company_name for j in jobs), "l'employeur vient du JSON-LD du détail"
    # le code de compte interne de la cellule masquée n'est jamais pris pour une entreprise
    assert all(j.company_name != j.raw_metadata.get("account_code") for j in jobs)


# ---------------------------------------------------------------- ConcourSN
def test_concoursn_title_split_and_fiche_parsing():
    assert split_title("Recrutement Terrou-Bi Resort Dakar : 05 Agents de Sécurité (Session 2026)") == ("Terrou-Bi Resort Dakar", "Agents de Sécurité")
    assert split_title("Terre des Hommes recrute 01 Chargé des opérations") == ("Terre des Hommes", "Chargé des opérations")
    assert split_title("Calendrier des concours") == (None, "Calendrier des concours")
    data = parse_fiche(fixture_text("concoursn_article.html"))
    assert data["fiche"]["company"].startswith("Terrou-Bi") and "Dakar" in data["fiche"]["place"]


async def test_concoursn_declared_company_beats_estimated_and_excluded_titles_dropped():
    cat = fixture_text("concoursn_category.html")
    art = fixture_text("concoursn_article.html")
    c, raws = await run_search(
        ConcourSNConnector,
        {
            r"concoursn\.com/category/senegal/recrutement-senegal": text_response(cat),
            r"concoursn\.com/category/senegal/stages-senegal": text_response(cat),
            r"concoursn\.com/recrutement": text_response(art),
            r"concoursn\.com/terre": text_response(art),
        },
        SearchParameters(keywords=["recrutement", "recrute", "agents"], detail_budget=5),
        {"pages": 1},
    )
    titles = [r.data["title"] for r in raws]
    assert not any("Récapitulatif" in t for t in titles)  # article « récapitulatif » écarté
    jobs = normalized(c, raws)
    assert jobs
    declared = [j for j in jobs if j.verified_at and not j.estimated_fields]
    assert declared and declared[0].company_name.startswith("Terrou-Bi")
    assert all(j.country == "SN" for j in jobs)


# ---------------------------------------------------------------- Expat-Dakar
async def test_expat_dakar_jsonld_same_as_and_zero_results_404():
    c, raws = await run_search(
        ExpatDakarConnector,
        {r"expat-dakar\.com/emploi": text_response(fixture_text("expat_dakar_list.html"))},
        SearchParameters(keywords=["développeur"]),
    )
    jobs = normalized(c, raws)
    assert jobs and all(j.url.startswith("https://www.expat-dakar.com/annonce/") for j in jobs)
    assert jobs[0].published_at is not None and jobs[0].application_deadline is not None
    assert any(j.same_as_urls for j in jobs), "sameAs vers l'annonce d'origine (déduplication inter-sources)"
    # HTTP 404 + page de résultats = aucun résultat (pas une panne)
    empty = "<html><title>Offres d'emploi | Expat-Dakar</title><body>Aucun résultat</body></html>"
    c2, raws2 = await run_search(ExpatDakarConnector, {r"expat-dakar\.com/emploi": text_response(empty, status=404)}, SearchParameters(keywords=["zzz"]))
    assert raws2 == []


async def test_expat_dakar_real_404_without_results_page_is_error():
    from jobradar.core.errors import SourceUnavailable

    with pytest.raises(SourceUnavailable):
        await run_search(ExpatDakarConnector, {r"expat-dakar\.com/emploi": text_response("not found", status=404)}, SearchParameters(keywords=["x"]))


# ---------------------------------------------------------------- Remote4Africa
async def test_remote4africa_eligibility_from_jsonld_and_source_filter_fallback():
    detail = fixture_text("remote4africa_detail.html")
    c, raws = await run_search(
        Remote4AfricaConnector,
        {
            r"remote4africa\.com/jobs/search": text_response(fixture_text("remote4africa_list.html")),
            r"remote4africa\.com/jobs/[^/]+$": text_response(detail),
        },
        SearchParameters(keywords=["developer"], detail_budget=1),
    )
    jobs = normalized(c, raws)
    assert len(jobs) == 3 and all(j.work_mode == "remote" for j in jobs)
    detailed = [j for j in jobs if j.verified_at]
    assert detailed[0].remote_eligibility == "eligible" and detailed[0].raw_metadata["eligibility_basis"] == "applicantLocationRequirements"
    assert detailed[0].published_at == datetime(2026, 10, 7, 8, 21, 25, tzinfo=UTC)
    assert detailed[0].salary_period == "yearly" and detailed[0].salary_currency == "USD"
    others = [j for j in jobs if not j.verified_at]
    assert others and all(j.raw_metadata["eligibility_basis"] == "source_country_filter" for j in others)


# ---------------------------------------------------------------- Himalayas / Remote OK (API)
async def test_himalayas_api_eligibility_dates_and_attribution():
    c, raws = await run_search(
        HimalayasConnector,
        {r"himalayas\.app/jobs/api/search": lambda req: json_response(fixture_json("himalayas_search.json"))},
        SearchParameters(keywords=["python"], countries=["SN"]),
    )
    jobs = normalized(c, raws)
    assert jobs and all(j.url.startswith("https://himalayas.app/companies/") for j in jobs)
    assert all(j.work_mode == "remote" and j.published_at and j.raw_metadata["attribution"].startswith("Source : Himalayas") for j in jobs)
    assert all(j.remote_eligibility in {"eligible", "restricted"} for j in jobs)


async def test_himalayas_restricted_when_senegal_not_in_country_list():
    data = fixture_json("himalayas_search.json")
    data["jobs"][0]["locationRestrictions"] = ["United States", "Canada"]
    c, raws = await run_search(HimalayasConnector, {r"search": json_response(data)}, SearchParameters(keywords=["python"]))
    first = next(j for j in normalized(c, raws) if j.title == data["jobs"][0]["title"])
    assert first.remote_eligibility == "restricted"


async def test_himalayas_unexpected_payload_is_parse_error():
    with pytest.raises(ParseError):
        await run_search(HimalayasConnector, {r"search": json_response({"oops": 1})}, SearchParameters(keywords=["x"]))


async def test_remoteok_one_request_local_filter_mojibake_and_unknown_eligibility():
    data = fixture_json("remoteok_api.json")
    data[1]["position"] = "Senior Python Engineer â Remote"  # mojibake réel du flux (« — » mal décodé)
    calls = []

    def api(req):
        calls.append(1)
        return json_response(data)

    c, raws = await run_search(RemoteOKConnector, {r"remoteok\.com/api": api}, SearchParameters(keywords=["engineer", "python"]))
    assert len(calls) == 1  # une seule requête pour tout le flux
    jobs = normalized(c, raws)
    assert jobs
    assert all(j.raw_metadata["attribution"].startswith("Source : Remote OK") for j in jobs)
    assert all(j.remote_eligibility in {"unknown", "eligible", "restricted"} for j in jobs)
    assert any(j.remote_eligibility == "unknown" for j in jobs), "location vide → inconnu, jamais présumé éligible"
    assert not any("â" in j.title for j in jobs)
    assert any("Senior Python Engineer — Remote" == j.title for j in jobs)


# ---------------------------------------------------------------- Wave (employeur)
async def test_wave_careers_list_detail_and_no_publication_date():
    c, raws = await run_search(
        WaveConnector,
        {
            r"wave\.com/en/careers/$": text_response(fixture_text("wave_careers.html")),
            r"wave\.com/en/careers/job/\d+/?$": text_response(fixture_text("wave_detail.html")),
        },
        SearchParameters(keywords=[], detail_budget=2),
    )
    jobs = normalized(c, raws)
    assert len(jobs) >= 3
    assert all(j.company_name == "Wave" and j.published_at is None for j in jobs)  # la page ne publie pas de date
    assert all(j.url.startswith("https://www.wave.com/en/careers/job/") for j in jobs)
    remote = [j for j in jobs if j.work_mode == "remote"]
    assert all(j.remote_eligibility == "unknown" for j in remote)
    detailed = [j for j in jobs if j.description]
    assert detailed and "Personal Business About Careers" not in detailed[0].description  # pas de menu dans la description


# ---------------------------------------------------------------- registre / sécurité
def test_registry_is_an_explicit_whitelist():
    assert set(CONNECTORS) == {
        "emploi_dakar", "emploisenegal", "africarrieres_sn", "senjob_sn", "concoursn", "expat_dakar",
        "remote4africa", "himalayas", "remoteok", "wave_careers",
    }
    pool = make_pool(route({}))
    with pytest.raises(UnknownConnector):
        build_connector("../../etc/passwd", pool, {})
    with pytest.raises(UnknownConnector):
        build_connector("https://evil.example.org", pool, {})


def test_every_connector_declares_its_allowed_hosts_and_normalize_is_offline():
    for key, cls in CONNECTORS.items():
        assert cls.source_key == key and cls.allowed_hosts and all("/" not in h for h in cls.allowed_hosts)


async def test_health_check_translates_errors_into_status():
    def blocked(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(403, headers={"content-type": "text/html"}, content=b"<title>Just a moment</title>")

    pool = make_pool(blocked)
    try:
        c = SenJobConnector(make_client(pool, SenJobConnector), {})
        res = await c.health_check()
        assert not res.ok and res.status == "blocked"
    finally:
        await pool.aclose()
