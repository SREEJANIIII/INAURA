from typing import List, Dict, Tuple, Optional
import math

from .evidence_weights import (
    SOURCE_RELIABILITY,
    DEFAULT_RELIABILITY,
    validation_strength as signals_validation_strength,
)

# Heuristic weights and calibration constants — prototype engine
# ASSUMPTION DOCUMENTATION:
# 1. Source Reliability (0.0 - 1.0): Weight reflecting institutional / platform credibility.
#    The single source of truth now lives in evidence_weights.SOURCE_RELIABILITY
#    (re-exported here for backward compatibility). Hierarchy: INAURA assessment
#    (0.95) > coding platforms (0.85) and verified coursework (0.80) >
#    project/GitHub artifact evidence (0.62/0.60) and certifications (0.55) >
#    self-reported resume/LinkedIn (0.50/0.40).
# 2. Confidence Calibration:
#    Confidence evaluates trustworthiness of an estimate using evidence volume,
#    source diversity, and — when supplied — how *directly* the strongest source
#    demonstrates the person's own ability (see `confidence`).
#    Saturation points: 2.5 total reliability weight and 3 distinct source types.
# 3. Career Readiness:
#    Readiness synthesizes skill proficiency alignment (45%), industry gap coverage (25%), and evidence confidence (30%).
# NOTE: These values are heuristic estimates for prototype career guidance, not scientifically validated psychometrics.

# Confidence model weights and saturation ceilings.
# Two-term (legacy) form, used when no validation strength is supplied:
CONFIDENCE_W_WEIGHT = 0.55
CONFIDENCE_D_WEIGHT = 0.45
CONFIDENCE_W_NORM = 2.5   # Volume saturation: sum of source reliabilities >= 2.5 reaches 1.0
CONFIDENCE_D_NORM = 3.0   # Diversity saturation: >= 3 distinct source types reaches 1.0

# Three-term form, used when the caller can supply validation strength
# (how directly the evidence demonstrates the person's own current ability).
# Same architecture — normalized components combined by fixed weights — with
# volume and diversity re-scaled proportionally to make room for the new term.
CONFIDENCE_VOL_WEIGHT = 0.40
CONFIDENCE_DIV_WEIGHT = 0.25
CONFIDENCE_VAL_WEIGHT = 0.35

# Readiness component weighting
READINESS_WEIGHTS: Dict[str, float] = {
    "skill": 0.45,
    "industry": 0.25,
    "evidence": 0.30,
}

ENGINE_VERSION = "4C-v1"


def clamp01(v: float) -> float:
    """Clamp float value to [0.0, 1.0]."""
    if v is None or math.isnan(v):
        return 0.0
    return max(0.0, min(1.0, float(v)))


def proficiency(signals: List[dict]) -> Tuple[float, float, int, float]:
    """
    Calculate proficiency for a single skill from its evidence signals.
    Formula: Weighted average = Σ(signal_strength × source_reliability) / Σ(source_reliability)

    Separation of Concepts:
    - signal_strength: depth to which evidence demonstrates the skill (0.30 tech list vs 0.75 strong implementation)
    - source_reliability: reliability of the source used as weighting factor (0.90 project vs 0.50 resume)
    - proficiency: resulting estimated demonstrated skill level [0.0, 1.0]

    Returns:
      (proficiency [0-1], total_evidence_weight, evidence_count, average_unweighted_signal)
    """
    if not signals:
        return 0.0, 0.0, 0, 0.0

    total_weight = 0.0
    weighted_sum = 0.0
    raw_signal_sum = 0.0

    for s in signals:
        # Support both 'signal_strength' and 'signal_value'
        val = float(s.get("signal_strength", s.get("signal_value", 0.0)))
        # Support both 'source_reliability' and fallback lookup
        rel = float(s.get("source_reliability", SOURCE_RELIABILITY.get(s.get("source", s.get("source_type", "")), DEFAULT_RELIABILITY)))
        rel = clamp01(rel)
        val = clamp01(val)

        total_weight += rel
        weighted_sum += val * rel
        raw_signal_sum += val

    if total_weight <= 0.0:
        return 0.0, 0.0, len(signals), 0.0

    prof = weighted_sum / total_weight
    avg_sig = raw_signal_sum / len(signals)
    return clamp01(prof), total_weight, len(signals), clamp01(avg_sig)


