"""P0 #2: institution / course / curriculum supply service.

Reliable supply-side representation only: institutions teach courses, courses
contain modules, courses/modules teach skills, trainers hold skills. There is
deliberately NO demand comparison, scoring, ranking, or recommendation logic
here — that belongs to later phases (alignment engine, district planner).

Canonical skills come exclusively from skill_taxonomy (single source of
truth). Raw curriculum phrases are preserved as source_concept; unmapped
concepts keep mapping_status='unmapped' and are never forced or discarded —
the same philosophy as the labour-market implementation.

Coverage scale (documented, no arbitrary numeric scores):
  introductory  — awareness + guided exercises (can follow a tutorial)
  intermediate  — independent coursework application (can build with docs)
  advanced      — production-grade / project ownership depth
The same scale doubles as trainer teaching-depth proficiency.
"""

from fastapi import HTTPException
from supabase import Client
from datetime import datetime, timezone

from ..core.supabase import get_supabase_client
from .skill_taxonomy import get_canonical_skill

TABLES_MIGRATION_HINT = "Institution supply tables missing — run backend/supabase/031_institution_course_supply.sql"

INSTITUTION_TYPES = frozenset({
    "iti", "polytechnic", "college", "university",
    "skill_training_centre", "training_institute", "other",
})
INSTITUTION_STATUSES = frozenset({"active", "suspended", "archived"})
COURSE_STATUSES = frozenset({"draft", "active", "archived"})
MODULE_STATUSES = frozenset({"draft", "active", "archived"})
TRAINER_STATUSES = frozenset({"active", "inactive", "archived"})
COVERAGE_LEVELS = frozenset({"introductory", "intermediate", "advanced"})
SKILL_IMPORTANCE = frozenset({"required", "preferred"})
DELIVERY_MODES = frozenset({"online", "offline", "hybrid"})

DEMO_ORIGIN = "demo_seeded"
DEMO_INSTITUTION_CODE = "INAURA-DEMO-TC"


def _ensure_client() -> Client:
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured — set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env",
        )
    return client


def _table_missing_msg(e: Exception) -> bool:
    m = str(e).lower()
    return "could not find table" in m or "pgrst205" in m


def _missing_table() -> HTTPException:
    return HTTPException(status_code=503, detail=TABLES_MIGRATION_HINT)


def _is_unique_violation(e: Exception) -> bool:
    m = str(e).lower()
    return "duplicate key" in m or "23505" in m or "already exists" in m


def _duplicate(detail: str) -> HTTPException:
    return HTTPException(status_code=409, detail=detail)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Canonical skill resolution (taxonomy reuse only — no second mapping system)
# ---------------------------------------------------------------------------

def resolve_skill(source_concept: str, client: Client | None = None) -> dict:
    """Resolve a raw curriculum phrase to the canonical taxonomy.

    Returns {source_concept, mapping_status, canonical_skill_slug,
    canonical_display, skill_id, mapping_rationale}. Unmapped concepts are
    preserved verbatim with mapping_status='unmapped' and skill_id None —
    never forced onto an unrelated skill. skill_id is resolved best-effort
    against public.skills and stays None when the DB row is absent.
    """
    concept = " ".join(str(source_concept or "").split())
    if not concept:
        raise HTTPException(status_code=400, detail="source_concept is required")
    canon = get_canonical_skill(concept)
    if canon is None:
        return {
            "source_concept": concept,
            "mapping_status": "unmapped",
            "canonical_skill_slug": None,
            "canonical_display": None,
            "skill_id": None,
            "mapping_rationale": "No clean canonical mapping; source concept preserved without forcing",
        }
    skill_id = None
    if client is not None:
        try:
            resp = client.table("skills").select("id").eq("canonical_name", canon.id).execute()
            rows = resp.data or []
            if rows:
                skill_id = rows[0].get("id")
        except Exception:
            skill_id = None
    return {
        "source_concept": concept,
        "mapping_status": "mapped",
        "canonical_skill_slug": canon.id,
        "canonical_display": canon.display_name,
        "skill_id": skill_id,
        "mapping_rationale": "Canonical mapping via INAURA skill taxonomy",
    }


