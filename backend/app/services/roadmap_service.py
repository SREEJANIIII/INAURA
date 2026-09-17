import math
import uuid
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple, Any
from fastapi import HTTPException
from supabase import Client

from ..core.supabase import get_supabase_client
from . import profile_service
from .roadmap_catalog import (
    get_resources_for_skill,
    get_template_for_skill,
    get_base_hours,
    get_item_type,
    decompose_skill_into_tasks,
    ENGINE_VERSION,
)
from .skill_taxonomy import normalize_skill, normalize_skill_slug
from . import skill_dependencies
from . import learner_state_service
from . import roadmap_personalization_service

logger = logging.getLogger(__name__)

# Tables
ROADMAPS = "roadmaps"
ITEMS = "roadmap_items"
RESOURCES = "roadmap_resources"
MILESTONES = "roadmap_milestones"
WEEKS = "roadmap_weeks"
TASKS = "roadmap_tasks"
SNAPSHOTS = "evidence_snapshots"
ANALYSIS_RESULTS = "analysis_results"
SKILL_GAPS = "skill_gaps"
SKILLS = "skills"

MILESTONE_TITLES = [
    ("Strengthen Core Foundations", "Build foundational understanding for your highest-priority gaps. Focus on core concepts and guided learning."),
    ("Build Practical Capability", "Apply what you learned through practice and small projects tied to your gaps."),
    ("Demonstrate Industry Readiness", "Validate with projects and assessments that mirror interview and on-the-job expectations."),
]


def _client() -> Client:
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    return c


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def clamp100(v: float) -> float:
    return max(0.0, min(100.0, v))


def estimate_weeks(total_hours: float, hours_per_week: int) -> int:
    """Ceil(total / hours_per_week). Raises 400 if hours_per_week missing/invalid."""
    if hours_per_week is None or not isinstance(hours_per_week, (int, float)):
        raise HTTPException(status_code=400, detail="Update your weekly availability to create a realistic timeline. Set hours_per_week in your profile (1-80).")
    try:
        h = int(hours_per_week)
    except:
        raise HTTPException(status_code=400, detail="Update your weekly availability to create a realistic timeline. Set hours_per_week in your profile (1-80).")
    if h <= 0 or h > 80:
        raise HTTPException(status_code=400, detail="Update your weekly availability to create a realistic timeline. hours_per_week must be between 1 and 80.")
    if total_hours <= 0:
        return 0
    return math.ceil(total_hours / h)


def validate_completion_percentage(val: float) -> float:
    if val is None or not isinstance(val, (int, float)):
        raise HTTPException(status_code=400, detail="completion_percentage must be a number between 0 and 100")
    if isinstance(val, bool):
        raise HTTPException(status_code=400, detail="completion_percentage must be a number between 0 and 100")
    if math.isnan(val) or math.isinf(val):
        raise HTTPException(status_code=400, detail="completion_percentage must be between 0 and 100")
    if val < 0 or val > 100:
        raise HTTPException(status_code=400, detail="completion_percentage must be between 0 and 100")
    return clamp100(float(val))


def calculate_progress(items: List[dict]) -> float:
    """progress = average(completion_percentage) clamped [0,100]"""
    if not items:
        return 0.0
    vals = []
    for it in items:
        cp = it.get("completion_percentage", 0)
        try:
            v = float(cp)
        except:
            v = 0
        if math.isnan(v) or math.isinf(v):
            v = 0
        vals.append(clamp100(v))
    if not vals:
        return 0.0
    return clamp100(sum(vals) / len(vals))


def filter_and_sort_gaps(gaps: List[dict]) -> List[dict]:
    """Remove zero gaps, sort by priority_score descending deterministic."""
    filtered = [g for g in gaps if float(g.get("gap", 0)) > 1e-9]
    # stable sort by priority_score desc, then skill name asc for determinism when equal
    filtered.sort(key=lambda x: (-float(x.get("priority_score", 0)), str(x.get("skill_id", ""))))
    return filtered


def limit_gaps(gaps: List[dict], max_items: int = 6, min_items: int = 3) -> List[dict]:
    """Take top max_items gaps. Keep deterministic. If fewer than min_items available, take all."""
    if not gaps:
        return []
    return gaps[:max_items]


def estimate_hours_for_gap(canonical: str, gap: float, importance: float) -> float:
    """Heuristic: base_hours + gap*6 + importance*2, clamped reasonable."""
    base = get_base_hours(canonical)
    extra = gap * 6 + importance * 2
    total = base + extra
    total = round(total, 1)
    total = max(2.0, min(30.0, total))
    return total


def generate_why_it_matters(
    display_name: str,
    current: float,
    required: float,
    gap: float,
    importance: float,
    demand: float,
    interview: float,
    confidence: float,
    target_role: str,
) -> str:
    """Explainability using actual stored values."""
    cur_pct = round(current * 100)
    req_pct = round(required * 100)
    gap_pct = round(gap * 100)
    conf_pct = round(confidence * 100)
    if gap == 0:
        return f"{display_name} is already covered (current {cur_pct}% meets required {req_pct}% for {target_role}). No learning item needed — this skill is excluded from the roadmap."
    parts = []
    parts.append(f"{display_name} is prioritized because your current proficiency ({cur_pct}%) is below the required level ({req_pct}%, gap {gap_pct}%) for {target_role}.")
    if importance >= 0.8:
        parts.append(f"It has high importance ({importance:.2f}) for this role.")
    elif importance >= 0.6:
        parts.append(f"It has moderate importance ({importance:.2f}) for this role.")
    else:
        parts.append(f"Industry importance is {importance:.2f}.")
    if demand >= 0.8:
        parts.append(f"Demand is high ({demand:.2f}).")
    if interview >= 0.75:
        parts.append(f"Interview relevance is high ({interview:.2f}).")
    parts.append(f"Confidence is {conf_pct}% — based on available evidence; stronger evidence would increase confidence.")
    return " ".join(parts)


