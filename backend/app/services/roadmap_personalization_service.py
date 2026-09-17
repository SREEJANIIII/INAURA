"""
Roadmap Personalization Service.

Provides evidence-traceable, deterministic personalization for every skill gap in the roadmap:
1. What the user already demonstrates (grounded in actual repository files, commit patterns, LeetCode topics, assessments).
2. What the user does not demonstrate (unobserved capabilities from curated blueprints and taxonomy tiers).
3. How confident INAURA is about that conclusion (with calibrated rationale).
4. What evidence supports the conclusion (traceable provenance).
5. What prerequisite knowledge is required (DAG resolution).
6. What the target role requires (proficiency benchmark, importance).
7. How important the skill is for the target role (criticality, demand, interview relevance).
8. How much time the user has (weekly capacity and pacing).
9. What the smallest useful learning unit is (time-boxed module targeting missing capabilities).
10. How the skill should be validated (concrete deliverable and verifiable proof criteria).

Answers the 5 Fundamental Learner Questions:
- "Why am I learning this?"
- "Why now?"
- "Why this much time?"
- "Why this resource?"
- "How will INAURA know that I learned it?"

Deterministic — no random LLM output. Traceable directly to evidence.
"""

from typing import Dict, List, Optional, Any, Tuple
import math
import logging

from .skill_taxonomy import normalize_skill, normalize_skill_slug
from .capability_map import (
    CAPABILITY_BLUEPRINTS,
    evaluate_capability,
    _rule_matches,
    _signal_source,
    _signal_depth,
    _signal_files,
    _signal_patterns,
    STATUS_DEMONSTRATED,
    STATUS_DEVELOPING,
    STATUS_UNVERIFIED,
    STATUS_CONFIRMED_GAP,
    DEMONSTRATED_SUPPORT,
)
from . import skill_dependencies

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fallback taxonomy tiers for skills without a pre-authored blueprint
# ---------------------------------------------------------------------------

DEFAULT_SKILL_TIERS: Dict[str, List[Dict[str, Any]]] = {
    "core": [
        {"title": "Core Syntax & Foundations", "ability": "Core syntax, data types, and standard library fundamentals"},
        {"title": "Applied Usage & Idiomatic Patterns", "ability": "Practical application, modular organization, and common patterns"},
        {"title": "Production Architecture & Optimization", "ability": "Error handling, configuration, concurrency, and performance tuning"},
        {"title": "Testing, Tooling & Verification", "ability": "Automated testing, edge-case coverage, and production validation"},
    ],
    "database": [
        {"title": "Data Querying & Filtering", "ability": "SELECT queries, filtering, aggregation, and relational joins"},
        {"title": "Schema Design & Migrations", "ability": "Relational schema design, constraints, and safe migrations"},
        {"title": "Performance Tuning & Indexes", "ability": "Query planning, indexing strategies, and execution optimization"},
        {"title": "Transactions & Data Integrity", "ability": "ACID guarantees, transaction boundaries, and rollback handling"},
    ],
    "devops": [
        {"title": "Containerization & Environment Configuration", "ability": "Dockerfiles, multi-stage builds, and environment isolation"},
        {"title": "Networking & Storage Orchestration", "ability": "Volume mounting, port mapping, and container networking"},
        {"title": "Deployment & CI/CD Pipelines", "ability": "Automated build/test workflows and release deployment"},
        {"title": "Monitoring, Health Checks & Reliability", "ability": "Health check probes, log aggregation, and failure recovery"},
    ],
    "ai_ml": [
        {"title": "Data Preprocessing & Feature Engineering", "ability": "Data cleaning, feature scaling, encoding, and exploratory analysis"},
        {"title": "Model Training & Baseline Evaluation", "ability": "Training standard models, loss metrics, and train/val splits"},
        {"title": "Hyperparameter Tuning & Cross-Validation", "ability": "Regularization, grid search, and generalization verification"},
        {"title": "Production Inference & Serving", "ability": "Model serialization, REST inference endpoints, and drift monitoring"},
    ],
}


