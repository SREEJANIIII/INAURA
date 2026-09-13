"""EXPERIMENTAL side feature: one-call Gemini career review (isolated).

Aggregates data INAURA already has — RAW evidence plus the CURRENT
deterministic estimates (assessments, gaps, readiness), each clearly labeled
so the LLM can critique rather than copy them — through the CURRENT services
(read-only: nothing here persists, verifies, or modifies the deterministic
analysis engine, its scoring formulas, readiness math, or RAG behavior).
The LLM produces its own ratings and recommendations from that material in
EXACTLY ONE Gemini invocation per request via LangChain
``ChatGoogleGenerativeAI`` (plain generate — no function calling).

Disposable: deleting this file, ``api/v1/endpoints/ai_review_test.py`` and
the frontend page/route removes the feature without touching INAURA.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ..core.config import get_settings
from ..core.supabase import get_supabase_client
from . import (
    analysis_service,
    evidence_service,
    industry_service,
    profile_service,
    retrieval_service,
    roadmap_service,
)
from . import analysis_run_service as ars
from .signal_extractor import extract_signals as extract_skill_signals

logger = logging.getLogger(__name__)

try:  # optional: present only when LinkedIn OAuth is set up
    from . import linkedin_service
except ImportError:  # pragma: no cover
    linkedin_service = None  # type: ignore

EXPERIMENTAL_TAG = "EXPERIMENTAL — ONE LLM CALL"

# Truncation budgets keep the single prompt bounded.
MAX_PARSED_TEXT_CHARS = 3000
MAX_METADATA_STR_CHARS = 500
MAX_ITEMS = 60  # requirements / signals per evidence
MAX_PROJECTS = 30

# Keys never sent to the LLM (matched case-insensitively, substring).
_SECRET_KEY_PARTS = (
    "token", "secret", "password", "passwd", "api_key", "apikey",
    "authorization", "cookie", "session", "service_role", "private_key",
    "client_secret",
)
# PII not needed for a career review.
_DROPPED_KEYS = ("email", "profile_email")


def _is_secret_key(key: str) -> bool:
    k = str(key).lower()
    if k in _DROPPED_KEYS:
        return True
    return any(part in k for part in _SECRET_KEY_PARTS)


def _scrub(obj: Any) -> Any:
    """Recursively remove secret/PII keys from plain data structures."""
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if not _is_secret_key(k)}
    if isinstance(obj, (list, tuple)):
        return [_scrub(v) for v in obj]
    return obj


def _shorten(value: Any, limit: int = MAX_METADATA_STR_CHARS) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"...[truncated {len(value) - limit} chars]"
    if isinstance(value, list) and len(value) > 20:
        return [_shorten(v, limit) for v in value[:20]] + [f"...[{len(value) - 20} more]"]
    if isinstance(value, dict):
        return {k: _shorten(v, limit) for k, v in value.items()}
    return value


def _cap(items: List[Any], limit: int) -> tuple:
    items = items or []
    return items[:limit], len(items) > limit


# ---------------------------------------------------------------------------
# Structured response models (all fields defaulted so partial output validates)
# ---------------------------------------------------------------------------

class Ratings(BaseModel):
    overall_rating: Optional[float] = None
    industry_readiness: Optional[float] = None
    technical_strength: Optional[float] = None
    problem_solving: Optional[float] = None
    project_strength: Optional[float] = None
    resume_strength: Optional[float] = None
    profile_strength: Optional[float] = None
    evidence_strength: Optional[float] = None
    interview_readiness: Optional[float] = None
    reasoning: str = ""


class GapItem(BaseModel):
    skill: str = ""
    severity: str = ""
    explanation: str = ""
    evidence: str = ""
    recommended_action: str = ""


class SkillReview(BaseModel):
    skill: str = ""
    demonstrated_level: Optional[float] = None
    required_level: Optional[float] = None
    verdict: str = ""
    explanation: str = ""


class Recommendation(BaseModel):
    what: str = ""
    why: str = ""
    expected_impact: str = ""
    priority: str = ""
    suggested_action: str = ""


class AIReviewResponse(BaseModel):
    ratings: Ratings = Field(default_factory=Ratings)
    executive_summary: str = ""
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    critical_gaps: List[GapItem] = Field(default_factory=list)
    skill_reviews: List[SkillReview] = Field(default_factory=list)
    evidence_gaps: List[GapItem] = Field(default_factory=list)
    coverage_gaps: List[GapItem] = Field(default_factory=list)
    evidence_reviews: List[str] = Field(default_factory=list)
    dsa_review: Dict[str, Any] = Field(default_factory=dict)
    github_review: Dict[str, Any] = Field(default_factory=dict)
    leetcode_review: Dict[str, Any] = Field(default_factory=dict)
    projects_review: Dict[str, Any] = Field(default_factory=dict)
    project_review: Dict[str, Any] = Field(default_factory=dict)
    resume_review: Dict[str, Any] = Field(default_factory=dict)
    profile_review: Dict[str, Any] = Field(default_factory=dict)
    resume_profile_review: Dict[str, Any] = Field(default_factory=dict)
    industry_alignment: List[Dict[str, Any]] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    overestimated_or_weakly_supported_skills: List[str] = Field(default_factory=list)
    recommendations: List[Recommendation] = Field(default_factory=list)
    priority_actions: List[str] = Field(default_factory=list)
    interview_readiness: Dict[str, Any] = Field(default_factory=dict)
    roadmap_improvements: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Read-only RAW aggregation (reuses existing services, modifies nothing).
# No deterministic-engine outputs (no proficiency, gaps, readiness scores):
# the LLM computes all judgments itself from the raw material below.
# ---------------------------------------------------------------------------

def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except HTTPException:
        raise
    except Exception:
        return None


def _slim_verified_signals(meta: Dict[str, Any]) -> List[dict]:
    verified = meta.get("verified_signals") or []
    if not isinstance(verified, list):
        return []
    slim, _ = _cap(verified, MAX_ITEMS)
    return [
        {
            "skill": s.get("skill", s.get("canonical_name")),
            "signal_strength": s.get("signal_strength", s.get("signal_value")),
            "source_reliability": s.get("source_reliability"),
            "depth": s.get("depth"),
            "reason": s.get("reason", s.get("explanation")),
            "metadata": _shorten(s.get("metadata") or {}),
        }
        for s in slim if isinstance(s, dict)
    ]


def _evidence_summary(evidence: List[dict]) -> List[dict]:
    out = []
    for ev in evidence or []:
        meta = ev.get("metadata") or {}
        parsed = meta.get("parsed_text")
        item = {
            "id": ev.get("id"),
            "evidence_type": ev.get("evidence_type"),
            "title": ev.get("title"),
            "source_url": ev.get("source_url"),
            "verification_status": ev.get("verification_status") or meta.get("verification_status"),
            "provider": ev.get("provider") or meta.get("provider"),
            "verification_message": ev.get("verification_message") or meta.get("verification_message"),
            "verified_at": ev.get("verified_at") or meta.get("verified_at"),
            "verified_signals": _slim_verified_signals(meta),
        }
        facts = meta.get("facts")
        if facts:
            facts = facts if isinstance(facts, list) else [str(facts)]
            item["facts"] = _shorten(facts)
        warnings = meta.get("warnings")
        if warnings:
            item["warnings"] = _shorten(warnings if isinstance(warnings, list) else [str(warnings)])
        profile = meta.get("profile")
        if isinstance(profile, dict) and profile:
            item["profile"] = _shorten(profile)
        if isinstance(parsed, str) and parsed.strip():
            item["parsed_text_excerpt"] = parsed[:MAX_PARSED_TEXT_CHARS]
            item["parsed_text_truncated"] = len(parsed) > MAX_PARSED_TEXT_CHARS
            item["word_count"] = meta.get("word_count")
            sections = meta.get("sections")
            if isinstance(sections, dict):
                item["sections"] = {k: str(v)[:500] for k, v in sections.items()}
        out.append(item)
    return out


def _slim_assessment(a: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic assessment reduced to review-relevant scalars only."""
    return {
        "skill": a.get("canonical_name", a.get("skill")),
        "proficiency": a.get("proficiency"),
        "confidence": a.get("confidence"),
        "required_level": a.get("required_level"),
        "gap": a.get("gap"),
        "gap_type": a.get("gap_type"),
        "evidence_count": a.get("evidence_count"),
        "evidence_state": a.get("evidence_state"),
        "has_assessment": a.get("has_assessment"),
    }


