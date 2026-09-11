"""
Regression tests for the 2026-09-11 GitHub supporting-evidence recalibration.

Product principle:
    GitHub says  "I found evidence that this person worked with this skill."
    Assessment says "This person demonstrated understanding of this skill."

These must never be represented as equivalent. Concretely:
  * github = project = 0.40 (supporting), fixed — never raised by an assessment
  * assessment = 0.95, stored as its own separate evidence source
  * GitHub-only evidence cannot reach high confidence
  * an assessment can move the final estimate up OR down
"""

from datetime import datetime, timezone
from typing import Dict, List

import pytest

from app.services import analysis_run_service as ars
from app.services import evidence_weights as weights
from app.services import roadmap_service
from app.services import signal_extractor as se
from app.services import skill_engine
from app.services.assessment import service as assessment_service
from app.services.evidence.base import EvidenceDepth
from app.services.evidence.github import GITHUB_RELIABILITY


NOW = datetime.now(timezone.utc)

GITHUB_SOURCES = ("github", "project")


def _sig(skill: str, source: str, strength: float) -> dict:
    return se.make_signal(
        canonical=skill,
        source_type=source,
        signal_value=strength,
        explanation=f"{source} evidence for {skill}",
    )


def _attempt(skill: str, score: float, correct: int, total: int = 5, attempt_id: str = "att-1") -> dict:
    return {
        "id": attempt_id,
        "skill_name": skill,
        "status": "completed",
        "validity": "valid",
        "score": score,
        "correct_count": correct,
        "question_count": total,
        "assessment_version": "assessment-v1",
        "completed_at": NOW.isoformat(),
    }


# ===========================================================================
# 1-3. The recalibrated weights
# ===========================================================================

def test_github_reliability_is_040():
    assert weights.SOURCE_RELIABILITY["github"] == 0.40
    assert weights.reliability("github") == 0.40
    # Every consumer reads the same central value.
    assert GITHUB_RELIABILITY == 0.40
    assert se.SOURCE_RELIABILITY["github"] == 0.40
    assert skill_engine.SOURCE_RELIABILITY["github"] == 0.40


def test_project_reliability_is_040():
    assert weights.SOURCE_RELIABILITY["project"] == 0.40
    assert weights.reliability("project") == 0.40
    assert se.SOURCE_RELIABILITY["project"] == 0.40


def test_assessment_reliability_is_095():
    assert weights.SOURCE_RELIABILITY["assessment"] == 0.95
    assert weights.reliability(weights.ASSESSMENT_SOURCE) == 0.95
    assert assessment_service.ASSESSMENT_RELIABILITY == 0.95


def test_performance_sources_outrank_github_and_project():
    for platform in ("leetcode", "codeforces", "kaggle"):
        assert weights.SOURCE_RELIABILITY[platform] == 0.85
        for artifact in GITHUB_SOURCES:
            assert weights.SOURCE_RELIABILITY[platform] > weights.SOURCE_RELIABILITY[artifact]
    for artifact in GITHUB_SOURCES:
        assert weights.SOURCE_RELIABILITY["assessment"] > weights.SOURCE_RELIABILITY[artifact]
        assert weights.SOURCE_RELIABILITY["syllabus"] > weights.SOURCE_RELIABILITY[artifact]

    # A platform signal outweighs an equally strong GitHub signal.
    prof, _, _, _ = skill_engine.proficiency([
        _sig("Python", "github", 0.80),
        _sig("Python", "leetcode", 0.40),
    ])
    assert prof < (0.80 + 0.40) / 2


# ===========================================================================
# 4. GitHub-only evidence cannot manufacture confidence
# ===========================================================================

def test_github_only_evidence_cannot_create_high_confidence():
    for strength in (0.60, 0.75, 0.85):
        signals = [_sig("Python", "github", strength)]
        conf, weight, diversity, validation = skill_engine.confidence_from_signals(signals)
        assert conf < 0.40, f"github-only confidence too high at strength {strength}: {conf}"
        assert weight == pytest.approx(0.40)
        assert diversity == 1.0
        assert validation <= weights.SOURCE_DIRECTNESS["github"]


def test_github_plus_project_artifacts_still_cannot_create_high_confidence():
    """Two artifact sources add diversity but no direct validation."""
    signals = [_sig("Python", "github", 0.85), _sig("Python", "project", 0.75)]
    conf, weight, diversity, _ = skill_engine.confidence_from_signals(signals)
    assert weight == pytest.approx(0.80)
    assert diversity == 2.0
    assert conf < 0.50, f"artifact-only confidence should stay limited, got {conf}"


