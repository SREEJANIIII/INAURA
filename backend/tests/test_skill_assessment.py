"""
Focused tests for the INAURA skill assessment layer and the recalibrated
evidence weighting.

Product principle under test:
    GitHub/project evidence = supporting evidence (technology exposure)
    INAURA assessment       = direct validation of the person

The assessment is a prototype heuristic instrument, so these tests pin
*relative* behaviour (hierarchy, direction of change, bounded influence)
rather than claiming any absolute measurement of human proficiency.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app.services import analysis_run_service as ars
from app.services import evidence_weights as weights
from app.services import roadmap_service
from app.services import signal_extractor as se
from app.services import skill_engine
from app.services.assessment import question_bank as bank
from app.services.assessment import service as assessment_service


NOW = datetime.now(timezone.utc)


def _github_signal(skill: str = "Python", strength: float = 0.75) -> dict:
    return se.make_signal(
        canonical=skill,
        source_type="github",
        signal_value=strength,
        explanation=f"Repository implementation evidence for {skill}",
    )


def _assessment_signal(skill: str = "Python", score: float = 0.80, attempt_id: str = "att-1") -> dict:
    return se.make_signal(
        canonical=skill,
        source_type=weights.ASSESSMENT_SOURCE,
        signal_value=score,
        explanation=f"INAURA skill assessment on {skill}",
        metadata={"assessment_attempt_id": attempt_id, "assessment_score": score},
    )


def _attempt(
    skill: str = "Python",
    score: float = 0.8,
    correct: int = 4,
    total: int = 5,
    completed_at: Optional[datetime] = None,
    status: str = "completed",
    validity: str = "valid",
    attempt_id: str = "att-1",
) -> dict:
    return {
        "id": attempt_id,
        "skill_name": skill,
        "skill_key": bank.skill_slug(skill),
        "status": status,
        "validity": validity,
        "score": score,
        "correct_count": correct,
        "question_count": total,
        "assessment_version": bank.ASSESSMENT_VERSION,
        "completed_at": (completed_at or NOW).isoformat(),
    }


# ===========================================================================
# 1 & 2. GitHub stays useful but cannot manufacture confidence
# ===========================================================================

def test_github_only_evidence_does_not_create_high_confidence():
    signals = [_github_signal("Python", 0.75), _github_signal("Docker", 0.75)]
    python_only = [signals[0]]

    conf, weight, diversity, validation = skill_engine.confidence_from_signals(python_only)

    assert conf < 0.40, f"GitHub-only confidence should stay low, got {conf}"
    assert diversity == 1.0
    assert validation < 0.40, "repository artifacts are weak *direct* evidence"
    assert weight == pytest.approx(weights.SOURCE_RELIABILITY["github"])


def test_many_github_repositories_still_cannot_reach_high_confidence():
    """A big portfolio adds breadth, not direct validation of the person."""
    portfolio = [_github_signal("Python", 0.85)]
    conf, _, _, _ = skill_engine.confidence_from_signals(portfolio)
    assert conf < 0.50

    # Even at the maximum GitHub signal strength the validation term is capped
    # by the source's directness factor.
    assert weights.validation_strength(portfolio) <= weights.SOURCE_DIRECTNESS["github"]


def test_github_remains_a_meaningful_supporting_source():
    """Recalibration must not make GitHub worthless."""
    assert weights.SOURCE_RELIABILITY["github"] == pytest.approx(0.60)
    assert weights.tier_of("github") == "medium"
    assert weights.SOURCE_RELIABILITY["github"] > weights.SOURCE_RELIABILITY["certification"]
    assert weights.SOURCE_RELIABILITY["github"] > weights.SOURCE_RELIABILITY["resume"]
    assert weights.SOURCE_RELIABILITY["github"] > weights.SOURCE_RELIABILITY["linkedin"]

    # GitHub alone still produces real proficiency and non-zero confidence.
    prof, weight, count, _ = skill_engine.proficiency([_github_signal("Python", 0.75)])
    conf, _, _, _ = skill_engine.confidence_from_signals([_github_signal("Python", 0.75)])
    assert prof == pytest.approx(0.75)
    assert count == 1
    assert weight > 0
    assert conf > 0.0


def test_evidence_hierarchy_tiers_are_ordered():
    r = weights.SOURCE_RELIABILITY
    assert r["assessment"] > r["leetcode"] == r["codeforces"] == r["kaggle"] > r["syllabus"]
    assert r["syllabus"] > r["project"] >= r["github"] > r["certification"]
    assert r["certification"] >= r["resume"] > r["linkedin"] > r["self_declared"]

    assert weights.tier_of("assessment") == "very_high"
    assert weights.tier_of("leetcode") == "high"
    assert weights.tier_of("github") == "medium"
    assert weights.tier_of("linkedin") == "low"

    # Central config is the single source of truth for every consumer.
    assert se.SOURCE_RELIABILITY is weights.SOURCE_RELIABILITY
    assert skill_engine.SOURCE_RELIABILITY is weights.SOURCE_RELIABILITY


# ===========================================================================
# 3. Assessment scoring / grading is normalized and deterministic
# ===========================================================================

def test_assessment_score_normalization():
    assert assessment_service.score_from_counts(4, 5) == 0.8
    assert assessment_service.score_from_counts(0, 5) == 0.0
    assert assessment_service.score_from_counts(5, 5) == 1.0
    assert assessment_service.score_from_counts(3, 0) == 0.0        # no divide-by-zero
    assert assessment_service.score_from_counts(9, 5) == 1.0        # clamped
    assert 0.0 <= assessment_service.score_from_counts(2, 7) <= 1.0


def test_question_bank_is_structurally_valid():
    problems = bank.validate_bank()
    assert problems == [], f"question bank problems: {problems}"
    assert len(bank.assessable_skills()) >= 5
    for skill in bank.assessable_skills():
        questions = bank.select_questions(skill)
        assert bank.MIN_QUESTIONS <= len(questions) <= bank.MAX_QUESTIONS


def test_grading_is_deterministic_and_hides_answer_keys():
    questions = bank.select_questions("Python", seed="fixed-seed")
    answers = {}
    for q in questions:
        answers[q.id] = q.correct_option if q.is_multiple_choice else q.accepted_answers[0]

    correct, details = assessment_service.grade_responses(questions, answers)
    assert correct == len(questions)
    assert assessment_service.score_from_counts(correct, len(questions)) == 1.0

    # Wrong / missing answers score zero and never crash.
    wrong = {q.id: "definitely-not-the-answer" for q in questions}
    correct_wrong, _ = assessment_service.grade_responses(questions, wrong)
    assert correct_wrong == 0
    empty_correct, empty_details = assessment_service.grade_responses(questions, {})
    assert empty_correct == 0
    assert all(d["answered"] is False for d in empty_details)

    # Questions served to clients never leak the answer.
    for q in questions:
        public = q.public_dict()
        assert "correct_option" not in public
        assert "accepted_answers" not in public
        assert "explanation" not in public

    # Short answers are normalized (case/punctuation/spacing insensitive).
    short = next((q for q in bank.questions_for_skill("Git") if not q.is_multiple_choice), None)
    assert short is not None
    assert short.grade(short.accepted_answers[0].upper() + " ") is True


def test_selection_is_stable_for_the_same_attempt_seed():
    a = [q.id for q in bank.select_questions("SQL", seed="attempt-abc")]
    b = [q.id for q in bank.select_questions("SQL", seed="attempt-abc")]
    assert a == b


# ===========================================================================
# 4 & 5. Assessment influence and confidence effect
# ===========================================================================

def test_assessment_evidence_outweighs_github_evidence():
    github = _github_signal("Python", 0.40)          # weak repo signal
    assessment = _assessment_signal("Python", 0.90)  # strong direct evidence

    prof, _, _, _ = skill_engine.proficiency([github, assessment])
    midpoint = (0.40 + 0.90) / 2
    assert prof > midpoint, "the assessment must pull the estimate more than GitHub"

    # Symmetric check: a poor assessment pulls a strong GitHub estimate down.
    prof_low, _, _, _ = skill_engine.proficiency([_github_signal("Python", 0.85), _assessment_signal("Python", 0.20)])
    assert prof_low < (0.85 + 0.20) / 2

    assert weights.SOURCE_RELIABILITY["assessment"] > weights.SOURCE_RELIABILITY["github"]


def test_assessment_materially_increases_confidence():
    github_only = [_github_signal("Python", 0.75)]
    with_assessment = github_only + [_assessment_signal("Python", 0.80)]

    conf_before, _, _, val_before = skill_engine.confidence_from_signals(github_only)
    conf_after, _, _, val_after = skill_engine.confidence_from_signals(with_assessment)

    assert conf_after > conf_before + 0.20, (conf_before, conf_after)
    assert val_after > val_before
    assert conf_before < 0.40 <= conf_after
    assert weights.has_direct_validation(with_assessment) is True
    assert weights.has_direct_validation(github_only) is False


def test_confidence_is_highest_with_performance_evidence_plus_assessment():
    github = _github_signal("Python", 0.75)
    leetcode = se.make_signal("Python", "leetcode", 0.70, "Solved problems")
    assessment = _assessment_signal("Python", 0.85)

    conf_gh, _, _, _ = skill_engine.confidence_from_signals([github])
    conf_gh_lc, _, _, _ = skill_engine.confidence_from_signals([github, leetcode])
    conf_all, _, _, _ = skill_engine.confidence_from_signals([github, leetcode, assessment])

    assert conf_gh < conf_gh_lc < conf_all


# ===========================================================================
# 6 & 7. Aggregation across sources and repeated attempts
# ===========================================================================

def test_multiple_evidence_types_aggregate_by_weighted_average():
    signals = [
        _github_signal("Python", 0.75),
        se.make_signal("Python", "leetcode", 0.60, "Platform performance"),
        se.make_signal("Python", "resume", 0.35, "Resume claim"),
        _assessment_signal("Python", 0.80),
    ]
    prof, weight, count, _ = skill_engine.proficiency(signals)

    expected = sum(
        s["signal_value"] * s["source_reliability"] for s in signals
    ) / sum(s["source_reliability"] for s in signals)
    assert prof == pytest.approx(expected)
    assert count == 4
    assert weight == pytest.approx(sum(s["source_reliability"] for s in signals))


def test_repeated_attempts_do_not_inflate_proficiency():
    """Ten retries must not add ten pieces of evidence."""
    attempts = [
        _attempt(score=0.6, correct=3, completed_at=NOW - timedelta(days=9), attempt_id="a1"),
        _attempt(score=0.6, correct=3, completed_at=NOW - timedelta(days=8), attempt_id="a2"),
        _attempt(score=0.6, correct=3, completed_at=NOW - timedelta(days=7), attempt_id="a3"),
        _attempt(score=0.6, correct=3, completed_at=NOW - timedelta(days=6), attempt_id="a4"),
        _attempt(score=0.6, correct=3, completed_at=NOW - timedelta(days=5), attempt_id="a5"),
    ]
    signals = assessment_service.build_assessment_signals(attempts)

    assert len(signals) == 1, "one skill must yield exactly one assessment signal"
    sig = signals[0]
    assert sig["signal_value"] == pytest.approx(0.6)
    assert sig["metadata"]["total_attempts"] == 5
    assert sig["metadata"]["attempts_considered"] == assessment_service.RECENT_ATTEMPTS_CONSIDERED

    prof_one, weight_one, count_one, _ = skill_engine.proficiency(
        assessment_service.build_assessment_signals([attempts[0]])
    )
    prof_many, weight_many, count_many, _ = skill_engine.proficiency(signals)
    assert (prof_many, weight_many, count_many) == (prof_one, weight_one, count_one)


def test_effective_attempt_is_best_of_recent_valid_attempts():
    attempts = [
        _attempt(score=1.0, correct=5, completed_at=NOW - timedelta(days=40), attempt_id="old-best"),
        _attempt(score=0.4, correct=2, completed_at=NOW - timedelta(days=3), attempt_id="r1"),
        _attempt(score=0.6, correct=3, completed_at=NOW - timedelta(days=2), attempt_id="r2"),
        _attempt(score=0.2, correct=1, completed_at=NOW - timedelta(days=1), attempt_id="r3"),
    ]
    effective = assessment_service.effective_attempts(attempts)["Python"]
    assert effective["id"] == "r2", "best of the most recent window, not the all-time best"
    assert effective["score"] == 0.6


def test_incomplete_or_invalid_attempts_are_not_used_as_evidence():
    attempts = [
        _attempt(status="in_progress", attempt_id="p1"),
        _attempt(validity="low_confidence", attempt_id="p2"),
        _attempt(validity="invalid", attempt_id="p3"),
    ]
    assert assessment_service.build_assessment_signals(attempts) == []


def test_assessment_signals_are_canonically_named_and_weighted():
    signals = assessment_service.build_assessment_signals([_attempt(skill="python")])
    assert len(signals) == 1
    sig = signals[0]
    assert sig["canonical_name"] == "Python"
    assert sig["source_type"] == "assessment"
    assert sig["source_reliability"] == pytest.approx(weights.SOURCE_RELIABILITY["assessment"])
    # Reliability is a weight, not a proficiency: the signal value is the score.
    assert sig["signal_value"] == pytest.approx(0.8)
    assert sig["signal_value"] != sig["source_reliability"]


# ===========================================================================
# 8, 9, 11, 12. Analysis pipeline behaviour
# ===========================================================================

def _requirements():
    return [
        {"skill": "Python", "required_level": 0.80, "importance": 0.90, "demand": 0.85, "interview_relevance": 0.85},
        {"skill": "Docker", "required_level": 0.60, "importance": 0.60, "demand": 0.60, "interview_relevance": 0.50},
    ]


def _run_pipeline(signals: List[dict]):
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, None))
    req_map = ars.build_requirements_map(_requirements(), None)
    assessments = ars.calculate_assessments(grouped, req_map, None)
    gaps = ars.calculate_gaps(assessments, "Backend Engineer")
    readiness = ars.calculate_readiness(assessments, _requirements(), gaps)
    return {a["canonical_name"]: a for a in assessments}, {g["canonical_name"]: g for g in gaps}, readiness


def test_analysis_works_without_any_assessment():
    """Missing assessment must never block analysis."""
    assessments, gaps, readiness = _run_pipeline([_github_signal("Python", 0.75)])

    python = assessments["Python"]
    assert python["proficiency"] == pytest.approx(0.75)
    assert python["has_assessment"] is False
    assert python["assessment_score"] is None
    assert python["evidence_proficiency"] == pytest.approx(0.75)
    assert python["confidence"] > 0.0
    assert 0.0 <= readiness["readiness_score"] <= 1.0
    assert "Python" in gaps


def test_required_skills_without_evidence_are_still_assessed():
    assessments, gaps, _ = _run_pipeline([_github_signal("Python", 0.75)])

    docker = assessments["Docker"]
    assert docker["is_missing_evidence"] is True
    assert docker["gap_type"] == "evidence_gap"
    assert docker["proficiency"] == 0.0
    assert docker["gap"] == pytest.approx(0.60)
    assert "No evidence found" in gaps["Docker"]["explanation"]


def test_completed_assessment_changes_the_skill_result():
    before_a, before_g, before_r = _run_pipeline([_github_signal("Python", 0.60)])
    after_a, after_g, after_r = _run_pipeline([
        _github_signal("Python", 0.60),
        _assessment_signal("Python", 0.85),
    ])

    b, a = before_a["Python"], after_a["Python"]

    # Proficiency reflects BOTH sources, weighted toward the assessment.
    assert a["proficiency"] > b["proficiency"]
    assert 0.60 < a["proficiency"] < 0.85
    # The evidence-only estimate is preserved and unchanged for comparison.
    assert a["evidence_proficiency"] == pytest.approx(b["proficiency"])
    assert a["assessment_score"] == pytest.approx(0.85)
    assert a["has_assessment"] is True

    # Confidence rises materially because the evidence is now direct.
    assert a["confidence"] > b["confidence"] + 0.20

    # Gap shrinks, and readiness responds.
    assert after_g["Python"]["gap"] < before_g["Python"]["gap"]
    assert after_r["readiness_score"] > before_r["readiness_score"]


def test_low_assessment_score_increases_the_gap():
    _, before_g, before_r = _run_pipeline([_github_signal("Python", 0.80)])
    _, after_g, after_r = _run_pipeline([
        _github_signal("Python", 0.80),
        _assessment_signal("Python", 0.20),
    ])

    assert after_g["Python"]["gap"] > before_g["Python"]["gap"]
    assert after_g["Python"]["current_proficiency"] < before_g["Python"]["current_proficiency"]
    assert after_r["skill_component"] < before_r["skill_component"]


def test_conflicting_evidence_is_flagged_for_assessment():
    assessments, _, _ = _run_pipeline([
        _github_signal("Python", 0.85),
        se.make_signal("Python", "resume", 0.35, "Resume mention"),
    ])
    assert assessments["Python"]["signal_spread"] >= assessment_service.CONFLICT_SPREAD_THRESHOLD

    available = assessment_service.select_assessable_skills([
        {
            "skill": "Python",
            "proficiency": assessments["Python"]["proficiency"],
            "confidence": assessments["Python"]["confidence"],
            "gap": assessments["Python"]["gap"],
            "importance": assessments["Python"]["importance"],
            "priority_score": assessments["Python"]["priority_score"],
            "signal_spread": assessments["Python"]["signal_spread"],
            "evidence_count": assessments["Python"]["evidence_count"],
        }
    ])
    assert available[0]["skill"] == "Python"
    assert available[0]["reason"] == assessment_service.AssessmentReason.CONFLICTING_EVIDENCE


# ===========================================================================
# 5b. Assessment selection rules
# ===========================================================================

def test_selection_only_offers_skills_the_bank_covers():
    rows = [
        {"skill": "Python", "gap": 0.3, "importance": 0.9, "priority_score": 55.0, "confidence": 0.3},
        {"skill": "Quantum Teleportation", "gap": 0.9, "importance": 0.9, "priority_score": 99.0, "confidence": 0.1},
    ]
    selected = assessment_service.select_assessable_skills(rows)
    assert [s["skill"] for s in selected] == ["Python"]


def test_selection_reasons_cover_gap_confidence_and_requirement():
    rows = [
        {"skill": "Python", "gap": 0.30, "importance": 0.90, "priority_score": 60.0, "confidence": 0.55},
        {"skill": "Docker", "gap": 0.0, "importance": 0.40, "priority_score": 5.0, "confidence": 0.25,
         "evidence_count": 2, "proficiency": 0.7},
        {"skill": "SQL", "gap": 0.0, "importance": 0.85, "priority_score": 2.0, "confidence": 0.9},
    ]
    by_skill = {s["skill"]: s for s in assessment_service.select_assessable_skills(rows)}
    assert by_skill["Python"]["reason"] == assessment_service.AssessmentReason.PRIORITY_GAP
    assert by_skill["Docker"]["reason"] == assessment_service.AssessmentReason.LOW_CONFIDENCE
    assert by_skill["SQL"]["reason"] == assessment_service.AssessmentReason.ROLE_REQUIREMENT
    # Highest priority first, and every entry advertises its question count.
    assert list(by_skill)[0] == "Python"
    assert all(s["question_count"] >= bank.MIN_QUESTIONS for s in by_skill.values())


def test_already_assessed_skills_rank_after_unassessed_ones():
    rows = [
        {"skill": "Python", "gap": 0.4, "importance": 0.9, "priority_score": 80.0, "confidence": 0.3,
         "has_assessment": True},
        {"skill": "SQL", "gap": 0.2, "importance": 0.7, "priority_score": 40.0, "confidence": 0.3},
    ]
    order = [s["skill"] for s in assessment_service.select_assessable_skills(rows)]
    assert order == ["SQL", "Python"]


# ===========================================================================
# 10. Existing scoring formulas remain intact
# ===========================================================================

def test_existing_formulas_unchanged():
    # Proficiency: weighted average, untouched.
    sigs = [
        {"signal_strength": 0.80, "source_reliability": 0.70},
        {"signal_strength": 0.40, "source_reliability": 0.85},
    ]
    expected = (0.80 * 0.70 + 0.40 * 0.85) / (0.70 + 0.85)
    prof, weight, count, avg = skill_engine.proficiency(sigs)
    assert prof == pytest.approx(expected)
    assert weight == pytest.approx(1.55)
    assert count == 2
    assert avg == pytest.approx(0.60)

    # Legacy two-term confidence: unchanged when no validation term is supplied.
    conf, w_norm, d_norm = skill_engine.confidence(1.40, 2)
    assert conf == pytest.approx(0.55 * (1.40 / 2.5) + 0.45 * (2 / 3.0))
    assert (w_norm, d_norm) == pytest.approx((1.40 / 2.5, 2 / 3.0))

    # Three-term extension weights sum to 1 and reduce to the same inputs.
    assert (
        skill_engine.CONFIDENCE_VOL_WEIGHT
        + skill_engine.CONFIDENCE_DIV_WEIGHT
        + skill_engine.CONFIDENCE_VAL_WEIGHT
    ) == pytest.approx(1.0)
    conf3, _, _ = skill_engine.confidence(1.40, 2, validation_strength=0.5)
    assert conf3 == pytest.approx(0.40 * (1.40 / 2.5) + 0.25 * (2 / 3.0) + 0.35 * 0.5)

    # Readiness, gap and priority formulas unchanged.
    assert skill_engine.READINESS_WEIGHTS == {"skill": 0.45, "industry": 0.25, "evidence": 0.30}
    assert skill_engine.readiness(0.6, 0.5, 0.4) == pytest.approx(0.45 * 0.6 + 0.25 * 0.5 + 0.30 * 0.4)
    assert skill_engine.gap(0.6, 0.8) == pytest.approx(0.2)
    assert skill_engine.ENGINE_VERSION == "4C-v1"


def test_failed_reverification_keeps_previously_verified_evidence(monkeypatch):
    """
    A rate-limited or offline re-verification must never wipe evidence that was
    inspected successfully before (protects historical analysis inputs).
    """
    import asyncio
    from app.services import evidence_service
    from app.services.evidence.base import VerificationResult, VerificationStatus as VS

    stored = {
        "id": "ev-1",
        "user_id": "u1",
        "evidence_type": "github",
        "source_url": "https://github.com/someone",
        "verification_status": VS.VERIFIED,
        "metadata": {
            "verification_status": VS.VERIFIED,
            "verified_signals": [{"skill": "Python", "signal_strength": 0.75, "source_reliability": 0.60}],
            "inspection": {"repositories_fetched": 12},
        },
    }
    saved: Dict[str, Any] = {}

    monkeypatch.setattr(evidence_service, "get_evidence", lambda uid, eid: stored)

    def _update(uid, eid, payload):
        saved.update(payload)
        return {**stored, **payload}

    monkeypatch.setattr(evidence_service, "update_evidence", _update)

    async def _failed_verify(ev, force_refresh=False):
        return VerificationResult(
            status=VS.FAILED,
            message="GitHub API rate limited",
            provider="github",
            signals=[],
        )

    monkeypatch.setattr(evidence_service.evidence_manager, "verify_evidence", _failed_verify)

    result = asyncio.run(evidence_service.verify_evidence_item("u1", "ev-1", force_refresh=True))

    assert saved["metadata"]["verified_signals"], "previous signals must be retained"
    assert saved["metadata"]["verification_status"] == VS.VERIFIED
    assert "rate limited" in saved["metadata"]["last_verification_error"]
    assert "verification_status" not in saved, "status column must stay untouched on transient failure"
    assert result["detected_skills"] == ["Python"]


# ===========================================================================
# 13. Roadmap consumes the updated gap result
# ===========================================================================

def test_roadmap_drops_a_skill_once_an_assessment_closes_its_gap():
    before_a, before_g, _ = _run_pipeline([_github_signal("Python", 0.50)])
    after_a, after_g, _ = _run_pipeline([
        _github_signal("Python", 0.50),
        _assessment_signal("Python", 1.00),
    ])

    before_items = roadmap_service.filter_and_sort_gaps(list(before_g.values()))
    after_items = roadmap_service.filter_and_sort_gaps(list(after_g.values()))

    assert "Python" in [g["canonical_name"] for g in before_items]
    assert "Python" not in [g["canonical_name"] for g in after_items], (
        "a validated skill that now meets the requirement must leave the roadmap"
    )
    # Docker (still an evidence gap) remains, so the roadmap is not emptied.
    assert "Docker" in [g["canonical_name"] for g in after_items]


def test_roadmap_priority_rises_when_assessment_reveals_a_weakness():
    _, before_g, _ = _run_pipeline([_github_signal("Python", 0.80)])
    _, after_g, _ = _run_pipeline([
        _github_signal("Python", 0.80),
        _assessment_signal("Python", 0.10),
    ])
    assert after_g["Python"]["priority_score"] > before_g["Python"]["priority_score"]


# ===========================================================================
# 14. Existing GitHub multi-repository evidence still flows through
# ===========================================================================

def test_github_multi_repository_evidence_still_reaches_the_engine():
    from app.services.evidence.github import GitHubProvider
    import asyncio

    owner = "multi_repo_dev"
    repos = [
        {
            "id": 1, "name": "svc", "full_name": f"{owner}/svc", "fork": False, "archived": False,
            "size": 4000, "language": "Python", "pushed_at": NOW.isoformat(),
            "inspection": {
                "languages": {"Python": 30000},
                "root_files": ["requirements.txt"],
                "top_files": ["app/main.py", "tests/test_main.py"],
                "python_deps": ["fastapi", "pytest"],
            },
        },
        {
            "id": 2, "name": "tools", "full_name": f"{owner}/tools", "fork": False, "archived": False,
            "size": 2000, "language": "Python", "pushed_at": NOW.isoformat(),
            "inspection": {
                "languages": {"Python": 9000},
                "root_files": ["requirements.txt"],
                "top_files": ["cli.py"],
            },
        },
    ]
    res = asyncio.run(GitHubProvider().verify(
        {"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}
    ))
    python_sigs = [s for s in res.signals if s.skill == "Python"]
    assert len(python_sigs) == 1
    assert python_sigs[0].metadata["repo_count"] == 2
    assert python_sigs[0].source_reliability == pytest.approx(weights.SOURCE_RELIABILITY["github"])

    assessments, _, _ = _run_pipeline([
        se.make_signal(
            canonical=s.skill, source_type="github", signal_value=s.signal_strength, explanation=s.reason
        )
        for s in res.signals
    ])
    assert assessments["Python"]["proficiency"] > 0.0
    assert assessments["Python"]["confidence"] < 0.50, "multi-repo GitHub alone stays low-confidence"


# ===========================================================================
# 15. The endpoints the frontend calls, against the real app
# ===========================================================================

class _FakeQuery:
    def __init__(self, store: Dict[str, List[dict]], table: str):
        self.store = store
        self.table = table
        self.filters: List[tuple] = []
        self.mode = "select"
        self.payload: Any = None
        self._limit: Optional[int] = None

    # -- builder API used by the service -----------------------------------
    def select(self, *_a, **_k):
        self.mode = "select"
        return self

    def insert(self, row):
        self.mode = "insert"
        self.payload = row
        return self

    def update(self, row):
        self.mode = "update"
        self.payload = row
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = self.store.setdefault(self.table, [])
        if self.mode == "insert":
            rows.append(dict(self.payload))
            return type("R", (), {"data": [dict(self.payload)]})()
        matched = [r for r in rows if all(r.get(f) == v for f, v in self.filters)]
        if self.mode == "update":
            for r in matched:
                r.update(self.payload)
            return type("R", (), {"data": matched})()
        if self._limit is not None:
            matched = matched[: self._limit]
        return type("R", (), {"data": matched})()


class _FakeSupabase:
    def __init__(self):
        self.store: Dict[str, List[dict]] = {}

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self.store, name)


@pytest.fixture()
def api_client(monkeypatch):
    from app.main import app
    from app.core.security import get_current_user, CurrentUser

    fake_db = _FakeSupabase()
    monkeypatch.setattr(assessment_service, "get_supabase_client", lambda: fake_db)
    # Recalculation needs the full analysis stack + DB; it is covered by the
    # pipeline tests above, so stub it out for the HTTP-level test.
    async def _no_recalc(user_id, skill):
        return {"analysis_id": None, "readiness_score": None, "skill": None}
    monkeypatch.setattr(assessment_service, "_recalculate_analysis", _no_recalc)

    app.dependency_overrides[get_current_user] = lambda: CurrentUser("user-123", "student@example.com")
    client = TestClient(app)
    yield client, fake_db
    app.dependency_overrides.clear()


def test_assessment_endpoints_support_the_frontend_flow(api_client):
    client, fake_db = api_client

    # 1. available
    r = client.get("/api/v1/analysis/assessment/available")
    assert r.status_code == 200
    body = r.json()
    assert body["assessment_version"] == bank.ASSESSMENT_VERSION
    assert len(body["available"]) > 0
    assert "prototype" in body["disclaimer"].lower()
    skill = body["available"][0]["skill"]

    # 2. start — questions arrive without answer keys
    r = client.post("/api/v1/analysis/assessment/start", json={"skill": skill})
    assert r.status_code == 200, r.text
    started = r.json()
    assert started["skill"] == skill
    assert bank.MIN_QUESTIONS <= started["question_count"] <= bank.MAX_QUESTIONS
    assert len(started["questions"]) == started["question_count"]
    raw = r.text.lower()
    assert "correct_option" not in raw and "accepted_answers" not in raw

    # 3. submit — deterministic grading of known-correct answers
    answers = {}
    for q in started["questions"]:
        source = bank.get_question(q["id"])
        answers[q["id"]] = source.correct_option if source.is_multiple_choice else source.accepted_answers[0]
    r = client.post(
        "/api/v1/analysis/assessment/submit",
        json={"attempt_id": started["attempt_id"], "responses": answers, "duration_seconds": 90},
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["score"] == 1.0
    assert result["correct_count"] == result["question_count"]
    assert result["validity"] == "valid"
    assert result["counts_as_evidence"] is True
    assert result["source_reliability"] == pytest.approx(weights.SOURCE_RELIABILITY["assessment"])
    assert len(result["feedback"]) == started["question_count"]

    # Stored attempt keeps correctness only — never the submitted answer text.
    stored = fake_db.store["assessment_attempts"][0]
    assert stored["status"] == "completed"
    assert stored["score"] == 1.0
    allowed_keys = {"question_id", "difficulty", "kind", "correct", "answered"}
    per_question = stored["result_summary"]["per_question"]
    assert len(per_question) == started["question_count"]
    for entry in per_question:
        assert set(entry) == allowed_keys
    # No field anywhere in the stored row holds a response/answer payload.
    assert not any(
        key for key in str(stored).lower().split("'")
        if key in ("answer", "answers", "response", "responses", "submitted_answer")
    )

    # 4. the same attempt cannot be graded twice
    r = client.post(
        "/api/v1/analysis/assessment/submit",
        json={"attempt_id": started["attempt_id"], "responses": answers},
    )
    assert r.status_code == 409

    # 5. available now reports the completed assessment
    r = client.get("/api/v1/analysis/assessment/available")
    entry = next(a for a in r.json()["available"] if a["skill"] == skill)
    assert entry["last_assessment"]["score"] == 1.0
    assert entry["already_assessed"] is True


def test_start_rejects_a_skill_without_questions(api_client):
    client, _ = api_client
    r = client.post("/api/v1/analysis/assessment/start", json={"skill": "Kubernetes"})
    assert r.status_code == 404
    r = client.post("/api/v1/analysis/assessment/start", json={"skill": "not-a-real-skill"})
    assert r.status_code == 400


def test_partial_submission_is_recorded_but_not_used_as_evidence(api_client):
    client, fake_db = api_client
    started = client.post("/api/v1/analysis/assessment/start", json={"skill": "Python"}).json()
    first = started["questions"][0]
    source = bank.get_question(first["id"])
    answers = {first["id"]: source.correct_option if source.is_multiple_choice else source.accepted_answers[0]}

    result = client.post(
        "/api/v1/analysis/assessment/submit",
        json={"attempt_id": started["attempt_id"], "responses": answers},
    ).json()

    assert result["validity"] == "low_confidence"
    assert result["counts_as_evidence"] is False
    assert assessment_service.build_assessment_signals(fake_db.store["assessment_attempts"]) == []