def _slim_gap(g: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "skill": g.get("canonical_name", g.get("skill")),
        "gap": g.get("gap"),
        "gap_type": g.get("gap_type"),
        "priority_category": g.get("priority_category"),
        "required_level": g.get("required_level"),
        "current_proficiency": g.get("current_proficiency"),
        "confidence": g.get("confidence"),
    }


def _deterministic_estimates(
    evidence: List[dict],
    projects: List[dict],
    certs: List[dict],
    requirements: List[dict],
    role: str,
) -> Dict[str, Any]:
    """Run INAURA's CURRENT deterministic pipeline in-memory (read-only) and
    return its estimates LABELED AS SUCH for the LLM to critique — never to
    copy blindly. Any section that cannot be computed is omitted outright
    (missing data is never fabricated). No persistence, no scoring changes."""
    estimates: Dict[str, Any] = {}
    try:
        signals = extract_skill_signals(evidence, projects, certs)
    except Exception:
        return estimates
    try:
        req_map = ars.build_requirements_map(requirements, None)
        assessments = ars.calculate_assessments(
            ars.aggregate_skills(ars.normalize_signals(signals, None)),
            req_map,
            None,
        )
    except Exception:
        return estimates
    slim_assessments, _ = _cap([_slim_assessment(a) for a in assessments], MAX_ITEMS)
    estimates["assessments"] = slim_assessments
    try:
        gaps = ars.calculate_gaps(assessments, role)
        slim_gaps, _ = _cap([_slim_gap(g) for g in gaps], MAX_ITEMS)
        estimates["skill_gaps"] = slim_gaps
    except Exception:
        pass
    try:
        dsa_gaps, _ = _cap(ars.extract_dsa_topic_gaps(evidence, signals), 20)
        estimates["dsa_gaps"] = dsa_gaps
    except Exception:
        pass
    try:
        strengths, _ = _cap(ars.extract_strengths(assessments), 10)
        estimates["strengths"] = strengths
    except Exception:
        pass
    try:
        estimates["readiness"] = ars.calculate_readiness(assessments, requirements, gaps)
    except Exception:
        pass
    return estimates


