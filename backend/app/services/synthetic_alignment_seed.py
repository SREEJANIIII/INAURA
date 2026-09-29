"""Synthetic end-to-end fixture for testing course/industry alignment.

Builds one clearly synthetic institution, course, two cohorts (10 + 3
learners), per-learner skill signals, and city-scoped industry-demand rows so
that a single dataset exercises every alignment outcome of
course_alignment_service (aligned, curriculum_gap, attainment_gap,
weak_supply, insufficient_data, extra_cohort_skills, unmapped exclusion,
rising/stable/declining/emerging trends, small-cohort suppression).

Architecture reuse (nothing invented twice):
- institution/course/module/skill import follows institution_service
  (match by code, service-level 409 duplicate guards);
- synthetic Auth users + membership + signal import follow
  cohort_supply_service (demo-student-N@demo.invalid via the Auth Admin API,
  real auth.users.id values, never fabricated UUIDs);
- demand rows target labour_market_demand_signals with the synthetic
  provider inaura_synthetic_market_v1, upserted by the table's logical cell
  key;
- every row carries data_origin='demo_seeded' (and metadata.demo_seeded
  where a metadata column exists).

Skill-engine rules are respected, never bypassed: cohort supply derives
verified coverage from assessment-source skill_signals (the same signal
source the engine treats as direct validation). No skill_assessments rows
are fabricated.

The module never touches non-demo data: every lookup is scoped to the
synthetic codes/provider/emails below. Real students, employers,
applications, and placements are never read or written.
"""

from fastapi import HTTPException

from ..core.supabase import get_supabase_client
from . import cohort_supply_service as cohort_svc
from . import institution_service as inst
from .evidence_weights import SOURCE_RELIABILITY

SYNTH_ORIGIN = "demo_seeded"
SYNTH_PROVIDER_ID = "inaura_synthetic_market_v1"
SYNTH_SOURCE_VERSION = "synthetic-v1"

SYNTH_INSTITUTION_CODE = "INAURA-SYNTH-INSTITUTE"
SYNTH_COURSE_CODE = "INAURA-SYNTH-FSE"
SYNTH_COHORT_CODE = "INAURA-SYNTH-FSE-2026A"
SYNTH_TINY_COHORT_CODE = "INAURA-SYNTH-FSE-TINY"

SYNTH_ROLE = "Software Engineer"
SYNTH_COUNTRY = "India"
SYNTH_REGION = "Karnataka"
SYNTH_CITY = "Bengaluru"
SYNTH_PERIOD_START = "2026-07-01"
SYNTH_PERIOD_END = "2026-07-31"

# Learner identity space. Batch A (10 learners, passes the skill-detail
# minimum) and the tiny cohort (3 learners, suppressed) use disjoint users.
SYNTH_MEMBER_NS = list(range(1, 11))
SYNTH_TINY_MEMBER_NS = [11, 12, 13]


def _skill(concept: str, coverage: str, importance: str) -> dict:
    return {"source_concept": concept, "coverage": coverage, "importance": importance}