def _get_skill_category_group(skill_name: str, category: str = "") -> str:
    """Classify skill into default tier family if no custom blueprint exists."""
    cat_lower = (category or "").lower()
    s_lower = skill_name.lower().replace(" ", "_")
    if "database" in cat_lower or any(k in s_lower for k in ("sql", "postgres", "mongo", "redis", "db")):
        return "database"
    if "devops" in cat_lower or "cloud" in cat_lower or any(k in s_lower for k in ("docker", "k8s", "kubernetes", "aws", "ci_cd", "linux")):
        return "devops"
    if "ai" in cat_lower or "ml" in cat_lower or any(k in s_lower for k in ("machine_learning", "deep_learning", "pytorch", "tensorflow", "nlp", "llm")):
        return "ai_ml"
    return "core"


def analyze_skill_capabilities_from_evidence(
    skill_canonical: str,
    grouped_signals: Dict[str, List[dict]],
) -> Tuple[List[str], List[str], List[str]]:
    """
    Extract:
    1. demonstrated_capabilities (observable abilities verified by evidence)
    2. missing_capabilities (unobserved abilities required for mastery)
    3. supporting_evidence (traceable provenance strings)
    """
    canon_display = normalize_skill(skill_canonical) or skill_canonical
    slug = normalize_skill_slug(skill_canonical) or skill_canonical.lower().replace(" ", "_")

    # Match signals for this skill
    skill_signals = grouped_signals.get(canon_display, [])
    if not skill_signals:
        for k, sigs in grouped_signals.items():
            if normalize_skill_slug(k) == slug:
                skill_signals = sigs
                break

    # Build traceable supporting evidence list
    supporting_evidence: List[str] = []
    seen_evidence = set()
    for sig in skill_signals:
        src = _signal_source(sig)
        meta = sig.get("metadata") or {}
        repo = meta.get("project_name") or meta.get("full_name") or meta.get("repo") or ""
        files = _signal_files(sig)
        patterns = _signal_patterns(sig)
        
        entry = ""
        if src == "github":
            if repo:
                files_str = f" (files: {', '.join(files[:3])})" if files else ""
                entry = f"GitHub repository '{repo}'{files_str}"
            elif files:
                entry = f"GitHub code files: {', '.join(files[:3])}"
            else:
                entry = "GitHub repository implementation"
            if patterns:
                entry += f" with patterns: {', '.join(patterns[:3])}"
        elif src in ("leetcode", "codeforces"):
            topics = meta.get("topics") or []
            cnt = meta.get("solved_count") or meta.get("count") or ""
            topic_str = f" on {', '.join(topics[:3])}" if topics else ""
            entry = f"{src.capitalize()} problem solving{topic_str}{f' ({cnt} solved)' if cnt else ''}"
        elif src == "project":
            pname = meta.get("project_name") or "Portfolio Project"
            entry = f"Project: {pname}"
        elif src == "assessment":
            score = sig.get("signal_strength") or sig.get("signal_value") or 0
            entry = f"INAURA skill assessment ({int(score * 100)}% score)"
        elif src == "certification":
            cname = meta.get("cert_name") or "Industry Certification"
            entry = f"Certification: {cname}"
        elif src == "resume":
            entry = "Verified resume project extraction"

        if entry and entry not in seen_evidence:
            seen_evidence.add(entry)
            supporting_evidence.append(entry)

    # 1. Check if skill has a curated blueprint
    blueprint = CAPABILITY_BLUEPRINTS.get(slug)
    if not blueprint:
        for k, b in CAPABILITY_BLUEPRINTS.items():
            if normalize_skill_slug(k) == slug:
                blueprint = b
                break

    demonstrated_capabilities: List[str] = []
    missing_capabilities: List[str] = []

    if blueprint:
        for cap in blueprint:
            eval_result = evaluate_capability(cap, grouped_signals)
            support = eval_result.get("support", 0.0)
            abilities = cap.get("observable_abilities") or [cap.get("title")]

            if support >= DEMONSTRATED_SUPPORT:
                for ab in abilities:
                    if ab not in demonstrated_capabilities:
                        demonstrated_capabilities.append(ab)
            else:
                for ab in abilities:
                    if ab not in missing_capabilities and ab not in demonstrated_capabilities:
                        missing_capabilities.append(ab)

        # In case some capabilities matched partially
        if not demonstrated_capabilities and supporting_evidence:
            # If student has depth >= 3 signals but didn't match strict rules, credit first blueprint tier
            if any(_signal_depth(s) >= 3 for s in skill_signals):
                first_cap = blueprint[0]
                first_abs = first_cap.get("observable_abilities") or [first_cap.get("title")]
                for ab in first_abs:
                    demonstrated_capabilities.append(ab)
                    if ab in missing_capabilities:
                        missing_capabilities.remove(ab)

    else:
        # 2. Generalized taxonomy evaluation for skills without a static blueprint
        group_key = _get_skill_category_group(skill_canonical)
        tiers = DEFAULT_SKILL_TIERS.get(group_key, DEFAULT_SKILL_TIERS["core"])
        max_depth = max([_signal_depth(s) for s in skill_signals], default=0)

        if max_depth >= 4:
            # Demonstrated syntax, applied usage, and modular organization
            demonstrated_capabilities.extend([tiers[0]["ability"], tiers[1]["ability"]])
            missing_capabilities.extend([tiers[2]["ability"], tiers[3]["ability"]])
        elif max_depth >= 3:
            # Demonstrated core fundamentals
            demonstrated_capabilities.append(tiers[0]["ability"])
            missing_capabilities.extend([tiers[1]["ability"], tiers[2]["ability"], tiers[3]["ability"]])
        elif max_depth >= 1:
            # Developing/mention only
            missing_capabilities.extend([tiers[0]["ability"], tiers[1]["ability"], tiers[2]["ability"], tiers[3]["ability"]])
        else:
            # Zero evidence
            missing_capabilities.extend([tiers[0]["ability"], tiers[1]["ability"], tiers[2]["ability"], tiers[3]["ability"]])

    if not supporting_evidence:
        supporting_evidence.append("No active implementation evidence submitted in INAURA.")

    return demonstrated_capabilities, missing_capabilities, supporting_evidence


