"""
AI skill interview — Layer 3 of skill assessment.

A structured, SKILL-SPECIFIC interview, not free chat:

  * one session validates exactly one skill
  * questions are generated deterministically from an evidence-adaptive plan
    anchored to defined per-skill competencies (the model never decides what
    "good" means — the rubric does)
  * the plan adapts to what INAURA already knows: weak layers get focus,
    strong layers get deeper scenario questions, related projects are
    referenced so the user can explain their own implementation
  * grading separates TECHNICAL evaluation from COMMUNICATION evaluation;
    communication is stored on the session only and never merged into the
    skill signal
  * the interview is one more evidence source: it can add a signal
    ("implementation understanding validated / not fully validated") but it
    never accuses, never deletes, and never rewrites existing evidence

LLM usage: question plans are deterministic templates (no LLM needed, fully
testable). Grading free-text responses needs a model: exactly ONE Gemini call
per completed interview via the existing provider pattern. When no API key is
configured the transcript is still stored and the session waits as
``awaiting_review`` — no signal is emitted and nothing breaks.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import json
import logging
import re
import uuid

from fastapi import HTTPException

from ...core.supabase import get_supabase_client
from ..evidence_weights import ASSESSMENT_SOURCE, reliability
from ..signal_extractor import make_signal
from ..skill_taxonomy import normalize_skill, normalize_skill_slug
from .layers import INTERVIEW

logger = logging.getLogger(__name__)

INTERVIEW_SESSIONS_TABLE = "assessment_interview_sessions"
INTERVIEW_VERSION = "interview-v1"

INTERVIEW_RELIABILITY = reliability(ASSESSMENT_SOURCE)

# One interview asks this many main questions (each with follow-ups).
INTERVIEW_QUESTION_COUNT = 4
# Displayed estimate; the interview is self-paced within the TTL.
INTERVIEW_ESTIMATED_MINUTES = 10
INTERVIEW_TTL_MINUTES = 120


# ---------------------------------------------------------------------------
# Competencies: the fixed rubric. The model grades against these, never
# invents its own criteria.
# ---------------------------------------------------------------------------

GENERIC_COMPETENCIES: List[Dict[str, str]] = [
    {"id": "fundamentals", "label": "Skill fundamentals"},
    {"id": "application", "label": "Practical application"},
    {"id": "reasoning", "label": "Trade-offs and reasoning"},
    {"id": "debugging", "label": "Debugging and problem-solving"},
    {"id": "explanation", "label": "Clear technical explanation"},
]

INTERVIEW_COMPETENCIES: Dict[str, List[Dict[str, str]]] = {
    "dsa": [
        {"id": "algorithm_selection", "label": "Algorithm selection"},
        {"id": "complexity_reasoning", "label": "Complexity reasoning"},
        {"id": "edge_cases", "label": "Edge cases"},
        {"id": "decomposition", "label": "Problem decomposition"},
        {"id": "explanation", "label": "Clear technical explanation"},
    ],
    "python": [
        {"id": "implementation_reasoning", "label": "Implementation reasoning"},
        {"id": "python_specifics", "label": "Python-specific understanding"},
        {"id": "debugging", "label": "Debugging"},
        {"id": "design_decisions", "label": "Design decisions"},
        {"id": "explanation", "label": "Clear technical explanation"},
    ],
    "sql": [
        {"id": "query_reasoning", "label": "Query reasoning"},
        {"id": "relational_understanding", "label": "Relational understanding"},
        {"id": "correctness", "label": "Correctness"},
        {"id": "optimization", "label": "Optimization reasoning"},
        {"id": "explanation", "label": "Clear technical explanation"},
    ],
    "react": [
        {"id": "component_reasoning", "label": "Component reasoning"},
        {"id": "state_data_flow", "label": "State and data flow"},
        {"id": "debugging", "label": "Debugging"},
        {"id": "api_interaction", "label": "API interaction"},
        {"id": "explanation", "label": "Clear technical explanation"},
    ],
    "java": [
        {"id": "implementation_reasoning", "label": "Implementation reasoning"},
        {"id": "oop_design", "label": "Object-oriented design"},
        {"id": "debugging", "label": "Debugging"},
        {"id": "api_design", "label": "API and library use"},
        {"id": "explanation", "label": "Clear technical explanation"},
    ],
    "javascript": [
        {"id": "implementation_reasoning", "label": "Implementation reasoning"},
        {"id": "async_reasoning", "label": "Asynchronous reasoning"},
        {"id": "debugging", "label": "Debugging"},
        {"id": "design_decisions", "label": "Design decisions"},
        {"id": "explanation", "label": "Clear technical explanation"},
    ],
}

COMMUNICATION_DIMENSIONS: List[Dict[str, str]] = [
    {"id": "clarity", "label": "Clarity"},
    {"id": "relevance", "label": "Relevance"},
    {"id": "structure", "label": "Logical structure"},
    {"id": "justification", "label": "Justifying decisions"},
    {"id": "follow_ups", "label": "Responding to follow-ups"},
]


def competencies_for_skill(skill: str) -> List[Dict[str, str]]:
    """Defined rubric for one skill (generic fallback for other skills)."""
    slug = normalize_skill_slug(skill or "") or ""
    return list(INTERVIEW_COMPETENCIES.get(slug, GENERIC_COMPETENCIES))


def _band(score: Optional[float]) -> str:
    if score is None:
        return "unknown"
    if score >= 0.75:
        return "strong"
    if score >= 0.5:
        return "moderate"
    return "weak"


def _mention(text: str, skill: str) -> bool:
    """Deterministic skill-mention check for project awareness."""
    hay = str(text or "").lower()
    needle = str(skill or "").lower().strip()
    if not needle:
        return False
    return needle in hay


def build_interview_plan(
    skill: str,
    evidence_summary: Optional[Dict[str, Any]] = None,
    knowledge_score: Optional[float] = None,
    practical_score: Optional[float] = None,
    projects: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Build an evidence-adaptive, competency-anchored interview plan (pure).

    Personalization rules (deterministic):
      * related projects (skill mentioned in name/description/technologies)
        seed a project-aware opener about the user's own implementation
      * the weakest completed layer becomes a focus area; a fully strong
        profile gets deeper scenario/trade-off questions instead of basics
      * every question carries its competency id so grading stays anchored
    """
    canonical = normalize_skill(skill or "") or (skill or "").strip()
    competencies = competencies_for_skill(canonical)

    related: List[str] = []
    for p in projects or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        blob = " ".join([
            name,
            str(p.get("description") or ""),
            " ".join(str(t) for t in (p.get("technologies") or []) if t),
        ])
        if name and _mention(blob, canonical):
            related.append(name)
    related = related[:3]

    k_band = _band(knowledge_score)
    p_band = _band(practical_score)
    focus: List[str] = []
    if k_band == "weak":
        focus.append("fundamentals")
    if p_band == "weak":
        focus.append("practical_reasoning")
    if not focus and (k_band == "unknown" or p_band == "unknown"):
        focus.append("applied_understanding")
    deep_mode = k_band == "strong" and p_band == "strong"

    questions: List[Dict[str, Any]] = []
    comp_ids = [c["id"] for c in competencies]

    def _q(qid: str, competency: str, prompt: str, follow_ups: List[str]) -> Dict[str, Any]:
        return {"id": qid, "competency": competency, "prompt": prompt, "follow_ups": follow_ups}

    # Q1 — project-aware opener when possible, else implementation walkthrough.
    if related:
        questions.append(_q(
            "q1", comp_ids[0],
            f"You have used {canonical} in {related[0]}. Walk me through one implementation "
            "there that you are most comfortable explaining — what did it do and how did you build it?",
            [
                "Why did you choose that approach over the main alternative?",
                "What would happen if the input or load grew tenfold?",
            ],
        ))
    else:
        questions.append(_q(
            "q1", comp_ids[0],
            f"Walk me through a recent implementation where you used {canonical}. What did you "
            "build, and what were the key decisions?",
            [
                "Why did you choose that approach over the main alternative?",
                "What was the trickiest part to get right?",
            ],
        ))

    # Q2 — adapts to the weakest signal.
    if "fundamentals" in focus:
        questions.append(_q(
            "q2", comp_ids[0],
            f"Let's cover fundamentals: what are the core concepts in {canonical} that you rely on "
            "most, and how do they fit together?",
            [f"Can you give a concrete example of one of those concepts in {canonical}?"],
        ))
    elif "practical_reasoning" in focus:
        questions.append(_q(
            "q2", comp_ids[1] if len(comp_ids) > 1 else comp_ids[0],
            f"Talk through how you would approach a new practical task in {canonical} from scratch. "
            "How do you break it down and validate each step?",
            ["How would you handle an edge case you did not anticipate?"],
        ))
    elif deep_mode:
        questions.append(_q(
            "q2", comp_ids[2] if len(comp_ids) > 2 else comp_ids[0],
            f"Your evidence and assessment results for {canonical} are strong, so let's go deeper: "
            "describe a trade-off you faced (performance, readability, cost, or complexity) and how "
            "you decided.",
            ["What would make you reverse that decision?"],
        ))
    else:
        questions.append(_q(
            "q2", comp_ids[1] if len(comp_ids) > 1 else comp_ids[0],
            f"Describe a time something in {canonical} did not work as expected. How did you "
            "diagnose and fix it?",
            ["How did you verify the fix actually solved the root cause?"],
        ))

    # Q3 — scenario / architecture reasoning.
    questions.append(_q(
        "q3", comp_ids[2] if len(comp_ids) > 2 else comp_ids[0],
        f"Suppose you had to design a small but production-quality solution using {canonical} "
        "for a teammate to maintain. How would you structure it, and why?",
        ["What would you do differently if the requirements doubled in scope?"],
    ))

    # Q4 — explanation check + second project reference when available.
    if len(related) > 1:
        questions.append(_q(
            "q4", comp_ids[-1],
            f"You also used {canonical} in {related[1]}. Explain that implementation as if to a "
            "junior teammate — what should they understand first?",
            ["What is the most common misunderstanding people have about this?"],
        ))
    else:
        questions.append(_q(
            "q4", comp_ids[-1],
            f"What is one thing about {canonical} you understand better now than when you started, "
            "and what taught you that?",
            ["How would you teach that insight to someone new?"],
        ))

    return {
        "skill": canonical,
        "version": INTERVIEW_VERSION,
        "competencies": competencies,
        "focus_areas": focus or (["deep_reasoning"] if deep_mode else ["applied_understanding"]),
        "deep_mode": deep_mode,
        "related_projects": related,
        "estimated_minutes": INTERVIEW_ESTIMATED_MINUTES,
        "questions": questions[:INTERVIEW_QUESTION_COUNT],
    }


