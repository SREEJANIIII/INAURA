"""Phase 1: 'What INAURA knows' interpretation layer tests.

Deterministic, no LLM. Verifies the new structured field reuses existing
evaluation/provenance without changing scoring.
"""

from app.services import capability_map as cm


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


def test_strong_implementation_evidence_is_demonstrated():
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={
            "relevant_files": ["backend/app/api/users.py"],
            "usage_status": "substantial"})],
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["backend/app/routes/users.py"],
            "usage_status": "used",
            "detected_usage_patterns": ["fastapi_app", "route_decorator"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.81, 0.6))
    knows = out["what_inaura_knows"]
    assert knows and knows["summary"]
    assert knows["demonstrated_areas"], "expected demonstrated areas"
    assert knows["evidence_summary"]["implementation_evidence_count"] > 0
    for area in knows["demonstrated_areas"]:
        assert area["status"] == "demonstrated"
        assert area["support"] >= cm.DEMONSTRATED_SUPPORT
        assert area["capability_id"] and area["capability_title"] and area["statement"]
    # REST APIs capability must be demonstrated with implementation language.
    rest = next(a for a in knows["demonstrated_areas"]
                if a["capability_id"] == "python-rest-apis")
    assert "implementation" in rest["statement"].lower()
    # Existing fields untouched.
    assert out["proficiency"] == 0.81 and out["confidence"] == 0.6
    assert any(c["title"] == "Build REST APIs" for c in out["demonstrated_capabilities"])


def test_partial_evidence_is_developing_not_demonstrated():
    # Testing signal at depth 2 without test patterns: 1/2 rules -> support 0.5.
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={"relevant_files": ["a.py"]})],
        "Testing": [_sig("Testing", depth=2, metadata={"relevant_files": ["t.py"]},
                          reason="test config")],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.7, 0.5))
    knows = out["what_inaura_knows"]
    developing = {a["capability_id"]: a for a in knows["developing_areas"]}
    assert "python-testing" in developing
    area = developing["python-testing"]
    assert cm.DEVELOPING_SUPPORT <= area["support"] < cm.DEMONSTRATED_SUPPORT
    assert area["status"] == "developing"
    assert "does not fully demonstrate" in area["statement"]
    # No false claim: partial capability must not appear as demonstrated.
    demonstrated_ids = {a["capability_id"] for a in knows["demonstrated_areas"]}
    assert "python-testing" not in demonstrated_ids


def test_no_evidence_is_unverified_not_confirmed_gap():
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), {}, _assessment("Python"))
    knows = out["what_inaura_knows"]
    assert knows["demonstrated_areas"] == []
    assert knows["developing_areas"] == []
    assert knows["unverified_areas"], "all capabilities unverified"
    for area in knows["unverified_areas"]:
        assert area["status"] == "unverified", area
        assert area["status"] != "confirmed_gap"
        assert "sufficient evidence" in area["statement"]
        assert "cannot" not in area["statement"].lower()
        assert "unable" not in area["statement"].lower()
    assert knows["evidence_summary"]["evidence_count"] == 0
    assert knows["evidence_summary"]["implementation_evidence_count"] == 0
    assert "limited evidence" in knows["summary"].lower()
    # Existing gap distinction preserved: evidence_gap, never skill_gap.
    assert out["skill_gap"] == []
    assert out["evidence_gap"]


def test_readme_mention_never_demonstrates_implementation():
    grouped = {
        "Docker": [_sig("Docker", strength=0.40, depth=1, metadata={},
                          reason="mentioned in README")],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Docker"), grouped, _assessment("Docker", 0.2, 0.2))
    knows = out["what_inaura_knows"]
    assert knows["demonstrated_areas"] == []
    assert knows["developing_areas"] == []
    assert all(a["status"] == "unverified" for a in knows["unverified_areas"])
    assert out["demonstrated_capabilities"] == []
    assert knows["evidence_summary"]["implementation_evidence_count"] == 0


def test_absence_of_evidence_is_not_confirmed_inability():
    # No signals at all: every area unverified, none confirmed_gap.
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), {}, _assessment("Python"))
    knows = out["what_inaura_knows"]
    statuses = {a["status"] for a in knows["unverified_areas"]}
    assert statuses == {"unverified"}
    blob = (knows["summary"] + " " + " ".join(
        a["statement"] for a in knows["unverified_areas"])).lower()
    assert "cannot" not in blob
    assert "unable" not in blob
    assert "never" not in blob or "never satisfies" not in blob  # no ability claim


