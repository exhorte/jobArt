"""Score de pertinence : fonction pure, règles explicites, aucun champ absent n'est un point positif."""

from jobradar.services.scoring import (
    DEFAULT_WEIGHTS,
    ProfileCriteria,
    ScorableOffer,
    canon_tokens,
    score_offer,
)


def profile(**kw) -> ProfileCriteria:
    base = dict(
        id=1, name="P", countries=["SN"], cities=["Dakar", "Thiès"], positive_keywords=["Software Engineer", "Développeur web"],
        target_roles=["Full Stack Developer"], keyword_groups={"Langages": ["Python", "TypeScript"], "Outils": ["Docker", "FastAPI"]},
        sectors=[], contract_types=["cdi", "cdd"], work_modes=["onsite", "hybrid", "remote"], experience_levels=["junior", "mid"],
    )
    base.update(kw)
    return ProfileCriteria(**base)


def offer(**kw) -> ScorableOffer:
    base = dict(title="Software Engineer", company_name="Acme", description="Python TypeScript Docker FastAPI " * 5,
                country="SN", city="Dakar", work_mode="onsite", contract_type="cdi", experience_level="mid")
    base.update(kw)
    return ScorableOffer(**base)


def test_default_weights_match_specification():
    assert DEFAULT_WEIGHTS == {"role": 30, "skills": 25, "location": 15, "experience": 10, "sector": 10, "contract_work_mode": 10}


def test_perfect_match_scores_100_and_is_explained():
    r = score_offer(offer(), profile())
    assert r.score == 100.0
    assert r.breakdown["role"]["points"] == 30
    assert "Software Engineer" in r.explanation["matched_keywords"]
    assert r.explanation["missing"] == []
    assert any("probabilité d'embauche" in n for n in r.explanation["notes"])


def test_score_is_deterministic_and_pure():
    p, o = profile(), offer()
    assert score_offer(o, p).score == score_offer(o, p).score
    assert o.title == "Software Engineer"  # l'offre n'est pas modifiée


def test_role_tiers_exact_phrase_tokens_description_only_and_none():
    p = profile(keyword_groups={})
    assert score_offer(offer(title="Senior Software Engineer"), p).breakdown["role"]["points"] == 30  # expression dans le titre
    assert score_offer(offer(title="Ingénieur logiciel"), p).breakdown["role"]["points"] == 25.5  # FR/EN équivalents (0,85)
    desc_only = score_offer(offer(title="Chef de projet", description="vous serez Software Engineer au quotidien"), p)
    assert desc_only.breakdown["role"]["points"] == 9.0 and "description seulement" in desc_only.breakdown["role"]["detail"]
    assert score_offer(offer(title="Comptable", description="gestion"), p).breakdown["role"]["points"] == 0


def test_french_english_synonyms_are_canonicalised():
    assert set(canon_tokens("Développeur logiciel")) == set(canon_tokens("Software Developer"))
    assert set(canon_tokens("Full-Stack Developer")) == {"fullstack", "dev"}
    assert "ai" in canon_tokens("Ingénieur intelligence artificielle")


def test_skills_component_counts_matches_and_flags_missing_description():
    p = profile(positive_keywords=[], target_roles=[])
    full = score_offer(offer(description="Python TypeScript Docker FastAPI"), p)
    assert full.breakdown["skills"]["points"] == 25  # 4 compétences trouvées sur un objectif de 4
    none = score_offer(offer(description=None), p)
    assert none.breakdown["skills"]["points"] == 0
    assert any("description" in m for m in none.explanation["missing"])  # signalé, pas un point positif


def test_missing_fields_are_never_positive_matches():
    r = score_offer(offer(city=None, country=None, work_mode=None, contract_type=None, experience_level=None), profile())
    assert r.breakdown["location"]["points"] == 0
    assert r.breakdown["experience"]["points"] == 0
    assert r.breakdown["contract_work_mode"]["points"] == 0
    missing = " ".join(r.explanation["missing"])
    for needle in ("localisation", "niveau d'expérience", "type de contrat", "mode de travail"):
        assert needle in missing