# ---------------------------------------------------------------------------
# Institutions
# ---------------------------------------------------------------------------

def _validate_enum(value, allowed: frozenset, field: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field}: {value!r}. Allowed: {sorted(allowed)}",
        )


def create_institution(payload: dict) -> dict:
    client = _ensure_client()
    name = str(payload.get("name") or "").strip()
    if len(name) < 2 or len(name) > 200:
        raise HTTPException(status_code=400, detail="Institution name must be 2–200 characters")
    _validate_enum(payload.get("institution_type", "other"), INSTITUTION_TYPES, "institution_type")
    _validate_enum(payload.get("status", "active"), INSTITUTION_STATUSES, "status")
    now = _now()
    row = {
        "name": name,
        "code": payload.get("code"),
        "institution_type": payload.get("institution_type", "other"),
        "district": payload.get("district"),
        "state": payload.get("state"),
        "country": payload.get("country"),
        "city": payload.get("city"),
        "website": payload.get("website"),
        "description": payload.get("description"),
        "status": payload.get("status", "active"),
        "data_origin": payload.get("data_origin", "source_data"),
        "created_at": now,
        "updated_at": now,
    }
    if row["data_origin"] not in ("source_data", "inaura_derived", "demo_seeded"):
        raise HTTPException(status_code=400, detail="Invalid data_origin")
    try:
        resp = client.table("institutions").insert(row).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail="Duplicate institution (same name/locale or code)")
        raise HTTPException(status_code=500, detail=f"Failed to create institution: {str(e)[:200]}")
    created = (resp.data or [None])[0]
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create institution")
    return created


def get_institution(institution_id: str) -> dict:
    client = _ensure_client()
    try:
        resp = client.table("institutions").select("*").eq("id", institution_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to fetch institution")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Institution not found")
    return rows[0]


def update_institution(institution_id: str, patch: dict) -> dict:
    client = _ensure_client()
    get_institution(institution_id)
    allowed = {"name", "code", "institution_type", "district", "state", "country",
               "city", "website", "description", "status"}
    clean = {k: v for k, v in (patch or {}).items() if k in allowed}
    if "name" in clean and not (2 <= len(str(clean["name"]).strip()) <= 200):
        raise HTTPException(status_code=400, detail="Institution name must be 2–200 characters")
    _validate_enum(clean.get("institution_type"), INSTITUTION_TYPES, "institution_type")
    _validate_enum(clean.get("status"), INSTITUTION_STATUSES, "status")
    if not clean:
        return get_institution(institution_id)
    clean["updated_at"] = _now()
    try:
        resp = client.table("institutions").update(clean).eq("id", institution_id).execute()
    except Exception as e:
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail="Duplicate institution (same name/locale or code)")
        raise HTTPException(status_code=500, detail="Failed to update institution")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Institution not found")
    return rows[0]


def list_institutions(district: str | None = None, state: str | None = None,
                      institution_type: str | None = None,
                      status: str | None = None) -> list:
    client = _ensure_client()
    _validate_enum(institution_type, INSTITUTION_TYPES, "institution_type")
    _validate_enum(status, INSTITUTION_STATUSES, "status")
    try:
        query = client.table("institutions").select("*")
        if district:
            query = query.eq("district", district)
        if state:
            query = query.eq("state", state)
        if institution_type:
            query = query.eq("institution_type", institution_type)
        if status:
            query = query.eq("status", status)
        resp = query.execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to list institutions")
    return resp.data or []


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

