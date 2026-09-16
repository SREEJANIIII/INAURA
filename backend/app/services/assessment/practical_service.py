"""
Practical (work-sample) assessment service — Layer 2 of skill assessment.

Mirrors the knowledge-layer service design:
  * start an attempt and serve its task (starter included, no solution exists
    server-side beyond structural checks)
  * grade deterministically and persist the result (code IS the evidence, so
    the submission text is stored — unlike MCQ answer text)
  * turn stored attempts into standard evidence signals
    (source_type="assessment", assessment_layer="practical")

Prototype disclaimer: structural checks are a heuristic proxy. The signal is
honest evidence of what was submitted, not a validated measurement.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import logging
import uuid

from fastapi import HTTPException

from ...core.supabase import get_supabase_client
from ..evidence_weights import ASSESSMENT_SOURCE, reliability
from ..signal_extractor import make_signal
from ..skill_taxonomy import normalize_skill, normalize_skill_slug
from .layers import PRACTICAL
from .practical_bank import (
    PRACTICAL_VERSION,
    PracticalTask,
    dimension_scores,
    get_task,
    grade_task_submission,
    has_practical,
    select_task,
)

logger = logging.getLogger(__name__)

PRACTICAL_ATTEMPTS_TABLE = "assessment_practical_attempts"

PRACTICAL_RELIABILITY = reliability(ASSESSMENT_SOURCE)

RECENT_PRACTICAL_ATTEMPTS_CONSIDERED = 3


# ---------------------------------------------------------------------------
# Pure grading logic (no I/O — unit testable)
# ---------------------------------------------------------------------------

def grade_practical_submission(
    task: PracticalTask, code: Optional[str]
) -> Tuple[float, List[dict], Dict[str, float]]:
    """Grade one submission: (score, per_check, per_dimension)."""
    score, checks = grade_task_submission(task, code)
    dims = dimension_scores(task, checks)
    return score, checks, dims


def effective_practical_attempts(attempts: List[dict]) -> Dict[str, dict]:
    """
    Reduce raw practical attempts to at most ONE effective attempt per skill:
    best score among the most recent valid, completed attempts.
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

    def _key(a: dict) -> str:
        return str(a.get("completed_at") or a.get("created_at") or "")

    effective: Dict[str, dict] = {}
    for canonical, rows in by_skill.items():
        rows.sort(key=_key, reverse=True)
        window = rows[:RECENT_PRACTICAL_ATTEMPTS_CONSIDERED]
        best = max(window, key=lambda r: float(r.get("score", 0.0) or 0.0))
        effective[canonical] = {
            **best,
            "attempts_considered": len(window),
            "total_attempts": len(rows),
        }
    return effective


