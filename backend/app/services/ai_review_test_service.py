"""EXPERIMENTAL side feature: one-call Gemini career review (isolated).

Reads RAW data INAURA already fetched (profile, evidence + provider signals,
industry requirements, roadmap) through the CURRENT services (read-only —
nothing here persists, verifies, or runs the deterministic analysis engine).
The LLM itself computes all gaps, ratings and recommendations from that raw
material in EXACTLY ONE Gemini invocation per request via LangChain
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
    roadmap_service,
)
from . import analysis_run_service as ars

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
    critical_gaps: List[GapItem] = Field(default_factory=list)
    skill_reviews: List[SkillReview] = Field(default_factory=list)
    evidence_reviews: List[str] = Field(default_factory=list)
    dsa_review: Dict[str, Any] = Field(default_factory=dict)
    github_review: Dict[str, Any] = Field(default_factory=dict)
    leetcode_review: Dict[str, Any] = Field(default_factory=dict)
    projects_review: Dict[str, Any] = Field(default_factory=dict)
    resume_review: Dict[str, Any] = Field(default_factory=dict)
    profile_review: Dict[str, Any] = Field(default_factory=dict)
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


async def build_review_context(user_id: str, target_role: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate RAW INAURA data only. Read-only: no persistence, no
    verification side effects beyond what the getters already do, and NO
    deterministic-engine math (no proficiency/confidence/gaps/readiness)."""
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
performing an EXPERIMENTAL one-shot review. You receive ONE JSON blob of RAW material INAURA
already fetched: student profile, per-evidence provider signals (skill, signal strength,
reliability, depth, reason), industry requirements for the target role, projects,
certifications, LinkedIn connection state and current roadmap.

IMPORTANT: the input contains NO precomputed scores, NO proficiency values, NO gaps and NO
readiness numbers. YOU compute every judgment yourself from the raw evidence:

Rules:
- Weigh each signal by its source_reliability and depth; a single weak or self-reported
  signal must never become a high rating. Strong claims need strong, corroborated evidence.
- Distinguish: skill_gap (evidence suggests the student lacks the skill) vs evidence_gap
  (may have it, insufficient evidence) vs coverage_gap (profile does not cover a required
  area) vs industry_data_gap (supplied industry data is too thin for a confident judgment).
  Missing data is NEVER proof of inability.
- Base industry claims ONLY on the supplied industry_requirements. Do not invent trends,
  salaries, hiring statistics, or requirements not present in the input.
- Ratings are 0-100 with reasoning. This is an AI EXPERIMENTAL rating, not an official INAURA score.
- Respond with JSON ONLY, matching this schema (all sections optional but preferred):
  {"ratings": {"overall_rating": 0-100, "industry_readiness": 0-100, "technical_strength": 0-100,
  "problem_solving": 0-100, "project_strength": 0-100, "resume_strength": 0-100,
  "profile_strength": 0-100, "evidence_strength": 0-100, "interview_readiness": 0-100,
  "reasoning": "..."}, "executive_summary": "...", "strengths": [...],
  "critical_gaps": [{"skill": "...", "severity": "...", "explanation": "...", "evidence": "...",
  "recommended_action": "..."}], "skill_reviews": [{"skill": "...", "demonstrated_level": 0-100,
  "required_level": 0-100, "verdict": "skill_gap|evidence_gap|covered|strong", "explanation": "..."}],
  "evidence_reviews": [...], "dsa_review": {...}, "github_review": {...}, "leetcode_review": {...},
  "projects_review": {...}, "resume_review": {...}, "profile_review": {...},
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
    for key in ("strengths", "evidence_reviews", "priority_actions",
                "missing_skills", "overestimated_or_weakly_supported_skills",
                "roadmap_improvements", "warnings"):
        if key in out:
            out[key] = _str_list(out[key])
    for key, item_keys in (
        ("critical_gaps", ("skill", "severity", "explanation", "evidence", "recommended_action")),
        ("skill_reviews", ("skill", "demonstrated_level", "required_level", "verdict", "explanation")),
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
                "resume_review", "profile_review", "interview_readiness"):
        if key in out and not isinstance(out[key], dict):
            out[key] = {"notes": str(out[key])}
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
    }
