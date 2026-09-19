"""Tests for the 3-question adaptive mock interview (live /interview path).

No real LLM calls: the provider chain (svc._run_chain) is faked.
No Supabase needed: a small in-memory fake covers the tables used.

Covers: default count 3, no 5+ plan, answer persistence, Q2/Q3 context
contents, evidence in context, counter-question generation, validation
rules, deterministic fallbacks, LLM-failure transcript safety, completion
invariants (never after Q1/Q2, always after Q3, never Q4), and full
interview reconstruction.
"""

import asyncio
import copy
import json
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from app.schemas.mock_interview import StartMockInterviewRequest
from app.services import mock_interview_service as svc


# ===========================================================================
# In-memory Supabase fake (supports exactly the chaining the service uses)
# ===========================================================================

class _Result:
    def __init__(self, data):
        self.data = data


class _Builder:
    def __init__(self, store, table):
        self.store = store
        self.table = table
        self.mode = "select"
        self.row: Optional[dict] = None
        self.patch: Optional[dict] = None
        self.filters: List[tuple] = []
        self.order_key: Optional[str] = None
        self.desc = False
        self.limit_n: Optional[int] = None

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
            assert self.row is not None
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


# ===========================================================================
# Fake provider chain
# ===========================================================================

class FakeChain:
    """Queue of payloads; records every messages list it receives."""

    def __init__(self, payloads: List[dict], provider: str = "gemini"):
        self.payloads = list(payloads)
        self.provider = provider
        self.calls = 0
        self.seen_messages: List[list] = []

    async def __call__(self, messages, session_id, question_id):
        self.calls += 1
        self.seen_messages.append(messages)

        class R:
            pass

        r = R()
        payload = self.payloads[min(self.calls - 1, len(self.payloads) - 1)]
        r.text = None if payload is None else json.dumps(payload)
        r.provider_used = self.provider if payload is not None else "deterministic"
        r.failure_class = None if payload is not None else "temporary_unavailable"
        return r

    @property
    def last_user_text(self) -> str:
        msgs = self.seen_messages[-1]
        return str(msgs[-1].get("content") or "")


def _eval_payload(next_question="", qtype="counter", skill="Python",
                  contradiction=0.1, tech=0.7, depth=0.65, explanation="Good walkthrough."):
    return {
        "evaluation": {
            "technical_correctness": tech, "depth": depth, "reasoning": 0.7,
            "communication": 0.75, "evidence_corroboration": 0.6,
            "contradiction": contradiction, "confidence": 0.8,
            "explanation": explanation,
            "demonstrated": ["caching layer"], "missing": ["latency measurements"],
            "misconceptions": [],
        },
        "skills": [skill],
        "spoken_response": "Got it — let's dig into that.",
        "next_question": next_question,
        "next_question_reason": "probe the performance claim",
        "target_skill": skill,
        "question_type": qtype,
        "interview_sufficient": False,
    }


Q2_TEXT = ("What specifically was slow before Redis, and how did you measure "
           "the change after introducing it?")
Q3_TEXT = ("When that cache entry expires under peak load, what happens to your "
           "database, and how would you prevent a stampede?")


def _assessments():
    return [
        {"canonical_name": "Python", "proficiency": 0.7, "confidence": 0.5, "gap": 0.1},
        {"canonical_name": "SQL", "proficiency": 0.3, "confidence": 0.4, "gap": 0.5},
    ]


def _projects():
    return [{"name": "RAG Chatbot",
             "description": "Python FastAPI vector search with pgvector",
             "technologies": ["Python", "FastAPI"],
             "student_contribution": "Built retrieval pipeline with Redis caching"}]


def _start(fake: FakeSupabase, chain: FakeChain):
    """Start a session with fully mocked I/O; returns the start dict."""
    ranked = [{"skill": "Python", "priority": 9.0, "gap": 0.1, "confidence": 0.5,
               "proficiency": 0.7, "interview_relevance": 0.9, "assessment": {}}]
    opening = {"question": "You built a RAG Chatbot with Redis caching. Walk me through the part you personally built?",
               "target_skill": "Python", "question_type": "warmup", "reason": "test"}
    with patch.object(svc, "_client", return_value=fake), \
         patch.object(svc, "_resolve_role", return_value="Backend Developer"), \
         patch.object(svc, "_ai_available", return_value=False), \
         patch.object(svc, "_snapshot_assessments",
                      return_value=(_assessments(), {}, _projects(), [])):
        with patch.object(svc, "generate_opening_question",
                          return_value=(opening, "gemini")):
            return asyncio.run(svc.start_session("u1", "Backend Developer", 3))


