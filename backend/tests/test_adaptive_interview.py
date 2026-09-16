"""Tests for the adaptive per-answer interview evaluation (Phase 1).

No real Gemini calls: the LLM is mocked. No Supabase needed: only pure
planning/evaluation/aggregation logic is exercised, plus endpoint routing
via FastAPI dependency overrides.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.assessment import interview as iv
from app.services.assessment import layers
from app.schemas.assessment import AnswerInterviewEvaluation


# ===========================================================================
# Helpers
# ===========================================================================

def _make_question(
    qid: str = "q1",
    skill: str = "Python",
    competency: str = "implementation_reasoning",
    prompt: str = "Walk me through a Python implementation you built.",
) -> Dict[str, Any]:
    return {"id": qid, "skill": skill, "competency": competency, "competency_label": "Implementation reasoning", "prompt": prompt}


def _make_evaluation(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = {
        "question_id": "q1",
        "technical_correctness": 0.80,
        "depth": 0.70,
        "reasoning": 0.85,
        "specificity": 0.75,
        "communication": 0.80,
        "evidence_corroboration": 0.70,
        "contradiction": 0.10,
        "confidence": 0.85,
        "brief_explanation": "Solid walkthrough of the implementation.",
        "follow_up_needed": False,
        "suggested_follow_up": "",
    }
    if overrides:
        base.update(overrides)
    return base


class _FakeLLM:
    """Mock LLM that returns a pre-configured JSON response."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    async def ainvoke(self, _messages):
        self.calls += 1
        class R:
            content = json.dumps(self.payload)
        return R()

    def invoke(self, prompt):
        self.calls += 1
        class R:
            content = json.dumps(self.payload)
        return R()


# ===========================================================================
# 1. Prior snapshot and evidence corroboration
# ===========================================================================

def test_build_prior_snapshot_returns_list():
    """build_prior_snapshot returns a list (never raises without Supabase)."""
    # Without Supabase configured, returns a minimal snapshot
    snapshot = iv.build_prior_snapshot("no-user", "Python")
    assert isinstance(snapshot, list)
    assert len(snapshot) == 1
    assert snapshot[0]["skill"] == "Python"


def test_prior_summary_text_with_empty_snapshot():
    text = iv.prior_summary_text([], "Python")
    assert "no prior evidence" in text
    assert "Python" in text


def test_prior_summary_text_with_snapshot():
    snapshot = [{"skill": "Python", "knowledge_score": 0.85, "practical_score": 0.70,
                 "related_projects": [{"name": "FastAPI App", "technologies": ["Python"]}],
                 "evidence_sources": ["github", "project"]}]
    text = iv.prior_summary_text(snapshot, "Python")
    assert "85%" in text
    assert "70%" in text
    assert "FastAPI App" in text
    assert "github" in text


# ===========================================================================
# 2. Gemini structured evaluation parsing
# ===========================================================================

def test_parse_answer_evaluation_strict_schema():
    raw = json.dumps({
        "technical_correctness": 0.82,
        "depth": 0.70,
        "reasoning": 0.86,
        "specificity": 0.74,
        "communication": 0.80,
        "evidence_corroboration": 0.88,
        "contradiction": 0.05,
        "confidence": 0.84,
        "brief_explanation": "Good answer.",
        "follow_up_needed": True,
        "suggested_follow_up": "Why did you choose that approach?",
    })
    ev = iv.parse_answer_evaluation(raw, "q1")
    assert ev["question_id"] == "q1"
    assert ev["technical_correctness"] == pytest.approx(0.82)
    assert ev["follow_up_needed"] is True
    assert ev["suggested_follow_up"] == "Why did you choose that approach?"
    # Validate with Pydantic schema
    AnswerInterviewEvaluation.model_validate(ev)


def test_parse_answer_evaluation_rejects_garbage():
    with pytest.raises(Exception):
        iv.parse_answer_evaluation("no json here", "q1")
    with pytest.raises(Exception):
        iv.parse_answer_evaluation("[1,2,3]", "q1")
    with pytest.raises(Exception):
        iv.parse_answer_evaluation("", "q1")


def test_parse_answer_evaluation_clamps_out_of_range():
    raw = json.dumps({
        "technical_correctness": 1.5,
        "depth": -0.3,
        "reasoning": 0.8,
        "specificity": 0.7,
        "communication": 0.9,
        "evidence_corroboration": 0.6,
        "contradiction": 0.0,
        "confidence": 0.8,
        "brief_explanation": "OK",
        "follow_up_needed": False,
        "suggested_follow_up": "",
    })
    ev = iv.parse_answer_evaluation(raw, "q1")
    assert ev["technical_correctness"] == 1.0  # clamped
    assert ev["depth"] == 0.0  # clamped


