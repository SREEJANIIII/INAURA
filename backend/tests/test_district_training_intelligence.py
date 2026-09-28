"""P0 #5: district training intelligence tests.

FakeDB pattern mirrors earlier phases (patched into institution_service and
cohort_supply_service, which the district engine composes without
modification). Demand fixtures live in the P0 #1 memory store.
"""

import json
import re
import pytest
from unittest.mock import patch
from fastapi import HTTPException
from pathlib import Path

from app.services import district_training_service as svc
from app.services import labour_market_service as lm

DISTRICT = "Bengaluru Urban"
STATE = "Karnataka"
COUNTRY = "India"
CITY = "Bengaluru"
ROLE = "Software Engineer"
SKILLS = {
    "react": "11111111-1111-1111-1111-111111111111",
    "java": "22222222-2222-2222-2222-222222222222",
    "sql": "33333333-3333-3333-3333-333333333333",
    "docker": "44444444-4444-4444-4444-444444444444",
    "aws": "55555555-5555-5555-5555-555555555555",
    "kotlin": "66666666-6666-6666-6666-666666666666",
}
A_USERS = [f"a-user-{i}" for i in range(1, 11)]
B_USERS = [f"b-user-{i}" for i in range(1, 101)]
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
        "location_country": COUNTRY, "location_region": STATE,
        "location_city": CITY,
        "published_at": f"{month}-{day:02d}T09:00:00Z",
        "data_origin": "source_data",
    }


def _gposting(pid, skills, month, day):
    return {
        "external_posting_id": pid, "provider_id": "global_provider",
        "title": "Software Engineer",
        "description": "SWE role needing " + ", ".join(skills) + ".",
        "skills": list(skills), "company_name": COMPANIES[int(pid[-2:]) % 4],
        "published_at": f"{month}-{day:02d}T09:00:00Z",
        "data_origin": "source_data",
    }


def _seed_demand():
    lm.clear_memory_store()
    raw = []
    n = 0

    def add(skills, month, day):
        nonlocal n
        n += 1
        raw.append(_posting(f"d-{month}-{n:02d}", skills, month, day, COMPANIES[(n - 1) % 4]))

    for day in range(1, 13):  # June: react 4, java 10, sql 8, docker 6
        skills = []
        if day <= 4:
            skills.append("React")
        if day <= 10:
            skills.append("Java")
        if day <= 8:
            skills.append("SQL")
        if day <= 6:
            skills.append("Docker")
        if day == 1:
            skills.append("Blockchain Basics")
        add(skills, "2026-06", day)
    for day in range(1, 13):  # July: react 10, java 4, sql 8, docker 7, aws 3
        skills = []
        if day <= 10:
            skills.append("React")
        if day <= 4:
            skills.append("Java")
        if day <= 8:
            skills.append("SQL")
        if day <= 7:
            skills.append("Docker")
        if day <= 3:
            skills.append("AWS")
        add(skills, "2026-07", day)
    # Global-scope rows (no location): react 6/10 — smaller sample than the
    # city rows so exact-city queries keep their city evidence on ties.
    graw = [_gposting(f"g-{i:02d}", ["React"] if i <= 6 else ["SQL"], "2026-07", i)
            for i in range(1, 11)]
    return lm.refresh_demand_signals(postings=raw + graw)


