"""P1.6: outcome feedback loop tests.

FakeDB outcome tables (applications/feedback/skill-feedback/alignments/
placements) plus the district cohort chain and P0 #1 demand. Students with
no cohort history are excluded from district scope; undated rows behave
per documented rules.
"""

import json
import re
import pytest
from unittest.mock import patch
from fastapi import HTTPException
from pathlib import Path

from app.services import outcome_feedback_service as svc
from app.services import labour_market_service as lm

DISTRICT = "Bengaluru Urban"
STATE = "Karnataka"
COUNTRY = "India"
CITY = "Bengaluru"
ROLE = "Software Engineer"
SKILLS = {
    "docker": "11111111-1111-1111-1111-111111111111",
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
        "2026-06": {"Docker": 3, "Git": 6, "SQL": 7},
        "2026-07": {"Docker": 7, "Git": 6, "SQL": 7},
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
    ]
    d.tables["courses"] = [
        {"id": "course-1", "institution_id": "inst-1", "name": "Full Stack",
         "data_origin": "source_data", "delivery_mode": "hybrid", "status": "active"},
    ]
    d.tables["course_modules"] = [
        {"id": "m1", "course_id": "course-1", "name": "Containers", "sequence": 1},
    ]
    d.tables["course_skills"] = [
        {"id": "cs-docker", "course_id": "course-1", "module_id": "m1",
         "skill_id": SKILLS["docker"], "canonical_skill_slug": "docker",
         "source_concept": "docker", "mapping_status": "mapped",
         "coverage": "intermediate", "importance": None},
        {"id": "cs-git", "course_id": "course-1", "module_id": "m1",
         "skill_id": SKILLS["git"], "canonical_skill_slug": "git",
         "source_concept": "git", "mapping_status": "mapped",
         "coverage": "intermediate", "importance": None},
        {"id": "cs-sql", "course_id": "course-1", "module_id": "m1",
         "skill_id": SKILLS["sql"], "canonical_skill_slug": "sql",
         "source_concept": "sql", "mapping_status": "mapped",
         "coverage": "introductory", "importance": None},
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
    ]
    d.tables["skill_assessments"] = [
        {"user_id": USERS[0], "skill_id": SKILLS["docker"], "proficiency": 0.8,
         "confidence": 0.7, "evidence_weight": 1.0, "source_diversity": 1, "evidence_count": 1},
    ]
    # ---- outcome tables ----
    d.tables["employers"] = [{"id": "emp-1", "name": "Acme"}]
    d.tables["hiring_requirements"] = [
        {"id": "req-1", "employer_id": "emp-1", "title": "Software Engineer",
         "role_key": "Software Engineer", "status": "open"},
    ]
    apps, feedbacks, skill_fbs = [], [], []
    # docker: 6 supportive observations (observed >= expected)
    # sql: 6 contradictory observations (observed well below expected)
    # git: 6 mixed-ish supportive observations
    # typescript: 2 observations -> insufficient
    gap_plan = {
        "docker": [0.1, 0.0, 0.2, 0.1, 0.0, 0.1],
        "sql": [-0.3, -0.2, -0.4, -0.3, -0.2, -0.3],
        "git": [0.0, 0.1, 0.0, 0.0, 0.1, 0.0],
        "typescript": [0.1, 0.0],
    }
    n = 0
    for slug, gaps in gap_plan.items():
        for i, gap in enumerate(gaps):
            n += 1
            uid = USERS[i % len(USERS)]
            app_id = f"app-{slug}-{i}"
            fb_id = f"fb-{slug}-{i}"
            apps.append({"id": app_id, "student_id": uid, "hiring_requirement_id": "req-1",
                         "status": "selected", "applied_at": "2026-08-01T00:00:00Z"})
            feedbacks.append({"id": fb_id, "employer_id": "emp-1", "application_id": app_id,
                              "student_id": uid, "overall_comment": "Private comment.",
                              "status": "submitted", "created_at": "2026-08-10T00:00:00Z"})
            skill_fbs.append({"id": f"sfb-{slug}-{i}", "employer_feedback_id": fb_id,
                              "skill_id": SKILLS[slug], "expected_level": 0.7,
                              "observed_level": round(0.7 + gap, 3)})
    # One outsider feedback (no cohort history): excluded from district scope.
    apps.append({"id": "app-out", "student_id": "outsider", "hiring_requirement_id": "req-1",
                 "status": "selected", "applied_at": "2026-08-01T00:00:00Z"})
    feedbacks.append({"id": "fb-out", "employer_id": "emp-1", "application_id": "app-out",
                      "student_id": "outsider", "status": "submitted",
                      "created_at": "2026-08-10T00:00:00Z"})
    skill_fbs.append({"id": "sfb-out", "employer_feedback_id": "fb-out",
                      "skill_id": SKILLS["docker"], "expected_level": 0.7,
                      "observed_level": 0.9})
    d.tables["applications"] = apps
    d.tables["employer_feedback"] = feedbacks
    d.tables["employer_skill_feedback"] = skill_fbs
    d.tables["qualification_alignments"] = [
        {"id": "qa-1", "hiring_requirement_id": "req-1", "course_name": "Full Stack",
         "skill_id": SKILLS["sql"], "coverage": 0.7},
        {"id": "qa-2", "hiring_requirement_id": "req-1", "course_name": "Full Stack",
         "skill_id": SKILLS["sql"], "coverage": 0.8},
        {"id": "qa-3", "hiring_requirement_id": "req-1", "course_name": "Full Stack",
         "skill_id": SKILLS["sql"], "coverage": 0.6},
    ]
    d.tables["placement_outcomes"] = [
        {"id": f"pl-{i}", "student_id": u, "employer_id": "emp-1",
         "application_id": f"app-docker-{i}" if i < 6 else f"app-git-{i - 6}",
         "role_title": "Software Engineer", "status": "joined",
         "outcome_source": "employer_confirmed", "verification_status": "verified",
         "joining_date": "2026-09-01"}
        for i, u in enumerate(USERS)
    ]
    d.tables["trainers"] = [{"id": "t1", "institution_id": "inst-1", "name": "T1"}]
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
    p3 = patch.object(svc, "get_supabase_client", return_value=d)
    p1.start()
    p2.start()
    p3.start()
    yield d
    p1.stop()
    p2.stop()
    p3.stop()


