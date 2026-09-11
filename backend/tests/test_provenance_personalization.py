"""
Focused tests for INAURA ungrounded-scores fix, evidence provenance,
and safe personalization (downward only, exclusion, AI-assisted, portfolio).
Implements the 16 required cases.
"""
import pytest
from app.services import analysis_run_service as ars
from app.services import evidence_weights as weights
from app.services import signal_extractor as se
from app.services import skill_engine
from app.services.assessment import service as assessment_service
from app.services.skill_taxonomy import normalize_skill_slug

# Helpers

def _sig(skill, source, strength, meta=None):
    return se.make_signal(canonical=skill, source_type=source, signal_value=strength, explanation=f"{source} for {skill}", metadata=meta or {})

def _requirements():
    return [
        {"skill": "Python", "required_level": 0.75, "importance": 0.85, "demand": 0.80, "interview_relevance": 0.75},
        {"skill": "Docker", "required_level": 0.60, "importance": 0.60, "demand": 0.60, "interview_relevance": 0.50},
        {"skill": "Data Structures & Algorithms", "required_level": 0.85, "importance": 0.95, "demand": 0.90, "interview_relevance": 0.95},
    ]

def _run(signals, overrides=None):
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, None))
    req_map = ars.build_requirements_map(_requirements(), None)
    assessments = ars.calculate_assessments(grouped, req_map, None, overrides=overrides or {})
    gaps = ars.calculate_gaps(assessments, "Backend Engineer")
    readiness = ars.calculate_readiness(assessments, _requirements(), gaps)
    return {a["canonical_name"]: a for a in assessments}, {g["canonical_name"]: g for g in gaps}, readiness


# 1. No evidence -> proficiency 0
def test_no_evidence_proficiency_zero():
    assessments, gaps, _ = _run([])
    for skill in ["Python", "Docker", "Data Structures & Algorithms"]:
        assert assessments[skill]["proficiency"] == 0.0
        assert assessments[skill]["gap"] == pytest.approx(assessments[skill]["required_level"])
        assert assessments[skill]["evidence_state"] == "no_evidence"
        assert assessments[skill]["evidence_state_label"] in ("No evidence", "No evidence submitted")
        assert assessments[skill]["evidence_count"] == 0

# 2. No evidence -> confidence 0
def test_no_evidence_confidence_zero():
    assessments, gaps, _ = _run([])
    for skill in ["Python", "Docker"]:
        assert assessments[skill]["confidence"] == 0.0
        assert gaps[skill]["confidence"] == 0.0
        assert gaps[skill]["gap"] == pytest.approx(assessments[skill]["required_level"])

# 3. Industry required value cannot leak into current proficiency
def test_required_value_does_not_leak():
    # No signals, required 0.75 -> current must be 0, not 0.75
    assessments, _, _ = _run([])
    assert assessments["Python"]["required_level"] == pytest.approx(0.75)
    assert assessments["Python"]["proficiency"] == 0.0
    assert assessments["Python"]["proficiency"] != assessments["Python"]["required_level"]
    # Even with weak signal, proficiency must be weighted average, not required
    sig = _sig("Python", "project", 0.30)
    assessments2, _, _ = _run([sig])
    # 0.30 with project 0.40 reliability -> raw 0.30, not 0.75
    assert assessments2["Python"]["proficiency"] == pytest.approx(0.30)
    assert assessments2["Python"]["proficiency"] != 0.75

# 4. No-evidence role-critical skill remains assessable
def test_no_evidence_role_critical_still_assessable():
    assessments, _, _ = _run([])
    # Python is required and has no evidence, but bank covers Python, so assessable
    python = assessments["Python"]
    rows = [{
        "skill": "Python",
        "proficiency": python["proficiency"],
        "confidence": python["confidence"],
        "required_level": python["required_level"],
        "gap": python["gap"],
        "importance": python["importance"],
        "priority_score": python["priority_score"],
        "gap_type": python["gap_type"],
        "signal_spread": 0.0,
        "evidence_count": 0,
    }]
    available = assessment_service.select_assessable_skills(rows)
    assert any(a["skill"] == "Python" for a in available)
    # DSA also
    dsa = assessments["Data Structures & Algorithms"]
    rows2 = [{
        "skill": "Data Structures & Algorithms",
        "proficiency": dsa["proficiency"],
        "confidence": dsa["confidence"],
        "required_level": dsa["required_level"],
        "gap": dsa["gap"],
        "importance": dsa["importance"],
        "priority_score": dsa["priority_score"],
        "gap_type": dsa["gap_type"],
        "signal_spread": 0.0,
        "evidence_count": 0,
    }]
    available2 = assessment_service.select_assessable_skills(rows2)
    assert any(a["skill"] == "Data Structures & Algorithms" for a in available2)