# ===========================================================================
# 3. Per-answer Gemini evaluation (mocked LLM)
# ===========================================================================

def test_evaluate_answer_uses_mocked_llm():
    payload = _make_evaluation()
    ev = asyncio.run(iv.evaluate_answer_llm(
        _make_question(),
        "I built a FastAPI app with SQLAlchemy and pytest.",
        "Python: prior proficiency 0.7",
        [{"id": "implementation_reasoning", "label": "Implementation reasoning"}],
        _llm=_FakeLLM(payload),
    ))
    assert ev["technical_correctness"] == pytest.approx(0.80)
    assert ev["follow_up_needed"] is False


def test_evaluate_answer_with_follow_up():
    payload = _make_evaluation({
        "technical_correctness": 0.35,
        "depth": 0.30,
        "reasoning": 0.40,
        "contradiction": 0.60,
        "confidence": 0.80,
        "follow_up_needed": True,
        "suggested_follow_up": "Can you explain the specific data structure you used?",
    })
    ev = asyncio.run(iv.evaluate_answer_llm(
        _make_question(qid="q2", competency="debugging"),
        "I just used a list.",
        "Python: no prior evidence",
        [{"id": "debugging", "label": "Debugging"}],
        _llm=_FakeLLM(payload),
    ))
    assert ev["follow_up_needed"] is True
    assert "data structure" in ev["suggested_follow_up"]


# ===========================================================================
# 4. Adaptive next-action decisions
# ===========================================================================

def test_decide_next_action_follow_up_on_weak_answer():
    weak = _make_evaluation({
        "technical_correctness": 0.35,
        "depth": 0.30,
        "contradiction": 0.60,
        "confidence": 0.80,
        "follow_up_needed": True,
        "suggested_follow_up": "Explain more.",
    })
    action = iv.decide_next_action(weak, current_index=0, total_planned=4, follow_ups_used=0, questions_answered=1)
    assert action == "follow_up"


def test_decide_next_action_next_on_strong_answer():
    strong = _make_evaluation({
        "technical_correctness": 0.90,
        "depth": 0.85,
        "contradiction": 0.05,
        "confidence": 0.90,
        "follow_up_needed": False,
    })
    action = iv.decide_next_action(strong, current_index=0, total_planned=4, follow_ups_used=0, questions_answered=1)
    assert action == "next"


def test_decide_next_action_complete_at_end():
    strong = _make_evaluation({"follow_up_needed": False})
    action = iv.decide_next_action(strong, current_index=3, total_planned=4, follow_ups_used=0, questions_answered=4)
    assert action == "complete"


def test_decide_next_action_budget_respected():
    weak = _make_evaluation({
        "technical_correctness": 0.30,
        "depth": 0.25,
        "contradiction": 0.70,
        "confidence": 0.85,
        "follow_up_needed": True,
        "suggested_follow_up": "Explain.",
    })
    # At budget limit, even weak answers don't get follow-ups
    action = iv.decide_next_action(weak, current_index=6, total_planned=8, follow_ups_used=4, questions_answered=8)
    assert action == "complete"


def test_decide_next_action_follow_up_budget_capped():
    weak = _make_evaluation({
        "technical_correctness": 0.30,
        "depth": 0.25,
        "contradiction": 0.70,
        "confidence": 0.85,
        "follow_up_needed": True,
        "suggested_follow_up": "Explain.",
    })
    # Max follow-ups used: should advance instead
    action = iv.decide_next_action(weak, current_index=2, total_planned=4, follow_ups_used=4, questions_answered=6)
    assert action == "next"


def test_decide_next_action_no_follow_up_without_suggested():
    weak = _make_evaluation({
        "technical_correctness": 0.30,
        "depth": 0.25,
        "contradiction": 0.70,
        "confidence": 0.85,
        "follow_up_needed": True,
        "suggested_follow_up": "",  # No suggested question
    })
    action = iv.decide_next_action(weak, current_index=0, total_planned=4, follow_ups_used=0, questions_answered=1)
    assert action == "next"  # Cannot follow up without a suggested question