def test_lower_reliability_reduced_github_only_confidence():
    """The recalibration is what suppresses artifact-only confidence."""
    signals = [_sig("Python", "github", 0.85)]
    conf_now, _, _, _ = skill_engine.confidence_from_signals(signals)

    # Same signal evaluated with the previous 0.60 weight.
    legacy = [{**signals[0], "source_reliability": 0.60, "source": "github"}]
    conf_before, _, _, _ = skill_engine.confidence_from_signals(legacy)
    assert conf_now < conf_before


# ===========================================================================
# 5-6. Assessment is a separate source and never mutates GitHub reliability
# ===========================================================================

def test_assessment_is_stored_as_a_separate_evidence_source():
    signals = assessment_service.build_assessment_signals([_attempt("Docker", 0.8, 4)])
    assert len(signals) == 1
    sig = signals[0]
    assert sig["source_type"] == "assessment"
    assert sig["source"] == "assessment"
    assert sig["source_reliability"] == 0.95
    assert sig["signal_value"] == pytest.approx(0.8)
    # Separate row/source, not a modification of an existing GitHub signal.
    assert sig["metadata"]["assessment_attempt_id"] == "att-1"
    assert sig["evidence_id"] is None


def test_assessment_does_not_change_github_reliability():
    github = _sig("Docker", "github", 0.75)
    github_weight_before = github["source_reliability"]

    assessed = [github, *assessment_service.build_assessment_signals([_attempt("Docker", 0.9, 5)])]

    gh_after = next(s for s in assessed if s["source_type"] == "github")
    assert gh_after["source_reliability"] == github_weight_before == 0.40
    assert weights.SOURCE_RELIABILITY["github"] == 0.40      # module state untouched
    assert GITHUB_RELIABILITY == 0.40

    # Both sources survive aggregation, each keeping its own weight.
    by_source = {s["source_type"]: s for s in assessed}
    assert set(by_source) == {"github", "assessment"}
    assert by_source["github"]["source_reliability"] == 0.40
    assert by_source["assessment"]["source_reliability"] == 0.95


def test_pipeline_keeps_github_weight_after_assessment():
    grouped = ars.aggregate_skills(ars.normalize_signals(
        [_sig("Docker", "github", 0.75), *assessment_service.build_assessment_signals([_attempt("Docker", 0.8, 4)])],
        None,
    ))
    req_map = ars.build_requirements_map(
        [{"skill": "Docker", "required_level": 0.60, "importance": 0.60}], None
    )
    docker = next(a for a in ars.calculate_assessments(grouped, req_map, None) if a["canonical_name"] == "Docker")

    reliabilities = {s["source_type"]: s["source_reliability"] for s in docker["signals"]}
    assert reliabilities == {"github": 0.40, "assessment": 0.95}
    assert docker["has_assessment"] is True
    # GitHub-only estimate, carrying the unvalidated prior:
    # (0.75*0.40 + 0.35*0.60) / 1.00 = 0.51
    assert docker["evidence_proficiency"] == pytest.approx(0.51)
    # The validated result drops the prior and uses both real sources.
    assert docker["proficiency"] == pytest.approx((0.75 * 0.40 + 0.80 * 0.95) / 1.35)
    assert docker["unvalidated_prior_applied"] is False
    assert docker["evidence_state"] == "validated"


# ===========================================================================
# 6b. Unvalidated-evidence prior (approved 2026-09-11)
# ===========================================================================

def test_prior_shrinks_an_inflated_artifact_only_estimate():
    """An 0.85 GitHub signal must not read as demonstrated mastery."""
    signals = [_sig("SQL", "github", 0.85)]
    raw, _, _, _ = skill_engine.proficiency(signals)
    shrunk, weight, count, _, applied = skill_engine.proficiency_with_prior(signals)

    w0 = skill_engine.UNVALIDATED_PRIOR_WEIGHT
    p0 = skill_engine.UNVALIDATED_PRIOR_VALUE
    assert raw == pytest.approx(0.85)
    assert shrunk == pytest.approx((0.85 * 0.40 + p0 * w0) / (0.40 + w0))
    assert shrunk == pytest.approx(0.55)
    assert applied is True
    # The prior must never inflate the evidence weight used by confidence.
    assert weight == pytest.approx(0.40)
    assert count == 1


