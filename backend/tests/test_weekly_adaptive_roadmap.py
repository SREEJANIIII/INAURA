import pytest
import math
from app.services import skill_dependencies as sd
from app.services import learner_state_service as lss
from app.services import roadmap_catalog as rc
from app.services import roadmap_service as rs


# 1. Skill Dependencies DAG & Topological Sort Tests

def test_skill_dependencies_prerequisites():
    assert "python" in sd.get_prerequisites_for_skill("numpy")
    assert "numpy" in sd.get_prerequisites_for_skill("pandas")
    assert "javascript" in sd.get_prerequisites_for_skill("react")
    assert "docker" in sd.get_prerequisites_for_skill("kubernetes")
    assert "linux" in sd.get_prerequisites_for_skill("docker")


def test_topological_resolution_orders_prerequisites_first():
    # Candidate skills where numpy depends on python
    candidates = ["numpy", "python", "pandas"]
    ordered = sd.resolve_dependencies(candidates)
    assert ordered.index("python") < ordered.index("numpy")
    assert ordered.index("numpy") < ordered.index("pandas")


def test_topological_resolution_with_known_skills():
    # If Python is already known by learner (prof >= 0.60), numpy does not need python first
    candidates = ["numpy", "react", "javascript"]
    profs = {"python": 0.85, "javascript": 0.20}
    ordered = sd.resolve_dependencies(candidates, learner_proficiencies=profs)
    # JS is not satisfied, so JS must precede React
    assert ordered.index("javascript") < ordered.index("react")


def test_topological_resolution_priority_tie_breaking():
    # If skills are independent (e.g. python and html_css), highest priority goes first
    candidates = ["python", "html_css"]
    priorities = {"python": 20.0, "html_css": 80.0}
    ordered = sd.resolve_dependencies(candidates, priority_scores=priorities)
    assert ordered[0] == "html_css"
    assert ordered[1] == "python"


# 2. Learner Skill State Classification Tests

def test_learner_state_classification_known():
    # High assessment score -> KNOWN
    state, reasoning = lss.classify_learner_state(
        proficiency=0.80,
        confidence=0.85,
        evidence_count=3,
        evidence_depth=3,
        has_assessment=True,
        active_sources=["assessment", "github"],
        skill_name="Python",
        gap_val=0.0,
        required_level=0.80,
    )
    assert state == "KNOWN"
    assert "verified through INAURA assessment" in reasoning


def test_learner_state_classification_inferred():
    # Supporting repository evidence without assessment -> INFERRED
    state, reasoning = lss.classify_learner_state(
        proficiency=0.45,
        confidence=0.35,
        evidence_count=2,
        evidence_depth=3,
        has_assessment=False,
        active_sources=["github", "projects"],
        skill_name="Docker",
        gap_val=0.30,
        required_level=0.75,
    )
    assert state == "INFERRED"
    assert "Supporting evidence" in reasoning


def test_learner_state_classification_unknown():
    # No evidence -> UNKNOWN (NOT zero ability)
    state, reasoning = lss.classify_learner_state(
        proficiency=0.0,
        confidence=0.0,
        evidence_count=0,
        evidence_depth=0,
        has_assessment=False,
        active_sources=[],
        skill_name="Kubernetes",
        gap_val=0.70,
        required_level=0.70,
    )
    assert state == "UNKNOWN"
    assert "not assumed to be zero skill" in reasoning.lower() or "unevidenced gap" in reasoning.lower()


# 3. 4-Stage Task Decomposition Tests

def test_decompose_skill_into_4_stages():
    tasks = rc.decompose_skill_into_tasks(
        canonical="Python",
        total_hours=10.0,
        learner_state_classification="UNKNOWN",
        target_role="Backend Developer",
    )
    assert len(tasks) == 4
    stages = [t["task_type"] for t in tasks]
    assert stages == ["learn", "practice", "build", "validate"]

    # Minutes should sum to total_hours * 60
    total_mins = sum(t["estimated_minutes"] for t in tasks)
    assert total_mins == 600

    # Resources should be attached
    assert len(tasks[0]["resources"]) >= 1


def test_decompose_skill_inferred_accelerated_learn():
    unknown_tasks = rc.decompose_skill_into_tasks("SQL", total_hours=8.0, learner_state_classification="UNKNOWN")
    inferred_tasks = rc.decompose_skill_into_tasks("SQL", total_hours=8.0, learner_state_classification="INFERRED")

    # Inferred learner spends less time on learn and more on build
    assert inferred_tasks[0]["estimated_minutes"] < unknown_tasks[0]["estimated_minutes"]
    assert inferred_tasks[2]["estimated_minutes"] >= unknown_tasks[2]["estimated_minutes"]


# 4. Evidence Snapshot Tests

def test_create_evidence_snapshot_structure():
    snapshot = lss.create_evidence_snapshot(
        user_id="11111111-1111-1111-1111-111111111111",
        analysis_result_id="22222222-2222-2222-2222-222222222222",
        learner_states={},
    )
    assert "id" in snapshot
    assert snapshot["user_id"] == "11111111-1111-1111-1111-111111111111"
    assert snapshot["analysis_result_id"] == "22222222-2222-2222-2222-222222222222"
    assert "sources_analyzed" in snapshot
    assert "sources_available" in snapshot
    assert "sources_unavailable" in snapshot
    assert snapshot["engine_version"] == "5A-v1"


# 5. Backward Compatibility Tests

def test_backward_compatibility_preserved():
    # Existing rs functions still exist and work
    assert rs.estimate_weeks(20, 10) == 2
    assert rs.clamp01(1.5) == 1.0
    assert rs.validate_completion_percentage(50) == 50.0
    with pytest.raises(Exception):
        rs.validate_completion_percentage(150)