def generate_item_title(display_name: str, canonical: str) -> str:
    return f"Master {display_name}"


def generate_item_description(canonical: str, display_name: str, target_role: str) -> str:
    tmpl = get_template_for_skill(canonical)
    parts = []
    if tmpl.get("learn"):
        parts.append(f"Learn: {tmpl['learn']}.")
    if tmpl.get("practice"):
        parts.append(f"Practice: {tmpl['practice']}.")
    if tmpl.get("project"):
        parts.append(f"Build: {tmpl['project']}.")
    if tmpl.get("validate"):
        parts.append(f"Validate: {tmpl['validate']}.")
    parts.append(f"Focused on {display_name} for {target_role} — curated prototype resources, not live industry data.")
    return " ".join(parts)


def _load_profile_hours(user_id: str, hours_override: Optional[int] = None) -> int:
    if hours_override is not None and 1 <= hours_override <= 80:
        return int(hours_override)
    prof = profile_service.get_profile(user_id)
    if not prof:
        raise HTTPException(status_code=400, detail="Profile not found — complete /profile/setup first. hours_per_week is required to estimate roadmap timeline.")
    hpw = prof.get("hours_per_week")
    if hpw is None or hpw == 0:
        raise HTTPException(status_code=400, detail="Update your weekly availability to create a realistic timeline. Set hours_per_week in your profile (1-80).")
    try:
        h = int(hpw)
    except:
        raise HTTPException(status_code=400, detail="Update your weekly availability to create a realistic timeline. Set hours_per_week in your profile (1-80).")
    if h <= 0 or h > 80:
        raise HTTPException(status_code=400, detail="Update your weekly availability to create a realistic timeline. hours_per_week must be between 1 and 80.")
    return h


def _get_latest_analysis(user_id: str) -> dict:
    c = _client()
    try:
        r = c.table(ANALYSIS_RESULTS).select("*").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
        if not r.data or len(r.data) == 0:
            raise HTTPException(status_code=404, detail="No analysis yet — Run your INAURA analysis first to generate a personalized roadmap.")
        return r.data[0]
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Analysis tables not found — run backend/supabase/005_skill_engine.sql")
        raise HTTPException(status_code=500, detail="Failed to fetch latest analysis")


def _get_gaps_for_analysis(user_id: str, analysis_id: str) -> List[dict]:
    c = _client()
    try:
        r = c.table(SKILL_GAPS).select("*, skills(canonical_name, display_name, category)").eq("user_id", user_id).eq("analysis_result_id", analysis_id).order("priority_score", desc=True).execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Skill gaps table not found — run 005_skill_engine.sql")
        raise HTTPException(status_code=500, detail="Failed to fetch gaps")


def _get_assessments_for_user(user_id: str) -> List[dict]:
    c = _client()
    try:
        r = c.table("skill_assessments").select("*, skills(canonical_name, display_name, category)").eq("user_id", user_id).order("created_at", desc=True).execute()
        return r.data or []
    except Exception:
        return []


def _get_skills_map() -> Dict[str, dict]:
    c = _client()
    try:
        r = c.table(SKILLS).select("*").execute()
        return {row["id"]: row for row in (r.data or [])}
    except Exception:
        return {}


