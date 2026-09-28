"""P0 #4: course / industry alignment tests.

Demand fixtures live in the P0 #1 memory store (deterministic custom
postings); curriculum/cohort fixtures use FakeDB (patched into
institution_service and cohort_supply_service, which the alignment engine
consumes without modification).
"""

import json
import pytest
from unittest.mock import patch
from pathlib import Path

from app.services import course_alignment_service as svc
from app.services import labour_market_service as lm
from app.services import skill_engine as engine

INST_1 = "inst-1"
COURSE_1 = "course-1"
COHORT_1 = "cohort-1"
SKILLS = {
    "react": "11111111-1111-1111-1111-111111111111",
    "java": "22222222-2222-2222-2222-222222222222",
    "sql": "33333333-3333-3333-3333-333333333333",
    "aws": "44444444-4444-4444-4444-444444444444",
    "docker": "55555555-5555-5555-5555-555555555555",
    "kotlin": "66666666-6666-6666-6666-666666666666",
    "python": "77777777-7777-7777-7777-777777777777",
}
U = [f"user-{i}" for i in range(1, 8)]
COMPANIES = ["C1", "C2", "C3", "C4"]


class Result:
    def __init__(self, data):
        self.data = data if isinstance(data, list) else ([data] if data else [])


class FakeQuery:
    def __init__(self, db, table, op="select", payload=None):
        self.db = db
        self.table = table
        self.op = op
        self.payload = payload
        self.filters = []
        self._order = None

    def select(self, *a, **k):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals)))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def _apply(self, rows):
        for kind, col, val in self.filters:
            if kind == "eq":
                rows = [r for r in rows if str(r.get(col)) == str(val)]
            else:
                rows = [r for r in rows if str(r.get(col)) in {str(v) for v in val}]
        if self._order:
            col, desc = self._order
            rows = sorted(rows, key=lambda r: (r.get(col) is None, r.get(col)), reverse=bool(desc))
        return rows

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "select":
            return Result(self._apply(rows))
        if self.op == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            for it in items:
                it.setdefault("id", f"{self.table}-{len(rows) + 1}")
                rows.append(dict(it))
            return Result(items)
        if self.op == "update":
            matched = self._apply(rows)
            for r in matched:
                r.update(self.payload)
            return Result(matched)
        if self.op == "delete":
            matched = self._apply(rows)
            self.db.tables[self.table] = [r for r in rows if r not in matched]
            return Result([])
        raise AssertionError("unknown op")


class FakeDB:
    def __init__(self):
        self.tables: dict[str, list] = {}

    def table(self, name):
        return FakeQuery(self, name)


def _posting(pid, skills, month, day, company="C1"):
    return {
        "external_posting_id": pid, "provider_id": "test_provider",
        "title": "Software Engineer",
        "description": "SWE role needing " + ", ".join(skills) + ".",
        "skills": list(skills), "company_name": company,
        "location_country": "India", "location_region": "Karnataka",
        "location_city": "Bengaluru",
        "published_at": f"{month}-{day:02d}T09:00:00Z",
        "data_origin": "source_data",
    }


def _seed_demand():
    """June/July/August SWE demand: react rising, java declining, sql stable,
    docker tiny-sample (suppressed), aws low-share, one unmapped concept."""
    lm.clear_memory_store()
    raw = []
    n = 0

    def add(skills, month, day):
        nonlocal n
        n += 1
        raw.append(_posting(f"swe-{month}-{n:02d}", skills, month, day,
                            COMPANIES[(n - 1) % 4]))

    for day in range(1, 13):  # June: react 8/12, java 9/12, sql 10/12
        skills = []
        if day <= 8:
            skills.append("React")
        if day <= 9:
            skills.append("Java")
        if day <= 10:
            skills.append("SQL")
        if day == 1:
            skills.append("Blockchain Basics")
        add(skills, "2026-06", day)
    for day in range(1, 13):  # July: react 10/12, java 4/12, sql 10/12, docker x1
        skills = []
        if day <= 10:
            skills.append("React")
        if day <= 4:
            skills.append("Java")
        if day <= 10:
            skills.append("SQL")
        if day == 1:
            skills.append("Docker")
        add(skills, "2026-07", day)
    for day in range(1, 22):  # Aug: react/sql 18/21, java/aws 3/21
        skills = []
        if day <= 18:
            skills.extend(["React", "SQL"])
        if day <= 3:
            skills.extend(["Java", "AWS"])
        add(skills, "2026-08", day)
    return lm.refresh_demand_signals(postings=raw)