async def _rag_industry_context(role: str) -> Any:
    """Slimmed RAG retrieval snapshot (same deterministic path as prepare).
    Returns "unavailable" on any failure instead of fabricating context."""
    try:
        retrieval = await retrieval_service.retrieve(role, None, top_k=10)
        items = []
        for it in (retrieval.get("items") or [])[:20]:
            if not isinstance(it, dict):
                continue
            items.append({
                "skill": it.get("skill"),
                "required_level": it.get("required_level"),
                "importance": it.get("importance"),
                "similarity": it.get("similarity"),
                "source": it.get("source"),
                "source_quality": it.get("source_quality"),
            })
        return {"role": retrieval.get("role"), "query": retrieval.get("query"), "items": items}
    except Exception:
        return "unavailable"


async def build_review_context(user_id: str, target_role: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate INAURA data for the one-shot review. Read-only: no
    persistence, no verification side effects beyond what the getters already
    do, and no changes to deterministic scoring — estimates are included
    LABELED so the LLM critiques them against the raw evidence."""
    try:
        profile = profile_service.get_profile(user_id)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=400, detail="Profile not found — complete /profile/setup first")
        raise
    if not profile:
        raise HTTPException(status_code=400, detail="Profile not found — complete /profile/setup first")

    role = (target_role or "").strip()
    if not role:
        state = _safe(analysis_service.get_state, user_id)
        if state and state.get("target_role"):
            role = state["target_role"]
        elif profile.get("career_interests"):
            interests = profile["career_interests"] or []
            role = interests[0] if interests else ""
    if not role:
        raise HTTPException(status_code=400, detail="No target role — select a primary career goal")

    evidence, projects, certs = ars.load_evidence(user_id)
    requirements = ars.load_industry_requirements(role)
    slim_reqs, req_truncated = _cap(requirements, MAX_ITEMS)
    slim_projects, projects_truncated = _cap(projects, MAX_PROJECTS)
    roadmap = _safe(roadmap_service.get_latest_roadmap, user_id)
    roadmap_items = _safe(roadmap_service.get_all_items_for_user, user_id) or []
    roadmap_milestones = _safe(roadmap_service.get_all_milestones_for_user, user_id) or []
    linkedin = (
        _safe(linkedin_service.get_connection_status, user_id)
        if linkedin_service is not None
        else "unavailable"
    )
    deterministic_estimates = _deterministic_estimates(evidence, projects, certs, requirements, role)
    rag_context = await _rag_industry_context(role)

    context = {
        "target_role": role,
        "profile": {
            "full_name": profile.get("full_name"),
            "college": profile.get("college"),
            "degree": profile.get("degree"),
            "branch": profile.get("branch"),
            "current_year": profile.get("current_year"),
            "graduation_year": profile.get("graduation_year"),
            "career_interests": profile.get("career_interests"),
            "hours_per_week": profile.get("hours_per_week"),
        },
        "evidence": _evidence_summary(evidence),
        "projects": slim_projects,
        "projects_truncated": projects_truncated,
        "certifications": certs,
        "linkedin": linkedin if linkedin is not None else "unavailable",
        "industry_requirements": slim_reqs,
        "industry_requirements_truncated": req_truncated,
        "rag_industry_context": rag_context,
        "deterministic_estimates": deterministic_estimates,
        "roadmap": {
            "latest": roadmap,
            "items": roadmap_items,
            "milestones": roadmap_milestones,
        } if roadmap else "unavailable",
    }
    return _scrub(context)


# ---------------------------------------------------------------------------
# Single Gemini invocation (plain generate — no function calling / AFC).
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a Senior Technical Recruiter + Engineering Hiring Manager + Career Advisor
performing an EXPERIMENTAL one-shot review. You receive ONE JSON blob INAURA already
assembled: student profile, per-evidence provider signals (skill, signal strength,
reliability, depth, reason), industry requirements for the target role, RAG retrieval
context, projects, certifications, LinkedIn connection state, current roadmap, AND a
"deterministic_estimates" section with INAURA's own computed assessments, gaps and
readiness. Treat deterministic_estimates as a second opinion to CRITIQUE against the raw
evidence -- verify each claim, call out disagreements in
"overestimated_or_weakly_supported_skills", and never copy numbers blindly.

Rules:
- Weigh each signal by its source_reliability and depth; a single weak or self-reported
  signal must never become a high rating. Strong claims need strong, corroborated evidence.
- Distinguish the four gap kinds and file each finding in its slot: skill_gap (evidence
  suggests the student lacks the skill) -> "skill_reviews"/"critical_gaps" with that
  verdict; evidence_gap (may have it, insufficient evidence) -> "evidence_gaps";
  coverage_gap (profile does not cover a required area) -> "coverage_gaps";
  industry_data_gap (supplied industry data is too thin for a confident judgment) ->
  "warnings" (and say so in the affected "industry_alignment" rows).
  Missing data is NEVER proof of inability.
- Base industry claims ONLY on the supplied industry_requirements. Do not invent trends,
  salaries, hiring statistics, or requirements not present in the input.
- Ratings are 0-100 with reasoning. This is an AI EXPERIMENTAL rating, not an official INAURA score.
- Respond with JSON ONLY, matching this schema (all sections optional but preferred):
  {"ratings": {"overall_rating": 0-100, "industry_readiness": 0-100, "technical_strength": 0-100,
  "problem_solving": 0-100, "project_strength": 0-100, "resume_strength": 0-100,
  "profile_strength": 0-100, "evidence_strength": 0-100, "interview_readiness": 0-100,
  "reasoning": "..."}, "executive_summary": "...", "strengths": [...], "weaknesses": [...],
  "critical_gaps": [{"skill": "...", "severity": "...", "explanation": "...", "evidence": "...",
  "recommended_action": "..."}], "skill_reviews": [{"skill": "...", "demonstrated_level": 0-100,
  "required_level": 0-100, "verdict": "skill_gap|evidence_gap|covered|strong", "explanation": "..."}],
  "evidence_gaps": [{"skill": "...", "severity": "...", "explanation": "...", "evidence": "...",
  "recommended_action": "..."}], "coverage_gaps": [{"skill": "...", "severity": "...",
  "explanation": "...", "evidence": "...", "recommended_action": "..."}],
  "evidence_reviews": [...], "dsa_review": {...}, "github_review": {...}, "leetcode_review": {...},
  "projects_review": {...}, "project_review": {...}, "resume_review": {...}, "profile_review": {...},
  "resume_profile_review": {...},
  "industry_alignment": [{"skill": "...", "student": "...", "industry_need": "..."}],
  "missing_skills": [...], "overestimated_or_weakly_supported_skills": [...],
  "recommendations": [{"what": "...", "why": "...", "expected_impact": "...", "priority": "...",
  "suggested_action": "..."}], "priority_actions": [...], "interview_readiness": {...},
  "roadmap_improvements": [...], "warnings": [...]}.
  Be concrete: name actual skills, projects and evidence from the input.
"""


def _build_user_prompt(context: Dict[str, Any]) -> str:
    return (
        "Analyze the student below and return the full structured review as JSON ONLY.\n\n"
        "INAURA_RAW_CONTEXT_JSON:\n" + json.dumps(context, default=str)
    )


def _make_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI

    settings = get_settings()
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="AI review is not configured — set GOOGLE_API_KEY (and optionally GEMINI_MODEL).",
        )
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model or "gemini-2.5-flash",
        google_api_key=settings.google_api_key,
        temperature=0.2,
    )