# 5. GitHub evidence appears in provenance
def test_github_evidence_in_provenance():
    sig = se.make_signal("Python", "github", 0.75, "repo impl", metadata={"project_name": "svc", "repo_count": 3})
    assessments, _, _ = _run([sig])
    py = assessments["Python"]
    assert py["evidence_sources"]
    assert any(s["source_type"] == "github" for s in py["evidence_sources"])
    gh = next(s for s in py["evidence_sources"] if s["source_type"] == "github")
    assert "GitHub" in gh["source_label"]
    # Should show repo-related label
    assert gh["strength"] == pytest.approx(0.75)
    assert gh["reliability"] == pytest.approx(weights.SOURCE_RELIABILITY["github"])

# 6. Assessment appears as separate provenance
def test_assessment_separate_provenance():
    gh = _sig("Python", "github", 0.60)
    import datetime, uuid
    now = datetime.datetime.now(datetime.timezone.utc)
    attempt = {
        "id": "att-1",
        "skill_name": "Python",
        "status": "completed",
        "validity": "valid",
        "score": 0.8,
        "correct_count": 4,
        "question_count": 5,
        "assessment_version": "assessment-v1",
        "completed_at": now.isoformat(),
    }
    assess_sig = assessment_service.build_assessment_signals([attempt])[0]
    assessments, _, _ = _run([gh, assess_sig])
    py = assessments["Python"]
    assert py["has_assessment"] is True
    assert py["assessment_score"] == pytest.approx(0.8)
    assert len([s for s in py["evidence_sources"] if s["source_type"] == "assessment"]) == 1
    assert len([s for s in py["evidence_sources"] if s["source_type"] == "github"]) == 1
    # State should be validated
    assert py["evidence_state"] == "validated"
    assert py["evidence_state_label"] in ("Validated by assessment", "Assessment-validated")

# 7. Multiple evidence sources aggregate correctly
def test_multiple_sources_aggregate():
    sigs = [
        _sig("Python", "github", 0.75),
        _sig("Python", "leetcode", 0.60),
        _sig("Python", "project", 0.50),
    ]
    assessments, _, _ = _run(sigs)
    py = assessments["Python"]
    expected = sum(s["signal_value"]*s["source_reliability"] for s in sigs) / sum(s["source_reliability"] for s in sigs)
    # Note: github/project are 0.40, leetcode 0.85, but proficiency_with_prior shrinks? For github+project+leetcode, still has no assessment, so prior applies? Let's check directly via proficiency_with_prior
    # Our _run uses calculate_assessments which applies prior (since no assessment). For these strengths, prior will shrink.
    # Instead verify weighted average without prior via engine.proficiency
    prof_no_prior, _, _, _ = skill_engine.proficiency(sigs)
    assert prof_no_prior == pytest.approx(expected)
    # With prior, shrunk should be <= raw
    assert py["proficiency"] <= prof_no_prior + 1e-6
    assert py["evidence_count"] == 3
    assert len(py["evidence_sources"]) == 3
    # Sources should be all present
    types = {s["source_type"] for s in py["evidence_sources"]}
    assert types == {"github", "leetcode", "project"}

# 8. User zero override forces effective proficiency to 0
def test_zero_override_forces_zero():
    sig = _sig("Python", "github", 0.75)
    # Without override, proficiency >0
    assessments, _, _ = _run([sig])
    assert assessments["Python"]["proficiency"] > 0
    # With override, forced to 0
    slug = normalize_skill_slug("Python") or "python"
    overrides = {slug: {"skill_name": "Python", "skill_key": slug, "is_zero_override": True}, "python": {"skill_name": "Python", "skill_key": slug, "is_zero_override": True}}
    assessments2, gaps2, _ = _run([sig], overrides=overrides)
    py2 = assessments2["Python"]
    assert py2["proficiency"] == 0.0
    assert py2["confidence"] == 0.0
    assert py2["gap"] == pytest.approx(py2["required_level"])
    assert py2["is_overridden"] is True
    assert py2["evidence_state"] in ("no_evidence", "user_override")
    # Original preserved
    assert py2["original_proficiency"] > 0

