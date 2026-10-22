"""Normalisation et validation des URLs d'annonces."""

import pytest

from jobradar.core.errors import NormalizationError
from jobradar.services.urls import clean_url, host_allowed, url_key, validate_job_url


def test_clean_url_removes_tracking_and_fragment_but_keeps_identifiers():
    url = "HTTPS://WWW.Example.com/jobs/view?id=42&utm_source=news&fbclid=abc&jobId=7#apply"
    assert clean_url(url) == "https://www.example.com/jobs/view?id=42&jobId=7"


def test_clean_url_keeps_path_case_and_non_default_port():
    assert clean_url("http://example.com:8080/Jobs/ABC") == "http://example.com:8080/Jobs/ABC"
    assert clean_url("https://example.com:443/x") == "https://example.com/x"


def test_clean_url_percent_encoding_is_canonical_and_idempotent():
    a = clean_url("https://senjob.com/sn/jobseekers/développeur_e_1.html")
    b = clean_url("https://senjob.com/sn/jobseekers/d%C3%A9veloppeur_e_1.html")
    assert a == b == clean_url(a)


def test_url_key_ignores_scheme_www_trailing_slash_and_param_order():
    assert url_key("http://www.site.com/a/b/?b=2&a=1") == url_key("https://site.com/a/b?a=1&b=2#x")


def test_url_key_keeps_distinct_ads_distinct():
    # deux annonces différentes ne doivent JAMAIS se confondre
    assert url_key("https://site.com/jobs?id=1") != url_key("https://site.com/jobs?id=2")
    assert url_key("https://site.com/jobs/1") != url_key("https://site.com/jobs/2")


def test_url_key_tracking_only_difference_is_same_page():
    assert url_key("https://site.com/jobs/1?utm_campaign=x") == url_key("https://site.com/jobs/1")


def test_host_allowed_matches_www_variants_only():
    assert host_allowed("https://www.emploidakar.com/x", {"emploidakar.com"})
    assert not host_allowed("https://evil.com/emploidakar.com", {"emploidakar.com"})
    assert not host_allowed("https://emploidakar.com.evil.com/x", {"emploidakar.com"})


@pytest.mark.parametrize(
    "url,reason",
    [
        (None, "manquante"),
        ("", "manquante"),
        ("javascript:alert(1)", "non http"),
        ("/relative/path", "non http"),
        ("ftp://example.com/x", "non http"),
        ("https://other.com/jobs/1", "non autorisé"),
        ("https://example.com/", "accueil"),
        ("https://example.com", "accueil"),
        ("https://example.com/offres", "liste"),
    ],
)
def test_validate_job_url_rejects_non_deep_links(url, reason):
    with pytest.raises(NormalizationError) as exc:
        validate_job_url(url, allowed_hosts={"example.com"}, forbidden_paths={"/offres"})
    assert reason in str(exc.value)


def test_validate_job_url_accepts_and_cleans_deep_link():
    out = validate_job_url("https://www.example.com/offres/dev-1?utm_source=x", allowed_hosts={"example.com"}, forbidden_paths={"/offres"})
    assert out == "https://www.example.com/offres/dev-1"