def build_synthetic_seed() -> dict:
    """Pure deterministic spec of the whole synthetic graph (no I/O)."""

    def _sig(user_n: int, slug: str, source: str, value: float) -> dict:
        return {
            "demo_user_n": user_n,
            "skill_slug": slug,
            "source_type": source,
            "signal_value": value,
            "source_reliability": SOURCE_RELIABILITY[source],
            "metadata": {"demo_seeded": True},
        }

    demand = [
        # (slug, display, share, trend, companies) — Kubernetes is taught but
        # deliberately has NO demand row, exercising insufficient_data.
        ("python", "Python", 0.75, "rising", 18),
        ("react", "React", 0.70, "rising", 16),
        ("javascript", "JavaScript", 0.65, "stable", 15),
        ("sql", "SQL", 0.55, "stable", 14),
        ("nodejs", "Node.js", 0.45, "rising", 12),
        ("typescript", "TypeScript", 0.40, "rising", 11),
        ("docker", "Docker", 0.35, "rising", 9),
        ("aws", "AWS", 0.50, "rising", 13),
        ("java", "Java", 0.25, "declining", 7),
        ("machine_learning", "Machine Learning", 0.20, "emerging", 6),
    ]

    learner_signals = [
        # Student 1: python/react verified strong; sql/git/docker observed only.
        _sig(1, "python", "assessment", 0.85),
        _sig(1, "react", "assessment", 0.88),
        _sig(1, "sql", "github", 0.60),
        _sig(1, "git", "github", 0.55),
        _sig(1, "docker", "github", 0.50),
        # Student 2: full-stack breadth, aws observed but unverified.
        _sig(2, "python", "assessment", 0.80),
        _sig(2, "react", "assessment", 0.82),
        _sig(2, "javascript", "assessment", 0.78),
        _sig(2, "sql", "assessment", 0.76),
        _sig(2, "aws", "github", 0.50),
        # Student 3: backend tilt; sole verified docker learner.
        _sig(3, "python", "github", 0.65),
        _sig(3, "react", "assessment", 0.84),
        _sig(3, "nodejs", "assessment", 0.80),
        _sig(3, "docker", "assessment", 0.62),
        # Student 4: data tilt; verified ML.
        _sig(4, "python", "assessment", 0.79),
        _sig(4, "react", "github", 0.68),
        _sig(4, "sql", "github", 0.55),
        _sig(4, "machine_learning", "assessment", 0.86),
        # Student 5: frontend specialist.
        _sig(5, "javascript", "assessment", 0.81),
        _sig(5, "react", "assessment", 0.87),
        _sig(5, "nodejs", "github", 0.66),
        _sig(5, "typescript", "assessment", 0.83),
        # Student 6: steady generalist, cloud observed only.
        _sig(6, "python", "assessment", 0.72),
        _sig(6, "sql", "github", 0.58),
        _sig(6, "docker", "github", 0.52),
        _sig(6, "aws", "github", 0.48),
        # Student 7: backend + infra; sole kubernetes evidence.
        _sig(7, "react", "assessment", 0.85),
        _sig(7, "nodejs", "assessment", 0.82),
        _sig(7, "rest_apis", "assessment", 0.80),
        _sig(7, "kubernetes", "github", 0.50),
        # Student 8: data + cloud-moderate.
        _sig(8, "python", "assessment", 0.88),
        _sig(8, "machine_learning", "assessment", 0.90),
        _sig(8, "sql", "assessment", 0.77),
        _sig(8, "aws", "github", 0.60),
        # Student 9: Java background; also demonstrates untaught skills.
        _sig(9, "java", "assessment", 0.86),
        _sig(9, "python", "github", 0.62),
        _sig(9, "react", "github", 0.58),
        _sig(9, "docker", "github", 0.50),
        _sig(9, "cpp", "assessment", 0.70),
        # Student 10: frontend breadth.
        _sig(10, "javascript", "assessment", 0.79),
        _sig(10, "typescript", "github", 0.63),
        _sig(10, "react", "assessment", 0.75),
        _sig(10, "nodejs", "github", 0.60),
        _sig(10, "html_css", "github", 0.55),
        # Tiny cohort: sparse evidence (suppressed regardless of content).
        _sig(11, "react", "github", 0.70),
        _sig(11, "python", "github", 0.65),
        _sig(12, "react", "github", 0.60),
        _sig(12, "sql", "github", 0.55),
        _sig(13, "python", "github", 0.70),
        _sig(13, "javascript", "github", 0.60),
    ]

    return {
        "institution": {
            "name": "INAURA Synthetic Institute",
            "code": SYNTH_INSTITUTION_CODE,
            "institution_type": "training_institute",
            "district": "Bengaluru Urban",
            "state": SYNTH_REGION,
            "country": SYNTH_COUNTRY,
            "city": SYNTH_CITY,
            "website": "https://example.invalid/synthetic-institute",
            "description": "Synthetic institution for testing INAURA course-industry alignment; not a real training centre.",
            "status": "active",
            "data_origin": SYNTH_ORIGIN,
        },
        "course": {
            "code": SYNTH_COURSE_CODE,
            "name": "Full Stack Engineering — Synthetic 2026",
            "description": "Synthetic course for testing INAURA course-industry alignment.",
            "level": "advanced",
            "duration_text": "6 months",
            "delivery_mode": "hybrid",
            "status": "active",
            "data_origin": SYNTH_ORIGIN,
            "modules": [
                {"code": f"{SYNTH_COURSE_CODE}-M1", "name": "Programming Fundamentals", "sequence": 1,
                 "skills": [_skill("Python", "intermediate", "required"),
                            _skill("JavaScript", "intermediate", "required"),
                            _skill("Git", "introductory", "preferred")]},
                {"code": f"{SYNTH_COURSE_CODE}-M2", "name": "Frontend Engineering", "sequence": 2,
                 "skills": [_skill("React", "advanced", "required"),
                            _skill("TypeScript", "intermediate", "preferred"),
                            _skill("HTML/CSS", "intermediate", "required")]},
                {"code": f"{SYNTH_COURSE_CODE}-M3", "name": "Backend Engineering", "sequence": 3,
                 "skills": [_skill("Node.js", "intermediate", "required"),
                            _skill("SQL", "introductory", "required"),
                            _skill("REST APIs", "intermediate", "required")]},
                {"code": f"{SYNTH_COURSE_CODE}-M4", "name": "Cloud & DevOps", "sequence": 4,
                 "skills": [_skill("Docker", "introductory", "preferred"),
                            _skill("AWS", "introductory", "preferred"),
                            _skill("Kubernetes", "introductory", "preferred")]},
                {"code": f"{SYNTH_COURSE_CODE}-M5", "name": "Data & Emerging Technology", "sequence": 5,
                 "skills": [_skill("Machine Learning", "introductory", "preferred"),
                            # Deliberately unmapped: must stay mapping_status='unmapped'.
                            _skill("Blockchain Basics", "introductory", "preferred")]},
            ],
        },
        "cohort": {
            "code": SYNTH_COHORT_CODE,
            "name": "Full Stack Engineering — Synthetic Batch A",
            "academic_year": "2026",
            "status": "active",
            "data_origin": SYNTH_ORIGIN,
        },
        "tiny_cohort": {
            "code": SYNTH_TINY_COHORT_CODE,
            "name": "Full Stack Engineering — Tiny Test Cohort",
            "academic_year": "2026",
            "status": "active",
            "data_origin": SYNTH_ORIGIN,
        },
        "member_ns": SYNTH_MEMBER_NS,
        "tiny_member_ns": SYNTH_TINY_MEMBER_NS,
        "signals": learner_signals,
        "demand": [
            {"skill_slug": slug, "display": display, "share": share,
             "trend": trend, "companies": companies}
            for slug, display, share, trend, companies in demand
        ],
    }