async def generate_roadmap(
    user_id: str,
    target_role: Optional[str] = None,
    hours_per_week_override: Optional[int] = None,
) -> dict:
    """
    Evidence-Driven Weekly Adaptive Roadmap Generation Pipeline:
    1. Load Profile & Hours Capacity
    2. Fetch Latest Analysis & Audited Evidence
    3. Compile LearnerSkillStates (KNOWN / INFERRED / UNKNOWN)
    4. Create Immutable EvidenceSnapshot
    5. Filter Non-Zero Gaps & Rank by Priority
    6. Resolve Topological Prerequisites via Skill Dependency DAG
    7. Decompose Skills into 4-Stage Tasks (Learn -> Practice -> Build -> Validate)
    8. Bin-pack Tasks into Time-Boxed Weekly Modules
    9. Persist Roadmaps, Weeks, Tasks, and Legacy Milestones (Backward Compatible)
    """
    c = _client()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Load profile hours
    hours_per_week = _load_profile_hours(user_id, hours_per_week_override)

    # 2. Latest analysis
    analysis = _get_latest_analysis(user_id)
    analysis_id = analysis["id"]
    role = target_role.strip() if target_role and target_role.strip() else analysis.get("target_role")
    if not role or len(role.strip()) < 2:
        role = analysis.get("target_role") or "Software Engineer"
    role = role.strip()

    # 3. Load gaps
    gaps = _get_gaps_for_analysis(user_id, analysis_id)
    filtered = filter_and_sort_gaps(gaps)
    if not filtered:
        raise HTTPException(
            status_code=400,
            detail="You're currently meeting the assessed requirements for this role. Keep building evidence and stay industry-ready. No priority gaps to generate a roadmap from."
        )

    # 4. Compile Learner Skill States and create immutable EvidenceSnapshot
    try:
        user_assessments = _get_assessments_for_user(user_id)
        learner_states = learner_state_service.compile_learner_skill_states(user_id, user_assessments, gaps)
    except Exception as e:
        logger.debug("Learner state compilation fallback: %s", e)
        learner_states = {}

    snapshot = learner_state_service.create_evidence_snapshot(user_id, analysis_id, learner_states)
    snapshot_id = snapshot.get("id")

    # 4b. Load grouped evidence signals for personalization
    try:
        from . import analysis_run_service as ars
        ev_items, ev_projs, ev_certs = ars.load_evidence(user_id)
        raw_signals = ars.extract_skill_signals(ev_items, ev_projs, ev_certs)
        grouped_signals = ars.aggregate_skills(ars.normalize_signals(raw_signals, c))
    except Exception as e:
        logger.debug("Failed to load grouped signals for personalization: %s", e)
        grouped_signals = {}

    explanations_by_slug: Dict[str, dict] = {}

    # 5. Limit candidate gaps to top 3-6 (sorted strictly by priority descending)
    priority_selected = limit_gaps(filtered, max_items=6)

    # Load skills map for display
    skills_map = _get_skills_map()

    # 6. Resolve Skill Dependencies (Prerequisite DAG) for weekly task scheduling
    slug_to_gap: Dict[str, dict] = {}
    for g in priority_selected:
        s_id = g.get("skill_id")
        s_info = skills_map.get(s_id, {})
        canon = s_info.get("canonical_name") or g.get("skills", {}).get("canonical_name") or g.get("canonical_name") or "unknown"
        slug = normalize_skill_slug(canon) or canon.lower().replace(" ", "_")
        slug_to_gap[slug] = g

    learner_profs = {slug: st.proficiency for slug, st in learner_states.items()}
    priority_map = {slug: float(g.get("priority_score", 0)) for slug, g in slug_to_gap.items()}

    ordered_slugs = skill_dependencies.resolve_dependencies(
        list(slug_to_gap.keys()),
        learner_proficiencies=learner_profs,
        priority_scores=priority_map,
    )
    ordered_selected = [slug_to_gap[s] for s in ordered_slugs if s in slug_to_gap]
    for g in priority_selected:
        if g not in ordered_selected:
            ordered_selected.append(g)

    # 7. Build items data (ordered by priority score for legacy items/milestones)
    items_data = []
    for idx, gap in enumerate(priority_selected):
        skill_id = gap.get("skill_id")
        skill_info = skills_map.get(skill_id, {})
        canonical = skill_info.get("canonical_name") or gap.get("skills", {}).get("canonical_name") or gap.get("canonical_name") or "unknown"
        display_name = skill_info.get("display_name") or gap.get("skills", {}).get("display_name") or canonical
        if not display_name or display_name == "unknown":
            display_name = canonical.replace("_", " ").title()
        category = skill_info.get("category") or gap.get("skills", {}).get("category") or ""
        slug = normalize_skill_slug(canonical) or canonical.lower().replace(" ", "_")
        
        current = float(gap.get("current_proficiency", 0))
        required = float(gap.get("required_level", 0.75))
        gap_val = float(gap.get("gap", 0))
        importance = float(gap.get("importance", 0.5))
        demand = float(gap.get("demand", 0.5))
        interview = float(gap.get("interview_relevance", 0.5))
        confidence = float(gap.get("confidence", 0))
        priority_score = float(gap.get("priority_score", 0))

        est_hours = estimate_hours_for_gap(canonical, gap_val, importance)
        why = generate_why_it_matters(display_name, current, required, gap_val, importance, demand, interview, confidence, role)

        # Build comprehensive evidence-traceable personalization & 5 Whys
        personalization = roadmap_personalization_service.build_skill_personalization(
            gap_dict=gap,
            target_role=role,
            user_hours_per_week=hours_per_week,
            learner_states=learner_states,
            grouped_signals=grouped_signals,
            skills_map=skills_map,
        )
        explanations_by_slug[slug] = personalization

        title = generate_item_title(display_name, canonical)
        desc = generate_item_description(canonical, display_name, role)
        item_type = get_item_type(canonical)
        priority_int = int(round(priority_score))

        item_entry = {
            "skill_id": skill_id,
            "skill_gap_id": gap.get("id"),
            "canonical": canonical,
            "display_name": display_name,
            "category": category,
            "title": title,
            "description": desc,
            "item_type": item_type,
            "priority": priority_int,
            "estimated_hours": est_hours,
            "sequence_order": idx + 1,
            "why_it_matters": why,
            "gap": gap,
            "personalization_explanation": personalization,
        }
        items_data.append(item_entry)

    # Decompose into 4 stages: Learn -> Practice -> Build -> Validate in dependency order
    all_decomposed_tasks = []
    for gap in ordered_selected:
        skill_id = gap.get("skill_id")
        skill_info = skills_map.get(skill_id, {})
        canonical = skill_info.get("canonical_name") or gap.get("skills", {}).get("canonical_name") or gap.get("canonical_name") or "unknown"
        display_name = skill_info.get("display_name") or gap.get("skills", {}).get("display_name") or canonical
        if not display_name or display_name == "unknown":
            display_name = canonical.replace("_", " ").title()

        gap_val = float(gap.get("gap", 0))
        importance = float(gap.get("importance", 0.5))
        est_hours = estimate_hours_for_gap(canonical, gap_val, importance)

        slug = normalize_skill_slug(canonical) or canonical.lower().replace(" ", "_")
        learner_st = learner_states.get(slug)
        classif = learner_st.state_classification if learner_st else "UNKNOWN"
        tasks_for_skill = decompose_skill_into_tasks(
            canonical=canonical,
            total_hours=est_hours,
            learner_state_classification=classif,
            target_role=role,
        )

        # Personalize 4-stage tasks based on specific missing capabilities
        gap_expl = explanations_by_slug.get(slug)
        if gap_expl:
            tasks_for_skill = roadmap_personalization_service.personalize_tasks_for_skill(
                canonical=canonical,
                tasks=tasks_for_skill,
                explanation=gap_expl,
            )

        for t in tasks_for_skill:
            t["skill_id"] = skill_id
            t["skill_slug"] = slug
            t["skill_name"] = display_name
            all_decomposed_tasks.append(t)

    # 8. Bin-pack tasks into weeks matching hours_per_week
    target_week_minutes = max(120, hours_per_week * 60)
    planned_weeks = []
    curr_week_num = 1
    curr_tasks: List[dict] = []
    curr_minutes = 0

    for task in all_decomposed_tasks:
        # Overflow check: allow slight grace window (15%) before opening a new week
        if curr_tasks and (curr_minutes + task["estimated_minutes"]) > (target_week_minutes * 1.15):
            week_skills = list(dict.fromkeys(t["skill_name"] for t in curr_tasks))
            theme = f"Week {curr_week_num}: {week_skills[0]} Fundamentals & Application" if week_skills else f"Week {curr_week_num}"
            objective = f"Master {', '.join(week_skills[:2])} concepts, complete targeted exercises, and implement working deliverables."
            planned_weeks.append({
                "week_number": curr_week_num,
                "title": theme,
                "objective": objective,
                "estimated_hours": round(curr_minutes / 60.0, 1),
                "skills": week_skills,
                "status": "current" if curr_week_num == 1 else "locked",
                "completion_percentage": 0.0,
                "tasks": curr_tasks,
            })
            curr_week_num += 1
            curr_tasks = []
            curr_minutes = 0

        curr_tasks.append(task)
        curr_minutes += task["estimated_minutes"]

    if curr_tasks:
        week_skills = list(dict.fromkeys(t["skill_name"] for t in curr_tasks))
        theme = f"Week {curr_week_num}: {week_skills[0]} Capstone & Verification" if week_skills else f"Week {curr_week_num}"
        objective = f"Finalize practical build projects, integration tests, and validation assessments for {', '.join(week_skills)}."
        planned_weeks.append({
            "week_number": curr_week_num,
            "title": theme,
            "objective": objective,
            "estimated_hours": round(curr_minutes / 60.0, 1),
            "skills": week_skills,
            "status": "current" if curr_week_num == 1 else "locked",
            "completion_percentage": 0.0,
            "tasks": curr_tasks,
        })

    total_hours = round(sum(it["estimated_hours"] for it in items_data), 1)
    estimated_weeks = estimate_weeks(total_hours, hours_per_week)
    total_weeks = len(planned_weeks) if planned_weeks else estimated_weeks

    # 9. Archive previous active roadmaps
    try:
        c.table(ROADMAPS).update({"status": "archived", "updated_at": now}).eq("user_id", user_id).eq("status", "active").execute()
    except Exception:
        pass

    # 10. Persist Roadmap
    roadmap_title = f"Personalized Roadmap — {role}"
    roadmap_row = {
        "user_id": user_id,
        "analysis_result_id": analysis_id,
        "target_role": role,
        "title": roadmap_title,
        "status": "active",
        "engine_version": ENGINE_VERSION,
        "total_estimated_hours": total_hours,
        "estimated_weeks": estimated_weeks,
        "evidence_snapshot_id": snapshot_id,
        "weekly_hours_budget": hours_per_week,
        "total_weeks": total_weeks,
        "current_week_index": 1,
        "adaptive_rebalance_count": 0,
        "created_at": now,
        "updated_at": now,
    }

    try:
        r = c.table(ROADMAPS).insert(roadmap_row).execute()
        if r.data and len(r.data) > 0:
            roadmap = r.data[0]
        else:
            roadmap = roadmap_row
            roadmap["id"] = str(uuid.uuid4())
    except Exception as e:
        # Fallback if 022 columns not yet migrated
        try:
            clean_row = {k: v for k, v in roadmap_row.items() if k not in ("evidence_snapshot_id", "weekly_hours_budget", "total_weeks", "current_week_index", "adaptive_rebalance_count")}
            r = c.table(ROADMAPS).insert(clean_row).execute()
            roadmap = r.data[0] if (r.data and len(r.data) > 0) else {**clean_row, "id": str(uuid.uuid4())}
        except Exception as e2:
            m = str(e2).lower()
            if "could not find the table" in m or "pgrst205" in m:
                raise HTTPException(status_code=503, detail="Roadmap tables not found — run backend/supabase/006_roadmap.sql")
            raise HTTPException(status_code=500, detail=f"Failed to create roadmap: {str(e2)[:200]}")

    roadmap_id = roadmap["id"]

    # 11. Persist legacy items & resources (100% backward compatible)
    persisted_items = []
    for it in items_data:
        row = {
            "roadmap_id": roadmap_id,
            "skill_id": it["skill_id"],
            "skill_gap_id": it["skill_gap_id"],
            "title": it["title"],
            "description": it["description"],
            "item_type": it["item_type"],
            "priority": it["priority"],
            "estimated_hours": it["estimated_hours"],
            "sequence_order": it["sequence_order"],
            "status": "not_started",
            "completion_percentage": 0,
            "why_it_matters": it["why_it_matters"],
            "created_at": now,
            "updated_at": now,
        }
        try:
            r2 = c.table(ITEMS).insert(row).execute()
            persisted = r2.data[0] if (r2.data and len(r2.data) > 0) else {**row, "id": str(uuid.uuid4())}
        except Exception:
            persisted = {**row, "id": str(uuid.uuid4())}
        persisted["personalization_explanation"] = it.get("personalization_explanation")
        persisted_items.append(persisted)

        resources = get_resources_for_skill(it["canonical"])
        for res in resources:
            res_row = {
                "roadmap_item_id": persisted["id"],
                "title": res["title"],
                "resource_type": res["resource_type"],
                "url": res["url"],
                "provider": res.get("provider"),
                "difficulty": res.get("difficulty"),
                "estimated_hours": res.get("estimated_hours"),
                "is_free": res.get("is_free", True),
                "description": res["description"],
                "created_at": now,
            }
            try:
                c.table(RESOURCES).insert(res_row).execute()
            except Exception:
                pass

    # 12. Persist weekly modules and 4-stage tasks
    persisted_weeks = []
    for w in planned_weeks:
        w_row = {
            "roadmap_id": roadmap_id,
            "week_number": w["week_number"],
            "title": w["title"],
            "objective": w["objective"],
            "estimated_hours": w["estimated_hours"],
            "skills": w["skills"],
            "status": w["status"],
            "completion_percentage": 0.0,
            "created_at": now,
            "updated_at": now,
        }
        try:
            rw = c.table(WEEKS).insert(w_row).execute()
            w_inst = rw.data[0] if (rw.data and len(rw.data) > 0) else {**w_row, "id": str(uuid.uuid4())}
        except Exception:
            w_inst = {**w_row, "id": str(uuid.uuid4())}

        week_tasks = []
        for seq_idx, t in enumerate(w.get("tasks", [])):
            t_row = {
                "roadmap_week_id": w_inst["id"],
                "skill_slug": t["skill_slug"],
                "skill_name": t["skill_name"],
                "task_type": t["task_type"],
                "title": t["title"],
                "description": t["description"],
                "estimated_minutes": t["estimated_minutes"],
                "sequence_order": t.get("sequence_order", seq_idx + 1),
                "status": "not_started",
                "completion_percentage": 0.0,
                "resources": t.get("resources", []),
                "validation_method": t.get("validation_method", "self_check"),
                "why_this_task": t.get("why_this_task", ""),
                "created_at": now,
                "updated_at": now,
            }
            try:
                rt = c.table(TASKS).insert(t_row).execute()
                t_inst = rt.data[0] if (rt.data and len(rt.data) > 0) else {**t_row, "id": str(uuid.uuid4())}
            except Exception:
                t_inst = {**t_row, "id": str(uuid.uuid4())}
            if t.get("personalization_context"):
                t_inst["personalization_context"] = t.get("personalization_context")
            week_tasks.append(t_inst)

        w_inst["tasks"] = week_tasks
        persisted_weeks.append(w_inst)

    # 13. Persist legacy Milestones for backward compatibility
    n = len(persisted_items)
    num_milestones = 3 if n >= 3 else (2 if n == 2 else 1)
    per = math.ceil(n / num_milestones) if num_milestones else 1
    milestones_created = []

    for mi in range(num_milestones):
        start = mi * per
        end = min(start + per, n)
        group = persisted_items[start:end]
        if not group:
            continue
        target_hours = round(sum(float(g.get("estimated_hours", 0)) for g in group), 1)
        m_title, m_desc = MILESTONE_TITLES[mi] if mi < len(MILESTONE_TITLES) else (f"Milestone {mi+1}", "Continue your roadmap.")
        mrow = {
            "roadmap_id": roadmap_id,
            "title": m_title,
            "description": m_desc,
            "sequence_order": mi + 1,
            "target_hours": target_hours,
            "status": "not_started",
            "created_at": now,
            "updated_at": now,
        }
        try:
            rm = c.table(MILESTONES).insert(mrow).execute()
            milestones_created.append(rm.data[0] if (rm.data and len(rm.data) > 0) else {**mrow, "id": str(uuid.uuid4())})
        except Exception:
            milestones_created.append({**mrow, "id": str(uuid.uuid4())})

    progress = calculate_progress(persisted_items)

    return {
        "id": roadmap_id,
        "user_id": user_id,
        "analysis_result_id": analysis_id,
        "evidence_snapshot_id": snapshot_id,
        "target_role": role,
        "title": roadmap_title,
        "status": "active",
        "engine_version": ENGINE_VERSION,
        "total_estimated_hours": total_hours,
        "estimated_weeks": estimated_weeks,
        "hours_per_week": hours_per_week,
        "weekly_hours_budget": hours_per_week,
        "total_weeks": total_weeks,
        "current_week_index": 1,
        "progress": progress,
        "skill_explanations": list(explanations_by_slug.values()),
        "created_at": roadmap.get("created_at", now),
        "updated_at": roadmap.get("updated_at", now),
        "items": persisted_items,
        "milestones": milestones_created,
        "weeks": persisted_weeks,
    }