def _usage_from_message(raw: Any) -> Optional[Dict[str, Any]]:
    meta = getattr(raw, "usage_metadata", None)
    if not isinstance(meta, dict):
        return None
    return {
        "input_tokens": meta.get("input_tokens"),
        "output_tokens": meta.get("output_tokens"),
        "total_tokens": meta.get("total_tokens"),
    }


def _extract_json_object(text: str) -> Optional[str]:
    """Best-effort extraction of the first balanced {...} object (handles
    markdown fences and surrounding prose)."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if not isinstance(v, (dict, list))]
    return []


def _lenient_review_dict(data: Any) -> Dict[str, Any]:
    """Coerce common model deviations (string items, scalar sections) into the
    AIReviewResponse shape before Pydantic validation."""
    if not isinstance(data, dict):
        return {}
    out = dict(data)
    for key in ("strengths", "weaknesses", "evidence_reviews", "priority_actions",
                "missing_skills", "overestimated_or_weakly_supported_skills",
                "roadmap_improvements", "warnings"):
        if key in out:
            out[key] = _str_list(out[key])
    for key, item_keys in (
        ("critical_gaps", ("skill", "severity", "explanation", "evidence", "recommended_action")),
        ("skill_reviews", ("skill", "demonstrated_level", "required_level", "verdict", "explanation")),
        ("evidence_gaps", ("skill", "severity", "explanation", "evidence", "recommended_action")),
        ("coverage_gaps", ("skill", "severity", "explanation", "evidence", "recommended_action")),
        ("recommendations", ("what", "why", "expected_impact", "priority", "suggested_action")),
    ):
        items = out.get(key)
        if isinstance(items, str):
            items = [items]
        coerced = []
        if isinstance(items, (list, tuple)):
            for it in items:
                if isinstance(it, str):
                    coerced.append({item_keys[0]: it[:120], "explanation" if "explanation" in item_keys else "what": it})
                elif isinstance(it, dict):
                    coerced.append(it)
        out[key] = coerced
    for key in ("dsa_review", "github_review", "leetcode_review", "projects_review",
                "project_review", "resume_review", "profile_review",
                "resume_profile_review", "interview_readiness"):
        if key in out and not isinstance(out[key], dict):
            out[key] = {"notes": str(out[key])}
    # Compat aliases: "project_review" mirrors "projects_review" and
    # "resume_profile_review" merges resume/profile reviews when the model
    # uses only one naming. Never invents content.
    if not out.get("project_review") and isinstance(out.get("projects_review"), dict):
        out["project_review"] = out["projects_review"]
    if not out.get("resume_profile_review"):
        merged: Dict[str, Any] = {}
        for key in ("resume_review", "profile_review"):
            section = out.get(key)
            if isinstance(section, dict):
                merged[key] = section
        if merged:
            out["resume_profile_review"] = merged
    if "industry_alignment" in out and not isinstance(out["industry_alignment"], list):
        out["industry_alignment"] = []
    ratings = out.get("ratings")
    if ratings is not None and not isinstance(ratings, dict):
        out["ratings"] = {}
    return out


def _review_from_json_text(content: Any) -> AIReviewResponse:
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    candidate = _extract_json_object(text)
    if not candidate:
        logger.warning("ai-review-test: no JSON object in model reply (first 500 chars: %r)", text[:500])
        raise HTTPException(status_code=502, detail="AI review returned an unparseable response.")
    try:
        data = json.loads(candidate)
    except Exception:
        logger.warning("ai-review-test: JSON decode failed (first 500 chars: %r)", candidate[:500])
        raise HTTPException(status_code=502, detail="AI review returned an unparseable response.")
    try:
        return AIReviewResponse.model_validate(_lenient_review_dict(data))
    except Exception as e:
        logger.warning("ai-review-test: schema validation failed: %s | reply excerpt: %r",
                       str(e)[:500], candidate[:1000])
        raise HTTPException(
            status_code=502,
            detail="AI review returned invalid structured output — please re-run the review.",
        )


# ---------------------------------------------------------------------------
# Phase 9 (experimental): deterministic INAURA-vs-Gemini comparison.
#
# Compares the deterministic estimates already in the context against the
# parsed Gemini review using fixed, documented rules below. The comparison
# NEVER overwrites deterministic values, NEVER treats Gemini as ground truth
# (disagreements are reported, not resolved), and performs no LLM calls.
# Pure function of (deterministic_estimates, review_dict): no I/O, no
# persistence, no scoring changes.
# ---------------------------------------------------------------------------

COMPARISON_VERSION = "comparison-v1"

# Percentage-point tolerance for "same magnitude" on 0-100 proficiency scales.
AGREEMENT_MAGNITUDE_TOLERANCE = 15.0

# A Gemini demonstrated_level at/above this (0-1 scale) counts as a strong
# claim about a skill, which then requires INAURA evidence to be supported.
STRONG_CLAIM_THRESHOLD = 0.50

_GEMINI_COVERED_VERDICTS = frozenset({"covered", "strong"})
_GEMINI_GAP_VERDICTS = frozenset({"skill_gap", "evidence_gap", "coverage_gap"})


def _comparison_skill_key(name: Any) -> str:
    """Canonical match key: taxonomy first, case-insensitive fallback."""
    text = str(name or "").strip()
    if not text:
        return ""
    try:
        from .skill_taxonomy import normalize_skill

        canonical = normalize_skill(text)
        if canonical:
            return canonical.lower()
    except Exception:
        pass
    return text.lower()


def _gemini_level_fraction(value: Any) -> Optional[float]:
    """Normalize a Gemini demonstrated_level to 0-1 (accepts 0-100 or 0-1)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    if number > 1:
        number = number / 100.0
    return max(0.0, min(1.0, number))