def _seed_supply_db():
    d = FakeDB()
    d.tables["skills"] = [
        {"id": sid, "canonical_name": slug, "display_name": slug.title(), "category": "General"}
        for slug, sid in SKILLS.items()
    ]
    d.tables["institutions"] = [{"id": INST_1, "name": "Test Institute"}]
    d.tables["courses"] = [{"id": COURSE_1, "institution_id": INST_1,
                            "name": "Full Stack Web Development", "data_origin": "source_data"}]
    d.tables["course_modules"] = [
        {"id": "m1", "course_id": COURSE_1, "name": "Frontend", "sequence": 1},
        {"id": "m2", "course_id": COURSE_1, "name": "Backend", "sequence": 2},
    ]

    def _cs(slug, module, coverage, importance=None, mapped=True):
        return {"id": f"cs-{slug}", "course_id": COURSE_1, "module_id": module,
                "skill_id": SKILLS.get(slug), "canonical_skill_slug": slug if mapped else None,
                "source_concept": slug if mapped else "Blockchain Basics",
                "mapping_status": "mapped" if mapped else "unmapped",
                "coverage": coverage, "importance": importance}

    d.tables["course_skills"] = [
        _cs("react", "m1", "intermediate", "required"),
        _cs("sql", "m2", "introductory"),
        _cs("kotlin", "m1", "intermediate"),
        _cs("aws", "m2", "introductory"),
        _cs("blockchain", None, None, mapped=False),
    ]
    d.tables["cohorts"] = [{"id": COHORT_1, "institution_id": INST_1, "course_id": COURSE_1,
                            "name": "Batch 2026-A", "status": "active", "data_origin": "source_data"}]
    d.tables["cohort_members"] = [
        {"id": f"mem-{i}", "cohort_id": COHORT_1, "user_id": u,
         "enrollment_status": "active", "joined_at": f"2026-01-0{i}T00:00:00Z"}
        for i, u in enumerate(U[:6], start=1)
    ]

    def _sig(uid, slug, source, value):
        from app.services.evidence_weights import reliability
        return {"user_id": uid, "skill_id": SKILLS[slug], "source_type": source,
                "signal_value": value, "source_reliability": reliability(source)}

    d.tables["skill_signals"] = [
        _sig(U[0], "react", "github", 0.70), _sig(U[0], "react", "project", 0.60),
        _sig(U[1], "react", "assessment", 0.85), _sig(U[2], "react", "assessment", 0.80),
        _sig(U[3], "react", "assessment", 0.75),
        _sig(U[4], "react", "self_declared", 0.60), _sig(U[5], "react", "resume", 0.50),
        _sig(U[0], "sql", "kaggle", 0.75), _sig(U[1], "sql", "github", 0.60),
        _sig(U[2], "sql", "assessment", 0.80), _sig(U[3], "sql", "assessment", 0.85),
        _sig(U[4], "sql", "github", 0.50),
        _sig(U[0], "aws", "self_declared", 0.50),
        _sig(U[0], "python", "github", 0.60),
        _sig(U[0], "docker", "github", 0.50),
        {"user_id": U[0], "skill_id": "unknown-skill-id", "source_type": "github",
         "signal_value": 0.60, "source_reliability": 0.40},
    ]
    d.tables["skill_assessments"] = []
    return d


