import pytest
import asyncio
import math
from app.services import industry_service
from app.services import industry_roles
from app.services import retrieval_service
from app.services import skill_taxonomy as taxonomy
from app.services import skill_engine as engine
from app.services import analysis_run_service as ars


# ===========================================================================
# 1. CATALOG COVERAGE & METADATA TESTS (11 ROLES)
# ===========================================================================

EXPECTED_11_ROLES = [
    "Software Engineer",
    "Backend Developer",
    "Frontend Developer",
    "Full Stack Developer",
    "Data Analyst",
    "Data Scientist",
    "Machine Learning Engineer",
    "DevOps Engineer",
    "Cloud Engineer",
    "Cybersecurity Engineer",
    "Mobile Developer",
]


def test_catalog_contains_all_11_roles():
    """Verify all 11 target roles exist in the canonical ROLE_CATALOG."""
    catalog_keys = set(industry_roles.ROLE_CATALOG.keys())
    for role in EXPECTED_11_ROLES:
        assert role in catalog_keys, f"Role {role} missing from ROLE_CATALOG"


def test_list_catalog_roles_metadata():
    """Verify list_catalog_roles returns complete structured metadata."""
    roles = industry_roles.list_catalog_roles()
    assert len(roles) >= 11
    for r in roles:
        assert "title" in r and r["title"]
        assert "slug" in r and r["slug"]
        assert "category" in r and r["category"]
        assert "description" in r and r["description"]
        assert "aliases" in r and isinstance(r["aliases"], list)
        assert "source_benchmarks" in r and len(r["source_benchmarks"]) > 0


def test_industry_service_list_roles_includes_all_11():
    """Verify industry_service.list_roles() includes all 11 catalog roles."""
    roles = industry_service.list_roles()
    for role in EXPECTED_11_ROLES:
        assert role in roles, f"Role {role} not found in industry_service.list_roles()"


def test_all_11_roles_have_valid_requirements():
    """Verify each of the 11 roles has non-empty requirements in the prototype dataset."""
    for role in EXPECTED_11_ROLES:
        reqs = industry_service.list_by_role(role)
        assert len(reqs) >= 6, f"Role {role} has fewer than 6 requirements ({len(reqs)})"
        for r in reqs:
            assert r["role"] == role
            assert r["skill"]
            assert r["skill_category"]


# ===========================================================================
# 2. SEPARATE 5 INDUSTRY DIMENSIONS & SOURCE PROVENANCE TESTS
# ===========================================================================

def test_five_distinct_dimensions_preservation():
    """Verify all 5 dimensions exist, are bounded [0, 1], and are distinct."""
    reqs = industry_service.list_by_role("Software Engineer")
    assert len(reqs) > 0
    for r in reqs:
        req_level = r["required_level"]
        importance = r["importance"]
        demand = r["demand"]
        interview = r["interview_relevance"]
        conf = r["industry_confidence"]

        assert 0.0 <= req_level <= 1.0
        assert 0.0 <= importance <= 1.0
        assert 0.0 <= demand <= 1.0
        assert 0.0 <= interview <= 1.0
        assert 0.0 <= conf <= 1.0

    # Verify DSA in Software Engineer has specific distinct dimensions
    dsa = next((r for r in reqs if r["skill"] == "Data Structures & Algorithms"), None)
    assert dsa is not None
    assert dsa["required_level"] >= 0.80
    assert dsa["importance"] >= 0.90
    assert dsa["interview_relevance"] >= 0.90
    assert dsa["industry_confidence"] >= 0.90


def test_source_provenance_and_non_fabrication():
    """Verify requirements carry authentic source attribution, quality, and context."""
    reqs = industry_service.list_by_role("Backend Developer")
    assert len(reqs) > 0
    for r in reqs:
        assert r["source"] and len(r["source"]) > 5
        assert r["source_quality"] in [0.70, 0.80, 0.85, 0.88, 0.90]
        assert r["evidence_context"] and len(r["evidence_context"]) > 10
        assert r["published_at"]
        assert r["retrieved_at"]


# ===========================================================================
# 3. CANONICAL SKILL NORMALIZATION IN INDUSTRY REQUIREMENTS
# ===========================================================================

def test_all_requirements_use_canonical_taxonomy_skills():
    """Verify every requirement in the prototype catalog maps to a canonical skill in taxonomy."""
    all_reqs = industry_service.get_all(limit=500)
    assert len(all_reqs) > 50
    for r in all_reqs:
        skill_name = r["skill"]
        canonical = taxonomy.normalize_skill(skill_name)
        assert canonical == skill_name, f"Skill '{skill_name}' is not in canonical display form"


# ===========================================================================
# 4. ALIAS RESOLUTION & CASE INSENSITIVITY TESTS
# ===========================================================================