def _ensure_client():
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured — set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env",
        )
    return client


def _find(client, table: str, filt: dict) -> dict | None:
    q = client.table(table).select("*")
    for k, v in filt.items():
        q = q.eq(k, v)
    rows = q.execute().data or []
    return rows[0] if rows else None


def _seed_institution_and_course(client, seed, created, skipped) -> tuple[dict, dict]:
    inst_spec = seed["institution"]
    inst_row = _find(client, "institutions", {"code": inst_spec["code"]})
    if inst_row is None:
        inst_row = inst.create_institution(dict(inst_spec))
        created["institutions"] += 1
    else:
        skipped["institutions"] += 1

    course_spec = seed["course"]
    course_row = _find(client, "courses", {"code": course_spec["code"]})
    if course_row is None:
        payload = {k: v for k, v in course_spec.items() if k not in ("modules",)}
        course_row = inst.create_course(inst_row["id"], payload)
        created["courses"] += 1
    else:
        skipped["courses"] += 1

    for mod in course_spec["modules"]:
        mex = _find(client, "course_modules",
                    {"course_id": course_row["id"], "sequence": mod["sequence"]})
        if mex is None:
            mex = inst.create_module(
                course_row["id"],
                {"name": mod["name"], "code": mod["code"],
                 "sequence": mod["sequence"], "status": "active"})
            created["modules"] += 1
        else:
            skipped["modules"] += 1
        for sk in mod.get("skills", []):
            try:
                inst.attach_course_skill(course_row["id"], {
                    "module_id": mex["id"],
                    "source_concept": sk["source_concept"],
                    "coverage": sk.get("coverage"),
                    "importance": sk.get("importance"),
                    "evidence_source": "demo_seeded syllabus outline",
                })
                created["course_skills"] += 1
            except HTTPException as e:
                if e.status_code == 409:
                    skipped["course_skills"] += 1
                else:
                    raise
    return inst_row, course_row


