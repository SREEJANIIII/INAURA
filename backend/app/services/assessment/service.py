"""
INAURA direct skill assessment service.

Responsibilities:
  * decide which skills are worth assessing (generic, evidence-driven rules)
  * start an attempt and serve its questions without answer keys
  * grade a submission deterministically and persist the result
  * turn stored attempts into a single evidence signal per skill

Prototype disclaimer: a short quiz is a heuristic proxy. It is INAURA's most
direct evidence source, but it is not a validated psychometric measurement of
human proficiency.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import logging
import uuid

from fastapi import HTTPException

from ...core.supabase import get_supabase_client
from ..evidence_weights import ASSESSMENT_SOURCE, reliability
from ..signal_extractor import make_signal
from ..skill_taxonomy import normalize_skill, normalize_skill_slug
from .question_bank import (
    ASSESSMENT_VERSION,
    DEFAULT_QUESTION_COUNT,
    MIN_QUESTIONS,
    AssessmentQuestion,
    BANK_SKILLS,
    get_question,
    has_questions,
    select_questions,
)

logger = logging.getLogger(__name__)

ATTEMPTS_TABLE = "assessment_attempts"
GAPS_TABLE = "skill_gaps"
RESULTS_TABLE = "analysis_results"

ASSESSMENT_RELIABILITY = reliability(ASSESSMENT_SOURCE)

# Aggregation policy: only the best of the most recent N valid attempts counts,
# so repeated retries cannot stack additional evidence for the same skill.
RECENT_ATTEMPTS_CONSIDERED = 3

# Selection thresholds (prototype heuristics)
LOW_CONFIDENCE_THRESHOLD = 0.50
CONFLICT_SPREAD_THRESHOLD = 0.35
HIGH_IMPORTANCE_THRESHOLD = 0.70
MAX_AVAILABLE_ASSESSMENTS = 12

# An in-progress attempt expires so abandoned attempts cannot be graded later.
ATTEMPT_TTL_MINUTES = 120


class AssessmentReason:
    """Why INAURA offers an assessment for a skill (ordered by precedence)."""

    CONFLICTING_EVIDENCE = "conflicting_evidence"
    PRIORITY_GAP = "priority_gap"
    LOW_CONFIDENCE = "low_confidence"
    ROLE_REQUIREMENT = "role_requirement"

    LABELS = {
        CONFLICTING_EVIDENCE: "Evidence sources disagree about this skill",
        PRIORITY_GAP: "High-priority gap for your target role",
        LOW_CONFIDENCE: "Detected from evidence, but with low confidence",
        ROLE_REQUIREMENT: "Important requirement for your target role",
    }


# ---------------------------------------------------------------------------
# Pure scoring / selection logic (no I/O — unit testable)
# ---------------------------------------------------------------------------

def score_from_counts(correct_count: int, question_count: int) -> float:
    """Normalize an assessment result to [0, 1]: correct / total."""
    total = int(question_count or 0)
    if total <= 0:
        return 0.0
    correct = max(0, min(int(correct_count or 0), total))
    return round(correct / total, 4)


def grade_responses(
    questions: List[AssessmentQuestion],
    responses: Dict[str, str],
) -> Tuple[int, List[dict]]:
    """
    Deterministically grade one submission.

    Returns (correct_count, per_question_results). Results carry correctness and
    the explanation, never the submitted answer text.
    """
    correct_count = 0
    details: List[dict] = []
    for q in questions:
        raw = (responses or {}).get(q.id)
        is_correct = q.grade(raw)
        if is_correct:
            correct_count += 1
        details.append({
            "question_id": q.id,
            "skill": q.skill,
            "difficulty": q.difficulty,
            "kind": q.kind,
            "correct": is_correct,
            "answered": raw is not None and str(raw).strip() != "",
            "explanation": q.explanation,
        })
    return correct_count, details


def select_assessable_skills(
    skill_rows: List[dict],
    limit: int = MAX_AVAILABLE_ASSESSMENTS,
) -> List[dict]:
    """
    Choose which skills INAURA has a reason to assess.

    `skill_rows` are per-skill analysis facts (canonical skill name, proficiency,
    confidence, required_level, gap, importance, priority_score, gap_type and
    optional signal_spread). The rules are generic — a skill qualifies when the
    question bank covers it AND at least one evidence-driven reason applies:

      * conflicting evidence  — sources disagree by more than the spread threshold
      * priority gap          — a role requirement that is not yet met
      * low confidence        — evidence exists but is not directly validated
      * role requirement      — important for the target role

    No technology is special-cased; coverage comes from the bank alone.
    """
    candidates: List[dict] = []
    for row in skill_rows or []:
        raw_skill = row.get("skill") or row.get("canonical_name") or ""
        canonical = normalize_skill(raw_skill) or raw_skill
        if not canonical or not has_questions(canonical):
            continue

        proficiency = float(row.get("proficiency", row.get("current_proficiency", 0.0)) or 0.0)
        conf = float(row.get("confidence", 0.0) or 0.0)
        gap = float(row.get("gap", 0.0) or 0.0)
        importance = float(row.get("importance", 0.0) or 0.0)
        priority = float(row.get("priority_score", row.get("priority", 0.0)) or 0.0)
        spread = float(row.get("signal_spread", 0.0) or 0.0)
        evidence_count = int(row.get("evidence_count", 0) or 0)
        already_assessed = bool(row.get("has_assessment"))

        reason: Optional[str] = None
        if spread >= CONFLICT_SPREAD_THRESHOLD:
            reason = AssessmentReason.CONFLICTING_EVIDENCE
        elif gap > 0.0 and importance > 0.0:
            reason = AssessmentReason.PRIORITY_GAP
        elif conf < LOW_CONFIDENCE_THRESHOLD and (evidence_count > 0 or proficiency > 0.0):
            reason = AssessmentReason.LOW_CONFIDENCE
        elif importance >= HIGH_IMPORTANCE_THRESHOLD:
            reason = AssessmentReason.ROLE_REQUIREMENT
        if reason is None:
            continue

        candidates.append({
            "skill": canonical,
            "skill_key": normalize_skill_slug(canonical) or canonical.lower(),
            "reason": reason,
            "reason_label": AssessmentReason.LABELS.get(reason, ""),
            "proficiency": round(proficiency, 4),
            "confidence": round(conf, 4),
            "required_level": round(float(row.get("required_level", 0.0) or 0.0), 4),
            "gap": round(gap, 4),
            "importance": round(importance, 4),
            "priority_score": round(priority, 2),
            "evidence_count": evidence_count,
            "already_assessed": already_assessed,
            "question_count": min(DEFAULT_QUESTION_COUNT, len(select_questions(canonical))),
        })

    # Not-yet-assessed first, then highest priority, then lowest confidence.
    candidates.sort(
        key=lambda c: (c["already_assessed"], -c["priority_score"], c["confidence"])
    )
    # De-duplicate by canonical skill, preserving rank.
    seen = set()
    ranked: List[dict] = []
    for c in candidates:
        if c["skill"] in seen:
            continue
        seen.add(c["skill"])
        ranked.append(c)
        if len(ranked) >= max(1, int(limit)):
            break
    return ranked


def _attempt_sort_key(attempt: dict) -> str:
    return str(attempt.get("completed_at") or attempt.get("created_at") or "")


def effective_attempts(attempts: List[dict]) -> Dict[str, dict]:
    """
    Reduce raw attempt rows to at most ONE effective attempt per skill.

    Policy: among the most recent RECENT_ATTEMPTS_CONSIDERED valid, completed
    attempts for a skill, take the best score. Retrying therefore cannot add
    evidence weight — it can only replace the estimate within a bounded window.
    """
    by_skill: Dict[str, List[dict]] = {}
    for a in attempts or []:
        if str(a.get("status") or "") != "completed":
            continue
        if str(a.get("validity") or "valid") != "valid":
            continue
        skill_name = a.get("skill_name") or a.get("skill") or ""
        canonical = normalize_skill(skill_name) or skill_name
        if not canonical:
            continue
        by_skill.setdefault(canonical, []).append(a)

    effective: Dict[str, dict] = {}
    for canonical, rows in by_skill.items():
        rows.sort(key=_attempt_sort_key, reverse=True)
        window = rows[:RECENT_ATTEMPTS_CONSIDERED]
        best = max(window, key=lambda r: float(r.get("score", 0.0) or 0.0))
        effective[canonical] = {
            **best,
            "attempts_considered": len(window),
            "total_attempts": len(rows),
        }
    return effective


def build_assessment_signals(attempts: List[dict]) -> List[dict]:
    """
    Convert stored attempts into evidence signals — exactly one per skill.

    The signal's strength is the normalized assessment score (direct evidence of
    what the person demonstrated); its reliability comes from the central
    weighting config (VERY HIGH). The two remain separate concepts.
    """
    signals: List[dict] = []
    for canonical, attempt in sorted(effective_attempts(attempts).items()):
        score = float(attempt.get("score", 0.0) or 0.0)
        correct = int(attempt.get("correct_count", 0) or 0)
        total = int(attempt.get("question_count", 0) or 0)
        completed_at = attempt.get("completed_at")
        explanation = (
            f"INAURA skill assessment: {correct}/{total} correct "
            f"({int(round(score * 100))}%) on {canonical} "
            f"({attempt.get('assessment_version', ASSESSMENT_VERSION)})."
        )
        signals.append(
            make_signal(
                canonical=canonical,
                source_type=ASSESSMENT_SOURCE,
                signal_value=score,
                explanation=explanation,
                metadata={
                    "assessment_attempt_id": attempt.get("id"),
                    "assessment_score": round(score, 4),
                    "correct_count": correct,
                    "question_count": total,
                    "assessment_version": attempt.get("assessment_version", ASSESSMENT_VERSION),
                    "completed_at": completed_at,
                    "attempts_considered": attempt.get("attempts_considered", 1),
                    "total_attempts": attempt.get("total_attempts", 1),
                    "aggregation": "best_of_recent_valid_attempts",
                    "prototype_instrument": True,
                },
            )
        )
    return signals


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _client():
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    return c


def _table_missing(err: Exception) -> bool:
    m = str(err).lower()
    return "could not find the table" in m or "pgrst205" in m or "does not exist" in m


def list_attempts(user_id: str, skill: Optional[str] = None) -> List[dict]:
    """Load a user's assessment attempts (most recent first)."""
    c = _client()
    try:
        q = c.table(ATTEMPTS_TABLE).select("*").eq("user_id", user_id)
        if skill:
            canonical = normalize_skill(skill) or skill
            q = q.eq("skill_name", canonical)
        r = q.order("created_at", desc=True).limit(200).execute()
        return r.data or []
    except Exception as e:
        if _table_missing(e):
            raise HTTPException(
                status_code=503,
                detail="Assessment tables not found — run backend/supabase/012_skill_assessment.sql",
            )
        logger.debug("Failed to list assessment attempts: %s", e)
        return []