def get_latest_roadmap(user_id: str) -> dict:
    c = _client()
    try:
        r = c.table(ROADMAPS).select("*").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
        if not r.data or len(r.data) == 0:
            raise HTTPException(status_code=404, detail="No roadmap found — generate your personalized roadmap first.")
        roadmap = r.data[0]
        items = get_items_for_roadmap(user_id, roadmap["id"])
        roadmap["progress"] = calculate_progress(items)
        try:
            prof = profile_service.get_profile(user_id)
            roadmap["hours_per_week"] = prof.get("hours_per_week") if prof else None
        except:
            roadmap["hours_per_week"] = None
        
        # Attach weeks if available
        try:
            weeks = get_roadmap_weeks(user_id, roadmap["id"])
            roadmap["weeks"] = weeks
        except Exception:
            roadmap["weeks"] = []

        # Attach skill_explanations from items
        roadmap["skill_explanations"] = [
            it["personalization_explanation"]
            for it in items
            if it.get("personalization_explanation")
        ]

        return roadmap
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Roadmap tables not found — run backend/supabase/006_roadmap.sql")
        raise HTTPException(status_code=500, detail="Failed to fetch latest roadmap")


def get_items_for_roadmap(user_id: str, roadmap_id: str) -> List[dict]:
    c = _client()
    try:
        r0 = c.table(ROADMAPS).select("id, target_role, weekly_hours_budget").eq("id", roadmap_id).eq("user_id", user_id).single().execute()
        if not r0.data:
            raise HTTPException(status_code=404, detail="Roadmap not found")
        rm_meta = r0.data
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "no rows" in m or "not found" in m or "0 rows" in m:
            raise HTTPException(status_code=404, detail="Roadmap not found or not owned by user")
        raise
    try:
        r = c.table(ITEMS).select("*, skills(canonical_name, display_name, category), roadmap_resources(*)").eq("roadmap_id", roadmap_id).order("sequence_order").execute()
        items = r.data or []
        for it in items:
            if not it.get("personalization_explanation"):
                try:
                    s_info = it.get("skills") or {}
                    canon = s_info.get("canonical_name") or it.get("title", "").replace("Master ", "")
                    it["personalization_explanation"] = roadmap_personalization_service.build_skill_personalization(
                        gap_dict={
                            "skill_id": it.get("skill_id"),
                            "canonical_name": canon,
                            "current_proficiency": 0.5,
                            "required_level": 0.8,
                            "gap": 0.3,
                            "confidence": 0.75,
                            "importance": 0.85,
                            "priority_score": it.get("priority", 25),
                        },
                        target_role=rm_meta.get("target_role") or "Software Engineer",
                        user_hours_per_week=rm_meta.get("weekly_hours_budget") or 10,
                        learner_states={},
                        grouped_signals={},
                        skills_map={},
                    )
                except Exception:
                    pass
        return items
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m:
            raise HTTPException(status_code=503, detail="Roadmap items table not found")
        raise HTTPException(status_code=500, detail="Failed to fetch roadmap items")


