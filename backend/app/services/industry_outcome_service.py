"""Phase 3B: industry outcome aggregation service (Person 2 owned).

Reads Person 2 source tables, canonicalizes roles/skills/locations, computes
independent per-scope cells (city / role / global — never collapsed), applies
approved suppression, quarantines unmapped cases, and writes append-only
observation rows.

HARD BOUNDARIES (enforced by tests/test_industry_outcome_direction.py):
- Never imports skill_engine, analysis_run_service, assessment, evidence,
  or learner-state modules.
- Never writes student state, curated requirements, or taxonomy.
- Never embeds anything into the vector store.

Thresholds: city (applied>=5 AND feedback>=5) and role (applied>=10 AND
feedback>=5) are APPROVED contract policy. Global-scope thresholds are
PROVISIONAL (open question 1) — isolated below and reported as such.
"""

import re
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from supabase import Client

from ..core.supabase import get_supabase_client
from ..schemas import industry_outcomes as S
from .skill_taxonomy import normalize_skill
from .industry_roles import canonicalize_role_name

TABLE = "industry_outcome_observations"

# Approved contract thresholds — do not change without Phase 1 re-approval.
CITY_MIN_APPLIED = S.CITY_MIN_APPLIED
CITY_MIN_FEEDBACK = S.CITY_MIN_FEEDBACK
ROLE_MIN_APPLIED = S.ROLE_MIN_APPLIED
ROLE_MIN_FEEDBACK = S.ROLE_MIN_FEEDBACK

# PROVISIONAL (NOT approved): global-scope suppression floor. Isolated here so
# the open question stays visible; global cells are labeled threshold_policy
# "provisional" in provenance. Do not treat as policy.
PROVISIONAL_GLOBAL_MIN_APPLIED = 25
PROVISIONAL_GLOBAL_MIN_FEEDBACK = 10

DEFAULT_WINDOW_DAYS = 90


def _ensure_client() -> Client:
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured — set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env",
        )
    return client


def _missing(e: Exception) -> bool:
    m = str(e).lower()
    return "could not find table" in m or "pgrst205" in m


# ---------------------------------------------------------------------------
# Normalization (deterministic string canonicalization only — there is no
# INAURA canonical location list, so no allowlist is invented here)
# ---------------------------------------------------------------------------

def normalize_location(raw: object) -> str | None:
    """Coarse city display form, or None when absent. No PII transformation."""
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw).strip())
    if not s:
        return None
    return s.title()


def _parse_window(from_s: str | None, to_s: str | None) -> tuple[datetime, datetime]:
    """Resolve a concrete day-snapped window. Defaults to trailing 90 days so
    stored window_to values are deterministic per day (refresh idempotent)."""
    try:
        to = datetime.fromisoformat(to_s) if to_s else datetime.now(timezone.utc)
        if to.tzinfo is None:
            to = to.replace(tzinfo=timezone.utc)
        to_day = to.replace(hour=0, minute=0, second=0, microsecond=0)
        if from_s:
            f = datetime.fromisoformat(from_s)
            if f.tzinfo is None:
                f = f.replace(tzinfo=timezone.utc)
            frm = f.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            frm = to_day - timedelta(days=DEFAULT_WINDOW_DAYS)
        if frm > to_day:
            raise HTTPException(status_code=400, detail="Invalid time window")
        return frm, to_day
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid time window (use ISO dates)")


def _in_window(ts: str | None, f: datetime, t_day: datetime) -> bool:
    if not ts:
        return False
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        end = t_day + timedelta(days=1)
        return f <= d < end
    except Exception:
        return False


def _is_stale(window_from: datetime, window_to: datetime, now: datetime) -> bool:
    span = (window_to - window_from).total_seconds()
    if span <= 0:
        return True
    return (now - window_to).total_seconds() > span


# ---------------------------------------------------------------------------
# Source-data loading (reads only — never copies PII into observations)
# ---------------------------------------------------------------------------

def _load_sources(client: Client, skill_map: dict) -> dict:
    reqs = (client.table("hiring_requirements").select("id,role_key,location").execute().data or [])
    req_skills = (client.table("hiring_requirement_skills").select(
        "hiring_requirement_id,skill_id").execute().data or [])
    apps = (client.table("applications").select(
        "id,status,applied_at,hiring_requirement_id").execute().data or [])
    feedback = (client.table("employer_feedback").select(
        "id,application_id,created_at").execute().data or [])
    skill_fb = (client.table("employer_skill_feedback").select(
        "employer_feedback_id,skill_id,expected_level,observed_level").execute().data or [])
    placements = (client.table("placement_outcomes").select(
        "id,application_id,status").execute().data or [])
    return {
        "reqs": reqs, "req_skills": req_skills, "apps": apps,
        "feedback": feedback, "skill_fb": skill_fb, "placements": placements,
        "skills": skill_map,
    }


