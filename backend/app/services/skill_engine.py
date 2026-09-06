from typing import List, Dict, Tuple
import math

# Configurable heuristic weights — Phase 4C prototype, not validated
SOURCE_RELIABILITY = {
    "github": 0.90,
    "project": 0.90,
    "leetcode": 0.85,
    "codeforces": 0.85,
    "kaggle": 0.85,
    "syllabus": 0.80,
    "certification": 0.65,
    "resume": 0.50,
    "linkedin": 0.40,
    "self_declared": 0.30,
}

CONFIDENCE_W_WEIGHT = 0.55
CONFIDENCE_D_WEIGHT = 0.45
CONFIDENCE_W_NORM = 2.5
CONFIDENCE_D_NORM = 3.0

READINESS_WEIGHTS = {
    "skill": 0.45,
    "industry": 0.25,
    "evidence": 0.30,
}

ENGINE_VERSION = "4C-v1"


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def proficiency(signals: List[dict]) -> Tuple[float, float, int, float]:
    """
    Calculate proficiency for a single skill from its signals.
    signals: list of {signal_value 0-1, source_reliability 0-1}
    Returns (proficiency 0-1, evidence_weight sum, evidence_count, avg_signal)
    Formula: Σ(weight × signal) / Σ(weight)
    weight = source_reliability
    """
    if not signals:
        return 0.0, 0.0, 0, 0.0
    total_weight = sum(s["source_reliability"] for s in signals)
    if total_weight == 0:
        return 0.0, 0.0, len(signals), 0.0
    weighted_sum = sum(s["signal_value"] * s["source_reliability"] for s in signals)
    prof = weighted_sum / total_weight
    avg_sig = sum(s["signal_value"] for s in signals) / len(signals)
    return clamp01(prof), total_weight, len(signals), clamp01(avg_sig)


def confidence(evidence_weight: float, source_diversity: int) -> Tuple[float, float, float]:
    """
    Confidence = 0.55*min(1, W/2.5) + 0.45*min(1, D/3)
    W = evidence_weight (sum of reliabilities) or evidence volume/strength
    D = source diversity (distinct source types)
    Returns (confidence 0-1, W_norm, D_norm)
    """
    w_norm = min(1.0, evidence_weight / CONFIDENCE_W_NORM)
    d_norm = min(1.0, source_diversity / CONFIDENCE_D_NORM)
    conf = CONFIDENCE_W_WEIGHT * w_norm + CONFIDENCE_D_WEIGHT * d_norm
    return clamp01(conf), w_norm, d_norm


def gap(current_proficiency: float, required_level: float) -> float:
    """
    Gap = max(0, required - current)
    """
    return clamp01(max(0.0, required_level - current_proficiency))


def gap_priority(
    gap_val: float,
    importance: float,
    demand: float,
    confidence_val: float,
    interview_relevance: float,
) -> float:
    """
    Gap Priority = 100 * gap * importance * demand * confidence * interview
    All 0-1, result 0-100
    Multiplying by confidence makes it conservative when evidence weak.
    """
    raw = 100.0 * gap_val * importance * demand * confidence_val * interview_relevance
    return max(0.0, min(100.0, raw))


def readiness(
    skill_component: float, industry_component: float, evidence_component: float
) -> float:
    """
    Career Readiness = 0.45*skill + 0.25*industry + 0.30*evidence
    All 0-1, result 0-1
    skill: overall alignment of current skills with target requirements
    industry: alignment with industry requirements (e.g., avg coverage)
    evidence: strength/confidence of available evidence
    """
    r = (
        READINESS_WEIGHTS["skill"] * skill_component
        + READINESS_WEIGHTS["industry"] * industry_component
        + READINESS_WEIGHTS["evidence"] * evidence_component
    )
    return clamp01(r)


def aggregate_skill_component(assessments: List[dict], requirements: List[dict]) -> float:
    """
    Skill component: weighted average of proficiency across required skills,
    weighted by importance. If no requirements, 0.
    """
    if not requirements:
        return 0.0
    # Map skill -> proficiency
    prof_map = {a["canonical_name"]: a["proficiency"] for a in assessments}
    total_weight = 0.0
    weighted_sum = 0.0
    for req in requirements:
        skill = req.get("skill")
        # Normalize skill name to canonical for matching? For now assume display_name matches canonical after lower
        # Try to find matching assessment
        # We need to map requirement skill to canonical via lower
        found = None
        for k, v in prof_map.items():
            if k.lower() == skill.lower() or k.lower().replace("_", " ") == skill.lower():
                found = v
                break
        prof = found if found is not None else 0.0
        imp = float(req.get("importance", 0.5))
        total_weight += imp
        weighted_sum += prof * imp
    if total_weight == 0:
        return 0.0
    return clamp01(weighted_sum / total_weight)


def aggregate_industry_component(gaps: List[dict]) -> float:
    """
    Industry component: alignment with industry — 1 - avg gap weighted by importance
    If no gaps, 1 (fully aligned)
    """
    if not gaps:
        return 0.0
    total_imp = sum(g["importance"] for g in gaps)
    if total_imp == 0:
        return 0.0
    weighted_gap = sum(g["gap"] * g["importance"] for g in gaps) / total_imp
    return clamp01(1.0 - weighted_gap)


def aggregate_evidence_component(assessments: List[dict]) -> float:
    """
    Evidence component: avg confidence across assessed skills
    """
    if not assessments:
        return 0.0
    avg_conf = sum(a["confidence"] for a in assessments) / len(assessments)
    return clamp01(avg_conf)


def explain_proficiency(
    proficiency: float, confidence: float, evidence_count: int, source_diversity: int
) -> str:
    if evidence_count == 0:
        return "Insufficient evidence to confidently assess this skill. No supporting evidence was found."
    if confidence < 0.4:
        return f"Estimated proficiency {proficiency*100:.0f}% with low confidence ({confidence*100:.0f}%) — based on limited evidence from {evidence_count} source(s) across {source_diversity} type(s). More diverse evidence would increase confidence."
    if confidence < 0.7:
        return f"Estimated proficiency {proficiency*100:.0f}% with moderate confidence ({confidence*100:.0f}%) — supported by {evidence_count} evidence signal(s) across {source_diversity} source type(s)."
    return f"Estimated proficiency {proficiency*100:.0f}% with high confidence ({confidence*100:.0f}%) — supported by {evidence_count} signals across {source_diversity} distinct source types."


def explain_gap(
    skill: str, current: float, required: float, gap_val: float, importance: float, confidence_val: float
) -> str:
    if gap_val == 0:
        return f"{skill} is covered (current {current*100:.0f}% meets required {required*100:.0f}%)."
    if gap_val < 0.2:
        return f"{skill} needs improvement — current {current*100:.0f}%, required {required*100:.0f}%, gap {gap_val*100:.0f}%. Confidence {confidence_val*100:.0f}%."
    return f"{skill} has a priority gap — current {current*100:.0f}%, required {required*100:.0f}%, gap {gap_val*100:.0f}%. Importance {importance:.2f} and confidence {confidence_val*100:.0f}% drive priority."


def explain_readiness(skill_c: float, industry_c: float, evidence_c: float, readiness: float) -> str:
    return (
        f"Career readiness {readiness*100:.0f}% = 0.45×skill {skill_c*100:.0f}% + 0.25×industry {industry_c*100:.0f}% + 0.30×evidence {evidence_c*100:.0f}%. "
        "Heuristic prototype weights (0.45/0.25/0.30) — not scientifically validated, based on available evidence."
    )