def load_assessment_signals(user_id: str) -> List[dict]:
    """
    Assessment evidence signals for the analysis pipeline.

    Never raises: a missing assessment table simply means no assessment
    evidence yet, and analysis must continue with the other sources.
    """
    try:
        return build_assessment_signals(list_attempts(user_id))
    except HTTPException:
        return []
    except Exception as e:
        logger.debug("Assessment signals unavailable for %s: %s", user_id, e)
        return []


def _skill_id_for(c, canonical: str) -> Optional[str]:
    try:
        slug = normalize_skill_slug(canonical) or canonical.lower()
        r = c.table("skills").select("id, canonical_name").eq("canonical_name", slug).limit(1).execute()
        if r.data:
            return r.data[0]["id"]
    except Exception:
        pass
    return None


def _latest_analysis_rows(user_id: str) -> Tuple[Optional[dict], List[dict]]:
    """Latest analysis result plus its persisted skill gaps (best effort)."""
    c = _client()
    analysis: Optional[dict] = None
    gaps: List[dict] = []
    try:
        r = (
            c.table(RESULTS_TABLE).select("*").eq("user_id", user_id)
            .order("created_at", desc=True).limit(1).execute()
        )
        if r.data:
            analysis = r.data[0]
    except Exception as e:
        logger.debug("No analysis results available: %s", e)
    if analysis:
        try:
            r2 = (
                c.table(GAPS_TABLE)
                .select("*, skills(canonical_name, display_name, category)")
                .eq("user_id", user_id)
                .eq("analysis_result_id", analysis["id"])
                .execute()
            )
            gaps = r2.data or []
        except Exception as e:
            logger.debug("No gaps available: %s", e)
    return analysis, gaps