def _feedback(db, **kw):
    params = {"district": DISTRICT, "role": ROLE, "state": STATE,
              "country": COUNTRY, "city": CITY, "region": STATE}
    params.update(kw)
    return svc.get_outcome_feedback(**params)


def _row(out, skill):
    return next(r for r in out["skills"] if r["skill"] == skill)


# ---------------------------------------------------------------------------
# Aggregation states
# ---------------------------------------------------------------------------

def test_supportive_signal(db):
    docker = _row(_feedback(db), "docker")
    assert docker["signal"] == "SUPPORTIVE_SIGNAL"
    assert docker["employer_feedback"]["observations"] == 6
    assert docker["employer_feedback"]["average_observed_minus_expected"] == pytest.approx(0.0833, abs=1e-4)


def test_contradictory_signal(db):
    sql = _row(_feedback(db), "sql")
    assert sql["signal"] == "CONTRADICTORY_SIGNAL"
    assert sql["employer_feedback"]["average_observed_minus_expected"] == pytest.approx(-0.2833, abs=1e-4)


def test_mixed_signal_unit():
    assert svc._signal_for(6, -0.05)[0] == "MIXED_SIGNAL"
    assert svc._signal_for(6, 0.0)[0] == "SUPPORTIVE_SIGNAL"
    assert svc._signal_for(6, -0.10)[0] == "CONTRADICTORY_SIGNAL"
    assert svc._signal_for(4, 0.5)[0] == "INSUFFICIENT_OUTCOME_EVIDENCE"
    assert svc._signal_for(6, None)[0] == "INSUFFICIENT_OUTCOME_EVIDENCE"


def test_insufficient_outcome_evidence(db):
    ts = _row(_feedback(db), "typescript")
    assert ts["signal"] == "INSUFFICIENT_OUTCOME_EVIDENCE"
    assert "insufficient" in ts["limitation"].lower()
    assert ts["sample"]["feedback_suppressed"] is True
    assert ts["sample"]["feedback_count"] is None