def create_course(institution_id: str, payload: dict) -> dict:
    client = _ensure_client()
    get_institution(institution_id)
    name = str(payload.get("name") or "").strip()
    if len(name) < 2 or len(name) > 200:
        raise HTTPException(status_code=400, detail="Course name must be 2–200 characters")
    _validate_enum(payload.get("status", "draft"), COURSE_STATUSES, "status")
    _validate_enum(payload.get("delivery_mode"), DELIVERY_MODES, "delivery_mode")
    now = _now()
    row = {
        "institution_id": institution_id,
        "name": name,
        "code": payload.get("code"),
        "description": payload.get("description"),
        "level": payload.get("level"),
        "duration_text": payload.get("duration_text"),
        "delivery_mode": payload.get("delivery_mode"),
        "status": payload.get("status", "draft"),
        "data_origin": payload.get("data_origin", "source_data"),
        "created_at": now,
        "updated_at": now,
    }
    if row["data_origin"] not in ("source_data", "inaura_derived", "demo_seeded"):
        raise HTTPException(status_code=400, detail="Invalid data_origin")
    # Service-level duplicate guard (DB unique index backstops in production).
    try:
        existing = client.table("courses").select("id,name,code").eq("institution_id", institution_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to check duplicate course")
    for other in existing.data or []:
        if str(other.get("name") or "").strip().lower() == name.lower():
            raise _duplicate("Duplicate course in this institution")
        if row["code"] and other.get("code") and str(other["code"]) == str(row["code"]):
            raise _duplicate("Duplicate course code in this institution")
    try:
        resp = client.table("courses").insert(row).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail="Duplicate course in this institution")
        raise HTTPException(status_code=500, detail=f"Failed to create course: {str(e)[:200]}")
    created = (resp.data or [None])[0]
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create course")
    return created


def get_course(course_id: str) -> dict:
    client = _ensure_client()
    try:
        resp = client.table("courses").select("*").eq("id", course_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to fetch course")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Course not found")
    return rows[0]


def update_course(course_id: str, patch: dict) -> dict:
    client = _ensure_client()
    get_course(course_id)
    allowed = {"name", "code", "description", "level", "duration_text", "delivery_mode", "status"}
    clean = {k: v for k, v in (patch or {}).items() if k in allowed}
    if "name" in clean and not (2 <= len(str(clean["name"]).strip()) <= 200):
        raise HTTPException(status_code=400, detail="Course name must be 2–200 characters")
    _validate_enum(clean.get("status"), COURSE_STATUSES, "status")
    _validate_enum(clean.get("delivery_mode"), DELIVERY_MODES, "delivery_mode")
    if not clean:
        return get_course(course_id)
    if "name" in clean:
        course = get_course(course_id)
        try:
            siblings = client.table("courses").select("id,name").eq(
                "institution_id", course["institution_id"]).execute()
        except Exception as e:
            if _table_missing_msg(e):
                raise _missing_table()
            raise HTTPException(status_code=500, detail="Failed to check duplicate course")
        for other in siblings.data or []:
            if str(other.get("id")) != str(course_id) and \
                    str(other.get("name") or "").strip().lower() == str(clean["name"]).strip().lower():
                raise _duplicate("Duplicate course in this institution")
    clean["updated_at"] = _now()
    try:
        resp = client.table("courses").update(clean).eq("id", course_id).execute()
    except Exception as e:
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail="Duplicate course in this institution")
        raise HTTPException(status_code=500, detail="Failed to update course")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Course not found")
    return rows[0]


def list_courses(institution_id: str, status: str | None = None) -> list:
    client = _ensure_client()
    get_institution(institution_id)
    _validate_enum(status, COURSE_STATUSES, "status")
    try:
        query = client.table("courses").select("*").eq("institution_id", institution_id)
        if status:
            query = query.eq("status", status)
        resp = query.order("name").execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to list courses")
    return resp.data or []


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------