def _deterministic_direction(assessment: Dict[str, Any]) -> str:
    """covered when the engine reports no gap, gap otherwise."""
    try:
        gap = float(assessment.get("gap", 0.0) or 0.0)
    except (TypeError, ValueError):
        gap = 0.0
    return "covered" if gap <= 1e-9 else "gap"


def _gemini_direction(verdict: Any) -> str:
    """covered / gap / unknown direction of one Gemini skill verdict."""
    normalized = str(verdict or "").strip().lower()
    if normalized in _GEMINI_COVERED_VERDICTS:
        return "covered"
    if normalized in _GEMINI_GAP_VERDICTS:
        return "gap"
    return "unknown"


def build_comparison(
    deterministic_estimates: Any,
    review: Any,
) -> Dict[str, Any]:
    """Compare INAURA deterministic estimates vs the parsed Gemini review.

    Returns {"version", "rows", "agreements", "differences", "ai_only_insights",
    "engine_only_insights", "warnings", "note"}. Rows cover the union of
    deterministic skills and Gemini-reviewed skills with per-side cells plus
    a category of agreement | partial_agreement | disagreement |
    gemini_only | engine_only. Inputs are only read, never mutated.
    """
    estimates = deterministic_estimates if isinstance(deterministic_estimates, dict) else {}
    review_dict = review if isinstance(review, dict) else {}

    det_assessments = [
        a for a in (estimates.get("assessments") or []) if isinstance(a, dict)
    ]
    gem_reviews = [
        r for r in (review_dict.get("skill_reviews") or []) if isinstance(r, dict)
    ]

    det_by_key: Dict[str, Dict[str, Any]] = {}
    for assessment in det_assessments:
        key = _comparison_skill_key(assessment.get("skill"))
        if key and key not in det_by_key:
            det_by_key[key] = assessment
    gem_by_key: Dict[str, Dict[str, Any]] = {}
    for item in gem_reviews:
        key = _comparison_skill_key(item.get("skill"))
        if key and key not in gem_by_key:
            gem_by_key[key] = item

    det_names = {key: str(det_by_key[key].get("skill") or key) for key in det_by_key}

    rows: List[Dict[str, Any]] = []
    for key in sorted(set(det_by_key) | set(gem_by_key)):
        det = det_by_key.get(key)
        gem = gem_by_key.get(key)
        display = det_names.get(key) or str((gem or {}).get("skill") or key)
        if det is None and gem is not None:
            gem_level = _gemini_level_fraction(gem.get("demonstrated_level"))
            rows.append({
                "skill": display,
                "deterministic": None,
                "gemini": {
                    "level_pct": None if gem_level is None else round(gem_level * 100, 1),
                    "verdict": str(gem.get("verdict") or ""),
                },
                "category": "gemini_only",
                "detail": "Reviewed by Gemini; INAURA has no record of this skill.",
            })
            continue
        assert det is not None
        try:
            det_prof = float(det.get("proficiency", 0.0) or 0.0)
        except (TypeError, ValueError):
            det_prof = 0.0
        det_pct = round(max(0.0, min(1.0, det_prof)) * 100, 1)
        try:
            det_evidence = int(det.get("evidence_count", 0) or 0)
        except (TypeError, ValueError):
            det_evidence = 0
        det_dir = _deterministic_direction(det)
        det_cell: Dict[str, Any] = {
            "level_pct": det_pct,
            "direction": det_dir,
            "evidence_count": det_evidence,
            "evidence_state": str(det.get("evidence_state") or ""),
        }
        if gem is None:
            rows.append({
                "skill": display,
                "deterministic": det_cell,
                "gemini": None,
                "category": "engine_only",
                "detail": "In INAURA estimates but not reviewed by Gemini.",
            })
            continue
        gem_level = _gemini_level_fraction(gem.get("demonstrated_level"))
        gem_verdict = str(gem.get("verdict") or "")
        gem_dir = _gemini_direction(gem_verdict)
        gem_cell: Dict[str, Any] = {
            "level_pct": None if gem_level is None else round(gem_level * 100, 1),
            "verdict": gem_verdict,
            "direction": gem_dir,
        }
        if gem_dir == "unknown":
            category, detail = (
                "partial_agreement",
                "Gemini reviewed this skill without a clear verdict.",
            )
        elif det_dir == "covered" and gem_dir == "covered":
            if gem_level is None:
                category, detail = "agreement", "Both report this skill as covered."
            elif abs(det_pct - gem_level * 100) <= AGREEMENT_MAGNITUDE_TOLERANCE:
                category, detail = "agreement", "Both report this skill as covered at a similar level."
            else:
                category, detail = (
                    "partial_agreement",
                    "Both report this skill as covered but at different levels.",
                )
        elif det_dir == "gap" and gem_dir == "gap":
            if gem_verdict.strip().lower() == "skill_gap":
                category, detail = "agreement", "Both flag a gap for this skill."
            else:
                category, detail = (
                    "partial_agreement",
                    "Both flag this skill, but Gemini reports a weaker gap kind "
                    f"({gem_verdict or 'unspecified'}) than INAURA's measured gap.",
                )
        else:
            category, detail = (
                "disagreement",
                f"INAURA reports '{det_dir}' while Gemini reports '{gem_dir}' "
                f"(verdict: {gem_verdict or 'unspecified'}). Neither side overwrites the other.",
            )
        rows.append({
            "skill": display,
            "deterministic": det_cell,
            "gemini": gem_cell,
            "category": category,
            "detail": detail,
        })

    agreements = sorted(r["skill"] for r in rows if r["category"] == "agreement")
    differences = [
        {
            "skill": r["skill"],
            "category": r["category"],
            "deterministic": r["deterministic"],
            "gemini": r["gemini"],
            "detail": r["detail"],
        }
        for r in rows if r["category"] in ("partial_agreement", "disagreement")
    ]

    # AI-only insights: Gemini recommendations/strengths naming no skill known
    # to INAURA (deterministic universe). Process advice with no skill anchor
    # is novel by construction.
    universe = set(det_by_key)
    ai_only_insights: List[Dict[str, Any]] = []
    for kind, texts in (
        ("recommendation", [
            f"{r.get('what', '')} {r.get('why', '')} {r.get('suggested_action', '')}"
            for r in (review_dict.get("recommendations") or []) if isinstance(r, dict)
        ]),
        ("strength", [
            str(s) for s in (review_dict.get("strengths") or []) if isinstance(s, str)
        ]),
    ):
        for text in texts:
            if not str(text or "").strip():
                continue
            lowered = f" {str(text).lower()} "
            if any(key and key in lowered for key in universe if key):
                continue
            ai_only_insights.append({"kind": kind, "text": str(text)[:300]})
    ai_only_insights = ai_only_insights[:20]

    # Engine-only insights: deterministic gaps and strengths Gemini never reviewed.
    gemini_mentioned = set(gem_by_key) | {
        key for key in universe
        if any(key and key in f" {str(t or '').lower()} "
               for t in ([str(s) for s in (review_dict.get("strengths") or []) if isinstance(s, str)]))
    }
    engine_only_insights: List[Dict[str, Any]] = []
    for assessment in det_assessments:
        key = _comparison_skill_key(assessment.get("skill"))
        if not key or key in gemini_mentioned:
            continue
        try:
            gap = float(assessment.get("gap", 0.0) or 0.0)
        except (TypeError, ValueError):
            gap = 0.0
        if gap > 1e-9:
            try:
                prof = float(assessment.get("proficiency", 0.0) or 0.0)
            except (TypeError, ValueError):
                prof = 0.0
            engine_only_insights.append({
                "skill": str(assessment.get("skill") or key),
                "proficiency_pct": round(max(0.0, min(1.0, prof)) * 100, 1),
                "gap_pct": round(max(0.0, min(1.0, gap)) * 100, 1),
                "reason": "INAURA-measured gap that Gemini did not review.",
            })
    for strength in (estimates.get("strengths") or []):
        if not isinstance(strength, dict):
            continue
        key = _comparison_skill_key(strength.get("skill") or strength.get("display_name"))
        if not key or key in gemini_mentioned:
            continue
        engine_only_insights.append({
            "skill": str(strength.get("display_name") or strength.get("skill") or key),
            "reason": "INAURA-validated strength that Gemini did not mention.",
        })
    engine_only_insights = engine_only_insights[:20]

    # Unsupported-claim warnings: strong Gemini claims with no INAURA evidence.
    # Never presented as proof Gemini is wrong -- only that INAURA cannot
    # corroborate the claim from submitted evidence.
    warnings: List[Dict[str, Any]] = []
    for key, gem in gem_by_key.items():
        gem_level = _gemini_level_fraction(gem.get("demonstrated_level"))
        if gem_level is None or gem_level < STRONG_CLAIM_THRESHOLD:
            continue
        det = det_by_key.get(key)
        try:
            det_evidence = int((det or {}).get("evidence_count", 0) or 0)
        except (TypeError, ValueError):
            det_evidence = 0
        if det is None or det_evidence <= 0:
            warnings.append({
                "type": "unsupported_ai_claim",
                "skill": str(gem.get("skill") or key),
                "detail": (
                    f"Gemini rates this skill at {round(gem_level * 100, 1)}% but "
                    f"INAURA holds no supporting evidence for it. Treat as unverified."
                ),
            })
    for text in [
        str(s) for s in (review_dict.get("strengths") or []) if isinstance(s, str)
    ][:20]:
        lowered = f" {text.lower()} "
        named = [key for key in det_by_key if key and key in lowered]
        if not named:
            continue
        if all(int(det_by_key[k].get("evidence_count", 0) or 0) <= 0 for k in named):
            warnings.append({
                "type": "unsupported_ai_claim",
                "skill": ", ".join(str(det_by_key[k].get("skill") or k) for k in named),
                "detail": f"Gemini lists this as a strength ({text[:120]}), but INAURA holds no supporting evidence for it.",
            })
    for text in [
        f"{r.get('what', '')} {r.get('why', '')}" if isinstance(r, dict) else ""
        for r in (review_dict.get("recommendations") or [])
    ][:20]:
        lowered = f" {str(text).lower()} "
        named = [key for key in det_by_key if key and key in lowered]
        if not named:
            continue
        if all(int(det_by_key[k].get("evidence_count", 0) or 0) <= 0 for k in named):
            warnings.append({
                "type": "unsupported_ai_recommendation",
                "skill": ", ".join(str(det_by_key[k].get("skill") or k) for k in named),
                "detail": f"Gemini recommends work predicated on this skill ({str(text)[:120]}), but INAURA holds no supporting evidence for it.",
            })
    warnings = warnings[:20]

    note_parts = [f"{len(rows)} skill(s) compared"]
    if not gem_by_key:
        note_parts.append("Gemini returned no skill reviews")
    if not det_by_key:
        note_parts.append("no deterministic assessments available")
    note_parts.append("deterministic values preserved; Gemini is never ground truth")
    return {
        "version": COMPARISON_VERSION,
        "rows": rows,
        "agreements": agreements,
        "differences": differences,
        "ai_only_insights": ai_only_insights,
        "engine_only_insights": engine_only_insights,
        "warnings": warnings,
        "note": "; ".join(note_parts) + ".",
    }


