"""Isolated tests for the experimental /ai-review-test feature.

The Gemini client is always faked: no real LLM calls, no API key needed.
The context carries RAW evidence only — the LLM computes all gaps itself.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import ai_review_test_service as svc


FAKE_CONTEXT = {
    "target_role": "Backend Developer",
    "profile": {"full_name": "Test Student", "college": "Test College"},
    "evidence": [{"evidence_type": "github", "title": "api"}],
    "projects": [],
    "certifications": [],
    "linkedin": "unavailable",
    "industry_requirements": [{"skill": "Python"}],
    "roadmap": "unavailable",
}


class FakeLLM:
    """Plain generate only — no function calling (mirrors the AFC-free path)."""

    def __init__(self, content=None):
        self.calls = []
        self.content = content if content is not None else json.dumps(
            {"executive_summary": "ok", "ratings": {"overall_rating": 70}}
        )

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(
            content=self.content,
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


def _patch_context(monkeypatch):
    async def fake_build(user_id, target_role=None):
        return dict(FAKE_CONTEXT)

    monkeypatch.setattr(svc, "build_review_context", fake_build)


def test_gemini_invoked_exactly_once(monkeypatch):
    _patch_context(monkeypatch)
    fake = FakeLLM()
    out = asyncio.run(svc.run_ai_review("user-1", _llm=fake))
    assert len(fake.calls) == 1
    assert out["meta"]["llm_calls"] == 1
    assert out["review"]["executive_summary"] == "ok"
    assert out["meta"]["usage"] == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


def test_prompt_contains_raw_context_but_no_engine_math(monkeypatch):
    _patch_context(monkeypatch)
    fake = FakeLLM()
    asyncio.run(svc.run_ai_review("user-1", _llm=fake))
    sent = fake.calls[0]
    user_msg = next(m for m in sent if m.get("role") == "user")["content"]
    assert "Backend Developer" in user_msg
    assert "github" in user_msg
    assert "Test Student" in user_msg
    # Raw material only: no deterministic-engine outputs for the LLM to copy
    for key in ("proficiency", "readiness_score", "skill_gaps", "evidence_gaps",
                "skill_assessments", "dsa_gaps"):
        assert key not in user_msg
    # Secrets must never be in the prompt even if present in context
    assert "GOOGLE_API_KEY" not in user_msg


def test_no_function_calling_used(monkeypatch):
    """The single call is a plain generate (no with_structured_output / AFC)."""
    _patch_context(monkeypatch)
    fake = FakeLLM()
    assert not hasattr(fake, "with_structured_output")
    out = asyncio.run(svc.run_ai_review("user-1", _llm=fake))
    assert len(fake.calls) == 1
    assert out["review"]["ratings"]["overall_rating"] == 70


def test_unparseable_response_is_safe_error(monkeypatch):
    _patch_context(monkeypatch)
    from fastapi import HTTPException

    fake = FakeLLM(content="not json at all!!!")
    with pytest.raises(HTTPException) as e:
        asyncio.run(svc.run_ai_review("user-1", _llm=fake))
    assert e.value.status_code == 502


def test_fenced_json_with_string_items_is_accepted(monkeypatch):
    _patch_context(monkeypatch)
    body = json.dumps({
        "executive_summary": "fenced ok",
        "critical_gaps": ["Python needs work", {"skill": "SQL", "severity": "high"}],
        "strengths": "single string strength",
        "ratings": {"overall_rating": 65},
    })
    fake = FakeLLM(content=f"Here is the review:\n```json\n{body}\n```\nGood luck!")
    out = asyncio.run(svc.run_ai_review("user-1", _llm=fake))
    assert out["review"]["executive_summary"] == "fenced ok"
    assert out["review"]["critical_gaps"][0]["explanation"] == "Python needs work"
    assert out["review"]["strengths"] == ["single string strength"]


def test_garbage_types_still_fail_safe(monkeypatch):
    _patch_context(monkeypatch)
    from fastapi import HTTPException

    fake = FakeLLM(content=json.dumps({"ratings": {"overall_rating": {"nested": "object"}}}))
    with pytest.raises(HTTPException) as e:
        asyncio.run(svc.run_ai_review("user-1", _llm=fake))
    assert e.value.status_code == 502
    assert "re-run" in e.value.detail


def test_missing_api_key_fails_cleanly(monkeypatch):
    monkeypatch.setattr(
        svc, "get_settings",
        lambda: SimpleNamespace(google_api_key=None, gemini_model="gemini-2.5-flash"),
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        svc._make_llm()
    assert e.value.status_code == 503
    assert "GOOGLE_API_KEY" in e.value.detail


def test_scrub_removes_secrets_and_pii():
    dirty = {
        "name": "Ada",
        "email": "ada@example.com",
        "access_token": "tok",
        "nested": {"client_secret": "s", "skills": ["Python"]},
        "list": [{"password": "p", "ok": 1}],
    }
    clean = svc._scrub(dirty)
    blob = json.dumps(clean)
    assert "tok" not in blob and "ada@example.com" not in blob
    assert clean["nested"]["skills"] == ["Python"]
    assert clean["list"] == [{"ok": 1}]


def test_endpoint_structural(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.security import get_current_user
    from app.api.v1.endpoints import ai_review_test as ep

    async def fake_user():
        return SimpleNamespace(id="user-1", email="u@example.com")

    async def fake_run(user_id, target_role=None):
        assert user_id == "user-1"
        return {"review": {"executive_summary": "ep ok"}, "meta": {"llm_calls": 1}}

    app.dependency_overrides[get_current_user] = fake_user
    monkeypatch.setattr(ep.review_service, "run_ai_review", fake_run)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/api/v1/ai-review-test", json={})
            assert r.status_code == 200, r.text
            assert r.json()["review"]["executive_summary"] == "ep ok"
            # Unauthenticated stays rejected (protected route)
            app.dependency_overrides.clear()
            r2 = client.post("/api/v1/ai-review-test", json={})
            assert r2.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
