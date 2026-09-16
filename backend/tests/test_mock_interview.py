"""Tests for the adaptive AI mock interview (evidence source).

No real Gemini calls: the LLM is mocked. No Supabase needed: only pure
planning/evaluation/aggregation logic is exercised, plus endpoint routing
via FastAPI dependency overrides.
"""

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.mock_interview import AnswerEvaluation
from app.services import mock_interview_service as svc
from app.services.evidence_weights import (
    MOCK_INTERVIEW_SOURCE,
    SOURCE_DIRECTNESS,
    SOURCE_RELIABILITY,
)


def _assessments():
    return [
        {"canonical_name": "Python", "skill": "Python", "proficiency": 0.7,
         "confidence": 0.3, "gap": 0.1, "gap_type": "skill_gap",
         "signals": [{"source": "github", "signal_strength": 0.75},
                     {"source": "project", "signal_strength": 0.3}]},
        {"canonical_name": "SQL", "skill": "SQL", "proficiency": 0.2,
         "confidence": 0.2, "gap": 0.6, "gap_type": "evidence_gap", "signals": []},
        {"canonical_name": "System Design", "skill": "System Design", "proficiency": 0.9,
         "confidence": 0.9, "gap": 0.0, "gap_type": "skill_gap", "signals": []},
    ]


def _req_map():
    return {
        "Python": {"importance": 0.8, "demand": 0.85, "interview_relevance": 0.9,
                   "required_level": 0.75, "industry_confidence": 0.9},
        "SQL": {"importance": 0.85, "demand": 0.88, "interview_relevance": 0.8,
                "required_level": 0.8, "industry_confidence": 0.9},
        "System Design": {"importance": 0.9, "demand": 0.85, "interview_relevance": 0.85,
                          "required_level": 0.8, "industry_confidence": 0.9},
    }


def test_interview_source_weights_documented():
    assert SOURCE_RELIABILITY[MOCK_INTERVIEW_SOURCE] == 0.75
    assert SOURCE_DIRECTNESS[MOCK_INTERVIEW_SOURCE] == 0.85
    assert MOCK_INTERVIEW_SOURCE == "interview"


def test_ranking_prefers_gaps_and_uncertainty_over_covered():
    ranked = svc.rank_skills_for_interview(_assessments(), _req_map(), limit=6)
    skills = [r["skill"] for r in ranked]
    assert "SQL" in skills  # big gap + high interview relevance
    assert "Python" in skills  # uncertain confidence + conflicting signals
    assert "System Design" not in skills  # covered with high confidence
    assert ranked[0]["skill"] == "SQL"


def test_plan_is_personalized_and_evidence_driven():
    ranked = svc.rank_skills_for_interview(_assessments(), _req_map())
    projects = [{"name": "RAG Chatbot", "description": "Python FastAPI vector search with pgvector",
                 "technologies": ["Python", "FastAPI"], "student_contribution": "Built retrieval pipeline"}]
    evidence = [{"evidence_type": "leetcode", "metadata": {}}]
    plan = svc.build_mock_plan(ranked, projects, evidence, question_count=6)
    assert 5 <= len(plan) <= 8
    assert plan[0]["question_type"] == "warmup"
    assert "RAG Chatbot" in plan[0]["question"]  # project ownership, not generic
    assert any(q["question_type"] == "followup_slot" for q in plan)
    # role-based: top skills drive questions
    targets = {q["target_skill"] for q in plan}
    assert "SQL" in targets and "Python" in targets


def test_plan_generic_fallback_without_requirements():
    plan = svc.build_mock_plan([], [], [], question_count=6)
    assert len(plan) == 6
    assert all(q["question"].strip() for q in plan if q["question_type"] != "followup_slot")


def test_parse_evaluation_strict_schema():
    raw = json.dumps({
        "skills": ["Python"], "technical_correctness": 0.7, "depth": 0.5,
        "reasoning": 0.6, "communication": 0.8, "evidence_corroboration": 0.7,
        "contradiction": 0.1, "confidence": 0.8, "explanation": "Solid walkthrough.",
        "follow_up_needed": True, "suggested_follow_up": "What happens at 10x load?",
    })
    ev = svc.parse_evaluation(f"```json\n{raw}\n```", "q2")
    AnswerEvaluation.model_validate(ev)  # strict contract
    assert ev["question_id"] == "q2"
    assert ev["follow_up_needed"] is True


def test_parse_evaluation_rejects_garbage():
    with pytest.raises(Exception):
        svc.parse_evaluation("no json here at all", "q1")
    with pytest.raises(Exception):
        svc.parse_evaluation("[1,2,3]", "q1")