async def run_ai_review(
    user_id: str,
    target_role: Optional[str] = None,
    _llm: Any = None,
) -> Dict[str, Any]:
    """Aggregate RAW context, invoke Gemini EXACTLY ONCE (plain generate, no
    function calling), return validated review + metadata."""
    context = await build_review_context(user_id, target_role)
    settings = get_settings()
    model_name = settings.gemini_model or "gemini-2.5-flash"
    prompt = _build_user_prompt(context)

    llm = _llm if _llm is not None else _make_llm()
    started = time.perf_counter()
    try:
        raw = await llm.ainvoke(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI review failed: {str(e)[:200]}")
    latency_ms = int((time.perf_counter() - started) * 1000)

    review = _review_from_json_text(getattr(raw, "content", raw))
    usage = _usage_from_message(raw)

    data_sources = sorted({
        str((ev or {}).get("evidence_type") or "unknown") for ev in context.get("evidence", [])
        if isinstance(ev, dict)
    })
    # Phase 9 (experimental): deterministic comparison. Computed locally from
    # the already-aggregated context plus the parsed review -- no extra LLM
    # call, no persistence, and deterministic values are never overwritten.
    try:
        comparison = build_comparison(
            context.get("deterministic_estimates") or {},
            review.model_dump(),
        )
    except Exception:
        comparison = build_comparison({}, {})
    return {
        "review": review.model_dump(),
        "meta": {
            "experimental": EXPERIMENTAL_TAG,
            "model": model_name,
            "llm_calls": 1,
            "latency_ms": latency_ms,
            "usage": usage,
            "data_sources": data_sources,
            "target_role": context.get("target_role"),
        },
        "comparison": comparison,
    }