@pytest.fixture
def db():
    _seed_demand()
    d = _seed_supply_db()
    from app.services import institution_service as inst
    from app.services import cohort_supply_service as coh
    p1 = patch.object(inst, "get_supabase_client", return_value=d)
    p2 = patch.object(coh, "get_supabase_client", return_value=d)
    p1.start()
    p2.start()
    yield d
    p1.stop()
    p2.stop()


def _align(db, **kw):
    params = {"course_id": COURSE_1, "role": "Software Engineer",
              "country": "India", "region": "Karnataka", "city": "Bengaluru"}
    params.update(kw)
    return svc.get_course_alignment(**params)


def _row(out, slug):
    return next(r for r in out["skills"] if r["skill"] == slug)


# ---------------------------------------------------------------------------
# 1–4. Join, unmapped exclusion, role normalization
# ---------------------------------------------------------------------------

def test_canonical_skill_joining(db):
    out = _align(db)
    react = _row(out, "react")
    assert react["industry"] and react["curriculum"] and react["cohort"]
    assert react["industry"]["skill_share"] == pytest.approx(18 / 21, abs=1e-4)
    assert react["curriculum"]["coverage"] == "intermediate"
    assert react["cohort"]["verified_member_count"] == 3


def test_unmapped_labour_skill_exclusion(db):
    out = _align(db)
    assert "blockchain basics" not in {r["skill"] for r in out["skills"]}
    assert out["unmapped_excluded"]["labour"] >= 1


def test_unmapped_course_skill_exclusion(db):
    out = _align(db)
    assert out["unmapped_excluded"]["course"] == 1
    assert all(r["curriculum"] is None or r["curriculum"]["mapping_status"] == "mapped"
               for r in out["skills"])


def test_role_normalization(db):
    full = _align(db, role="Software Engineer")
    alias = _align(db, role="swe")
    assert alias["canonical_role"] == "Software Engineer"
    assert {r["skill"] for r in alias["skills"]} == {r["skill"] for r in full["skills"]}


# ---------------------------------------------------------------------------
# 5–6. Location / date context
# ---------------------------------------------------------------------------

def test_location_context_preservation(db):
    out = _align(db)
    assert out["market_context"]["city"] == "Bengaluru"
    assert out["market_context"]["location_match"] == "exact"
    assert _row(out, "react")["industry"]["location"]["city"] == "Bengaluru"


def test_global_query_does_not_fabricate_city_demand(db):
    out = _align(db, country=None, region=None, city=None)
    assert out["market_context"]["location_match"] == "fallback_global"
    assert out["summary"]["total_market_skills"] == 0
    assert all(r["industry"] is None for r in out["skills"])
    assert all(r["alignment"]["overall_status"] == "insufficient_data" for r in out["skills"])


def test_partial_location_does_not_cross_match(db):
    # City-only query must not silently match Bengaluru/Karnataka/India rows:
    # exact P0 #1 location-key semantics, no cross-context fabrication.
    out = _align(db, country=None, region=None, city="Bengaluru")
    assert out["summary"]["total_market_skills"] == 0
    assert all(r["industry"] is None for r in out["skills"])


def test_date_context_preservation(db):
    out = _align(db, start_date="2026-07-01", end_date="2026-07-31")
    assert out["market_context"]["period_start"] == "2026-07-01"
    assert out["market_context"]["period_end"] == "2026-07-31"
    assert _row(out, "react")["industry"]["posting_count"] == 12
    assert _row(out, "react")["industry"]["skill_share"] == pytest.approx(10 / 12, abs=1e-4)


# ---------------------------------------------------------------------------
# 7–9. Source retrieval reuse
# ---------------------------------------------------------------------------

def test_industry_demand_retrieval(db):
    out = _align(db, start_date="2026-07-01", end_date="2026-07-31")
    java = _row(out, "java")
    assert java["industry"]["posting_count"] == 12
    assert java["industry"]["skill_posting_count"] == 4
    assert java["industry"]["provider_id"] == "test_provider"
    assert java["industry"]["data_origin"] == "source_data"


