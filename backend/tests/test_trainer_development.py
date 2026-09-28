"""P1.3: trainer development signal tests.

Fixtures mirror the P1.1/P1.2 style: deterministic P0 #1 demand plus a
FakeDB district patched into institution_service and cohort_supply_service.
Trainer rows deliberately carry names/emails to prove they never leak.
"""

import json
import pytest
from unittest.mock import patch
from fastapi import HTTPException
from pathlib import Path

from app.services import trainer_development_service as svc
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

    def _cs(cid, slug, module, coverage):
        return {"id": f"cs-{cid}-{slug}", "course_id": cid, "module_id": module,
                "skill_id": SKILLS[slug], "canonical_skill_slug": slug,
                "source_concept": slug, "mapping_status": "mapped",
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
         "email": "asha@example.test", "designation": "Faculty", "status": "active"},
    ]
    d.tables["trainer_skills"] = [
        {"id": "ts-1", "trainer_id": "t1", "canonical_skill_slug": "git",
         "proficiency": "advanced", "source": "verified_certificate"},
        {"id": "ts-2", "trainer_id": "t1", "canonical_skill_slug": "sql",
         "proficiency": "intermediate", "source": "self_reported"},
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


def _signals(db, **kw):
    params = {"district": DISTRICT, "role": ROLE, "state": STATE,
              "country": COUNTRY, "city": CITY, "region": STATE}
    params.update(kw)
    return svc.get_trainer_development_signals(**params)


def _one(out, skill):
    return next(s for s in out["signals"] if s["skill"] == skill)


# ---------------------------------------------------------------------------
# Signal types
# ---------------------------------------------------------------------------

def test_trainer_capability_observed(db):
    git = _one(_signals(db), "git")
    assert git["signal"] == "SUFFICIENT_EVIDENCE"
    assert git["signal_type"] == "TRAINER_CAPABILITY_OBSERVED"
    assert git["trainer_evidence"]["trainer_count"] == 1
    assert git["trainer_evidence"]["institutions_with_skill_trainers"] == 1


def test_no_trainer_observed(db):
    sql = _one(_signals(db), "sql")
    assert sql["signal"] == "DEVELOPMENT_SIGNAL"
    assert sql["signal_type"] == "NO_TRAINER_OBSERVED"
    assert sql["trainer_evidence"]["trainer_count"] == 0
    # Absence is reported as absent evidence, never as inability.
    assert "not evidence of inability" in " ".join(sql["reasons"]).lower()


def test_skill_trainer_mismatch(db):
    docker = _one(_signals(db), "docker")
    assert docker["signal"] == "DEVELOPMENT_SIGNAL"
    assert docker["signal_type"] == "SKILL_TRAINER_MISMATCH"
    assert docker["trainer_evidence"]["trainers_in_teaching_institutions"] == 1


def test_untaught_skill_with_trainers_present_is_mismatch(db):
    k8s = _one(_signals(db), "kubernetes")
    assert k8s["signal"] == "DEVELOPMENT_SIGNAL"
    assert k8s["signal_type"] == "SKILL_TRAINER_MISMATCH"


def test_untaught_skill_without_trainers_is_absent(db):
    out = _signals(db, course_id="course-2")  # inst-2 has no trainers at all
    k8s = _one(out, "kubernetes")
    assert k8s["signal_type"] == "NO_TRAINER_OBSERVED"


def test_insufficient_evidence_without_actionable_priority(db):
    ts = _one(_signals(db), "typescript")
    assert ts["signal"] == "INSUFFICIENT_EVIDENCE"
    assert ts["signal_type"] == "TRAINER_DATA_INSUFFICIENT"


def test_low_trainer_coverage_needs_partial_mapping(db):
    # Direct unit check of the coverage branch: mapped in 1 of 2 teaching
    # institutions is LOW_TRAINER_COVERAGE, not observed, not absent.
    level, stype, _ = svc._determine(
        True, {"i1", "i2"}, {"i1", "i2"}, {"i1"}, 1, 3)
    assert (level, stype) == ("DEVELOPMENT_SIGNAL", "LOW_TRAINER_COVERAGE")
    level, stype, _ = svc._determine(
        True, {"i1", "i2"}, {"i1", "i2"}, {"i1", "i2"}, 2, 3)
    assert (level, stype) == ("SUFFICIENT_EVIDENCE", "TRAINER_CAPABILITY_OBSERVED")
    level, stype, _ = svc._determine(
        False, {"i1"}, {"i1", "i2"}, set(), 0, 0)
    assert (level, stype) == ("INSUFFICIENT_EVIDENCE", "TRAINER_DATA_INSUFFICIENT")


def test_proficiency_breakdown_observed_only(db):
    git = _one(_signals(db), "git")
    assert git["trainer_evidence"]["proficiency_breakdown"] == {"advanced": 1}
    sql = _one(_signals(db), "sql")
    assert sql["trainer_evidence"]["proficiency_breakdown"] == {}


# ---------------------------------------------------------------------------
# Filters + roles + determinism
# ---------------------------------------------------------------------------

def test_district_course_skill_filters(db):
    out = _signals(db, course_id="course-1")
    assert {s["skill"] for s in out["signals"]} <= {"docker", "git", "kubernetes", "sql", "typescript"}
    assert out["course_id"] == "course-1"
    assert len(_signals(db, skill="docker")["signals"]) == 1
    with pytest.raises(HTTPException) as exc:
        _signals(db, course_id="nope")
    assert exc.value.status_code in (400, 404)
    with pytest.raises(HTTPException) as exc:
        _signals(db, signal="MAKE_EVERYTHING_UP")
    assert exc.value.status_code == 400


def test_role_normalization_and_unmapped(db):
    out = _signals(db, role="swe")
    assert out["canonical_role"] == ROLE
    bad = svc.get_trainer_development_signals(district=DISTRICT, role="Quantum Wizard")
    assert bad["role_mapping_status"] == "unmapped" and bad["signals"] == []


def test_deterministic_output(db):
    first, second = _signals(db), _signals(db)
    first["provenance"].pop("computed_at")
    second["provenance"].pop("computed_at")
    assert first == second
    # Rank-grouped order (development first), alphabetical within each level.
    levels = [s["signal"] for s in first["signals"]]
    assert levels == ["DEVELOPMENT_SIGNAL"] * 3 + ["SUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE"]
    assert [s["skill"] for s in first["signals"]] == [
        "docker", "kubernetes", "sql", "git", "typescript"]


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------

def test_no_trainer_identities_leak(db):
    blob = json.dumps(_signals(db))
    for token in ("t1", "Asha Rao", "asha@example.test", "Faculty"):
        assert token not in blob
    for u in USERS:
        assert u not in blob


def test_no_assignment_or_plan_language(db):
    blob = json.dumps(_signals(db)).lower()
    for phrase in ("assign a trainer", "should hire", "hire a trainer",
                   "recruit trainers", "must complete", "required to complete",
                   "training plan for", "you should"):
        assert phrase not in blob


def test_no_fabricated_capability(db):
    blob = json.dumps(_signals(db)).lower()
    assert "no trainer knows" not in blob
    assert "lacks the skill" not in blob
    assert "cannot teach" not in blob


# ---------------------------------------------------------------------------
# Integration + provenance + schema + API
# ---------------------------------------------------------------------------

def test_p1_1_integration(db):
    out = _signals(db)
    docker = _one(out, "docker")
    assert docker["priority"]["level"] == "HIGH"
    assert docker["priority"]["status"] == "actionable_gap"
    assert docker["market_context"]["match_type"] == "exact"


def test_p1_2_integration(db):
    docker = _one(_signals(db), "docker")
    actions = {p["action_type"] for p in docker["related_proposals"]}
    assert actions == {"ADD_PRACTICAL_ASSESSMENT", "ADD_SKILL"}
    assert all(p["proposal_id"] and p["course_id"] for p in docker["related_proposals"])
    k8s = _one(_signals(db), "kubernetes")
    assert len(k8s["related_proposals"]) == 2


def test_provenance(db):
    out = _signals(db)
    assert out["provenance"]["engine_version"] == "trainer-development-signal-v1"
    assert out["provenance"]["priority_engine_version"] == "training-priority-v1"
    assert out["provenance"]["proposal_engine_version"] == "curriculum-proposal-v1"
    assert out["provenance"]["computed_at"]


def test_empty_district(db):
    out = svc.get_trainer_development_signals(district="Nowhere District", role=ROLE)
    assert out["district_status"] == "unknown" and out["signals"] == []
    assert out["summary"]["total"] == 0


def test_response_validates_against_schema(db):
    from app.schemas.trainer_development import TrainerDevelopmentResponse
    parsed = TrainerDevelopmentResponse.model_validate(_signals(db))
    assert len(parsed.signals) == len(_signals(db)["signals"])
    assert parsed.summary["total"] == 5


def test_api_route_registered_and_guarded():
    from app.main import app
    from app.core.security import get_current_user
    targets = [r for r in app.routes if hasattr(r, "path")
               and r.path == "/api/v1/industry/trainer-development-signals"]
    assert len(targets) == 1
    assert get_current_user in [d.call for d in targets[0].dependant.dependencies]


def test_no_llm_invocation():
    text = (Path(__file__).resolve().parents[1] / "app" / "services" /
            "trainer_development_service.py").read_text().lower()
    for token in ("gemini", "groq", "openai", "anthropic", "chatcompletion",
                  "generate_content", "llm_client", "import llm"):
        assert token not in text


# ---------------------------------------------------------------------------
# Compatibility + gap math
# ---------------------------------------------------------------------------

def test_p0_1_compatibility():
    assert lm.calculate_demand(100, 45) == {"skill_share": 0.45, "demand": 0.45}
    assert lm.DemoPostingProvider().is_live is False


def test_p0_2_compatibility():
    from app.services import institution_service as inst
    assert inst.resolve_skill("React.js")["canonical_skill_slug"] == "react"


def test_p0_3_compatibility():
    from app.services import cohort_supply_service as coh
    assert coh.MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL == 5


def test_p0_4_compatibility():
    from app.services import course_alignment_service as al
    assert al.ENGINE_VERSION == "course-alignment-v1"


def test_p1_1_p1_2_compatibility():
    from app.services import training_priority_service as prio
    from app.services import curriculum_proposal_service as prop
    assert prio.ENGINE_VERSION == "training-priority-v1"
    assert prop.ENGINE_VERSION == "curriculum-proposal-v1"


def test_gap_mathematics_unchanged():
    from app.services import skill_engine as engine
    assert engine.gap(0.50, 0.75) == 0.25
    assert engine.gap(0.85, 0.75) == 0.0
