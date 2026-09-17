"""Answer-adaptive next-question generation (single Gemini call).

Proves the chain CURRENT ANSWER -> GEMINI EVALUATION -> NEXT-QUESTION
DECISION -> SPECIFIC NEXT QUESTION using mocked LLMs and mocked
persistence. No real Gemini calls, no Supabase needed.
"""

import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from app.services.assessment import interview as iv


COMPS = [
    {"id": "implementation_reasoning", "label": "Implementation reasoning"},
    {"id": "debugging", "label": "Debugging"},
    {"id": "explanation", "label": "Clear technical explanation"},
]

Q1_PROMPT = "Explain polymorphism in Java."


def _question(qid="q1", prompt=Q1_PROMPT, competency="implementation_reasoning"):
    return {"id": qid, "skill": "Java", "competency": competency,
            "competency_label": "Implementation reasoning", "prompt": prompt}


def _eval_payload(overrides=None):
    base = {
        "question_id": "q1",
        "technical_correctness": 0.5, "depth": 0.5, "reasoning": 0.5,
        "specificity": 0.5, "communication": 0.6,
        "evidence_corroboration": 0.5, "contradiction": 0.1, "confidence": 0.8,
        "brief_explanation": "An answer.",
        "follow_up_needed": False, "suggested_follow_up": "",
        "next_question": "", "next_question_reason": "",
        "target_competency": "", "question_type": "probe",
        "demonstrated": [], "missing": [], "misconceptions": [],
    }
    if overrides:
        base.update(overrides)
    return base