def build_skill_personalization(
    gap_dict: Dict[str, Any],
    target_role: str,
    user_hours_per_week: int,
    learner_states: Dict[str, Any],
    grouped_signals: Dict[str, List[dict]],
    skills_map: Dict[str, dict],
) -> Dict[str, Any]:
    """
    Build the full 10-point personalization & 5 Whys explanation for a skill gap.
    """
    skill_id = gap_dict.get("skill_id")
    s_info = skills_map.get(skill_id, {})
    canonical = (
        s_info.get("canonical_name")
        or gap_dict.get("skills", {}).get("canonical_name")
        or gap_dict.get("canonical_name")
        or "unknown"
    )
    display_name = (
        s_info.get("display_name")
        or gap_dict.get("skills", {}).get("display_name")
        or canonical.replace("_", " ").title()
    )
    slug = normalize_skill_slug(canonical) or canonical.lower().replace(" ", "_")

    current_prof = float(gap_dict.get("current_proficiency", 0.0))
    required_level = float(gap_dict.get("required_level", 0.75))
    gap_val = float(gap_dict.get("gap", max(0.0, required_level - current_prof)))
    importance = float(gap_dict.get("importance", 0.5))
    demand = float(gap_dict.get("demand", 0.5))
    interview = float(gap_dict.get("interview_relevance", 0.5))
    confidence = float(gap_dict.get("confidence", 0.0))
    priority_score = float(gap_dict.get("priority_score", 0.0))

    cur_pct = int(round(current_prof * 100))
    req_pct = int(round(required_level * 100))
    gap_pct = int(round(gap_val * 100))
    conf_pct = int(round(confidence * 100))
    imp_pct = int(round(importance * 100))
    dem_pct = int(round(demand * 100))
    int_pct = int(round(interview * 100))

    # 1, 2, 4. Analyze Capabilities & Supporting Evidence
    demonstrated, missing, evidence_list = analyze_skill_capabilities_from_evidence(
        skill_canonical=canonical,
        grouped_signals=grouped_signals,
    )

    # 3. Confidence Rationale
    if conf_pct >= 75:
        confidence_rationale = f"High confidence ({conf_pct}%) backed by direct implementation code and verified activity in your submissions."
    elif conf_pct >= 45:
        confidence_rationale = f"Moderate confidence ({conf_pct}%) based on repository presence; production patterns and edge-case testing remain unverified."
    else:
        confidence_rationale = f"Low confidence ({conf_pct}%) due to limited submitted artifacts. Initial tasks include hands-on diagnostic checks to calibrate your level."

    # 5. Prerequisite Analysis (DAG)
    prereqs = skill_dependencies.get_prerequisites(slug)
    prereq_details = []
    all_satisfied = True
    for p in prereqs:
        p_canon = normalize_skill(p) or p.title()
        p_state = learner_states.get(p)
        p_prof = p_state.proficiency if p_state else 0.0
        p_pct = int(round(p_prof * 100))
        if p_prof >= 0.70:
            prereq_details.append(f"{p_canon} (Satisfied: {p_pct}%)")
        else:
            all_satisfied = False
            prereq_details.append(f"{p_canon} (Developing: {p_pct}%)")

    if not prereqs:
        prerequisites_status = "No prerequisites required; direct entry allowed."
    elif all_satisfied:
        prerequisites_status = f"All prerequisites satisfied: {', '.join(prereq_details)}."
    else:
        prerequisites_status = f"Prerequisite dependencies scheduled ahead: {', '.join(prereq_details)}."

    # 8. Time Allocation & Pacing
    # Hours calculation matching roadmap catalog formula
    from .roadmap_catalog import get_base_hours
    base_hours = get_base_hours(canonical)
    allocated_hours = round(max(3.0, base_hours * (gap_val / 0.5) * (importance / 0.5)), 1)
    
    # Weekly pacing: how many hours/week over how many weeks
    weeks_span = max(1, math.ceil(allocated_hours / max(1.0, user_hours_per_week * 0.4)))
    pacing_per_week = round(allocated_hours / weeks_span, 1)
    weekly_pacing = f"~{pacing_per_week}h/week across {weeks_span} week{'s' if weeks_span > 1 else ''} ({user_hours_per_week}h/week budget)"

    # 9. Smallest Useful Learning Unit
    missing_focus = missing[0] if missing else f"production {display_name} patterns"
    smallest_learning_unit = f"90-minute module: Implement and verify {missing_focus.lower()}."

    # 10. How the skill should be validated
    validation_target = missing[0] if missing else display_name
    validation_criteria = (
        f"Deliver a working repository deliverable implementing {validation_target} "
        f"with automated test coverage (passing status), or achieve ≥80% on the {display_name} validation challenge."
    )

    # The 5 Whys
    why_learning = (
        f"{display_name} is a required competency for {target_role} ({imp_pct}% role importance, "
        f"{dem_pct}% market demand). Your assessed proficiency ({cur_pct}%) leaves a {gap_pct} percentage point "
        f"gap against the {req_pct}% industry benchmark."
    )
    
    if all_satisfied or not prereqs:
        why_now = (
            f"Ranked with priority score {int(round(priority_score))} based on gap magnitude and role criticality. "
            f"All prerequisite foundations are satisfied, making this the highest-leverage skill to master next."
        )
    else:
        why_now = (
            f"Ranked as a priority {int(round(priority_score))} core skill. Scheduled in alignment with prerequisite "
            f"dependencies ({', '.join(prereqs)}) so you build upon verified foundations."
        )

    why_time = (
        f"{allocated_hours} hours allocated based on your {gap_pct}% gap magnitude and {imp_pct}% role importance, "
        f"paced at {pacing_per_week}h/week within your {user_hours_per_week}h/week availability."
    )

    why_resource = (
        f"Curated specifically to address your missing capabilities ({', '.join(missing[:2]) if missing else 'production implementation'}) "
        f"without repeating the foundational areas your existing projects already demonstrate."
    )

    how_validated = (
        f"INAURA verifies this capability through demonstrable code: submit a GitHub repository deliverable with "
        f"test proof covering {missing[0] if missing else display_name}, or pass the {display_name} verification assessment with ≥80%."
    )

    five_whys = {
        "why_learning": why_learning,
        "why_now": why_now,
        "why_time": why_time,
        "why_resource": why_resource,
        "how_validated": how_validated,
    }

    # Human-Readable Explanation Block
    evidence_lines = "\n".join(f"- {e}" for e in evidence_list[:6]) if evidence_list else "- No active implementation evidence"
    missing_lines = "\n".join(f"- {m}" for m in missing[:6]) if missing else "- Advanced production validation & scaling"
    demonstrated_lines = "\n".join(f"- {d}" for d in demonstrated[:6]) if demonstrated else "- Foundational concepts only"

    readable_summary = f"""Skill: {display_name}

Current proficiency: {cur_pct}%
Confidence: {conf_pct}% ({confidence_rationale})

Evidence:
{evidence_lines}

Demonstrated capabilities:
{demonstrated_lines}

Missing evidence:
{missing_lines}

Required for target role: {req_pct}% ({target_role})
Gap: {gap_pct} percentage points
Priority Score: {int(round(priority_score))}

Prerequisites: {prerequisites_status}
Allocated Time: {allocated_hours} hours ({weekly_pacing})

Smallest useful learning unit:
{smallest_learning_unit}

Validation criteria:
{validation_criteria}"""

    return {
        "skill_name": display_name,
        "canonical_name": canonical,
        "skill_slug": slug,
        "current_proficiency": current_prof,
        "current_proficiency_pct": cur_pct,
        "required_level": required_level,
        "required_level_pct": req_pct,
        "gap_pct": gap_pct,
        "confidence": confidence,
        "confidence_pct": conf_pct,
        "confidence_rationale": confidence_rationale,
        "demonstrated_capabilities": demonstrated,
        "missing_capabilities": missing,
        "supporting_evidence": evidence_list,
        "prerequisites_required": prereqs,
        "prerequisites_status": prerequisites_status,
        "target_role": target_role,
        "importance_pct": imp_pct,
        "demand_pct": dem_pct,
        "interview_relevance_pct": int_pct,
        "priority_score": priority_score,
        "allocated_hours": allocated_hours,
        "weekly_hours_budget": user_hours_per_week,
        "weekly_pacing": weekly_pacing,
        "smallest_learning_unit": smallest_learning_unit,
        "validation_criteria": validation_criteria,
        "five_whys": five_whys,
        "readable_summary": readable_summary,
    }