def create_module(course_id: str, payload: dict) -> dict:
    client = _ensure_client()
    get_course(course_id)
    name = str(payload.get("name") or "").strip()
    if len(name) < 2 or len(name) > 200:
        raise HTTPException(status_code=400, detail="Module name must be 2–200 characters")
    _validate_enum(payload.get("status", "draft"), MODULE_STATUSES, "status")
    try:
        sequence = int(payload.get("sequence", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="sequence must be an integer >= 0")
    if sequence < 0:
        raise HTTPException(status_code=400, detail="sequence must be an integer >= 0")
    now = _now()
    row = {
        "course_id": course_id,
        "name": name,
        "code": payload.get("code"),
        "description": payload.get("description"),
        "sequence": sequence,
        "hours": payload.get("hours"),
        "status": payload.get("status", "draft"),
        "created_at": now,
        "updated_at": now,
    }
    try:
        taken = client.table("course_modules").select("id").eq("course_id", course_id).eq(
            "sequence", sequence).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to check duplicate module sequence")
    if taken.data:
        raise _duplicate("Duplicate module sequence in this course")
    try:
        resp = client.table("course_modules").insert(row).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail="Duplicate module sequence in this course")
        raise HTTPException(status_code=500, detail=f"Failed to create module: {str(e)[:200]}")
    created = (resp.data or [None])[0]
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create module")
    return created