def test_salary_absence_is_not_a_criterion_and_costs_nothing():
    base = score_offer(offer(), profile()).score
    # aucune donnée de salaire dans ScorableOffer : l'absence ne peut pénaliser
    assert not hasattr(offer(), "salary_min")
    assert base == 100.0


def test_location_priority_city_other_city_country_and_foreign():
    p = profile()
    assert score_offer(offer(city="Dakar"), p).breakdown["location"]["points"] == 15
    assert score_offer(offer(city="Thiès"), p).breakdown["location"]["points"] == 13.5
    assert score_offer(offer(city="Kaolack"), p).breakdown["location"]["points"] == 9  # pays du profil, autre ville
    assert score_offer(offer(city="Abidjan", country="CI"), p).breakdown["location"]["points"] == 0


def test_remote_eligibility_eligible_restricted_unknown():
    p = profile()
    eligible = score_offer(offer(work_mode="remote", country=None, city=None, remote_eligibility="eligible"), p)
    restricted = score_offer(offer(work_mode="remote", country=None, city=None, remote_eligibility="restricted", remote_regions=["United States"]), p)
    unknown = score_offer(offer(work_mode="remote", country=None, city=None, remote_eligibility="unknown"), p)
    assert eligible.breakdown["location"]["points"] == 15
    assert restricted.breakdown["location"]["points"] == 0
    assert any("restrictions géographiques" in r for r in restricted.explanation["restrictions"])
    assert unknown.breakdown["location"]["points"] == 0
    assert any("éligibilité" in m for m in unknown.explanation["missing"])


def test_remote_not_wanted_by_profile_scores_zero_location():
    p = profile(work_modes=["onsite"])
    assert score_offer(offer(work_mode="remote", remote_eligibility="eligible"), p).breakdown["location"]["points"] == 0


def test_experience_exact_adjacent_far():
    p = profile(experience_levels=["junior", "mid"])
    assert score_offer(offer(experience_level="mid"), p).breakdown["experience"]["points"] == 10
    assert score_offer(offer(experience_level="senior"), p).breakdown["experience"]["points"] == 5  # voisin
    assert score_offer(offer(experience_level="lead"), p).breakdown["experience"]["points"] == 0


def test_sector_component_only_when_profile_defines_sectors():
    o = offer(company_name="Wave", description="paiement mobile money " * 5)
    without = score_offer(o, profile(sectors=[]))
    assert not without.breakdown["sector"]["applicable"]
    with_sector = score_offer(o, profile(sectors=["Fintech", "Banque"]))
    assert with_sector.breakdown["sector"]["points"] == 10 and with_sector.explanation["sector"] == ["Fintech"]
    other = score_offer(offer(company_name="Boulangerie", description="pain " * 20), profile(sectors=["Fintech"]))
    assert other.breakdown["sector"]["points"] == 0 and "secteur" in " ".join(other.explanation["missing"])


def test_excluded_keywords_title_zeroes_score_and_description_penalises():
    p = profile(excluded_keywords=["stage", "commercial"])
    assert score_offer(offer(title="Software Engineer - Stage"), p).score == 0.0
    base = score_offer(offer(), p).score
    penalised = score_offer(offer(description="Python TypeScript Docker FastAPI commercial " * 5), p)
    assert penalised.score == base - 20
    assert "commercial" in penalised.explanation["excluded"]


def test_weights_are_configurable_and_zero_disables_a_criterion():
    o = offer(city="Kaolack", experience_level="lead")  # location 0,6 ; experience 0
    default = score_offer(o, profile()).score
    heavier_location = score_offer(o, profile(weights={"location": 60})).score
    no_experience = score_offer(o, profile(weights={"experience": 0})).score
    assert heavier_location != default
    assert no_experience > default  # un critère raté désactivé ne tire plus le score vers le bas
    assert not score_offer(o, profile(weights={"experience": 0})).breakdown["experience"]["applicable"]


def test_score_never_leaves_0_100():
    r = score_offer(offer(title="", description=None, country=None, city=None), profile(positive_keywords=[], target_roles=[], keyword_groups={}))
    assert 0 <= r.score <= 100