def test_role_alias_resolution():
    """Verify canonicalize_role_name resolves aliases and case variations."""
    assert industry_roles.canonicalize_role_name("swe") == "Software Engineer"
    assert industry_roles.canonicalize_role_name("sde") == "Software Engineer"
    assert industry_roles.canonicalize_role_name("software developer") == "Software Engineer"
    assert industry_roles.canonicalize_role_name("backend engineer") == "Backend Developer"
    assert industry_roles.canonicalize_role_name("front-end developer") == "Frontend Developer"
    assert industry_roles.canonicalize_role_name("fullstack developer") == "Full Stack Developer"
    assert industry_roles.canonicalize_role_name("ai/ml engineer") == "Machine Learning Engineer"
    assert industry_roles.canonicalize_role_name("mle") == "Machine Learning Engineer"
    assert industry_roles.canonicalize_role_name("cloud solutions architect") == "Cloud Engineer"
    assert industry_roles.canonicalize_role_name("infosec engineer") == "Cybersecurity Engineer"
    assert industry_roles.canonicalize_role_name("ios developer") == "Mobile Developer"


def test_industry_service_list_by_role_with_alias():
    """Verify list_by_role resolves alias strings transparently."""
    swe_reqs = industry_service.list_by_role("swe")
    full_reqs = industry_service.list_by_role("Software Engineer")
    assert len(swe_reqs) == len(full_reqs)
    assert {r["skill"] for r in swe_reqs} == {r["skill"] for r in full_reqs}


# ===========================================================================
# 5. MULTI-SOURCE REQUIREMENT AGGREGATION TESTS
# ===========================================================================

def test_multi_source_aggregation_formula():
    """
    Test deterministic aggregation of multiple requirement rows for same skill:
      required_level = sum(level_i * q_i) / sum(q_i)
      importance = sum(importance_i * q_i) / sum(q_i)
      confidence = min(0.98, max(0.40, 1.0 - prod(1 - 0.5 * q_i)))
    """
    sample_rows = [
        {
            "role": "Test Role",
            "skill": "Python",
            "skill_category": "Programming",
            "required_level": 0.80,
            "importance": 0.85,
            "demand": 0.80,
            "interview_relevance": 0.70,
            "source": "Source A",
            "source_quality": 0.90,
            "published_at": "2024-01-01",
        },
        {
            "role": "Test Role",
            "skill": "Python",
            "skill_category": "Programming",
            "required_level": 0.90,
            "importance": 0.95,
            "demand": 0.90,
            "interview_relevance": 0.80,
            "source": "Source B",
            "source_quality": 0.70,
            "published_at": "2024-02-01",
        },
    ]

    agg = industry_service.aggregate_requirements(sample_rows)
    assert len(agg) == 1
    res = agg[0]

    expected_level = (0.80 * 0.90 + 0.90 * 0.70) / (0.90 + 0.70)
    expected_imp = (0.85 * 0.90 + 0.95 * 0.70) / (0.90 + 0.70)
    assert math.isclose(res["required_level"], round(expected_level, 3), abs_tol=0.01)
    assert math.isclose(res["importance"], round(expected_imp, 3), abs_tol=0.01)

    # Confidence must compound with multiple sources
    uncovered = (1.0 - 0.5 * 0.90) * (1.0 - 0.5 * 0.70)
    expected_conf = min(0.98, max(0.40, 1.0 - uncovered))
    assert math.isclose(res["industry_confidence"], round(expected_conf, 3), abs_tol=0.01)


def test_aggregation_preserves_single_source_intact():
    """Verify single requirement passes through aggregation without distortion."""
    single = [{
        "role": "Test Role",
        "skill": "Docker",
        "skill_category": "DevOps/Cloud",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.85,
        "interview_relevance": 0.65,
        "source": "CNCF",
        "source_quality": 0.90,
        "industry_confidence": 0.90,
    }]
    agg = industry_service.aggregate_requirements(single)
    assert len(agg) == 1
    assert agg[0]["skill"] == "Docker"
    assert agg[0]["required_level"] == 0.75
    assert agg[0]["importance"] == 0.80


# ===========================================================================
# 6. ROLE COMPARISON TESTS
# ===========================================================================

def test_compare_roles_frontend_vs_fullstack():
    """Compare Frontend Developer vs Full Stack Developer (expect high overlap)."""
    comp = industry_service.compare_two_roles("Frontend Developer", "Full Stack Developer")
    assert comp["role_a"] == "Frontend Developer"
    assert comp["role_b"] == "Full Stack Developer"
    assert comp["overlap_score"] >= 0.40
    assert comp["transition_effort"] in ["low", "medium"]

    shared_skills = {s["skill"] for s in comp["shared_skills"]}
    assert "JavaScript" in shared_skills
    assert "React" in shared_skills
    assert "HTML/CSS" in shared_skills

    # Full Stack unique skills should include Node.js or SQL
    unique_b = {s["skill"] for s in comp["unique_skills_b"]}
    assert "Node.js" in unique_b or "SQL" in unique_b