def test_course_skill_retrieval(db):
    out = _align(db)
    react = _row(out, "react")
    assert react["curriculum"]["modules"] == ["Frontend"]
    assert react["curriculum"]["mapping_status"] == "mapped"
    assert react["curriculum"]["data_origin"] == "source_data"


def test_cohort_supply_retrieval(db):
    out = _align(db)
    react = _row(out, "react")
    assert react["cohort"]["evidenced_member_count"] == 4
    assert react["cohort"]["member_count"] == 6
    assert out["cohort_context"]["mode"] == "course_combined"


def test_single_cohort_selection(db):
    out = _align(db, cohort_id=COHORT_1)
    assert out["cohort_context"]["mode"] == "single_cohort"
    assert out["cohort_context"]["member_count"] == 6
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _align(db, cohort_id="missing-cohort")
    assert exc.value.status_code == 404


def test_cohort_course_mismatch_rejected(db):
    db.tables["courses"].append({"id": "other-course", "institution_id": INST_1, "name": "Other"})
    db.tables["cohorts"].append({"id": "other-cohort", "institution_id": INST_1,
                                 "course_id": "other-course", "name": "Other"})
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _align(db, cohort_id="other-cohort")
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 10–14. Demand × curriculum × supply categories
# ---------------------------------------------------------------------------

def test_required_and_taught_strong(db):
    react = _row(_align(db), "react")
    assert react["alignment"]["curriculum_status"] == "covered"
    assert react["alignment"]["attainment_status"] == "strong"
    assert react["alignment"]["overall_status"] == "aligned"


def test_required_and_missing(db):
    java = _row(_align(db), "java")
    assert java["curriculum"] is None
    assert java["alignment"]["curriculum_status"] == "missing"
    assert java["alignment"]["overall_status"] == "curriculum_gap"


def test_taught_weak_cohort_supply(db):
    aws = _row(_align(db), "aws")
    assert aws["alignment"]["curriculum_status"] == "weakly_covered"
    assert aws["alignment"]["attainment_status"] == "weak"
    assert aws["alignment"]["overall_status"] == "attainment_gap"


def test_taught_moderate_cohort_supply(db):
    sql = _row(_align(db), "sql")
    assert sql["alignment"]["attainment_status"] == "moderate"
    assert sql["alignment"]["overall_status"] == "weak_supply"


def test_taught_insufficient_market_evidence(db):
    kotlin = _row(_align(db), "kotlin")
    assert kotlin["curriculum"]["taught"] is True
    assert kotlin["industry"] is None
    assert kotlin["alignment"]["demand_status"] == "insufficient_market_evidence"
    assert kotlin["alignment"]["overall_status"] == "insufficient_data"


def test_moderate_attainment_rule_unit():
    assert svc._attainment_status(True, 0.30) == "moderate"
    assert svc._overall_status("covered", "moderate", True) == "weak_supply"
    assert svc._overall_status("covered", "strong", True) == "aligned"


# ---------------------------------------------------------------------------
# 15–18. Trends (July window) + suppressed tiny sample
# ---------------------------------------------------------------------------

def test_rising_demand(db):
    react = _row(_align(db, start_date="2026-07-01", end_date="2026-07-31"), "react")
    assert react["alignment"]["demand_status"] == "rising"


def test_stable_demand(db):
    sql = _row(_align(db, start_date="2026-07-01", end_date="2026-07-31"), "sql")
    assert sql["alignment"]["demand_status"] == "stable"


def test_declining_demand(db):
    java = _row(_align(db, start_date="2026-07-01", end_date="2026-07-31"), "java")
    assert java["alignment"]["demand_status"] == "declining"
    assert "obsolete" not in " ".join(java["alignment"]["priority_reasons"]).lower()
    assert any("declining" in r.lower() for r in java["alignment"]["priority_reasons"])


