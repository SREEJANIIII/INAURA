"""Regression tests: the interview must never end after Q1.

Root cause (fixed): the live plan intentionally contains only Q1, so after
answering Q1 with no usable Gemini next-question, the answer endpoint
returned next_action="next" with current_question=None — and the frontend
treated a missing current_question as completion. The backend now inserts a
deterministic coverage question whenever a non-terminal turn would otherwise
have no next question, and the frontend only completes on the server's
explicit terminal state.

Covers the required invariant:
  questions_answered < 4  -> NEVER complete (unless explicit end intent)
  questions_answered >= 4 AND interview_sufficient -> complete
  questions_answered >= 8 -> complete
  otherwise -> generate/return the next question

No real Gemini calls, no Supabase: evaluate_answer_llm and persistence are
mocked following the pattern in test_adaptive_interview.py.
"""

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.assessment import interview as iv


COMPETENCIES = [
    {"id": "c1", "label": "C1"},
    {"id": "c2", "label": "C2"},
    {"id": "c3", "label": "C3"},
]


def _base_eval(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A real (non-recovery) evaluation with NO usable next question."""
    base = {
        "technical_correctness": 0.70,
        "depth": 0.65,
        "reasoning": 0.70,
        "specificity": 0.60,
        "communication": 0.75,
        "evidence_corroboration": 0.60,
        "contradiction": 0.05,
        "confidence": 0.80,
        "brief_explanation": "Adequate answer.",
        "follow_up_needed": False,
        "suggested_follow_up": "",
        "spoken_response": "I see.",
        "next_question": "",
        "next_question_reason": "",
        "target_competency": "",
        "question_type": "",
        "interview_sufficient": False,
        "demonstrated": [],
        "missing": [],
        "misconceptions": [],
    }
    if overrides:
        base.update(overrides)
    return base


def _make_session(
    qids: List[str],
    answered: int,
    eval_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Session with len(qids) planned questions, `answered` real evals."""
    questions = [
        {"id": qid, "prompt": f"Prompt for {qid}?", "competency": COMPETENCIES[i % 3]["id"], "follow_ups": []}
        for i, qid in enumerate(qids)
    ]
    evals = [
        {
            "question_id": qids[i],
            "competency": questions[i]["competency"],
            "evaluation": _base_eval(eval_overrides),
            "transcript_hash": f"hash-{i}",
        }
        for i in range(answered)
    ]
    return {
        "id": "s1",
        "user_id": "user1",
        "skill_name": "Python",
        "status": "in_progress",
        "interview_version": iv.INTERVIEW_VERSION,
        "transcript": [],
        "evaluation_results": evals,
        "plan": {"questions": questions, "competencies": COMPETENCIES, "prior_snapshot": []},
        "current_index": answered,
        "prior_snapshot": [],
    }


def _mock_client():
    mock_exec = MagicMock()
    mock_exec.execute.return_value = MagicMock(data=[])
    mock_eq2 = MagicMock()
    mock_eq2.eq.return_value = mock_exec
    mock_eq1 = MagicMock()
    mock_eq1.eq.return_value = mock_eq2
    mock_update = MagicMock()
    mock_update.update.return_value = mock_eq1
    mock_c = MagicMock()
    mock_c.table.return_value = mock_update
    return mock_c, mock_update


def _answer(session: Dict[str, Any], evaluation: Dict[str, Any], transcript: str = "I built a service with retries and caching for our API."):
    """Run one answer turn against a mocked session; return (response, update_payload)."""
    mock_c, mock_update = _mock_client()
    qid = session["plan"]["questions"][session["current_index"]]["id"]
    with patch("app.services.assessment.interview._client", return_value=mock_c):
        with patch("app.services.assessment.interview._load_session", return_value=session):
            with patch("app.services.assessment.interview.evaluate_answer_llm", new_callable=AsyncMock, return_value=evaluation):
                resp = asyncio.run(iv.answer_interview_question("user1", "s1", qid, transcript))
    update_payload = mock_update.update.call_args[0][0]
    return resp, update_payload


# 1. Initial plan contains only Q1.
def test_initial_plan_contains_only_q1():
    plan = iv.build_interview_plan("Python", knowledge_score=0.5, practical_score=0.3)
    assert iv.validate_plan(plan) == []
    assert len(plan["questions"]) == 1
    assert plan["questions"][0]["id"] == "q1"


# 2. Answering Q1 always continues to Q2 (no usable Gemini question).
def test_q1_answer_continues_to_q2():
    session = _make_session(["q1"], answered=0)
    resp, update = _answer(session, _base_eval())
    assert resp["completed"] is False
    assert resp["next_action"] == "next"
    assert resp["current_question"] is not None
    assert resp["answered_count"] == 1
    assert resp["total_questions"] == 2
    saved = update.get("plan")
    assert saved is not None
    assert len(saved["questions"]) == 2


# 3. Gemini interview_sufficient=true after Q1 -> still continue.
def test_q1_sufficient_true_still_continues():
    session = _make_session(["q1"], answered=0)
    resp, _ = _answer(session, _base_eval({"interview_sufficient": True}))
    assert resp["completed"] is False
    assert resp["next_action"] in ("next", "follow_up")
    assert resp["current_question"] is not None


# 4. Q2 continues to Q3.
def test_q2_continues_to_q3():
    session = _make_session(["q1", "q2_coverage"], answered=1)
    resp, update = _answer(session, _base_eval())
    assert resp["completed"] is False
    assert resp["next_action"] == "next"
    assert resp["current_question"] is not None
    assert resp["answered_count"] == 2
    assert resp["total_questions"] == 3


# 5. Q3 continues to Q4.
def test_q3_continues_to_q4():
    session = _make_session(["q1", "q2_coverage", "q3_coverage"], answered=2)
    resp, _ = _answer(session, _base_eval())
    assert resp["completed"] is False
    assert resp["current_question"] is not None
    assert resp["answered_count"] == 3


# 6. Q4 + interview_sufficient=true -> complete.
def test_q4_sufficient_true_completes():
    session = _make_session(["q1", "q2_coverage", "q3_coverage", "q4_coverage"], answered=3)
    resp, _ = _answer(session, _base_eval({"interview_sufficient": True}))
    assert resp["completed"] is True
    assert resp["next_action"] == "complete"
    assert resp["current_question"] is None


# 7. Q4 + interview_sufficient=false -> continue.
def test_q4_sufficient_false_continues():
    session = _make_session(["q1", "q2_coverage", "q3_coverage", "q4_coverage"], answered=3)
    resp, _ = _answer(session, _base_eval({"interview_sufficient": False}))
    assert resp["completed"] is False
    assert resp["current_question"] is not None
    assert resp["answered_count"] == 4
    assert resp["total_questions"] == 5


# 8. Q8 -> complete (even with a valid Gemini next question and no sufficiency).
def test_q8_always_completes():
    qids = ["q1"] + [f"q{i}_coverage" for i in range(2, 9)]
    session = _make_session(qids, answered=7)
    resp, _ = _answer(
        session,
        _base_eval({
            "interview_sufficient": False,
            "next_question": "You mentioned caching with Redis. How did you choose the TTL and handle stale reads?",
            "next_question_reason": "verify the caching claim",
            "target_competency": "c2",
            "question_type": "verify",
            "confidence": 0.9,
        }),
    )
    assert resp["completed"] is True
    assert resp["next_action"] == "complete"
    assert resp["answered_count"] == 8


# 9. Explicit end after Q1 -> complete.
def test_explicit_end_after_q1_completes():
    session = _make_session(["q1"], answered=0)
    mock_c, _ = _mock_client()
    with patch("app.services.assessment.interview._client", return_value=mock_c):
        with patch("app.services.assessment.interview._load_session", return_value=session):
            resp = asyncio.run(iv.answer_interview_question(
                "user1", "s1", "q1", "I want to stop. Please end interview here."
            ))
    assert resp["completed"] is True
    assert resp["next_action"] == "complete"
    assert resp.get("conversation_intent") == "end_interview"


# 10. Non-terminal control language must NOT end a single-question interview.
def test_repetition_complaint_after_q1_does_not_end():
    session = _make_session(["q1"], answered=0)
    mock_c, _ = _mock_client()
    with patch("app.services.assessment.interview._client", return_value=mock_c):
        with patch("app.services.assessment.interview._load_session", return_value=session):
            resp = asyncio.run(iv.answer_interview_question(
                "user1", "s1", "q1", "You are repeating the question, you already asked this."
            ))
    assert resp["completed"] is False
    assert resp["current_question"] is not None


# Provider-outage path: evaluation=None must still continue after Q1.
def test_q1_provider_outage_still_continues():
    import fastapi

    session = _make_session(["q1"], answered=0)

    async def _outage(*args, **kwargs):
        raise fastapi.HTTPException(status_code=503, detail={"message": "no provider"})

    mock_c, _ = _mock_client()
    with patch("app.services.assessment.interview._client", return_value=mock_c):
        with patch("app.services.assessment.interview._load_session", return_value=session):
            with patch("app.services.assessment.interview.evaluate_answer_llm", side_effect=_outage):
                resp = asyncio.run(iv.answer_interview_question(
                    "user1", "s1", "q1", "I built a service with retries and caching for our API."
                ))
    assert resp["completed"] is False
    assert resp["current_question"] is not None


def test_coverage_fallback_targets_untested_competency():
    questions = [{"id": "q1", "prompt": "Prompt q1?", "competency": "c1", "follow_ups": []}]
    q = iv._coverage_fallback_question(questions, COMPETENCIES, "Python", 0, questions[0])
    assert q is not None
    assert q["competency"] in ("c2", "c3")
    assert q["prompt"].strip().endswith("?")
    assert iv.validate_next_question(
        {"next_question": q["prompt"], "target_competency": q["competency"]},
        COMPETENCIES, ["Prompt q1?"], "some answer text",
    ) is not None


def test_coverage_fallback_refuses_over_cap():
    questions = [
        {"id": f"q{i}", "prompt": f"Prompt {i}?", "competency": "c1", "follow_ups": []}
        for i in range(8)
    ]
    assert iv._coverage_fallback_question(questions, COMPETENCIES, "Python", 7) is None