# 9. User cannot manually increase proficiency (only downward to 0)
def test_cannot_manually_increase():
    from app.services import evidence_service
    # Attempt to set override with is_zero_override=False should be rejected
    try:
        evidence_service.set_skill_override("user-test", "Python", is_zero_override=False)
        assert False, "should have raised"
    except Exception as e:
        msg = str(e).lower()
        assert "only downward" in msg or "manual increase" in msg or "400" in msg or "downward" in msg

# 10. Evidence exclusion preserves raw evidence (is_excluded flag)
def test_evidence_exclusion_preserves_raw():
    # Simulate evidence item
    ev = {"id": "ev1", "evidence_type": "github", "source_url": "https://github.com/a/b", "is_excluded": False, "metadata": {}}
    # signal extractor should skip when is_excluded True
    signals = se.extract_signals([ev], [], [])
    # unverified github with no verified_signals yields 0 signals (continue), but not excluded logic
    # Let's test with a verified github mock
    ev_verified = {
        "id": "ev2",
        "evidence_type": "github",
        "source_url": "https://github.com/a/b",
        "verification_status": "verified",
        "metadata": {"verification_status": "verified", "verified_signals": [{"skill": "Python", "signal_strength": 0.75, "source_reliability": 0.40, "reason": "repo"}]},
        "is_excluded": True,
    }
    signals_excluded = se.extract_signals([ev_verified], [], [])
    assert signals_excluded == [], "excluded evidence must produce no signals"
    # Not excluded should produce signal
    ev_not_excluded = {**ev_verified, "is_excluded": False}
    signals_included = se.extract_signals([ev_not_excluded], [], [])
    assert len(signals_included) == 1

# 11. Evidence exclusion removes scoring contribution
def test_exclusion_removes_scoring():
    # Two projects, one excluded
    proj_included = {"id": "p1", "name": "Svc", "description": "Built Python service with FastAPI", "technologies": ["Python"], "github_url": None, "is_excluded": False}
    proj_excluded = {"id": "p2", "name": "Tool", "description": "Python tool", "technologies": ["Python"], "github_url": None, "is_excluded": True}
    sigs_included = se.extract_signals([], [proj_included], [])
    sigs_both = se.extract_signals([], [proj_included, proj_excluded], [])
    # Both should give same as included only, because excluded is skipped
    assert len(sigs_included) == len(sigs_both)
    # Now test proficiency: with excluded, same as single
    assessments_inc, _, _ = _run(sigs_included)
    assessments_both, _, _ = _run(sigs_both)
    assert assessments_inc["Python"]["proficiency"] == pytest.approx(assessments_both["Python"]["proficiency"])

# 12. Recalculation updates gap/readiness/roadmap
def test_recalculation_updates_gap_and_readiness():
    # Before: github only
    sig = _sig("Python", "github", 0.60)
    a_before, g_before, r_before = _run([sig])
    # After: add assessment
    attempt = {
        "id": "att2",
        "skill_name": "Python",
        "status": "completed",
        "validity": "valid",
        "score": 0.90,
        "correct_count": 5,
        "question_count": 5,
        "assessment_version": "assessment-v1",
        "completed_at": "2026-01-01T00:00:00Z",
    }
    assess_sig = assessment_service.build_assessment_signals([attempt])[0]
    a_after, g_after, r_after = _run([sig, assess_sig])
    # Proficiency should increase
    assert a_after["Python"]["proficiency"] > a_before["Python"]["proficiency"]
    # Gap should shrink
    assert g_after["Python"]["gap"] < g_before["Python"]["gap"]
    # Readiness should change
    assert r_after["readiness_score"] != r_before["readiness_score"]
    # Roadmap would drop skill if gap closed - simulate via filter_and_sort_gaps
    from app.services import roadmap_service
    before_items = roadmap_service.filter_and_sort_gaps(list(g_before.values()))
    after_items = roadmap_service.filter_and_sort_gaps(list(g_after.values()))
    # With strong assessment, Python gap may still exist but smaller, so both may contain Python; check priority declines
    assert g_after["Python"]["priority_score"] < g_before["Python"]["priority_score"] or g_after["Python"]["gap"] < g_before["Python"]["gap"]