def test_decide_next_action_no_follow_up_on_low_confidence():
    weak = _make_evaluation({
        "technical_correctness": 0.30,
        "depth": 0.25,
        "contradiction": 0.70,
        "confidence": 0.30,  # Low confidence in the grading
        "follow_up_needed": True,
        "suggested_follow_up": "Explain.",
    })
    action = iv.decide_next_action(weak, current_index=0, total_planned=4, follow_ups_used=0, questions_answered=1)
    assert action == "next"  # Don't follow up when Gemini is unsure


# ===========================================================================
# 5. Signal strength from per-answer evaluation
# ===========================================================================

def test_signal_strength_weights_technical():
    strong = _make_evaluation({
        "technical_correctness": 0.95,
        "depth": 0.85,
        "reasoning": 0.90,
        "specificity": 0.80,
        "contradiction": 0.0,
        "confidence": 0.90,
    })
    weak = _make_evaluation({
        "technical_correctness": 0.20,
        "depth": 0.15,
        "reasoning": 0.25,
        "specificity": 0.20,
        "contradiction": 0.70,
        "confidence": 0.80,
    })
    assert iv.signal_strength_from_answer_evaluation(strong) > 0.6
    assert iv.signal_strength_from_answer_evaluation(weak) < 0.30


def test_signal_strength_scales_by_confidence():
    mid = _make_evaluation({
        "technical_correctness": 0.70,
        "depth": 0.60,
        "reasoning": 0.65,
        "specificity": 0.55,
        "contradiction": 0.10,
        "confidence": 0.50,
    })
    high_conf = dict(mid, confidence=0.95)
    low_conf = dict(mid, confidence=0.20)
    assert iv.signal_strength_from_answer_evaluation(high_conf) > iv.signal_strength_from_answer_evaluation(low_conf)


# ===========================================================================
# 6. Follow-up question generation (mocked LLM)
# ===========================================================================

def test_generate_follow_up_uses_suggested_when_available():
    """When the evaluation includes a suggested_follow_up, use it directly."""
    ev = _make_evaluation({
        "follow_up_needed": True,
        "suggested_follow_up": "Why did you choose vector search over keyword matching?",
    })
    fu = asyncio.run(iv.generate_follow_up_question(
        _make_question(), "I used vector search.", ev, _llm=_FakeLLM({})
    ))
    assert fu == "Why did you choose vector search over keyword matching?"


def test_generate_follow_up_calls_llm_when_no_suggested():
    """When no suggested_follow_up, LLM generates one."""
    llm_payload = {"follow_up": "Can you explain the caching layer in more detail?"}
    ev = _make_evaluation({
        "follow_up_needed": True,
        "technical_correctness": 0.40,
        "depth": 0.35,
        "suggested_follow_up": "",
    })
    fu = asyncio.run(iv.generate_follow_up_question(
        _make_question(), "I used Redis.", ev, _llm=_FakeLLM(llm_payload)
    ))
    assert fu == "Can you explain the caching layer in more detail?"


def test_generate_follow_up_fallback_on_llm_failure():
    """When LLM fails, a fallback question is generated based on weak dimensions."""
    ev = _make_evaluation({
        "follow_up_needed": True,
        "technical_correctness": 0.30,
        "depth": 0.25,
        "suggested_follow_up": "",
    })
    # LLM that raises
    class _FailLLM:
        async def ainvoke(self, _):
            raise RuntimeError("API error")
    fu = asyncio.run(iv.generate_follow_up_question(
        _make_question(), "Something.", ev, _llm=_FailLLM()
    ))
    assert fu is not None  # Fallback question generated
    assert len(fu) > 0


# ===========================================================================
# 7. Integration: evaluate + decide + follow-up
# ===========================================================================

def test_full_adaptive_cycle_weak_answer():
    """Weak answer -> follow_up decision -> follow-up question generated."""
    ev_payload = _make_evaluation({
        "technical_correctness": 0.35,
        "depth": 0.30,
        "reasoning": 0.40,
        "contradiction": 0.55,
        "confidence": 0.80,
        "follow_up_needed": True,
        "suggested_follow_up": "Can you explain the error handling approach?",
    })
    ev = asyncio.run(iv.evaluate_answer_llm(
        _make_question(), "I just used try/except.",
        "Python: no prior evidence",
        [{"id": "implementation_reasoning", "label": "Implementation reasoning"}],
        _llm=_FakeLLM(ev_payload),
    ))
    action = iv.decide_next_action(ev, current_index=0, total_planned=4, follow_ups_used=0, questions_answered=1)
    assert action == "follow_up"
    fu = asyncio.run(iv.generate_follow_up_question(
        _make_question(), "I just used try/except.", ev, _llm=_FakeLLM(ev_payload)
    ))
    assert fu is not None
    assert "error handling" in fu.lower() or "explain" in fu.lower()


