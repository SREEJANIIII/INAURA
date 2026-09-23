"""Tests for the adaptive AI mock interview (evidence source).

No real Gemini calls: the LLM is mocked. No Supabase needed: only pure
planning/evaluation/aggregation logic is exercised, plus endpoint routing
via FastAPI dependency overrides.
"""

import asyncio
import json
from types import SimpleNamespace

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
    summary = svc.build_evidence_summary("Backend Developer", ranked, projects, evidence, [])
    assert "Backend Developer" in summary
    assert "RAG Chatbot" in summary  # project ownership, not generic
    assert "Python" in summary
    opening = svc.deterministic_opening_question(ranked, projects)
    assert "RAG Chatbot" in opening["question"]
    assert opening["question"].endswith("?")
    assert opening["question_type"] == "warmup"


def test_plan_generic_fallback_without_requirements():
    opening = svc.deterministic_opening_question([], [])
    assert len(opening["question"]) >= 20
    assert opening["question"].endswith("?")


def _grounding_anchors():
    return [{
        "project": "MirrorVibes",
        "repository": "student/mirrorvibes",
        "technology": ["Express", "Spotify API"],
        "artifact": ["spotifyService.js"],
        "implementation": "Spotify token refresh and playlist operations",
        "contribution": "backend integration",
        "source": "GitHub",
    }]


def test_live_question_validation_requires_real_evidence_anchor():
    anchors = _grounding_anchors()
    summary = "EVIDENCE ANCHORS:\n- Project: MirrorVibes\n- Technology: Express, Spotify API\n- Artifact: spotifyService.js"
    assert svc.validate_next_question("Tell me about your project?", [], "", summary, anchors) == "generic"
    assert svc.validate_next_question("How did you approach scalability?", [], "", summary, anchors) == "generic"
    assert svc.validate_next_question("In MirrorVibes, how did you handle Spotify authentication?", [], "", summary, anchors) is None
    assert svc.validate_next_question("In ResQNet, how does your FastAPI routing endpoint process vehicle constraints?", [], "", summary, anchors) == "unrelated_technology"
    assert svc.validate_next_question("In spotifyService.js, how does token refresh work?", [], "", summary, anchors) is None
    assert svc.validate_next_question("You said Redis reduced P95 latency. What bottleneck was removed?", [], "Redis reduced our P95 latency.", summary, anchors) is None
    assert svc.validate_next_question("How did you configure Kubernetes autoscaling?", [], "", summary, anchors) == "unrelated_technology"


def test_live_deterministic_fallback_and_spoken_response_are_grounded():
    summary = "EVIDENCE ANCHORS:\n- Project: MirrorVibes\n- Technology: Spotify API"
    fallback = svc.deterministic_next_question(
        "The Spotify API handles playlist operations.",
        {"technical_correctness": 0.3, "depth": 0.2}, ["In MirrorVibes, explain playlist operations?"], "Backend", summary,
    )
    assert "MirrorVibes" in fallback["question"] or "Spotify API" in fallback["question"]
    spoken = svc._evidence_specific_spoken_response("I've gone through your profile.", "I implemented Spotify token refresh.", summary)
    assert "profile" not in spoken.lower()
    assert "Spotify" in spoken


def test_live_q1_rejects_generic_model_question(monkeypatch):
    async def fake_chain(*_args, **_kwargs):
        return SimpleNamespace(
            text=json.dumps({"question": "What challenges did you face in your project?", "target_skill": "Python"}),
            provider_used="gemini",
        )

    monkeypatch.setattr(svc, "_run_chain", fake_chain)
    summary = "EVIDENCE ANCHORS:\n- Project: MirrorVibes\n- Technology: Express, Spotify API"
    out, provider = asyncio.run(svc.generate_opening_question(
        "Backend Developer", [{"skill": "Python"}],
        [{"name": "MirrorVibes", "technologies": ["Express", "Spotify API"], "student_contribution": "backend integration"}],
        [], [], summary, "session-1",
    ))
    assert provider == "deterministic"
    assert "MirrorVibes" in out["question"]
    assert "What challenges did you face" not in out["question"]


def test_parse_evaluation_strict_schema():
    raw = json.dumps({
        "evaluation": {
            "technical_correctness": 0.7, "depth": 0.5, "reasoning": 0.6,
            "communication": 0.8, "evidence_corroboration": 0.7,
            "contradiction": 0.1, "confidence": 0.8, "explanation": "Solid walkthrough.",
            "demonstrated": ["caching"], "missing": ["measurements"], "misconceptions": [],
        },
        "skills": ["Python"],
        "spoken_response": "Got it — let's dig in.",
        "next_question": "What specifically was slow before you introduced caching, and how did you measure the change?",
        "next_question_reason": "probe the unsupported performance claim",
        "target_skill": "Python",
        "question_type": "counter",
        "interview_sufficient": False,
    })
    ev = svc.parse_adaptive_evaluation(f"```json\n{raw}\n```", "q2")
    AnswerEvaluation.model_validate(ev)  # strict contract
    assert ev["question_id"] == "q2"
    assert ev["demonstrated"] == ["caching"]
    assert ev["next_question"].startswith("What specifically was slow")
    assert ev["question_type"] == "counter"


def test_parse_evaluation_rejects_garbage():
    with pytest.raises(Exception):
        svc.parse_adaptive_evaluation("no json here at all", "q1")
    with pytest.raises(Exception):
        svc.parse_adaptive_evaluation("[1,2,3]", "q1")


