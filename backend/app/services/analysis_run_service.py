from typing import List, Dict, Optional
from fastapi import HTTPException
from supabase import Client
from datetime import datetime, timezone
import uuid
from ..core.supabase import get_supabase_client
from . import profile_service, evidence_service, industry_service, retrieval_service
from . import skill_engine as engine
from .signal_extractor import extract_signals
from .skill_taxonomy import get_all_skills

TABLE_RESULTS = "analysis_results"
TABLE_ASSESSMENTS = "skill_assessments"
TABLE_GAPS = "skill_gaps"
TABLE_SIGNALS = "skill_signals"


def _client() -> Client:
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    return c


def _get_or_create_skills_map() -> Dict[str, str]:
    """Return canonical_name -> id map"""
    c = _client()
    try:
        r = c.table("skills").select("id, canonical_name").execute()
        return {row["canonical_name"]: row["id"] for row in (r.data or [])}
    except Exception:
        return {}


async def run_analysis(user_id: str, target_role: str) -> dict:
    """
    Deterministic pipeline:
    1. Load profile
    2. Load target role (validated)
    3. Load evidence/projects/certs
    4. Load industry requirements for role
    5. Extract skill signals
    6. Calculate proficiency/confidence per skill
    7. Calculate gaps
    8. Calculate priorities
    9. Calculate readiness
    10. Persist results
    11. Update analysis_state to completed
    12. Return structured result
    """
    # 1. Profile
    try:
        profile = profile_service.get_profile(user_id)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=400, detail="Profile not found — complete /profile/setup first")
        raise
    if not profile:
        raise HTTPException(status_code=400, detail="Profile not found")

    # 2. Target role already validated by caller, but ensure not empty
    if not target_role or len(target_role.strip()) < 2:
        raise HTTPException(status_code=400, detail="Target role required")

    # 3. Evidence
    try:
        evidence = evidence_service.list_evidence(user_id)
        projects = evidence_service.list_projects(user_id)
        certs = evidence_service.list_certs(user_id)
    except HTTPException as e:
        if e.status_code == 503:
            raise HTTPException(status_code=503, detail="Evidence tables not configured — run 002_create_evidence.sql")
        raise

    # Check at least some evidence or profile
    has_any_evidence = len(evidence) > 0 or len(projects) > 0 or len(certs) > 0
    # Allow analysis even with weak evidence, but will have low confidence

    # 4. Industry requirements for role
    try:
        requirements = industry_service.list_by_role(target_role)
    except HTTPException as e:
        if e.status_code == 503:
            raise HTTPException(status_code=503, detail="Industry knowledge not configured — run 003_industry_knowledge.sql")
        raise
    if not requirements:
        # If no requirements for custom role, treat as empty — still create analysis with 0 gaps
        requirements = []

    # 5. Extract signals
    signals = extract_signals(evidence, projects, certifications=certs)
    # Group signals by canonical skill
    from collections import defaultdict
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for s in signals:
        grouped[s["canonical_name"]].append(s)

    # Load skills map for IDs
    skills_map = _get_or_create_skills_map()
    all_skills = {row["canonical_name"]: row for row in get_all_skills(_client())} if skills_map else {}

    # 6-7. Calculate assessments per required skill + also for any extra skills with signals
    # For gap calculation, we need required_level per skill
    # Build required_level map from industry requirements
    required_map: Dict[str, dict] = {}
    for req in requirements:
        # Normalize skill to canonical if possible
        # For prototype, assume req["skill"] maps to canonical via lower
        # We should try to normalize
        from .skill_taxonomy import normalize_skill
        c = _client()
        canonical = normalize_skill(req["skill"], c)
        key = canonical or req["skill"].lower().replace(" ", "_")
        # Use required_level if exists, else importance as proxy
        required_map[key] = {
            "importance": float(req.get("importance", 0.5)),
            "demand": float(req.get("demand", 0.5)),
            "interview": float(req.get("interview_relevance", 0.5)),
            "required_level": float(req.get("required_level", req.get("importance", 0.75))),
            "skill": req["skill"],
            "category": req.get("skill_category", ""),
            "description": req.get("description", ""),
        }

    # Also include any skills that have signals but not in requirements (for completeness)
    for canonical in grouped.keys():
        if canonical not in required_map:
            # Add with low required_level so gap is 0? Or mark as extra?
            # For now, treat extra skills as not required (gap 0, but still assess)
            required_map[canonical] = {
                "importance": 0.3,
                "demand": 0.3,
                "interview": 0.3,
                "required_level": 0.5,
                "skill": canonical,
                "category": all_skills.get(canonical, {}).get("category", "Other"),
                "description": "",
            }

    assessments = []
    gaps = []
    # For persistence, we will collect signals to save
    signals_to_save = []

    for canonical, sigs in grouped.items():
        # Calculate proficiency
        prof, ev_weight, ev_count, avg_sig = engine.proficiency(sigs)
        # Source diversity: distinct source_type
        diversity = len(set(s["source_type"] for s in sigs))
        conf, w_norm, d_norm = engine.confidence(ev_weight, diversity)
        # Find required for this skill
        req = required_map.get(canonical)
        if req:
            required_level = req["required_level"]
            gap_val = engine.gap(prof, required_level)
            priority = engine.gap_priority(gap_val, req["importance"], req["demand"], conf, req["interview"])
            explanation = engine.explain_proficiency(prof, conf, ev_count, diversity)
            # Assessment
            assessments.append({
                "canonical_name": canonical,
                "proficiency": prof,
                "confidence": conf,
                "evidence_weight": ev_weight,
                "source_diversity": float(diversity),
                "evidence_count": ev_count,
                "explanation": explanation,
                "required_level": required_level,
                "gap": gap_val,
                "importance": req["importance"],
                "demand": req["demand"],
                "interview": req["interview"],
                "priority": priority,
                "signals": sigs,
            })
            # Gap
            if gap_val > 0 or True:  # always create gap entry for traceability, but priority 0 for covered
                gaps.append({
                    "canonical_name": canonical,
                    "required_level": required_level,
                    "current_proficiency": prof,
                    "confidence": conf,
                    "gap": gap_val,
                    "importance": req["importance"],
                    "demand": req["demand"],
                    "interview": req["interview"],
                    "priority": priority,
                    "explanation": engine.explain_gap(canonical, prof, required_level, gap_val, req["importance"], conf),
                })
        else:
            # No requirement, just assessment
            prof, ev_weight, ev_count, _ = engine.proficiency(sigs)
            diversity = len(set(s["source_type"] for s in sigs))
            conf, _, _ = engine.confidence(ev_weight, diversity)
            assessments.append({
                "canonical_name": canonical,
                "proficiency": prof,
                "confidence": conf,
                "evidence_weight": ev_weight,
                "source_diversity": float(diversity),
                "evidence_count": ev_count,
                "explanation": engine.explain_proficiency(prof, conf, ev_count, diversity),
                "required_level": 0.5,
                "gap": 0,
                "importance": 0.3,
                "demand": 0.3,
                "interview": 0.3,
                "priority": 0,
                "signals": sigs,
            })

    # For required skills with NO signals, create assessment with proficiency 0 and low confidence
    for canonical, req in required_map.items():
        if canonical not in grouped:
            prof = 0.0
            ev_weight = 0.0
            ev_count = 0
            diversity = 0
            conf, _, _ = engine.confidence(ev_weight, diversity)
            gap_val = engine.gap(prof, req["required_level"])
            priority = engine.gap_priority(gap_val, req["importance"], req["demand"], conf, req["interview"])
            assessments.append({
                "canonical_name": canonical,
                "proficiency": prof,
                "confidence": conf,
                "evidence_weight": ev_weight,
                "source_diversity": 0,
                "evidence_count": 0,
                "explanation": "Insufficient evidence to confidently assess this skill. No supporting evidence was found.",
                "required_level": req["required_level"],
                "gap": gap_val,
                "importance": req["importance"],
                "demand": req["demand"],
                "interview": req["interview"],
                "priority": priority,
                "signals": [],
            })
            gaps.append({
                "canonical_name": canonical,
                "required_level": req["required_level"],
                "current_proficiency": prof,
                "confidence": conf,
                "gap": gap_val,
                "importance": req["importance"],
                "demand": req["demand"],
                "interview": req["interview"],
                "priority": priority,
                "explanation": engine.explain_gap(canonical, prof, req["required_level"], gap_val, req["importance"], conf),
            })

    # Sort gaps by priority descending
    gaps.sort(key=lambda x: x["priority"], reverse=True)

    # 8-9. Readiness components
    skill_comp = engine.aggregate_skill_component(
        [{"canonical_name": a["canonical_name"], "proficiency": a["proficiency"]} for a in assessments],
        requirements,
    )
    industry_comp = engine.aggregate_industry_component(
        [{"gap": g["gap"], "importance": g["importance"]} for g in gaps]
    )
    evidence_comp = engine.aggregate_evidence_component(assessments)
    readiness = engine.readiness(skill_comp, industry_comp, evidence_comp)
    readiness_expl = engine.explain_readiness(skill_comp, industry_comp, evidence_comp, readiness)

    # 10. Persist
    c = _client()
    now = datetime.now(timezone.utc).isoformat()
    engine_version = engine.ENGINE_VERSION

    # Create analysis_results
    result_data = {
        "user_id": user_id,
        "target_role": target_role,
        "skill_component": skill_comp,
        "industry_component": industry_comp,
        "evidence_component": evidence_comp,
        "readiness_score": readiness,
        "assessment_count": len(assessments),
        "gap_count": len([g for g in gaps if g["gap"] > 0]),
        "engine_version": engine_version,
        "created_at": now,
        "updated_at": now,
    }
    try:
        r = c.table("analysis_results").insert(result_data).execute()
        analysis_id = r.data[0]["id"] if r.data and len(r.data) > 0 else str(uuid.uuid4())
        # If insert returned data, use it
        if r.data and len(r.data) > 0:
            result_data = r.data[0]
            analysis_id = result_data["id"]
        else:
            result_data["id"] = analysis_id
    except Exception as e:
        # Handle table not found
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Analysis tables not found — run backend/supabase/005_skill_engine.sql")
        if "permission denied" in m:
            raise HTTPException(status_code=503, detail="Database permission denied for analysis_results — run GRANTs")
        raise HTTPException(status_code=500, detail=f"Failed to save analysis: {str(e)[:200]}")

    # Persist skill_assessments
    for a in assessments:
        skill_id = skills_map.get(a["canonical_name"])
        if not skill_id:
            # Try to find via get_all_skills
            # If not found, skip (should not happen as we seeded)
            continue
        row = {
            "user_id": user_id,
            "skill_id": skill_id,
            "proficiency": a["proficiency"],
            "confidence": a["confidence"],
            "evidence_weight": a["evidence_weight"],
            "source_diversity": a["source_diversity"],
            "evidence_count": a["evidence_count"],
            "explanation": a["explanation"],
        }
        try:
            c.table("skill_assessments").insert(row).execute()
        except Exception:
            pass  # don't fail whole analysis if one insert fails

    # Persist skill_gaps
    for g in gaps:
        skill_id = skills_map.get(g["canonical_name"])
        if not skill_id:
            continue
        row = {
            "user_id": user_id,
            "analysis_result_id": analysis_id,
            "skill_id": skill_id,
            "target_role": target_role,
            "required_level": g["required_level"],
            "current_proficiency": g["current_proficiency"],
            "confidence": g["confidence"],
            "gap": g["gap"],
            "importance": g["importance"],
            "demand": g["demand"],
            "interview_relevance": g["interview"],
            "priority_score": g["priority"],
            "explanation": g["explanation"],
        }
        try:
            c.table("skill_gaps").insert(row).execute()
        except Exception:
            pass

    # Persist skill_signals
    for sig in signals:
        skill_id = skills_map.get(sig["canonical_name"])
        if not skill_id:
            continue
        row = {
            "user_id": user_id,
            "skill_id": skill_id,
            "evidence_id": sig.get("evidence_id"),
            "project_id": sig.get("project_id"),
            "certification_id": sig.get("certification_id"),
            "source_type": sig["source_type"],
            "signal_value": sig["signal_value"],
            "source_reliability": sig["source_reliability"],
            "explanation": sig["explanation"],
            "metadata": sig.get("metadata") or {},
        }
        try:
            c.table("skill_signals").insert(row).execute()
        except Exception:
            pass

    # Also update analysis_state to completed
    try:
        from .analysis_service import upsert_state
        # Get retrieval for this role to store
        from .retrieval_service import retrieve
        retr = await retrieve(target_role, None, top_k=10)
        upsert_state(user_id, target_role, "completed", retr)
    except Exception:
        pass

    # Build structured result for response
    return {
        "id": analysis_id,
        "user_id": user_id,
        "target_role": target_role,
        "readiness_score": readiness,
        "skill_component": skill_comp,
        "industry_component": industry_comp,
        "evidence_component": evidence_comp,
        "readiness_explanation": readiness_expl,
        "assessment_count": len(assessments),
        "gap_count": len([g for g in gaps if g["gap"] > 0]),
        "engine_version": engine_version,
        "assessments": [
            {
                "skill": a["canonical_name"],
                "display_name": a["canonical_name"],
                "proficiency": a["proficiency"],
                "confidence": a["confidence"],
                "required_level": a["required_level"],
                "gap": a["gap"],
                "importance": a["importance"],
                "demand": a["demand"],
                "interview_relevance": a["interview"],
                "priority": a["priority"],
                "evidence_count": a["evidence_count"],
                "source_diversity": a["source_diversity"],
                "explanation": a["explanation"],
            }
            for a in sorted(assessments, key=lambda x: x["priority"], reverse=True)
        ],
        "gaps": sorted(gaps, key=lambda x: x["priority"], reverse=True),
        "created_at": result_data.get("created_at", now),
    }