def _seed_cohorts_and_learners(client, seed, inst_row, course_row, created, skipped) -> dict:
    cohorts: dict[str, dict] = {}
    for key in ("cohort", "tiny_cohort"):
        spec = seed[key]
        found = _find(client, "cohorts", {"code": spec["code"]})
        if found is None:
            found = cohort_svc.create_cohort({
                "institution_id": inst_row["id"], "course_id": course_row["id"],
                **spec,
            })
            created["cohorts"] += 1
        else:
            skipped["cohorts"] += 1
        cohorts[key] = found

    try:
        slookup = client.table("skills").select("id,canonical_name").execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to load skill taxonomy")
    slug_to_id = {str(r.get("canonical_name")): str(r.get("id")) for r in (slookup.data or [])}
    missing = sorted({s["skill_slug"] for s in seed["signals"]} - set(slug_to_id))
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Skill taxonomy rows missing for synthetic signals: {missing}",
        )

    n_to_uid: dict[int, str] = {}
    for n in seed["member_ns"] + seed["tiny_member_ns"]:
        uid, was_created = cohort_svc._ensure_demo_auth_user(client, int(n))
        n_to_uid[int(n)] = uid
        created["auth_users"] += 1 if was_created else 0
        skipped["auth_users"] += 0 if was_created else 1

    cohort_for_n = {n: cohorts["cohort"]["id"] for n in seed["member_ns"]}
    cohort_for_n.update({n: cohorts["tiny_cohort"]["id"] for n in seed["tiny_member_ns"]})
    for n, uid in n_to_uid.items():
        try:
            cohort_svc.add_member(str(cohort_for_n[n]), uid)
            created["members"] += 1
        except HTTPException as e:
            if e.status_code == 409:
                skipped["members"] += 1
            else:
                raise

    member_uids = list(n_to_uid.values())
    existing = client.table("skill_signals").select(
        "user_id,skill_id,source_type").in_("user_id", member_uids).execute()
    have = {(str(r.get("user_id")), str(r.get("skill_id")),
             str(r.get("source_type") or "").lower()) for r in (existing.data or [])}
    new_rows = []
    for sig in seed["signals"]:
        uid = n_to_uid[int(sig["demo_user_n"])]
        sid = slug_to_id[sig["skill_slug"]]
        key = (uid, sid, sig["source_type"])
        if key in have:
            skipped["signals"] += 1
            continue
        have.add(key)
        new_rows.append({
            "user_id": uid, "skill_id": sid, "source_type": sig["source_type"],
            "signal_value": sig["signal_value"],
            "source_reliability": sig["source_reliability"],
            "explanation": "Synthetic demo evidence for alignment testing; not a real learner.",
            "metadata": {"demo_seeded": True},
        })
    if new_rows:
        client.table("skill_signals").insert(new_rows).execute()
        created["signals"] += len(new_rows)
    return cohorts