def _answer(fake: FakeSupabase, chain: FakeChain, session_id: str, text: str):
    with patch.object(svc, "_client", return_value=fake), \
         patch.object(svc, "_run_chain", chain):
        return asyncio.run(svc.submit_answer("u1", session_id, text))


# ===========================================================================
# 1-2. Count contract
# ===========================================================================

def test_01_default_question_count_is_3():
    assert svc.INTERVIEW_QUESTION_COUNT == 3
    assert svc.MIN_INTERVIEW_QUESTIONS == 3
    assert svc.MAX_INTERVIEW_QUESTIONS == 3
    assert StartMockInterviewRequest().question_count == 3


def test_02_start_persists_q1_only_with_count_3():
    fake, chain = FakeSupabase(), FakeChain([_eval_payload()])
    started = _start(fake, chain)
    assert started["question_count"] == 3
    session_rows = fake.store[svc.SESSIONS_TABLE]
    assert session_rows[0]["question_count"] == 3
    assert session_rows[0]["status"] == "in_progress"
    q_rows = fake.store[svc.QUESTIONS_TABLE]
    assert len(q_rows) == 1  # only Q1 exists; Q2/Q3 come from answers
    assert q_rows[0]["sequence"] == 1
    assert q_rows[0]["is_follow_up"] is False
    assert started["current_question"]["question"].endswith("?")
    assert started["ai_available"] is False  # no provider keys in test env


# ===========================================================================
# 3. Q1 answer persisted (transcript + keys)
# ===========================================================================

def test_03_q1_answer_persisted():
    fake = FakeSupabase()
    chain = FakeChain([_eval_payload(next_question=Q2_TEXT)])
    started = _start(fake, chain)
    resp = _answer(fake, chain, started["session_id"],
                   "I added Redis caching to our FastAPI chatbot and it got faster.")
    rows = fake.store[svc.RESPONSES_TABLE]
    assert len(rows) == 1
    assert "Redis caching" in rows[0]["transcript"]
    assert rows[0]["question_key"] == "q1"
    assert rows[0]["question_id"] == fake.store[svc.QUESTIONS_TABLE][0]["id"]
    assert isinstance(rows[0]["evaluation"], dict)
    assert resp["answered_count"] == 1


# ===========================================================================
# 4-6. Conversation memory passed to Gemini
# ===========================================================================

def test_04_q2_receives_q1_plus_answer1():
    fake = FakeSupabase()
    chain = FakeChain([_eval_payload(next_question=Q2_TEXT)])
    started = _start(fake, chain)
    q1_text = started["current_question"]["question"]
    _answer(fake, chain, started["session_id"], "I added Redis caching to our FastAPI chatbot.")
    user_text = chain.last_user_text
    assert q1_text[:60] in user_text  # Q1 present
    assert "Redis caching" in user_text  # Answer1 present


def test_05_q3_receives_full_history():
    fake = FakeSupabase()
    chain = FakeChain([
        _eval_payload(next_question=Q2_TEXT, explanation="Eval one notes caching claim."),
        _eval_payload(next_question=Q3_TEXT),
    ])
    started = _start(fake, chain)
    q1_text = started["current_question"]["question"]
    _answer(fake, chain, started["session_id"], "I added Redis caching to our FastAPI chatbot.")
    _answer(fake, chain, started["session_id"], "P95 latency dropped from 900ms to 120ms after Redis.")
    user_text = chain.last_user_text
    assert q1_text[:60] in user_text  # Q1
    assert "Redis caching to our FastAPI" in user_text  # Answer1
    assert "Eval one notes caching claim" in user_text  # Evaluation1
    assert "What specifically was slow before Redis" in user_text  # Q2
    assert "P95 latency dropped" in user_text  # Answer2