def _skills_map(client: Client) -> dict:
    try:
        rows = client.table("skills").select("id,canonical_name").execute().data or []
        return {str(r["id"]): r.get("canonical_name") or "" for r in rows}
    except Exception:
        return {}


def _canon_skill_name(skill_id: str | None, skill_map: dict) -> str | None:
    if not skill_id:
        return None
    name = skill_map.get(str(skill_id))
    if not name:
        return None
    return normalize_skill(name) or name


# ---------------------------------------------------------------------------
# Cell computation — scopes independent, never collapsed
# ---------------------------------------------------------------------------

def _empty_cell() -> dict:
    return {"req_ids": set(), "requesting": set(), "apps": [],
            "feedbacks": [], "gaps": [], "placements": 0}


def build_cells(role_filter: str | None = None, skill_filter: str | None = None,
                location_filter: str | None = None, scope_filter: str | None = None,
                from_s: str | None = None, to_s: str | None = None) -> tuple[list, list]:
    """Compute observation cells + quarantine issues. Pure read; no writes."""
    client = _ensure_client()
    frm, to_day = _parse_window(from_s, to_s)
    now = datetime.now(timezone.utc)
    skill_map = _skills_map(client)
    try:
        src = _load_sources(client, skill_map)
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Person 2 tables missing — run migrations 026/027")
        raise HTTPException(status_code=500, detail="Failed to load outcome sources")

    issues: list = []
    # Canonical role per requirement; quarantine unmapped role_key.
    req_canon: dict = {}
    for r in src["reqs"]:
        canon = canonicalize_role_name(str(r.get("role_key") or "")) if r.get("role_key") else None
        if not canon:
            issues.append({"key": f"requirement:{r['id']}", "code": "unmapped_role"})
            continue
        req_canon[r["id"]] = {"role": canon, "city": normalize_location(r.get("location"))}

    if role_filter:
        want = canonicalize_role_name(role_filter) or role_filter.strip()
        req_canon = {k: v for k, v in req_canon.items() if v["role"].lower() == want.lower()}

    # Applications in window (applied_at basis).
    apps = [a for a in src["apps"]
            if a.get("hiring_requirement_id") in req_canon
            and a.get("applied_at") and _in_window(a["applied_at"], frm, to_day)]
    apps_by_req: dict = {}
    for a in apps:
        apps_by_req.setdefault(a["hiring_requirement_id"], []).append(a)

    # Feedback in window (created_at basis) + skill gaps with resolved names.
    fb_by_app = {f["application_id"]: f for f in src["feedback"]
                 if _in_window(f.get("created_at"), frm, to_day)}
    gaps_by_fb: dict = {}
    for s in src["skill_fb"]:
        if s.get("employer_feedback_id") not in [f["id"] for f in fb_by_app.values()]:
            continue
        name = _canon_skill_name(s.get("skill_id"), skill_map)
        if not name:
            issues.append({"key": f"skill_feedback:{s.get('employer_feedback_id')}", "code": "unmapped_skill"})
            continue
        exp, obs = s.get("expected_level"), s.get("observed_level")
        if exp is None or obs is None:
            continue
        gaps_by_fb.setdefault(s["employer_feedback_id"], []).append((name, float(exp) - float(obs)))

    # Requirement-skill demand edges with resolved names.
    demand_edges: dict = {}
    for e in src["req_skills"]:
        if e.get("hiring_requirement_id") not in req_canon:
            continue
        name = _canon_skill_name(e.get("skill_id"), skill_map)
        if not name:
            issues.append({"key": f"requirement_skill:{e.get('hiring_requirement_id')}", "code": "unmapped_skill"})
            continue
        demand_edges.setdefault(e["hiring_requirement_id"], []).append(name)

    # Placement counts per application (joined only).
    placed_apps = {p["application_id"] for p in src["placements"]
                   if p.get("application_id") and p.get("status") == "joined"}

    # Group cells independently per scope (city / role / global).
    # Each family is harvested by its own matcher — never collapsed.
    city_cells: dict = {}
    role_cells: dict = {}
    global_cells: dict = {}

    # Simpler deterministic fill: iterate once per scope family.
    def harvest(cells: dict, match) -> None:
        for req_id, rc in req_canon.items():
            r_apps = apps_by_req.get(req_id, [])
            r_demand = set(demand_edges.get(req_id, []))
            # all skills relevant here: demanded + observed
            rel_skills: set = set(r_demand)
            for a in r_apps:
                fb = fb_by_app.get(a["id"])
                if fb:
                    rel_skills.update(n for n, _ in gaps_by_fb.get(fb["id"], []))
            for skill_name in rel_skills:
                if skill_filter and skill_name.lower() != skill_filter.strip().lower():
                    continue
                key = match(rc, skill_name)
                if key is None:
                    continue
                cell = cells.setdefault(key, _empty_cell())
                cell["req_ids"].add(req_id)
                if skill_name in r_demand:
                    cell["requesting"].add(req_id)
                for a in r_apps:
                    if a["id"] not in [x["id"] for x in cell["apps"]]:
                        cell["apps"].append(a)
                    fb = fb_by_app.get(a["id"])
                    if fb and fb["id"] not in cell["feedbacks"]:
                        for n, g in gaps_by_fb.get(fb["id"], []):
                            if n == skill_name:
                                cell["feedbacks"].append(fb["id"])
                                cell["gaps"].append(g)
                for a in r_apps:
                    if a["id"] in placed_apps:
                        cell["placements"] = len({x["id"] for x in cell["apps"] if x["id"] in placed_apps})

    city_match = lambda rc, s: (rc["role"], s, rc["city"]) if rc["city"] and (
        not location_filter or rc["city"].lower() == location_filter.strip().lower()) else None
    role_match = lambda rc, s: (rc["role"], s)
    harvest(city_cells, city_match)
    if not scope_filter or scope_filter == S.SCOPE_ROLE:
        harvest(role_cells, role_match)
    if not scope_filter or scope_filter == S.SCOPE_GLOBAL:
        harvest(global_cells, role_match)
    if scope_filter == S.SCOPE_CITY or not scope_filter:
        pass  # city already harvested

    observations: list = []
    fro, to_iso = frm.isoformat(), to_day.isoformat()
    stale = _is_stale(frm, to_day, now)

    def emit(key, cell, scope, location, min_a, min_f, provisional):
        applied_n = len(cell["apps"])
        fbn = len(cell["gaps"])
        ok = applied_n >= min_a and fbn >= min_f
        n_req = len(cell["req_ids"])
        st = [a["status"] for a in cell["apps"]]
        observations.append({
            "role": key[0], "skill": key[1],
            "skill_id": None,  # resolved at write from skills table
            "scope": scope, "location": location,
            "window_from": fro, "window_to": to_iso,
            "requirements_n": n_req, "applied_n": applied_n,
            "interview_count": sum(1 for s in st if s in ("interview", "offer_received", "selected")),
            "selection_count": sum(1 for s in st if s == "selected"),
            "placement_count": cell["placements"],
            "feedback_count": fbn,
            "observed_demand": (len(cell["requesting"]) / n_req) if (ok and n_req) else None,
            "observed_skill_gap": (sum(cell["gaps"]) / len(cell["gaps"])) if (ok and cell["gaps"]) else None,
            "min_n_met": ok, "stale": stale,
            "threshold_policy": "provisional" if provisional else "approved",
        })

    if not scope_filter or scope_filter == S.SCOPE_CITY:
        for key, cell in city_cells.items():
            emit(key, cell, S.SCOPE_CITY, key[2], CITY_MIN_APPLIED, CITY_MIN_FEEDBACK, False)
    if not scope_filter or scope_filter == S.SCOPE_ROLE:
        for key, cell in role_cells.items():
            emit(key, cell, S.SCOPE_ROLE, S.GLOBAL_LOCATION, ROLE_MIN_APPLIED, ROLE_MIN_FEEDBACK, False)
    if not scope_filter or scope_filter == S.SCOPE_GLOBAL:
        for key, cell in global_cells.items():
            emit(key, cell, S.SCOPE_GLOBAL, S.GLOBAL_LOCATION,
                 PROVISIONAL_GLOBAL_MIN_APPLIED, PROVISIONAL_GLOBAL_MIN_FEEDBACK, True)

    return observations, issues