def confidence(
    evidence_weight: float,
    source_diversity: int,
    validation_strength: Optional[float] = None,
) -> Tuple[float, float, float]:
    """
    Calculate confidence in the skill estimate.
    Confidence answers: 'How certain is INAURA that this estimate is well-supported?'

    Two forms of the same architecture (normalized components × fixed weights):

    1. Legacy two-term form (validation_strength omitted) — unchanged:
         Confidence = 0.55 × min(1, W / 2.5) + 0.45 × min(1, D / 3)

    2. Three-term form (validation_strength supplied):
         Confidence = 0.40 × min(1, W / 2.5)
                    + 0.25 × min(1, D / 3)
                    + 0.35 × V
       where V is how directly the strongest evidence demonstrates the person's
       own current ability (evidence_weights.validation_strength). Artifact
       evidence such as an inspected repository scores low on V, so a portfolio
       of repositories can no longer produce high confidence on its own; a
       graded INAURA assessment scores high on V and raises confidence sharply.

      W = evidence_weight (sum of source reliabilities)
      D = source_diversity (number of distinct source types)

    Returns:
      (confidence [0-1], volume_normalized [0-1], diversity_normalized [0-1])
    """
    if evidence_weight <= 0.0 or source_diversity <= 0:
        return 0.0, 0.0, 0.0

    w_norm = min(1.0, max(0.0, evidence_weight / CONFIDENCE_W_NORM))
    d_norm = min(1.0, max(0.0, float(source_diversity) / CONFIDENCE_D_NORM))

    if validation_strength is None:
        conf = CONFIDENCE_W_WEIGHT * w_norm + CONFIDENCE_D_WEIGHT * d_norm
    else:
        v_norm = clamp01(validation_strength)
        conf = (
            CONFIDENCE_VOL_WEIGHT * w_norm
            + CONFIDENCE_DIV_WEIGHT * d_norm
            + CONFIDENCE_VAL_WEIGHT * v_norm
        )
    return clamp01(conf), w_norm, d_norm


def confidence_from_signals(signals: List[dict]) -> Tuple[float, float, float, float]:
    """
    Confidence for a skill computed directly from its evidence signals.

    Derives the three inputs of the extended confidence model from the signals
    themselves: total reliability weight, distinct source types, and validation
    strength (directness × signal strength of the strongest direct evidence).

    Returns:
      (confidence, evidence_weight, source_diversity, validation_strength)
    """
    if not signals:
        return 0.0, 0.0, 0.0, 0.0

    _, ev_weight, _, _ = proficiency(signals)
    diversity = len({str(s.get("source", s.get("source_type", ""))) for s in signals})
    val = signals_validation_strength(signals)
    conf, _, _ = confidence(ev_weight, diversity, validation_strength=val)
    return conf, ev_weight, float(diversity), val


def gap(current_proficiency: float, required_level: float) -> float:
    """
    Calculate skill gap.
    Gap = max(0, required_level - current_proficiency)
    Always in [0.0, 1.0].
    """
    cur = clamp01(current_proficiency)
    req = clamp01(required_level)
    return clamp01(max(0.0, req - cur))


# Gap Category Thresholds
GAP_CATEGORY_THRESHOLDS: Dict[str, float] = {
    "critical": 40.0,
    "high": 25.0,
    "medium": 10.0,
    "low": 0.0,
}

# Skill Quadrant Thresholds
QUADRANT_PROFICIENCY_THRESHOLD = 0.60
QUADRANT_CONFIDENCE_THRESHOLD = 0.50


def gap_priority(
    gap_val: float,
    importance: float,
    demand: float,
    confidence_val: float,
    interview_relevance: float,
) -> float:
    """
    Calculate gap priority score (0 to 100).
    Formula: Priority = 100 × gap × importance × demand × confidence × interview_relevance

    Multiplying by confidence makes the priority conservative when evidence is weak,
    ensuring unconfirmed assertions do not falsely dominate student roadmap ranking.
    Kept for backward compatibility.
    """
    g = clamp01(gap_val)
    imp = clamp01(importance)
    dem = clamp01(demand)
    conf = clamp01(confidence_val)
    ir = clamp01(interview_relevance)
    raw = 100.0 * g * imp * dem * conf * ir
    return max(0.0, min(100.0, raw))