def build_practical_signals(attempts: List[dict]) -> List[dict]:
    """
    Convert stored practical attempts into evidence signals — one per skill.

    Same contract as the knowledge layer (source_type="assessment") with an
    ``assessment_layer="practical"`` marker so layers stay distinguishable.
    """
    signals: List[dict] = []
    for canonical, attempt in sorted(effective_practical_attempts(attempts).items()):
        score = float(attempt.get("score", 0.0) or 0.0)
        task_id = attempt.get("task_id") or "practical task"
        completed_at = attempt.get("completed_at")
        explanation = (
            f"INAURA practical assessment: {int(round(score * 100))}% on {canonical} "
            f"({attempt.get('task_version', PRACTICAL_VERSION)})."
        )
        signals.append(
            make_signal(
                canonical=canonical,
                source_type=ASSESSMENT_SOURCE,
                signal_value=score,
                explanation=explanation,
                metadata={
                    "assessment_layer": PRACTICAL,
                    "assessment_attempt_id": attempt.get("id"),
                    "assessment_score": round(score, 4),
                    "task_id": task_id,
                    "task_version": attempt.get("task_version", PRACTICAL_VERSION),
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


def list_practical_attempts(user_id: str, skill: Optional[str] = None) -> List[dict]:
    c = _client()
    try:
        q = c.table(PRACTICAL_ATTEMPTS_TABLE).select("*").eq("user_id", user_id)
        if skill:
            canonical = normalize_skill(skill) or skill
            q = q.eq("skill_name", canonical)
        r = q.order("created_at", desc=True).limit(200).execute()
        return r.data or []
    except Exception as e:
        if _table_missing(e):
            raise HTTPException(
                status_code=503,
                detail="Practical assessment tables not found — run backend/supabase/019_assessment_layers.sql",
            )
        logger.debug("Failed to list practical attempts: %s", e)
        return []


def load_practical_signals(user_id: str) -> List[dict]:
    """Practical evidence signals for the analysis pipeline. Never raises."""
    try:
        return build_practical_signals(list_practical_attempts(user_id))
    except HTTPException:
        return []
    except Exception as e:
        logger.debug("Practical signals unavailable for %s: %s", user_id, e)
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


def start_practical_attempt(user_id: str, skill: str) -> dict:
    """Create a practical attempt and return its task (starter included)."""
    canonical = normalize_skill(skill) or ""
    if not canonical:
        raise HTTPException(status_code=400, detail=f"Unknown skill '{skill}'")
    task = select_task(canonical)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=f"No practical assessment is available yet for '{canonical}'",
        )

    attempt_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    c = _client()
    row = {
        "id": attempt_id,
        "user_id": user_id,
        "skill_id": _skill_id_for(c, canonical),
        "skill_key": normalize_skill_slug(canonical) or canonical.lower(),
        "skill_name": canonical,
        "task_id": task.id,
        "task_version": task.version,
        "status": "in_progress",
        "score": 0.0,
        "validity": "valid",
        "result_summary": {},
        "started_at": now.isoformat(),
    }
    try:
        c.table(PRACTICAL_ATTEMPTS_TABLE).insert(row).execute()
    except Exception as e:
        if _table_missing(e):
            raise HTTPException(
                status_code=503,
                detail="Practical assessment tables not found — run backend/supabase/019_assessment_layers.sql",
            )
        raise HTTPException(status_code=500, detail=f"Failed to start practical assessment: {str(e)[:200]}")

    return {
        "attempt_id": attempt_id,
        "skill": canonical,
        "skill_key": row["skill_key"],
        "task_version": task.version,
        "started_at": row["started_at"],
        "task": task.public_dict(),
        "disclaimer": (
            "Prototype instrument — a structural work-sample check used as supporting "
            "assessment evidence, not a validated measurement of human proficiency."
        ),
    }


def _load_practical_attempt(c, user_id: str, attempt_id: str) -> dict:
    try:
        r = (
            c.table(PRACTICAL_ATTEMPTS_TABLE).select("*")
            .eq("user_id", user_id).eq("id", attempt_id).limit(1).execute()
        )
    except Exception as e:
        if _table_missing(e):
            raise HTTPException(
                status_code=503,
                detail="Practical assessment tables not found — run backend/supabase/019_assessment_layers.sql",
            )
        raise HTTPException(status_code=500, detail="Failed to load practical attempt")
    if not r.data:
        raise HTTPException(status_code=404, detail="Practical attempt not found")
    return r.data[0]


async def submit_practical_attempt(
    user_id: str,
    attempt_id: str,
    code: Optional[str],
    duration_seconds: Optional[int] = None,
    recalculate: bool = True,
) -> dict:
    """Grade a practical submission deterministically and recalculate analysis."""
    c = _client()
    attempt = _load_practical_attempt(c, user_id, attempt_id)
    now = datetime.now(timezone.utc)

    if str(attempt.get("status")) == "completed":
        raise HTTPException(status_code=409, detail="This practical attempt was already submitted")

    task = get_task(str(attempt.get("task_id") or ""))
    if task is None:
        raise HTTPException(status_code=409, detail="Practical task is no longer available")

    submitted = str(code or "")
    score, checks, dims = grade_practical_submission(task, submitted)
    # An empty submission records but never counts as evidence.
    validity = "low_confidence" if not submitted.strip() else "valid"

    canonical = normalize_skill(attempt.get("skill_name") or "") or str(attempt.get("skill_name") or "")
    update = {
        "status": "completed",
        "score": score,
        "validity": validity,
        "completed_at": now.isoformat(),
        "duration_seconds": int(duration_seconds) if duration_seconds is not None else None,
        "submission": submitted[:20000],
        "result_summary": {
            "per_check": [
                {k: v for k, v in d.items() if k in ("check_id", "dimension", "description", "passed")}
                for d in checks
            ],
            "dimensions": dims,
            "task_version": task.version,
        },
    }
    try:
        c.table(PRACTICAL_ATTEMPTS_TABLE).update(update).eq("id", attempt_id).eq("user_id", user_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save practical result: {str(e)[:200]}")

    result: Dict[str, Any] = {
        "attempt_id": attempt_id,
        "skill": canonical,
        "task_id": task.id,
        "task_version": task.version,
        "score": score,
        "validity": validity,
        "counts_as_evidence": validity == "valid",
        "completed_at": update["completed_at"],
        "source_reliability": PRACTICAL_RELIABILITY,
        "dimensions": dims,
        "checks": [
            {k: v for k, v in d.items() if k in ("check_id", "dimension", "description", "passed")}
            for d in checks
        ],
        "disclaimer": (
            "Prototype instrument: this result is weighted as supporting assessment "
            "evidence, not treated as a definitive measurement of proficiency."
        ),
    }

    if recalculate:
        from .service import _recalculate_analysis

        result["analysis"] = await _recalculate_analysis(user_id, canonical)
    return result


def practical_status_for_skills(user_id: str, skills: List[str]) -> Dict[str, Optional[dict]]:
    """
    Best effective practical result per requested skill (canonical names).
    Missing table / no attempts -> None per skill (never raises for storage
    issues other than a missing table, which also degrades to None so the
    layers overview keeps working before migration 019 is applied).
    """
    try:
        attempts = list_practical_attempts(user_id)
    except HTTPException:
        return {s: None for s in skills or []}
    except Exception as e:
        logger.debug("Practical status unavailable for %s: %s", user_id, e)
        return {s: None for s in skills or []}
    effective = effective_practical_attempts(attempts)
    out: Dict[str, Optional[dict]] = {}
    for s in skills or []:
        canonical = normalize_skill(s) or s
        attempt = effective.get(canonical)
        out[s] = (
            {
                "status": "completed",
                "score": float(attempt.get("score", 0.0) or 0.0),
                "attempt_id": attempt.get("id"),
                "completed_at": attempt.get("completed_at"),
                "validity": attempt.get("validity", "valid"),
            }
            if attempt
            else None
        )
    return out
