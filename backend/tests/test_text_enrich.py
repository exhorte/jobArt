"""Normalisation de texte, géographie, détection contrat / mode / expérience / secteur / éligibilité."""

import pytest

from jobart.services.enrich import (
    classify_remote_eligibility,
    detect_contract,
    detect_experience_level,
    detect_sectors,
    detect_work_mode,
    map_schema_employment_type,
)
from jobart.services.geo import parse_location
from jobart.services.text import (
    fix_mojibake,
    html_to_text,
    jaccard,
    keyword_hits,
    normalize_company,
    normalize_text,
    normalize_title,
    token_set,
)


def test_normalize_text_strips_accents_case_and_punctuation():
    assert normalize_text("  Développeur  Full-Stack (H/F) !") == "developpeur full stack h f"
    assert normalize_text(None) == ""


def test_normalize_title_removes_gender_markers_refs_and_location_suffix():
    from jobart.services.geo import LOCATION_WORDS

    assert normalize_title("Développeur(euse) Python (H/F) - Dakar", location_words=LOCATION_WORDS) == "developpeur python"
    assert normalize_title("Ingénieur Données F/H Réf: ABC-123") == "ingenieur donnees"
    # un suffixe qui n'est pas un lieu est conservé
    assert normalize_title("Chef de projet - Digital", location_words=LOCATION_WORDS) == "chef de projet digital"


def test_normalize_company_strips_legal_forms_and_country_suffix():
    assert normalize_company("ALTEN Sénégal") == normalize_company("Alten SENEGAL") == "alten"
    assert normalize_company("Acme SARL") == "acme"
    assert normalize_company("Confidentiel") is None
    assert normalize_company(None) is None
    assert normalize_company("Sonatel Group") == "sonatel"


def test_html_to_text_removes_scripts_and_keeps_text_untrusted():
    html = "<p>Bonjour</p><script>alert('x')</script><ul><li>Python</li><li>SQL</li></ul>"
    text = html_to_text(html)
    assert "alert" not in text
    assert text.splitlines() == ["Bonjour", "Python", "SQL"]


def test_keyword_hits_whole_words_phrases_and_plural():
    assert keyword_hits("Nous recrutons des Développeurs Python", ["développeur", "java"]) == ["développeur"]
    assert keyword_hits("Full Stack Developer senior", ["Developer Full Stack"]) == ["Developer Full Stack"]
    assert keyword_hits("Javascript expert", ["java"]) == []  # pas de correspondance partielle de mot
    assert keyword_hits(None, ["x"]) == []


def test_jaccard_and_tokens():
    a, b = token_set("python fastapi docker"), token_set("python django docker")
    assert jaccard(a, b) == pytest.approx(0.5)
    assert jaccard(set(), a) == 0.0


def test_fix_mojibake_repairs_and_leaves_clean_text():
    assert fix_mojibake("Ciudad de MÃ©xico") == "Ciudad de México"
    assert fix_mojibake("Sénégal") == "Sénégal"
    assert fix_mojibake(None) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("CDI & CDD", "cdi"),  # priorité au premier motif reconnu
        ("Stage de fin d'études", "stage"),
        ("Contrat à durée déterminée", "cdd"),
        ("Prestation de services", "freelance"),
        ("Full time", "full_time"),
        ("Intérim", "interim"),
        ("Poste passionnant", None),
    ],
)
def test_detect_contract(text, expected):
    assert detect_contract(text) == expected


def test_map_schema_employment_type():
    assert map_schema_employment_type(["FULL_TIME"]) == "full_time"
    assert map_schema_employment_type("INTERN") == "stage"
    assert map_schema_employment_type("CONTRACTOR") == "contract"
    assert map_schema_employment_type(None) is None


def test_work_mode_is_conservative_in_descriptions():
    # simple mention de télétravail possible : hybride, jamais « remote » par défaut
    assert detect_work_mode("Dev", "Dakar", "possibilité de télétravail 2j/semaine") == "hybrid"
    assert detect_work_mode("Dev", "Dakar", "Poste 100% remote") == "remote"
    assert detect_work_mode("Développeur (remote)", "Dakar", None) == "remote"
    assert detect_work_mode("Dev", "Dakar", "Une ESN renforce ses équipes à distance") is None
    assert detect_work_mode("Dev", None, "travail en présentiel à Dakar") == "onsite"


def test_experience_level_from_title_years_and_none():
    assert detect_experience_level("Développeur Senior") == "senior"
    assert detect_experience_level("Stagiaire développeur") == "intern"
    assert detect_experience_level("Dev", "Expérience entre 2 ans et 5 ans") == "mid"
    assert detect_experience_level("Dev", "au moins 8 ans d'expérience") == "senior"
    assert detect_experience_level("Dev", "1 an d'expérience") == "junior"
    assert detect_experience_level("Développeur", "Rejoignez-nous") is None


def test_detect_sectors():
    assert "fintech" in detect_sectors("Wave", "Data Scientist")
    assert "esn" in detect_sectors("ALTEN Sénégal", "Développeur")
    assert detect_sectors("Boulangerie du coin", "Boulanger") == []


@pytest.mark.parametrize(
    "restrictions,status",
    [
        (["Worldwide"], "eligible"),
        ("Anywhere in the world", "eligible"),
        (["Africa"], "eligible"),
        (["Senegal", "Ghana"], "eligible"),
        (["United States", "Canada"], "restricted"),
        ("US only", "restricted"),
        (["Europe"], "restricted"),
        (None, "unknown"),
        ([], "unknown"),
        ("Remote", "unknown"),
    ],
)
def test_classify_remote_eligibility(restrictions, status):
    assert classify_remote_eligibility(restrictions)[0] == status


def test_classify_remote_eligibility_unmarked_policy():
    assert classify_remote_eligibility("Vancouver", unmarked="unknown")[0] == "unknown"
    assert classify_remote_eligibility("Vancouver")[0] == "restricted"


def test_parse_location():
    assert parse_location("Dakar, Sénégal") == ("Dakar", "SN")
    assert parse_location("Almadies") == ("Dakar", "SN")  # quartier connu → ville
    assert parse_location("Abidjan, Côte d'Ivoire") == ("Abidjan", "CI")
    assert parse_location("Lieu mystérieux") == (None, None)  # ne devine rien
    assert parse_location(None) == (None, None)