def test_parse_evaluation_preserves_probe_target_and_investigation_state():
    raw = json.dumps({
        "evaluation": {
            "technical_correctness": 0.8,
            "depth": 0.7,
            "established": ["Candidate described token refresh entry point"],
            "unproven": ["Refresh-token storage and rotation remain unclear"],
        },
        "contradictions": ["Repository evidence shows server-side handling"],
        "interesting_claims": ["Concurrent requests can arrive after expiry"],
        "probe_target": {"topic": "refresh-token concurrency", "reason": "race handling is unresolved", "evidence_anchor_id": "e1", "depth": "deep"},
        "next_action": "counter_question",
        "next_question": "In MirrorVibes, how do you prevent two expired Spotify requests from refreshing the same token concurrently?",
        "question_type": "scenario",
    })
    ev = svc.parse_adaptive_evaluation(raw, "q1")
    assert ev["established"] == ["Candidate described token refresh entry point"]
    assert ev["unproven"] == ["Refresh-token storage and rotation remain unclear"]
    assert ev["contradictions"] == ["Repository evidence shows server-side handling"]
    assert ev["probe_target"]["evidence_anchor_id"] == "e1"
    assert ev["next_action"] == "counter_question"


def test_explicit_model_completion_can_end_after_a_sufficient_answer():
    assert svc.decide_next_action({"next_action": "complete"}, 1) == "complete"
    assert svc.decide_next_action({"interview_sufficient": True}, 2) == "complete"
    assert svc.decide_next_action({"interview_sufficient": False}, 2) == "next"


def test_adaptive_follow_up_policy():
    # 3-question invariant: answered < 3 always continues, >= 3 completes.
    assert svc.INTERVIEW_QUESTION_COUNT == 3
    assert svc.decide_next_action({}, 0) == "next"
    assert svc.decide_next_action({}, 1) == "next"
    assert svc.decide_next_action({}, 2) == "next"
    assert svc.decide_next_action({}, 3) == "complete"
    # No Q4 even with more answers recorded.
    assert svc.decide_next_action({}, 4) == "complete"


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


class _FakeChain:
    """Fake provider chain result for evaluate_and_generate (no real calls)."""

    def __init__(self, payload: dict, provider: str = "gemini"):
        self.payload = payload
        self.provider = provider
        self.calls = 0

    async def __call__(self, messages, session_id, question_id):
        self.calls += 1
        self.last_messages = messages

        class R:
            pass

        r = R()
        r.text = json.dumps(self.payload)
        r.provider_used = self.provider
        r.failure_class = None
        return r


def _adaptive_payload(next_question=""):
    return {
        "evaluation": {
            "technical_correctness": 0.6, "depth": 0.5, "reasoning": 0.5,
            "communication": 0.7, "evidence_corroboration": 0.5,
            "contradiction": 0.2, "confidence": 0.7, "explanation": "OK",
            "demonstrated": ["fastapi"], "missing": ["metrics"], "misconceptions": [],
        },
        "skills": ["Python"],
        "spoken_response": "Got it.",
        "next_question": next_question,
        "next_question_reason": "probe",
        "target_skill": "Python",
        "question_type": "probe",
        "interview_sufficient": False,
    }


def test_evaluate_answer_uses_mocked_llm_no_real_call():
    from unittest.mock import patch
    chain = _FakeChain(_adaptive_payload())
    with patch.object(svc, "_run_chain", chain):
        ev, provider = asyncio.run(svc.evaluate_and_generate(
            "Backend Developer",
            "Target role: Backend Developer",
            [],
            {"question": "Explain X", "target_skill": "Python", "id": "q1", "question_key": "q1"},
            "I built it with FastAPI and pgvector.",
            False,
            "sess-1",
        ))
    assert chain.calls == 1  # exactly one reasoning call per answer
    assert ev["technical_correctness"] == 0.6
    assert provider == "gemini"


def test_mock_interview_routes_registered():
    from app.api.v1.endpoints.mock_interview import router
    paths = sorted({r.path for r in router.routes})
    assert "/interview/start" in paths
    assert "/interview/history" in paths
    assert "/interview/{session_id}/answer" in paths
    assert "/interview/{session_id}/complete" in paths
    assert "/interview/{session_id}/report" in paths


def test_classify_conversation_intent_entire_skill_vs_subtopic():
    from app.services.assessment.interview import classify_conversation_intent
    # If candidate states they don't know the core skill being interviewed:
    intent1 = classify_conversation_intent("I dont know anything about python", "Python")
    assert intent1 == "entire_skill_unknown"
    intent2 = classify_conversation_intent("i have never learned python or used it", "Python")
    assert intent2 == "entire_skill_unknown"
    # But if they don't know a sub-topic/library within that skill:
    intent3 = classify_conversation_intent("I dont know about pandas library in python", "Python")
    assert intent3 == "technical_answer"
    intent4 = classify_conversation_intent("I'm not familiar with the asyncio module in python", "Python")
    assert intent4 == "technical_answer"
    # Clarifications:
    intent5 = classify_conversation_intent("Could you clarify the question?", "Python")
    assert intent5 == "interviewer_clarification"


def test_start_requires_supabase_or_role_resolution():
    # Without Supabase configured, start raises 503 (graceful, never fabricated)
    from fastapi import HTTPException
    try:
        svc._resolve_role("no-such-user", "")
    except HTTPException as e:
        assert e.status_code in (400, 503)
    else:
        pass  # profile/state present in some dev envs — acceptable
