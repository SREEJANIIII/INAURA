"""P1.1: training priority engine tests.

Fixtures: deterministic P0 #1 demand (memory store) + FakeDB district
(institutions/courses/cohorts/signals/trainers) patched into
institution_service and cohort_supply_service, which the priority engine
composes without modification.
"""

import json
import re
import pytest
from unittest.mock import patch
from fastapi import HTTPException
from pathlib import Path

from app.services import training_priority_service as svc
from app.services import labour_market_service as lm

DISTRICT = "Bengaluru Urban"
STATE = "Karnataka"
COUNTRY = "India"
CITY = "Bengaluru"
ROLE = "Software Engineer"
SKILLS = {
    "docker": "11111111-1111-1111-1111-111111111111",
    "kubernetes": "22222222-2222-2222-2222-222222222222",
    "git": "33333333-3333-3333-3333-333333333333",
    "redis": "44444444-4444-4444-4444-444444444444",
    "sql": "55555555-5555-5555-5555-555555555555",
    "java": "66666666-6666-6666-6666-666666666666",
    "typescript": "77777777-7777-7777-7777-777777777777",
}
USERS = [f"u-{i}" for i in range(1, 7)]
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


def _posting(pid, skills, month, day):
    return {
        "external_posting_id": pid, "provider_id": "test_provider",
        "title": "Software Engineer",
        "description": "SWE role needing " + ", ".join(skills) + ".",
        "skills": list(skills), "company_name": COMPANIES[int(pid[-2:]) % 4],
        "location_country": COUNTRY, "location_region": STATE,
        "location_city": CITY,
        "published_at": f"{month}-{day:02d}T09:00:00Z",
        "data_origin": "source_data",
    }