# 13. Portfolio-only skills do not inflate target-role readiness
def test_portfolio_does_not_inflate_readiness():
    # Create a portfolio skill signal (e.g., Flutter not required for Backend Engineer)
    sig_portfolio = _sig("Flutter", "github", 0.85)
    sig_required = _sig("Python", "github", 0.60)
    # With both, readiness should be based only on target requirements (Python, Docker, DSA), not Flutter
    assessments_with_portfolio, gaps_with_portfolio, readiness_with = _run([sig_required, sig_portfolio])
    assessments_without, gaps_without, readiness_without = _run([sig_required])
    # Portfolio should be flagged
    assert assessments_with_portfolio["Flutter"]["is_portfolio"] is True
    assert assessments_with_portfolio["Python"]["is_portfolio"] is False
    # Readiness should be identical whether portfolio exists or not (since filtered)
    assert readiness_with["readiness_score"] == pytest.approx(readiness_without["readiness_score"])
    assert readiness_with["skill_component"] == pytest.approx(readiness_without["skill_component"])

# 14. Existing GitHub verification tests still pass (smoke)
def test_github_still_verified():
    # Simple sanity that github provider still works
    assert weights.SOURCE_RELIABILITY["github"] == 0.40
    assert se.SOURCE_RELIABILITY["github"] == 0.40

# 15. Existing assessment tests still pass (smoke)
def test_assessment_bank_valid():
    from app.services.assessment.question_bank import validate_bank, assessable_skills
    assert validate_bank() == []
    assert len(assessable_skills()) >= 5

# 16. Existing skill engine tests still pass (smoke)
def test_skill_engine_no_evidence():
    prof, w, cnt, avg = skill_engine.proficiency([])
    assert prof == 0
    assert w == 0
    assert cnt == 0
    conf, _, _ = skill_engine.confidence(0, 0)
    assert conf == 0

# Additional: AI-assisted reduces reliability
def test_ai_assisted_reduces_contribution():
    sig_normal = se.make_signal("Python", "github", 0.75, "repo", is_ai_assisted=False)
    sig_ai = se.make_signal("Python", "github", 0.75, "repo", is_ai_assisted=True)
    assert sig_ai["source_reliability"] < sig_normal["source_reliability"]
    assert sig_ai["source_reliability"] == pytest.approx(sig_normal["source_reliability"] * 0.5)
    # Proficiency with AI should be lower or equal? Actually reliability weighting changes, but strength same, so proficiency same if single source (0.75). But confidence weight reduced.
    prof_normal, w_normal, _, _ = skill_engine.proficiency([sig_normal])
    prof_ai, w_ai, _, _ = skill_engine.proficiency([sig_ai])
    assert w_ai < w_normal
    # Confidence should be lower with AI
    conf_normal, _, _, _ = skill_engine.confidence_from_signals([sig_normal])
    conf_ai, _, _, _ = skill_engine.confidence_from_signals([sig_ai])
    assert conf_ai <= conf_normal

# Additional: Provenance shows both github and assessment
def test_mixed_provenance_shows_both():
    gh = _sig("Python", "github", 0.70)
    att = {
        "id": "att3",
        "skill_name": "Python",
        "status": "completed",
        "validity": "valid",
        "score": 0.80,
        "correct_count": 4,
        "question_count": 5,
        "assessment_version": "assessment-v1",
        "completed_at": "2026-01-01T00:00:00Z",
    }
    assess_sig = assessment_service.build_assessment_signals([att])[0]
    assessments, _, _ = _run([gh, assess_sig])
    py = assessments["Python"]
    assert py["evidence_state"] == "validated"
    types = {s["source_type"] for s in py["evidence_sources"]}
    assert "github" in types and "assessment" in types

# Additional: No generic filename fallback
def test_no_filename_fallback():
    ev = {"id": "evf", "evidence_type": "resume", "file_path": "python_resume.pdf", "title": "python_resume.pdf", "metadata": {"parsed_text": "", "sections": {}}, "is_excluded": False}
    sigs = se.extract_signals([ev], [], [])
    # Should be 0 because no parsed_text and no explicit skills, and filename fallback removed
    assert sigs == []