def calculate_prioritized_gap(
    gap_val: float,
    importance: float,
    demand: float,
    student_confidence: float,
    interview_relevance: float,
    industry_confidence: float = 0.85,
    gap_type: str = "skill_gap",
) -> Tuple[float, str, Dict[str, float]]:
    """
    Multi-factor Prioritized Gap Calculation for the Gap Analysis Engine.
    
    Prioritization criteria:
    1. Gap size (required_level - current_proficiency)
    2. Role importance (essential vs elective skills)
    3. Interview relevance (technical screening weight)
    4. Industry market demand
    5. Evidence certainty (student confidence)
    6. Industry benchmark confidence
    
    Ensures high-importance, interview-critical requirements outrank large gaps in low-importance electives.
    For unverified required skills (evidence gaps), uses a calibrated certainty factor so essential
    missing skills are prioritized rather than suppressed to zero.

    Returns:
      (priority_score [0-100], priority_category ['critical','high','medium','low','covered'], breakdown)
    """
    g = clamp01(gap_val)
    if g <= 1e-9:
        return (
            0.0,
            "covered",
            {
                "gap": 0.0,
                "impact_factor": 0.0,
                "base_score": 0.0,
                "certainty_weight": 1.0,
            },
        )

    imp = clamp01(importance)
    dem = clamp01(demand)
    ir = clamp01(interview_relevance)
    ind_conf = clamp01(industry_confidence)
    s_conf = clamp01(student_confidence)

    # Core Impact Factor combining role importance, interview weight, demand, and industry confidence
    impact_factor = (
        0.35 * imp
        + 0.35 * ir
        + 0.15 * dem
        + 0.15 * ind_conf
    )

    # Base Score blending gap magnitude (40%) and role impact (60%)
    base_score = 100.0 * (0.40 * g + 0.60 * impact_factor)

    # Certainty Weight adjustment
    if gap_type == "evidence_gap":
        # Missing evidence for a role requirement demands urgent attention
        certainty_weight = 0.70
    else:
        # For demonstrated skills, confidence slightly scales certainty
        certainty_weight = 0.65 + 0.35 * s_conf

    raw_priority = base_score * certainty_weight
    priority_score = round(max(0.0, min(100.0, raw_priority)), 2)

    # Category classification
    if priority_score >= GAP_CATEGORY_THRESHOLDS["critical"]:
        category = "critical"
    elif priority_score >= GAP_CATEGORY_THRESHOLDS["high"]:
        category = "high"
    elif priority_score >= GAP_CATEGORY_THRESHOLDS["medium"]:
        category = "medium"
    elif priority_score > 0.0:
        category = "low"
    else:
        category = "covered"

    breakdown = {
        "gap": round(g, 4),
        "impact_factor": round(impact_factor, 4),
        "base_score": round(base_score, 2),
        "certainty_weight": round(certainty_weight, 4),
    }

    return priority_score, category, breakdown


def classify_skill_quadrant(proficiency_val: float, confidence_val: float) -> Tuple[str, str, str]:
    """
    Classifies a skill into one of four confidence-aware quadrants:
    1. strong_validated: High Proficiency + High Confidence
    2. unverified_claim: High Proficiency + Low Confidence
    3. confirmed_gap:    Low Proficiency + High Confidence
    4. exploratory:       Low Proficiency + Low Confidence

    Returns:
      (quadrant_key, display_title, human_guidance)
    """
    p = clamp01(proficiency_val)
    c = clamp01(confidence_val)

    if p >= QUADRANT_PROFICIENCY_THRESHOLD and c >= QUADRANT_CONFIDENCE_THRESHOLD:
        return (
            "strong_validated",
            "Strong & Validated",
            "Demonstrated high proficiency with robust independent evidence. Focus on showcasing in interviews.",
        )
    elif p >= QUADRANT_PROFICIENCY_THRESHOLD and c < QUADRANT_CONFIDENCE_THRESHOLD:
        return (
            "unverified_claim",
            "Unverified Claim / Emergent",
            "High claimed or estimated proficiency, but lacking sufficient independent verification. Provide code repos or certifications.",
        )
    elif p < QUADRANT_PROFICIENCY_THRESHOLD and c >= QUADRANT_CONFIDENCE_THRESHOLD:
        return (
            "confirmed_gap",
            "Confirmed Development Need",
            "Well-supported evidence shows current proficiency is below benchmark. Prioritize focused deliberate practice.",
        )
    else:
        return (
            "exploratory",
            "Exploratory / Unclear",
            "Insufficient evidence to make a definitive assessment; submit projects or platform profiles.",
        )