def test_insufficient_trend_data_suppressed(db):
    docker = _row(_align(db, start_date="2026-07-01", end_date="2026-07-31"), "docker")
    assert docker["industry"]["evidence_suppressed"] is True
    assert docker["alignment"]["demand_status"] == "insufficient_data"
    # Tiny sample must not dominate: no high priority from one mentioning post
    assert docker["alignment"]["priority"] != "high"


# ---------------------------------------------------------------------------
# 19–21. Level preservation without false comparability
# ---------------------------------------------------------------------------

def test_required_level_preservation(db):
    out = _align(db)
    for r in out["skills"]:
        if r["industry"]:
            assert r["industry"]["required_level"] is None  # postings don't observe it


def test_course_coverage_preservation(db):
    assert _row(_align(db), "react")["curriculum"]["coverage"] == "intermediate"
    assert _row(_align(db), "sql")["curriculum"]["coverage"] == "introductory"


def test_cohort_proficiency_preservation(db):
    out = _align(db)
    react = _row(out, "react")
    assert react["cohort"]["average_proficiency"] is not None
    assert react["cohort"]["median_proficiency"] is not None
    assert react["cohort"]["average_confidence"] is not None


# ---------------------------------------------------------------------------
# 22–24. No opaque score, determinism, provenance
# ---------------------------------------------------------------------------

def test_no_opaque_score_as_sole_result(db):
    out = _align(db)
    blob = json.dumps(out).lower()
    assert "alignment_score" not in blob and "overall_score" not in blob
    for r in out["skills"]:
        assert set(("industry", "curriculum", "cohort", "alignment")) <= set(r)
        assert set(("curriculum_status", "attainment_status", "demand_status",
                    "overall_status", "priority", "priority_reasons")) <= set(r["alignment"])


def test_deterministic_output(db):
    first, second = _align(db), _align(db)
    first["provenance"].pop("computed_at")
    second["provenance"].pop("computed_at")
    assert first == second


def test_provenance_preservation(db):
    out = _align(db)
    prov = out["provenance"]
    assert prov["engine_version"] == "course-alignment-v1"
    assert prov["computed_at"]
    assert out["market_context"]["providers"] == ["test_provider"]
    assert out["market_context"]["data_origins"] == ["source_data"]
    assert prov["course_data_origin"] == "source_data"
    assert prov["cohort_supply_source"] == "cohort-skill-supply-v1"


# ---------------------------------------------------------------------------
# Priority rules + summary
# ---------------------------------------------------------------------------

def test_priority_reasons_structure(db):
    out = _align(db, start_date="2026-07-01", end_date="2026-07-31")
    react = _row(out, "react")
    # Aligned + rising: low action priority, but the trend is still recorded.
    assert react["alignment"]["priority"] == "low"
    assert any("rising" in r.lower() for r in react["alignment"]["priority_reasons"])
    java = _row(out, "java")
    assert java["alignment"]["priority"] == "medium"
    # High-priority rules (pure-function level): missing+rising, weak+rising.
    rising_row = {"skill_share": 0.50, "trend": "rising", "evidence_suppressed": False}
    assert svc._priority("missing", "insufficient_evidence", rising_row)[0] == "high"
    weak_row = {"skill_share": 0.30, "trend": "rising", "evidence_suppressed": False}
    assert svc._priority("covered", "weak", weak_row)[0] == "high"
    suppressed_row = {"skill_share": 0.50, "trend": "rising", "evidence_suppressed": True}
    assert svc._priority("missing", "insufficient_evidence", suppressed_row)[0] == "medium"


def test_course_level_summary(db):
    s = _align(db)["summary"]
    assert s["total_market_skills"] == 5
    assert s["covered_market_skills"] == 1
    assert s["weakly_covered_market_skills"] == 2
    assert s["missing_market_skills"] == 2
    assert s["strong_attainment_skills"] == 1
    assert s["moderate_attainment_skills"] == 1
    assert s["weak_attainment_skills"] == 1
    assert s["insufficient_market_evidence_skills"] == 1
    assert s["low_demand_skills"] == 2
    assert "course score" not in json.dumps(s).lower()