def validate_plan(plan: Dict[str, Any]) -> List[str]:
    """Structural self-check of an interview plan. Returns problems (empty = OK)."""
    problems: List[str] = []
    if not plan.get("skill"):
        problems.append("plan has no skill")
    comp_ids = {c.get("id") for c in (plan.get("competencies") or []) if isinstance(c, dict)}
    if not comp_ids:
        problems.append("plan has no competencies")
    questions = plan.get("questions") or []
    if not questions:
        problems.append("plan has no questions")
    for q in questions:
        if not isinstance(q, dict):
            problems.append("question is not an object")
            continue
        if not str(q.get("prompt") or "").strip():
            problems.append(f"{q.get('id', '?')}: missing prompt")
        if q.get("competency") not in comp_ids:
            problems.append(f"{q.get('id', '?')}: competency '{q.get('competency')}' is not defined")
    return problems


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

def _client():
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    return c


def _table_missing(err: Exception) -> bool:
    m = str(err).lower()
    return "could not find the table" in m or "pgrst205" in m or "does not exist" in m


def _related_projects(user_id: str, canonical: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Best-effort project context for one skill. Never raises."""
    try:
        c = get_supabase_client()
        if c is None:
            return []
        r = c.table("projects").select("name,description,technologies").eq("user_id", user_id).limit(50).execute()
        out: List[Dict[str, Any]] = []
        for row in r.data or []:
            blob = " ".join([
                str(row.get("name") or ""),
                str(row.get("description") or ""),
                " ".join(str(t) for t in (row.get("technologies") or []) if t),
            ])
            if _mention(blob, canonical):
                out.append({
                    "name": row.get("name"),
                    "description": row.get("description"),
                    "technologies": row.get("technologies") or [],
                })
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        logger.debug("Project context unavailable for %s: %s", user_id, e)
        return []


def _effective_score(table: str, user_id: str, canonical: str, attempts_considered: int = 3) -> Optional[float]:
    """Best of the most recent valid, completed attempts in a layer table."""
    try:
        c = get_supabase_client()
        if c is None:
            return None
        r = (
            c.table(table).select("score,validity,status,completed_at,created_at")
            .eq("user_id", user_id).eq("skill_name", canonical)
            .order("created_at", desc=True).limit(50).execute()
        )
        rows = [
            row for row in (r.data or [])
            if str(row.get("status") or "") == "completed"
            and str(row.get("validity") or "valid") == "valid"
        ]
        if not rows:
            return None
        window = rows[:attempts_considered]
        return max(float(row.get("score", 0.0) or 0.0) for row in window)
    except Exception as e:
        logger.debug("Layer score unavailable (%s) for %s: %s", table, user_id, e)
        return None


def _skill_id_for(c, canonical: str) -> Optional[str]:
    try:
        slug = normalize_skill_slug(canonical) or canonical.lower()
        r = c.table("skills").select("id, canonical_name").eq("canonical_name", slug).limit(1).execute()
        if r.data:
            return r.data[0]["id"]
    except Exception:
        pass
    return None


def start_interview_session(user_id: str, skill: str) -> dict:
    """Create an interview session with its deterministic, evidence-adaptive plan."""
    canonical = normalize_skill(skill) or ""
    if not canonical:
        raise HTTPException(status_code=400, detail=f"Unknown skill '{skill}'")

    knowledge_score = _effective_score("assessment_attempts", user_id, canonical)
    practical_score = _effective_score("assessment_practical_attempts", user_id, canonical)
    projects = _related_projects(user_id, canonical)

    plan = build_interview_plan(
        canonical,
        knowledge_score=knowledge_score,
        practical_score=practical_score,
        projects=[{"name": p.get("name"), "description": p.get("description"), "technologies": p.get("technologies")} for p in projects],
    )
    problems = validate_plan(plan)
    if problems:
        raise HTTPException(status_code=500, detail=f"Interview plan failed validation: {problems[0]}")

    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    c = _client()
    row = {
        "id": session_id,
        "user_id": user_id,
        "skill_id": _skill_id_for(c, canonical),
        "skill_key": normalize_skill_slug(canonical) or canonical.lower(),
        "skill_name": canonical,
        "interview_version": INTERVIEW_VERSION,
        "status": "in_progress",
        "plan": plan,
        "transcript": [],
        "started_at": now.isoformat(),
    }
    try:
        c.table(INTERVIEW_SESSIONS_TABLE).insert(row).execute()
    except Exception as e:
        if _table_missing(e):
            raise HTTPException(
                status_code=503,
                detail="Interview tables not found — run backend/supabase/019_assessment_layers.sql",
            )
        raise HTTPException(status_code=500, detail=f"Failed to start interview: {str(e)[:200]}")

    return {
        "session_id": session_id,
        "skill": canonical,
        "skill_key": row["skill_key"],
        "interview_version": INTERVIEW_VERSION,
        "status": "in_progress",
        "started_at": row["started_at"],
        "plan": plan,
        "evaluated_dimensions": {
            "technical": [c_["label"] for c_ in plan["competencies"]],
            "communication": [d["label"] for d in COMMUNICATION_DIMENSIONS],
        },
        "privacy_notice": (
            "Camera and microphone stay on this device for presence checks. INAURA does not "
            "store video or audio from this interview — only your written answers are saved."
        ),
        "disclaimer": (
            "Structured skill interview: your answers are evaluated against a fixed rubric "
            "as supporting assessment evidence, never as a verdict on your ability."
        ),
    }


def _load_session(c, user_id: str, session_id: str) -> dict:
    try:
        r = (
            c.table(INTERVIEW_SESSIONS_TABLE).select("*")
            .eq("user_id", user_id).eq("id", session_id).limit(1).execute()
        )
    except Exception as e:
        if _table_missing(e):
            raise HTTPException(
                status_code=503,
                detail="Interview tables not found — run backend/supabase/019_assessment_layers.sql",
            )
        raise HTTPException(status_code=500, detail="Failed to load interview session")
    if not r.data:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return r.data[0]


def get_interview_session(user_id: str, session_id: str) -> dict:
    """Public session view (plan + transcript, never the rubric scores early)."""
    c = _client()
    s = _load_session(c, user_id, session_id)
    return {
        "session_id": s.get("id"),
        "skill": s.get("skill_name"),
        "status": s.get("status"),
        "plan": s.get("plan") or {},
        "transcript": s.get("transcript") or [],
        "technical_scores": s.get("technical_scores"),
        "communication_scores": s.get("communication_scores"),
        "started_at": s.get("started_at"),
        "completed_at": s.get("completed_at"),
    }


def submit_interview_responses(
    user_id: str, session_id: str, responses: Dict[str, str]
) -> dict:
    """Save written answers onto an in-progress session (transcript only)."""
    c = _client()
    s = _load_session(c, user_id, session_id)
    if str(s.get("status")) not in ("in_progress",):
        raise HTTPException(status_code=409, detail="This interview session is already completed")

    plan = s.get("plan") or {}
    valid_ids = {q.get("id") for q in (plan.get("questions") or []) if isinstance(q, dict)}
    transcript = []
    for q in (plan.get("questions") or []):
        if not isinstance(q, dict):
            continue
        qid = q.get("id")
        if qid not in valid_ids:
            continue
        answer = str((responses or {}).get(qid) or "")
        transcript.append({
            "question_id": qid,
            "competency": q.get("competency"),
            "prompt": q.get("prompt"),
            "answer": answer[:8000],
            "answered": bool(answer.strip()),
        })
    try:
        c.table(INTERVIEW_SESSIONS_TABLE).update({"transcript": transcript}).eq("id", session_id).eq("user_id", user_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save interview answers: {str(e)[:200]}")
    return {"session_id": session_id, "skill": s.get("skill_name"), "answered": sum(1 for t in transcript if t["answered"]), "total": len(transcript)}


# ---------------------------------------------------------------------------
# Grading: exactly ONE Gemini call; strict schema validation; technical and
# communication kept separate.
# ---------------------------------------------------------------------------

def _make_interview_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI
    from ...core.config import get_settings

    settings = get_settings()
    if not settings.google_api_key:
        raise HTTPException(
            status_code=503,
            detail="AI interview grading is not configured — set GOOGLE_API_KEY (and optionally GEMINI_MODEL). "
                   "Your answers are saved and will be graded once grading is configured.",
        )
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model or "gemini-2.5-flash",
        google_api_key=settings.google_api_key,
        temperature=0.2,
    )


def _extract_json_object(text: str) -> Optional[str]:
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


def _clamp01(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return max(0.0, min(1.0, round(f, 4)))


def grade_interview_transcript(
    skill: str,
    competencies: List[Dict[str, str]],
    transcript: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Grade one interview transcript with a single model call.

    Returns {"technical": {...}, "communication": {...}} with every value in
    [0, 1]. Raises HTTPException when grading is unavailable or the model
    output fails validation.
    """
    llm = _make_interview_llm()
    comp_list = "\n".join(f"- {c['id']}: {c['label']}" for c in competencies)
    qa = "\n\n".join(
        f"Q ({t.get('competency')}): {t.get('prompt')}\nA: {t.get('answer') or '(no answer)'}"
        for t in transcript
    )
    prompt = (
        f"You are grading a structured {skill} skill interview against a FIXED rubric. "
        "Score ONLY what the answers demonstrate; empty answers score 0 for their competency. "
        "Never judge appearance, accent, or identity — only the content and structure of the answers.\n\n"
        f"COMPETENCIES (technical, one score 0..1 each):\n{comp_list}\n\n"
        "COMMUNICATION (content only, one score 0..1 each): clarity, relevance, structure, "
        "justification, follow_ups.\n\n"
        f"TRANSCRIPT:\n{qa}\n\n"
        'Return JSON ONLY with this exact shape: {"technical": {"<competency_id>": 0..1, ...}, '
        '"communication": {"clarity": 0..1, "relevance": 0..1, "structure": 0..1, '
        '"justification": 0..1, "follow_ups": 0..1}}'
    )
    try:
        raw = llm.invoke(prompt)
        text = str(getattr(raw, "content", raw) or "")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Interview grading failed: {str(e)[:200]}")

    blob = _extract_json_object(text)
    if not blob:
        raise HTTPException(status_code=502, detail="Interview grading returned an unparsable response")
    try:
        data = json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=502, detail="Interview grading returned invalid JSON")

    comp_ids = {c["id"] for c in competencies}
    technical: Dict[str, float] = {}
    for cid in comp_ids:
        v = _clamp01((data.get("technical") or {}).get(cid))
        if v is None:
            raise HTTPException(status_code=502, detail=f"Interview grading missing technical score for '{cid}'")
        technical[cid] = v
    communication: Dict[str, float] = {}
    for dim in ("clarity", "relevance", "structure", "justification", "follow_ups"):
        v = _clamp01((data.get("communication") or {}).get(dim))
        if v is None:
            raise HTTPException(status_code=502, detail=f"Interview grading missing communication score for '{dim}'")
        communication[dim] = v
    return {"technical": technical, "communication": communication}