def _seed_db():
    from app.services.evidence_weights import reliability
    d = FakeDB()
    d.tables["skills"] = [
        {"id": sid, "canonical_name": slug, "display_name": slug.title(), "category": "General"}
        for slug, sid in SKILLS.items()
    ]
    d.tables["institutions"] = [
        {"id": "inst-1", "name": "Test College", "institution_type": "college",
         "district": DISTRICT, "state": STATE, "country": COUNTRY},
        {"id": "inst-2", "name": "Test ITI", "institution_type": "iti",
         "district": DISTRICT, "state": STATE, "country": COUNTRY},
    ]
    d.tables["courses"] = [
        {"id": "course-1", "institution_id": "inst-1", "name": "Full Stack",
         "data_origin": "source_data", "delivery_mode": "hybrid", "status": "active"},
        {"id": "course-2", "institution_id": "inst-2", "name": "Backend Basics",
         "data_origin": "source_data", "delivery_mode": "offline", "status": "active"},
    ]
    d.tables["course_modules"] = [
        {"id": "m1", "course_id": "course-1", "name": "Frontend", "sequence": 1},
        {"id": "m2", "course_id": "course-1", "name": "Data", "sequence": 2},
        {"id": "m3", "course_id": "course-2", "name": "Databases", "sequence": 1},
        {"id": "m4", "course_id": "course-2", "name": "Cloud Intro", "sequence": 2},
    ]

    def _cs(cid, slug, module, coverage, mapped=True):
        return {"id": f"cs-{cid}-{slug}", "course_id": cid, "module_id": module,
                "skill_id": SKILLS.get(slug), "canonical_skill_slug": slug if mapped else None,
                "source_concept": slug if mapped else "Blockchain Basics",
                "mapping_status": "mapped" if mapped else "unmapped",
                "coverage": coverage, "importance": None}

    d.tables["course_skills"] = [
        _cs("course-1", "react", "m1", "intermediate"),
        _cs("course-1", "sql", "m2", "intermediate"),
        _cs("course-1", "kotlin", "m1", "intermediate"),
        _cs("course-1", "blockchain", None, None, mapped=False),
        _cs("course-2", "sql", "m3", "intermediate"),
        _cs("course-2", "aws", "m4", "introductory"),
    ]
    d.tables["cohorts"] = [
        {"id": "cohort-a", "institution_id": "inst-1", "course_id": "course-1",
         "name": "Batch A", "status": "active", "data_origin": "source_data"},
        {"id": "cohort-b", "institution_id": "inst-2", "course_id": "course-2",
         "name": "Batch B", "status": "active", "data_origin": "source_data"},
    ]
    d.tables["cohort_members"] = (
        [{"id": f"ma-{i}", "cohort_id": "cohort-a", "user_id": u,
          "enrollment_status": "active"} for i, u in enumerate(A_USERS)]
        + [{"id": f"mb-{i}", "cohort_id": "cohort-b", "user_id": u,
            "enrollment_status": "active"} for i, u in enumerate(B_USERS)]
    )

    def _sig(uid, slug, source, value):
        return {"user_id": uid, "skill_id": SKILLS[slug], "source_type": source,
                "signal_value": value, "source_reliability": reliability(source)}

    sigs = [
        _sig(A_USERS[0], "react", "github", 0.70),
        _sig(A_USERS[0], "react", "project", 0.60),
        _sig(A_USERS[1], "react", "assessment", 0.85),
        _sig(A_USERS[2], "react", "self_declared", 0.60),
    ]
    sigs += [_sig(u, "sql", "assessment", 0.80) for u in A_USERS[:8]]
    sigs += [_sig(A_USERS[8], "sql", "github", 0.60)]
    sigs += [_sig(u, "react", "assessment", 0.80) for u in B_USERS[:10]]
    sigs += [_sig(u, "sql", "assessment", 0.75) for u in B_USERS[:20]]
    sigs += [{"user_id": A_USERS[0], "skill_id": "unknown-skill",
              "source_type": "github", "signal_value": 0.6, "source_reliability": 0.4}]
    d.tables["skill_signals"] = sigs
    d.tables["skill_assessments"] = []
    d.tables["trainers"] = [
        {"id": "t1", "institution_id": "inst-1", "name": "Trainer One"},
        {"id": "t2", "institution_id": "inst-2", "name": "Trainer Two"},
    ]
    d.tables["trainer_skills"] = [
        {"id": "ts-1", "trainer_id": "t1", "canonical_skill_slug": "react"},
        {"id": "ts-2", "trainer_id": "t1", "canonical_skill_slug": "sql"},
        {"id": "ts-3", "trainer_id": "t2", "canonical_skill_slug": "sql"},
    ]
    return d