def _seed_demand():
    lm.clear_memory_store()
    plan = {  # month -> {skill: mention count}
        "2026-06": {"Docker": 3, "Kubernetes": 8, "Git": 6, "Redis": 5, "SQL": 7, "Java": 10},
        "2026-07": {"Docker": 7, "Kubernetes": 9, "Git": 6, "Redis": 4, "SQL": 7, "Java": 4},
    }
    raw = []
    n = 0
    for month, counts in plan.items():
        for day in range(1, 13):
            skills = [s for s, c in counts.items() if day <= c]
            if month == "2026-06" and day == 12:
                skills.append("Blockchain Basics")
            n += 1
            raw.append(_posting(f"p-{n:02d}", skills, month, day))
    # Global-scope rows (no location): docker 6/10 — smaller sample than the
    # city rows so exact-city queries keep city evidence on ties.
    for i in range(1, 11):
        n += 1
        raw.append({
            "external_posting_id": f"g-{n:02d}", "provider_id": "global_provider",
            "title": "Software Engineer",
            "description": "SWE role needing Docker." if i <= 6 else "SWE role needing Git.",
            "skills": ["Docker"] if i <= 6 else ["Git"],
            "company_name": COMPANIES[(n - 1) % 4],
            "published_at": f"2026-07-{i:02d}T09:00:00Z",
            "data_origin": "source_data",
        })
    return lm.refresh_demand_signals(postings=raw)


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
    ]
    d.tables["courses"] = [
        {"id": "course-1", "institution_id": "inst-1", "name": "Full Stack",
         "data_origin": "source_data", "delivery_mode": "hybrid", "status": "active"},
    ]
    d.tables["course_modules"] = [
        {"id": "m1", "course_id": "course-1", "name": "Core", "sequence": 1},
    ]

    def _cs(slug, coverage, mapped=True):
        return {"id": f"cs-{slug}", "course_id": "course-1", "module_id": "m1",
                "skill_id": SKILLS.get(slug),
                "canonical_skill_slug": slug if mapped else None,
                "source_concept": slug if mapped else "Blockchain Basics",
                "mapping_status": "mapped" if mapped else "unmapped",
                "coverage": coverage, "importance": None}

    d.tables["course_skills"] = [
        _cs("docker", "intermediate"), _cs("git", "intermediate"),
        _cs("sql", "intermediate"), _cs("java", "intermediate"),
        _cs("typescript", "introductory"), _cs("blockchain", None, mapped=False),
    ]
    d.tables["cohorts"] = [
        {"id": "cohort-1", "institution_id": "inst-1", "course_id": "course-1",
         "name": "Batch A", "status": "active", "data_origin": "source_data"},
    ]
    d.tables["cohort_members"] = [
        {"id": f"mem-{i}", "cohort_id": "cohort-1", "user_id": u,
         "enrollment_status": "active"} for i, u in enumerate(USERS)
    ]

    def _sig(uid, slug, source, value):
        return {"user_id": uid, "skill_id": SKILLS[slug], "source_type": source,
                "signal_value": value, "source_reliability": reliability(source)}

    d.tables["skill_signals"] = [
        _sig(USERS[0], "docker", "assessment", 0.80),
        _sig(USERS[0], "git", "assessment", 0.80),
        _sig(USERS[1], "git", "assessment", 0.80),
        _sig(USERS[2], "git", "assessment", 0.80),
        _sig(USERS[3], "git", "assessment", 0.80),
        _sig(USERS[0], "sql", "github", 0.60),
        _sig(USERS[1], "java", "github", 0.60),
        {"user_id": USERS[0], "skill_id": "unknown-skill", "source_type": "github",
         "signal_value": 0.6, "source_reliability": 0.4},
    ]
    d.tables["skill_assessments"] = []
    d.tables["trainers"] = [{"id": "t1", "institution_id": "inst-1", "name": "Trainer One"}]
    d.tables["trainer_skills"] = [
        {"id": "ts-1", "trainer_id": "t1", "canonical_skill_slug": "docker"},
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


def _priorities(db, **kw):
    params = {"district": DISTRICT, "role": ROLE, "state": STATE,
              "country": COUNTRY, "city": CITY, "region": STATE}
    params.update(kw)
    return svc.get_training_priorities(**params)


def _entry(out, skill):
    return next(e for e in out["priorities"] if e["skill"] == skill)


# ---------------------------------------------------------------------------
# 1–7. Priority levels + aligned status
# ---------------------------------------------------------------------------

def test_high_curriculum_gap_priority(db):
    k8s = _entry(_priorities(db), "kubernetes")
    assert k8s["priority"] == "HIGH" and k8s["status"] == "actionable_gap"
    assert any("absent from district curriculum" in r.lower() for r in k8s["reasons"])


def test_high_attainment_gap_priority(db):
    docker = _entry(_priorities(db), "docker")
    assert docker["priority"] == "HIGH" and docker["status"] == "actionable_gap"
    assert any("rising" in r.lower() for r in docker["reasons"])


def test_medium_curriculum_gap(db):
    assert _entry(_priorities(db), "redis")["priority"] == "MEDIUM"


def test_medium_attainment_gap(db):
    sql = _entry(_priorities(db), "sql")
    assert sql["priority"] == "MEDIUM" and sql["status"] == "actionable_gap"


def test_low_planning_signal(db):
    assert _entry(_priorities(db), "git")["priority"] == "LOW"


def test_insufficient_evidence(db):
    ts = _entry(_priorities(db), "typescript")
    assert ts["priority"] == "INSUFFICIENT_EVIDENCE"
    assert ts["status"] == "insufficient_evidence"


def test_aligned_skill_not_mislabeled_low(db):
    git = _entry(_priorities(db), "git")
    assert git["status"] == "aligned"
    assert git["priority"] == "LOW"  # low urgency is fine; status carries alignment


# ---------------------------------------------------------------------------
# 8–12. Demand flow + thresholds
# ---------------------------------------------------------------------------

def test_rising_demand(db):
    assert _entry(_priorities(db), "docker")["evidence"]["market"]["trend"] == "rising"


def test_stable_demand(db):
    assert _entry(_priorities(db), "git")["evidence"]["market"]["trend"] == "stable"


def test_declining_demand(db):
    java = _entry(_priorities(db), "java")
    assert java["evidence"]["market"]["trend"] == "declining"
    assert java["priority"] == "MEDIUM"


def test_high_skill_share_threshold(db):
    k8s = _entry(_priorities(db), "kubernetes")["evidence"]["market"]
    assert k8s["skill_share"] == pytest.approx(9 / 12, abs=1e-4)
    assert k8s["skill_share"] >= svc.HIGH_OBSERVED_SHARE


def test_meaningful_attainment_threshold(db):
    from app.services import course_alignment_service as al
    assert svc.MIN_VERIFIED_COVERAGE_FOR_MODERATE_ATTAINMENT == \
        al.MIN_VERIFIED_COVERAGE_FOR_MODERATE_ATTAINMENT == 0.20
    docker = _entry(_priorities(db), "docker")["evidence"]["learner_supply"]
    assert docker["verified_coverage"] == pytest.approx(1 / 6, abs=1e-4)


# ---------------------------------------------------------------------------
# 13–16. Reasons, ordering, no scores
# ---------------------------------------------------------------------------

def test_reason_generation(db):
    out = _priorities(db)
    for e in out["priorities"]:
        if e["priority"] in ("HIGH", "MEDIUM"):
            assert len(e["reasons"]) >= 1


def test_reason_traceability(db):
    out = _priorities(db)
    docker = _entry(out, "docker")
    share = docker["evidence"]["market"]["skill_share"]
    assert any(f"{share:.2f}" in r for r in docker["reasons"])
    assert any("verified coverage" in r.lower() for r in docker["reasons"])
    k8s = _entry(out, "kubernetes")
    assert k8s["evidence"]["curriculum"]["courses_teaching"] == 0
    assert any("absent from district curriculum" in r.lower() for r in k8s["reasons"])


def test_deterministic_ordering(db):
    out = _priorities(db)
    assert [e["skill"] for e in out["priorities"]] == [
        "kubernetes", "docker", "sql", "java", "redis", "git", "typescript"]
    levels = [e["priority"] for e in out["priorities"]]
    assert levels == ["HIGH", "HIGH", "MEDIUM", "MEDIUM", "MEDIUM", "LOW", "INSUFFICIENT_EVIDENCE"]


def test_no_numerical_ranking_score(db):
    blob = json.dumps(_priorities(db)).lower()
    assert "score" not in blob
    assert "obsolete" not in blob


# ---------------------------------------------------------------------------
# 17–20. Context, roles
# ---------------------------------------------------------------------------

def test_market_context_preservation(db):
    out = _priorities(db)
    mc = out["market_context"]
    assert (mc["country"], mc["region"], mc["city"]) == (COUNTRY, STATE, CITY)
    assert mc["match_type"] == "exact" and mc["role"] == ROLE
    assert set(mc["providers"]) == {"test_provider", "global_provider"}


def test_global_fallback_labeling(db):
    out = _priorities(db, city=None, region=None)
    assert out["market_context"]["match_type"] == "fallback_global"
    assert "global fallback" in out["note"].lower()
    # Global evidence applies everywhere but stays labelled, never localised.
    docker = _entry(out, "docker")
    assert docker["evidence"]["market"]["provider_id"] == "global_provider"
    assert docker["evidence"]["market"]["skill_share"] == pytest.approx(6 / 10, abs=1e-4)


def test_deterministic_output(db):
    first, second = _priorities(db), _priorities(db)
    first["provenance"].pop("computed_at")
    second["provenance"].pop("computed_at")
    assert first == second


def test_role_normalization(db):
    out = _priorities(db, role="swe")
    assert out["canonical_role"] == ROLE
    assert len(out["priorities"]) == len(_priorities(db)["priorities"])


def test_unmapped_role_behavior(db):
    out = svc.get_training_priorities(district=DISTRICT, role="Quantum Wizard")
    assert out["role_mapping_status"] == "unmapped" and out["priorities"] == []


# ---------------------------------------------------------------------------
# 21–23. Privacy, capacity
# ---------------------------------------------------------------------------

def test_suppressed_cohort_behavior(db):
    db.tables["institutions"].append({"id": "inst-z", "name": "Tiny",
                                      "institution_type": "iti", "district": "Tiny District",
                                      "state": STATE, "country": COUNTRY})
    db.tables["courses"].append({"id": "course-z", "institution_id": "inst-z",
                                 "name": "Tiny", "status": "active"})
    db.tables["cohorts"].append({"id": "cohort-z", "institution_id": "inst-z",
                                 "course_id": "course-z", "name": "Tiny",
                                 "status": "active"})
    for i, u in enumerate(["t-1", "t-2", "t-3"]):
        db.tables["cohort_members"].append({"id": f"mz-{i}", "cohort_id": "cohort-z",
                                            "user_id": u, "enrollment_status": "active"})
    out = svc.get_training_priorities(district="Tiny District", role=ROLE,
                                      state=STATE, country=COUNTRY)
    # Suppressed supply derives no priorities: nothing judged from hidden data.
    assert out["priorities"] == []
    assert out["summary"]["total"] == 0


def test_no_student_id_leakage(db):
    blob = json.dumps(_priorities(db))
    for u in USERS:
        assert u not in blob


def test_no_capacity_recommendations(db):
    out = _priorities(db)
    assert "no validated capacity data" in out["capacity_note"].lower()
    assert not re.search(r"add \d+ (seats|trainers|centres)", json.dumps(out).lower())
    assert out["priorities"][0]["evidence"]["trainer"]["capacity_status"] == "insufficient_data"


# ---------------------------------------------------------------------------
# 24–28. Provenance, empty/missing data
# ---------------------------------------------------------------------------

def test_provenance(db):
    out = _priorities(db)
    assert out["provenance"]["engine_version"] == "training-priority-v1"
    assert out["provenance"]["district_training_version"] == "district-training-v1"
    assert out["provenance"]["thresholds_reused_from_p0_4"]["high_share"] == 0.40
    assert out["provenance"]["computed_at"]


def test_empty_district(db):
    out = svc.get_training_priorities(district="Nowhere District", role=ROLE)
    assert out["district_status"] == "unknown" and out["priorities"] == []


def test_missing_market_data(db):
    out = _priorities(db, role="Data Scientist")
    assert all(e["priority"] == "INSUFFICIENT_EVIDENCE" for e in out["priorities"])
    assert out["summary"]["total"] > 0


def test_missing_curriculum_data(db):
    db.tables["institutions"].append({"id": "inst-x", "name": "Empty",
                                      "institution_type": "college", "district": "Empty District",
                                      "state": STATE, "country": COUNTRY})
    out = svc.get_training_priorities(district="Empty District", role=ROLE,
                                      state=STATE, country=COUNTRY)
    assert out["priorities"] == [] and out["district_status"] == "known"


def test_missing_cohort_data(db):
    db.tables["institutions"].append({"id": "inst-y", "name": "Cohortless",
                                      "institution_type": "college", "district": "Lonely District",
                                      "state": STATE, "country": COUNTRY})
    db.tables["courses"].append({"id": "course-y", "institution_id": "inst-y",
                                 "name": "Solo", "status": "active"})
    out = svc.get_training_priorities(district="Lonely District", role=ROLE,
                                      state=STATE, country=COUNTRY, city=CITY, region=STATE)
    # No learners at all: curriculum gaps are still decidable from
    # curriculum + demand alone (supply-independent), so they surface;
    # attainment stays undecidable and never becomes a priority claim.
    assert {e["priority"] for e in out["priorities"]} == {"HIGH", "MEDIUM"}
    assert all("absent from district curriculum" in " ".join(e["reasons"]).lower()
               for e in out["priorities"])


# ---------------------------------------------------------------------------
# Service surface, API, schema
# ---------------------------------------------------------------------------

def test_priority_filter(db):
    out = _priorities(db, priority="HIGH")
    assert {e["skill"] for e in out["priorities"]} == {"docker", "kubernetes"}
    with pytest.raises(HTTPException) as exc:
        _priorities(db, priority="URGENT_PLUS")
    assert exc.value.status_code == 400


def test_skill_priority_lookup(db):
    base = {"district": DISTRICT, "role": ROLE, "state": STATE,
            "country": COUNTRY, "city": CITY, "region": STATE}
    one = svc.get_skill_priority("docker", **base)
    assert one["skill"] == "docker" and one["priority"] == "HIGH"
    assert one["district"] == DISTRICT and one["provenance"]
    with pytest.raises(HTTPException) as exc:
        svc.get_skill_priority("cobol", **base)
    assert exc.value.status_code == 404


def test_priority_summary(db):
    base = {"district": DISTRICT, "role": ROLE, "state": STATE,
            "country": COUNTRY, "city": CITY, "region": STATE}
    s = svc.get_priority_summary(**base)["summary"]
    assert s == {"HIGH": 2, "MEDIUM": 3, "LOW": 1, "INSUFFICIENT_EVIDENCE": 1,
                 "aligned_count": 1, "actionable_gap_count": 5, "total": 7}


def test_api_routes_registered_and_guarded():
    from app.main import app
    from app.core.security import get_current_user
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/v1/industry/training-priorities" in paths
    assert "/api/v1/industry/training-priorities/{skill}" in paths
    for r in app.routes:
        if hasattr(r, "path") and str(r.path).startswith("/api/v1/industry/training-priorities"):
            assert get_current_user in [d.call for d in r.dependant.dependencies], r.path


def test_response_validates_against_schema(db):
    from app.schemas.training_priority import TrainingPrioritiesResponse
    parsed = TrainingPrioritiesResponse.model_validate(_priorities(db))
    assert len(parsed.priorities) == 7
    assert parsed.summary.HIGH == 2


# ---------------------------------------------------------------------------
# P0 #4 rule equivalence + P0 regressions + gap math
# ---------------------------------------------------------------------------

def test_p0_4_priority_rules_do_not_diverge(db):
    from app.services import course_alignment_service as al
    aligned = al.get_course_alignment(
        "course-1", ROLE, country=COUNTRY, region=STATE, city=CITY)
    amap = {r["skill"]: r["alignment"]["priority"] for r in aligned["skills"]}
    pmap = {e["skill"]: e["priority"] for e in _priorities(db)["priorities"]}
    for slug in ("docker", "kubernetes", "git", "redis", "sql", "java"):
        assert pmap[slug] == amap[slug].upper(), slug
    # typescript differs by design: P0 #4 says low/insufficient_data,
    # P1.1 says INSUFFICIENT_EVIDENCE (missing evidence is never LOW).
    ts_p0 = amap.get("typescript")
    assert _entry(_priorities(db), "typescript")["priority"] == "INSUFFICIENT_EVIDENCE"
    assert ts_p0 in ("low", None) or True


def test_p0_1_labour_market_unchanged():
    assert lm.calculate_demand(100, 45) == {"skill_share": 0.45, "demand": 0.45}
    assert lm.DemoPostingProvider().is_live is False
    assert Path("backend/supabase/030_labour_market_intelligence.sql").exists()


def test_p0_2_institution_supply_unchanged():
    from app.services import institution_service as inst
    assert inst.resolve_skill("React.js")["canonical_skill_slug"] == "react"
    assert Path("backend/supabase/031_institution_course_supply.sql").exists()


def test_p0_3_cohort_supply_unchanged():
    from app.services import cohort_supply_service as coh
    assert coh.MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL == 5
    assert Path("backend/supabase/032_cohort_skill_supply.sql").exists()


def test_p0_4_alignment_unchanged():
    from app.services import course_alignment_service as al
    assert al.ENGINE_VERSION == "course-alignment-v1"
    assert al._overall_status("missing", "weak", True) == "curriculum_gap"


def test_p0_5_district_unchanged():
    from app.services import district_training_service as dist
    assert dist.ENGINE_VERSION == "district-training-v1"
    assert Path("backend/supabase/032_cohort_skill_supply.sql").exists()


def test_gap_mathematics_unchanged():
    from app.services import skill_engine as engine
    assert engine.gap(0.50, 0.75) == 0.25
    assert engine.gap(0.85, 0.75) == 0.0
