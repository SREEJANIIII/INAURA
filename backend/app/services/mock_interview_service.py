"""Adaptive AI mock interview — a new EVIDENCE SOURCE for INAURA.

Core principle: "Does the evidence actually demonstrate that the student
possesses the skill?" The interview collects additional skill evidence,
corroborates or challenges existing evidence, and improves confidence —
it never overwrites deterministic proficiency directly.

Architecture:
  existing evidence + assessments + interview evidence
    -> evidence aggregation / confidence (skill_engine, unchanged)
    -> skill profile -> readiness / gaps -> roadmap refinement

Design:
  * Question PLANNING is deterministic + evidence-driven (no LLM needed):
    target role, industry requirements (importance/demand/
    interview_relevance), skill gaps, signal strength, source reliability,
    assessment results, project info decide what to ask.
  * Answer EVALUATION + adaptive follow-ups use NVIDIA NIM with strict
    structured output (AnswerEvaluation). If NVIDIA NIM is unavailable the
    transcript is preserved, evaluation is marked pending, and no score is
    fabricated — the session continues with the deterministic plan.
  * Completion emits one signal per skill (source="interview",
    reliability 0.75 / directness 0.85 prototype heuristics in
    evidence_weights) through signal_extractor.make_signal, picked up by
    analysis_run_service via load_assessment_signals extension.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from ..core.supabase import get_supabase_client
from .evidence_weights import MOCK_INTERVIEW_SOURCE, reliability
from .signal_extractor import make_signal
from .skill_taxonomy import normalize_skill
from . import skill_engine as engine

logger = logging.getLogger(__name__)

SESSIONS_TABLE = "mock_interview_sessions"
QUESTIONS_TABLE = "mock_interview_questions"
RESPONSES_TABLE = "mock_interview_responses"

MOCK_INTERVIEW_VERSION = "mock-interview-v1"
INTERVIEW_RELIABILITY = reliability(MOCK_INTERVIEW_SOURCE)

# Prototype heuristics (documented, not validated psychometrics):
# contradiction thresholds compare prior proficiency vs interview signal.
CONTRADICTION_PRIOR_HIGH = 0.60
CONTRADICTION_INTERVIEW_LOW = 0.35
CORROBORATION_INTERVIEW_HIGH = 0.65
CORROBORATION_PRIOR_LOW = 0.35
MAX_FOLLOW_UP_DEPTH = 1  # at most one adaptive follow-up per base question

PRIVACY_NOTICE = (
    "Camera and microphone stay in your browser for presence. "
    "INAURA does not upload or store raw video — only your written/transcribed "
    "answers and structured evaluations are saved."
)
DISCLAIMER = (
    "Structured evidence-gathering interview: responses become supporting "
    "assessment evidence and never a verdict on your ability. INAURA does not "
    "infer competence from appearance and makes no employment decisions."
)


# ---------------------------------------------------------------------------
# Pure planning logic (no I/O — unit testable)
# ---------------------------------------------------------------------------

def _clamp01(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:
        return 0.0
    return max(0.0, min(1.0, f))


def rank_skills_for_interview(
    assessments: List[dict],
    requirements_map: Dict[str, dict],
    limit: int = 6,
) -> List[dict]:
    """Rank skills by interview priority using the EXISTING gap engine.

    Reuses engine.calculate_prioritized_gap so there is no second priority
    system. Prefers high importance + high interview_relevance + real gaps +
    uncertain confidence (evidence_estimate / low confidence / conflicting
    signals bubble up for verification).
    """
    scored: List[dict] = []
    for a in assessments or []:
        name = str(a.get("canonical_name") or a.get("skill") or "").strip()
        if not name:
            continue
        req = (requirements_map or {}).get(name)
        if req is None:
            # normalize lookup
            for k, v in (requirements_map or {}).items():
                if k.lower() == name.lower():
                    req = v
                    break
        if req is None:
            continue
        gap_val = _clamp01(a.get("gap", 0.0))
        # Skip covered skills unless evidence is shaky (worth corroborating)
        conf = _clamp01(a.get("confidence", 0.0))
        if gap_val <= 1e-9 and conf >= 0.60:
            continue
        priority, category, _ = engine.calculate_prioritized_gap(
            gap_val=gap_val if gap_val > 1e-9 else 0.15,
            importance=float(req.get("importance", 0.5)),
            demand=float(req.get("demand", 0.5)),
            student_confidence=conf,
            interview_relevance=float(req.get("interview_relevance", req.get("interview", 0.5))),
            industry_confidence=float(req.get("industry_confidence", 0.85)),
            gap_type=str(a.get("gap_type") or "skill_gap"),
        )
        # Uncertainty bonus: low confidence or conflicting signals deserve probing
        spread = 0.0
        sigs = a.get("signals") or []
        if len(sigs) >= 2:
            strengths = [_clamp01(s.get("signal_strength", s.get("signal_value", 0))) for s in sigs]
            spread = max(strengths) - min(strengths)
        bonus = 0.0
        if conf < 0.40:
            bonus += 8.0
        if spread >= 0.35:
            bonus += 6.0
        if str(a.get("evidence_state") or a.get("evidence_state_key") or "") in ("evidence_estimate",):
            bonus += 4.0
        scored.append({
            "skill": name,
            "priority": round(priority + bonus, 2),
            "category": category,
            "gap": gap_val,
            "confidence": conf,
            "proficiency": _clamp01(a.get("proficiency", 0.0)),
            "importance": float(req.get("importance", 0.5)),
            "interview_relevance": float(req.get("interview_relevance", req.get("interview", 0.5))),
            "required_level": float(req.get("required_level", 0.75)),
            "spread": round(spread, 3),
            "assessment": a,
        })
    scored.sort(key=lambda r: (r["priority"], r["interview_relevance"], r["importance"]), reverse=True)
    return scored[:limit]


def _project_for_skill(skill: str, projects: List[dict]) -> Optional[dict]:
    needle = skill.lower()
    for p in projects or []:
        if not isinstance(p, dict):
            continue
        blob = " ".join([
            str(p.get("name") or ""),
            str(p.get("description") or ""),
            str(p.get("student_contribution") or ""),
            " ".join(str(t) for t in (p.get("technologies") or []) if t),
        ]).lower()
        if needle and needle in blob:
            return p
    return None


def _leetcode_topics_for_skill(skill: str, evidence: List[dict]) -> List[str]:
    topics: List[str] = []
    for ev in evidence or []:
        if (ev.get("evidence_type") or "").lower() not in ("leetcode", "codeforces"):
            continue
        meta = ev.get("metadata") or {}
        insp = meta.get("inspection") or {}
        tc = insp.get("topic_coverage") or meta.get("topic_coverage") or {}
        bd = tc.get("pillar_breakdown") or {}
        for pillar, data in bd.items():
            if isinstance(data, dict) and skill.lower() in str(pillar).lower():
                topics.append(f"{pillar} ({data.get('solved', 0)} solved)")
    return topics[:3]


def build_mock_plan(
    ranked: List[dict],
    projects: List[dict],
    evidence: List[dict],
    question_count: int = 6,
) -> List[dict]:
    """Deterministic, evidence-driven question plan (no LLM).

    Slots for 6 questions (5-8 supported by trimming/extending):
      1. warm-up / project ownership (strongest project-linked skill)
      2. high-priority technical skill
      3. reserved adaptive follow-up slot (filled after Q2 answer)
      4. second important skill
      5. problem-solving scenario
      6. project/evidence verification
      7. (optional) final communication/behavioral
    """
    n = max(5, min(8, int(question_count or 6)))
    if not ranked:
        # No role requirements matched: generic ownership + fundamentals fallback
        base = [
            ("warmup", "General", "Walk me through a project you are most proud of. What did you personally build, and what were the key technical decisions?"),
            ("technical", "General", "Describe a challenging technical problem you solved recently. How did you diagnose it and verify the fix?"),
            ("followup_slot", "General", ""),
            ("scenario", "General", "Suppose you had to design a small production-quality solution for a teammate to maintain. How would you structure it, and why?"),
            ("verification", "General", "Pick one implementation detail from your project and explain it as if to a junior teammate — what should they understand first?"),
        ]
        if n >= 6:
            base.append(("behavioral", "General", "Tell me about a time you had to explain a technical decision to someone non-technical. How did you approach it?"))
        if n >= 7:
            base.append(("technical", "General", "What is one thing you understand better now than when you started, and what taught you that?"))
        if n >= 8:
            base.append(("scenario", "General", "What would you do differently in your project if the requirements doubled in scope?"))
        return _to_question_rows(base[:n])

    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else ranked[0]
    # Warm-up prefers the highest-priority skill with a matching project so Q1
    # is always ownership-grounded when possible (generic only as fallback).
    ownership_skill = top["skill"]
    owner_proj = _project_for_skill(ownership_skill, projects)
    if owner_proj is None:
        for r in ranked[1:]:
            cand = _project_for_skill(r["skill"], projects)
            if cand is not None:
                ownership_skill = r["skill"]
                owner_proj = cand
                break
    proj_name = (owner_proj or {}).get("name") if owner_proj else None

    if proj_name:
        q1 = (
            f"You have demonstrated {ownership_skill} through '{proj_name}'. "
            "Walk me through the part you personally built — the architecture, "
            "your implementation choices, and why you chose that approach."
        )
    else:
        q1 = (
            f"You have evidence involving {ownership_skill}. Walk me through one "
            "implementation you are most comfortable explaining — what did it do "
            "and how did you build it?"
        )

    lc = _leetcode_topics_for_skill(top["skill"], evidence)
    if lc:
        q2 = (
            f"Your coding profile shows activity related to {top['skill']} "
            f"({'; '.join(lc)}). Solved counts alone don't show mastery — explain "
            "the core pattern behind one of those topics and when you would use it."
        )
    elif top["confidence"] < 0.40 or top["spread"] >= 0.35:
        q2 = (
            f"INAURA has some evidence for {top['skill']} but with limited confidence. "
            f"Explain the core concepts of {top['skill']} you rely on most and give "
            "a concrete example of each in practice."
        )
    else:
        q2 = (
            f"For {top['skill']}: describe a trade-off you faced (performance, "
            "readability, cost, or complexity) and how you decided. What would "
            "make you reverse that decision?"
        )

    rows: List[Tuple[str, str, str]] = [
        ("warmup", ownership_skill, q1),
        ("technical", top["skill"], q2),
        ("followup_slot", top["skill"], ""),  # filled adaptively
        ("technical", second["skill"],
         f"Moving to {second['skill']}: explain how you would approach a new practical "
         "task in this skill from scratch. How do you break it down and validate each step?"),
        ("scenario", top["skill"],
         f"Scenario: you must design a small but production-quality solution using "
         f"{top['skill']} for a teammate to maintain. How would you structure it, and why?"),
        ("verification", ownership_skill,
         f"Verification: in '{proj_name or 'your project'}', what would break if a core "
         f"{ownership_skill} implementation detail changed? Explain the mechanism, not just the outcome."),
    ]
    if n >= 7:
        rows.append(("behavioral", second["skill"],
                      "Finally: explain your strongest technical decision in this "
                      "interview as if to a non-technical stakeholder. What mattered most?"))
    if n >= 8:
        third = ranked[2]["skill"] if len(ranked) > 2 else second["skill"]
        rows.insert(5, ("technical", third,
                        f"For {third}: what is a common misunderstanding people have "
                        "about this skill, and how would you correct it with an example?"))
    return _to_question_rows(rows[:n])


def _to_question_rows(slots: List[Tuple[str, str, str]]) -> List[dict]:
    out = []
    for i, (qtype, skill, text) in enumerate(slots, start=1):
        out.append({
            "id": f"q{i}",
            "sequence": i,
            "question": text,
            "question_type": qtype,
            "target_skill": skill,
            "source_evidence": "",
            "priority": 0.0,
            "interview_relevance": 0.0,
            "is_follow_up": False,
            "parent_question_id": None,
        })
    return out


def parse_evaluation(raw_text: str, question_id: str) -> Dict[str, Any]:
    """Strict-parse NVIDIA NIM JSON into the AnswerEvaluation contract."""
    blob = _extract_json_object(raw_text or "")
    if not blob:
        raise ValueError("no JSON object in model reply")
    data = json.loads(blob)
    if not isinstance(data, dict):
        raise ValueError("evaluation is not an object")
    out = {
        "question_id": question_id,
        "skills": [str(s)[:80] for s in (data.get("skills") or []) if str(s).strip()][:8],
        "technical_correctness": _clamp01(data.get("technical_correctness", 0)),
        "depth": _clamp01(data.get("depth", 0)),
        "reasoning": _clamp01(data.get("reasoning", 0)),
        "communication": _clamp01(data.get("communication", 0)),
        "evidence_corroboration": _clamp01(data.get("evidence_corroboration", 0)),
        "contradiction": _clamp01(data.get("contradiction", 0)),
        "confidence": _clamp01(data.get("confidence", 0)),
        "explanation": str(data.get("explanation") or "")[:1000],
        "follow_up_needed": bool(data.get("follow_up_needed", False)),
        "suggested_follow_up": str(data.get("suggested_follow_up") or "")[:600],
    }
    return out


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


def decide_next_action(
    evaluation: Optional[Dict[str, Any]],
    current_sequence: int,
    total_planned: int,
    follow_ups_used: int,
) -> str:
    """Adaptive policy (pure): follow_up | next | complete.

    Follow up only when the evaluator asks for it with sufficient confidence,
    the answer shows a real gap (low technical/depth or high contradiction),
    and budget remains (depth + total count caps for 5-8 question MVP).
    """
    answered = current_sequence  # 1-based count just answered
    if answered >= total_planned and (not evaluation or not evaluation.get("follow_up_needed")):
        return "complete"
    if evaluation and evaluation.get("follow_up_needed"):
        weak = (
            evaluation.get("technical_correctness", 1) < 0.55
            or evaluation.get("depth", 1) < 0.50
            or evaluation.get("contradiction", 0) > 0.50
        )
        confident = evaluation.get("confidence", 0) >= 0.45
        has_question = bool(str(evaluation.get("suggested_follow_up") or "").strip())
        if weak and confident and has_question and follow_ups_used < MAX_FOLLOW_UP_DEPTH * 2 and answered < 8:
            return "follow_up"
    if answered >= total_planned:
        return "complete"
    return "next"


def signal_strength_from_evaluation(ev: Dict[str, Any]) -> float:
    """Answer -> evidence signal strength (pure, documented).

    Weights technical correctness most (0.45), then depth (0.25) and
    reasoning (0.20); corroboration adds a small bonus, contradiction a
    penalty — all scaled by evaluator confidence so uncertain grades
    contribute weakly rather than confidently.
    """
    t = _clamp01(ev.get("technical_correctness", 0))
    d = _clamp01(ev.get("depth", 0))
    r = _clamp01(ev.get("reasoning", 0))
    corr = _clamp01(ev.get("evidence_corroboration", 0))
    contra = _clamp01(ev.get("contradiction", 0))
    conf = _clamp01(ev.get("confidence", 0))
    raw = 0.45 * t + 0.25 * d + 0.20 * r + 0.10 * corr - 0.25 * contra
    raw = max(0.0, min(1.0, raw))
    # Confidence scales the signal toward neutral (0.5 shrinks weakly held
    # judgments instead of asserting them).
    return round(max(0.0, min(1.0, raw * (0.5 + 0.5 * conf))), 4)


def detect_contradiction(prior_proficiency: Optional[float], interview_signal: Optional[float]) -> Tuple[str, str]:
    """Compare prior evidence vs interview signal (pure).

    Never accuses — language distinguishes "exposure" from "demonstrated
    understanding" per INAURA's evidence principle.
    """
    if prior_proficiency is None or interview_signal is None:
        return "insufficient_data", "Not enough evidence on one side to compare."
    p, s = float(prior_proficiency), float(interview_signal)
    if p >= CONTRADICTION_PRIOR_HIGH and s <= CONTRADICTION_INTERVIEW_LOW:
        return (
            "requires_further_validation",
            "Repository evidence indicates substantial exposure, but interview "
            "responses provided limited evidence of independent understanding.",
        )
    if p <= CORROBORATION_PRIOR_LOW and s >= CORROBORATION_INTERVIEW_HIGH:
        return (
            "corroborated_upgrade",
            "Interview responses provided additional evidence supporting the "
            "demonstrated skill beyond what prior evidence showed.",
        )
    if s >= 0.55 and p >= 0.45:
        return "corroborated", "Interview evidence corroborates existing evidence."
    if s < 0.40 and p < 0.45:
        return "consistent_weak", "Both prior evidence and interview responses show limited demonstration so far."
    return "mixed", "Interview evidence partially aligns with prior evidence; further validation would help."


def build_skill_signals(
    session_id: str,
    evaluations: List[Dict[str, Any]],
    target_role: str,
) -> List[dict]:
    """Per-skill interview signals (one per skill, mean of answer strengths)."""
    by_skill: Dict[str, List[float]] = {}
    for ev in evaluations or []:
        skills = ev.get("skills") or []
        if not skills:
            continue
        strength = signal_strength_from_evaluation(ev)
        for s in skills:
            canon = normalize_skill(str(s)) or str(s).strip()
            if canon:
                by_skill.setdefault(canon, []).append(strength)
    signals = []
    for skill, strengths in sorted(by_skill.items()):
        avg = round(sum(strengths) / len(strengths), 4) if strengths else 0.0
        signals.append(make_signal(
            canonical=skill,
            source_type=MOCK_INTERVIEW_SOURCE,
            signal_value=avg,
            explanation=(
                f"AI mock interview ({MOCK_INTERVIEW_VERSION}): {len(strengths)} "
                f"answer(s) averaged to {int(round(avg * 100))}% for target role {target_role}."
            ),
            metadata={
                "mock_interview_session_id": session_id,
                "mock_interview_version": MOCK_INTERVIEW_VERSION,
                "target_role": target_role,
                "answers_count": len(strengths),
                "aggregation": "mean_answer_strength",
                "prototype_instrument": True,
            },
        ))
    return signals


# ---------------------------------------------------------------------------
# NVIDIA NIM (server-side only; never fabricate when unavailable)
# ---------------------------------------------------------------------------

def _make_llm():
    from langchain_nvidia_ai_endpoints import ChatNVIDIA
    from ..core.config import get_settings

    settings = get_settings()
    if not settings.nvidia_api_key:
        raise HTTPException(
            status_code=503,
            detail="AI interview evaluation is not configured — set NVIDIA_API_KEY. "
                   "Your answer is saved; retry evaluation once configured.",
        )
    return ChatNVIDIA(
        model=settings.nvidia_model or "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        api_key=settings.nvidia_api_key,
        temperature=0.6,
        top_p=0.95,
        max_completion_tokens=65536,
    )


# Gemini implementation kept commented for a future provider rollback.
#
# def _make_gemini_llm_legacy():
#     from langchain_google_genai import ChatGoogleGenerativeAI
#     from ..core.config import get_settings
#
#     settings = get_settings()
#     if not settings.google_api_key:
#         raise HTTPException(
#             status_code=503,
#             detail="AI interview evaluation is not configured — set GOOGLE_API_KEY.",
#         )
#     return ChatGoogleGenerativeAI(
#         model=settings.gemini_model or "gemini-2.5-flash",
#         google_api_key=settings.google_api_key,
#         temperature=0.2,
#     )


EVAL_SYSTEM = (
    "You are a professional technical interviewer producing STRUCTURED EVIDENCE, "
    "not hiring decisions. Ask nothing; evaluate ONE answer against the question, "
    "the target skill, and the prior evidence summary. Be concise and fair: score "
    "only what the answer demonstrates. Never judge appearance, accent, or identity. "
    "Never claim certainty beyond the evidence. Return JSON ONLY with keys: "
    "skills (list of canonical skill names this answer evidences), "
    "technical_correctness 0-1, depth 0-1, reasoning 0-1, communication 0-1, "
    "evidence_corroboration 0-1 (does it support the prior evidence?), "
    "contradiction 0-1 (does it conflict with prior evidence?), "
    "confidence 0-1 (your certainty in this grading), "
    "explanation (2-3 sentences, evidence-based), "
    "follow_up_needed (true when the answer is vague, shallow, or contradictory "
    "and one focused probe would clarify understanding), "
    "suggested_follow_up (one concise question, or empty string)."
)


async def evaluate_answer_llm(
    question: dict,
    transcript: str,
    prior_evidence_summary: str,
    _llm: Any = None,
) -> Dict[str, Any]:
    llm = _llm if _llm is not None else _make_llm()
    user_prompt = (
        f"Target skill: {question.get('target_skill')}\n"
        f"Question ({question.get('question_type')}): {question.get('question')}\n"
        f"Prior evidence: {prior_evidence_summary[:1500]}\n\n"
        f"Student answer:\n{transcript[:4000]}"
    )
    try:
        if hasattr(llm, "ainvoke"):
            raw = await llm.ainvoke([
                {"role": "system", "content": EVAL_SYSTEM},
                {"role": "user", "content": user_prompt},
            ])
            text = str(getattr(raw, "content", raw) or "")
        else:  # sync mock in tests
            raw = llm.invoke(user_prompt)
            text = str(getattr(raw, "content", raw) or "")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Interview evaluation failed: {str(e)[:200]}")
    try:
        return parse_evaluation(text, str(question.get("id") or ""))
    except Exception:
        logger.warning("mock-interview: unparseable evaluation (excerpt %r)", text[:400])
        raise HTTPException(status_code=502, detail="AI interview returned an unparseable evaluation — please retry.")


# ---------------------------------------------------------------------------
# Session orchestration (I/O)
# ---------------------------------------------------------------------------

def _client():
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    return c


def _table_missing(err: Exception) -> bool:
    m = str(err).lower()
    return "could not find the table" in m or "pgrst205" in m or "does not exist" in m


def _resolve_role(user_id: str, requested: Optional[str]) -> str:
    if requested and requested.strip():
        return requested.strip()
    try:
        from . import analysis_service
        state = analysis_service.get_state(user_id) or {}
        if state.get("target_role"):
            return str(state["target_role"])
    except Exception:
        pass
    try:
        from . import profile_service
        profile = profile_service.get_profile(user_id) or {}
        interests = profile.get("career_interests") or []
        if interests:
            return str(interests[0])
    except Exception:
        pass
    raise HTTPException(status_code=400, detail="No target role — select a primary career goal first")


def _snapshot_assessments(user_id: str, role: str) -> Tuple[List[dict], Dict[str, dict], List[dict], List[dict]]:
    """Reuse the CURRENT deterministic pipeline read-only for planning context."""
    from . import analysis_run_service as ars
    evidence, projects, certs = ars.load_evidence(user_id)
    requirements = ars.load_industry_requirements(role)
    signals = ars.extract_skill_signals(evidence, projects, certs)
    try:
        from .assessment.service import load_assessment_signals
        signals = list(signals) + load_assessment_signals(user_id)
    except Exception:
        pass
    try:
        signals = list(signals) + load_mock_interview_signals(user_id)
    except Exception:
        pass
    c = get_supabase_client()
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, c))
    req_map = ars.build_requirements_map(requirements, c)
    try:
        overrides = ars.load_user_overrides(user_id, c)
    except Exception:
        overrides = {}
    assessments = ars.calculate_assessments(grouped, req_map, c, overrides=overrides)
    return assessments, req_map, projects, evidence


MOCK_PLAN_SYSTEM = (
    "You are a professional technical interviewer. Create an original interview "
    "plan from the supplied evidence context. Do not use a fixed question bank, "
    "generic filler, or repeated question patterns. Every question must be "
    "specific to the supplied skills, projects, or evidence. Return JSON only "
    "with a questions array; each item must contain question, question_type, "
    "and target_skill."
)


async def generate_mock_plan(
    ranked: List[dict],
    projects: List[dict],
    evidence: List[dict],
    question_count: int,
) -> List[dict]:
    """Generate the live mock plan; never expose the deterministic templates."""
    llm = _make_llm()
    count = max(5, min(8, int(question_count or 6)))
    context = {
        "skills": [
            {k: r.get(k) for k in ("skill", "priority", "gap", "confidence", "proficiency")}
            for r in ranked[:6]
        ],
        "projects": projects[:8],
        "evidence_types": sorted({str(e.get("evidence_type") or "") for e in evidence if isinstance(e, dict)}),
        "question_count": count,
    }
    try:
        raw = await llm.ainvoke([
            {"role": "system", "content": MOCK_PLAN_SYSTEM},
            {"role": "user", "content": json.dumps(context, default=str)},
        ])
        text = str(getattr(raw, "content", raw) or "")
        blob = _extract_json_object(text)
        data = json.loads(blob) if blob else {}
        generated = data.get("questions") if isinstance(data, dict) else None
        if not isinstance(generated, list) or len(generated) < count:
            raise ValueError("AI returned too few interview questions")
        rows = []
        for index, item in enumerate(generated[:count], start=1):
            question = str(item.get("question") or "").strip()
            if len(question) < 20:
                raise ValueError("AI returned an invalid interview question")
            rows.append({
                "id": f"q{index}",
                "sequence": index,
                "question": question[:800],
                "question_type": str(item.get("question_type") or "technical")[:40],
                "target_skill": str(item.get("target_skill") or "")[:120],
                "source_evidence": "",
                "priority": 0.0,
                "interview_relevance": 0.0,
                "is_follow_up": False,
                "parent_question_id": None,
            })
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("mock interview plan generation failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="AI interview question generation is unavailable. No predefined questions were used.",
        ) from exc


async def start_session(user_id: str, target_role: Optional[str], question_count: int = 6) -> dict:
    role = _resolve_role(user_id, target_role)
    assessments, req_map, projects, evidence = _snapshot_assessments(user_id, role)
    ranked = rank_skills_for_interview(assessments, req_map, limit=6)
    plan = await generate_mock_plan(ranked, projects, evidence, question_count)
    # Annotate priority / interview_relevance + source evidence onto plan
    rank_by_skill = {r["skill"].lower(): r for r in ranked}
    for q in plan:
        r = rank_by_skill.get(str(q.get("target_skill") or "").lower())
        if r:
            q["priority"] = r["priority"]
            q["interview_relevance"] = r["interview_relevance"]
            a = r.get("assessment") or {}
            sigs = (a.get("signals") or [])[:2]
            srcs = sorted({str(s.get("source") or s.get("source_type") or "") for s in sigs if isinstance(s, dict)})
            q["source_evidence"] = ", ".join(s for s in srcs if s) or "industry requirement"

    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    c = _client()
    try:
        c.table(SESSIONS_TABLE).insert({
            "id": session_id,
            "user_id": user_id,
            "target_role": role,
            "status": "in_progress",
            "current_index": 0,
            "question_count": len(plan),
            "plan": {"version": MOCK_INTERVIEW_VERSION, "ranked_skills": [
                {k: r[k] for k in ("skill", "priority", "gap", "confidence", "proficiency") if k in r}
                for r in ranked
            ]},
            "prior_snapshot": [
                {"skill": a.get("canonical_name"), "proficiency": a.get("proficiency"),
                 "confidence": a.get("confidence"), "gap": a.get("gap")}
                for a in assessments[:40]
            ],
            "started_at": now,
        }).execute()
        for q in plan:
            c.table(QUESTIONS_TABLE).insert({
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "question_key": q["id"],
                "sequence": q["sequence"],
                "question": q["question"],
                "question_type": q["question_type"],
                "target_skill": q["target_skill"],
                "source_evidence": q.get("source_evidence") or "",
                "priority": float(q.get("priority") or 0),
                "interview_relevance": float(q.get("interview_relevance") or 0),
                "is_follow_up": False,
            }).execute()
    except Exception as e:
        if _table_missing(e):
            raise HTTPException(status_code=503, detail="Interview tables not found — run backend/supabase/020_mock_interview.sql")
        raise HTTPException(status_code=500, detail=f"Failed to start interview: {str(e)[:200]}")

    from ..core.config import get_settings
    ai_available = bool(get_settings().nvidia_api_key)
    return {
        "session_id": session_id,
        "target_role": role,
        "status": "in_progress",
        "question_count": len(plan),
        "current_index": 0,
        "questions": plan,
        "current_question": plan[0] if plan else None,
        "ai_available": ai_available,
        "privacy_notice": PRIVACY_NOTICE,
        "disclaimer": DISCLAIMER,
    }


def _load_session(c: Any, user_id: str, session_id: str) -> dict:
    try:
        r = c.table(SESSIONS_TABLE).select("*").eq("user_id", user_id).eq("id", session_id).limit(1).execute()
    except Exception as e:
        if _table_missing(e):
            raise HTTPException(status_code=503, detail="Interview tables not found — run backend/supabase/020_mock_interview.sql")
        raise HTTPException(status_code=500, detail="Failed to load interview session")
    if not r.data:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return r.data[0]


def _load_questions(c: Any, session_id: str) -> List[dict]:
    try:
        r = c.table(QUESTIONS_TABLE).select("*").eq("session_id", session_id).order("sequence").execute()
    except Exception:
        return []
    return r.data or []


def _load_responses(c: Any, session_id: str) -> List[dict]:
    try:
        r = c.table(RESPONSES_TABLE).select("*").eq("session_id", session_id).order("created_at").execute()
    except Exception:
        return []
    return r.data or []


def _question_out(q: dict) -> dict:
    return {
        "id": str(q.get("question_key") or q.get("id")),
        "sequence": int(q.get("sequence") or 0),
        "question": str(q.get("question") or ""),
        "question_type": str(q.get("question_type") or "technical"),
        "target_skill": str(q.get("target_skill") or ""),
        "source_evidence": str(q.get("source_evidence") or ""),
        "priority": float(q.get("priority") or 0),
        "interview_relevance": float(q.get("interview_relevance") or 0),
        "is_follow_up": bool(q.get("is_follow_up")),
        "parent_question_id": q.get("parent_question_id"),
    }


def get_session(user_id: str, session_id: str) -> dict:
    from ..core.config import get_settings
    c = _client()
    s = _load_session(c, user_id, session_id)
    questions = _load_questions(c, session_id)
    responses = _load_responses(c, session_id)
    idx = int(s.get("current_index") or 0)
    outs = [_question_out(q) for q in questions]
    current = outs[idx] if 0 <= idx < len(outs) else None
    return {
        "session_id": s.get("id"),
        "target_role": s.get("target_role"),
        "status": s.get("status"),
        "question_count": len(outs),
        "current_index": idx,
        "questions": outs,
        "current_question": current,
        "answers_count": len(responses),
        "ai_available": bool(get_settings().nvidia_api_key),
    }


async def submit_answer(
    user_id: str,
    session_id: str,
    transcript: str,
    question_id: Optional[str] = None,
    _llm: Any = None,
) -> dict:
    c = _client()
    s = _load_session(c, user_id, session_id)
    if str(s.get("status")) != "in_progress":
        raise HTTPException(status_code=409, detail="This interview session is already completed")
    questions = _load_questions(c, session_id)
    if not questions:
        raise HTTPException(status_code=500, detail="Interview has no questions")
    idx = int(s.get("current_index") or 0)
    current = questions[idx] if 0 <= idx < len(questions) else questions[-1]
    if question_id and str(current.get("question_key")) != str(question_id) and str(current.get("id")) != str(question_id):
        # Tolerate explicit ids by finding the question; never silently grade the wrong one
        match = next((q for q in questions
                      if str(q.get("question_key")) == str(question_id) or str(q.get("id")) == str(question_id)), None)
        if match is None:
            raise HTTPException(status_code=400, detail="question_id does not belong to this session")
        current = match
        idx = questions.index(current)

    text = (transcript or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Answer transcript is empty")
    # Scrub secrets before any LLM call (reuse ai-review pattern)
    text = _scrub_text(text)

    prior_summary = _prior_summary_for(s, str(current.get("target_skill") or ""))
    q_out = _question_out(current)
    evaluation: Optional[Dict[str, Any]] = None
    ai_available = True
    evaluation_pending = False
    note = None
    try:
        evaluation = await evaluate_answer_llm(
            {"id": q_out["id"], "target_skill": q_out["target_skill"],
             "question_type": q_out["question_type"], "question": q_out["question"]},
            text, prior_summary, _llm=_llm,
        )
    except HTTPException as e:
        if e.status_code in (502, 503):
            ai_available = False
            evaluation_pending = True
            note = e.detail
        else:
            raise

    try:
        c.table(RESPONSES_TABLE).insert({
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "question_id": current.get("id"),
            "question_key": current.get("question_key"),
            "transcript": text[:8000],
            "evaluation": evaluation,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        if _table_missing(e):
            raise HTTPException(status_code=503, detail="Interview tables not found — run backend/supabase/020_mock_interview.sql")
        raise HTTPException(status_code=500, detail=f"Failed to save answer: {str(e)[:200]}")

    responses = _load_responses(c, session_id)
    follow_ups_used = sum(1 for q in questions if q.get("is_follow_up"))
    action = decide_next_action(evaluation, idx + 1, len(questions), follow_ups_used)

    if action == "follow_up" and evaluation and evaluation.get("suggested_follow_up"):
        follow_q = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "question_key": f"q{idx + 1}f",
            "sequence": idx + 1,  # inserted right after current
            "question": str(evaluation["suggested_follow_up"])[:600],
            "question_type": "follow_up",
            "target_skill": q_out["target_skill"],
            "source_evidence": "adaptive follow-up",
            "priority": q_out["priority"],
            "interview_relevance": q_out["interview_relevance"],
            "is_follow_up": True,
            "parent_question_id": current.get("id"),
        }
        try:
            # Shift later questions down by re-sequencing in memory order
            c.table(QUESTIONS_TABLE).insert(follow_q).execute()
            questions = _load_questions(c, session_id)
            # Re-sequence deterministically by (sequence, created order)
            questions.sort(key=lambda q: (int(q.get("sequence") or 0), str(q.get("created_at") or "")))
            for i, q in enumerate(questions):
                try:
                    c.table(QUESTIONS_TABLE).update({"sequence": i + 1}).eq("id", q.get("id")).execute()
                except Exception:
                    pass
            questions = _load_questions(c, session_id)
        except Exception:
            action = "next"  # fall back to deterministic plan; never break the session

    if action == "complete":
        return {
            "session_id": session_id,
            "question_id": q_out["id"],
            "next_action": "complete",
            "ai_available": ai_available,
            "evaluation": evaluation,
            "evaluation_pending": evaluation_pending,
            "current_index": idx,
            "current_question": None,
            "completed": False,
            "note": (note or "Final answer recorded. Complete the interview to see your evidence report."),
        }

    new_idx = idx + 1
    # If a follow-up was inserted at idx+1, new_idx already points at it
    try:
        c.table(SESSIONS_TABLE).update({"current_index": new_idx}).eq("id", session_id).execute()
    except Exception:
        pass
    questions = _load_questions(c, session_id)
    outs = [_question_out(q) for q in questions]
    current_out = outs[new_idx] if 0 <= new_idx < len(outs) else None
    return {
        "session_id": session_id,
        "question_id": q_out["id"],
        "next_action": action,
        "ai_available": ai_available,
        "evaluation": evaluation,
        "evaluation_pending": evaluation_pending,
        "current_index": new_idx,
        "current_question": current_out,
        "completed": False,
        "note": note,
    }


async def complete_session(user_id: str, session_id: str) -> dict:
    c = _client()
    s = _load_session(c, user_id, session_id)
    if str(s.get("status")) != "in_progress":
        raise HTTPException(status_code=409, detail="This interview session is already completed")
    report = build_report(user_id, session_id)
    try:
        c.table(SESSIONS_TABLE).update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "report": report,
        }).eq("id", session_id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to complete interview: {str(e)[:200]}")
    # Flow new evidence through the EXISTING pipeline (recalc); failures never block the report
    try:
        from .assessment.service import _recalculate_analysis
        target = str(s.get("target_role") or "")
        if target:
            from . import analysis_run_service as ars
            from . import analysis_service
            state = None
            try:
                state = analysis_service.get_state(user_id) or {}
            except Exception:
                state = {}
            role = state.get("target_role") or target
            if role:
                analysis = await ars.run_analysis(user_id, role)
                report["analysis"] = {
                    "analysis_id": analysis.get("id"),
                    "target_role": analysis.get("target_role"),
                    "readiness_score": analysis.get("readiness_score"),
                }
    except Exception as e:
        logger.debug("Post-interview recalculation failed for %s: %s", user_id, e)
    return report


def build_report(user_id: str, session_id: str) -> dict:
    from ..core.config import get_settings
    c = _client() if get_supabase_client() is not None else None
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    s = _load_session(c, user_id, session_id)
    questions = _load_questions(c, session_id)
    responses = _load_responses(c, session_id)
    evals = [r.get("evaluation") for r in responses if isinstance(r.get("evaluation"), dict)]

    prior = {str(p.get("skill") or "").lower(): p for p in (s.get("prior_snapshot") or []) if isinstance(p, dict)}
    signals = build_skill_signals(str(s.get("id")), evals, str(s.get("target_role") or ""))
    sig_by_skill = {}
    for sig in signals:
        sig_by_skill[str(sig.get("skill") or sig.get("canonical_name") or "").lower()] = float(
            sig.get("signal_strength", sig.get("signal_value", 0)) or 0)

    skills = sorted({str(q.get("target_skill") or "") for q in questions if str(q.get("target_skill") or "").strip()}
                    | {str(sig.get("skill") or sig.get("canonical_name") or "") for sig in signals})
    skill_results = []
    corroborated, needs_validation, strengths, weak = [], [], [], []
    inconsistencies = []
    for skill in skills:
        p = prior.get(skill.lower(), {})
        before_prof = p.get("proficiency")
        before_conf = p.get("confidence")
        iv = sig_by_skill.get(skill.lower())
        verdict, explanation = detect_contradiction(
            float(before_prof) if before_prof is not None else None,
            iv,
        )
        skill_results.append({
            "skill": skill,
            "evidence_before": before_prof,
            "proficiency_before": before_prof,
            "confidence_before": before_conf,
            "interview_signal": iv,
            "verdict": verdict,
            "explanation": explanation,
        })
        if verdict in ("corroborated", "corroborated_upgrade"):
            corroborated.append(skill)
            if iv is not None and iv >= 0.60:
                strengths.append(skill)
        elif verdict == "requires_further_validation":
            needs_validation.append(skill)
            weak.append(skill)
            inconsistencies.append({
                "skill": skill,
                "detail": explanation,
            })
        elif verdict in ("consistent_weak", "mixed"):
            weak.append(skill)
            if verdict == "mixed":
                needs_validation.append(skill)

    next_actions = []
    for r in skill_results:
        if r["verdict"] == "requires_further_validation":
            next_actions.append(f"Revisit {r['skill']} fundamentals — interview showed limited demonstration despite project exposure.")
        elif r["verdict"] == "corroborated_upgrade":
            next_actions.append(f"Showcase {r['skill']} — interview added new supporting evidence; keep it visible in your profile.")
        elif r["verdict"] == "consistent_weak":
            next_actions.append(f"Practice {r['skill']} basics and re-verify with an INAURA assessment.")
    # Roadmap hint is derived, never written directly: updated skill profile ->
    # existing gap calculation -> existing roadmap generation on next run.
    if not next_actions:
        next_actions.append("Run INAURA analysis to refresh gaps and regenerate your roadmap with the new interview evidence.")

    conf_vals = [float(e.get("confidence") or 0) for e in evals]
    overall = round(sum(conf_vals) / len(conf_vals), 3) if conf_vals else 0.0
    return {
        "session_id": str(s.get("id")),
        "target_role": str(s.get("target_role") or ""),
        "status": "completed",
        "questions_answered": len(responses),
        "skills_evaluated": skills,
        "strengths": strengths,
        "weak_evidence": sorted(set(weak)),
        "needs_validation": sorted(set(needs_validation)),
        "corroborated": corroborated,
        "inconsistencies": inconsistencies,
        "skill_results": skill_results,
        "recommended_next_actions": next_actions[:8],
        "overall_interview_confidence": overall,
        "ai_available": bool(get_settings().nvidia_api_key),
        "note": "Interview evidence flows into your skill profile on next analysis; roadmap updates follow existing gap logic.",
    }


def _prior_summary_for(session: dict, skill: str) -> str:
    prior = session.get("prior_snapshot") or []
    for p in prior:
        if str(p.get("skill") or "").lower() == skill.lower():
            return (
                f"{skill}: prior proficiency {p.get('proficiency')}, "
                f"confidence {p.get('confidence')}, gap {p.get('gap')}"
            )
    return f"{skill}: no prior INAURA estimate"


def _scrub_text(text: str) -> str:
    """Remove likely secrets from transcripts before LLM calls (best effort)."""
    import re
    patterns = [
        r"(?i)(api[_-]?key\s*[:=]\s*)([^\s,;]+)",
        r"(?i)(secret\s*[:=]\s*)([^\s,;]+)",
        r"(?i)(password\s*[:=]\s*)([^\s,;]+)",
        r"(?i)(bearer\s+)([A-Za-z0-9\-._~+/=]+)",
        r"ghp_[A-Za-z0-9]+",
        r"github_pat_[A-Za-z0-9_]+",
    ]
    out = text
    for pat in patterns:
        out = re.sub(pat, r"\1[redacted]", out)
    return out


# ---------------------------------------------------------------------------
# Evidence integration: interview signals join the standard pipeline
# ---------------------------------------------------------------------------

def _graded_completed_sessions(user_id: str) -> List[dict]:
    try:
        c = get_supabase_client()
        if c is None:
            return []
        r = (c.table(SESSIONS_TABLE).select("*").eq("user_id", user_id)
             .eq("status", "completed").order("created_at", desc=True).limit(20).execute())
        return r.data or []
    except Exception as e:
        logger.debug("Mock interview sessions unavailable for %s: %s", user_id, e)
        return []


def load_mock_interview_signals(user_id: str) -> List[dict]:
    """Completed mock-interview sessions -> one signal per skill. Never raises."""
    try:
        sessions = _graded_completed_sessions(user_id)
        if not sessions:
            return []
        c = get_supabase_client()
        signals: List[dict] = []
        for s in sessions[:5]:  # recent sessions only; analysis persists snapshots anyway
            try:
                r = c.table(RESPONSES_TABLE).select("evaluation").eq("session_id", s.get("id")).execute()
            except Exception:
                continue
            evals = [row.get("evaluation") for row in (r.data or []) if isinstance(row.get("evaluation"), dict)]
            signals.extend(build_skill_signals(str(s.get("id")), evals, str(s.get("target_role") or "")))
        # Keep best signal per skill (a later strong session supersedes)
        best: Dict[str, dict] = {}
        for sig in signals:
            key = str(sig.get("skill") or sig.get("canonical_name") or "").lower()
            val = float(sig.get("signal_strength", 0) or 0)
            if key and (key not in best or val > float(best[key].get("signal_strength", 0) or 0)):
                best[key] = sig
        return list(best.values())
    except Exception as e:
        logger.debug("Mock interview signals unavailable for %s: %s", user_id, e)
        return []
