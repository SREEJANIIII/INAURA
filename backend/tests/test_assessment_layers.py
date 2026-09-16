"""
Tests for the skill-specific 3-layer assessment flow.

Layers: knowledge (existing MCQ bank) / practical (work-sample tasks) /
interview (structured, skill-specific AI interview).

Product principles under test:
  * every skill is validated with only the layers appropriate for it —
    coding tasks are never forced onto non-coding skills
  * the knowledge layer keeps working exactly as before (deterministic)
  * interviews are skill-specific, competency-anchored, and keep technical
    evaluation separate from communication evaluation
  * every layer emits standard assessment signals so the existing skill/gap
    pipeline incorporates them with no competing score system
  * missing/partial layers never break the skill profile
"""

from typing import Any, Dict, List

import pytest

from app.services.assessment import interview as interview_mod
from app.services.assessment import layers
from app.services.assessment import practical_bank as pb
from app.services.assessment import practical_service as ps
from app.services.assessment import question_bank as bank
from app.services.assessment import service as knowledge_service
from app.services import evidence_weights as weights


# ===========================================================================
# 1. Skill capabilities: applicable layers per skill type
# ===========================================================================

def test_dsa_receives_all_three_layers():
    cap = layers.capability_for_skill("Data Structures & Algorithms")
    assert cap is not None
    assert cap.knowledge_assessment is True
    assert cap.practical_assessment is True
    assert cap.interview_assessment is True
    assert cap.layers == ["knowledge", "practical", "interview"]


def test_dsa_alias_resolves_to_same_capability():
    cap = layers.capability_for_skill("DSA")
    assert cap is not None
    assert cap.skill == "Data Structures & Algorithms"
    assert cap.practical_assessment is True


def test_python_receives_practical_assessment():
    cap = layers.capability_for_skill("Python")
    assert cap is not None
    assert cap.knowledge_assessment is True
    assert cap.practical_assessment is True
    assert cap.interview_assessment is True


def test_sql_receives_practical_sql_task():
    cap = layers.capability_for_skill("SQL")
    assert cap is not None and cap.practical_assessment is True
    task = pb.select_task("SQL")
    assert task is not None
    assert task.task_type == "sql"
    assert task.skill == "SQL"


def test_non_coding_skill_gets_no_coding_task():
    # Git has knowledge questions but no work-sample task: knowledge +
    # interview only, never a coding task.
    cap = layers.capability_for_skill("Git")
    assert cap is not None
    assert cap.knowledge_assessment is True
    assert cap.practical_assessment is False
    assert cap.interview_assessment is True
    assert "practical" not in cap.layers
    assert pb.select_task("Git") is None
    assert pb.has_practical("Git") is False


def test_system_design_gets_no_practical_task():
    cap = layers.capability_for_skill("System Design")
    assert cap is not None
    assert cap.practical_assessment is False
    assert cap.interview_assessment is True


def test_unknown_skill_has_no_capability():
    assert layers.capability_for_skill("Underwater Basket Weaving XYZ") is None


def test_react_and_java_receive_practical_tasks():
    for skill in ("React", "Java", "JavaScript"):
        cap = layers.capability_for_skill(skill)
        assert cap is not None and cap.practical_assessment is True, skill
        assert pb.select_task(skill) is not None, skill


# ===========================================================================
# 2. Knowledge assessment keeps working (deterministic, unchanged)
# ===========================================================================

def test_knowledge_bank_still_valid():
    assert bank.validate_bank() == []


def test_knowledge_grading_unchanged():
    questions = bank.select_questions("Python", limit=5, seed="fixed-seed")
    assert len(questions) == 5
    responses = {q.id: (q.correct_option or "") for q in questions if q.is_multiple_choice}
    for q in questions:
        if not q.is_multiple_choice:
            responses[q.id] = q.accepted_answers[0]
    correct, _ = knowledge_service.grade_responses(questions, responses)
    assert correct == len(questions)


def test_knowledge_signals_carry_no_layer_marker():
    # Backward compatibility: knowledge signals keep their exact existing
    # shape (no assessment_layer key), so the pipeline's aggregate
    # assessment_score derivation is unchanged.
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    attempts = [{
        "id": "att-1", "skill_name": "Python", "status": "completed",
        "validity": "valid", "score": 0.8, "correct_count": 4,
        "question_count": 5, "assessment_version": bank.ASSESSMENT_VERSION,
        "completed_at": now,
    }]
    signals = knowledge_service.build_assessment_signals(attempts)
    assert len(signals) == 1
    assert "assessment_layer" not in (signals[0].get("metadata") or {})


# ===========================================================================
# 3. Practical bank: content validity + deterministic grading
# ===========================================================================

def test_practical_bank_valid():
    assert pb.validate_practical_bank() == []


