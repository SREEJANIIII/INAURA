"""
Skill-specific 3-layer assessment capabilities (pure logic, no I/O).

Layers:
  * knowledge  — MCQ / conceptual / scenario questions (existing question bank)
  * practical  — coding or skill-specific work-sample task (only where applicable)
  * interview  — structured, skill-specific AI interview (competency-anchored)

A skill is validated independently using only the layers appropriate for it.
Coding tasks are never forced onto non-coding skills.

Assessment remains ONE evidence source among many: each completed layer emits
a standard evidence signal (source_type="assessment" with an
``assessment_layer`` marker) so the existing skill/gap pipeline incorporates
it without any competing score system.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..skill_taxonomy import get_canonical_skill, normalize_skill, normalize_skill_slug
from .question_bank import has_questions
from .practical_bank import has_practical

KNOWLEDGE = "knowledge"
PRACTICAL = "practical"
INTERVIEW = "interview"

LAYERS = (KNOWLEDGE, PRACTICAL, INTERVIEW)

LAYER_LABELS: Dict[str, str] = {
    KNOWLEDGE: "Knowledge",
    PRACTICAL: "Practical",
    INTERVIEW: "AI Interview",
}

LAYER_DESCRIPTIONS: Dict[str, str] = {
    KNOWLEDGE: "Do you understand the skill?",
    PRACTICAL: "Can you apply the skill?",
    INTERVIEW: "Can you explain, reason about, and defend your understanding?",
}

LAYER_ICONS: Dict[str, str] = {
    KNOWLEDGE: "\U0001f9e0",  # 🧠
    PRACTICAL: "\U0001f4bb",  # 💻
    INTERVIEW: "\U0001f3a4",  # 🎤
}


@dataclass(frozen=True)
class SkillAssessmentCapability:
    """Which assessment layers apply to one canonical skill."""

    skill: str
    skill_key: str
    knowledge_assessment: bool = False
    practical_assessment: bool = False
    interview_assessment: bool = False
    practical_kind: Optional[str] = None

    @property
    def layers(self) -> List[str]:
        ordered: List[str] = []
        if self.knowledge_assessment:
            ordered.append(KNOWLEDGE)
        if self.practical_assessment:
            ordered.append(PRACTICAL)
        if self.interview_assessment:
            ordered.append(INTERVIEW)
        return ordered

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "skill_key": self.skill_key,
            "knowledge_assessment": self.knowledge_assessment,
            "practical_assessment": self.practical_assessment,
            "interview_assessment": self.interview_assessment,
            "practical_kind": self.practical_kind,
            "layers": self.layers,
        }


def capability_for_skill(skill: str) -> Optional[SkillAssessmentCapability]:
    """
    Applicable assessment layers for one skill.

    * knowledge  — when the deterministic question bank covers the skill
    * practical  — when the practical task bank has a work-sample task
                   (never forced onto skills without one)
    * interview  — for every skill the taxonomy knows, anchored to
                   skill-specific competencies (generic fallback otherwise)

    Returns None only when the skill is unknown to both the taxonomy and
    the banks.
    """
    canonical = normalize_skill(skill or "")
    slug = normalize_skill_slug(skill or "")
    known = canonical is not None or get_canonical_skill(skill or "") is not None
    knowledge = bool(canonical and has_questions(canonical))
    practical = bool((canonical and has_practical(canonical)) or (slug and has_practical(slug)))

    if not (known or knowledge or practical):
        return None

    display = canonical or (skill or "").strip()
    key = slug or (display.lower() if display else "")
    return SkillAssessmentCapability(
        skill=display,
        skill_key=key,
        knowledge_assessment=knowledge,
        practical_assessment=practical,
        interview_assessment=True,
        practical_kind="coding" if practical else None,
    )


def capabilities_for_skills(skills: List[str]) -> Dict[str, SkillAssessmentCapability]:
    """Map canonical skill name -> capability (skips unrecognized skills)."""
    out: Dict[str, SkillAssessmentCapability] = {}
    for s in skills or []:
        cap = capability_for_skill(s)
        if cap is not None:
            out[cap.skill] = cap
    return out


def layer_status_summary(layer_results: Dict[str, Optional[dict]]) -> dict:
    """
    Normalize per-layer results into a stable status dict for API responses.

    Input maps layer -> None (not started) or a result dict with at least a
    numeric ``score``. Missing/partial layers never raise; they degrade to
    ``not_started`` so a partial assessment cannot break the skill profile.
    """
    summary: Dict[str, dict] = {}
    for layer in LAYERS:
        result = (layer_results or {}).get(layer)
        if not isinstance(result, dict):
            summary[layer] = {"status": "not_started", "score": None}
            continue
        score = result.get("score")
        try:
            score_f = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_f = None
        status = str(result.get("status") or ("completed" if score_f is not None else "not_started"))
        summary[layer] = {
            "status": status,
            "score": round(score_f, 4) if score_f is not None else None,
        }
        # Pass through a small allowlist of display fields when present.
        for extra in ("completed_at", "attempt_id", "session_id", "validity"):
            if result.get(extra) is not None:
                summary[layer][extra] = result[extra]
    return summary