def _gap_rows_to_skill_rows(gaps: List[dict]) -> List[dict]:
    rows: List[dict] = []
    for g in gaps:
        skills = g.get("skills") or {}
        name = skills.get("display_name") or skills.get("canonical_name") or g.get("skill") or ""
        rows.append({
            "skill": name,
            "proficiency": g.get("current_proficiency", 0.0),
            "confidence": g.get("confidence", 0.0),
            "required_level": g.get("required_level", 0.0),
            "gap": g.get("gap", 0.0),
            "importance": g.get("importance", 0.0),
            "priority_score": g.get("priority_score", 0.0),
            "gap_type": g.get("gap_type", "skill_gap"),
            "evidence_count": 1 if float(g.get("current_proficiency", 0.0) or 0.0) > 0 else 0,
        })
    return rows


def list_available_assessments(user_id: str) -> dict:
    """
    Skills INAURA offers to verify for this user, plus their latest results.

    Falls back to the target-role requirement list when no analysis has been
    run yet, so a user is never blocked from verifying a skill.
    """
    analysis, gaps = _latest_analysis_rows(user_id)
    skill_rows = _gap_rows_to_skill_rows(gaps)

    attempts = list_attempts(user_id)
    effective = effective_attempts(attempts)
    for row in skill_rows:
        canonical = normalize_skill(row["skill"]) or row["skill"]
        row["has_assessment"] = canonical in effective

    available = select_assessable_skills(skill_rows)

    if not available:
        # No analysis yet (or nothing flagged): offer the bank's coverage so the
        # feature is still reachable. Assessment is always optional.
        available = [
            {
                "skill": name,
                "skill_key": slug,
                "reason": AssessmentReason.ROLE_REQUIREMENT,
                "reason_label": "Available for verification",
                "proficiency": 0.0,
                "confidence": 0.0,
                "required_level": 0.0,
                "gap": 0.0,
                "importance": 0.0,
                "priority_score": 0.0,
                "evidence_count": 0,
                "already_assessed": name in effective,
                "question_count": min(DEFAULT_QUESTION_COUNT, len(select_questions(name))),
            }
            for slug, name in sorted(BANK_SKILLS.items(), key=lambda kv: kv[1])
        ][:MAX_AVAILABLE_ASSESSMENTS]

    for item in available:
        attempt = effective.get(item["skill"])
        item["last_assessment"] = (
            {
                "attempt_id": attempt.get("id"),
                "score": float(attempt.get("score", 0.0) or 0.0),
                "correct_count": int(attempt.get("correct_count", 0) or 0),
                "question_count": int(attempt.get("question_count", 0) or 0),
                "completed_at": attempt.get("completed_at"),
                "assessment_version": attempt.get("assessment_version", ASSESSMENT_VERSION),
                "total_attempts": attempt.get("total_attempts", 1),
            }
            if attempt
            else None
        )

    return {
        "assessment_version": ASSESSMENT_VERSION,
        "target_role": (analysis or {}).get("target_role"),
        "analysis_id": (analysis or {}).get("id"),
        "available": available,
        "disclaimer": (
            "Prototype instrument: a short deterministic quiz used as INAURA's most "
            "direct evidence source. It is not a validated measurement of human proficiency."
        ),
    }


