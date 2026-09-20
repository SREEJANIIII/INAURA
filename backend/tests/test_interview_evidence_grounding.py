"""Evidence-grounding regression tests for the live /interview path.

Reproduces the exact reported bug: generic questions ("What challenges did
you face?", "Tell me about your project.", "How did you approach this?")
reaching the browser despite concrete student evidence, plus generic spoken
filler ("I've gone through your profile.").

No real LLM calls (svc._run_chain faked). No Supabase (in-memory fake).
"""

import asyncio
import copy
import json
from typing import Dict, List, Optional
from unittest.mock import patch

from app.services import mock_interview_service as svc


# ===========================================================================
# Fixtures: MirrorVibes evidence from the bug report
# ===========================================================================

def _mirrorvibes_projects():
    return [{
        "name": "MirrorVibes",
        "repository": "student/mirror-vibes-ai",
        "description": "Music mood app with Spotify integration",
        "technologies": ["Express", "Spotify API"],
        "student_contribution": "backend API integration with Spotify authentication and token refresh",
        "artifacts": ["spotifyService.js"],
        "implementation_signal": "Spotify token refresh and playlist operations",
        "source": "GitHub",
    }]


def _mirrorvibes_anchors():
    return svc.extract_evidence_anchors(_mirrorvibes_projects(), [], "Express")


def _mirrorvibes_summary():
    ranked = [{"skill": "Express", "proficiency": 0.5, "confidence": 0.3,
               "gap": 0.4, "interview_relevance": 0.9, "priority": 9.0}]
    return svc.build_evidence_summary(
        "Backend Developer", ranked, _mirrorvibes_projects(), [], [])


# ===========================================================================
# TEST 1-3: generic questions are REJECTED even though well-formed
# ===========================================================================

def test_01_challenges_question_rejected():
    anchors, summary = _mirrorvibes_anchors(), _mirrorvibes_summary()
    assert anchors, "test needs a concrete anchor to be meaningful"
    reason = svc.validate_next_question(
        "What challenges did you face while building your project?",
        [], "", summary, anchors)
    assert reason is not None, "generic challenges question must be rejected"


def test_02_scalability_question_rejected():
    anchors, summary = _mirrorvibes_anchors(), _mirrorvibes_summary()
    assert svc.validate_next_question(
        "How did you approach scalability in your project?",
        [], "", summary, anchors) is not None


def test_03_tell_me_about_experience_rejected():
    anchors, summary = _mirrorvibes_anchors(), _mirrorvibes_summary()
    assert svc.validate_next_question(
        "Tell me about your backend experience?",
        [], "", summary, anchors) is not None


# ===========================================================================
# TEST 4-5: anchored questions are ACCEPTED
# ===========================================================================

def test_04_mirrorvibes_token_refresh_accepted():
    anchors, summary = _mirrorvibes_anchors(), _mirrorvibes_summary()
    assert svc.validate_next_question(
        "In MirrorVibes, how does your Spotify token refresh flow work?",
        [], "", summary, anchors) is None


def test_05_resqnet_routing_accepted_with_own_anchors():
    projects = [{
        "name": "ResQNet",
        "repository": "student/resqnet",
        "technologies": ["FastAPI"],
        "student_contribution": "backend routing logic with route scoring and vehicle constraints",
        "source": "GitHub",
    }]
    anchors = svc.extract_evidence_anchors(projects, [], "FastAPI")
    ranked = [{"skill": "FastAPI", "proficiency": 0.5, "confidence": 0.3, "gap": 0.4}]
    summary = svc.build_evidence_summary("Backend Developer", ranked, projects, [], [])
    assert svc.validate_next_question(
        "In ResQNet, how does your FastAPI route-scoring pipeline handle vehicle constraints?",
        [], "", summary, anchors) is None


# ===========================================================================
# TEST 6: unrelated technology is REJECTED
# ===========================================================================

def test_06_kubernetes_rejected_when_not_in_evidence():
    anchors, summary = _mirrorvibes_anchors(), _mirrorvibes_summary()
    assert svc.validate_next_question(
        "How did you configure Kubernetes autoscaling?",
        [], "", summary, anchors) == "unrelated_technology"


# ===========================================================================
# TEST 7-8: answer-claim anchoring
# ===========================================================================

def test_07_claim_specific_counter_question_accepted():
    anchors, summary = _mirrorvibes_anchors(), _mirrorvibes_summary()
    assert svc.validate_next_question(
        "You said Redis reduced P95 latency. What bottleneck was removed?",
        [], "Redis reduced our P95 latency.", summary, anchors) is None


def test_08_bare_why_this_approach_rejected():
    anchors, summary = _mirrorvibes_anchors(), _mirrorvibes_summary()
    assert svc.validate_next_question(
        "Why did you choose this approach?",
        [], "I used refresh tokens because access tokens expire.",
        summary, anchors) is not None


