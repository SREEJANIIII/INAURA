import math
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from fastapi import HTTPException
from supabase import Client
from ..core.supabase import get_supabase_client
from . import profile_service
from .roadmap_catalog import (
    get_resources_for_skill,
    get_template_for_skill,
    get_base_hours,
    get_item_type,
    ENGINE_VERSION,
)

# Tables
ROADMAPS = "roadmaps"
ITEMS = "roadmap_items"
RESOURCES = "roadmap_resources"
MILESTONES = "roadmap_milestones"
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
    # Take up to max_items
    limited = gaps[:max_items]
    # For prototype: 3-6 items, but if <3 gaps available we return all
    return limited

def estimate_hours_for_gap(canonical: str, gap: float, importance: float) -> float:
    """Heuristic: base_hours + gap*6 + importance*2, clamped reasonable."""
    base = get_base_hours(canonical)
    # Configurable heuristic, not validated
    extra = gap * 6 + importance * 2
    total = base + extra
    # Round to nearest 0.5 heuristic? Keep float with 1 decimal
    total = round(total, 1)
    # Clamp to avoid absurd
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
    # Use percentages for readability
    cur_pct = round(current * 100)
    req_pct = round(required * 100)
    gap_pct = round(gap * 100)
    conf_pct = round(confidence * 100)
    # Determine phrasing based on importance/demand
    if gap == 0:
        return f"{display_name} is already covered (current {cur_pct}% meets required {req_pct}% for {target_role}). No learning item needed — this skill is excluded from the roadmap."
    # Build explanation
    parts = []
    parts.append(f"{display_name} is prioritized because your current proficiency ({cur_pct}%) is below the required level ({req_pct}%, gap {gap_pct}%) for {target_role}.")
    # Add importance context
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
    # Deterministic title per skill
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
    # Add context
    parts.append(f"Focused on {display_name} for {target_role} — curated prototype resources, not live industry data.")
    return " ".join(parts)

def _load_profile_hours(user_id: str) -> int:
    prof = profile_service.get_profile(user_id)
    if not prof:
        raise HTTPException(status_code=400, detail="Profile not found — complete /profile/setup first. hours_per_week is required to estimate roadmap timeline.")
    hpw = prof.get("hours_per_week")
    if hpw is None or hpw == 0:
        raise HTTPException(status_code=400, detail="Update your weekly availability to create a realistic timeline. Set hours_per_week in your profile (1-80).")
    try:
        h = int(hpw)
    except:
        raise HTTPException(status_code=400, detail="Update your weekly availability to create a realistic timeline. hours_per_week must be between 1 and 80.")
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
        # Use joined skills for display_name
        r = c.table(SKILL_GAPS).select("*, skills(canonical_name, display_name, category)").eq("user_id", user_id).eq("analysis_result_id", analysis_id).order("priority_score", desc=True).execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Skill gaps table not found — run 005_skill_engine.sql")
        raise HTTPException(status_code=500, detail="Failed to fetch gaps")

def _get_skills_map() -> Dict[str, dict]:
    c = _client()
    try:
        r = c.table(SKILLS).select("*").execute()
        return {row["id"]: row for row in (r.data or [])}
    except Exception:
        return {}

