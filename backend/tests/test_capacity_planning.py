"""P1.4: capacity planning signal tests.

Same fixture style as P1.3 (deterministic demand + FakeDB district). The
core assertion throughout: observed counts pass through, seat capacity is
never invented, and missing data is never a shortage claim.
"""

import json
import re
import pytest
from unittest.mock import patch
from fastapi import HTTPException
from pathlib import Path

from app.services import capacity_planning_service as svc
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
    "sql": "55555555-5555-5555-5555-555555555555",
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
    plan = {
        "2026-06": {"Docker": 3, "Kubernetes": 8, "Git": 6, "SQL": 7},
        "2026-07": {"Docker": 7, "Kubernetes": 9, "Git": 6, "SQL": 7},
    }
    raw = []
    n = 0
    for month, counts in plan.items():
        for day in range(1, 13):
            skills = [s for s, c in counts.items() if day <= c]
            n += 1
            raw.append(_posting(f"p-{n:02d}", skills, month, day))
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
        {"id": "m1", "course_id": "course-1", "name": "Containers", "sequence": 1},
        {"id": "m2", "course_id": "course-1", "name": "Version Control", "sequence": 2},
        {"id": "m3", "course_id": "course-2", "name": "Databases", "sequence": 1},
    ]

    def _cs(cid, slug, module, coverage, mapped=True):
        return {"id": f"cs-{cid}-{slug}", "course_id": cid, "module_id": module,
                "skill_id": SKILLS.get(slug),
                "canonical_skill_slug": slug if mapped else None,
                "source_concept": slug if mapped else "Blockchain Basics",
                "mapping_status": "mapped" if mapped else "unmapped",
                "coverage": coverage, "importance": None}

    d.tables["course_skills"] = [
        _cs("course-1", "docker", "m1", "intermediate"),
        _cs("course-1", "git", "m2", "intermediate"),
        _cs("course-2", "sql", "m3", "intermediate"),
        _cs("course-2", "typescript", None, "introductory"),
    ]
    d.tables["cohorts"] = [
        {"id": "cohort-1", "institution_id": "inst-1", "course_id": "course-1",
         "name": "Batch A", "status": "active", "data_origin": "source_data"},
        {"id": "cohort-2", "institution_id": "inst-2", "course_id": "course-2",
         "name": "Batch B", "status": "active", "data_origin": "source_data"},
    ]
    d.tables["cohort_members"] = (
        [{"id": f"ma-{i}", "cohort_id": "cohort-1", "user_id": u,
          "enrollment_status": "active"} for i, u in enumerate(USERS)]
        + [{"id": f"mb-{i}", "cohort_id": "cohort-2", "user_id": f"v-{i}",
            "enrollment_status": "active"} for i in range(1, 7)]
    )

    def _sig(uid, slug, source, value):
        return {"user_id": uid, "skill_id": SKILLS[slug], "source_type": source,
                "signal_value": value, "source_reliability": reliability(source)}

    d.tables["skill_signals"] = [
        _sig(USERS[0], "docker", "assessment", 0.80),
        _sig(USERS[0], "git", "assessment", 0.80),
        _sig(USERS[1], "git", "assessment", 0.80),
        _sig(USERS[2], "git", "assessment", 0.80),
        _sig(USERS[3], "git", "assessment", 0.80),
        _sig("v-1", "sql", "assessment", 0.80),
        _sig("v-2", "sql", "assessment", 0.80),
        _sig("v-3", "sql", "github", 0.60),
    ]
    d.tables["skill_assessments"] = []
    d.tables["trainers"] = [
        {"id": "t1", "institution_id": "inst-1", "name": "Asha Rao",
         "email": "asha@example.test", "status": "active"},
    ]
    d.tables["trainer_skills"] = [
        {"id": "ts-1", "trainer_id": "t1", "canonical_skill_slug": "git",
         "proficiency": "advanced"},
        {"id": "ts-2", "trainer_id": "t1", "canonical_skill_slug": "sql",
         "proficiency": "intermediate"},
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


def _capacity(db, **kw):
    params = {"district": DISTRICT, "role": ROLE, "state": STATE,
              "country": COUNTRY, "city": CITY, "region": STATE}
    params.update(kw)
    return svc.get_capacity_planning(**params)


def _row(out, skill):
    return next(r for r in out["capacity"] if r["skill"] == skill)


# ---------------------------------------------------------------------------
# Core honesty: observed counts only, capacity never measured
# ---------------------------------------------------------------------------

def test_missing_capacity_data(db):
    out = _capacity(db)
    assert all(r["capacity_status"] == "CAPACITY_DATA_INSUFFICIENT" for r in out["capacity"])
    assert out["capacity_evidence_status"] == "CAPACITY_DATA_INSUFFICIENT"
    assert "no validated capacity data" in out["planning_note"].lower()


def test_available_state_gated(db):
    # The AVAILABLE vocabulary exists for future validated data, but the gate
    # (a validated seat-capacity source, of which the repo has none) keeps it
    # unreachable: zero rows may ever claim it today.
    out = _capacity(db)
    assert out["summary"]["capacity_data_available"] == 0
    assert svc.STATUS_AVAILABLE == "CAPACITY_DATA_AVAILABLE"


def test_zero_learners_not_zero_capacity(db):
    k8s = _row(_capacity(db), "kubernetes")
    assert k8s["learner_count"] == 0
    assert k8s["capacity_status"] == "CAPACITY_DATA_INSUFFICIENT"
    # Missing learner data is missing data — not a shortage, not zero capacity.
    assert "shortage" not in json.dumps(k8s).lower()


def test_suppressed_learners(db):
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
    out = svc.get_capacity_planning(district="Tiny District", role=ROLE,
                                    state=STATE, country=COUNTRY)
    assert out["capacity"] == []  # suppressed P1.1 rows yield no capacity rows
    assert out["summary"]["skills_evaluated"] == 0


def test_trainer_evidence_passthrough(db):
    out = _capacity(db)
    assert _row(out, "git")["trainers_observed"] == 1
    assert _row(out, "kubernetes")["trainers_observed"] == 0
    # Observed counts only — never a requirement or ratio.
    blob = json.dumps(out).lower()
    assert "required trainers" not in blob and "trainer-to-student" not in blob
    assert "student-to-trainer" not in blob and "utilization" not in blob
    assert not re.search(r"\d+\s*:\s*\d+\s*(trainer|student|learner)", blob)


def test_no_trainer_evidence_still_insufficient(db):
    row = _row(_capacity(db), "kubernetes")
    assert row["trainers_observed"] == 0
    assert row["capacity_status"] == "CAPACITY_DATA_INSUFFICIENT"


def test_course_scope(db):
    out = _capacity(db, course_id="course-1")
    assert out["course_id"] == "course-1"
    assert len(out["capacity"]) == len(_capacity(db)["capacity"])
    with pytest.raises(HTTPException) as exc:
        _capacity(db, course_id="nope")
    assert exc.value.status_code in (400, 404)


def test_district_scope(db):
    out = _capacity(db)
    assert out["summary"]["institution_count"] == 2
    assert out["summary"]["course_count"] == 2
    assert out["summary"]["learner_count"] == 12
    docker = _row(out, "docker")
    assert docker["institutions_total"] == 2
    assert docker["courses_teaching"] == 1
    assert docker["learner_count"] == 6
    assert docker["verified_learner_count"] == 1


def test_privacy(db):
    blob = json.dumps(_capacity(db))
    for token in ("t1", "Asha Rao", "asha@example.test") + tuple(USERS):
        assert token not in blob


def test_no_invented_seat_counts(db):
    blob = json.dumps(_capacity(db)).lower()
    assert not re.search(r"add \d+ seats?", blob)
    assert not re.search(r"\d+ seats (required|needed|recommended)", blob)
    assert "recommended seats" not in blob and "required seats" not in blob


def test_no_fabricated_shortage(db):
    blob = json.dumps(_capacity(db)).lower()
    for phrase in ("capacity shortage", "shortage of", "over capacity",
                   "under capacity", "is short of", "full capacity"):
        assert phrase not in blob


def test_p1_1_compatibility(db):
    out = _capacity(db)
    assert {r["priority"] for r in out["capacity"]} <= {"HIGH", "MEDIUM", "LOW", "INSUFFICIENT_EVIDENCE"}
    assert _row(out, "docker")["priority"] == "HIGH"
    assert _row(out, "docker")["status"] == "actionable_gap"


def test_p1_2_p1_3_compatibility(db):
    from app.services import curriculum_proposal_service as prop
    from app.services import trainer_development_service as tdev
    assert prop.ENGINE_VERSION == "curriculum-proposal-v1"
    assert tdev.ENGINE_VERSION == "trainer-development-signal-v1"


def test_api_auth():
    from app.main import app
    from app.core.security import get_current_user
    targets = [r for r in app.routes if hasattr(r, "path")
               and r.path == "/api/v1/industry/capacity-planning"]
    assert len(targets) == 1
    assert get_current_user in [d.call for d in targets[0].dependant.dependencies]


def test_schema_validation(db):
    from app.schemas.capacity_planning import CapacityPlanningResponse
    parsed = CapacityPlanningResponse.model_validate(_capacity(db))
    assert len(parsed.capacity) == len(_capacity(db)["capacity"])
    assert parsed.capacity_evidence_status == "CAPACITY_DATA_INSUFFICIENT"


def test_provenance(db):
    out = _capacity(db)
    assert out["provenance"]["engine_version"] == "capacity-planning-signal-v1"
    assert out["provenance"]["priority_engine_version"] == "training-priority-v1"
    assert out["provenance"]["district_training_version"] == "district-training-v1"
    assert out["provenance"]["computed_at"]


def test_no_llm_invocation():
    text = (Path(__file__).resolve().parents[1] / "app" / "services" /
            "capacity_planning_service.py").read_text().lower()
    for token in ("gemini", "groq", "openai", "anthropic", "chatcompletion",
                  "generate_content", "llm_client", "import llm"):
        assert token not in text


def test_deterministic_output(db):
    first, second = _capacity(db), _capacity(db)
    first["provenance"].pop("computed_at")
    second["provenance"].pop("computed_at")
    assert first == second


def test_role_normalization_and_unmapped(db):
    assert _capacity(db, role="swe")["canonical_role"] == ROLE
    bad = svc.get_capacity_planning(district=DISTRICT, role="Quantum Wizard")
    assert bad["role_mapping_status"] == "unmapped" and bad["capacity"] == []


def test_empty_district(db):
    out = svc.get_capacity_planning(district="Nowhere District", role=ROLE)
    assert out["capacity"] == [] and out["summary"]["skills_evaluated"] == 0


def test_p0_compat_and_gap_math():
    assert lm.calculate_demand(100, 45) == {"skill_share": 0.45, "demand": 0.45}
    from app.services import skill_engine as engine
    assert engine.gap(0.50, 0.75) == 0.25
    assert engine.gap(0.85, 0.75) == 0.0