# ===========================================================================
# TEST 9-10: generic Gemini output never reaches the browser
# ===========================================================================

class _FakeChain:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0

    async def __call__(self, messages, session_id, question_id):
        self.calls += 1

        class R:
            pass

        r = R()
        r.text = self.texts[min(self.calls - 1, len(self.texts) - 1)]
        r.provider_used = "gemini"
        r.failure_class = None
        return r


def test_09_generic_gemini_q1_never_reaches_browser():
    anchors, summary = _mirrorvibes_anchors(), _mirrorvibes_summary()
    generic_q1 = json.dumps({
        "question": "What challenges did you face while building your project?",
        "target_skill": "Express", "question_type": "warmup", "reason": "generic"})
    chain = _FakeChain([generic_q1])
    with patch.object(svc, "_run_chain", chain):
        out, provider = asyncio.run(svc.generate_opening_question(
            "Backend Developer", [{"skill": "Express"}],
            _mirrorvibes_projects(), [], [], summary, "sess-test-9"))
    assert out["question"] != "What challenges did you face while building your project?"
    assert provider == "deterministic"
    assert "MirrorVibes" in out["question"]
    assert svc.validate_next_question(
        out["question"], [], "", summary, anchors) is None


def test_10_generic_gemini_q2_never_reaches_browser():
    anchors, summary = _mirrorvibes_anchors(), _mirrorvibes_summary()
    assert svc.validate_next_question(
        "How did you approach scalability?", [], "I used refresh tokens.",
        summary, anchors) is not None


# ===========================================================================
# TEST 11-12: deterministic fallback is grounded AND re-validated
# ===========================================================================

def test_11_fallback_uses_actual_project_and_claim():
    anchors, summary = _mirrorvibes_anchors(), _mirrorvibes_summary()
    out = svc.deterministic_next_question(
        "I used refresh tokens because access tokens expire.",
        {"contradiction": 0.0, "technical_correctness": 0.6, "depth": 0.55},
        ["In MirrorVibes, you implemented Spotify authentication. Walk me through it?"],
        "Express", summary, anchors, 2)
    assert "MirrorVibes" in out["question"]
    assert out["question"] != "What challenges did you face while building your project?"


def test_12_fallback_passes_same_validator():
    anchors, summary = _mirrorvibes_anchors(), _mirrorvibes_summary()
    priors = ["In MirrorVibes, you implemented Spotify authentication. Walk me through it?"]
    for qnum, scores in (
        (2, {"contradiction": 0.0, "technical_correctness": 0.3, "depth": 0.2}),
        (2, {"contradiction": 0.0, "technical_correctness": 0.8, "depth": 0.8}),
        (3, {"contradiction": 0.0, "technical_correctness": 0.8, "depth": 0.8}),
        (2, {"contradiction": 0.9, "technical_correctness": 0.5, "depth": 0.5}),
    ):
        out = svc.deterministic_next_question(
            "I used refresh tokens because access tokens expire.",
            scores, priors, "Express", summary, anchors, qnum)
        assert svc.validate_next_question(
            out["question"], priors,
            "I used refresh tokens because access tokens expire.",
            summary, anchors) is None, f"fallback failed validation: {out['question']}"


# ===========================================================================
# TEST 13: generic spoken filler is replaced with evidence-specific ack
# ===========================================================================

def test_13_profile_filler_spoken_response_replaced():
    summary = _mirrorvibes_summary()
    for filler in ("I've gone through your profile.",
                   "I've reviewed your profile.",
                   "I see you have experience with backend development.",
                   "That's interesting."):
        spoken = svc._evidence_specific_spoken_response(
            filler, "I implemented Spotify token refresh in MirrorVibes.", summary)
        assert "profile" not in spoken.lower(), filler
        assert "experience with backend" not in spoken.lower(), filler


# ===========================================================================
# TEST 14 + full-flow integration: generic Q2/Q3 rejected, grounded
# fallbacks used, interview completes exactly at Q3.
# ===========================================================================

class _Result:
    def __init__(self, data):
        self.data = data


class _Builder:
    def __init__(self, store, table):
        self.store = store
        self.table = table
        self.mode = "select"
        self.row = None
        self.patch = None
        self.filters = []
        self.order_key = None
        self.desc = False
        self.limit_n = None

    def select(self, *args):
        self.mode = "select"
        return self

    def insert(self, row):
        self.mode = "insert"
        self.row = copy.deepcopy(row)
        return self

    def update(self, patch):
        self.mode = "update"
        self.patch = dict(patch)
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, key, desc=False):
        self.order_key = key
        self.desc = bool(desc)
        return self

    def limit(self, n):
        self.limit_n = int(n)
        return self

    def execute(self):
        rows = self.store.setdefault(self.table, [])
        if self.mode == "insert":
            self.row.setdefault("id", f"fake-{len(rows)}")
            rows.append(self.row)
            return _Result([copy.deepcopy(self.row)])
        matched = [r for r in rows if all(r.get(k) == v for k, v in self.filters)]
        if self.mode == "update":
            for r in matched:
                r.update(self.patch or {})
            return _Result([copy.deepcopy(r) for r in matched])
        out = list(matched)
        if self.order_key is not None:
            out.sort(key=lambda r: (r.get(self.order_key) is None, r.get(self.order_key) or 0),
                     reverse=self.desc)
        if self.limit_n is not None:
            out = out[:self.limit_n]
        return _Result([copy.deepcopy(r) for r in out])