def start_attempt(user_id: str, skill: str, question_count: int = DEFAULT_QUESTION_COUNT) -> dict:
    """Create an attempt and return its questions without answer keys."""
    canonical = normalize_skill(skill) or ""
    if not canonical:
        raise HTTPException(status_code=400, detail=f"Unknown skill '{skill}'")
    if not has_questions(canonical):
        raise HTTPException(
            status_code=404,
            detail=f"No assessment is available yet for '{canonical}'",
        )

    attempt_id = str(uuid.uuid4())
    questions = select_questions(canonical, limit=question_count, seed=attempt_id)
    if len(questions) < MIN_QUESTIONS:
        raise HTTPException(status_code=404, detail=f"No assessment is available yet for '{canonical}'")

    now = datetime.now(timezone.utc)
    c = _client()
    row = {
        "id": attempt_id,
        "user_id": user_id,
        "skill_id": _skill_id_for(c, canonical),
        "skill_key": normalize_skill_slug(canonical) or canonical.lower(),
        "skill_name": canonical,
        "assessment_version": ASSESSMENT_VERSION,
        "status": "in_progress",
        "question_ids": [q.id for q in questions],
        "question_count": len(questions),
        "correct_count": 0,
        "score": 0.0,
        "validity": "valid",
        "result_summary": {},
        "started_at": now.isoformat(),
    }
    try:
        c.table(ATTEMPTS_TABLE).insert(row).execute()
    except Exception as e:
        if _table_missing(e):
            raise HTTPException(
                status_code=503,
                detail="Assessment tables not found — run backend/supabase/012_skill_assessment.sql",
            )
        raise HTTPException(status_code=500, detail=f"Failed to start assessment: {str(e)[:200]}")

    return {
        "attempt_id": attempt_id,
        "skill": canonical,
        "skill_key": row["skill_key"],
        "assessment_version": ASSESSMENT_VERSION,
        "question_count": len(questions),
        "started_at": row["started_at"],
        "expires_at": (now + timedelta(minutes=ATTEMPT_TTL_MINUTES)).isoformat(),
        "questions": [q.public_dict() for q in questions],
        "disclaimer": (
            "Prototype instrument — results contribute as INAURA's strongest evidence "
            "source but are not a validated measurement of human proficiency."
        ),
    }


