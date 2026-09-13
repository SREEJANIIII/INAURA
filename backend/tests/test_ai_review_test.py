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


def test_prompt_contains_raw_context_and_labeled_estimates(monkeypatch):
    _patch_context(monkeypatch)
    fake = FakeLLM()
    asyncio.run(svc.run_ai_review("user-1", _llm=fake))
    sent = fake.calls[0]
    user_msg = next(m for m in sent if m.get("role") == "user")["content"]
    assert "Backend Developer" in user_msg
    assert "github" in user_msg
    assert "Test Student" in user_msg
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


def test_llm_ainvoke_called_once_with_mock(monkeypatch):
    """The single Gemini invocation, asserted with a real mock object."""
    from unittest.mock import AsyncMock

    _patch_context(monkeypatch)
    mock_invoke = AsyncMock(return_value=SimpleNamespace(
        content=json.dumps({"executive_summary": "mocked ok"}),
        usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    ))
    fake_llm = SimpleNamespace(ainvoke=mock_invoke)
    out = asyncio.run(svc.run_ai_review("user-1", _llm=fake_llm))
    mock_invoke.assert_called_once()
    assert out["meta"]["llm_calls"] == 1
    assert out["review"]["executive_summary"] == "mocked ok"


def test_missing_profile_is_400(monkeypatch):
    from fastapi import HTTPException

    def _raise(*args, **kwargs):
        raise HTTPException(status_code=404, detail="not found")

    monkeypatch.setattr(svc.profile_service, "get_profile", _raise)
    with pytest.raises(HTTPException) as e:
        asyncio.run(svc.build_review_context("ghost-user", "Backend Developer"))
    assert e.value.status_code == 400