async def complete_interview_session(
    user_id: str,
    session_id: str,
    recalculate: bool = True,
) -> dict:
    """
    Finish an interview: grade via the model when configured, else store the
    transcript as awaiting_review (no signal, nothing breaks).
    """
    c = _client()
    s = _load_session(c, user_id, session_id)
    if str(s.get("status")) not in ("in_progress",):
        raise HTTPException(status_code=409, detail="This interview session is already completed")

    plan = s.get("plan") or {}
    transcript = s.get("transcript") or []
    canonical = normalize_skill(s.get("skill_name") or "") or str(s.get("skill_name") or "")
    competencies = plan.get("competencies") or competencies_for_skill(canonical)
    now = datetime.now(timezone.utc)

    answered = sum(1 for t in transcript if isinstance(t, dict) and str(t.get("answer") or "").strip())
    if not transcript or answered == 0:
        # Nothing to grade: record honestly, emit no signal.
        update = {"status": "completed", "validity": "low_confidence", "completed_at": now.isoformat()}
        try:
            c.table(INTERVIEW_SESSIONS_TABLE).update(update).eq("id", session_id).eq("user_id", user_id).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to complete interview: {str(e)[:200]}")
        return {
            "session_id": session_id,
            "skill": canonical,
            "status": "completed",
            "validity": "low_confidence",
            "counts_as_evidence": False,
            "completed_at": update["completed_at"],
            "note": "INAURA found limited evidence of implementation understanding — no answers were submitted.",
        }

    try:
        grades = grade_interview_transcript(canonical, competencies, transcript)
    except HTTPException as e:
        if e.status_code == 503:
            # Grading not configured: keep the transcript, wait for review.
            update = {"status": "awaiting_review", "validity": "low_confidence", "completed_at": now.isoformat()}
            try:
                c.table(INTERVIEW_SESSIONS_TABLE).update(update).eq("id", session_id).eq("user_id", user_id).execute()
            except Exception as ue:
                raise HTTPException(status_code=500, detail=f"Failed to save interview: {str(ue)[:200]}")
            return {
                "session_id": session_id,
                "skill": canonical,
                "status": "awaiting_review",
                "validity": "low_confidence",
                "counts_as_evidence": False,
                "completed_at": update["completed_at"],
                "note": e.detail,
            }
        raise

    tech = grades["technical"]
    comm = grades["communication"]
    technical_overall = round(sum(tech.values()) / len(tech), 4) if tech else 0.0
    comm_overall = round(sum(comm.values()) / len(comm), 4) if comm else 0.0
    update = {
        "status": "graded",
        "validity": "valid",
        "completed_at": now.isoformat(),
        "technical_scores": {"per_competency": tech, "overall": technical_overall},
        "communication_scores": {"per_dimension": comm, "overall": comm_overall},
    }
    try:
        c.table(INTERVIEW_SESSIONS_TABLE).update(update).eq("id", session_id).eq("user_id", user_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save interview grades: {str(e)[:200]}")

    result: Dict[str, Any] = {
        "session_id": session_id,
        "skill": canonical,
        "status": "graded",
        "validity": "valid",
        "counts_as_evidence": True,
        "completed_at": update["completed_at"],
        "source_reliability": INTERVIEW_RELIABILITY,
        "technical_scores": update["technical_scores"],
        "communication_scores": update["communication_scores"],
        "note": (
            "Implementation understanding validated."
            if technical_overall >= 0.5
            else "INAURA found limited evidence of implementation understanding."
        ),
    }
    if recalculate:
        from .service import _recalculate_analysis

        result["analysis"] = await _recalculate_analysis(user_id, canonical)
    return result


def _graded_sessions(user_id: str) -> List[dict]:
    try:
        c = get_supabase_client()
        if c is None:
            return []
        r = (
            c.table(INTERVIEW_SESSIONS_TABLE).select("*")
            .eq("user_id", user_id).eq("status", "graded").eq("validity", "valid")
            .order("created_at", desc=True).limit(200).execute()
        )
        return r.data or []
    except Exception as e:
        logger.debug("Interview sessions unavailable for %s: %s", user_id, e)
        return []


def effective_interview_sessions(attempts: List[dict]) -> Dict[str, dict]:
    """Best (highest technical overall) recent graded session per skill."""
    by_skill: Dict[str, List[dict]] = {}
    for s in attempts or []:
        canonical = normalize_skill(s.get("skill_name") or "") or s.get("skill_name") or ""
        if not canonical:
            continue
        by_skill.setdefault(canonical, []).append(s)

    def _overall(s: dict) -> float:
        tech = s.get("technical_scores") or {}
        try:
            return float(tech.get("overall", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    effective: Dict[str, dict] = {}
    for canonical, rows in by_skill.items():
        rows.sort(key=lambda r: str(r.get("completed_at") or r.get("created_at") or ""), reverse=True)
        window = rows[:3]
        best = max(window, key=_overall)
        effective[canonical] = {**best, "sessions_considered": len(window), "total_sessions": len(rows)}
    return effective


def build_interview_signals(sessions: Optional[List[dict]] = None, user_id: Optional[str] = None) -> List[dict]:
    """
    Graded interview sessions -> evidence signals, one per skill.

    Only TECHNICAL scores feed the skill signal. Communication scores stay on
    the session row and are never merged into any aggregate.
    """
    rows = sessions if sessions is not None else (_graded_sessions(user_id) if user_id else [])
    signals: List[dict] = []
    for canonical, s in sorted(effective_interview_sessions(rows).items()):
        tech = s.get("technical_scores") or {}
        try:
            overall = float(tech.get("overall", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        per_comp = tech.get("per_competency") or {}
        explanation = (
            f"INAURA skill interview: {int(round(overall * 100))}% technical reasoning "
            f"on {canonical} ({s.get('interview_version', INTERVIEW_VERSION)})."
        )
        signals.append(
            make_signal(
                canonical=canonical,
                source_type=ASSESSMENT_SOURCE,
                signal_value=round(overall, 4),
                explanation=explanation,
                metadata={
                    "assessment_layer": INTERVIEW,
                    "interview_session_id": s.get("id"),
                    "assessment_score": round(overall, 4),
                    "technical_scores": per_comp,
                    "interview_version": s.get("interview_version", INTERVIEW_VERSION),
                    "completed_at": s.get("completed_at"),
                    "sessions_considered": s.get("sessions_considered", 1),
                    "aggregation": "best_of_recent_graded_sessions",
                    "prototype_instrument": True,
                },
            )
        )
    return signals


def load_interview_signals(user_id: str) -> List[dict]:
    """Interview evidence signals for the analysis pipeline. Never raises."""
    try:
        return build_interview_signals(user_id=user_id)
    except Exception as e:
        logger.debug("Interview signals unavailable for %s: %s", user_id, e)
        return []


def interview_status_for_skills(user_id: str, skills: List[str]) -> Dict[str, Optional[dict]]:
    """Best effective interview result per requested skill. Never raises."""
    try:
        c = get_supabase_client()
        if c is None:
            return {s: None for s in skills or []}
        r = (
            c.table(INTERVIEW_SESSIONS_TABLE).select("*")
            .eq("user_id", user_id).order("created_at", desc=True).limit(200).execute()
        )
        rows = r.data or []
    except Exception as e:
        logger.debug("Interview status unavailable for %s: %s", user_id, e)
        return {s: None for s in skills or []}

    out: Dict[str, Optional[dict]] = {}
    for s in skills or []:
        canonical = normalize_skill(s) or s
        mine = [row for row in rows if (normalize_skill(row.get("skill_name") or "") or row.get("skill_name")) == canonical]
        if not mine:
            out[s] = None
            continue
        # Prefer the latest graded session, else the latest session state.
        graded = [row for row in mine if str(row.get("status")) == "graded"]
        chosen = graded[0] if graded else mine[0]
        tech = chosen.get("technical_scores") or {}
        comm = chosen.get("communication_scores") or {}
        try:
            score = float(tech.get("overall")) if tech.get("overall") is not None else None
        except (TypeError, ValueError):
            score = None
        try:
            comm_overall = float(comm.get("overall")) if comm.get("overall") is not None else None
        except (TypeError, ValueError):
            comm_overall = None
        out[s] = {
            "status": str(chosen.get("status")),
            "score": round(score, 4) if score is not None else None,
            "communication_score": round(comm_overall, 4) if comm_overall is not None else None,
            "session_id": chosen.get("id"),
            "completed_at": chosen.get("completed_at"),
            "validity": chosen.get("validity", "valid"),
        }
    return out