def test_placement_aggregation(db):
    docker = _row(_feedback(db), "docker")
    assert docker["sample"]["placement_count"] == 6
    assert docker["sample"]["successful_placements"] == 6


def test_qualification_alignment(db):
    sql = _row(_feedback(db), "sql")
    assert sql["employer_feedback"]["average_coverage"] == pytest.approx(0.7, abs=1e-4)


# ---------------------------------------------------------------------------
# Filters: skill / course / proposal / district / time
# ---------------------------------------------------------------------------

def test_skill_filtering(db):
    out = _feedback(db, skill="docker")
    assert [r["skill"] for r in out["skills"]] == ["docker"]
    one = svc.get_skill_outcome_feedback("docker", district=DISTRICT, role=ROLE)
    assert one["skill"] == "docker" and one["signal"] == "SUPPORTIVE_SIGNAL"
    with pytest.raises(HTTPException) as exc:
        svc.get_skill_outcome_feedback("cobol", district=DISTRICT, role=ROLE)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        svc.get_skill_outcome_feedback("  ", district=DISTRICT, role=ROLE)
    assert exc.value.status_code == 400


def test_course_filtering(db):
    out = _feedback(db, course_id="course-1")
    assert out["course_id"] == "course-1"
    assert len(out["skills"]) == len(_feedback(db)["skills"])
    out2 = _feedback(db)
    db.tables["courses"].append({"id": "course-empty", "institution_id": "inst-1",
                                 "name": "Empty", "status": "active"})
    out3 = svc.get_outcome_feedback(district=DISTRICT, role=ROLE, course_id="course-empty")
    assert out3["skills"] == []
    assert out2["summary"]["skills_observed"] > 0


def test_proposal_filtering(db):
    from app.services import curriculum_proposal_service as prop
    props = prop.get_curriculum_proposals(district=DISTRICT, role=ROLE,
                                          state=STATE, country=COUNTRY,
                                          city=CITY, region=STATE)["proposals"]
    assert len(props) > 0
    pid = props[0]["proposal_id"]
    out = svc.get_outcome_feedback(district=DISTRICT, role=ROLE, proposal_id=pid,
                                   state=STATE, country=COUNTRY, city=CITY, region=STATE)
    assert out["proposal_id"] == pid
    assert out["course_id"] == props[0]["course_id"]
    with pytest.raises(HTTPException) as exc:
        svc.get_outcome_feedback(district=DISTRICT, role=ROLE, proposal_id="prop-missing")
    assert exc.value.status_code == 404


def test_district_filtering(db):
    out = _feedback(db)
    # Outsider feedback (no cohort history) is excluded from district scope…
    assert _row(out, "docker")["employer_feedback"]["observations"] == 6
    # …but visible without the district filter.
    unscoped = svc.get_outcome_feedback(role=ROLE)
    assert _row(unscoped, "docker")["employer_feedback"]["observations"] == 7


def test_time_filtering(db):
    out = _feedback(db, start_date="2026-08-01", end_date="2026-08-31")
    assert out["observation_period"] == {"start": "2026-08-01T00:00:00+00:00",
                                         "end": "2026-08-31T00:00:00+00:00"}
    assert _row(out, "docker")["signal"] == "SUPPORTIVE_SIGNAL"
    empty = _feedback(db, start_date="2020-01-01", end_date="2020-12-31")
    assert all(r["signal"] == "INSUFFICIENT_OUTCOME_EVIDENCE" for r in empty["skills"])
    assert empty["summary"]["insufficient"] == len(empty["skills"]) > 0


# ---------------------------------------------------------------------------
# Mismatch, privacy, causality
# ---------------------------------------------------------------------------

def test_observed_mismatch(db):
    out = _feedback(db)
    sql = _row(out, "sql")
    assert sql["training_priority"] == "MEDIUM"
    assert sql["observed_mismatch"] is True
    docker = _row(out, "docker")
    assert docker["observed_mismatch"] is False
    assert out["summary"]["observed_mismatches"] == 1