@pytest.fixture
def db():
    _seed_demand()
    d = _seed_db()
    from app.services import institution_service as inst
    from app.services import cohort_supply_service as coh
    p1 = patch.object(inst, "get_supabase_client", return_value=d)
    p2 = patch.object(coh, "get_supabase_client", return_value=d)
    p1.start()
    p2.start()
    yield d
    p1.stop()
    p2.stop()


def _district(db, **kw):
    params = {"district": DISTRICT, "role": ROLE, "state": STATE,
              "country": COUNTRY, "city": CITY, "region": STATE}
    params.update(kw)
    return svc.get_district_training(**params)


def _skill(out, slug):
    return next(s for s in out["skills"] if s["skill"] == slug)


# ---------------------------------------------------------------------------
# 1–5. Identification + institution/course/cohort/learner aggregation
# ---------------------------------------------------------------------------

def test_district_identification(db):
    out = _district(db)
    assert out["district"] == DISTRICT and out["district_status"] == "known"
    assert {i["name"] for i in out["institutions"]} == {"Test College", "Test ITI"}


def test_institution_aggregation(db):
    s = _district(db)["summary"]
    assert s["institution_count"] == 2
    assert s["institution_count_by_type"] == {"college": 1, "iti": 1}


def test_course_aggregation(db):
    s = _district(db)["summary"]
    assert s["course_count"] == 2
    assert s["course_count_by_delivery_mode"] == {"hybrid": 1, "offline": 1}


def test_cohort_aggregation(db):
    s = _district(db)["summary"]
    assert s["cohort_count"] == 2
    assert s["suppressed_cohort_count"] == 0


def test_learner_aggregation(db):
    assert _district(db)["summary"]["learner_count"] == 110


# ---------------------------------------------------------------------------
# 6. Learner-weighted aggregation (spec case: 8/10 + 20/100 = 28/110)
# ---------------------------------------------------------------------------

def test_learner_weighted_skill_aggregation(db):
    sql = _skill(_district(db), "sql")
    ts = sql["training_supply"]
    assert ts["learner_count"] == 110
    assert ts["evidenced_learner_count"] == 29
    assert ts["verified_learner_count"] == 28
    assert ts["verified_coverage"] == pytest.approx(28 / 110, abs=1e-4)
    assert ts["verified_coverage"] != pytest.approx(0.50)


def test_weighted_averages_not_means_of_ratios(db):
    from app.services import cohort_supply_service as coh
    a = coh.get_cohort_skill_supply("cohort-a")
    b = coh.get_cohort_skill_supply("cohort-b")
    ra = next(s for s in a["skills"] if s["skill"] == "sql")
    rb = next(s for s in b["skills"] if s["skill"] == "sql")
    sql = _skill(_district(db), "sql")["training_supply"]
    expected = (ra["average_proficiency"] * 9 + rb["average_proficiency"] * 20) / 29
    assert sql["average_proficiency"] == pytest.approx(expected, abs=1e-4)


# ---------------------------------------------------------------------------
# 7–8. Canonical join + labour reuse
# ---------------------------------------------------------------------------

def test_canonical_skill_joining(db):
    out = _district(db)
    assert {s["skill"] for s in out["skills"]} >= {"react", "java", "sql", "docker", "aws", "kotlin"}
    assert not hasattr(svc, "RAW_TAXONOMY")


def test_labour_market_reuse(db):
    react = _skill(_district(db), "react")["market"]
    assert react["posting_count"] == 12 and react["skill_posting_count"] == 10
    assert react["skill_share"] == pytest.approx(10 / 12, abs=1e-4)
    assert react["trend"] == "rising" and react["provider_id"] == "test_provider"


# ---------------------------------------------------------------------------
# 9–12. Location match labelling
# ---------------------------------------------------------------------------

def test_exact_location_labeling(db):
    assert _district(db)["market_context"]["match_type"] == "exact"