def test_confirmed_gap_only_with_implementation_evidence():
    # Python L4 alone: testing capability unmet while implementation exists.
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={"relevant_files": ["a.py", "b.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.7, 0.5))
    knows = out["what_inaura_knows"]
    by_id = {a["capability_id"]: a for a in (
        knows["demonstrated_areas"] + knows["developing_areas"]
        + knows["unverified_areas"])}
    testing = by_id["python-testing"]
    # support == 0 with skill-level implementation -> confirmed_gap.
    assert testing["support"] == 0.0
    assert testing["status"] == "confirmed_gap"
    assert "does not demonstrate" in testing["statement"]
    assert "cannot" not in testing["statement"].lower()
    # Existing skill_gap list still carries the same capability (distinction kept).
    assert "Write automated tests" in out["skill_gap"]


def test_evidence_summary_reuses_provenance():
    grouped = {
        "Python": [
            _sig("Python", depth=4, source="github", metadata={"relevant_files": ["a.py"]}),
            _sig("Python", strength=0.60, depth=0, source="leetcode",
                 metadata={}, reason="84 Python submissions"),
        ],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.8, 0.6))
    summary = out["what_inaura_knows"]["evidence_summary"]
    assert summary["evidence_count"] == 2
    assert set(summary["source_types"]) == {"github", "leetcode"}
    assert summary["implementation_evidence_count"] == 1
    # Provenance intact: path-only, no source contents.
    assert out["evidence_sources"]
    blob = str(out["what_inaura_knows"]) + str(out["evidence_sources"])
    assert "def " not in blob and "import " not in blob


def test_status_thresholds_and_helpers():
    assert cm.DEMONSTRATED_SUPPORT == 0.75
    assert cm.DEVELOPING_SUPPORT == 0.40
    assert cm.classify_capability_status(0.90, False) == "demonstrated"
    assert cm.classify_capability_status(0.75, False) == "demonstrated"
    assert cm.classify_capability_status(0.50, False) == "developing"
    assert cm.classify_capability_status(0.40, True) == "developing"
    assert cm.classify_capability_status(0.0, False) == "unverified"
    assert cm.classify_capability_status(0.0, True) == "confirmed_gap"
    assert cm.classify_capability_status(0.20, True) == "unverified"
    # evaluate_capability scoring untouched: demonstrated bool still threshold-based.
    cap = {"evidence_rules": [{"kind": "signal", "skill": "Python", "min_depth": 3}]}
    result = cm.evaluate_capability(cap, {"Python": [_sig("Python", depth=4)]})
    assert result["support"] == 1.0 and result["demonstrated"] is True


def test_scoring_and_blueprints_unchanged():
    assert cm.validate_blueprints() == []
    grouped = {"Python": [_sig("Python", depth=4, metadata={"relevant_files": ["a.py"]})]}
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.7, 0.5))
    # Proficiency/confidence pass through unchanged.
    assert out["proficiency"] == 0.7 and out["confidence"] == 0.5
    # Capabilities keep support + evidence from evaluate_capability.
    for cap in out["capabilities"]:
        assert "support" in cap and "evidence" in cap
        assert "status" in cap and "knowledge_statement" in cap
    # Summary is deterministic.
    again = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.7, 0.5))
    assert again["what_inaura_knows"] == out["what_inaura_knows"]


# Status-consistency fix: WHAT INAURA KNOWS vs STILL DEVELOP -----------------

def _knowledge_by_id(knows):
    return {a["capability_id"]: a for a in (
        knows["demonstrated_areas"] + knows["developing_areas"]
        + knows["unverified_areas"])}


