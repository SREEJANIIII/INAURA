"""Skill Capability Map tests (core feature, deterministic, no LLM).

Covers: industry expectation generation, capability extraction, demonstrated
capability from GitHub evidence, evidence gaps, skill gaps, insufficient
industry data, provenance preservation, multiple evidence sources,
capability prioritization (reusing skill_engine), and no fabricated
capabilities. Existing analysis, scoring, and readiness logic untouched.
"""

import pytest

from app.services import capability_map as cm
from app.services import skill_engine as engine
from app.services.skill_taxonomy import normalize_skill


def _sig(skill, strength=0.75, depth=3, source="github", metadata=None, reason="evidence"):
    return {
        "skill": skill,
        "canonical_name": skill,
        "source": source,
        "source_type": source,
        "signal_strength": strength,
        "signal_value": strength,
        "source_reliability": 0.85 if source != "github" else 0.40,
        "reason": reason,
        "explanation": reason,
        "depth": depth,
        "metadata": metadata or {},
    }


def _req(skill, **kw):
    base = {
        "skill": skill,
        "skill_category": "Programming",
        "required_level": 0.85,
        "importance": 0.90,
        "demand": 0.80,
        "interview_relevance": 0.85,
        "industry_confidence": 0.90,
        "source": "O*NET 15-1252 via INAURA mapping heuristic",
        "source_url": "https://www.onetonline.org/link/summary/15-1252.00",
        "source_quality": 0.95,
        "evidence_strength": "moderate",
        "evidence_context": "Core competency context.",
        "role_relevance": "CORE",
        "description": "Skill description.",
        "supporting_chunks": [
            {"chunk_id": "chunk-x-1", "role": "Backend Developer",
             "topic": "Server Architecture", "source": "Stack Overflow 2024",
             "source_url": "https://survey.stackoverflow.co/2024/"},
        ],
    }
    base.update(kw)
    return base


def _assessment(skill, proficiency=0.0, confidence=0.0):
    return {"canonical_name": skill, "skill": skill,
            "proficiency": proficiency, "confidence": confidence}


# 1. Industry expectation generation -------------------------------------

def test_industry_expectations_carry_provenance():
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"),
        {"Python": [_sig("Python", depth=4)]}, _assessment("Python", 0.81, 0.6))
    assert len(out["industry_expectations"]) == len(cm.get_capability_blueprint("python"))
    first = out["industry_expectations"][0]
    assert first["title"]
    assert first["relevance"]
    assert out["requirement"]["source"].startswith("O*NET")
    assert out["requirement"]["source_quality"] == pytest.approx(0.95)
    assert out["requirement"]["supporting_chunks"][0]["chunk_id"] == "chunk-x-1"


def test_no_requirement_means_insufficient_data():
    out = cm.build_skill_capability("Backend Developer", None, {}, None)
    assert out["status"] == "insufficient_industry_data"
    assert out["capabilities"] == []
    assert out["demonstrated_capabilities"] == []
    assert "cannot define" in out["explanation"]


def test_weak_requirement_evidence_means_industry_gap():
    out = cm.build_skill_capability(
        "Backend Developer",
        _req("Python", evidence_strength="insufficient"),
        {"Python": [_sig("Python", depth=4)]}, _assessment("Python", 0.81, 0.6))
    assert out["status"] == "industry_gap"


# 2. Capability extraction -------------------------------------------------

def test_blueprints_valid_and_taxonomy_bound():
    assert cm.validate_blueprints() == []
    for slug, capabilities in cm.CAPABILITY_BLUEPRINTS.items():
        assert normalize_skill(slug) is not None, slug
        ids = [c["id"] for c in capabilities]
        assert len(ids) == len(set(ids))
        for cap in capabilities:
            assert cap["title"] and cap["observable_abilities"]
            assert cap["action"]


def test_capability_extraction_lists_abilities():
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), {}, _assessment("Python"))
    titles = [c["title"] for c in out["capabilities"]]
    assert "Build REST APIs" in titles
    rest = next(c for c in out["capabilities"] if c["id"] == "python-rest-apis")
    assert "Build REST APIs" in rest["observable_abilities"]
    assert "Implement validation and error handling" in rest["observable_abilities"]


# 3. Demonstrated capability from GitHub -----------------------------------