def get_all_items_for_user(user_id: str) -> List[dict]:
    roadmap = get_latest_roadmap(user_id)
    return get_items_for_roadmap(user_id, roadmap["id"])


def get_milestones_for_roadmap(user_id: str, roadmap_id: str) -> List[dict]:
    c = _client()
    try:
        r0 = c.table(ROADMAPS).select("id").eq("id", roadmap_id).eq("user_id", user_id).single().execute()
        if not r0.data:
            raise HTTPException(status_code=404, detail="Roadmap not found")
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "no rows" in m:
            raise HTTPException(status_code=404, detail="Roadmap not found")
        try:
            rr = c.table(ROADMAPS).select("id").eq("user_id", user_id).eq("id", roadmap_id).execute()
            if not rr.data or len(rr.data) == 0:
                raise HTTPException(status_code=404, detail="Roadmap not found")
        except HTTPException:
            raise
        except:
            pass
    try:
        r = c.table(MILESTONES).select("*").eq("roadmap_id", roadmap_id).order("sequence_order").execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m:
            raise HTTPException(status_code=503, detail="Milestones table not found")
        raise HTTPException(status_code=500, detail="Failed to fetch milestones")


def get_all_milestones_for_user(user_id: str) -> List[dict]:
    roadmap = get_latest_roadmap(user_id)
    return get_milestones_for_roadmap(user_id, roadmap["id"])