def test_compare_roles_cybersecurity_vs_data_analyst():
    """Compare Cybersecurity Engineer vs Data Analyst (expect low overlap, high effort)."""
    comp = industry_service.compare_two_roles("Cybersecurity Engineer", "Data Analyst")
    assert comp["overlap_score"] < 0.35
    assert comp["transition_effort"] == "high"
    assert len(comp["unique_skills_b"]) > 0


# ===========================================================================
# 7. RETRIEVAL & VECTOR FALLBACK TESTS
# ===========================================================================

def test_retrieval_service_fallback_returns_normalized_items():
    """Verify retrieval_service.retrieve returns normalized skills with similarity proxy."""
    result = asyncio.run(retrieval_service.retrieve("Software Engineer"))
    assert result["role"] == "Software Engineer"
    assert result["count"] > 0
    assert len(result["items"]) > 0
    for it in result["items"]:
        assert "skill" in it
        assert "required_level" in it
        assert "importance" in it
        assert "similarity" in it
        assert 0.0 <= it["similarity"] <= 1.0


def test_retrieval_query_keyword_ranking():
    """Verify free-text query re-ranks requirements matching query terms."""
    result = asyncio.run(retrieval_service.retrieve("Software Engineer", query="testing automation"))
    assert result["count"] > 0
    first_item = result["items"][0]
    assert first_item["skill"] == "Testing" or "test" in first_item["skill"].lower()


# ===========================================================================
# 8. CUSTOM ROLE SYNTHESIS & HONEST REJECTION TESTS
# ===========================================================================

def test_custom_role_synthesis_with_knowledge_chunks():
    """Verify synthesis for custom role 'AI Engineer' uses knowledge chunks and extracts skills."""
    result = asyncio.run(retrieval_service.synthesize_custom_role("AI Engineer"))
    assert result["status"] == "synthesized"
    assert result["is_custom"] is True
    assert result["skills_count"] >= 3
    assert 0.50 <= result["confidence"] <= 0.80

    skills = {r["skill"] for r in result["requirements"]}
    assert "Python" in skills or "REST APIs" in skills or "Deep Learning" in skills


def test_custom_role_rejection_when_insufficient_data():
    """Verify ungrounded role is rejected honestly rather than fabricating fake numbers."""
    result = asyncio.run(retrieval_service.synthesize_custom_role("Quantum Origami Chef 4000"))
    assert result["status"] == "insufficient_data"
    assert result["skills_count"] < 2
    assert result["requirements"] == []
    assert result["confidence"] == 0.0
    assert "could not locate sufficient verifiable industry benchmark data" in result["note"]


# ===========================================================================
# 9. IN-MEMORY CACHING & INVALIDATION
# ===========================================================================

def test_industry_cache_retrieval_and_invalidation():
    """Verify role requirements are cached and cache can be invalidated safely."""
    # First call primes cache
    r1 = industry_service.list_by_role("Cloud Engineer")
    assert len(r1) > 0

    # Second call should retrieve cached result
    r2 = industry_service.list_by_role("Cloud Engineer")
    assert r1 == r2

    # Invalidate cache
    industry_service.clear_industry_cache()
    r3 = industry_service.list_by_role("Cloud Engineer")
    assert len(r3) == len(r1)


# ===========================================================================
# 10. INTEGRATION WITH DETERMINISTIC SKILL ENGINE & ANALYSIS
# ===========================================================================

def test_gap_analysis_integration_with_new_industry_dimensions():
    """Verify deterministic skill engine correctly processes new 5 dimensions."""
    reqs = industry_service.list_by_role("Backend Developer")
    req_map = ars.build_requirements_map(reqs)

    # Student has verified evidence in REST APIs and PostgreSQL
    signals = [
        {"skill": "REST APIs", "source": "github", "signal_strength": 0.80, "source_reliability": 0.90},
        {"skill": "PostgreSQL", "source": "github", "signal_strength": 0.70, "source_reliability": 0.85},
    ]
    grouped = ars.aggregate_skills(signals)
    assessments = ars.calculate_assessments(grouped, req_map)

    assert len(assessments) >= len(reqs)
    rest_api_assessment = next(a for a in assessments if a["canonical_name"] == "REST APIs")
    assert rest_api_assessment["proficiency"] > 0.0
    assert rest_api_assessment["is_missing_evidence"] is False

    # Missing skill (e.g. Caching) must be assessed with 0 evidence
    caching_assessment = next(a for a in assessments if a["canonical_name"] == "Caching")
    assert caching_assessment["proficiency"] == 0.0
    assert caching_assessment["confidence"] == 0.0
    assert caching_assessment["is_missing_evidence"] is True
    assert caching_assessment["gap"] == caching_assessment["required_level"]

    # Gaps calculation
    gaps = ars.calculate_gaps(assessments, "Backend Developer")
    assert len(gaps) > 0
    # Gaps must be sorted by priority_score descending
    for i in range(len(gaps) - 1):
        assert gaps[i]["priority_score"] >= gaps[i + 1]["priority_score"]