# ---------------------------------------------------------------------------
# Refresh (idempotent upsert) + reads
# ---------------------------------------------------------------------------

def _resolve_skill_ids(client: Client, observations: list) -> None:
    try:
        rows = client.table("skills").select("id,canonical_name").execute().data or []
    except Exception:
        return
    by_name = {}
    for r in rows:
        canon = normalize_skill(r.get("canonical_name") or "") or r.get("canonical_name")
        if canon:
            by_name[canon.lower()] = str(r["id"])
    for o in observations:
        sid = by_name.get(str(o["skill"]).lower())
        if sid:
            o["skill_id"] = sid


def refresh_observations(role=None, skill=None, location=None, scope=None,
                         from_s=None, to_s=None) -> dict:
    """Compute cells and upsert by (role, skill, scope, location, window_to)."""
    if scope and scope not in S.ALLOWED_SCOPES:
        raise HTTPException(status_code=400, detail="Invalid scope")
    client = _ensure_client()
    observations, issues = build_cells(role, skill, location, scope, from_s, to_s)
    _resolve_skill_ids(client, observations)
    accepted = 0
    try:
        for o in observations:
            row = {k: v for k, v in o.items() if k not in ("stale", "threshold_policy")}
            row["signal_version"] = S.SIGNAL_VERSION
            client.table(TABLE).upsert(row, on_conflict="role,skill,scope,location,window_to").execute()
            accepted += 1
    except Exception as e:
        if _missing(e):
            raise HTTPException(status_code=503, detail="Phase 3 table missing — run backend/supabase/029_industry_outcomes.sql")
        raise HTTPException(status_code=500, detail=f"Failed to persist observations: {str(e)[:200]}")
    return {"accepted": accepted, "quarantined": len(issues), "issues": issues[:50]}