def test_full_adaptive_cycle_strong_answer():
    """Strong answer -> next decision -> no follow-up needed."""
    ev_payload = _make_evaluation({
        "technical_correctness": 0.92,
        "depth": 0.88,
        "reasoning": 0.90,
        "contradiction": 0.02,
        "confidence": 0.92,
        "follow_up_needed": False,
    })
    ev = asyncio.run(iv.evaluate_answer_llm(
        _make_question(), "I implemented a full pipeline with error handling and retry logic.",
        "Python: prior proficiency 0.8",
        [{"id": "implementation_reasoning", "label": "Implementation reasoning"}],
        _llm=_FakeLLM(ev_payload),
    ))
    action = iv.decide_next_action(ev, current_index=0, total_planned=4, follow_ups_used=0, questions_answered=1)
    assert action == "next"


# ===========================================================================
# 8. Interview version and constants
# ===========================================================================

def test_interview_version_updated():
    assert iv.INTERVIEW_VERSION == "interview-v2"


def test_adaptive_constants_defined():
    assert iv.INTERVIEW_MAX_FOLLOW_UPS == 4
    assert iv.INTERVIEW_TOTAL_BUDGET == 8


# ===========================================================================
# 9. Backward compatibility: existing functions still work
# ===========================================================================

def test_existing_competencies_unchanged():
    comps = iv.competencies_for_skill("Python")
    comp_ids = {c["id"] for c in comps}
    assert "implementation_reasoning" in comp_ids
    assert "debugging" in comp_ids


def test_existing_plan_building_unchanged():
    plan = iv.build_interview_plan("Python", knowledge_score=0.5, practical_score=0.3)
    assert iv.validate_plan(plan) == []
    assert len(plan["questions"]) == 4
    # Plan still has competencies
    comp_ids = {c["id"] for c in plan["competencies"]}
    for q in plan["questions"]:
        assert q["competency"] in comp_ids


def test_existing_batch_grading_still_works(monkeypatch):
    """grade_interview_transcript still works for the batch path."""
    class _Msg:
        content = (
            '{"technical": {"implementation_reasoning": 0.8, "python_specifics": 0.6, '
            '"debugging": 0.7, "design_decisions": 0.5, "explanation": 0.9}, '
            '"communication": {"clarity": 0.9, "relevance": 0.8, "structure": 0.7, '
            '"justification": 0.6, "follow_ups": 0.5}}'
        )

    class _FakeBatchLLM:
        def invoke(self, prompt):
            return _Msg()

    monkeypatch.setattr(iv, "_make_interview_llm", lambda: _FakeBatchLLM())
    grades = iv.grade_interview_transcript(
        "Python", iv.competencies_for_skill("Python"),
        [{"competency": "implementation_reasoning", "prompt": "Q", "answer": "A"}],
    )
    assert set(grades["technical"]) == {c["id"] for c in iv.competencies_for_skill("Python")}
    assert all(0.0 <= v <= 1.0 for v in grades["technical"].values())


def test_existing_interview_signals_unchanged():
    """build_interview_signals still works with the existing schema."""
    sessions = [{
        "id": "s-1", "skill_name": "Python",
        "technical_scores": {"overall": 0.7, "per_competency": {}},
        "interview_version": iv.INTERVIEW_VERSION,
        "completed_at": "2026-01-01T00:00:00+00:00",
    }]
    signals = iv.build_interview_signals(sessions=sessions)
    assert len(signals) == 1
    assert float(signals[0].get("signal_strength", signals[0].get("signal_value", 0))) == pytest.approx(0.7)


# ===========================================================================
# 10. Schema validation
# ===========================================================================

def test_answer_interview_evaluation_schema():
    ev = AnswerInterviewEvaluation(
        question_id="q1",
        technical_correctness=0.82,
        depth=0.70,
        reasoning=0.86,
        specificity=0.74,
        communication=0.80,
        evidence_corroboration=0.88,
        contradiction=0.05,
        confidence=0.84,
        brief_explanation="Good answer.",
        follow_up_needed=True,
        suggested_follow_up="Why?",
    )
    assert ev.question_id == "q1"
    assert ev.technical_correctness == pytest.approx(0.82)
    assert ev.follow_up_needed is True


