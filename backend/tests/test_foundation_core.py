import pytest
from app.services import skill_taxonomy as taxonomy
from app.services import skill_engine as se
from app.services import signal_extractor as extractor
from app.services import analysis_run_service as ars


# ===========================================================================
# 1. CANONICAL SKILL TAXONOMY & NORMALIZATION TESTS
# ===========================================================================

def test_skill_normalization_required_examples():
    """
    At minimum test:
      ReactJS → React
      React.js → React
      DSA → Data Structures & Algorithms
      Postgres → PostgreSQL
    """
    assert taxonomy.normalize_skill("ReactJS") == "React"
    assert taxonomy.normalize_skill("React.js") == "React"
    assert taxonomy.normalize_skill("DSA") == "Data Structures & Algorithms"
    assert taxonomy.normalize_skill("Postgres") == "PostgreSQL"


def test_skill_normalization_additional_variations():
    # REST APIs
    assert taxonomy.normalize_skill("REST API") == "REST APIs"
    assert taxonomy.normalize_skill("REST APIs") == "REST APIs"
    assert taxonomy.normalize_skill("rest api") == "REST APIs"
    assert taxonomy.normalize_skill("fastapi") == "REST APIs"

    # Databases
    assert taxonomy.normalize_skill("postgresql") == "PostgreSQL"
    assert taxonomy.normalize_skill("psql") == "PostgreSQL"
    assert taxonomy.normalize_skill("mongodb") == "MongoDB"
    assert taxonomy.normalize_skill("redis") == "Redis"

    # Frontend
    assert taxonomy.normalize_skill("react-js") == "React"
    assert taxonomy.normalize_skill("next.js") == "Next.js"
    assert taxonomy.normalize_skill("nextjs") == "Next.js"

    # Computer Science & Backend
    assert taxonomy.normalize_skill("dsa") == "Data Structures & Algorithms"
    assert taxonomy.normalize_skill("algorithms") == "Data Structures & Algorithms"
    assert taxonomy.normalize_skill("node.js") == "Node.js"
    assert taxonomy.normalize_skill("nodejs") == "Node.js"
    assert taxonomy.normalize_skill("spring boot") == "Spring Boot"
    assert taxonomy.normalize_skill("oop") == "OOP"
    assert taxonomy.normalize_skill("operating systems") == "Operating Systems"
    assert taxonomy.normalize_skill("computer networks") == "Computer Networks"

    # DevOps / Cloud
    assert taxonomy.normalize_skill("docker") == "Docker"
    assert taxonomy.normalize_skill("k8s") == "Kubernetes"
    assert taxonomy.normalize_skill("kubernetes") == "Kubernetes"
    assert taxonomy.normalize_skill("ci/cd") == "CI/CD"
    assert taxonomy.normalize_skill("github actions") == "GitHub Actions"


def test_canonical_skill_slugs():
    assert taxonomy.normalize_skill_slug("ReactJS") == "react"
    assert taxonomy.normalize_skill_slug("Postgres") == "postgresql"
    assert taxonomy.normalize_skill_slug("DSA") == "dsa"
    assert taxonomy.normalize_skill_slug("REST API") == "rest_apis"


def test_canonical_skill_categories():
    react_def = taxonomy.get_canonical_skill("ReactJS")
    assert react_def is not None
    assert react_def.category == "Frontend"

    dsa_def = taxonomy.get_canonical_skill("DSA")
    assert dsa_def is not None
    assert dsa_def.category == "Computer Science"

    pg_def = taxonomy.get_canonical_skill("Postgres")
    assert pg_def is not None
    assert pg_def.category == "Databases"

    node_def = taxonomy.get_canonical_skill("Node.js")
    assert node_def is not None
    assert node_def.category == "Backend"

    docker_def = taxonomy.get_canonical_skill("Docker")
    assert docker_def is not None
    assert docker_def.category == "DevOps/Cloud"


def test_extract_known_skills_from_text():
    text = "Developed a full-stack platform using React, PostgreSQL, and REST APIs with Docker containerization."
    found = taxonomy.extract_known_skills_from_text(text)
    display_names = {s.display_name for s in found}
    assert "React" in display_names
    assert "PostgreSQL" in display_names
    assert "REST APIs" in display_names
    assert "Docker" in display_names


# ===========================================================================
# 2. SIGNAL MODEL & EXTRACTION TESTS
# ===========================================================================

def test_signal_model_conceptual_fields():
    projects = [{
        "id": "proj-1",
        "name": "Cloud Microservices",
        "description": "Implemented Docker container deployment and PostgreSQL database indexing.",
        "technologies": ["Docker", "PostgreSQL"],
    }]
    signals = extractor.extract_signals([], projects, [])
    assert len(signals) >= 2
    for s in signals:
        # Verify both new conceptual fields and backward-compatible fields
        assert "skill" in s
        assert "source" in s
        assert "signal_strength" in s
        assert "source_reliability" in s
        assert "reason" in s
        assert "canonical_name" in s
        assert "source_type" in s
        assert "signal_value" in s
        assert "explanation" in s
        assert 0.0 <= s["signal_strength"] <= 1.0
        assert 0.0 <= s["source_reliability"] <= 1.0