def get_roadmap_weeks(user_id: str, roadmap_id: Optional[str] = None) -> List[dict]:
    """Retrieve structured weeks and nested 4-stage tasks for roadmap."""
    c = _client()
    if not roadmap_id:
        rm = get_latest_roadmap(user_id)
        roadmap_id = rm["id"]

    try:
        rw = c.table(WEEKS).select("*").eq("roadmap_id", roadmap_id).order("week_number").execute()
        weeks = rw.data or []
        if not weeks:
            return []

        # Fetch all tasks for these weeks
        week_ids = [w["id"] for w in weeks]
        rt = c.table(TASKS).select("*").in_("roadmap_week_id", week_ids).order("sequence_order").execute()
        tasks_by_week = defaultdict(list)
        for t in (rt.data or []):
            tasks_by_week[t["roadmap_week_id"]].append(t)

        for w in weeks:
            w["tasks"] = tasks_by_week.get(w["id"], [])

        return weeks
    except Exception as e:
        logger.debug("Failed to fetch roadmap weeks: %s", e)
        message = str(e).lower()
        if "could not find the table" in message or "pgrst205" in message:
            raise HTTPException(status_code=503, detail="Weekly roadmap tables not found — run backend/supabase/022_adaptive_weekly_roadmap.sql")
        raise HTTPException(status_code=500, detail="Failed to fetch weekly roadmap")


def get_roadmap_week(user_id: str, week_id: str) -> dict:
    c = _client()
    try:
        rw = c.table(WEEKS).select("*, roadmaps!inner(user_id)").eq("id", week_id).single().execute()
        if not rw.data:
            raise HTTPException(status_code=404, detail="Roadmap week not found")
        week = rw.data
        rt = c.table(TASKS).select("*").eq("roadmap_week_id", week_id).order("sequence_order").execute()
        week["tasks"] = rt.data or []
        return week
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch week: {str(e)[:150]}")


def get_roadmap_tasks(user_id: str, week_id: Optional[str] = None) -> List[dict]:
    c = _client()
    try:
        if week_id:
            return get_roadmap_week(user_id, week_id).get("tasks", [])
        weeks = get_roadmap_weeks(user_id)
        all_tasks = []
        for w in weeks:
            all_tasks.extend(w.get("tasks", []))
        return all_tasks
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch roadmap tasks")