# ===========================================================================
# 11. Endpoint routing
# ===========================================================================

def test_assessment_routes_include_answer_endpoint():
    from app.api.v1.endpoints.assessment import router
    paths = sorted({r.path for r in router.routes})
    assert "/analysis/assessment/interview/{session_id}/answer" in paths
    # Existing routes still present
    assert "/analysis/assessment/interview/start" in paths
    assert "/analysis/assessment/interview/complete" in paths
    assert "/analysis/assessment/interview/respond" in paths


# ===========================================================================
# 12. Contradiction / corroboration language
# ===========================================================================

def test_contradiction_language_never_accuses():
    """The mock interview's detect_contradiction is reused; verify it doesn't accuse."""
    from app.services import mock_interview_service as mock_svc
    verdict, text = mock_svc.detect_contradiction(0.8, 0.2)
    assert verdict == "requires_further_validation"
    assert "lying" not in text.lower()


def test_evidence_corroboration_in_evaluation():
    """High corroboration when answer aligns with prior evidence."""
    ev = _make_evaluation({"evidence_corroboration": 0.90, "contradiction": 0.05})
    assert ev["evidence_corroboration"] > 0.80
    assert ev["contradiction"] < 0.10


def test_contradiction_flag_in_evaluation():
    """High contradiction when answer conflicts with prior evidence."""
    ev = _make_evaluation({
        "evidence_corroboration": 0.20,
        "contradiction": 0.75,
        "technical_correctness": 0.30,
        "depth": 0.25,
        "reasoning": 0.30,
        "specificity": 0.25,
        "confidence": 0.80,
    })
    assert ev["contradiction"] > 0.50
    # Signal strength penalizes contradiction heavily
    sig = iv.signal_strength_from_answer_evaluation(ev)
    assert sig < 0.35  # Low scores + high contradiction = weak signal


# ---------------------------------------------------------------------------
# Bug fix regression tests
# ---------------------------------------------------------------------------

def test_answer_wrong_question_returns_409():
    """Bug 3 fix: answering a question not at current_index returns 409."""
    from fastapi import HTTPException

    q0 = {"id": "q0", "prompt": "P0", "competency": "c1"}
    q1 = {"id": "q1", "prompt": "P1", "competency": "c2"}
    session = {
        "id": "s1", "user_id": "user1", "skill_name": "python",
        "status": "in_progress", "interview_version": iv.INTERVIEW_VERSION,
        "transcript": [
            {"role": "assistant", "content": "P0", "question_id": "q0"},
            {"role": "assistant", "content": "P1", "question_id": "q1"},
        ],
        "evaluation_results": [],
        "plan": {"questions": [q0, q1], "competencies": ["c1", "c2"], "prior_snapshot": []},
        "current_index": 0,
    }

    mock_update = MagicMock()
    mock_update.execute.return_value = MagicMock(data=[session])
    mock_c = MagicMock()
    mock_c.table.return_value.update.return_value.eq.return_value.eq.return_value = mock_update

    with patch("app.services.assessment.interview._client", return_value=mock_c):
        with patch("app.services.assessment.interview._load_session", return_value=session):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(iv.answer_interview_question(
                    "user1", "s1", "q1", "Answer for q1"
                ))
            assert exc_info.value.status_code == 409
            assert "not the current question" in str(exc_info.value.detail)