async def generate_roadmap(user_id: str, target_role: Optional[str] = None) -> dict:
    """Deterministic roadmap generation pipeline."""
    c = _client()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Load profile hours
    hours_per_week = _load_profile_hours(user_id)

    # 2. Latest analysis
    analysis = _get_latest_analysis(user_id)
    analysis_id = analysis["id"]
    role = target_role.strip() if target_role and target_role.strip() else analysis.get("target_role")
    if not role or len(role.strip()) < 2:
        role = analysis.get("target_role") or "Software Engineer"
    role = role.strip()

    # 3. Load gaps
    gaps = _get_gaps_for_analysis(user_id, analysis_id)
    # 4. Remove zero gaps
    filtered = filter_and_sort_gaps(gaps)
    if not filtered:
        raise HTTPException(status_code=400, detail="You're currently meeting the assessed requirements for this role. Keep building evidence and stay industry-ready. No priority gaps to generate a roadmap from.")
    # 5. Sort already done, 6. Limit to top 3-6
    selected = limit_gaps(filtered, max_items=6)
    # Ensure 3-6 but if selected <3, we still generate that many (deterministic)
    # But if >6, truncate to 6
    # If filtered has 7+ gaps, we take 6 highest priority

    # Load skills map for display
    skills_map = _get_skills_map()

    # Build items data in memory first to compute total hours
    items_data = []
    for idx, gap in enumerate(selected):
        skill_id = gap.get("skill_id")
        skill_info = skills_map.get(skill_id, {})
        canonical = skill_info.get("canonical_name") or gap.get("skills", {}).get("canonical_name") or gap.get("canonical_name") or "unknown"
        display_name = skill_info.get("display_name") or gap.get("skills", {}).get("display_name") or canonical
        # fallback: canonical -> display via skills_map values scan
        if not display_name or display_name == "unknown":
            # try to find by skill_id in gap's skills
            if gap.get("skills"):
                display_name = gap["skills"].get("display_name") or gap["skills"].get("canonical_name") or canonical
            else:
                display_name = canonical.replace("_", " ").title()
        category = skill_info.get("category") or gap.get("skills", {}).get("category") or ""
        # Values
        current = float(gap.get("current_proficiency", 0))
        required = float(gap.get("required_level", 0.75))
        gap_val = float(gap.get("gap", 0))
        importance = float(gap.get("importance", 0.5))
        demand = float(gap.get("demand", 0.5))
        interview = float(gap.get("interview_relevance", 0.5))
        confidence = float(gap.get("confidence", 0))
        priority_score = float(gap.get("priority_score", 0))
        # Estimate hours
        est_hours = estimate_hours_for_gap(canonical, gap_val, importance)
        # Why it matters
        why = generate_why_it_matters(display_name, current, required, gap_val, importance, demand, interview, confidence, role)
        # Title/description
        title = generate_item_title(display_name, canonical)
        desc = generate_item_description(canonical, display_name, role)
        item_type = get_item_type(canonical)
        # priority integer: rank priority (1 highest) but also store scaled priority_score for tie? Use int(round(priority_score))
        priority_int = int(round(priority_score))
        # Ensure priority ordering matches sequence: keep priority_int but sequence_order is deterministic rank
        items_data.append({
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
        })

    # 8. Estimate total hours, 9. Milestones, 10-11 weeks
    total_hours = round(sum(it["estimated_hours"] for it in items_data), 1)
    estimated_weeks = estimate_weeks(total_hours, hours_per_week)

    # 12. Persist roadmap
    # Archive previous active roadmaps
    try:
        c.table(ROADMAPS).update({"status": "archived", "updated_at": now}).eq("user_id", user_id).eq("status", "active").execute()
    except Exception:
        pass

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
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Roadmap tables not found — run backend/supabase/006_roadmap.sql")
        if "permission denied" in m:
            raise HTTPException(status_code=503, detail="Database permission denied for roadmaps — run GRANTs")
        raise HTTPException(status_code=500, detail=f"Failed to create roadmap: {str(e)[:200]}")
    roadmap_id = roadmap["id"]

    # Persist items and resources
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
            if r2.data and len(r2.data) > 0:
                persisted = r2.data[0]
            else:
                persisted = row
                persisted["id"] = str(uuid.uuid4())
        except Exception as e:
            # If skill_id invalid, skip but don't fail whole roadmap
            continue
        persisted_items.append(persisted)
        # Resources 1-3 per item
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

    # Generate milestones — group items
    n = len(persisted_items)
    if n == 0:
        milestones_created = []
    else:
        if n >= 3:
            num_milestones = 3
        elif n == 2:
            num_milestones = 2
        else:
            num_milestones = 1
        # Distribute items evenly
        per = math.ceil(n / num_milestones)
        milestones_created = []
        for mi in range(num_milestones):
            start = mi * per
            end = min(start + per, n)
            group = persisted_items[start:end]
            if not group:
                continue
            target_hours = round(sum(float(g.get("estimated_hours", 0)) for g in group), 1)
            title, desc = MILESTONE_TITLES[mi] if mi < len(MILESTONE_TITLES) else (f"Milestone {mi+1}", "Continue your roadmap.")
            mrow = {
                "roadmap_id": roadmap_id,
                "title": title,
                "description": desc,
                "sequence_order": mi + 1,
                "target_hours": target_hours,
                "status": "not_started",
                "created_at": now,
                "updated_at": now,
            }
            try:
                rm = c.table(MILESTONES).insert(mrow).execute()
                if rm.data and len(rm.data) > 0:
                    milestones_created.append(rm.data[0])
                else:
                    mrow["id"] = str(uuid.uuid4())
                    milestones_created.append(mrow)
            except Exception:
                pass

    # Fetch full roadmap with progress
    progress = calculate_progress(persisted_items)

    # Return structured roadmap
    return {
        "id": roadmap_id,
        "user_id": user_id,
        "analysis_result_id": analysis_id,
        "target_role": role,
        "title": roadmap_title,
        "status": "active",
        "engine_version": ENGINE_VERSION,
        "total_estimated_hours": total_hours,
        "estimated_weeks": estimated_weeks,
        "hours_per_week": hours_per_week,
        "progress": progress,
        "created_at": roadmap.get("created_at", now),
        "updated_at": roadmap.get("updated_at", now),
        "items": persisted_items,
        "milestones": milestones_created,
    }