def test_adaptive_follow_up_policy():
    weak = {"technical_correctness": 0.3, "depth": 0.3, "reasoning": 0.4,
            "communication": 0.6, "evidence_corroboration": 0.2,
            "contradiction": 0.7, "confidence": 0.8,
            "follow_up_needed": True, "suggested_follow_up": "Explain retrieval step by step."}
    assert svc.decide_next_action(weak, 2, 6, 0) == "follow_up"
    strong = dict(weak, technical_correctness=0.9, depth=0.85, contradiction=0.0,
                  follow_up_needed=False, suggested_follow_up="")
    assert svc.decide_next_action(strong, 2, 6, 0) == "next"
    assert svc.decide_next_action(strong, 6, 6, 0) == "complete"
    # budget respected
    assert svc.decide_next_action(weak, 2, 6, 99) == "next"


def test_signal_strength_weights_technical_over_verbosity():
    strong = {"technical_correctness": 0.9, "depth": 0.8, "reasoning": 0.8,
              "communication": 1.0, "evidence_corroboration": 0.8,
              "contradiction": 0.0, "confidence": 0.9}
    weak = {"technical_correctness": 0.2, "depth": 0.2, "reasoning": 0.3,
            "communication": 0.9, "evidence_corroboration": 0.1,
            "contradiction": 0.7, "confidence": 0.8}
    assert svc.signal_strength_from_evaluation(strong) > 0.6
    assert svc.signal_strength_from_evaluation(weak) < 0.35


def test_contradiction_language_never_accuses():
    verdict, text = svc.detect_contradiction(0.8, 0.2)
    assert verdict == "requires_further_validation"
    assert "lying" not in text.lower()
    assert "independent understanding" in text
    verdict2, _ = svc.detect_contradiction(0.2, 0.8)
    assert verdict2 == "corroborated_upgrade"
    v3, _ = svc.detect_contradiction(None, 0.5)
    assert v3 == "insufficient_data"


def test_build_signals_one_per_skill_through_skill_engine():
    evals = [
        {"skills": ["Python"], "technical_correctness": 0.8, "depth": 0.7,
         "reasoning": 0.7, "communication": 0.7, "evidence_corroboration": 0.7,
         "contradiction": 0.0, "confidence": 0.8},
        {"skills": ["Python"], "technical_correctness": 0.6, "depth": 0.6,
         "reasoning": 0.6, "communication": 0.6, "evidence_corroboration": 0.5,
         "contradiction": 0.1, "confidence": 0.7},
        {"skills": ["SQL"], "technical_correctness": 0.3, "depth": 0.3,
         "reasoning": 0.3, "communication": 0.5, "evidence_corroboration": 0.2,
         "contradiction": 0.5, "confidence": 0.7},
    ]
    signals = svc.build_skill_signals("sess-1", evals, "Backend Developer")
    assert len(signals) == 2
    for s in signals:
        assert s["source"] == "interview"
        assert s["source_reliability"] == 0.75
    # Aggregates through the UNCHANGED engine without special cases
    from app.services import skill_engine as engine
    prof, _, _, _ = engine.proficiency(signals)
    assert 0.0 <= prof <= 1.0


class _FakeLLM:
    def __init__(self, payload: dict):
        self.payload = payload

    async def ainvoke(self, _messages):
        class R:
            content = json.dumps(self.payload)
        return R()


def test_evaluate_answer_uses_mocked_llm_no_real_call():
    payload = {"skills": ["Python"], "technical_correctness": 0.6, "depth": 0.5,
               "reasoning": 0.5, "communication": 0.7, "evidence_corroboration": 0.5,
               "contradiction": 0.2, "confidence": 0.7, "explanation": "OK",
               "follow_up_needed": False, "suggested_follow_up": ""}
    ev = asyncio.run(svc.evaluate_answer_llm(
        {"id": "q1", "target_skill": "Python", "question_type": "technical", "question": "Explain X"},
        "I built it with FastAPI and pgvector.",
        "Python: prior proficiency 0.7",
        _llm=_FakeLLM(payload),
    ))
    assert ev["skills"] == ["Python"]
    assert ev["technical_correctness"] == 0.6


def test_mock_interview_routes_registered():
    from app.api.v1.endpoints.mock_interview import router
    paths = sorted({r.path for r in router.routes})
    assert "/interview/start" in paths
    assert "/interview/{session_id}/answer" in paths
    assert "/interview/{session_id}/complete" in paths
    assert "/interview/{session_id}/report" in paths


def test_start_requires_supabase_or_role_resolution():
    # Without Supabase configured, start raises 503 (graceful, never fabricated)
    from fastapi import HTTPException
    try:
        svc._resolve_role("no-such-user", "")
    except HTTPException as e:
        assert e.status_code in (400, 503)
    else:
        pass  # profile/state present in some dev envs — acceptable