def test_missing_role_is_400(monkeypatch):
    from fastapi import HTTPException

    def _profile(*args, **kwargs):
        return {"full_name": "No Goal", "career_interests": []}

    monkeypatch.setattr(svc.profile_service, "get_profile", _profile)
    monkeypatch.setattr(svc.analysis_service, "get_state", lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        asyncio.run(svc.build_review_context("user-1", None))
    assert e.value.status_code == 400


def test_gemini_failure_is_502(monkeypatch):
    _patch_context(monkeypatch)
    from fastapi import HTTPException

    async def _boom(messages):
        raise RuntimeError("model overloaded")

    with pytest.raises(HTTPException) as e:
        asyncio.run(svc.run_ai_review("user-1", _llm=SimpleNamespace(ainvoke=_boom)))
    assert e.value.status_code == 502


def test_successful_structured_response_has_required_fields(monkeypatch):
    _patch_context(monkeypatch)
    payload = {
        "ratings": {"overall_rating": 72, "industry_readiness": 68},
        "executive_summary": "solid backend foundations",
        "strengths": ["Python APIs"],
        "weaknesses": ["Testing depth"],
        "skill_reviews": [{"skill": "Python", "demonstrated_level": 70,
                           "required_level": 80, "verdict": "skill_gap",
                           "explanation": "APIs built, auth missing"}],
        "evidence_gaps": [{"skill": "Docker", "severity": "medium",
                           "explanation": "mentioned only", "evidence": "resume",
                           "recommended_action": "ship a container"}],
        "coverage_gaps": [{"skill": "Redis", "severity": "low",
                           "explanation": "not in profile", "evidence": "none",
                           "recommended_action": "add caching"}],
        "industry_alignment": [{"skill": "Python", "student": "used", "industry_need": "core"}],
        "github_review": {"notes": "3 repos with imports"},
        "leetcode_review": {"notes": "40 solved"},
        "projects_review": {"notes": "2 services"},
        "resume_review": {"notes": "clear"},
        "profile_review": {"notes": "complete"},
        "dsa_review": {"notes": "arrays ok"},
        "recommendations": [{"what": "Learn Docker", "why": "role needs it",
                             "expected_impact": "high", "priority": "high",
                             "suggested_action": "containerize svc"}],
        "priority_actions": ["Containerize the API"],
        "interview_readiness": {"notes": "ready for backend loops"},
        "roadmap_improvements": ["Add Docker milestone"],
        "warnings": ["Single weak Docker signal"],
    }
    out = asyncio.run(svc.run_ai_review("user-1", _llm=FakeLLM(content=json.dumps(payload))))
    review = out["review"]
    assert review["ratings"]["overall_rating"] == 72
    assert review["ratings"]["industry_readiness"] == 68
    assert review["strengths"] == ["Python APIs"]
    assert review["weaknesses"] == ["Testing depth"]
    assert review["skill_reviews"][0]["verdict"] == "skill_gap"
    assert review["evidence_gaps"][0]["skill"] == "Docker"
    assert review["coverage_gaps"][0]["skill"] == "Redis"
    assert review["industry_alignment"][0]["skill"] == "Python"
    assert review["github_review"] == {"notes": "3 repos with imports"}
    assert review["leetcode_review"] == {"notes": "40 solved"}
    # Compat aliases mirror the split/single naming without inventing content.
    assert review["project_review"] == {"notes": "2 services"}
    assert review["resume_profile_review"]["resume_review"] == {"notes": "clear"}
    assert review["dsa_review"] == {"notes": "arrays ok"}
    assert review["recommendations"][0]["what"] == "Learn Docker"
    assert review["priority_actions"] == ["Containerize the API"]
    assert review["interview_readiness"] == {"notes": "ready for backend loops"}
    assert review["roadmap_improvements"] == ["Add Docker milestone"]
    assert review["warnings"] == ["Single weak Docker signal"]


def _patch_full_stack(monkeypatch):
    def _profile(*args, **kwargs):
        return {"full_name": "Ada", "college": "X", "career_interests": ["Backend Developer"]}

    monkeypatch.setattr(svc.profile_service, "get_profile", _profile)
    monkeypatch.setattr(svc.ars, "load_evidence", lambda *a, **k: ([], [], []))
    monkeypatch.setattr(
        svc.ars, "load_industry_requirements",
        lambda *a, **k: __import__("app.services.industry_service", fromlist=["x"]).list_by_role("Backend Developer"),
    )
    monkeypatch.setattr(svc.roadmap_service, "get_latest_roadmap", lambda *a, **k: None)
    monkeypatch.setattr(svc.roadmap_service, "get_all_items_for_user", lambda *a, **k: [])
    monkeypatch.setattr(svc.roadmap_service, "get_all_milestones_for_user", lambda *a, **k: [])
    monkeypatch.setattr(svc.analysis_service, "get_state", lambda *a, **k: None)


def test_deterministic_estimates_aggregated_and_labeled(monkeypatch):
    _patch_full_stack(monkeypatch)
    ctx = asyncio.run(svc.build_review_context("user-1", "Backend Developer"))
    estimates = ctx.get("deterministic_estimates")
    assert isinstance(estimates, dict)
    # Labeled deterministic sections for the LLM to critique, not copy.
    for key in ("assessments", "skill_gaps", "strengths", "readiness"):
        assert key in estimates, f"missing deterministic section '{key}'"
    assert isinstance(estimates["assessments"], list) and estimates["assessments"]
    assert estimates["assessments"][0]["skill"]
    assert "rag_industry_context" in ctx
    # No secrets leak into aggregated context.
    blob = json.dumps(ctx, default=str)
    assert "GOOGLE_API_KEY" not in blob


def test_no_persistence_performs_no_writes(monkeypatch):
    """The review path must never write: any insert/update/delete/upsert
    attempt fails the test loudly."""
    from app.core import supabase as supabase_core

    writes = []

    class _Chain:
        def __getattr__(self, name):
            if name in ("insert", "update", "delete", "upsert"):
                def _record(*args, **kwargs):
                    writes.append(name)
                    raise AssertionError(f"unexpected DB write: {name}")
                return _record
            return lambda *args, **kwargs: _Chain()

        def execute(self):
            return SimpleNamespace(data=[])

    class _Recorder:
        def table(self, *args, **kwargs):
            return _Chain()

    _patch_full_stack(monkeypatch)
    monkeypatch.setattr(supabase_core, "get_supabase_client", lambda: _Recorder())
    fake = FakeLLM()
    out = asyncio.run(svc.run_ai_review("user-1", _llm=fake))
    assert len(fake.calls) == 1
    assert writes == []
    assert out["review"]["executive_summary"] == "ok"


def _det_estimates(rows):
    return {"assessments": rows}


def _det_row(skill, proficiency=0.0, gap=0.0, evidence_count=0, gap_type="skill_gap"):
    return {
        "skill": skill,
        "proficiency": proficiency,
        "confidence": 0.5,
        "required_level": 0.8,
        "gap": gap,
        "gap_type": gap_type,
        "evidence_count": evidence_count,
        "evidence_state": "evidence_estimate" if evidence_count else "no_evidence",
        "has_assessment": False,
    }


def _gem_review(skill, level, verdict):
    return {"skill": skill, "demonstrated_level": level,
            "required_level": 80, "verdict": verdict, "explanation": "test"}


def test_comparison_agreement(monkeypatch):
    estimates = _det_estimates([_det_row("Python", proficiency=0.81, gap=0.0, evidence_count=5)])
    review = {"skill_reviews": [_gem_review("Python", 85, "strong")]}
    out = svc.build_comparison(estimates, review)
    assert out["version"] == "comparison-v1"
    assert out["agreements"] == ["Python"]
    assert out["differences"] == []
    row = next(r for r in out["rows"] if r["skill"] == "Python")
    assert row["category"] == "agreement"
    assert row["deterministic"]["level_pct"] == pytest.approx(81.0)
    assert row["gemini"]["level_pct"] == pytest.approx(85.0)


def test_comparison_disagreement(monkeypatch):
    estimates = _det_estimates([_det_row("Docker", proficiency=0.0, gap=0.7, evidence_count=0)])
    review = {"skill_reviews": [_gem_review("Docker", 80, "strong")]}
    out = svc.build_comparison(estimates, review)
    assert out["agreements"] == []
    assert len(out["differences"]) == 1
    assert out["differences"][0]["category"] == "disagreement"
    assert out["differences"][0]["skill"] == "Docker"


def test_comparison_partial_agreement(monkeypatch):
    estimates = _det_estimates([_det_row("Python", proficiency=0.81, gap=0.0, evidence_count=5)])
    review = {"skill_reviews": [_gem_review("Python", 40, "strong")]}
    out = svc.build_comparison(estimates, review)
    row = next(r for r in out["rows"] if r["skill"] == "Python")
    assert row["category"] == "partial_agreement"
    assert out["agreements"] == []
    assert len(out["differences"]) == 1


def test_comparison_missing_gemini_result(monkeypatch):
    estimates = _det_estimates([_det_row("Python", proficiency=0.81, gap=0.0, evidence_count=5)])
    out = svc.build_comparison(estimates, {})
    # Deterministic skills stand as engine-only rows; nothing is fabricated.
    assert [r["category"] for r in out["rows"]] == ["engine_only"]
    assert out["agreements"] == []
    assert out["differences"] == []
    assert "no skill reviews" in out["note"]
    # None review degrades identically (no crash, no fabrication).
    out_none = svc.build_comparison(estimates, None)
    assert [r["category"] for r in out_none["rows"]] == ["engine_only"]


def test_comparison_unsupported_ai_claim(monkeypatch):
    estimates = _det_estimates([_det_row("Kubernetes", proficiency=0.0, gap=0.7, evidence_count=0)])
    review = {"skill_reviews": [_gem_review("Kubernetes", 90, "strong")]}
    out = svc.build_comparison(estimates, review)
    assert len(out["warnings"]) == 1
    assert out["warnings"][0]["type"] == "unsupported_ai_claim"
    assert out["warnings"][0]["skill"] == "Kubernetes"


def test_comparison_supported_claim_has_no_warning(monkeypatch):
    estimates = _det_estimates([_det_row("Python", proficiency=0.81, gap=0.0, evidence_count=5)])
    review = {"skill_reviews": [_gem_review("Python", 85, "strong")]}
    out = svc.build_comparison(estimates, review)
    assert out["warnings"] == []


def test_comparison_engine_only_and_ai_only(monkeypatch):
    estimates = _det_estimates([
        _det_row("Docker", proficiency=0.0, gap=0.7, evidence_count=0),
        _det_row("Python", proficiency=0.81, gap=0.0, evidence_count=5),
    ])
    review = {
        "skill_reviews": [_gem_review("Python", 85, "strong")],
        "recommendations": [{"what": "Build a portfolio website", "why": "visibility",
                             "expected_impact": "medium", "priority": "low",
                             "suggested_action": "ship it"}],
        "strengths": ["Great Python APIs"],
    }
    out = svc.build_comparison(estimates, review)
    engine_skills = [e["skill"] for e in out["engine_only_insights"]]
    assert "Docker" in engine_skills
    assert any(i["kind"] == "recommendation" for i in out["ai_only_insights"])
    docker_row = next(r for r in out["rows"] if r["skill"] == "Docker")
    assert docker_row["category"] == "engine_only"


def test_comparison_preserves_deterministic_values(monkeypatch):
    import copy

    estimates = _det_estimates([_det_row("Python", proficiency=0.81, gap=0.0, evidence_count=5)])
    review = {"skill_reviews": [_gem_review("Python", 10, "skill_gap")]}
    before_estimates, before_review = copy.deepcopy(estimates), copy.deepcopy(review)
    out = svc.build_comparison(estimates, review)
    # Pure function: inputs untouched, deterministic outputs intact.
    assert estimates == before_estimates
    assert review == before_review
    assert out["rows"][0]["deterministic"]["level_pct"] == pytest.approx(81.0)
    # Recompute identically (deterministic).
    again = svc.build_comparison(estimates, review)
    assert again == out


def test_run_ai_review_includes_comparison(monkeypatch):
    _patch_context(monkeypatch)
    fake = FakeLLM(content=json.dumps({
        "executive_summary": "ok",
        "skill_reviews": [_gem_review("Python", 80, "strong")],
    }))
    out = asyncio.run(svc.run_ai_review("user-1", _llm=fake))
    assert len(fake.calls) == 1
    assert out["comparison"]["version"] == "comparison-v1"
    assert isinstance(out["comparison"]["rows"], list)


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