def explain_evidence_gap(
    skill: str,
    required_level: float,
    importance: float,
    actionable_advice: Optional[str] = None,
) -> str:
    """
    Human-readable explanation of an evidence gap.
    Communicates 'insufficient evidence' NOT 'you don't know X'.
    """
    req_pct = int(round(clamp01(required_level) * 100))
    imp_pct = int(round(clamp01(importance) * 100))
    advice = actionable_advice or f"Submit a GitHub project, coding profile, or certification demonstrating {skill}."
    return (
        f"No evidence found for {skill}. INAURA has not found enough reliable independent evidence to "
        f"confidently evaluate your proficiency. Target role expects {req_pct}% (role importance: {imp_pct}%). "
        f"Note: This indicates absence of submitted evidence, not confirmed inability. Next step: {advice}"
    )



def explain_coverage_gap(
    pillar: str,
    solved: int,
    status: str,
    actionable_advice: Optional[str] = None,
) -> str:
    """
    Human-readable explanation of a domain pillar coverage gap (e.g. DSA topic).
    """
    advice = actionable_advice or f"Solve 5-10 fundamental problems in {pillar} to demonstrate conceptual fluency."
    if status == "missing" or solved == 0:
        return (
            f"Zero verified problems solved in {pillar}. Technical interviews for engineering roles "
            f"frequently test this pillar. Next step: {advice}"
        )
    return (
        f"Only {solved} problem(s) solved in {pillar} (status: {status}). "
        f"Deeper practice across medium-difficulty patterns is recommended. Next step: {advice}"
    )



def readiness(
    skill_component: float,
    industry_component: float,
    evidence_component: float,
) -> float:
    """
    Calculate overall career readiness score [0.0, 1.0].
    Career Readiness = 0.45 × skill + 0.25 × industry + 0.30 × evidence

    - skill_component: Weighted proficiency across target role requirements
    - industry_component: 1 - average weighted gap across industry requirements
    - evidence_component: Average confidence across assessed skills
    """
    sc = clamp01(skill_component)
    ic = clamp01(industry_component)
    ec = clamp01(evidence_component)
    r = (
        READINESS_WEIGHTS["skill"] * sc
        + READINESS_WEIGHTS["industry"] * ic
        + READINESS_WEIGHTS["evidence"] * ec
    )
    return clamp01(r)


def aggregate_skill_component(assessments: List[dict], requirements: List[dict]) -> float:
    """
    Skill component: weighted average of student proficiency across required skills,
    weighted by skill importance in the target role.
    """
    if not requirements:
        return 0.0

    # Build proficiency lookup using canonical names
    prof_map: Dict[str, float] = {}
    for a in assessments:
        name = a.get("canonical_name", a.get("skill", ""))
        prof_map[name.lower()] = float(a.get("proficiency", 0.0))
        prof_map[name.lower().replace("_", " ")] = float(a.get("proficiency", 0.0))

    total_weight = 0.0
    weighted_sum = 0.0

    for req in requirements:
        skill_name = req.get("skill", "")
        # Lookup proficiency
        prof = prof_map.get(skill_name.lower(), prof_map.get(skill_name.lower().replace("_", " "), 0.0))
        imp = clamp01(float(req.get("importance", 0.5)))
        total_weight += imp
        weighted_sum += prof * imp

    if total_weight <= 0.0:
        return 0.0
    return clamp01(weighted_sum / total_weight)


def aggregate_industry_component(gaps: List[dict]) -> float:
    """
    Industry component: alignment with role requirements:
    1.0 - (average gap weighted by importance).
    If no gaps exist, returns 1.0 (fully aligned).
    """
    if not gaps:
        return 0.0
    total_imp = sum(float(g.get("importance", 0.5)) for g in gaps)
    if total_imp <= 0.0:
        return 0.0
    weighted_gap = sum(float(g.get("gap", 0.0)) * float(g.get("importance", 0.5)) for g in gaps) / total_imp
    return clamp01(1.0 - weighted_gap)


def aggregate_evidence_component(assessments: List[dict]) -> float:
    """
    Evidence component: average confidence score across all assessed skills.
    Reflects the breadth and depth of verification supporting the student profile.
    """
    if not assessments:
        return 0.0
    avg_conf = sum(float(a.get("confidence", 0.0)) for a in assessments) / len(assessments)
    return clamp01(avg_conf)