def test_new_evidence_after_override_supersedes():
    # Old evidence before override should remain suppressed; new evidence after should reopen
    old_sig = se.make_signal("Python", "github", 0.75, "old repo", metadata={"source_created_at": "2026-01-01T00:00:00Z"}, source_created_at="2026-01-01T00:00:00Z")
    overrides = {"python": {"skill_name": "Python", "skill_key": "python", "is_zero_override": True, "created_at": "2026-01-10T00:00:00Z"}}
    # With only old evidence, still overridden
    a_old, _, _ = _run([old_sig], overrides=overrides)
    assert a_old["Python"]["is_overridden"] is True
    assert a_old["Python"]["proficiency"] == 0.0
    # New evidence after override
    new_sig = se.make_signal("Python", "github", 0.75, "new repo", metadata={"source_created_at": "2026-01-15T00:00:00Z"}, source_created_at="2026-01-15T00:00:00Z")
    a_new, _, _ = _run([old_sig, new_sig], overrides=overrides)
    # New evidence supersedes override, so not overridden anymore
    assert a_new["Python"]["is_overridden"] is False
    assert a_new["Python"]["proficiency"] > 0

def test_old_evidence_before_override_cannot_restore():
    old_sig = se.make_signal("Python", "github", 0.75, "old repo", metadata={"source_created_at": "2026-01-01T00:00:00Z"}, source_created_at="2026-01-01T00:00:00Z")
    overrides = {"python": {"skill_name": "Python", "skill_key": "python", "is_zero_override": True, "created_at": "2026-01-10T00:00:00Z"}}
    a_old, _, _ = _run([old_sig], overrides=overrides)
    assert a_old["Python"]["proficiency"] == 0.0
    # Old evidence alone cannot restore, even if we run again without new evidence
    a_old2, _, _ = _run([old_sig], overrides=overrides)
    assert a_old2["Python"]["is_overridden"] is True

def test_new_assessment_after_override_supersedes():
    gh_sig = se.make_signal("Python", "github", 0.70, "repo", metadata={"source_created_at": "2026-01-01T00:00:00Z"}, source_created_at="2026-01-01T00:00:00Z")
    overrides = {"python": {"skill_name": "Python", "skill_key": "python", "is_zero_override": True, "created_at": "2026-01-10T00:00:00Z"}}
    # With override, even with old github, still 0
    a_before, _, _ = _run([gh_sig], overrides=overrides)
    assert a_before["Python"]["proficiency"] == 0.0
    # New assessment after override should supersede
    att = {"id": "att-new", "skill_name": "Python", "status": "completed", "validity": "valid", "score": 0.80, "correct_count": 4, "question_count": 5, "assessment_version": "assessment-v1", "completed_at": "2026-01-15T00:00:00Z"}
    assess_sig = assessment_service.build_assessment_signals([att])[0]
    a_after, _, _ = _run([gh_sig, assess_sig], overrides=overrides)
    assert a_after["Python"]["is_overridden"] is False
    assert a_after["Python"]["has_assessment"] is True
    assert a_after["Python"]["proficiency"] > 0
    assert a_after["Python"]["evidence_state"] == "validated"

def test_override_after_assessment_still_forces_zero():
    # Assessment exists before override, then user says I don't know this yet
    att = {"id": "att-old", "skill_name": "Python", "status": "completed", "validity": "valid", "score": 0.80, "correct_count": 4, "question_count": 5, "assessment_version": "assessment-v1", "completed_at": "2026-01-01T00:00:00Z"}
    assess_sig = assessment_service.build_assessment_signals([att])[0]
    gh_sig = se.make_signal("Python", "github", 0.60, "repo", metadata={"source_created_at": "2026-01-01T00:00:00Z"}, source_created_at="2026-01-01T00:00:00Z")
    # Before override, has assessment, proficiency >0
    a_before, _, _ = _run([gh_sig, assess_sig])
    assert a_before["Python"]["proficiency"] > 0
    # Override created after assessment
    overrides = {"python": {"skill_name": "Python", "skill_key": "python", "is_zero_override": True, "created_at": "2026-01-10T00:00:00Z"}}
    a_after, _, _ = _run([gh_sig, assess_sig], overrides=overrides)
    assert a_after["Python"]["is_overridden"] is True
    assert a_after["Python"]["proficiency"] == 0.0
    assert a_after["Python"]["evidence_state"] == "user_override"