def test_global_fallback_labeling(db):
    out = _district(db, city=None, region=None)
    assert out["market_context"]["match_type"] == "fallback_global"
    assert "global fallback" in out["note"].lower()
    # Global evidence applies everywhere but is labelled, never localised.
    react = _skill(out, "react")
    assert react["market"]["provider_id"] == "global_provider"
    assert react["market"]["skill_share"] == pytest.approx(6 / 10, abs=1e-4)


def test_no_regional_fallback_invents_demand(db):
    # Region-only query: city rows must not cross-match (exact P0 #1 keys),
    # but global rows still apply — labelled fallback, never localised.
    out = _district(db, city=None, region=STATE)
    assert out["market_context"]["match_type"] == "fallback_global"
    for s in out["skills"]:
        if s["market"] is not None:
            assert s["market"]["provider_id"] == "global_provider"


def test_location_match_preservation(db):
    out = _district(db)
    assert out["market_context"]["country"] == COUNTRY
    assert out["market_context"]["region"] == STATE
    assert out["market_context"]["city"] == CITY


# ---------------------------------------------------------------------------
# 13–15. Curriculum / attainment / concentration gaps
# ---------------------------------------------------------------------------

def test_curriculum_gap_aggregation(db):
    java = _skill(_district(db), "java")
    assert java["curriculum"]["courses_teaching"] == 0
    assert java["curriculum"]["courses_missing"] == 2
    assert java["gap"]["curriculum"] == "district_curriculum_gap"


def test_attainment_gap_aggregation(db):
    react = _skill(_district(db), "react")
    assert react["training_supply"]["verified_coverage"] == pytest.approx(11 / 110, abs=1e-4)
    assert react["gap"]["attainment"] == "district_attainment_gap"


def test_concentration_signal(db):
    kotlin = _skill(_district(db), "kotlin")
    assert kotlin["gap"]["concentration"] == "concentrated"
    assert _skill(_district(db), "sql")["gap"]["concentration"] == "distributed"
    assert _skill(_district(db), "java")["gap"]["concentration"] == "absent"
    # Descriptive only: concentration alone never forces high priority
    assert kotlin["priority"]["level"] == "low"


# ---------------------------------------------------------------------------
# 16–19. Trainers + capacity honesty
# ---------------------------------------------------------------------------

def test_trainer_counts(db):
    react = _skill(_district(db), "react")["trainer"]
    assert react["trainer_count"] == 1
    assert react["institutions_with_skill_trainers"] == 1
    assert react["trainer_skill_coverage"] == pytest.approx(0.5)
    sql = _skill(_district(db), "sql")["trainer"]
    assert sql["trainer_count"] == 2 and sql["trainer_skill_coverage"] == pytest.approx(1.0)


def test_trainer_signal_behavior(db):
    out = _district(db)
    assert _skill(out, "react")["trainer"]["trainer_signal"] == "observed"
    assert _skill(out, "kotlin")["trainer"]["trainer_signal"] == "no_trainer_observed"
    assert _skill(out, "java")["trainer"]["trainer_signal"] == "not_applicable"
    for s in out["skills"]:
        assert s["trainer"]["capacity_status"] == "insufficient_data"


def test_capacity_evidence_status(db):
    cap = _district(db)["capacity"]
    assert cap["capacity_evidence_status"] == "partial_data"
    assert cap["current_course_count"] == 2 and cap["current_learner_count"] == 110
    assert "no validated capacity data" in cap["seat_note"].lower()


def test_no_unsupported_seat_recommendations(db):
    blob = json.dumps(_district(db)).lower()
    assert not re.search(r"add \d+ seats?", blob)
    assert "seat-capacity recommendation unavailable" in blob


# ---------------------------------------------------------------------------
# 20–22. Priority reasons, determinism, ordering
# ---------------------------------------------------------------------------