def update_module(module_id: str, patch: dict) -> dict:
    client = _ensure_client()
    allowed = {"name", "code", "description", "sequence", "hours", "status"}
    clean = {k: v for k, v in (patch or {}).items() if k in allowed}
    if "name" in clean and not (2 <= len(str(clean["name"]).strip()) <= 200):
        raise HTTPException(status_code=400, detail="Module name must be 2–200 characters")
    _validate_enum(clean.get("status"), MODULE_STATUSES, "status")
    if "sequence" in clean:
        try:
            clean["sequence"] = int(clean["sequence"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="sequence must be an integer >= 0")
        if clean["sequence"] < 0:
            raise HTTPException(status_code=400, detail="sequence must be an integer >= 0")
    if not clean:
        raise HTTPException(status_code=400, detail="Nothing to update")
    clean["updated_at"] = _now()
    try:
        resp = client.table("course_modules").update(clean).eq("id", module_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail="Duplicate module sequence in this course")
        raise HTTPException(status_code=500, detail="Failed to update module")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Module not found")
    return rows[0]


def list_modules(course_id: str) -> list:
    client = _ensure_client()
    get_course(course_id)
    try:
        resp = client.table("course_modules").select("*").eq("course_id", course_id).order("sequence").execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to list modules")
    return resp.data or []


# ---------------------------------------------------------------------------
# Course skills
# ---------------------------------------------------------------------------

def attach_course_skill(course_id: str, payload: dict) -> dict:
    """Attach a raw curriculum concept to a course (and optionally a module).

    The concept resolves server-side through the canonical taxonomy; callers
    never supply a skill_id. Unmapped concepts are stored verbatim with
    mapping_status='unmapped'.
    """
    client = _ensure_client()
    get_course(course_id)
    module_id = payload.get("module_id")
    if module_id:
        try:
            mresp = client.table("course_modules").select("id,course_id").eq("id", module_id).execute()
        except Exception as e:
            if _table_missing_msg(e):
                raise _missing_table()
            raise HTTPException(status_code=500, detail="Failed to validate module")
        mrows = mresp.data or []
        if not mrows:
            raise HTTPException(status_code=404, detail="Module not found")
        if str(mrows[0].get("course_id")) != str(course_id):
            raise HTTPException(status_code=400, detail="Module does not belong to this course")
    _validate_enum(payload.get("coverage"), COVERAGE_LEVELS, "coverage")
    _validate_enum(payload.get("importance"), SKILL_IMPORTANCE, "importance")
    resolved = resolve_skill(str(payload.get("source_concept") or ""), client)
    try:
        current = client.table("course_skills").select(
            "id,module_id,canonical_skill_slug,source_concept").eq("course_id", course_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to check duplicate skill mapping")
    for other in current.data or []:
        same_module = str(other.get("module_id") or "") == str(module_id or "")
        if not same_module:
            continue
        if resolved["canonical_skill_slug"]:
            if (other.get("canonical_skill_slug") or "").lower() == resolved["canonical_skill_slug"].lower():
                raise _duplicate("Duplicate skill mapping for this course/module")
        elif (other.get("canonical_skill_slug") is None and
                str(other.get("source_concept") or "").strip().lower() == resolved["source_concept"].lower()):
            raise _duplicate("Duplicate skill mapping for this course/module")
    now = _now()
    row = {
        "course_id": course_id,
        "module_id": module_id,
        "skill_id": resolved["skill_id"],
        "canonical_skill_slug": resolved["canonical_skill_slug"],
        "source_concept": resolved["source_concept"],
        "mapping_status": resolved["mapping_status"],
        "mapping_rationale": resolved["mapping_rationale"],
        "coverage": payload.get("coverage"),
        "importance": payload.get("importance"),
        "evidence_source": payload.get("evidence_source"),
        "created_at": now,
        "updated_at": now,
    }
    try:
        resp = client.table("course_skills").insert(row).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail="Duplicate skill mapping for this course/module")
        raise HTTPException(status_code=500, detail=f"Failed to attach course skill: {str(e)[:200]}")
    created = (resp.data or [None])[0]
    if not created:
        raise HTTPException(status_code=500, detail="Failed to attach course skill")
    return created


def list_course_skills(course_id: str, mapping_status: str | None = None) -> list:
    client = _ensure_client()
    get_course(course_id)
    if mapping_status is not None and mapping_status not in ("mapped", "unmapped"):
        raise HTTPException(status_code=400, detail="mapping_status must be mapped or unmapped")
    try:
        query = client.table("course_skills").select("*").eq("course_id", course_id)
        if mapping_status:
            query = query.eq("mapping_status", mapping_status)
        resp = query.execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to list course skills")
    return resp.data or []


def remove_course_skill(course_id: str, skill_row_id: str) -> None:
    client = _ensure_client()
    get_course(course_id)
    try:
        resp = client.table("course_skills").select("id").eq("id", skill_row_id).eq("course_id", course_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to remove course skill")
    if not (resp.data or []):
        raise HTTPException(status_code=404, detail="Course skill mapping not found")
    try:
        client.table("course_skills").delete().eq("id", skill_row_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to remove course skill")


def get_course_coverage(course_id: str) -> dict:
    """Answer 'which skills does this course teach?' — supply only, no demand math.

    Returns the course plus module-grouped skills (module-level under each
    module, course-level under a null-module group) with mapped/unmapped
    counts. No comparison against industry demand happens here.
    """
    course = get_course(course_id)
    modules = list_modules(course_id)
    skills = list_course_skills(course_id)
    module_name = {m["id"]: m.get("name") for m in modules}
    groups: dict[str | None, list] = {}
    for s in skills:
        groups.setdefault(s.get("module_id"), []).append(s)
    module_groups = [
        {"module_id": m["id"], "module_name": m.get("name"),
         "sequence": m.get("sequence"),
         "skills": sorted(groups.get(m["id"], []), key=lambda r: str(r.get("source_concept") or ""))}
        for m in modules
    ]
    course_level = sorted(groups.get(None, []), key=lambda r: str(r.get("source_concept") or ""))
    mapped = sum(1 for s in skills if s.get("mapping_status") == "mapped")
    return {
        "course": course,
        "modules": module_groups,
        "course_level_skills": course_level,
        "counts": {
            "modules": len(modules),
            "skills": len(skills),
            "mapped": mapped,
            "unmapped": len(skills) - mapped,
        },
    }


# ---------------------------------------------------------------------------
# Trainers
# ---------------------------------------------------------------------------

def create_trainer(institution_id: str, payload: dict) -> dict:
    client = _ensure_client()
    get_institution(institution_id)
    name = str(payload.get("name") or "").strip()
    if len(name) < 2 or len(name) > 200:
        raise HTTPException(status_code=400, detail="Trainer name must be 2–200 characters")
    _validate_enum(payload.get("status", "active"), TRAINER_STATUSES, "status")
    if payload.get("email"):
        try:
            dupes = client.table("trainers").select("id").eq(
                "institution_id", institution_id).eq("email", payload["email"]).execute()
        except Exception as e:
            if _table_missing_msg(e):
                raise _missing_table()
            raise HTTPException(status_code=500, detail="Failed to check duplicate trainer")
        if dupes.data:
            raise _duplicate("Duplicate trainer email in this institution")
    now = _now()
    row = {
        "institution_id": institution_id,
        "name": name,
        "email": payload.get("email"),
        "designation": payload.get("designation"),
        "status": payload.get("status", "active"),
        "created_at": now,
        "updated_at": now,
    }
    try:
        resp = client.table("trainers").insert(row).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail="Duplicate trainer email in this institution")
        raise HTTPException(status_code=500, detail=f"Failed to create trainer: {str(e)[:200]}")
    created = (resp.data or [None])[0]
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create trainer")
    return created


def get_trainer(trainer_id: str) -> dict:
    client = _ensure_client()
    try:
        resp = client.table("trainers").select("*").eq("id", trainer_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to fetch trainer")
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Trainer not found")
    return rows[0]


def list_trainers(institution_id: str, status: str | None = None) -> list:
    client = _ensure_client()
    get_institution(institution_id)
    _validate_enum(status, TRAINER_STATUSES, "status")
    try:
        query = client.table("trainers").select("*").eq("institution_id", institution_id)
        if status:
            query = query.eq("status", status)
        resp = query.order("name").execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to list trainers")
    return resp.data or []


def attach_trainer_skill(trainer_id: str, payload: dict) -> dict:
    """Attach a canonical skill to a trainer. Unmapped concepts are rejected
    (400): trainer records reference the canonical taxonomy only."""
    client = _ensure_client()
    get_trainer(trainer_id)
    _validate_enum(payload.get("proficiency"), COVERAGE_LEVELS, "proficiency")
    resolved = resolve_skill(str(payload.get("source_concept") or ""), client)
    if resolved["mapping_status"] != "mapped":
        raise HTTPException(
            status_code=400,
            detail=f"No canonical skill for {resolved['source_concept']!r}; trainer skills must map to the taxonomy",
        )
    try:
        dupes = client.table("trainer_skills").select("id").eq(
            "trainer_id", trainer_id).eq("canonical_skill_slug", resolved["canonical_skill_slug"]).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to check duplicate trainer skill")
    if dupes.data:
        raise _duplicate("Duplicate trainer skill")
    now = _now()
    row = {
        "trainer_id": trainer_id,
        "skill_id": resolved["skill_id"],
        "canonical_skill_slug": resolved["canonical_skill_slug"],
        "proficiency": payload.get("proficiency"),
        "source": payload.get("source"),
        "created_at": now,
        "updated_at": now,
    }
    try:
        resp = client.table("trainer_skills").insert(row).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        if _is_unique_violation(e):
            raise HTTPException(status_code=409, detail="Duplicate trainer skill")
        raise HTTPException(status_code=500, detail=f"Failed to attach trainer skill: {str(e)[:200]}")
    created = (resp.data or [None])[0]
    if not created:
        raise HTTPException(status_code=500, detail="Failed to attach trainer skill")
    return created


def list_trainer_skills(trainer_id: str) -> list:
    client = _ensure_client()
    get_trainer(trainer_id)
    try:
        resp = client.table("trainer_skills").select("*").eq("trainer_id", trainer_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to list trainer skills")
    return resp.data or []


def remove_trainer_skill(trainer_id: str, skill_row_id: str) -> None:
    client = _ensure_client()
    get_trainer(trainer_id)
    try:
        resp = client.table("trainer_skills").select("id").eq("id", skill_row_id).eq("trainer_id", trainer_id).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to remove trainer skill")
    if not (resp.data or []):
        raise HTTPException(status_code=404, detail="Trainer skill mapping not found")
    try:
        client.table("trainer_skills").delete().eq("id", skill_row_id).execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to remove trainer skill")


# ---------------------------------------------------------------------------
# Deterministic demo seed (synthetic — never real institutional data)
# ---------------------------------------------------------------------------

def build_demo_seed() -> dict:
    """Pure deterministic demo supply graph. Every entity carries
    data_origin='demo_seeded'. Includes one intentionally unmapped raw concept
    ('Blockchain Basics') to prove unmapped preservation."""
    return {
        "institution": {
            "name": "INAURA Demo Skill Training Centre",
            "code": DEMO_INSTITUTION_CODE,
            "institution_type": "skill_training_centre",
            "district": "Bengaluru Urban",
            "state": "Karnataka",
            "country": "India",
            "city": "Bengaluru",
            "website": "https://example.invalid/demo-training-centre",
            "description": "Synthetic demo institution for supply-model plumbing; not a real training centre.",
            "status": "active",
            "data_origin": DEMO_ORIGIN,
        },
        "courses": [
            {
                "code": "DEMO-FSWD",
                "name": "Full Stack Web Development",
                "description": "Synthetic demo course outline; not a real curriculum.",
                "level": "Diploma",
                "duration_text": "6 months",
                "delivery_mode": "hybrid",
                "status": "active",
                "data_origin": DEMO_ORIGIN,
                "modules": [
                    {"code": "DEMO-FSWD-M1", "name": "HTML/CSS Fundamentals", "sequence": 1,
                     "skills": [{"source_concept": "HTML/CSS", "coverage": "intermediate"}]},
                    {"code": "DEMO-FSWD-M2", "name": "JavaScript Programming", "sequence": 2,
                     "skills": [{"source_concept": "JavaScript", "coverage": "intermediate"}]},
                    {"code": "DEMO-FSWD-M3", "name": "React Frontend", "sequence": 3,
                     "skills": [{"source_concept": "React", "coverage": "intermediate"}]},
                    {"code": "DEMO-FSWD-M4", "name": "Backend APIs", "sequence": 4,
                     "skills": [{"source_concept": "REST APIs", "coverage": "introductory"},
                                {"source_concept": "Node.js", "coverage": "introductory"}]},
                    {"code": "DEMO-FSWD-M5", "name": "Databases", "sequence": 5,
                     "skills": [{"source_concept": "SQL", "coverage": "introductory"}]},
                ],
                "course_skills": [],
            },
            {
                "code": "DEMO-MAD",
                "name": "Mobile Application Development",
                "description": "Synthetic demo course outline; not a real curriculum.",
                "level": "Certificate",
                "duration_text": "4 months",
                "delivery_mode": "offline",
                "status": "active",
                "data_origin": DEMO_ORIGIN,
                "modules": [
                    {"code": "DEMO-MAD-M1", "name": "Android Basics", "sequence": 1,
                     "skills": [{"source_concept": "Android", "coverage": "introductory"}]},
                    {"code": "DEMO-MAD-M2", "name": "Kotlin Programming", "sequence": 2,
                     "skills": [{"source_concept": "Kotlin", "coverage": "intermediate"}]},
                    {"code": "DEMO-MAD-M3", "name": "Flutter Development", "sequence": 3,
                     "skills": [{"source_concept": "Flutter", "coverage": "intermediate"}]},
                    {"code": "DEMO-MAD-M4", "name": "Mobile APIs", "sequence": 4,
                     "skills": [{"source_concept": "REST APIs", "coverage": "introductory"}]},
                ],
                "course_skills": [],
            },
            {
                "code": "DEMO-DA",
                "name": "Data Analytics",
                "description": "Synthetic demo course outline; not a real curriculum.",
                "level": "Certificate",
                "duration_text": "3 months",
                "delivery_mode": "online",
                "status": "active",
                "data_origin": DEMO_ORIGIN,
                "modules": [
                    {"code": "DEMO-DA-M1", "name": "Python for Data", "sequence": 1,
                     "skills": [{"source_concept": "Python", "coverage": "intermediate"}]},
                    {"code": "DEMO-DA-M2", "name": "Data Wrangling", "sequence": 2,
                     "skills": [{"source_concept": "Pandas", "coverage": "intermediate"}]},
                    {"code": "DEMO-DA-M3", "name": "SQL Analytics", "sequence": 3,
                     "skills": [{"source_concept": "SQL", "coverage": "intermediate"}]},
                    {"code": "DEMO-DA-M4", "name": "Visual Storytelling", "sequence": 4,
                     "skills": [{"source_concept": "Data Visualization", "coverage": "introductory"},
                                {"source_concept": "Blockchain Basics", "coverage": "introductory"}]},
                ],
                "course_skills": [],
            },
        ],
        "trainers": [
            {"name": "Demo Trainer One", "email": "trainer.one@example.invalid",
             "designation": "Web Development Faculty", "status": "active",
             "skills": [{"source_concept": "React", "proficiency": "advanced"},
                        {"source_concept": "JavaScript", "proficiency": "advanced"}]},
            {"name": "Demo Trainer Two", "email": "trainer.two@example.invalid",
             "designation": "Data Faculty", "status": "active",
             "skills": [{"source_concept": "Python", "proficiency": "advanced"},
                        {"source_concept": "SQL", "proficiency": "intermediate"}]},
        ],
    }


def seed_demo_data() -> dict:
    """Idempotent demo import: skips entities already present (matched by
    code/email unique keys). Returns counts of created vs skipped rows."""
    client = _ensure_client()
    seed = build_demo_seed()
    created = {"institutions": 0, "courses": 0, "modules": 0,
               "course_skills": 0, "trainers": 0, "trainer_skills": 0}
    skipped = {"institutions": 0, "courses": 0, "modules": 0,
               "course_skills": 0, "trainers": 0, "trainer_skills": 0}

    def _find(table: str, filt: dict) -> dict | None:
        try:
            q = client.table(table).select("*")
            for k, v in filt.items():
                q = q.eq(k, v)
            rows = (q.execute().data or [])
            return rows[0] if rows else None
        except Exception as e:
            if _table_missing_msg(e):
                raise _missing_table()
            raise

    inst = _find("institutions", {"code": seed["institution"]["code"]})
    if inst is None:
        inst = create_institution(seed["institution"])
        created["institutions"] += 1
    else:
        skipped["institutions"] += 1

    for course in seed["courses"]:
        existing = _find("courses", {"code": course["code"]})
        if existing is None:
            payload = {k: v for k, v in course.items() if k not in ("modules", "course_skills")}
            existing = create_course(inst["id"], payload)
            created["courses"] += 1
        else:
            skipped["courses"] += 1
        module_ids: dict[str, str] = {}
        for mod in course.get("modules", []):
            mex = _find("course_modules", {"course_id": existing["id"], "sequence": mod["sequence"]})
            if mex is None:
                mex = create_module(existing["id"], {k: v for k, v in mod.items() if k != "skills"})
                created["modules"] += 1
            else:
                skipped["modules"] += 1
            module_ids[mod["code"]] = mex["id"]
            for sk in mod.get("skills", []):
                try:
                    attach_course_skill(existing["id"], {
                        "module_id": mex["id"],
                        "source_concept": sk["source_concept"],
                        "coverage": sk.get("coverage"),
                        "evidence_source": "demo_seeded syllabus outline",
                    })
                    created["course_skills"] += 1
                except HTTPException as e:
                    if e.status_code == 409:
                        skipped["course_skills"] += 1
                    else:
                        raise

    for tr in seed["trainers"]:
        tex = _find("trainers", {"institution_id": inst["id"], "email": tr["email"]}) if tr.get("email") else None
        if tex is None:
            tex = create_trainer(inst["id"], {k: v for k, v in tr.items() if k != "skills"})
            created["trainers"] += 1
        else:
            skipped["trainers"] += 1
        for sk in tr.get("skills", []):
            try:
                attach_trainer_skill(tex["id"], {
                    "source_concept": sk["source_concept"],
                    "proficiency": sk.get("proficiency"),
                    "source": "demo_seeded roster",
                })
                created["trainer_skills"] += 1
            except HTTPException as e:
                if e.status_code == 409:
                    skipped["trainer_skills"] += 1
                else:
                    raise
    return {"created": created, "skipped": skipped,
            "institution_id": inst["id"], "data_origin": DEMO_ORIGIN}