def test_06_prior_evidence_included_in_context():
    fake = FakeSupabase()
    chain = FakeChain([_eval_payload(next_question=Q2_TEXT)])
    started = _start(fake, chain)
    plan = fake.store[svc.SESSIONS_TABLE][0]["plan"]
    assert "RAG Chatbot" in plan["evidence_summary"]
    assert "Backend Developer" in plan["evidence_summary"]
    _answer(fake, chain, started["session_id"], "I added Redis caching.")
    user_text = chain.last_user_text
    assert "RAG Chatbot" in user_text
    assert "Backend Developer" in user_text
    assert "Python" in user_text


# ===========================================================================
# 7. Counter-question generated from the actual answer
# ===========================================================================

def test_07_q2_is_model_counter_question_with_followup_metadata():
    fake = FakeSupabase()
    chain = FakeChain([_eval_payload(next_question=Q2_TEXT)])
    started = _start(fake, chain)
    q1_id = fake.store[svc.QUESTIONS_TABLE][0]["id"]
    resp = _answer(fake, chain, started["session_id"], "Redis improved performance.")
    assert resp["next_action"] == "next"
    assert resp["current_question"] is not None
    assert resp["current_question"]["question"] == Q2_TEXT
    assert resp["spoken_response"] == "Got it — let's dig into that."
    q2_rows = [q for q in fake.store[svc.QUESTIONS_TABLE] if q["sequence"] == 2]
    assert len(q2_rows) == 1
    assert q2_rows[0]["is_follow_up"] is True
    assert q2_rows[0]["parent_question_id"] == q1_id
    assert q2_rows[0]["question_type"] == "counter"
    assert q2_rows[0]["source_evidence"]  # describes what caused the question


# ===========================================================================
# 8-9. Next-question validation
# ===========================================================================

def test_08_generic_repeated_question_rejected_and_replaced():
    assert svc.validate_next_question("Can you explain more about this?", ["Prior?"], "answer") == "generic"
    fake = FakeSupabase()
    chain = FakeChain([_eval_payload(next_question="Can you explain more about this?")])
    started = _start(fake, chain)
    resp = _answer(fake, chain, started["session_id"], "I built the retrieval pipeline with embeddings.")
    assert resp["current_question"]["question"] != "Can you explain more about this?"
    assert resp["current_question"]["question"].endswith("?")


def test_09_question_restating_answer_rejected():
    answer = "I implemented JWT authentication with refresh token rotation in our API gateway service layer"
    assert svc.validate_next_question(
        "Why did you implement JWT authentication with refresh token rotation in the API gateway service layer?",
        ["Earlier question?"], answer) == "restates_answer"
    assert svc.validate_next_question("", ["Q?"], "answer") == "missing"
    assert svc.validate_next_question("Too short?", ["Q?"], "answer") == "too_short"
    assert svc.validate_next_question("This is not a question", ["Q?"], "answer") == "not_a_question"


# ===========================================================================
# 10-12. Deterministic fallback behavior by answer quality
# ===========================================================================

def test_10_contradiction_causes_clarification():
    out = svc.deterministic_next_question(
        "We store sessions in JWT tokens on the client.",
        {"contradiction": 0.8, "technical_correctness": 0.5, "depth": 0.5},
        ["Q1?"], "Python")
    assert out["question_type"] == "verification"
    assert "clarify" in out["question"].lower()


def test_11_strong_answer_causes_deeper_question():
    out = svc.deterministic_next_question(
        "I used consistent hashing with virtual nodes to rebalance our cache ring.",
        {"contradiction": 0.0, "technical_correctness": 0.9, "depth": 0.85},
        ["Q1?"], "Python")
    assert out["question_type"] == "tradeoff"
    assert "trade-off" in out["question"] or "edge case" in out["question"]


def test_12_weak_answer_causes_concrete_probe():
    out = svc.deterministic_next_question(
        "It was good.",
        {"contradiction": 0.0, "technical_correctness": 0.3, "depth": 0.2},
        ["Q1?"], "Python")
    assert out["question_type"] == "probe"
    assert out["question"].endswith("?")


# ===========================================================================
# 13. LLM failure preserves transcript, interview continues
# ===========================================================================