def _load_attempt(c, user_id: str, attempt_id: str) -> dict:
    try:
        r = (
            c.table(ATTEMPTS_TABLE).select("*")
            .eq("user_id", user_id).eq("id", attempt_id).limit(1).execute()
        )
    except Exception as e:
        if _table_missing(e):
            raise HTTPException(
                status_code=503,
                detail="Assessment tables not found — run backend/supabase/012_skill_assessment.sql",
            )
        raise HTTPException(status_code=500, detail="Failed to load assessment attempt")
    if not r.data:
        raise HTTPException(status_code=404, detail="Assessment attempt not found")
    return r.data[0]


def _is_expired(attempt: dict, now: datetime) -> bool:
    started = attempt.get("started_at") or attempt.get("created_at")
    if not started:
        return False
    try:
        started_dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        if started_dt.tzinfo is None:
            started_dt = started_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return (now - started_dt) > timedelta(minutes=ATTEMPT_TTL_MINUTES)


async def submit_attempt(
    user_id: str,
    attempt_id: str,
    responses: Dict[str, str],
    duration_seconds: Optional[int] = None,
    recalculate: bool = True,
) -> dict:
    """
    Grade a submission, persist the result, and recalculate the analysis.

    Only per-question correctness is stored — never the submitted answer text.
    """
    c = _client()
    attempt = _load_attempt(c, user_id, attempt_id)
    now = datetime.now(timezone.utc)

    if str(attempt.get("status")) == "completed":
        raise HTTPException(status_code=409, detail="This assessment attempt was already submitted")

    question_ids = list(attempt.get("question_ids") or [])
    questions = [q for q in (get_question(qid) for qid in question_ids) if q is not None]
    if not questions:
        raise HTTPException(status_code=409, detail="Assessment questions are no longer available")

    correct_count, details = grade_responses(questions, responses or {})
    question_count = len(questions)
    score = score_from_counts(correct_count, question_count)

    expired = _is_expired(attempt, now)
    answered = sum(1 for d in details if d["answered"])
    if question_count < MIN_QUESTIONS:
        validity = "invalid"
    elif expired or answered < question_count:
        # Partial or late submissions still record a result but are not used as
        # skill evidence, so an abandoned attempt cannot depress a skill.
        validity = "low_confidence"
    else:
        validity = "valid"

    canonical = normalize_skill(attempt.get("skill_name") or "") or str(attempt.get("skill_name") or "")
    update = {
        "status": "completed",
        "correct_count": correct_count,
        "question_count": question_count,
        "score": score,
        "validity": validity,
        "completed_at": now.isoformat(),
        "duration_seconds": int(duration_seconds) if duration_seconds is not None else None,
        "result_summary": {
            "per_question": [
                {k: v for k, v in d.items() if k in ("question_id", "difficulty", "kind", "correct", "answered")}
                for d in details
            ],
            "answered": answered,
            "expired": expired,
            "assessment_version": attempt.get("assessment_version", ASSESSMENT_VERSION),
        },
    }
    try:
        c.table(ATTEMPTS_TABLE).update(update).eq("id", attempt_id).eq("user_id", user_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save assessment result: {str(e)[:200]}")

    result = {
        "attempt_id": attempt_id,
        "skill": canonical,
        "assessment_version": attempt.get("assessment_version", ASSESSMENT_VERSION),
        "score": score,
        "correct_count": correct_count,
        "question_count": question_count,
        "validity": validity,
        "counts_as_evidence": validity == "valid",
        "completed_at": update["completed_at"],
        "source_reliability": ASSESSMENT_RELIABILITY,
        "feedback": details,
        "disclaimer": (
            "Prototype instrument: this result is weighted as direct evidence, not "
            "treated as a definitive measurement of proficiency."
        ),
    }

    if recalculate:
        result["analysis"] = await _recalculate_analysis(user_id, canonical)
    return result


async def _recalculate_analysis(user_id: str, canonical_skill: str) -> Optional[dict]:
    """
    Re-run the existing analysis pipeline so the new assessment flows through
    proficiency -> confidence -> gap -> priority -> readiness -> roadmap inputs.
    Failures never block returning the graded result.
    """
    try:
        from ..analysis_run_service import run_analysis
        from .. import analysis_service

        state = analysis_service.get_state(user_id) or {}
        target_role = state.get("target_role")
        if not target_role:
            return None

        analysis = await run_analysis(user_id, target_role)
        skill_entry = next(
            (a for a in analysis.get("assessments", []) if a.get("skill") == canonical_skill),
            None,
        )
        return {
            "analysis_id": analysis.get("id"),
            "target_role": analysis.get("target_role"),
            "readiness_score": analysis.get("readiness_score"),
            "evidence_component": analysis.get("evidence_component"),
            "skill": skill_entry,
        }
    except Exception as e:
        logger.debug("Post-assessment recalculation failed for %s: %s", user_id, e)
        return None