def test_prior_is_one_sided_and_never_invents_proficiency():
    """A weak estimate stays exactly where the evidence puts it."""
    weak = [_sig("Data Structures & Algorithms", "leetcode", 0.13)]
    raw, _, _, _ = skill_engine.proficiency(weak)
    shrunk, _, _, _, applied = skill_engine.proficiency_with_prior(weak)
    assert raw == pytest.approx(0.13)
    assert shrunk == pytest.approx(0.13), "shrinkage toward the prior must not raise an estimate"
    assert applied is False

    zero = []
    assert skill_engine.proficiency_with_prior(zero) == (0.0, 0.0, 0, 0.0, False)


def test_prior_disappears_once_an_assessment_exists():
    github = [_sig("SQL", "github", 0.85)]
    validated = github + assessment_service.build_assessment_signals([_attempt("SQL", 0.60, 3)])

    unvalidated, _, _, _, applied_before = skill_engine.proficiency_with_prior(github)
    final, _, _, _, applied_after = skill_engine.proficiency_with_prior(validated)

    assert applied_before is True
    assert applied_after is False, "direct validation switches the prior off"
    # Pure weighted average of the two real sources — no prior term.
    assert final == pytest.approx((0.85 * 0.40 + 0.60 * 0.95) / 1.35)
    assert final == pytest.approx(0.674, abs=1e-3)
    assert unvalidated < final < 0.85


def test_prior_leaves_the_base_formula_and_confidence_untouched():
    signals = [_sig("SQL", "github", 0.85)]
    # proficiency() itself is unchanged: single source maps 1:1.
    assert skill_engine.proficiency(signals)[0] == pytest.approx(0.85)
    # Confidence inputs are computed from real evidence only.
    conf, weight, diversity, _ = skill_engine.confidence_from_signals(signals)
    assert weight == pytest.approx(0.40)
    assert diversity == 1.0
    assert conf < 0.40


def test_prior_exemption_hook_is_configurable(monkeypatch):
    """Performance platforms can be exempted with a one-line config change."""
    signals = [_sig("Python", "leetcode", 0.80)]
    shrunk, _, _, _, applied = skill_engine.proficiency_with_prior(signals)
    assert applied is True and shrunk < 0.80

    monkeypatch.setattr(skill_engine, "PRIOR_EXEMPT_SOURCES", frozenset({"leetcode"}))
    exempt, _, _, _, applied_after = skill_engine.proficiency_with_prior(signals)
    assert applied_after is False
    assert exempt == pytest.approx(0.80)


# ===========================================================================
# 7-8. The assessment can move the estimate up OR down
# ===========================================================================

def test_assessment_can_raise_proficiency():
    github_only, _, _, _ = skill_engine.proficiency([_sig("Docker", "github", 0.50)])
    with_assessment, _, _, _ = skill_engine.proficiency([
        _sig("Docker", "github", 0.50),
        *assessment_service.build_assessment_signals([_attempt("Docker", 0.90, 5)]),
    ])
    assert github_only == pytest.approx(0.50)
    assert with_assessment > github_only
    # Weighted by 0.40 vs 0.95, the direct evidence dominates.
    assert with_assessment == pytest.approx((0.50 * 0.40 + 0.90 * 0.95) / 1.35)
    assert with_assessment > 0.75


def test_assessment_can_lower_proficiency():
    """GitHub 0.75 + assessment 0.40 must NOT stay at 0.75."""
    github_only, _, _, _ = skill_engine.proficiency([_sig("Python", "github", 0.75)])
    with_assessment, _, _, _ = skill_engine.proficiency([
        _sig("Python", "github", 0.75),
        *assessment_service.build_assessment_signals([_attempt("Python", 0.40, 2)]),
    ])
    assert github_only == pytest.approx(0.75)
    assert with_assessment < github_only
    assert with_assessment == pytest.approx((0.75 * 0.40 + 0.40 * 0.95) / 1.35)
    assert with_assessment < 0.55, "a weak assessment must pull an artifact estimate down"


def test_failed_assessment_pulls_estimate_far_down():
    prof, _, _, _ = skill_engine.proficiency([
        _sig("Python", "github", 0.85),
        *assessment_service.build_assessment_signals([_attempt("Python", 0.20, 1)]),
    ])
    assert prof < 0.40