class FakeSupabase:
    def __init__(self):
        self.store: Dict[str, list] = {}

    def table(self, name):
        return _Builder(self.store, name)


def _eval_text(next_question, spoken="You mentioned Spotify token refresh. Let's go deeper."):
    return json.dumps({
        "evaluation": {
            "technical_correctness": 0.7, "depth": 0.65, "reasoning": 0.7,
            "communication": 0.75, "evidence_corroboration": 0.6,
            "contradiction": 0.1, "confidence": 0.8,
            "explanation": "Candidate described the refresh flow.",
            "demonstrated": ["token refresh"], "missing": ["failure handling"],
            "misconceptions": [],
        },
        "skills": ["Express"],
        "spoken_response": spoken,
        "next_question": next_question,
        "next_question_reason": "probe the claim",
        "target_skill": "Express",
        "question_type": "counter",
        "interview_sufficient": False,
    })


def _assessments():
    return [{"canonical_name": "Express", "skill": "Express", "proficiency": 0.5,
             "confidence": 0.3, "gap": 0.4, "gap_type": "skill_gap", "signals": []}]


def _req_map():
    return {"Express": {"importance": 0.8, "demand": 0.8, "interview_relevance": 0.9,
                        "required_level": 0.75, "industry_confidence": 0.85}}


def test_14_full_flow_q1_grounded_q2_q3_reject_generic_complete_at_q3():
    q1 = ("In MirrorVibes, you implemented Spotify authentication and token handling. "
          "Walk me through how your refresh-token flow works and why you designed it that way?")
    chain = _FakeChain([
        json.dumps({"question": q1, "target_skill": "Express",
                    "question_type": "warmup", "reason": "test"}),
        _eval_text("What challenges did you face while building your project?",
                   spoken="I've gone through your profile."),
        _eval_text("How did you approach scalability in your project?"),
        _eval_text("", spoken="Thanks."),
    ])
    fake = FakeSupabase()
    with patch.object(svc, "_client", return_value=fake), \
         patch.object(svc, "_resolve_role", return_value="Backend Developer"), \
         patch.object(svc, "_ai_available", return_value=True), \
         patch.object(svc, "_snapshot_assessments",
                      return_value=(_assessments(), _req_map(), _mirrorvibes_projects(), [])), \
         patch.object(svc, "_run_chain", chain):
        started = asyncio.run(svc.start_session("u1", "Backend Developer", 3))
        # Q1 names concrete evidence
        assert "MirrorVibes" in started["current_question"]["question"]
        assert "Spotify" in started["current_question"]["question"]
        sid = started["session_id"]

        # A1 -> Gemini proposes generic Q2 -> must be rejected + replaced
        r1 = asyncio.run(svc.submit_answer(
            "u1", sid, "I used refresh tokens because access tokens expire."))
        assert r1["next_action"] == "next"
        q2 = r1["current_question"]["question"]
        assert q2 != "What challenges did you face while building your project?"
        assert "MirrorVibes" in q2, f"Q2 lost its evidence anchor: {q2}"
        assert "profile" not in (r1["spoken_response"] or "").lower()
        assert r1["answered_count"] == 1

        # A2 -> Gemini proposes generic Q3 -> must be rejected + replaced, deeper
        r2 = asyncio.run(svc.submit_answer(
            "u1", sid, "The backend refreshes it and retries the request."))
        assert r2["next_action"] == "next"
        q3 = r2["current_question"]["question"]
        assert q3 != "How did you approach scalability in your project?"
        assert "MirrorVibes" in q3, f"Q3 lost its evidence anchor: {q3}"
        assert r2["answered_count"] == 2

        # A3 -> completes, never a Q4
        r3 = asyncio.run(svc.submit_answer(
            "u1", sid, "We added a lock around refresh and queued retries."))
        assert r3["next_action"] == "complete"
        assert r3["current_question"] is None
        assert r3["answered_count"] == 3
        assert len(fake.store[svc.QUESTIONS_TABLE]) == 3

        # Q2/Q3 share concrete anchors with the evidence (TEST 14)
        q_texts = [q["question"] for q in fake.store[svc.QUESTIONS_TABLE]]
        assert any("MirrorVibes" in t for t in q_texts[1:])
        assert all(t.endswith("?") for t in q_texts)