def update_roadmap_item(user_id: str, item_id: str, payload: dict) -> dict:
    """Legacy item updater for backward compatibility."""
    c = _client()
    try:
        r = c.table(ITEMS).select("*, roadmaps!inner(user_id)").eq("id", item_id).execute()
        if not r.data or len(r.data) == 0:
            rr = c.table(ITEMS).select("*").eq("id", item_id).single().execute()
            if not rr.data:
                raise HTTPException(status_code=404, detail="Roadmap item not found")
            roadmap_id = rr.data.get("roadmap_id")
            r2 = c.table(ROADMAPS).select("user_id").eq("id", roadmap_id).single().execute()
            if not r2.data or r2.data.get("user_id") != user_id:
                raise HTTPException(status_code=403, detail="Not authorized to update this roadmap item")
            item = rr.data
        else:
            row = r.data[0]
            roadmaps = row.get("roadmaps")
            owner = None
            if isinstance(roadmaps, dict):
                owner = roadmaps.get("user_id")
            elif isinstance(roadmaps, list) and len(roadmaps) > 0:
                owner = roadmaps[0].get("user_id")
            if owner and owner != user_id:
                raise HTTPException(status_code=403, detail="Not authorized")
            item = row
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "no rows" in m or "0 rows" in m:
            raise HTTPException(status_code=404, detail="Roadmap item not found")
        raise HTTPException(status_code=500, detail="Failed to fetch roadmap item")

    allowed_status = {"not_started", "in_progress", "completed"}
    update_data = {}
    if "status" in payload:
        st = payload["status"]
        if st not in allowed_status:
            raise HTTPException(status_code=400, detail="Invalid status")
        update_data["status"] = st
        if st == "completed" and "completion_percentage" not in payload:
            update_data["completion_percentage"] = 100

    if "completion_percentage" in payload:
        cp = validate_completion_percentage(payload["completion_percentage"])
        update_data["completion_percentage"] = cp
        if "status" not in payload:
            if cp == 100:
                update_data["status"] = "completed"
            elif cp > 0:
                update_data["status"] = "in_progress"
            else:
                update_data["status"] = "not_started"

    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

    try:
        r3 = c.table(ITEMS).update(update_data).eq("id", item_id).execute()
        updated = r3.data[0] if (r3.data and len(r3.data) > 0) else {**item, **update_data}
        return updated
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update item: {str(e)[:150]}")