def test_no_individual_ids(db):
    blob = json.dumps(_feedback(db))
    for u in USERS + ["outsider"]:
        assert u not in blob
    assert "Private comment." not in blob
    for token in ("app-docker-0", "fb-docker-0", "emp-1", "req-1"):
        assert token not in blob


def test_no_causal_claims(db):
    blob = json.dumps(_feedback(db)).lower()
    for phrase in ("caused", "causes", "led to", "resulted in", "will improve",
                   "causal impact", "proves", "because of the training"):
        assert phrase not in blob


def test_no_skill_assessment_mutation(db):
    before = json.dumps(db.tables, sort_keys=True, default=str)
    _feedback(db)
    svc.get_training_outcome_summary(district=DISTRICT, role=ROLE)
    assert json.dumps(db.tables, sort_keys=True, default=str) == before


def test_no_gap_math_mutation():
    import inspect
    from app.services import outcome_feedback_service as mod
    source = inspect.getsource(mod)
    # Read-only module: no table writes of any kind (hence none to skill,
    # assessment, or gap tables either).
    assert ".insert(" not in source
    assert ".update(" not in source
    assert ".delete(" not in source
    assert ".upsert(" not in source


# ---------------------------------------------------------------------------
# API, schema, provenance, compat
# ---------------------------------------------------------------------------

def test_api_auth():
    from app.main import app
    from app.core.security import get_current_user
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/v1/industry/outcome-feedback" in paths
    assert "/api/v1/industry/outcome-feedback/{skill}" in paths
    for r in app.routes:
        if hasattr(r, "path") and str(r.path).startswith("/api/v1/industry/outcome-feedback"):
            assert get_current_user in [d.call for d in r.dependant.dependencies], r.path


def test_schema_validation(db):
    from app.schemas.outcome_feedback import OutcomeFeedbackResponse
    parsed = OutcomeFeedbackResponse.model_validate(_feedback(db))
    assert parsed.summary.skills_observed == len(parsed.skills) > 0


def test_provenance_and_period(db):
    out = _feedback(db)
    assert out["provenance"]["engine_version"] == "outcome-feedback-v1"
    assert out["provenance"]["min_feedback_observations"] == 5
    assert "ever-membership" in out["provenance"]["membership_basis"]
    assert "causal" in out["provenance"]["note"].lower()
    summary = svc.get_training_outcome_summary(district=DISTRICT, role=ROLE,
                                               state=STATE, country=COUNTRY,
                                               city=CITY, region=STATE)
    assert summary["summary"] == out["summary"]


def test_unmapped_role(db):
    out = svc.get_outcome_feedback(district=DISTRICT, role="Quantum Wizard")
    assert out["role_mapping_status"] == "unmapped" and out["skills"] == []
    with pytest.raises(HTTPException) as exc:
        svc.get_outcome_feedback(district=DISTRICT, role="  ")
    assert exc.value.status_code == 400


def test_no_llm_invocation():
    text = (Path(__file__).resolve().parents[1] / "app" / "services" /
            "outcome_feedback_service.py").read_text().lower()
    for token in ("gemini", "groq", "openai", "anthropic", "chatcompletion",
                  "generate_content", "llm_client", "import llm"):
        assert token not in text


def test_existing_outcome_service_compatibility():
    from app.services import outcome_service as out
    assert out.TRANSITIONS["applied"]["screening"] == "employer"
    assert out.TERMINAL == {"selected", "rejected", "withdrawn"}


def test_p0_p1_compatibility():
    from app.services import training_priority_service as prio
    from app.services import curriculum_proposal_service as prop
    from app.services import proposal_review_service as rev
    assert prio.ENGINE_VERSION == "training-priority-v1"
    assert prop.ENGINE_VERSION == "curriculum-proposal-v1"
    assert rev.ENGINE_VERSION == "proposal-review-v1"
    assert Path("backend/supabase/027_outcomes.sql").exists()
    assert Path("backend/supabase/033_curriculum_proposal_reviews.sql").exists()


def test_gap_mathematics_unchanged():
    from app.services import skill_engine as engine
    assert engine.gap(0.50, 0.75) == 0.25
    assert engine.gap(0.85, 0.75) == 0.0