def _demand_row(skill_id: str | None, spec: dict) -> dict:
    count = int(round(spec["share"] * 100))
    return {
        "role_key": SYNTH_ROLE,
        "skill_id": skill_id,
        "source_concept": spec["display"],
        "canonical_skill_slug": spec["skill_slug"],
        "mapping_status": "mapped",
        "location_scope": "city",
        "country": SYNTH_COUNTRY,
        "region": SYNTH_REGION,
        "city": SYNTH_CITY,
        "period_start": SYNTH_PERIOD_START,
        "period_end": SYNTH_PERIOD_END,
        "posting_count": 100,
        "skill_posting_count": count,
        "distinct_company_count": spec["companies"],
        "skill_share": spec["share"],
        "demand": spec["share"],
        "required_level": 0.7,
        "importance": 0.8,
        "trend": spec["trend"],
        "confidence": 0.9,
        "evidence_suppressed": False,
        "provider_id": SYNTH_PROVIDER_ID,
        "data_origin": SYNTH_ORIGIN,
        "source_version": SYNTH_SOURCE_VERSION,
        "evidence_context": "Synthetic demo demand for alignment testing; not live market data.",
    }


def _seed_demand(client, seed, created, skipped, updated) -> None:
    try:
        slookup = client.table("skills").select("id,canonical_name").execute()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to load skill taxonomy")
    slug_to_id = {str(r.get("canonical_name")): str(r.get("id")) for r in (slookup.data or [])}
    missing = sorted({d["skill_slug"] for d in seed["demand"]} - set(slug_to_id))
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Skill taxonomy rows missing for synthetic demand: {missing}",
        )
    for spec in seed["demand"]:
        desired = _demand_row(slug_to_id[spec["skill_slug"]], spec)
        cell = {k: desired[k] for k in (
            "provider_id", "role_key", "canonical_skill_slug", "location_scope",
            "country", "region", "city", "period_start")}
        found = _find(client, "labour_market_demand_signals", cell)
        if found is None:
            client.table("labour_market_demand_signals").insert(desired).execute()
            created["demand"] += 1
            continue
        diff = {k: v for k, v in desired.items()
                if k not in ("id", "created_at", "computed_at")
                and str(found.get(k)) != str(v)}
        # skill_id UUID normalisation can differ in string form; ignore it.
        diff.pop("skill_id", None)
        if diff:
            client.table("labour_market_demand_signals").update(diff).eq("id", found["id"]).execute()
            updated["demand"] += 1
        else:
            skipped["demand"] += 1


def seed_synthetic_alignment() -> dict:
    """Idempotent import of the synthetic alignment fixture.

    Everything is matched by stable synthetic keys (institution/course/cohort
    codes, demo Auth emails, demand cell key, user+skill+source triples), so
    re-running creates nothing twice. Only synthetic rows are ever read or
    written — real students, employers, applications, and placements are
    never touched.
    """
    client = _ensure_client()
    seed = build_synthetic_seed()
    created: dict[str, int] = {k: 0 for k in (
        "institutions", "courses", "modules", "course_skills", "cohorts",
        "auth_users", "members", "signals", "demand")}
    skipped: dict[str, int] = dict(created)
    updated: dict[str, int] = {"demand": 0}

    inst_row, course_row = _seed_institution_and_course(client, seed, created, skipped)
    cohorts = _seed_cohorts_and_learners(client, seed, inst_row, course_row, created, skipped)
    _seed_demand(client, seed, created, skipped, updated)

    return {
        "created": created, "skipped": skipped, "updated": updated,
        "institution_id": inst_row["id"], "course_id": course_row["id"],
        "cohort_id": cohorts["cohort"]["id"],
        "tiny_cohort_id": cohorts["tiny_cohort"]["id"],
        "role": SYNTH_ROLE,
        "location": {"country": SYNTH_COUNTRY, "region": SYNTH_REGION, "city": SYNTH_CITY},
        "provider_id": SYNTH_PROVIDER_ID,
        "data_origin": SYNTH_ORIGIN,
    }