def test_low_partial_is_unverified_and_evidence_gap_not_developing():
    # 0 < support < 0.40: actual weak signal, but insufficient to claim
    # developing. Must be unverified in WHAT INAURA KNOWS and evidence_gap
    # in STILL DEVELOP — never "Developing".
    grouped = {
        "Python": [_sig("Python", depth=2,
                          metadata={"relevant_files": ["a.py", "b.py", "c.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.5, 0.4))
    knows = out["what_inaura_knows"]
    by_id = _knowledge_by_id(knows)
    low = by_id["python-async"]
    assert 0.0 < low["support"] < cm.DEVELOPING_SUPPORT
    assert low["status"] == "unverified"
    missing = {c["id"]: c for c in out["missing_capabilities"]}
    assert missing["python-async"]["status"] == "evidence_gap"
    assert missing["python-async"]["status"] != "developing"
    assert "Build asynchronous services" in out["evidence_gap"]
    assert "Build asynchronous services" not in out["skill_gap"]


def test_still_develop_derives_from_same_knowledge_status():
    # Every non-demonstrated capability: knowledge status and STILL DEVELOP
    # status must agree (developing->developing, unverified->evidence_gap,
    # confirmed_gap->confirmed_gap). Reported bug: Validate Unverified vs
    # Developing must never recur.
    grouped = {
        "REST APIs": [_sig("REST APIs", depth=2,
                             metadata={"relevant_files": ["a.py", "b.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("REST APIs"), grouped,
        _assessment("REST APIs", 0.5, 0.4))
    knows = out["what_inaura_knows"]
    by_id = _knowledge_by_id(knows)
    missing = {c["id"]: c for c in out["missing_capabilities"]}
    assert missing, "expected STILL DEVELOP entries"
    for cap_id, miss in missing.items():
        knowledge_status = by_id[cap_id]["status"]
        assert miss["support"] == by_id[cap_id]["support"]
        if knowledge_status == "developing":
            assert miss["status"] == "developing", cap_id
        elif knowledge_status == "confirmed_gap":
            assert miss["status"] == "confirmed_gap", cap_id
        else:
            assert knowledge_status == "unverified", cap_id
            assert miss["status"] == "evidence_gap", cap_id
        # The contradiction itself: unverified must never read as Developing.
        if knowledge_status == "unverified":
            assert miss["status"] != "developing", cap_id


def test_no_evidence_never_becomes_developing_or_confirmed_gap():
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), {}, _assessment("Python"))
    for miss in out["missing_capabilities"]:
        assert miss["status"] == "evidence_gap", miss["id"]
        assert miss["status"] not in ("developing", "confirmed_gap", "skill_gap")
    assert out["skill_gap"] == []
    assert len(out["evidence_gap"]) == len(out["capabilities"])
    knows = out["what_inaura_knows"]
    assert {a["status"] for a in knows["unverified_areas"]} == {"unverified"}


def test_confirmed_gap_maps_to_confirmed_gap_and_skill_gap_list():
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={"relevant_files": ["a.py", "b.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.7, 0.5))
    knows = out["what_inaura_knows"]
    by_id = _knowledge_by_id(knows)
    assert by_id["python-testing"]["status"] == "confirmed_gap"
    missing = {c["id"]: c for c in out["missing_capabilities"]}
    assert missing["python-testing"]["status"] == "confirmed_gap"
    # Backwards compat: confirmed gaps still populate the legacy skill_gap list.
    assert "Write automated tests" in out["skill_gap"]
    assert "Write automated tests" not in out["evidence_gap"]
    # Priority calculation unchanged: still uses skill_gap weighting.
    from app.services import skill_engine as engine
    test_cap = missing["python-testing"]
    expected, _, _ = engine.calculate_prioritized_gap(
        gap_val=round(1.0 - test_cap["support"], 3),
        importance=0.90, demand=0.80, student_confidence=0.5,
        interview_relevance=0.85, industry_confidence=0.90,
        gap_type="skill_gap",
    )
    assert test_cap["priority"] == expected