def test_follow_up_inserted_at_correct_position():
    """Bug 2 fix: follow-up is inserted at current_index + 1, not at end."""
    q0 = {"id": "q0", "prompt": "P0", "competency": "c1"}
    q1 = {"id": "q1", "prompt": "P1", "competency": "c2"}
    competencies = [{"id": "c1", "label": "C1"}, {"id": "c2", "label": "C2"}]
    session = {
        "id": "s1", "user_id": "user1", "skill_name": "python",
        "status": "in_progress", "interview_version": iv.INTERVIEW_VERSION,
        "transcript": [
            {"role": "assistant", "content": "P0", "question_id": "q0"},
            {"role": "assistant", "content": "P1", "question_id": "q1"},
        ],
        "evaluation_results": [],
        "plan": {"questions": [q0, q1], "competencies": competencies, "prior_snapshot": []},
        "current_index": 0,
    }

    weak_ev = {
        "technical_correctness": 0.20, "depth": 0.15, "reasoning": 0.20,
        "specificity": 0.10, "communication": 0.50, "confidence": 0.70,
        "follow_up_needed": True, "evidence_corroboration": 0.30,
        "contradiction": 0.10, "suggested_follow_up": "Why?",
    }

    mock_exec = MagicMock()
    mock_exec.execute.return_value = MagicMock(data=[session])
    mock_eq2 = MagicMock()
    mock_eq2.eq.return_value = mock_exec
    mock_eq1 = MagicMock()
    mock_eq1.eq.return_value = mock_eq2
    mock_update = MagicMock()
    mock_update.update.return_value = mock_eq1
    mock_c = MagicMock()
    mock_c.table.return_value = mock_update

    with patch("app.services.assessment.interview._client", return_value=mock_c):
        with patch("app.services.assessment.interview._load_session", return_value=session):
            with patch("app.services.assessment.interview.evaluate_answer_llm", new_callable=AsyncMock, return_value=weak_ev):
                with patch("app.services.assessment.interview.generate_follow_up_question", new_callable=AsyncMock, return_value="Why did you do that?"):
                    resp = asyncio.run(iv.answer_interview_question(
                        "user1", "s1", "q0", "Weak answer"
                    ))

    # Follow-up should be the current question (index 1, right after q0)
    nq = resp.get("current_question") or {}
    assert nq.get("id") == "q0_followup_1"
    assert nq.get("competency") == "c1_followup"
    assert resp.get("action") == "FOLLOW_UP"
    assert resp.get("spoken_response") is not None
    assert "Why did you do that?" in resp["spoken_response"]
    # The persisted plan should have the follow-up inserted between q0 and q1
    update_call = mock_update.update.call_args
    saved_plan = update_call[0][0].get("plan")
    assert saved_plan is not None, "Plan must be saved when follow-up is inserted"
    qs = saved_plan["questions"]
    assert len(qs) == 3
    assert qs[0]["id"] == "q0"
    assert qs[1]["id"] == "q0_followup_1"  # Follow-up at position 1
    assert qs[2]["id"] == "q1"  # Original q1 at position 2


def test_follow_up_plan_persisted_to_db():
    """Bug 1 fix: plan with follow-up is always persisted (not dead code)."""
    q0 = {"id": "q0", "prompt": "P0", "competency": "c1"}
    competencies = [{"id": "c1", "label": "C1"}]
    session = {
        "id": "s1", "user_id": "user1", "skill_name": "python",
        "status": "in_progress", "interview_version": iv.INTERVIEW_VERSION,
        "transcript": [{"role": "assistant", "content": "P0", "question_id": "q0"}],
        "evaluation_results": [],
        "plan": {"questions": [q0], "competencies": competencies, "prior_snapshot": []},
        "current_index": 0,
    }

    weak_ev = {
        "technical_correctness": 0.20, "depth": 0.15, "reasoning": 0.20,
        "specificity": 0.10, "communication": 0.50, "confidence": 0.70,
        "follow_up_needed": True, "evidence_corroboration": 0.30,
        "contradiction": 0.10, "suggested_follow_up": "Explain more.",
    }

    mock_exec = MagicMock()
    mock_exec.execute.return_value = MagicMock(data=[session])
    mock_eq2 = MagicMock()
    mock_eq2.eq.return_value = mock_exec
    mock_eq1 = MagicMock()
    mock_eq1.eq.return_value = mock_eq2
    mock_update = MagicMock()
    mock_update.update.return_value = mock_eq1
    mock_c = MagicMock()
    mock_c.table.return_value = mock_update

    with patch("app.services.assessment.interview._client", return_value=mock_c):
        with patch("app.services.assessment.interview._load_session", return_value=session):
            with patch("app.services.assessment.interview.evaluate_answer_llm", new_callable=AsyncMock, return_value=weak_ev):
                with patch("app.services.assessment.interview.generate_follow_up_question", new_callable=AsyncMock, return_value="Explain more."):
                    asyncio.run(iv.answer_interview_question(
                        "user1", "s1", "q0", "Weak"
                    ))

    # The update call must include "plan" in its payload
    update_call = mock_update.update.call_args
    update_payload = update_call[0][0]
    assert "plan" in update_payload, "Plan must be persisted when follow-up is generated"
    saved_plan = update_payload["plan"]
    assert len(saved_plan["questions"]) == 2
    assert saved_plan["questions"][1]["_is_follow_up"] is True
