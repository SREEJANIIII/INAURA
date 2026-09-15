"""Phase 2: Capability-level evidence & explainability tests.

Deterministic, no LLM. Every capability explanation must be built only from
the existing blueprint rules and the existing grouped evidence via the same
_rule_matches() engine evaluate_capability() uses. Scoring untouched.
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


def _explain_by_id(out):
    return {c["id"]: c["capability_explanation"] for c in out["capabilities"]}


def _all_signal_files(grouped):
    files = set()
    for sigs in (grouped or {}).values():
        for sig in (sigs or []):
            for path in (((sig or {}).get("metadata") or {}).get("relevant_files") or []):
                if str(path or "").strip():
                    files.add(str(path))
    return files


def _all_providers(grouped):
    providers = set()
    for sigs in (grouped or {}).values():
        for sig in (sigs or []):
            provider = str((sig or {}).get("source") or (sig or {}).get("source_type") or "")
            if provider.strip():
                providers.add(provider.strip().lower())
    return providers


# TEST 1: strong implementation evidence -------------------------------------

def test_strong_evidence_explains_demonstrated():
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
    cap = next(c for c in out["capabilities"] if c["id"] == "python-rest-apis")
    assert cap["status"] == "demonstrated"
    expl = cap["capability_explanation"]
    assert expl["evidence_strength"] == "strong"
    assert expl["status_reason"]
    assert expl["summary"]
    assert expl["matched_signals"], "expected matched signals"
    assert expl["missing_signals"] == []
    # Explanation references actual evidence (provider + real file paths).
    assert "github" in expl["summary"].lower() or "rest apis" in expl["summary"].lower()
    real_files = _all_signal_files(grouped)
    for match in expl["matched_signals"]:
        assert match["signal"] and match["statement"] and match["source_type"]
        assert match["source_type"] in _all_providers(grouped)
        assert set(match["files"]) <= real_files, match["files"]
    assert set().union(*[set(m["files"]) for m in expl["matched_signals"]]) <= real_files
    # No fabricated evidence: every cited file/provider exists in grouped data.
    assert "backend/app/routes/users.py" in {
        f for m in expl["matched_signals"] for f in m["files"]}


# TEST 2: partial evidence ----------------------------------------------------

def test_partial_evidence_explains_developing():
    # Python-async: 3 rules (Python sig, REST patterns, Python files). With
    # only the Python sig (depth 4) the capability-specific support is
    # 1/2.5 = 0.4 -> developing (generic REST files alone does NOT make
    # validation developing — this test proves capability-specific path).
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={
            "relevant_files": ["backend/app/api/users.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped,
        _assessment("Python", 0.55, 0.5))
    cap = next(c for c in out["capabilities"] if c["id"] == "python-async")
    # Support is still the overall 0.4 (generic+files), status is developing
    # because Python's generic split keeps all rules specific.
    assert cap["status"] == "developing"
    expl = cap["capability_explanation"]
    assert expl["evidence_strength"] == "moderate"
    assert "partial" in expl["status_reason"].lower()
    # Matched contains the detected Python signal ...
    assert len(expl["matched_signals"]) == 1
    # ... and missing contains the unsupported capability-specific rule(s).
    assert len(expl["missing_signals"]) >= 1
    assert "did not find sufficient evidence" in expl["missing_signals"][0]["statement"]
    assert "cannot" not in expl["summary"].lower()
    # Generic REST alone must NOT become developing for REST validation:
    generic_grouped = {
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["backend/app/routes/users.py"],
            "usage_status": "used"})],
    }
    generic_out = cm.build_skill_capability(
        "Backend Developer", _req("REST APIs"), generic_grouped,
        _assessment("REST APIs", 0.55, 0.5))
    generic_cap = next(c for c in generic_out["capabilities"] if c["id"] == "rest-design")
    assert generic_cap["status"] == "unverified"
    assert generic_cap["capability_explanation"]["evidence_strength"] == "insufficient"
    assert generic_cap["capability_explanation"]["matched_signals"] == []


# TEST 3: no evidence ----------------------------------------------------------

def test_no_evidence_explains_unverified():
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), {}, _assessment("Python"))
    cap = next(c for c in out["capabilities"] if c["id"] == "python-testing")
    assert cap["status"] == "unverified"
    expl = cap["capability_explanation"]
    assert expl["evidence_strength"] == "insufficient"
    assert expl["matched_signals"] == []
    assert expl["missing_signals"], "expected blueprint-derived missing signals"
    assert "sufficient evidence" in expl["summary"].lower()
    assert "sufficient evidence" in expl["status_reason"].lower()
    assert cap["status"] != "confirmed_gap"
    blob = (expl["summary"] + " " + expl["status_reason"] + " "
            + " ".join(m["statement"] for m in expl["missing_signals"])).lower()
    assert "cannot" not in blob
    assert "unable" not in blob
    # Missing signals come from the blueprint (2 rules), nothing invented.
    assert len(expl["missing_signals"]) == 2


def test_weak_evidence_strength_for_low_partial():
    # Python depth 2 with 3 files: only the files rule matches -> support 0.2.
    grouped = {
        "Python": [_sig("Python", depth=2,
                          metadata={"relevant_files": ["a.py", "b.py", "c.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.5, 0.4))
    cap = next(c for c in out["capabilities"] if c["id"] == "python-async")
    assert 0.0 < cap["support"] < cm.DEVELOPING_SUPPORT
    assert cap["status"] == "unverified"
    assert cap["capability_explanation"]["evidence_strength"] == "weak"


# TEST 4: README-only / shallow evidence ----------------------------------------

def test_readme_only_respects_implementation_depth():
    grouped = {
        "Docker": [_sig("Docker", strength=0.40, depth=1, metadata={},
                          reason="mentioned in README")],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Docker"), grouped, _assessment("Docker", 0.2, 0.2))
    cap = next(c for c in out["capabilities"] if c["id"] == "docker-images")
    assert cap["status"] == "unverified"
    expl = cap["capability_explanation"]
    assert expl["evidence_strength"] == "insufficient"
    assert expl["matched_signals"] == []
    blob = (expl["summary"] + " " + expl["status_reason"]).lower()
    assert "implementation evidence supports" not in blob
    assert "demonstrated" not in blob or "whether" in blob  # no demonstrated claim


# TEST 5: provenance --------------------------------------------------------------

def test_matched_evidence_preserves_provenance():
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={
            "relevant_files": ["backend/app/api/users.py", "backend/app/main.py"],
            "usage_status": "substantial"})],
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["frontend/src/services/api.ts"],
            "usage_status": "used",
            "detected_usage_patterns": ["fastapi_app", "route_decorator"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.81, 0.6))
    cap = next(c for c in out["capabilities"] if c["id"] == "python-rest-apis")
    expl = cap["capability_explanation"]
    for match in expl["matched_signals"]:
        assert match["source_type"] == "github"
        assert match["files"], "file paths must remain traceable"
    cited = {f for m in expl["matched_signals"] for f in m["files"]}
    assert cited <= _all_signal_files(grouped)
    assert cited, "expected at least one traceable file path"


# TEST 6: no fabricated capability --------------------------------------------------

def test_no_evidence_invents_nothing():
    out = cm.build_skill_capability(
        "Backend Developer", _req("REST APIs"), {}, _assessment("REST APIs"))
    cap = next(c for c in out["capabilities"] if c["id"] == "rest-auth")
    expl = cap["capability_explanation"]
    assert expl["matched_signals"] == []
    # Missing signals reference only blueprint vocabulary (rule skills).
    assert expl["missing_signals"]
    for miss in expl["missing_signals"]:
        assert miss["signal"] and miss["statement"]
        assert "did not find sufficient evidence" in miss["statement"]
    blob = str(expl).lower()
    assert ".py" not in blob and ".ts" not in blob, "no invented file paths"
    assert "cannot" not in blob and "unable" not in blob


# TEST 7: existing scoring unchanged --------------------------------------------------

def test_explanation_layer_does_not_change_scoring():
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={"relevant_files": ["a.py"]})],
        "Testing": [_sig("Testing", depth=2, metadata={"relevant_files": ["t.py"]},
                          reason="test config")],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.7, 0.5))
    # Proficiency/confidence pass through unchanged.
    assert out["proficiency"] == 0.7 and out["confidence"] == 0.5
    # evaluate_capability output shape/values identical to the contract.
    for cap in out["capabilities"]:
        blueprint = next(b for b in cm.get_capability_blueprint("python")
                         if b["id"] == cap["id"])
        fresh = cm.evaluate_capability(blueprint, grouped)
        assert cap["support"] == fresh["support"]
        assert cap["evidence"] == fresh["evidence"]
        assert set(fresh.keys()) == {"support", "demonstrated", "evidence"}
    # Priority still follows the engine formula with the legacy gap mapping.
    from app.services import skill_engine as engine
    for miss in out["missing_capabilities"]:
        has_impl = any((s.get("depth", 0) or 0) >= 3
                       for s in grouped.get("Python", []))
        gap_type = "skill_gap" if has_impl else "evidence_gap"
        expected, category, _ = engine.calculate_prioritized_gap(
            gap_val=round(1.0 - miss["support"], 3),
            importance=0.90, demand=0.80, student_confidence=0.5,
            interview_relevance=0.85, industry_confidence=0.90,
            gap_type=gap_type,
        )
        assert miss["priority"] == expected
        assert miss["priority_category"] == category
    assert cm.validate_blueprints() == []


# Helpers: strength + reasons are deterministic ------------------------------------

def test_evidence_strength_thresholds():
    assert cm.classify_evidence_strength(1.0) == "strong"
    assert cm.classify_evidence_strength(0.75) == "strong"
    assert cm.classify_evidence_strength(0.50) == "moderate"
    assert cm.classify_evidence_strength(0.40) == "moderate"
    assert cm.classify_evidence_strength(0.20) == "weak"
    assert cm.classify_evidence_strength(0.0) == "insufficient"
    assert cm.classify_evidence_strength(None) == "insufficient"


def test_status_reasons_cover_all_statuses_without_inability_claims():
    for status in ("demonstrated", "developing", "unverified", "confirmed_gap"):
        reason = cm.build_status_reason(status)
        assert reason, status
    blob = " ".join(cm.build_status_reason(s) for s in
                     ("demonstrated", "developing", "unverified", "confirmed_gap")).lower()
    assert "cannot" not in blob
    assert "unable" not in blob
    assert "strong implementation evidence" in cm.build_status_reason("demonstrated").lower()
    assert "partial" in cm.build_status_reason("developing").lower()
    assert "sufficient evidence" in cm.build_status_reason("unverified").lower()


def test_every_capability_has_explanation_and_is_deterministic():
    grouped = {
        "Python": [_sig("Python", depth=4, metadata={"relevant_files": ["a.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.7, 0.5))
    for cap in out["capabilities"]:
        expl = cap["capability_explanation"]
        assert expl["summary"] and expl["status_reason"] and expl["evidence_strength"]
        assert isinstance(expl["matched_signals"], list)
        assert isinstance(expl["missing_signals"], list)
        # Strength mirrors support thresholds exactly.
        assert expl["evidence_strength"] == cm.classify_evidence_strength(cap["support"])
        # Matched + missing partition the blueprint rules (no loss, no overlap).
        blueprint = next(b for b in cm.get_capability_blueprint("python")
                         if b["id"] == cap["id"])
        assert (len(expl["matched_signals"]) + len(expl["missing_signals"])
                == len([r for r in blueprint.get("evidence_rules", [])
                        if isinstance(r, dict) and float(r.get("weight", 1.0) or 0.0) > 0]))
    again = cm.build_skill_capability(
        "Backend Developer", _req("Python"), grouped, _assessment("Python", 0.7, 0.5))
    assert [c["capability_explanation"] for c in again["capabilities"]] == [
        c["capability_explanation"] for c in out["capabilities"]]


# Phase 2 refinement: generic skill vs capability-specific evidence -------------

def test_generic_rest_not_validation_evidence():
    # A: Generic REST API evidence (signal + 5 files) must NOT become
    # validation evidence. Validation has no capability-specific rule;
    # generic alone stays unverified with explicit summary.
    grouped = {
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["a.py", "b.py", "c.py", "d.py", "e.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("REST APIs"), grouped,
        _assessment("REST APIs", 0.5, 0.4))
    cap = next(c for c in out["capabilities"] if c["id"] == "rest-validation")
    # Overall support is high (generic sig + files), but capability-specific
    # support is 0, so status stays unverified and strength insufficient.
    assert cap["support"] == 1.0  # scoring unchanged (overall)
    assert cap["status"] == "unverified"
    expl = cap["capability_explanation"]
    assert expl["evidence_strength"] == "insufficient"
    assert expl["matched_signals"] == []
    # Summary explicitly says no capability-specific validation evidence.
    assert "no capability-specific evidence for validate input" in expl["summary"].lower()
    assert "cannot" not in expl["summary"].lower()
    # Provenance: generic REST presence is not presented as validation support.
    assert all("validation" not in m["signal"].lower() or "rest apis" in m["signal"].lower()
               for m in expl["matched_signals"])


def test_generic_rest_not_security_evidence():
    # B: Generic REST API evidence must NOT become security evidence.
    grouped = {
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["a.py", "b.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("REST APIs"), grouped,
        _assessment("REST APIs", 0.5, 0.4))
    cap = next(c for c in out["capabilities"] if c["id"] == "rest-auth")
    assert cap["support"] == 0.667  # sig alone
    assert cap["status"] == "unverified"
    expl = cap["capability_explanation"]
    assert expl["matched_signals"] == []
    assert any("application security" in m["signal"].lower()
               for m in expl["missing_signals"])
    assert "no capability-specific evidence for secure apis" in expl["summary"].lower()


def test_generic_rest_not_documentation_evidence():
    # C: Generic REST API evidence must NOT become documentation evidence.
    grouped = {
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["a.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("REST APIs"), grouped,
        _assessment("REST APIs", 0.5, 0.4))
    cap = next(c for c in out["capabilities"] if c["id"] == "rest-docs")
    # Docs has only a generic signal rule; generic alone must not prove docs.
    assert cap["support"] == 1.0  # overall
    assert cap["status"] == "unverified"
    assert cap["capability_explanation"]["matched_signals"] == []
    assert cap["capability_explanation"]["evidence_strength"] == "insufficient"
    assert "no capability-specific evidence for document apis" in cap["capability_explanation"]["summary"].lower()


def test_no_specific_evidence_remains_unverified_not_developing():
    # D: Capability with no capability-specific evidence stays unverified.
    grouped = {
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["a.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("REST APIs"), grouped,
        _assessment("REST APIs", 0.5, 0.4))
    for cap_id in ("rest-validation", "rest-docs", "rest-auth", "rest-design"):
        cap = next(c for c in out["capabilities"] if c["id"] == cap_id)
        # None of these have capability-specific evidence with only generic.
        assert cap["status"] == "unverified", f"{cap_id} should be unverified"
        assert cap["capability_explanation"]["evidence_strength"] == "insufficient"
        # Must not be presented as Developing or Confirmed gap.
        assert cap["status"] not in ("developing", "confirmed_gap")
        # Missing signals, when present, are capability-specific (not generic).
        for miss in cap["capability_explanation"]["missing_signals"]:
            assert "implementation-level rest apis usage" not in miss["statement"].lower() or \
                   "route decorator" in miss["statement"].lower() or \
                   "application security" in miss["statement"].lower(), miss


def test_missing_signals_are_capability_specific():
    # E: Missing signals come only from the capability's own blueprint
    # and, for REST, only from its capability-specific rules.
    grouped = {
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["a.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("REST APIs"), grouped,
        _assessment("REST APIs", 0.5, 0.4))
    # Secure's missing must be Application Security, not generic REST sig.
    secure = next(c for c in out["capabilities"] if c["id"] == "rest-auth")
    assert len(secure["capability_explanation"]["missing_signals"]) == 1
    assert "application security" in secure["capability_explanation"]["missing_signals"][0]["signal"].lower()
    # Design's missing must be code patterns, not generic.
    design = next(c for c in out["capabilities"] if c["id"] == "rest-design")
    assert any("code patterns" in m["signal"].lower()
               for m in design["capability_explanation"]["missing_signals"])
    # Consume's missing must be http client pattern.
    clients = next(c for c in out["capabilities"] if c["id"] == "rest-clients")
    assert any("http client" in m["statement"].lower()
               for m in clients["capability_explanation"]["missing_signals"])
    # Generic "implementation-level REST APIs usage" must not appear as a
    # missing signal for capabilities where it is merely contextual.
    for cap in out["capabilities"]:
        for miss in cap["capability_explanation"]["missing_signals"]:
            assert not (miss["signal"] == "REST APIs implementation evidence" and
                        cap["id"] in ("rest-validation", "rest-auth")), \
                f"generic missing shown for {cap['id']}"


def test_refinement_does_not_change_scoring():
    # F: Scoring (proficiency/confidence/support/priority) unchanged.
    grouped = {
        "REST APIs": [_sig("REST APIs", depth=3, metadata={
            "relevant_files": ["a.py", "b.py"]})],
    }
    out = cm.build_skill_capability(
        "Backend Developer", _req("REST APIs"), grouped,
        _assessment("REST APIs", 0.7, 0.5))
    # Overall support still computed from all blueprint rules.
    design = next(c for c in out["capabilities"] if c["id"] == "rest-design")
    assert design["support"] == 0.5  # sig alone: 1/2
    validation = next(c for c in out["capabilities"] if c["id"] == "rest-validation")
    assert validation["support"] == 1.0  # sig + files (2 files) both match
    # Proficiency/confidence pass through.
    assert out["proficiency"] == 0.7 and out["confidence"] == 0.5
    # Priority still uses overall gap (engine formula).
    from app.services import skill_engine as engine
    for miss in out["missing_capabilities"]:
        gap_type = "skill_gap" if any(s.get("depth", 0) >= 3 for s in grouped.get("REST APIs", [])) else "evidence_gap"
        # Use has_impl logic as in service (REST depth3 => skill_gap)
        expected, cat, _ = engine.calculate_prioritized_gap(
            gap_val=round(1.0 - miss["support"], 3),
            importance=0.90, demand=0.80, student_confidence=0.5,
            interview_relevance=0.85, industry_confidence=0.90,
            gap_type=gap_type,
        )
        assert miss["priority"] == expected
    assert cm.validate_blueprints() == []