def explain_proficiency(
    proficiency_val: float,
    confidence_val: float,
    evidence_count: int,
    source_diversity: int,
    signals: Optional[List[dict]] = None,
    skill_name: Optional[str] = None,
) -> str:
    """
    Human-readable explanation of proficiency and confidence for a skill.
    Explains the evidence sources, signal depth, and reasons for the confidence rating.
    """
    name = skill_name or "This skill"
    prof_pct = int(round(proficiency_val * 100))
    conf_pct = int(round(confidence_val * 100))

    # Case 1: No evidence found
    if evidence_count == 0 or not signals:
        return (
            f"No evidence submitted for {name}. Assessed at 0% demonstrated proficiency "
            f"with 0% confidence. Note: This indicates absence of submitted evidence, "
            f"not verified inability."
        )

    # Build evidence breakdown
    evidence_summaries: List[str] = []
    for s in signals:
        src = s.get("source", s.get("source_type", "evidence"))
        reason = s.get("reason", s.get("explanation", ""))
        val = float(s.get("signal_strength", s.get("signal_value", 0.5)))
        strength_desc = "strong" if val >= 0.70 else ("moderate" if val >= 0.50 else "weak")
        if reason:
            evidence_summaries.append(f"{src} ({strength_desc} signal: {reason})")
        else:
            evidence_summaries.append(f"{src} ({strength_desc} signal: {int(val*100)}%)")

    evidence_text = "; ".join(evidence_summaries[:3])

    # Confidence justification
    if confidence_val < 0.40:
        conf_reason = f"Confidence is low ({conf_pct}%) because evidence is limited to {evidence_count} signal(s) from {source_diversity} source type(s). Providing diverse evidence would increase confidence."
    elif confidence_val < 0.70:
        conf_reason = f"Confidence is moderate ({conf_pct}%) because evidence comes from {evidence_count} signal(s) across {source_diversity} distinct source type(s)."
    else:
        conf_reason = f"Confidence is high ({conf_pct}%) supported by extensive verification across {source_diversity} distinct source types."

    return f"Estimated proficiency {prof_pct}%. Evidence: {evidence_text}. {conf_reason}"


def explain_gap(
    skill: str,
    current: float,
    required: float,
    gap_val: float,
    importance: float,
    confidence_val: float,
    evidence_count: int = 1,
) -> str:
    """
    Human-readable explanation of a skill gap.
    Distinguishes clearly between 'no evidence provided' vs 'demonstrated deficit'.
    """
    current_pct = int(round(current * 100))
    required_pct = int(round(required * 100))
    gap_pct = int(round(gap_val * 100))
    conf_pct = int(round(confidence_val * 100))

    if evidence_count == 0 or (current == 0.0 and confidence_val == 0.0):
        return (
            f"No evidence found for {skill} (target requirement: {required_pct}%). "
            f"Gap is {gap_pct}%. Note: This indicates lack of submitted evidence, "
            f"not confirmed inability."
        )

    if gap_val <= 0.0:
        return f"{skill} is covered (current demonstrated {current_pct}% meets or exceeds required {required_pct}%)."

    if gap_val < 0.20:
        return f"{skill} needs incremental improvement — current {current_pct}%, required {required_pct}%, gap {gap_pct}%. Confidence is {conf_pct}%."

    return (
        f"{skill} has a priority gap — current {current_pct}%, required {required_pct}%, gap {gap_pct}%. "
        f"Role importance ({importance:.2f}) and evidence confidence ({conf_pct}%) determine priority."
    )


def explain_readiness(
    skill_c: float,
    industry_c: float,
    evidence_c: float,
    readiness_val: float,
) -> str:
    """Explain career readiness breakdown."""
    r_pct = int(round(readiness_val * 100))
    s_pct = int(round(skill_c * 100))
    i_pct = int(round(industry_c * 100))
    e_pct = int(round(evidence_c * 100))
    return (
        f"Career readiness {r_pct}% = 0.45×skill ({s_pct}%) + 0.25×industry ({i_pct}%) + 0.30×evidence ({e_pct}%). "
        "Heuristic prototype weights (0.45 / 0.25 / 0.30) synthesize skill coverage, industry alignment, and evidence confidence."
    )