def update_roadmap_task(user_id: str, task_id: str, payload: dict) -> dict:
    """
    Update a 4-stage roadmap task.
    When a task is marked completed with validation or project evidence:
    - Automatically generates an evidence artifact signal.
    - Updates learner skill state.
    - Recalculates week completion percentage.
    - Unlocks next week if current week is 100% completed.
    """
    c = _client()
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        rt = c.table(TASKS).select("*, roadmap_weeks!inner(roadmap_id, week_number, roadmaps!inner(user_id))").eq("id", task_id).execute()
        if not rt.data or len(rt.data) == 0:
            # Fallback simple check
            rt2 = c.table(TASKS).select("*").eq("id", task_id).single().execute()
            if not rt2.data:
                raise HTTPException(status_code=404, detail="Roadmap task not found")
            task = rt2.data
            week_id = task.get("roadmap_week_id")
            if week_id:
                rw = c.table(WEEKS).select("roadmap_id").eq("id", week_id).single().execute()
                if rw.data:
                    rm = c.table(ROADMAPS).select("user_id").eq("id", rw.data.get("roadmap_id")).single().execute()
                    if rm.data and rm.data.get("user_id") != user_id:
                        raise HTTPException(status_code=403, detail="Not authorized to update this roadmap task")
        else:
            task = rt.data[0]
            w_info = task.get("roadmap_weeks", {})
            r_info = w_info.get("roadmaps", {}) if isinstance(w_info, dict) else {}
            owner = r_info.get("user_id") if isinstance(r_info, dict) else None
            if owner and owner != user_id:
                raise HTTPException(status_code=403, detail="Not authorized")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Roadmap task not found")

    update_data: Dict[str, Any] = {"updated_at": now_iso}

    if "status" in payload and payload["status"]:
        st = payload["status"]
        if st not in ("not_started", "in_progress", "completed", "skipped"):
            raise HTTPException(status_code=400, detail="Invalid task status")
        update_data["status"] = st
        if st == "completed":
            update_data["completion_percentage"] = 100.0
            update_data["completed_at"] = now_iso
        elif st == "not_started":
            update_data["completion_percentage"] = 0.0

    if "completion_percentage" in payload and payload["completion_percentage"] is not None:
        cp = validate_completion_percentage(payload["completion_percentage"])
        update_data["completion_percentage"] = cp
        if cp == 100.0 and "status" not in payload:
            update_data["status"] = "completed"
            update_data["completed_at"] = now_iso

    # Handle validation evidence generation
    submission_url = payload.get("submission_url")
    quiz_score = payload.get("quiz_score")
    if update_data.get("status") == "completed" and (submission_url or quiz_score is not None):
        evidence_gen = {
            "task_id": task_id,
            "skill_slug": task.get("skill_slug"),
            "task_type": task.get("task_type"),
            "submission_url": submission_url,
            "quiz_score": quiz_score,
            "completed_at": now_iso,
        }
        update_data["evidence_generated"] = evidence_gen

    try:
        r_up = c.table(TASKS).update(update_data).eq("id", task_id).execute()
        updated_task = r_up.data[0] if (r_up.data and len(r_up.data) > 0) else {**task, **update_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update task: {str(e)[:150]}")

    # Recalculate parent week progress & unlock next week if complete
    week_id = task.get("roadmap_week_id")
    if week_id:
        try:
            all_w_tasks = c.table(TASKS).select("completion_percentage, status").eq("roadmap_week_id", week_id).execute()
            t_rows = all_w_tasks.data or []
            if t_rows:
                avg_cp = sum(float(r.get("completion_percentage", 0)) for r in t_rows) / len(t_rows)
                is_done = all(r.get("status") in ("completed", "skipped") for r in t_rows)
                week_update = {
                    "completion_percentage": round(avg_cp, 1),
                    "status": "completed" if is_done else "current",
                    "updated_at": now_iso,
                }
                c.table(WEEKS).update(week_update).eq("id", week_id).execute()

                # Unlock subsequent week if this week is done
                if is_done:
                    curr_w = c.table(WEEKS).select("roadmap_id, week_number").eq("id", week_id).single().execute()
                    if curr_w.data:
                        r_id = curr_w.data.get("roadmap_id")
                        next_num = curr_w.data.get("week_number", 1) + 1
                        c.table(WEEKS).update({"status": "current", "updated_at": now_iso}).eq("roadmap_id", r_id).eq("week_number", next_num).eq("status", "locked").execute()
                        c.table(ROADMAPS).update({"current_week_index": next_num, "updated_at": now_iso}).eq("id", r_id).execute()
        except Exception as e:
            logger.debug("Parent week progress update skipped: %s", e)

    return updated_task


async def reassess_and_adapt(
    user_id: str,
    target_role: Optional[str] = None,
    adjust_hours_per_week: Optional[int] = None,
    mode: str = "compress",
) -> dict:
    """
    Adaptive Roadmap Reassessment:
    - Never regenerates completed history: completed tasks and weeks remain untouched.
    - Reassesses current learner states and recalculates remaining skill gaps.
    - Dynamically reschedules future uncompleted weeks based on updated pacing or availability.
    """
    c = _client()
    now_iso = datetime.now(timezone.utc).isoformat()

    current_roadmap = get_latest_roadmap(user_id)
    roadmap_id = current_roadmap["id"]

    # Load weeks
    weeks = get_roadmap_weeks(user_id, roadmap_id)
    if not weeks:
        # Generate fresh if no weeks exist
        return await generate_roadmap(user_id, target_role, adjust_hours_per_week)

    completed_weeks = [w for w in weeks if w.get("status") == "completed"]
    pending_weeks = [w for w in weeks if w.get("status") != "completed"]

    if not pending_weeks:
        return current_roadmap

    hpw = adjust_hours_per_week or current_roadmap.get("weekly_hours_budget") or _load_profile_hours(user_id)

    # Collect uncompleted tasks
    uncompleted_tasks = []
    for pw in pending_weeks:
        for t in pw.get("tasks", []):
            if t.get("status") not in ("completed", "skipped"):
                uncompleted_tasks.append(t)

    # Reschedule uncompleted tasks into remaining weeks
    target_week_minutes = max(120, hpw * 60)
    new_weeks = []
    start_week_num = len(completed_weeks) + 1
    curr_week_num = start_week_num
    curr_tasks: List[dict] = []
    curr_mins = 0

    for task in uncompleted_tasks:
        if curr_tasks and (curr_mins + task["estimated_minutes"]) > (target_week_minutes * 1.15):
            week_skills = list(dict.fromkeys(t["skill_name"] for t in curr_tasks))
            new_weeks.append({
                "week_number": curr_week_num,
                "title": f"Week {curr_week_num}: {week_skills[0]} Accelerated Application" if week_skills else f"Week {curr_week_num}",
                "objective": f"Continue targeted practice and validation for {', '.join(week_skills)}.",
                "estimated_hours": round(curr_mins / 60.0, 1),
                "skills": week_skills,
                "status": "current" if curr_week_num == start_week_num else "locked",
                "completion_percentage": 0.0,
                "tasks": curr_tasks,
            })
            curr_week_num += 1
            curr_tasks = []
            curr_mins = 0

        curr_tasks.append(task)
        curr_mins += task["estimated_minutes"]

    if curr_tasks:
        week_skills = list(dict.fromkeys(t["skill_name"] for t in curr_tasks))
        new_weeks.append({
            "week_number": curr_week_num,
            "title": f"Week {curr_week_num}: Capstone & Final Verification",
            "objective": f"Validate mastery and finalize portfolio deliverables.",
            "estimated_hours": round(curr_mins / 60.0, 1),
            "skills": week_skills,
            "status": "current" if curr_week_num == start_week_num else "locked",
            "completion_percentage": 0.0,
            "tasks": curr_tasks,
        })

    # Update database: delete pending weeks & re-insert rescheduled weeks
    try:
        pending_ids = [pw["id"] for pw in pending_weeks]
        c.table(WEEKS).delete().in_("id", pending_ids).execute()
        
        rebalanced_count = (current_roadmap.get("adaptive_rebalance_count") or 0) + 1
        total_rebalanced_weeks = len(completed_weeks) + len(new_weeks)
        c.table(ROADMAPS).update({
            "total_weeks": total_rebalanced_weeks,
            "estimated_weeks": total_rebalanced_weeks,
            "weekly_hours_budget": hpw,
            "adaptive_rebalance_count": rebalanced_count,
            "last_rebalanced_at": now_iso,
            "updated_at": now_iso,
        }).eq("id", roadmap_id).execute()

        # Insert new weeks and tasks
        for nw in new_weeks:
            nw_row = {
                "roadmap_id": roadmap_id,
                "week_number": nw["week_number"],
                "title": nw["title"],
                "objective": nw["objective"],
                "estimated_hours": nw["estimated_hours"],
                "skills": nw["skills"],
                "status": nw["status"],
                "completion_percentage": 0.0,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            res_w = c.table(WEEKS).insert(nw_row).execute()
            inserted_w = res_w.data[0] if (res_w.data and len(res_w.data) > 0) else {**nw_row, "id": str(uuid.uuid4())}
            for seq_idx, t in enumerate(nw["tasks"]):
                t_row = {
                    "roadmap_week_id": inserted_w["id"],
                    "skill_slug": t["skill_slug"],
                    "skill_name": t["skill_name"],
                    "task_type": t["task_type"],
                    "title": t["title"],
                    "description": t["description"],
                    "estimated_minutes": t["estimated_minutes"],
                    "sequence_order": seq_idx + 1,
                    "status": "not_started",
                    "completion_percentage": 0.0,
                    "resources": t.get("resources", []),
                    "validation_method": t.get("validation_method", "self_check"),
                    "why_this_task": t.get("why_this_task", ""),
                    "created_at": now_iso,
                    "updated_at": now_iso,
                }
                c.table(TASKS).insert(t_row).execute()
    except Exception as e:
        logger.debug("Database update for reassess_and_adapt fallback: %s", e)

    return get_latest_roadmap(user_id)