def test_demonstrated_capability_from_github_implementation():
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={
            "relevant_files": ["backend/app/api/users.py", "backend/app/services/auth.py"],
            "usage_status": "substantial"})],
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["backend/app/routes/users.py"],
            "usage_status": "used",
            "detected_usage_patterns": ["fastapi_app", "route_decorator"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.81, 0.6))
    demonstrated = {c["title"]: c for c in out["demonstrated_capabilities"]}
    assert "Build REST APIs" in demonstrated
    rest = demonstrated["Build REST APIs"]
    assert rest["support"] >= 0.75
    providers = {e["provider"] for e in rest["evidence"]}
    assert "github" in providers
    files = [f for e in rest["evidence"] for f in e["files"]]
    assert "backend/app/routes/users.py" in files
    assert all(e["depth"] >= 3 and e["reason"] for e in rest["evidence"])


# 4. Evidence gap ------------------------------------------------------------

def test_empty_evidence_is_evidence_gap_not_inability():
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), {}, _assessment("Python"))
    assert out["status"] == "evidence_gap"
    assert out["demonstrated_capabilities"] == []
    assert out["missing_capabilities"]
    assert out["skill_gap"] == []
    assert len(out["evidence_gap"]) == len(out["capabilities"])
    assert "absence of submitted evidence" in out["explanation"]
    assert "not confirmed inability" in out["explanation"]
    assert "does not know" not in out["explanation"].lower()


# 5. Skill gap -----------------------------------------------------------------