# ===========================================================================
# 9. Confidence responds to direct validation
# ===========================================================================

def test_assessment_increases_confidence():
    github = [_sig("Docker", "github", 0.75)]
    validated = github + assessment_service.build_assessment_signals([_attempt("Docker", 0.80, 4)])

    conf_before, w_before, _, val_before = skill_engine.confidence_from_signals(github)
    conf_after, w_after, _, val_after = skill_engine.confidence_from_signals(validated)

    assert conf_before < 0.40
    assert conf_after > 0.60
    assert conf_after > conf_before + 0.25
    assert val_after > val_before
    assert w_after > w_before
    assert weights.has_direct_validation(validated) is True


def test_confidence_rises_even_when_proficiency_falls():
    """A poor assessment lowers the estimate but INAURA is more certain of it."""
    github = [_sig("Python", "github", 0.85)]
    validated = github + assessment_service.build_assessment_signals([_attempt("Python", 0.20, 1)])

    prof_b, _, _, _ = skill_engine.proficiency(github)
    prof_a, _, _, _ = skill_engine.proficiency(validated)
    conf_b, _, _, _ = skill_engine.confidence_from_signals(github)
    conf_a, _, _, _ = skill_engine.confidence_from_signals(validated)

    assert prof_a < prof_b
    assert conf_a > conf_b


# ===========================================================================
# 10. Gap / readiness / roadmap respond to the updated estimate
# ===========================================================================

REQUIREMENTS = [
    {"skill": "Python", "required_level": 0.80, "importance": 0.90, "demand": 0.85, "interview_relevance": 0.85},
    {"skill": "Docker", "required_level": 0.60, "importance": 0.60, "demand": 0.60, "interview_relevance": 0.50},
]


def _pipeline(signals: List[dict]):
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, None))
    assessments = ars.calculate_assessments(grouped, ars.build_requirements_map(REQUIREMENTS, None), None)
    gaps = ars.calculate_gaps(assessments, "Backend Engineer")
    readiness = ars.calculate_readiness(assessments, REQUIREMENTS, gaps)
    return (
        {a["canonical_name"]: a for a in assessments},
        {g["canonical_name"]: g for g in gaps},
        readiness,
    )


def test_gap_and_readiness_follow_a_strong_assessment():
    before_a, before_g, before_r = _pipeline([_sig("Python", "github", 0.50)])
    after_a, after_g, after_r = _pipeline([
        _sig("Python", "github", 0.50),
        *assessment_service.build_assessment_signals([_attempt("Python", 0.90, 5)]),
    ])

    assert after_a["Python"]["proficiency"] > before_a["Python"]["proficiency"]
    assert after_g["Python"]["gap"] < before_g["Python"]["gap"]
    assert after_r["readiness_score"] > before_r["readiness_score"]
    assert after_r["skill_component"] > before_r["skill_component"]


def test_gap_and_readiness_follow_a_weak_assessment():
    before_a, before_g, before_r = _pipeline([_sig("Python", "github", 0.75)])
    after_a, after_g, after_r = _pipeline([
        _sig("Python", "github", 0.75),
        *assessment_service.build_assessment_signals([_attempt("Python", 0.40, 2)]),
    ])

    assert after_a["Python"]["proficiency"] < before_a["Python"]["proficiency"]
    assert after_g["Python"]["gap"] > before_g["Python"]["gap"]
    assert after_r["skill_component"] < before_r["skill_component"]


def test_roadmap_reacts_to_the_validated_estimate():
    _, weak_gaps, _ = _pipeline([
        _sig("Python", "github", 0.75),
        *assessment_service.build_assessment_signals([_attempt("Python", 0.40, 2)]),
    ])
    _, strong_gaps, _ = _pipeline([
        _sig("Python", "github", 0.75),
        *assessment_service.build_assessment_signals([_attempt("Python", 1.00, 5)]),
    ])

    weak_items = roadmap_service.filter_and_sort_gaps(list(weak_gaps.values()))
    strong_items = roadmap_service.filter_and_sort_gaps(list(strong_gaps.values()))

    assert "Python" in [g["canonical_name"] for g in weak_items]
    assert "Python" not in [g["canonical_name"] for g in strong_items]
    # Roadmap ordering still comes from the existing gap engine.
    assert weak_gaps["Python"]["priority_score"] > strong_gaps["Python"]["priority_score"]