def test_practical_grading_rewards_structure():
    task = pb.get_task("sql-top-customers")
    assert task is not None
    good_sql = (
        "SELECT c.name, c.country, SUM(o.amount) AS revenue FROM customers c "
        "JOIN orders o ON o.customer_id = c.id "
        "WHERE o.status = 'completed' AND o.created_at >= '2025-01-01' "
        "GROUP BY c.name, c.country ORDER BY revenue DESC LIMIT 5"
    )
    score, checks, dims = ps.grade_practical_submission(task, good_sql)
    assert score == pytest.approx(1.0)
    assert all(c["passed"] for c in checks)
    assert set(dims) == {"query_correctness", "joins_filtering", "aggregation"}

    weak_score, _, _ = ps.grade_practical_submission(task, "hello world")
    assert weak_score == pytest.approx(0.0)


def test_empty_practical_submission_scores_zero():
    task = pb.get_task("dsa-two-sum")
    assert task is not None
    score, _, _ = ps.grade_practical_submission(task, "   ")
    assert score == pytest.approx(0.0)


def test_practical_grading_never_executes_code():
    task = pb.get_task("python-debug-max")
    assert task is not None
    # Even hostile text is only regex-matched, never run.
    score, _, _ = ps.grade_practical_submission(task, "__import__('os').system('rm -rf /')")
    assert 0.0 <= score <= 1.0


# ===========================================================================
# 4. Practical signals feed the existing pipeline contract
# ===========================================================================

def test_practical_signals_use_assessment_source_with_layer_marker():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    attempts = [{
        "id": "p-1", "skill_name": "Python", "status": "completed",
        "validity": "valid", "score": 0.62, "task_id": "python-debug-max",
        "task_version": pb.PRACTICAL_VERSION, "completed_at": now,
    }]
    signals = ps.build_practical_signals(attempts)
    assert len(signals) == 1
    sig = signals[0]
    assert sig["source_type"] == weights.ASSESSMENT_SOURCE
    assert (sig.get("metadata") or {}).get("assessment_layer") == "practical"
    assert float(sig.get("signal_strength", sig.get("signal_value", 0))) == pytest.approx(0.62)


def test_effective_practical_attempts_best_of_recent():
    from datetime import datetime, timedelta, timezone

    base = datetime.now(timezone.utc)
    attempts = [
        {
            "id": f"p-{i}", "skill_name": "SQL", "status": "completed",
            "validity": "valid", "score": score,
            "completed_at": (base - timedelta(days=i)).isoformat(),
        }
        for i, score in enumerate([0.4, 0.9, 0.6, 0.2])
    ]
    effective = ps.effective_practical_attempts(attempts)
    assert effective["SQL"]["score"] == pytest.approx(0.9)
    assert effective["SQL"]["attempts_considered"] == 3


def test_layered_signals_merge_without_breaking_pipeline_split():
    # The pipeline splits assessment vs evidence by source_type; every layer
    # must land on the assessment side.
    from datetime import datetime, timezone

    from app.services import signal_extractor as se

    now = datetime.now(timezone.utc).isoformat()
    knowledge = knowledge_service.build_assessment_signals([{
        "id": "att-1", "skill_name": "Python", "status": "completed",
        "validity": "valid", "score": 0.8, "correct_count": 4,
        "question_count": 5, "assessment_version": bank.ASSESSMENT_VERSION,
        "completed_at": now,
    }])
    practical = ps.build_practical_signals([{
        "id": "p-1", "skill_name": "Python", "status": "completed",
        "validity": "valid", "score": 0.62, "task_id": "python-debug-max",
        "task_version": pb.PRACTICAL_VERSION, "completed_at": now,
    }])
    interview = interview_mod.build_interview_signals(sessions=[{
        "id": "s-1", "skill_name": "Python",
        "technical_scores": {"overall": 0.74, "per_competency": {"implementation_reasoning": 0.74}},
        "interview_version": interview_mod.INTERVIEW_VERSION,
        "completed_at": now,
    }])
    github = [se.make_signal(canonical="Python", source_type="github", signal_value=0.7,
                             explanation="repo evidence")]
    all_signals = knowledge + practical + interview + github
    assessment_sigs = [s for s in all_signals if s.get("source_type") == weights.ASSESSMENT_SOURCE]
    assert len(assessment_sigs) == 3
    assert max(float(s.get("signal_strength", s.get("signal_value", 0)) or 0) for s in assessment_sigs) == pytest.approx(0.8)


# ===========================================================================
# 5. Interviews are skill-specific and competency-anchored
# ===========================================================================

def test_interview_competencies_defined_per_skill():
    for skill, expected in (
        ("Data Structures & Algorithms", "complexity_reasoning"),
        ("Python", "implementation_reasoning"),
        ("SQL", "query_reasoning"),
        ("React", "component_reasoning"),
    ):
        comps = interview_mod.competencies_for_skill(skill)
        assert expected in {c["id"] for c in comps}, skill


def test_interview_plan_valid_and_anchored():
    plan = interview_mod.build_interview_plan("Python", knowledge_score=0.9, practical_score=0.4)
    assert interview_mod.validate_plan(plan) == []
    assert plan["skill"] == "Python"
    comp_ids = {c["id"] for c in plan["competencies"]}
    for q in plan["questions"]:
        assert q["competency"] in comp_ids
        assert q["prompt"].strip()
    # Weak practical layer becomes the focus; basics are not repeated for fun.
    assert "practical_reasoning" in plan["focus_areas"]