def test_implementation_without_capability_is_skill_gap():
    # Python L4 alone: fundamentals demonstrated, but the async capability has
    # no matching evidence while implementation exists -> skill_gap kind.
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={"relevant_files": ["a.py", "b.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.7, 0.5))
    assert "Write automated tests" in out["skill_gap"]
    assert "Write automated tests" not in out["evidence_gap"]
    # Partial support stays developing rather than a gap kind.
    assert "Build asynchronous services" not in out["skill_gap"]
    assert "Build asynchronous services" not in out["evidence_gap"]
    # The gap kind flows into engine prioritization as a skill gap.
    test_cap = next(c for c in out["missing_capabilities"]
                    if c["id"] == "python-testing")
    expected, _, _ = engine.calculate_prioritized_gap(
        gap_val=round(1.0 - test_cap["support"], 3),
        importance=0.90, demand=0.80, student_confidence=0.5,
        interview_relevance=0.85, industry_confidence=0.90,
        gap_type="skill_gap",
    )
    assert test_cap["priority"] == pytest.approx(expected)


# 6. Insufficient industry data --------------------------------------------------

def test_unknown_skill_has_no_fabricated_capabilities():
    out = cm.build_skill_capability(
        "Backend Developer", _req("QuantumFlux"), {"QuantumFlux": [_sig("QuantumFlux")]},
        _assessment("QuantumFlux", 0.5, 0.4))
    assert out["status"] == "insufficient_industry_data"
    assert out["capabilities"] == []
    assert out["industry_expectations"] == []
    assert "not invent" in out["explanation"]


# 7. Provenance preservation -----------------------------------------------------

def test_every_demonstrated_capability_has_provenance():
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={"relevant_files": ["a.py"]})],
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["b.py"], "detected_usage_patterns": ["fastapi_app"]})],
        "Testing": [_sig("Testing", depth=3, source="github",
                          metadata={"relevant_files": ["test_a.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.8, 0.6))
    assert out["demonstrated_capabilities"]
    for cap in out["demonstrated_capabilities"]:
        assert cap["evidence"], cap["title"]
        for entry in cap["evidence"]:
            assert entry["provider"]
            assert isinstance(entry["files"], list)
            assert entry["depth"] >= 1
            assert entry["reason"]
    blob = str(out)
    assert "def " not in blob and "import " not in blob  # no source contents


# 8. Multiple evidence sources ----------------------------------------------------

def test_multiple_sources_combine_in_evidence():
    grouped = {
        "Python": [
            _sig("Python", depth=4, source="github", metadata={"relevant_files": ["a.py"]}),
            _sig("Python", strength=0.60, depth=0, source="leetcode",
                 metadata={}, reason="84 Python submissions"),
        ],
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["b.py"], "usage_status": "used",
            "detected_usage_patterns": ["fastapi_app"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.8, 0.6))
    rest = next(c for c in out["demonstrated_capabilities"] if c["id"] == "python-rest-apis")
    assert {e["provider"] for e in rest["evidence"]} >= {"github"}
    assert out["evidence_sources"]
    assert {e["provider"] for e in out["evidence_sources"]} == {"github", "leetcode"}


# 9. Capability prioritization ------------------------------------------------------

def test_priority_reuses_engine_formula():
    grouped = {"Python": [_sig("Python", depth=4, metadata={"relevant_files": ["a.py"]})]}
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.7, 0.5))
    missing = {c["id"]: c for c in out["missing_capabilities"]}
    assert missing
    for cap in missing.values():
        expected, category, _ = engine.calculate_prioritized_gap(
            gap_val=round(1.0 - cap["support"], 3),
            importance=0.90, demand=0.80, student_confidence=0.5,
            interview_relevance=0.85, industry_confidence=0.90,
            gap_type=cap["status"] if cap["status"] in ("skill_gap", "evidence_gap") else "skill_gap",
        )
        # statuses developing/evidence_gap/skill_gap all flow through the engine
        assert cap["priority"] == pytest.approx(expected)
        assert cap["priority_category"] == category


def test_higher_importance_means_higher_priority():
    grouped = {}
    low = cm.build_skill_capability(
        "Backend Developer", _req("Python", importance=0.30), grouped, _assessment("Python"))
    high = cm.build_skill_capability(
        "Backend Developer", _req("Python", importance=0.95), grouped, _assessment("Python"))
    p_low = max(c["priority"] for c in low["missing_capabilities"])
    p_high = max(c["priority"] for c in high["missing_capabilities"])
    assert p_high > p_low
    assert low["priority"] == pytest.approx(p_low)
    assert high["priority"] == pytest.approx(p_high)


# 10. No fabricated capabilities ------------------------------------------------------

def test_readme_mention_never_demonstrates_implementation():
    grouped = {
        "Docker": [_sig("Docker", strength=0.40, depth=1, metadata={},
                          reason="mentioned in README")],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Docker"), grouped, _assessment("Docker", 0.2, 0.2))
    assert out["demonstrated_capabilities"] == []
    assert out["status"] == "evidence_gap"


def test_status_ladder_and_developing_state():
    # Partial support -> developing, never demonstrated.
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={"relevant_files": ["a.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.7, 0.5))
    assert out["status"] == "developing"
    developing = [c for c in out["missing_capabilities"] if c["status"] == "developing"]
    assert developing
    assert all(0 < c["support"] < 0.75 for c in developing)


def test_map_builder_filters_and_summarizes(monkeypatch):
    import app.services.capability_map as svc

    monkeypatch.setattr(svc.ars, "load_profile", lambda user_id: {"user_id": user_id})
    monkeypatch.setattr(svc.ars, "load_evidence", lambda user_id: ([], [], []))
    monkeypatch.setattr(
        svc.ars, "load_industry_requirements",
        lambda role: [_req("Python"), _req("Docker")],
    )
    result = svc.build_capability_map_for_user("user-1", "Backend Developer", skill="python")
    assert result["role"] == "Backend Developer"
    assert [s["skill"] for s in result["skills"]] == ["Python"]
    assert result["capability_model_version"] == cm.CAPABILITY_MODEL_VERSION
    assert result["summary"]["total_skills"] == 1
    assert sum(result["summary"]["by_status"].values()) == 1


def test_map_builder_requires_role(monkeypatch):
    import app.services.capability_map as svc
    from fastapi import HTTPException

    monkeypatch.setattr(svc.ars, "load_profile", lambda user_id: {"user_id": user_id})
    with pytest.raises(HTTPException):
        svc.build_capability_map_for_user("user-1", target_role="   ")


def test_endpoint_returns_map_shape_and_requires_auth(monkeypatch):
    import app.services.capability_map as svc
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.security import get_current_user
    from types import SimpleNamespace

    payload = {
        "role": "Backend Developer",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "capability_model_version": "capability-v1",
        "engine_version": "4C-v1",
        "skills": [],
        "summary": {"total_skills": 0, "by_status": {}},
    }

    async def fake_user():
        return SimpleNamespace(id="user-1", email="u@example.com")

    def fake_build(user_id, target_role=None, client=None, skill=None):
        assert user_id == "user-1"
        assert target_role == "Backend Developer"
        assert skill == "Python"
        return payload

    app.dependency_overrides[get_current_user] = fake_user
    monkeypatch.setattr(svc, "build_capability_map_for_user", fake_build)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/api/v1/analysis/capability-map",
                           params={"target_role": "Backend Developer", "skill": "Python"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["role"] == "Backend Developer"
            assert body["capability_model_version"] == "capability-v1"
            assert isinstance(body["skills"], list)
            app.dependency_overrides.clear()
            r2 = client.get("/api/v1/analysis/capability-map",
                            params={"target_role": "Backend Developer"})
            assert r2.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