def test_priority_reasons(db):
    out = _district(db)
    react = _skill(out, "react")
    assert react["priority"]["level"] == "high"
    joined = " ".join(react["priority"]["reasons"]).lower()
    assert "rising" in joined and "verified coverage" in joined
    docker = _skill(out, "docker")
    assert docker["priority"]["level"] == "high"
    assert any("absent from district curriculum" in r.lower()
               for r in docker["priority"]["reasons"])
    assert "obsolete" not in json.dumps(out).lower()


def test_deterministic_priority_and_output(db):
    first, second = _district(db), _district(db)
    first["provenance"].pop("computed_at")
    second["provenance"].pop("computed_at")
    assert first == second


def test_deterministic_output_ordering(db):
    slugs = [s["skill"] for s in _district(db)["skills"]]
    assert slugs == sorted(slugs)


# ---------------------------------------------------------------------------
# 23–27. Empty / missing data handling
# ---------------------------------------------------------------------------

def test_empty_district(db):
    out = svc.get_district_training(district="Nowhere District", role=ROLE)
    assert out["district_status"] == "unknown" and out["skills"] == []
    assert out["summary"]["institution_count"] == 0
    assert out["capacity"]["capacity_evidence_status"] == "insufficient_data"


def test_missing_district(db):
    with pytest.raises(HTTPException) as exc:
        svc.get_district_training(district="  ", role=ROLE)
    assert exc.value.status_code == 400


def test_missing_market_data(db):
    out = _district(db, role="Data Scientist")
    assert out["market_context"]["match_type"] == "insufficient_data"
    assert all(s["market"] is None for s in out["skills"])
    assert out["summary"]["high_priority_skill_count"] == 0


def test_missing_course_data(db):
    db.tables["institutions"].append({"id": "inst-x", "name": "Empty Inst",
                                      "institution_type": "college", "district": "Empty District",
                                      "state": STATE, "country": COUNTRY})
    out = svc.get_district_training(district="Empty District", role=ROLE,
                                    state=STATE, country=COUNTRY)
    assert out["district_status"] == "known"
    assert out["summary"]["course_count"] == 0 and out["skills"] == []
    assert out["market_context"]["match_type"] == "insufficient_data"


def test_missing_cohort_data(db):
    db.tables["institutions"].append({"id": "inst-y", "name": "Cohortless",
                                      "institution_type": "college", "district": "Lonely District",
                                      "state": STATE, "country": COUNTRY})
    db.tables["courses"].append({"id": "course-y", "institution_id": "inst-y",
                                 "name": "Solo", "status": "active"})
    out = svc.get_district_training(district="Lonely District", role=ROLE,
                                    state=STATE, country=COUNTRY, city=CITY, region=STATE)
    assert out["summary"]["learner_count"] == 0
    assert out["summary"]["cohort_count"] == 0
    assert out["suppressed"] is False


# ---------------------------------------------------------------------------
# 28–29. Privacy
# ---------------------------------------------------------------------------

def test_small_cohort_privacy(db):
    db.tables["institutions"].append({"id": "inst-z", "name": "Tiny Inst",
                                      "institution_type": "iti", "district": "Tiny District",
                                      "state": STATE, "country": COUNTRY})
    db.tables["courses"].append({"id": "course-z", "institution_id": "inst-z",
                                 "name": "Tiny Course", "status": "active"})
    db.tables["cohorts"].append({"id": "cohort-z", "institution_id": "inst-z",
                                 "course_id": "course-z", "name": "Tiny",
                                 "status": "active"})
    for i, u in enumerate(["t-user-1", "t-user-2", "t-user-3"]):
        db.tables["cohort_members"].append({"id": f"mz-{i}", "cohort_id": "cohort-z",
                                            "user_id": u, "enrollment_status": "active"})
    out = svc.get_district_training(district="Tiny District", role=ROLE,
                                    state=STATE, country=COUNTRY, city=CITY, region=STATE)
    assert out["suppressed"] is True and out["skills"] == []
    assert out["summary"]["learner_count"] == 3
    assert out["summary"]["suppressed_learner_count"] == 3