def test_interview_plan_references_related_projects():
    projects = [
        {"name": "ResQNet", "description": "FastAPI backend", "technologies": ["Python", "FastAPI"]},
        {"name": "Notes", "description": "plain notes", "technologies": ["Markdown"]},
    ]
    plan = interview_mod.build_interview_plan("Python", projects=projects)
    assert interview_mod.validate_plan(plan) == []
    assert plan["related_projects"] == ["ResQNet"]
    assert "ResQNet" in plan["questions"][0]["prompt"]


def test_interview_plan_deep_mode_for_strong_profile():
    plan = interview_mod.build_interview_plan("Python", knowledge_score=0.9, practical_score=0.85)
    assert plan["deep_mode"] is True
    assert "deep_reasoning" in plan["focus_areas"]


def test_interview_plan_for_non_coding_skill():
    plan = interview_mod.build_interview_plan("Git", knowledge_score=0.3)
    assert interview_mod.validate_plan(plan) == []
    assert "fundamentals" in plan["focus_areas"]


# ===========================================================================
# 6. Technical vs communication evaluation stays separate
# ===========================================================================

def test_interview_signal_excludes_communication():
    sessions = [{
        "id": "s-1", "skill_name": "Python",
        "technical_scores": {"overall": 0.7, "per_competency": {}},
        "communication_scores": {"overall": 0.95, "per_dimension": {"clarity": 0.95}},
        "interview_version": interview_mod.INTERVIEW_VERSION,
        "completed_at": "2026-01-01T00:00:00+00:00",
    }]
    signals = interview_mod.build_interview_signals(sessions=sessions)
    assert len(signals) == 1
    metadata = signals[0].get("metadata") or {}
    # Communication must not leak into the signal: no communication keys,
    # no communication values, signal driven by technical overall only.
    assert "communication_scores" not in metadata
    assert "clarity" not in str(metadata)
    assert "0.95" not in str(metadata)
    assert float(signals[0].get("signal_strength", signals[0].get("signal_value", 0))) == pytest.approx(0.7)


def test_interview_grading_validates_model_output(monkeypatch):
    # Mock the LLM: one call, structured output, then check separation.
    import app.services.assessment.interview as iv

    class _Msg:
        content = (
            '{"technical": {"implementation_reasoning": 0.8, "python_specifics": 0.6, '
            '"debugging": 0.7, "design_decisions": 0.5, "explanation": 0.9}, '
            '"communication": {"clarity": 0.9, "relevance": 0.8, "structure": 0.7, '
            '"justification": 0.6, "follow_ups": 0.5}}'
        )

    class _FakeLLM:
        def __init__(self):
            self.calls = 0

        def invoke(self, prompt):
            self.calls += 1
            assert "Python" in prompt
            return _Msg()

    fake = _FakeLLM()
    monkeypatch.setattr(iv, "_make_interview_llm", lambda: fake)
    grades = iv.grade_interview_transcript(
        "Python", iv.competencies_for_skill("Python"),
        [{"competency": "implementation_reasoning", "prompt": "Q", "answer": "A"}],
    )
    assert fake.calls == 1
    assert set(grades["technical"]) == {c["id"] for c in iv.competencies_for_skill("Python")}
    assert set(grades["communication"]) == {"clarity", "relevance", "structure", "justification", "follow_ups"}
    assert all(0.0 <= v <= 1.0 for v in list(grades["technical"].values()) + list(grades["communication"].values()))


def test_interview_grading_rejects_incomplete_model_output(monkeypatch):
    import app.services.assessment.interview as iv
    from fastapi import HTTPException

    class _Msg:
        content = '{"technical": {"implementation_reasoning": 0.8}}'

    class _FakeLLM:
        def invoke(self, prompt):
            return _Msg()

    monkeypatch.setattr(iv, "_make_interview_llm", lambda: _FakeLLM())
    with pytest.raises(HTTPException):
        iv.grade_interview_transcript(
            "Python", iv.competencies_for_skill("Python"),
            [{"competency": "implementation_reasoning", "prompt": "Q", "answer": "A"}],
        )


# ===========================================================================
# 7. Missing/partial layers never break the profile
# ===========================================================================

def test_layer_status_summary_degrades_gracefully():
    summary = layers.layer_status_summary({"knowledge": None, "practical": None, "interview": None})
    assert all(v["status"] == "not_started" and v["score"] is None for v in summary.values())

    summary = layers.layer_status_summary({
        "knowledge": {"status": "completed", "score": 0.82},
        "practical": "garbage",
    })
    assert summary["knowledge"]["score"] == pytest.approx(0.82)
    assert summary["practical"]["status"] == "not_started"
    assert summary["interview"]["status"] == "not_started"


def test_empty_layer_signals_combine_safely():
    assert ps.build_practical_signals([]) == []
    assert interview_mod.build_interview_signals(sessions=[]) == []
    assert interview_mod.build_interview_signals(user_id=None) == []