def test_extra_cohort_skills_listed(db):
    out = _align(db)
    assert out["extra_cohort_skills"] == ["python"]


# ---------------------------------------------------------------------------
# 25–28. Privacy, leakage, insufficient data, role-unmapped
# ---------------------------------------------------------------------------

def test_small_cohort_privacy_suppression(db):
    db.tables["cohorts"].append({"id": "small-cohort", "institution_id": INST_1,
                                 "course_id": COURSE_1, "name": "Tiny",
                                 "status": "active", "data_origin": "source_data"})
    for i, u in enumerate(U[:3]):
        db.tables["cohort_members"].append({"id": f"sm-{i}", "cohort_id": "small-cohort",
                                            "user_id": u, "enrollment_status": "active"})
    out = _align(db, cohort_id="small-cohort")
    assert out["cohort_context"]["suppressed"] is True
    react = _row(out, "react")
    assert react["alignment"]["attainment_status"] == "insufficient_evidence"
    assert react["alignment"]["overall_status"] == "insufficient_data"


def test_no_student_id_leakage(db):
    blob = json.dumps(_align(db))
    for u in U:
        assert u not in blob
    assert "skill_signals" not in blob


def test_role_unmapped_behavior(db):
    out = svc.get_course_alignment(course_id=COURSE_1, role="Quantum Wizard Level 9")
    assert out["role_mapping_status"] == "unmapped"
    assert out["skills"] == []
    assert "cannot be evaluated" in out["note"]


# ---------------------------------------------------------------------------
# 29. No false "obsolete"
# ---------------------------------------------------------------------------

def test_no_false_obsolete_conclusion(db):
    blob = json.dumps(_align(db)).lower()
    assert "obsolete" not in blob


# ---------------------------------------------------------------------------
# API + schema validation
# ---------------------------------------------------------------------------

def test_api_route_registered_and_guarded():
    from app.main import app
    from app.core.security import get_current_user

    targets = [r for r in app.routes if hasattr(r, "path")
               and r.path == "/api/v1/industry/course-alignment"]
    assert len(targets) == 1
    calls = [d.call for d in targets[0].dependant.dependencies]
    assert get_current_user in calls


def test_response_validates_against_schema(db):
    from app.schemas.alignment import CourseAlignmentResponse
    out = _align(db)
    parsed = CourseAlignmentResponse.model_validate(out)
    assert parsed.role == "Software Engineer"
    assert len(parsed.skills) == len(out["skills"])


# ---------------------------------------------------------------------------
# 30–33. P0 regressions + gap math
# ---------------------------------------------------------------------------

def test_p0_1_labour_market_unchanged():
    assert lm.calculate_demand(100, 45) == {"skill_share": 0.45, "demand": 0.45}
    demo = lm.DemoPostingProvider()
    assert demo.is_live is False and demo.data_origin == "demo_seeded"
    from app.services import industry_intelligence as intel
    assert any(p["provider_id"] == "inaura_demo_seed_v1" for p in intel.list_providers())
    assert Path("backend/supabase/030_labour_market_intelligence.sql").exists()


def test_p0_2_institution_supply_unchanged():
    from app.services import institution_service as inst
    assert inst.resolve_skill("React.js")["canonical_skill_slug"] == "react"
    assert [c["code"] for c in inst.build_demo_seed()["courses"]] == ["DEMO-FSWD", "DEMO-MAD", "DEMO-DA"]
    assert Path("backend/supabase/031_institution_course_supply.sql").exists()


def test_p0_3_cohort_supply_unchanged():
    from app.services import cohort_supply_service as coh
    assert coh.MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL == 5
    assert coh.build_demo_seed()["cohort"]["code"] == "DEMO-FSWD-2026A"
    assert Path("backend/supabase/032_cohort_skill_supply.sql").exists()


def test_gap_mathematics_unchanged():
    assert engine.gap(0.50, 0.75) == 0.25
    assert engine.gap(0.85, 0.75) == 0.0
