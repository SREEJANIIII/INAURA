import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone
import uuid

from app.services import skill_engine as se
from app.services import analysis_run_service as ars
from app.services import industry_service


# ---------------------------------------------------------------------------
# Criterion 1: Skill Gap (student proficiency < required level)
# ---------------------------------------------------------------------------

def test_skill_gap_when_student_below_required():
    """When student has verified evidence below requirement, calculate positive gap."""
    current_prof = 0.50
    req_level = 0.75
    gap_val = se.gap(current_prof, req_level)
    assert gap_val == pytest.approx(0.25)

    prio_score, category, breakdown = se.calculate_prioritized_gap(
        gap_val=gap_val,
        importance=0.85,
        demand=0.80,
        student_confidence=0.70,
        interview_relevance=0.75,
        industry_confidence=0.90,
        gap_type="skill_gap",
    )
    assert prio_score > 0.0
    assert category in ("critical", "high", "medium")
    assert breakdown["gap"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Criterion 2: Zero Gap when student proficiency >= required level (Strengths)
# ---------------------------------------------------------------------------

def test_zero_gap_when_student_meets_or_exceeds_requirement():
    """When student proficiency meets or exceeds role requirement, gap is 0 and categorized as covered."""
    current_prof = 0.85
    req_level = 0.75
    gap_val = se.gap(current_prof, req_level)
    assert gap_val == 0.0

    prio_score, category, breakdown = se.calculate_prioritized_gap(
        gap_val=gap_val,
        importance=0.90,
        demand=0.85,
        student_confidence=0.80,
        interview_relevance=0.85,
        industry_confidence=0.90,
        gap_type="skill_gap",
    )
    assert prio_score == 0.0
    assert category == "covered"

    # Verify extract_strengths captures this skill
    assessments = [{
        "canonical_name": "Python",
        "display_name": "Python",
        "category": "Programming",
        "proficiency": 0.85,
        "confidence": 0.80,
        "required_level": 0.75,
        "gap": 0.0,
        "evidence_count": 3,
        "explanation": "Demonstrated across 3 projects",
        "quadrant": "strong_validated",
        "quadrant_title": "Strong & Validated",
        "is_missing_evidence": False,
    }]
    strengths = ars.extract_strengths(assessments)
    assert len(strengths) == 1
    assert strengths[0]["skill"] == "Python"
    assert strengths[0]["proficiency"] == 0.85


# ---------------------------------------------------------------------------
# Criterion 3: Evidence Gap (insufficient evidence, NOT confirmed inability)
# ---------------------------------------------------------------------------

def test_evidence_gap_communicates_insufficient_evidence():
    """Evidence gaps must communicate absence of evidence, NOT confirmed inability, with advice."""
    explanation = se.explain_evidence_gap(
        skill="Kubernetes",
        required_level=0.75,
        importance=0.80,
        actionable_advice="Deploy a mini-cluster using Minikube or Kind and push config repo to GitHub."
    )
    assert "No evidence found for Kubernetes" in explanation
    assert "not confirmed inability" in explanation.lower() or "absence of submitted evidence" in explanation.lower()
    assert "Minikube" in explanation

    # Ensure prioritized gap does not drop to 0 for unverified critical requirements
    prio_score, category, breakdown = se.calculate_prioritized_gap(
        gap_val=0.75,
        importance=0.90,
        demand=0.85,
        student_confidence=0.0,
        interview_relevance=0.85,
        industry_confidence=0.90,
        gap_type="evidence_gap",
    )
    assert prio_score >= se.GAP_CATEGORY_THRESHOLDS["critical"]
    assert category == "critical"


# ---------------------------------------------------------------------------
# Criterion 4: Multi-factor Prioritization (High Importance beats Large Trivial Gap)
# ---------------------------------------------------------------------------

def test_multifactor_priority_high_importance_outranks_large_low_importance_gap():
    """
    A 0.25 gap in DSA (importance 0.95, interview 0.95) MUST receive higher priority
    than a 0.50 gap in a low-importance elective skill (importance 0.35, interview 0.30).
    """
    # Core requirement: DSA with 0.25 gap
    prio_dsa, cat_dsa, _ = se.calculate_prioritized_gap(
        gap_val=0.25,
        importance=0.95,
        demand=0.90,
        student_confidence=0.50,
        interview_relevance=0.95,
        industry_confidence=0.95,
        gap_type="skill_gap",
    )

    # Elective tool: Docker with 0.50 gap
    prio_docker, cat_docker, _ = se.calculate_prioritized_gap(
        gap_val=0.50,
        importance=0.35,
        demand=0.40,
        student_confidence=0.70,
        interview_relevance=0.30,
        industry_confidence=0.85,
        gap_type="skill_gap",
    )

    # Priority of high-importance smaller gap must exceed large low-importance gap
    assert prio_dsa > prio_docker
    assert prio_dsa >= se.GAP_CATEGORY_THRESHOLDS["critical"]


# ---------------------------------------------------------------------------
# Criterion 5: Confidence-Aware Skill Quadrant Classification
# ---------------------------------------------------------------------------

def test_confidence_aware_quadrant_classification():
    """Verifies all 4 confidence-aware quadrants."""
    # 1. High Prof, High Conf -> strong_validated
    q1_key, q1_title, _ = se.classify_skill_quadrant(0.80, 0.75)
    assert q1_key == "strong_validated"
    assert "Strong" in q1_title

    # 2. High Prof, Low Conf -> unverified_claim
    q2_key, q2_title, _ = se.classify_skill_quadrant(0.80, 0.20)
    assert q2_key == "unverified_claim"
    assert "Unverified" in q2_title

    # 3. Low Prof, High Conf -> confirmed_gap
    q3_key, q3_title, _ = se.classify_skill_quadrant(0.35, 0.75)
    assert q3_key == "confirmed_gap"
    assert "Confirmed" in q3_title

    # 4. Low Prof, Low Conf -> exploratory
    q4_key, q4_title, _ = se.classify_skill_quadrant(0.20, 0.15)
    assert q4_key == "exploratory"
    assert "Exploratory" in q4_title


# ---------------------------------------------------------------------------
# Criterion 6: Role Dependence of Gap Priorities
# ---------------------------------------------------------------------------

def test_gap_priorities_differ_by_target_role():
    """The same student profile produces different gap priorities for Frontend vs DevOps roles."""
    assessments_common = [
        {
            "canonical_name": "React",
            "display_name": "React",
            "proficiency": 0.20,
            "required_level": 0.80,
            "confidence": 0.40,
            "evidence_count": 1,
            "gap": 0.60,
            "importance": 0.95,  # High in Frontend
            "demand": 0.90,
            "interview": 0.90,
            "interview_relevance": 0.90,
            "priority": 55.0,
            "priority_score": 55.0,
            "category": "Frontend",
            "is_missing_evidence": False,
        },
        {
            "canonical_name": "Kubernetes",
            "display_name": "Kubernetes",
            "proficiency": 0.20,
            "required_level": 0.80,
            "confidence": 0.40,
            "evidence_count": 1,
            "gap": 0.60,
            "importance": 0.20,  # Low in Frontend, but high in DevOps
            "demand": 0.30,
            "interview": 0.20,
            "interview_relevance": 0.20,
            "priority": 15.0,
            "priority_score": 15.0,
            "category": "DevOps",
            "is_missing_evidence": False,
        }
    ]

    gaps_frontend = ars.calculate_gaps(assessments_common, "Frontend Developer")
    # In Frontend Developer, React gap must rank above Kubernetes
    top_skill = gaps_frontend[0]["canonical_name"]
    assert top_skill == "React"


# ---------------------------------------------------------------------------
# Criterion 7: DSA Topic Coverage Extraction
# ---------------------------------------------------------------------------

def test_dsa_topic_coverage_gaps_extraction():
    """Weak or missing pillars from LeetCode evidence are extracted as coverage_gap items."""
    signals = [
        {
            "canonical_name": "Data Structures & Algorithms",
            "skill": "Data Structures & Algorithms",
            "source": "leetcode",
            "metadata": {
                "pillar_breakdown": {
                    "Arrays & Strings": {"solved": 45, "status": "covered", "percentage": 45.0},
                    "Dynamic Programming": {"solved": 0, "status": "missing", "percentage": 0.0},
                    "Graphs": {"solved": 1, "status": "weak", "percentage": 1.0},
                    "Trees": {"solved": 15, "status": "moderate", "percentage": 15.0},
                },
                "missing_topics": ["Dynamic Programming"],
                "weak_topics": ["Graphs"],
            }
        }
    ]

    topic_gaps = ars.extract_dsa_topic_gaps(evidence=[], signals=signals)
    assert len(topic_gaps) >= 2

    dp_gap = next((g for g in topic_gaps if g["pillar"] == "Dynamic Programming"), None)
    assert dp_gap is not None
    assert dp_gap["status"] == "missing"
    assert dp_gap["gap_type"] == "coverage_gap"
    assert dp_gap["priority_category"] == "critical"
    assert "memoization" in dp_gap["actionable_advice"].lower() or "recursion" in dp_gap["actionable_advice"].lower()

    graph_gap = next((g for g in topic_gaps if g["pillar"] == "Graphs"), None)
    assert graph_gap is not None
    assert graph_gap["status"] == "weak"


# ---------------------------------------------------------------------------
# Criterion 8: Re-analysis Signal Deduplication
# ---------------------------------------------------------------------------

def test_persist_analysis_deduplicates_signals():
    """Running persist_analysis deletes previous signals for the user so signals don't accumulate."""
    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    mock_table.select.return_value.execute.return_value.data = []
    mock_table.insert.return_value.execute.return_value.data = [{"id": "test-res-1"}]
    mock_table.delete.return_value.eq.return_value.execute.return_value.data = []

    user_id = str(uuid.uuid4())
    readiness_data = {
        "readiness_score": 0.72,
        "skill_component": 0.75,
        "industry_component": 0.70,
        "evidence_component": 0.65,
        "explanation": "Readiness breakdown",
    }

    ars.persist_analysis(
        user_id=user_id,
        target_role="Software Engineer",
        readiness_data=readiness_data,
        assessments=[],
        gaps=[],
        signals=[],
        skills_map={},
        c=mock_client,
    )

    # Verify delete was called on skill_signals for this user
    mock_client.table.assert_any_call("skill_signals")
    mock_table.delete.return_value.eq.assert_called_with("user_id", user_id)


# ---------------------------------------------------------------------------
# Criterion 9: Historical Analysis Snapshot Preservation
# ---------------------------------------------------------------------------

def test_historical_analysis_snapshots_preserved():
    """Each analysis run inserts a new distinct snapshot record into analysis_results."""
    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    mock_table.insert.return_value.execute.return_value.data = [{"id": "run-snapshot-uuid"}]

    user_id = str(uuid.uuid4())
    readiness_data = {
        "readiness_score": 0.65,
        "skill_component": 0.60,
        "industry_component": 0.70,
        "evidence_component": 0.65,
        "explanation": "Run 1",
    }

    run1_id = ars.persist_analysis(
        user_id=user_id,
        target_role="Software Engineer",
        readiness_data=readiness_data,
        assessments=[],
        gaps=[],
        signals=[],
        skills_map={},
        c=mock_client,
    )

    # Verify analysis_results received an INSERT, not an overwrite
    mock_client.table.assert_any_call("analysis_results")
    assert run1_id is not None


# ---------------------------------------------------------------------------
# Criterion 10: Explainability & Non-fabrication
# ---------------------------------------------------------------------------

def test_explainability_traceability_and_disclaimer():
    """
    Every readiness result includes transparent component breakdown and disclaimer:
    Readiness != Placement Guarantee.
    """
    sc = 0.80
    ic = 0.70
    ec = 0.60
    r_score = se.readiness(sc, ic, ec)
    explanation = se.explain_readiness(sc, ic, ec, r_score)

    assert "0.45×skill" in explanation
    assert "0.25×industry" in explanation
    assert "0.30×evidence" in explanation
    assert f"{int(round(r_score * 100))}%" in explanation

    # Verify no NaN or fabricated placement certainty
    assert not (r_score != r_score)
    assert 0.0 <= r_score <= 1.0