def get_latest_roadmap(user_id: str) -> dict:
    c = _client()
    try:
        r = c.table(ROADMAPS).select("*").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
        if not r.data or len(r.data) == 0:
            raise HTTPException(status_code=404, detail="No roadmap found — generate your personalized roadmap first.")
        roadmap = r.data[0]
        # Attach progress
        # Fetch items for progress
        items = get_items_for_roadmap(user_id, roadmap["id"])
        roadmap["progress"] = calculate_progress(items)
        # Also fetch profile hours_per_week for context
        try:
            prof = profile_service.get_profile(user_id)
            roadmap["hours_per_week"] = prof.get("hours_per_week") if prof else None
        except:
            roadmap["hours_per_week"] = None
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
    # Verify ownership
    try:
        r0 = c.table(ROADMAPS).select("id").eq("id", roadmap_id).eq("user_id", user_id).single().execute()
        if not r0.data:
            raise HTTPException(status_code=404, detail="Roadmap not found")
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "no rows" in m or "not found" in m or "0 rows" in m:
            raise HTTPException(status_code=404, detail="Roadmap not found or not owned by user")
        raise
    try:
        r = c.table(ITEMS).select("*, skills(canonical_name, display_name, category), roadmap_resources(*)").eq("roadmap_id", roadmap_id).order("sequence_order").execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m:
            raise HTTPException(status_code=503, detail="Roadmap items table not found")
        raise HTTPException(status_code=500, detail="Failed to fetch roadmap items")

def get_all_items_for_user(user_id: str) -> List[dict]:
    c = _client()
    try:
        # Get latest roadmap id
        roadmap = get_latest_roadmap(user_id)
        return get_items_for_roadmap(user_id, roadmap["id"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch items")

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
        # fallback list check
        try:
            rr = c.table(ROADMAPS).select("id").eq("user_id", user_id).eq("id", roadmap_id).execute()
            if not rr.data or len(rr.data)==0:
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
    c = _client()
    try:
        roadmap = get_latest_roadmap(user_id)
        return get_milestones_for_roadmap(user_id, roadmap["id"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to fetch milestones")

def update_roadmap_item(user_id: str, item_id: str, payload: dict) -> dict:
    c = _client()
    # Verify ownership via roadmap
    try:
        # Fetch item with roadmap check
        r = c.table(ITEMS).select("*, roadmaps!inner(user_id)").eq("id", item_id).execute()
        # Supabase join check: alternative manual
        if not r.data or len(r.data)==0:
            # fallback: fetch item then check roadmap ownership
            rr = c.table(ITEMS).select("*").eq("id", item_id).single().execute()
            if not rr.data:
                raise HTTPException(status_code=404, detail="Roadmap item not found")
            roadmap_id = rr.data.get("roadmap_id")
            # Check roadmap ownership
            r2 = c.table(ROADMAPS).select("user_id").eq("id", roadmap_id).single().execute()
            if not r2.data or r2.data.get("user_id") != user_id:
                raise HTTPException(status_code=403, detail="Not authorized to update this roadmap item")
            item = rr.data
        else:
            # Check user_id via joined roadmaps
            row = r.data[0]
            # roadmaps join may be nested
            roadmaps = row.get("roadmaps")
            owner = None
            if isinstance(roadmaps, dict):
                owner = roadmaps.get("user_id")
            elif isinstance(roadmaps, list) and len(roadmaps)>0:
                owner = roadmaps[0].get("user_id")
            if owner and owner != user_id:
                raise HTTPException(status_code=403, detail="Not authorized")
            item = row
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "no rows" in m:
            raise HTTPException(status_code=404, detail="Roadmap item not found")
        raise HTTPException(status_code=500, detail="Failed to fetch roadmap item")
    # Validate allowed updates only status and completion_percentage
    allowed_status = {"not_started","in_progress","completed"}
    update_data = {}
    if "status" in payload:
        st = payload["status"]
        if st not in allowed_status:
            raise HTTPException(status_code=400, detail="Invalid status. Allowed: not_started, in_progress, completed")
        update_data["status"] = st
        # Auto adjust completion_percentage if status completed
        if st == "completed" and "completion_percentage" not in payload:
            update_data["completion_percentage"] = 100
        if st == "not_started" and "completion_percentage" not in payload:
            # keep existing? don't auto change
            pass
    if "completion_percentage" in payload:
        cp = validate_completion_percentage(payload["completion_percentage"])
        update_data["completion_percentage"] = cp
        # Auto update status if 100 => completed, if 0 => not_started?
        # Keep explicit status if provided, else infer
        if "status" not in payload:
            if cp == 100:
                update_data["status"] = "completed"
            elif cp > 0:
                update_data["status"] = "in_progress"
            else:
                update_data["status"] = "not_started"
    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update. Allowed: status, completion_percentage")
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    # Prevent changing user_id, roadmap ownership, etc. — only update those two fields
    try:
        r3 = c.table(ITEMS).update(update_data).eq("id", item_id).execute()
        if r3.data and len(r3.data)>0:
            updated = r3.data[0]
        else:
            # fetch updated
            rr = c.table(ITEMS).select("*").eq("id", item_id).single().execute()
            updated = rr.data
        # Also update roadmap updated_at
        try:
            roadmap_id = updated.get("roadmap_id") or item.get("roadmap_id")
            c.table(ROADMAPS).update({"updated_at": update_data["updated_at"]}).eq("id", roadmap_id).execute()
        except:
            pass
        return updated
    except HTTPException:
        raise
    except Exception as e:
        if "permission denied" in str(e).lower():
            raise HTTPException(status_code=503, detail="Permission denied")
        raise HTTPException(status_code=500, detail=f"Failed to update item: {str(e)[:200]}")