def personalize_tasks_for_skill(
    canonical: str,
    tasks: List[dict],
    explanation: Dict[str, Any],
) -> List[dict]:
    """
    Personalize the 4-stage tasks (Learn, Practice, Build, Validate) to target
    the specific MISSING capabilities rather than re-teaching demonstrated ones.
    """
    missing = explanation.get("missing_capabilities") or []
    demonstrated = explanation.get("demonstrated_capabilities") or []
    display_name = explanation.get("skill_name") or canonical.replace("_", " ").title()

    if not missing:
        return tasks

    primary_missing = missing[0]
    secondary_missing = missing[1] if len(missing) > 1 else missing[0]
    learning_note = (
        "Skip concepts already demonstrated and spend the time on applied understanding."
        if demonstrated
        else "Start with the smallest concepts needed to complete the practical task."
    )

    for t in tasks:
        t_type = t.get("task_type")
        if t_type == "learn":
            t["title"] = f"Learn {primary_missing}"
            t["description"] = (
                f"Study {primary_missing} and {secondary_missing} through a short, role-relevant lesson. "
                f"{learning_note}"
            )
            t["why_this_task"] = f"Targets the next capability needed to close your {explanation.get('gap_pct', 0)}% gap."

        elif t_type == "practice":
            t["title"] = f"Implement {primary_missing}"
            t["description"] = (
                f"Complete focused exercises implementing {primary_missing} and {secondary_missing}. "
                f"Include error handling, boundary conditions, and a brief self-review."
            )
            t["why_this_task"] = f"Bridges the {explanation.get('gap_pct', 0)}% gap through targeted practice."

        elif t_type == "build":
            t["title"] = f"Build Practical Deliverable: {display_name} Component"
            t["description"] = (
                f"Construct a complete deliverable integrating {primary_missing} and {secondary_missing}. "
                f"Structure clean code, documentation, and configuration."
            )
            t["why_this_task"] = "Turns the missing capability into a practical, portfolio-ready deliverable."

        elif t_type == "validate":
            t["title"] = f"Automated Verification & Submission for {display_name}"
            t["description"] = (
                f"Write automated tests verifying {primary_missing} functionality, edge cases, and failure responses. "
                f"Finish with a short checklist explaining what works and what remains."
            )
            t["validation_method"] = explanation.get("validation_criteria") or t.get("validation_method")
            t["why_this_task"] = "Confirms that you can apply the capability independently in a realistic scenario."

        t["personalization_context"] = {
            "primary_gap": primary_missing,
            "gap_pct": explanation.get("gap_pct"),
            "confidence_pct": explanation.get("confidence_pct"),
        }

    return tasks