class _FakeLLM:
    """Mock LLM returning canned JSON; records prompts and call count."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0
        self.prompts: List[str] = []

    async def ainvoke(self, messages):
        self.calls += 1
        self.prompts.append(json.dumps(messages)[:6000])
        content = json.dumps(self.payload)

        class R:
            pass
        r = R()
        r.content = content
        return r


# ===========================================================================
# 1. Extended evaluation parsing (backward compatible)
# ===========================================================================

def test_parse_keeps_new_adaptive_fields():
    ev = iv.parse_answer_evaluation(json.dumps(_eval_payload({
        "next_question": "How is runtime polymorphism achieved?",
        "next_question_reason": "Answer missed overriding.",
        "target_competency": "implementation_reasoning",
        "question_type": "probe",
        "demonstrated": ["definition"],
        "missing": ["method overriding"],
        "misconceptions": [],
    })), "q1")
    assert ev["next_question"] == "How is runtime polymorphism achieved?"
    assert ev["target_competency"] == "implementation_reasoning"
    assert ev["question_type"] == "probe"
    assert ev["demonstrated"] == ["definition"]
    assert ev["missing"] == ["method overriding"]


def test_parse_old_shape_defaults_adaptive_fields():
    raw = json.dumps({"technical_correctness": 0.7, "follow_up_needed": False})
    ev = iv.parse_answer_evaluation(raw, "q1")
    assert ev["next_question"] == ""
    assert ev["target_competency"] == ""
    assert ev["question_type"] == ""
    assert ev["demonstrated"] == []
    # Legacy field preserved.
    assert "suggested_follow_up" in ev


def test_evaluate_single_call_returns_scores_and_next_question():
    llm = _FakeLLM(_eval_payload({"next_question": "Probe?", "target_competency": "debugging"}))
    ev = asyncio.run(iv.evaluate_answer_llm(
        _question(), "An answer.", "Java: no prior evidence", COMPS,
        _llm=llm, adaptive_context="budget: 7",
    ))
    assert llm.calls == 1  # exactly ONE Gemini call
    assert ev["technical_correctness"] == 0.5
    assert ev["next_question"] == "Probe?"
    assert "budget: 7" in llm.prompts[0]


# ===========================================================================
# 2. PART 20 — same Q1, different answers -> different next questions
# ===========================================================================

def _select(prompt_answer_next: str, comp: str = "implementation_reasoning"):
    plan_qs = [
        {"id": "q1", "competency": comp, "prompt": Q1_PROMPT, "follow_ups": []},
        {"id": "q2", "competency": "debugging", "prompt": "What are the main principles of OOP?", "follow_ups": []},
    ]
    ev = iv.parse_answer_evaluation(json.dumps(_eval_payload({
        "next_question": prompt_answer_next, "target_competency": comp,
    })), "q1")
    return iv.select_adaptive_insertion(ev, plan_qs, 0, COMPS, current_competency=comp)


def test_weak_answer_yields_targeted_probe_not_generic_q2():
    ins = _select("You described polymorphism as having many forms. Can you explain "
                  "how runtime polymorphism is achieved through method overriding?")
    assert ins is not None
    assert "overriding" in ins["prompt"].lower()
    assert ins["prompt"] != "What are the main principles of OOP?"


def test_strong_answer_yields_deeper_question():
    ins = _select("How does dynamic method dispatch determine which implementation "
                  "runs at runtime, and what limitations apply to static methods?",
                  comp="implementation_reasoning")
    assert ins is not None
    assert "dispatch" in ins["prompt"].lower()
    assert "definition" not in ins["prompt"].lower()


def test_project_answer_yields_project_specific_question():
    ins = _select("You mentioned using FastAPI for your prediction endpoint. How did "
                  "you handle validation and what would happen if the model service "
                  "became slow or unavailable?")
    assert ins is not None
    assert "fastapi" in ins["prompt"].lower()


def test_duplicate_of_planned_question_falls_back():
    ins = _select("What are the main principles of OOP?")
    assert ins is None  # rejected -> deterministic fallback must be used


def test_invalid_target_competency_falls_back_to_current():
    plan_qs = [{"id": "q1", "competency": "debugging", "prompt": Q1_PROMPT, "follow_ups": []}]
    ev = iv.parse_answer_evaluation(json.dumps(_eval_payload({
        "next_question": "How would you debug a race condition in this code?",
        "target_competency": "not_a_real_competency",
    })), "q1")
    ins = iv.select_adaptive_insertion(ev, plan_qs, 0, COMPS, current_competency="debugging")
    assert ins is not None
    assert ins["competency"] == "debugging"


def test_budget_cap_disables_insertion():
    plan_qs = [{"id": f"q{i}", "competency": "debugging", "prompt": f"Planned question {i}?",
                "follow_ups": []} for i in range(8)]
    ev = iv.parse_answer_evaluation(json.dumps(_eval_payload({
        "next_question": "A perfectly good adaptive probe question here?",
    })), "q1")
    assert iv.select_adaptive_insertion(ev, plan_qs, 0, COMPS) is None


# ===========================================================================
# 3. Adaptive state + context (PARTs 3-4)
# ===========================================================================

def test_adaptive_state_tracks_demonstrated_and_weak():
    transcript = [
        {"question_id": "q1", "competency": "implementation_reasoning",
         "prompt": "Explain inheritance.", "answer": "A subclass inherits fields."},
    ]
    evals = [{"question_id": "q1", "competency": "implementation_reasoning",
              "evaluation": _eval_payload({"demonstrated": ["inheritance basics"],
                                           "missing": ["method overriding"]})}]
    state = iv.summarize_adaptive_state(transcript, evals)
    assert "inheritance basics" in state["demonstrated"]
    assert "method overriding" in state["weak"]
    assert "implementation_reasoning" in state["tested_competencies"]


def test_context_is_bounded_and_includes_history():
    transcript = [
        {"question_id": f"q{i}", "competency": "debugging",
         "prompt": f"Question {i} " + ("x" * 500),
         "answer": f"Answer {i} " + ("y" * 500)} for i in range(6)
    ]
    ctx = iv.build_adaptive_context("Python", transcript, [], COMPS, ["MirrorVibes"], 5)
    assert len(ctx) <= 2500
    assert "MirrorVibes" in ctx
    assert "Answer 5" in ctx  # most recent kept
    assert "Answer 0" not in ctx  # old detail compacted away


# ===========================================================================
# 4. Locked-flow integration with mocked persistence (PARTs 21-22)
# ===========================================================================

class _FakeTable:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self._rows: List[dict] = []

    def _reset(self):
        self._rows = []
        return self

    def select(self, *a, **k): return self
    def insert(self, row): self._pending = ("insert", row); return self
    def update(self, row): self._pending = ("update", row); return self
    def delete(self): self._pending = ("delete", None); return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def order(self, *a, **k): return self

    def execute(self):
        op = getattr(self, "_pending", None)
        if op and op[0] == "update" and self.client.session is not None:
            self.client.session.update(op[1])
        m = MagicMock()
        m.data = []
        return m


class _FakeClient:
    def __init__(self, session):
        self.session = session

    def table(self, name):
        return _FakeTable(self, name)


def _session_row():
    return {
        "id": "sess-1", "user_id": "u1", "skill_name": "Java",
        "status": "in_progress", "current_index": 0,
        "plan": {
            "competencies": COMPS,
            "related_projects": ["MirrorVibes"],
            "questions": [
                {"id": "q1", "competency": "implementation_reasoning",
                 "prompt": Q1_PROMPT, "follow_ups": []},
                {"id": "q2", "competency": "debugging",
                 "prompt": "What are the main principles of OOP?", "follow_ups": []},
            ],
        },
        "transcript": [],
        "evaluation_results": [],
        "prior_snapshot": [],
    }


def _run_locked(session, question_id, answer, llm):
    fake = _FakeClient(session)
    with patch.object(iv, "_client", return_value=fake), \
         patch.object(iv, "_load_session", return_value=session), \
         patch.object(iv, "_claim_answer", return_value=("claimed", None)), \
         patch.object(iv, "_finish_answer_claim", return_value=None), \
         patch.object(iv, "_release_answer_claim", return_value=None):
        return asyncio.run(iv._answer_interview_question_locked(
            "u1", "sess-1", question_id, answer, _llm=llm))


def test_locked_flow_speaks_gemini_derived_followup_not_planned_q2():
    session = _session_row()
    llm = _FakeLLM(_eval_payload({
        "technical_correctness": 0.35, "depth": 0.3, "confidence": 0.8,
        "follow_up_needed": True,
        "suggested_follow_up": "Fallback probe?",
        "next_question": "You described polymorphism as having many forms. Can you "
                         "explain how runtime polymorphism works via overriding?",
        "next_question_reason": "Answer missed overriding.",
        "target_competency": "implementation_reasoning",
        "question_type": "probe",
    }))
    res = _run_locked(session, "q1", "Polymorphism means many forms.", llm)
    assert llm.calls == 1  # single Gemini call for eval + next question
    assert res["is_adaptive"] is True
    assert res["current_question"] is not None
    assert "overriding" in res["current_question"]["prompt"].lower()
    assert res["current_question"]["prompt"] != "What are the main principles of OOP?"
    # Ack/question separation: the ack never contains the question text;
    # the exact generated question travels in current_question (voiced once).
    assert "overriding" not in (res["spoken_response"] or "").lower()
    assert res["provider_used"] is None  # injected mock: no provider tracked


def test_multi_turn_later_question_uses_earlier_answers():
    session = _session_row()
    llm1 = _FakeLLM(_eval_payload({
        "technical_correctness": 0.4, "depth": 0.35, "confidence": 0.8,
        "follow_up_needed": True, "suggested_follow_up": "Fallback?",
        "next_question": "What is runtime polymorphism in your own words?",
        "target_competency": "implementation_reasoning", "question_type": "probe",
        "missing": ["runtime dispatch"],
    }))
    res1 = _run_locked(session, "q1", "Polymorphism means one thing having many forms.", llm1)
    q2id = res1["current_question"]["id"]
    llm2 = _FakeLLM(_eval_payload({
        "technical_correctness": 0.85, "depth": 0.8, "reasoning": 0.85, "confidence": 0.9,
        "follow_up_needed": False,
        "next_question": "How does dynamic dispatch pick implementations, and what "
                         "breaks with static methods?",
        "target_competency": "implementation_reasoning", "question_type": "deepen",
    }))
    res2 = _run_locked(session, q2id, "A superclass reference to a subclass object picks the override at runtime.", llm2)
    # Turn-2 prompt carried turn-1 answer + evaluation forward.
    assert "many forms" in llm2.prompts[0]
    assert "runtime dispatch" in llm2.prompts[0]
    assert "static methods" in res2["current_question"]["prompt"].lower()
    assert res2["is_adaptive"] is True


def test_project_context_flows_into_generation():
    session = _session_row()
    llm = _FakeLLM(_eval_payload({
        "technical_correctness": 0.7, "depth": 0.6, "reasoning": 0.65, "confidence": 0.8,
        "follow_up_needed": False,
        "next_question": "You mentioned Express handled the Spotify integration. How did "
                         "you manage authentication and token expiry during requests?",
        "target_competency": "implementation_reasoning", "question_type": "verify",
    }))
    res = _run_locked(
        session, "q1",
        "I used Express to handle the Spotify API integration in MirrorVibes.", llm)
    assert "MirrorVibes" in llm.prompts[0]  # project context reached the model
    assert "express" in res["current_question"]["prompt"].lower()
    assert "spotify" in res["current_question"]["prompt"].lower()


def test_gemini_failure_falls_back_to_deterministic_plan():
    session = _session_row()

    class _FailLLM:
        async def ainvoke(self, _messages):
            raise RuntimeError("provider down")

    res = _run_locked(session, "q1", "Some answer here.", _FailLLM())
    assert res["evaluation_pending"] is True
    assert res["is_adaptive"] is False
    # Deterministic plan still advances the interview.
    assert res["current_question"]["prompt"] == "What are the main principles of OOP?"