def test_no_user_id_leakage(db):
    blob = json.dumps(_district(db))
    for u in A_USERS + B_USERS:
        assert u not in blob
    assert "skill_signals" not in blob


# ---------------------------------------------------------------------------
# 30–33. Provenance, role, date, provider
# ---------------------------------------------------------------------------

def test_provenance(db):
    out = _district(db)
    assert out["provenance"]["engine_version"] == "district-training-v1"
    assert out["provenance"]["course_alignment_version"] == "course-alignment-v1"
    assert out["provenance"]["cohort_supply_version"] == "cohort-skill-supply-v1"
    assert out["provenance"]["computed_at"]


def test_role_normalization(db):
    out = _district(db, role="swe")
    assert out["canonical_role"] == "Software Engineer"
    assert {s["skill"] for s in out["skills"]} == {s["skill"] for s in _district(db)["skills"]}
    bad = svc.get_district_training(district=DISTRICT, role="Quantum Wizard")
    assert bad["role_mapping_status"] == "unmapped" and bad["skills"] == []


def test_date_filtering(db):
    out = _district(db, start_date="2026-07-01", end_date="2026-07-31")
    assert out["market_context"]["period_start"] == "2026-07-01"
    assert _skill(out, "react")["market"]["skill_share"] == pytest.approx(10 / 12, abs=1e-4)


def test_provider_filtering(db):
    out = _district(db, provider_id="no-such-provider")
    assert out["market_context"]["match_type"] == "insufficient_data"
    assert all(s["market"] is None for s in out["skills"])


# ---------------------------------------------------------------------------
# Service surface, API, schemas
# ---------------------------------------------------------------------------

def test_service_surface_projections(db):
    base = {"district": DISTRICT, "role": ROLE, "state": STATE,
            "country": COUNTRY, "city": CITY, "region": STATE}
    assert set(svc.get_district_summary(**base)) >= {"summary", "capacity", "market_context"}
    skills = svc.get_district_skill_intelligence(**base)
    assert len(skills["skills"]) == len(_district(db)["skills"])
    gaps = svc.get_district_training_gaps(**base)
    assert {g["skill"] for g in gaps["gaps"]} == {"react", "java", "docker"}
    pri = svc.get_district_priority_signals(**base)
    assert [p["skill"] for p in pri["signals"] if p["priority"]["level"] == "high"] == ["docker", "react"]
    assert all("reasons" in p["priority"] for p in pri["signals"])


def test_api_route_registered_and_guarded():
    from app.main import app
    from app.core.security import get_current_user
    targets = [r for r in app.routes if hasattr(r, "path")
               and r.path == "/api/v1/industry/district-training"]
    assert len(targets) == 1
    assert get_current_user in [d.call for d in targets[0].dependant.dependencies]


def test_response_validates_against_schema(db):
    from app.schemas.district_training import DistrictTrainingResponse
    parsed = DistrictTrainingResponse.model_validate(_district(db))
    assert parsed.district == DISTRICT and len(parsed.skills) > 0


# ---------------------------------------------------------------------------
# 34–38. P0 regressions + gap math
# ---------------------------------------------------------------------------

def test_p0_1_labour_market_unchanged():
    assert lm.calculate_demand(100, 45) == {"skill_share": 0.45, "demand": 0.45}
    demo = lm.DemoPostingProvider()
    assert demo.is_live is False and demo.data_origin == "demo_seeded"
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


def test_p0_4_alignment_unchanged():
    from app.services import course_alignment_service as al
    assert al.ENGINE_VERSION == "course-alignment-v1"
    assert al._overall_status("missing", "weak", True) == "curriculum_gap"
    assert al.HIGH_OBSERVED_SHARE == svc.HIGH_SHARE


def test_gap_mathematics_unchanged():
    from app.services import skill_engine as engine
    assert engine.gap(0.50, 0.75) == 0.25
    assert engine.gap(0.85, 0.75) == 0.0