def _latest_rows(client: Client, role=None, skill=None, location=None, scope=None) -> list:
    try:
        q = client.table(TABLE).select("*")
        if role:
            q = q.eq("role", role)
        if skill:
            q = q.eq("skill", skill)
        if scope:
            q = q.eq("scope", scope)
        if location:
            q = q.eq("location", location)
        rows = q.execute().data or []
    except Exception as e:
        if _missing(e):
            return []
        raise HTTPException(status_code=500, detail="Failed to read observations")
    latest: dict = {}
    for r in rows:
        key = (r["role"], r["skill"], r["scope"], r["location"])
        if key not in latest or str(r.get("window_to") or "") > str(latest[key].get("window_to") or ""):
            latest[key] = r
    return list(latest.values())


def get_observations(role=None, skill=None, location=None, scope=None) -> list:
    """Latest-window observation rows. Empty (not error) when table missing."""
    client = _ensure_client()
    return _latest_rows(client, role, skill, location, scope)


def build_overlay(role: str, canonical_skill: str) -> dict | None:
    """Role-scope overlay for one curated requirement. None when suppressed/
    missing/stale-unknown. Never raises for missing table (flag-gated callers
    must degrade to curated behavior)."""
    try:
        client = _ensure_client()
        rows = _latest_rows(client, role, canonical_skill, S.GLOBAL_LOCATION, S.SCOPE_ROLE)
    except Exception:
        return None
    rows = [r for r in rows if r.get("min_n_met")]
    if not rows:
        return None
    r = rows[0]
    return {
        "observed_demand": r.get("observed_demand"),
        "observed_skill_gap": r.get("observed_skill_gap"),
        "outcome_sample": {
            "requirements_n": r.get("requirements_n", 0),
            "applied_n": r.get("applied_n", 0),
            "feedback_count": r.get("feedback_count", 0),
        },
        "outcome_window": {
            "window_from": r.get("window_from"),
            "window_to": r.get("window_to"),
            "basis": S.TIME_WINDOW_BASIS,
        },
        "outcome_provenance": {
            "signal_version": r.get("signal_version", S.SIGNAL_VERSION),
            "scope": r.get("scope"),
            "location": r.get("location"),
            "role": r.get("role"),
            "skill": r.get("skill"),
        },
        "stale": False,
    }


def get_emerging(role: str, location: str | None = None, curated_skills: set | None = None) -> list:
    """Derived read model: min_n_met observations with no curated counterpart.
    No table, no writes, no taxonomy/requirement mutation."""
    client = _ensure_client()
    scope = S.SCOPE_CITY if location else S.SCOPE_ROLE
    loc = normalize_location(location) if location else S.GLOBAL_LOCATION
    rows = _latest_rows(client, role, None, loc, scope)
    curated = {str(s).lower() for s in (curated_skills or set())}
    out = []
    for r in rows:
        if not r.get("min_n_met"):
            continue
        if str(r.get("skill", "")).lower() in curated:
            continue
        out.append({
            "skill": r["skill"],
            "skill_id": r.get("skill_id"),
            "observed_demand": r.get("observed_demand"),
            "observed_skill_gap": r.get("observed_skill_gap"),
            "outcome_sample": {
                "requirements_n": r.get("requirements_n", 0),
                "applied_n": r.get("applied_n", 0),
                "feedback_count": r.get("feedback_count", 0),
            },
            "outcome_window": {
                "window_from": r.get("window_from"),
                "window_to": r.get("window_to"),
                "basis": S.TIME_WINDOW_BASIS,
            },
            "status": "observed_not_required",
            "role": r.get("role"),
            "location": None if scope == S.SCOPE_ROLE else r.get("location"),
        })
    return out