def test_13_llm_failure_preserves_transcript_and_continues():
    fake = FakeSupabase()
    chain = FakeChain([None])  # every provider failed
    started = _start(fake, chain)
    resp = _answer(fake, chain, started["session_id"], "I built the retrieval pipeline.")
    rows = fake.store[svc.RESPONSES_TABLE]
    assert rows[0]["transcript"] == "I built the retrieval pipeline."
    assert resp["evaluation_pending"] is True
    assert resp["next_action"] == "next"  # never terminates on LLM failure
    assert resp["current_question"] is not None
    assert resp["answered_count"] == 1


# ===========================================================================
# 14-17. Completion invariants
# ===========================================================================

def _full_interview():
    fake = FakeSupabase()
    chain = FakeChain([
        _eval_payload(next_question=Q2_TEXT),
        _eval_payload(next_question=Q3_TEXT),
        _eval_payload(next_question="Should never be used as Q4?"),
    ])
    started = _start(fake, chain)
    sid = started["session_id"]
    r1 = _answer(fake, chain, sid, "Answer one about Redis caching work.")
    r2 = _answer(fake, chain, sid, "Answer two with latency numbers.")
    r3 = _answer(fake, chain, sid, "Answer three about stampede protection.")
    return fake, chain, (r1, r2, r3)


def test_14_never_completes_after_q1():
    _, _, (r1, _, _) = _full_interview()
    assert r1["next_action"] == "next"
    assert r1["current_question"] is not None
    assert r1["answered_count"] == 1


def test_15_never_completes_after_q2():
    _, _, (_, r2, _) = _full_interview()
    assert r2["next_action"] == "next"
    assert r2["current_question"] is not None
    assert r2["answered_count"] == 2


def test_16_completes_after_q3():
    _, _, (_, _, r3) = _full_interview()
    assert r3["next_action"] == "complete"
    assert r3["current_question"] is None
    assert r3["answered_count"] == 3


def test_17_no_q4_generated():
    fake, _, (_, _, r3) = _full_interview()
    assert r3["next_action"] == "complete"
    assert len(fake.store[svc.QUESTIONS_TABLE]) == 3
    assert sorted(q["sequence"] for q in fake.store[svc.QUESTIONS_TABLE]) == [1, 2, 3]


def test_complete_session_builds_report_from_persisted_evals():
    fake = FakeSupabase()
    chain = FakeChain([
        _eval_payload(next_question=Q2_TEXT),
        _eval_payload(next_question=Q3_TEXT),
        _eval_payload(next_question="Ignored?"),
    ])
    started = _start(fake, chain)
    sid = started["session_id"]
    _answer(fake, chain, sid, "Answer one about Redis caching work.")
    _answer(fake, chain, sid, "Answer two with latency numbers.")
    _answer(fake, chain, sid, "Answer three about stampede protection.")
    with patch.object(svc, "_client", return_value=fake):
        report = asyncio.run(svc.complete_session("u1", sid))
    assert report["status"] == "completed"
    assert report["questions_answered"] == 3
    assert fake.store[svc.SESSIONS_TABLE][0]["status"] == "completed"


# ===========================================================================
# 19. Full reconstruction from persisted rows
# ===========================================================================

def test_19_persisted_rows_reconstruct_entire_interview():
    fake, _, _ = _full_interview()
    turns = svc.reconstruct_interview(
        fake.store[svc.QUESTIONS_TABLE], fake.store[svc.RESPONSES_TABLE])
    assert len(turns) == 3
    assert [t["sequence"] for t in turns] == [1, 2, 3]
    assert all(t["answered"] and t["answer"] for t in turns)
    assert all(isinstance(t["evaluation"], dict) for t in turns)
    assert turns[0]["question"].endswith("?")
    assert turns[1]["is_follow_up"] is True
    assert "Redis" in turns[1]["question"] or "slow" in turns[1]["question"]


# ===========================================================================
# 20. No NVIDIA reasoning left on the browser path
# ===========================================================================

def test_20_no_nvidia_reasoning_on_browser_path():
    assert not hasattr(svc, "_make_llm")
    assert not hasattr(svc, "evaluate_answer_llm")
    assert not hasattr(svc, "generate_mock_plan")
    assert not hasattr(svc, "build_mock_plan")
    import inspect
    src = inspect.getsource(svc)
    assert "ChatNVIDIA" not in src
    assert "langchain_nvidia" not in src