def test_url_only_evidence_produces_no_proficiency():
    evidence = [
        {"id": "e1", "evidence_type": "github", "source_url": "https://github.com/student"},
        {"id": "e2", "evidence_type": "leetcode", "source_url": "https://leetcode.com/student"},
        {"id": "e3", "evidence_type": "linkedin", "source_url": "https://linkedin.com/in/student"},
    ]
    signals = extractor.extract_signals(evidence, [], [])
    # Merely submitting a URL must not yield arbitrary skill proficiency
    assert len(signals) == 0


def test_evidence_strength_separate_from_source_reliability():
    projects = [{
        "id": "proj-2",
        "name": "Basic Profile",
        "description": "Simple student webpage.",
        "technologies": ["Docker"],
    }]
    signals = extractor.extract_signals([], projects, [])
    docker_sig = [s for s in signals if s["skill"] == "Docker"][0]
    # Tech-only listing gives moderate/weak depth (0.30), while project source reliability is 0.90
    assert docker_sig["signal_strength"] == pytest.approx(0.30)
    assert docker_sig["source_reliability"] == pytest.approx(0.90)
    assert docker_sig["signal_strength"] != docker_sig["source_reliability"]


# ===========================================================================
# 3. SIGNAL AGGREGATION TESTS
# ===========================================================================

def test_signal_aggregation_weighted_average():
    """Multiple signals for the same skill must be combined using reliability-weighted average."""
    # Signal 1: Strong project implementation (strength 0.75, weight 0.90)
    # Signal 2: Resume mention (strength 0.35, weight 0.50)
    signals = [
        {"skill": "Docker", "signal_strength": 0.75, "source_reliability": 0.90, "source": "project"},
        {"skill": "Docker", "signal_strength": 0.35, "source_reliability": 0.50, "source": "resume"},
    ]
    prof, weight, count, avg_sig = se.proficiency(signals)
    expected_prof = (0.75 * 0.90 + 0.35 * 0.50) / (0.90 + 0.50)
    assert prof == pytest.approx(expected_prof, abs=1e-5)
    assert weight == pytest.approx(1.40, abs=1e-5)
    assert count == 2
    assert avg_sig == pytest.approx((0.75 + 0.35) / 2, abs=1e-5)


def test_signal_aggregation_three_sources():
    signals = [
        {"skill": "Python", "signal_strength": 0.75, "source_reliability": 0.90, "source": "project"},
        {"skill": "Python", "signal_strength": 0.70, "source_reliability": 0.85, "source": "leetcode"},
        {"skill": "Python", "signal_strength": 0.50, "source_reliability": 0.65, "source": "certification"},
    ]
    prof, weight, count, _ = se.proficiency(signals)
    expected = (0.75 * 0.90 + 0.70 * 0.85 + 0.50 * 0.65) / (0.90 + 0.85 + 0.65)
    assert prof == pytest.approx(expected, abs=1e-5)
    assert count == 3


# ===========================================================================
# 4. CONFIDENCE DIVERSITY & VOLUME TESTS
# ===========================================================================

def test_confidence_quantity_and_diversity():
    """Different evidence quantity and diversity must produce sensible confidence values."""
    # Low volume, low diversity (1 source, weight 0.50)
    conf_low, _, _ = se.confidence(0.50, 1)

    # Moderate volume, moderate diversity (2 sources, weight 1.40)
    conf_med, _, _ = se.confidence(1.40, 2)

    # High volume, high diversity (3+ sources, weight >= 2.5)
    conf_high, _, _ = se.confidence(2.50, 3)

    assert 0.0 < conf_low < conf_med < conf_high <= 1.0
    assert conf_low < 0.40   # Low confidence bracket
    assert 0.40 <= conf_med <= 0.70  # Moderate bracket
    assert conf_high >= 0.90 # Near or at saturation


def test_confidence_zero_when_no_evidence():
    conf_zero, w_norm, d_norm = se.confidence(0.0, 0)
    assert conf_zero == 0.0
    assert w_norm == 0.0
    assert d_norm == 0.0


# ===========================================================================
# 5. MISSING SKILLS TESTS
# ===========================================================================