# ===========================================================================
# 11-12. Evidence states and untouched formulas
# ===========================================================================

def test_evidence_states_distinguish_estimate_from_validated():
    estimate, _, _ = _pipeline([_sig("Docker", "github", 0.75)])
    validated, _, _ = _pipeline([
        _sig("Docker", "github", 0.75),
        *assessment_service.build_assessment_signals([_attempt("Docker", 0.80, 4)]),
    ])
    missing, _, _ = _pipeline([_sig("Docker", "github", 0.75)])

    assert estimate["Docker"]["evidence_state"] == "evidence_estimate"
    assert estimate["Docker"]["evidence_state_label"] == "Evidence-based estimate"
    assert estimate["Docker"]["has_assessment"] is False

    assert validated["Docker"]["evidence_state"] == "validated"
    assert validated["Docker"]["evidence_state_label"] in ("Assessment-validated", "Validated by assessment")

    # A required skill with no evidence at all is a third, distinct state.
    assert missing["Python"]["evidence_state"] == "no_evidence"
    assert missing["Python"]["evidence_state_label"] in ("No evidence submitted", "No evidence")


def test_scoring_formulas_unchanged_by_this_recalibration():
    # Weighted-average proficiency: untouched.
    sigs = [
        {"signal_strength": 0.80, "source_reliability": 0.70},
        {"signal_strength": 0.40, "source_reliability": 0.85},
    ]
    prof, weight, count, avg = skill_engine.proficiency(sigs)
    assert prof == pytest.approx((0.80 * 0.70 + 0.40 * 0.85) / 1.55)
    assert (weight, count, avg) == pytest.approx((1.55, 2, 0.60))

    # Confidence: legacy two-term form and the three-term extension both intact.
    assert (skill_engine.CONFIDENCE_W_WEIGHT, skill_engine.CONFIDENCE_D_WEIGHT) == (0.55, 0.45)
    assert (
        skill_engine.CONFIDENCE_VOL_WEIGHT,
        skill_engine.CONFIDENCE_DIV_WEIGHT,
        skill_engine.CONFIDENCE_VAL_WEIGHT,
    ) == (0.40, 0.25, 0.35)
    assert skill_engine.confidence(1.40, 2)[0] == pytest.approx(0.55 * (1.40 / 2.5) + 0.45 * (2 / 3.0))

    # Depth->strength map, readiness weights, gap and engine version unchanged.
    assert EvidenceDepth.DEPTH_STRENGTH_MAP == {0: 0.0, 1: 0.40, 2: 0.60, 3: 0.75, 4: 0.85}
    assert skill_engine.READINESS_WEIGHTS == {"skill": 0.45, "industry": 0.25, "evidence": 0.30}
    assert skill_engine.gap(0.6, 0.8) == pytest.approx(0.2)
    assert skill_engine.ENGINE_VERSION == "4C-v1"

    # No proficiency cap was introduced: a single source still maps 1:1.
    only, _, _, _ = skill_engine.proficiency([_sig("Python", "github", 0.85)])
    assert only == pytest.approx(0.85)


def test_cached_signals_do_not_resurrect_pre_recalibration_weights():
    """A stored signal must not keep an old source weight alive."""
    import asyncio
    from app.services.evidence.manager import EvidenceManager
    from app.services.evidence.base import VerificationStatus

    stale_evidence = {
        "id": "ev-1",
        "evidence_type": "github",
        "source_url": "https://github.com/someone",
        "provider": "github",
        "verification_status": VerificationStatus.VERIFIED,
        "verified_at": NOW.isoformat(),
        "metadata": {
            "verification_status": VerificationStatus.VERIFIED,
            "verified_at": NOW.isoformat(),
            "provider": "github",
            # Persisted before the recalibration, with the old 0.70 weight.
            "verified_signals": [
                {"skill": "Python", "signal_strength": 0.85, "depth": 4, "source_reliability": 0.70}
            ],
        },
    }
    res = asyncio.run(EvidenceManager().verify_evidence(stale_evidence))
    assert [s.source_reliability for s in res.signals] == [0.40]


def test_signal_strength_stays_independent_of_source_reliability():
    sig = _sig("Python", "github", 0.85)
    assert sig["signal_value"] == pytest.approx(0.85)
    assert sig["source_reliability"] == pytest.approx(0.40)
    assert sig["signal_value"] != sig["source_reliability"]