def test_missing_required_skill_assessment():
    """
    A required skill with no evidence should produce:
      proficiency = 0
      confidence = 0
      gap = required_level
    and clearly note lack of evidence rather than asserting inability.
    """
    requirements_map = {
        "Kubernetes": {
            "skill": "Kubernetes",
            "category": "DevOps/Cloud",
            "required_level": 0.75,
            "importance": 0.80,
            "demand": 0.85,
            "interview": 0.70,
            "description": "Container orchestration",
            "source": "Prototype",
        }
    }
    grouped_signals = {}  # Student has zero signals for Kubernetes

    assessments = ars.calculate_assessments(grouped_signals, requirements_map)
    assert len(assessments) == 1

    k8s = assessments[0]
    assert k8s["canonical_name"] == "Kubernetes"
    assert k8s["proficiency"] == 0.0
    assert k8s["confidence"] == 0.0
    assert k8s["evidence_count"] == 0
    assert k8s["gap"] == pytest.approx(0.75)
    assert k8s["is_missing_evidence"] is True

    # Check human-readable explanation distinguishes absence of evidence from verified inability
    assert "No evidence" in k8s["explanation"]
    assert "not verified inability" in k8s["explanation"].lower() or "absence of submitted evidence" in k8s["explanation"].lower()


def test_missing_skill_gap_calculation():
    assessments = [{
        "canonical_name": "Kubernetes",
        "display_name": "Kubernetes",
        "proficiency": 0.0,
        "required_level": 0.80,
        "gap": 0.80,
        "importance": 0.85,
        "demand": 0.90,
        "interview": 0.75,
        "confidence": 0.0,
        "priority": 0.0,
        "evidence_count": 0,
        "category": "DevOps/Cloud",
    }]
    gaps = ars.calculate_gaps(assessments, "DevOps / Cloud Engineer")
    assert len(gaps) == 1
    g = gaps[0]
    assert g["current_proficiency"] == 0.0
    assert g["required_level"] == 0.80
    assert g["gap"] == 0.80
    assert g["confidence"] == 0.0
    assert "not confirmed inability" in g["explanation"].lower() or "no evidence found" in g["explanation"].lower()


# ===========================================================================
# 6. GAP PRIORITIZATION TESTS
# ===========================================================================

def test_gap_prioritization_factors():
    """
    Higher:
      gap
      importance
      demand
      interview relevance
    should increase priority, subject to confidence/evidence logic.
    """
    base = se.gap_priority(gap_val=0.4, importance=0.6, demand=0.6, confidence_val=0.7, interview_relevance=0.6)

    # 1. Higher gap -> higher priority
    high_gap = se.gap_priority(gap_val=0.7, importance=0.6, demand=0.6, confidence_val=0.7, interview_relevance=0.6)
    assert high_gap > base

    # 2. Higher importance -> higher priority
    high_imp = se.gap_priority(gap_val=0.4, importance=0.9, demand=0.6, confidence_val=0.7, interview_relevance=0.6)
    assert high_imp > base

    # 3. Higher demand -> higher priority
    high_dem = se.gap_priority(gap_val=0.4, importance=0.6, demand=0.9, confidence_val=0.7, interview_relevance=0.6)
    assert high_dem > base

    # 4. Higher interview relevance -> higher priority
    high_ir = se.gap_priority(gap_val=0.4, importance=0.6, demand=0.6, confidence_val=0.7, interview_relevance=0.9)
    assert high_ir > base

    # 5. Zero confidence -> conservative priority (0.0)
    zero_conf = se.gap_priority(gap_val=0.8, importance=0.9, demand=0.9, confidence_val=0.0, interview_relevance=0.9)
    assert zero_conf == 0.0


# ===========================================================================
# 7. EXPLAINABILITY TESTS
# ===========================================================================

def test_explain_proficiency_with_evidence():
    signals = [
        {"source": "project", "signal_strength": 0.75, "reason": "FastAPI backend implementation with PostgreSQL"},
        {"source": "resume", "signal_strength": 0.35, "reason": "Mentioned in resume skills"},
    ]
    expl = se.explain_proficiency(
        proficiency_val=0.65,
        confidence_val=0.55,
        evidence_count=2,
        source_diversity=2,
        signals=signals,
        skill_name="REST APIs",
    )
    assert "Estimated proficiency 65%" in expl
    assert "project" in expl
    assert "resume" in expl
    assert "Confidence is moderate" in expl


def test_explain_gap_covered_and_deficit():
    # Covered skill
    expl_covered = se.explain_gap(
        skill="Python",
        current=0.90,
        required=0.80,
        gap_val=0.0,
        importance=0.85,
        confidence_val=0.80,
    )
    assert "meets or exceeds" in expl_covered

    # Uncovered deficit
    expl_deficit = se.explain_gap(
        skill="Docker",
        current=0.30,
        required=0.75,
        gap_val=0.45,
        importance=0.80,
        confidence_val=0.60,
    )
    assert "gap 45%" in expl_deficit
    assert "importance" in expl_deficit.lower()


def test_explain_readiness():
    expl = se.explain_readiness(
        skill_c=0.70,
        industry_c=0.60,
        evidence_c=0.50,
        readiness_val=0.615,
    )
    assert "62%" in expl
    assert "0.45×skill" in expl
    assert "0.25×industry" in expl
    assert "0.30×evidence" in expl
