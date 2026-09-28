"""P2 end-to-end integration scenario: one deterministic Docker/Kubernetes
flow across all ten layers, from labour-market evidence to outcome feedback.

Layers exercised with shared fixtures (FakeDB + P0 #1 memory store):
  demand -> alignment -> cohort supply -> district -> priority -> proposal
  -> trainer signal -> capacity -> human review -> outcome feedback,
plus global-fallback honesty, suppression preservation, and unmapped
exclusion throughout.
"""

import json
import pytest
from unittest.mock import patch
from pathlib import Path

from app.services import labour_market_service as lm
from app.services import industry_roles as roles
from app.services import skill_engine as engine

DISTRICT = "Bengaluru Urban"
TINY_DISTRICT = "Tiny District"
STATE = "Karnataka"
COUNTRY = "India"
CITY = "Bengaluru"
ROLE = "Software Engineer"
SKILLS = {
    "docker": "11111111-1111-1111-1111-111111111111",
    "kubernetes": "22222222-2222-2222-2222-222222222222",
    "git": "33333333-3333-3333-3333-333333333333",
    "sql": "55555555-5555-5555-5555-555555555555",
}
USERS = [f"u-{i}" for i in range(1, 7)]
COMPANIES = ["C1", "C2", "C3", "C4"]
CTX = {"district": DISTRICT, "role": ROLE, "state": STATE,
       "country": COUNTRY, "city": CITY, "region": STATE}


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


def _posting(pid, skills, month, day, loc=True):
    row = {
        "external_posting_id": pid, "provider_id": "test_provider",
        "title": "Software Engineer",
        "description": "SWE role needing " + ", ".join(skills) + ".",
        "skills": list(skills), "company_name": COMPANIES[int(pid[-2:]) % 4],
        "published_at": f"{month}-{day:02d}T09:00:00Z",
        "data_origin": "source_data",
    }
    if loc:
        row.update({"location_country": COUNTRY, "location_region": STATE,
                    "location_city": CITY})
    return row


def _seed_demand():
    lm.clear_memory_store()
    plan = {
        "2026-06": {"Docker": 3, "Kubernetes": 8, "Git": 6},
        "2026-07": {"Docker": 7, "Kubernetes": 9, "Git": 6},
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
    for i in range(1, 11):  # global-scope docker rows for fallback honesty
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
        {"id": "inst-tiny", "name": "Tiny Inst", "institution_type": "iti",
         "district": TINY_DISTRICT, "state": STATE, "country": COUNTRY},
    ]
    d.tables["courses"] = [
        {"id": "course-1", "institution_id": "inst-1", "name": "Full Stack",
         "data_origin": "source_data", "delivery_mode": "hybrid", "status": "active"},
        {"id": "course-tiny", "institution_id": "inst-tiny", "name": "Tiny Course",
         "data_origin": "source_data", "delivery_mode": "offline", "status": "active"},
    ]
    d.tables["course_modules"] = [
        {"id": "m1", "course_id": "course-1", "name": "Containers", "sequence": 1},
        {"id": "m2", "course_id": "course-1", "name": "Version Control", "sequence": 2},
    ]
    d.tables["course_skills"] = [
        {"id": "cs-docker", "course_id": "course-1", "module_id": "m1",
         "skill_id": SKILLS["docker"], "canonical_skill_slug": "docker",
         "source_concept": "docker", "mapping_status": "mapped",
         "coverage": "intermediate", "importance": None},
        {"id": "cs-git", "course_id": "course-1", "module_id": "m2",
         "skill_id": SKILLS["git"], "canonical_skill_slug": "git",
         "source_concept": "git", "mapping_status": "mapped",
         "coverage": "intermediate", "importance": None},
        {"id": "cs-raw", "course_id": "course-1", "module_id": None,
         "skill_id": None, "canonical_skill_slug": None,
         "source_concept": "Blockchain Basics", "mapping_status": "unmapped",
         "coverage": None, "importance": None},
    ]
    d.tables["cohorts"] = [
        {"id": "cohort-1", "institution_id": "inst-1", "course_id": "course-1",
         "name": "Batch A", "status": "active", "data_origin": "source_data"},
        {"id": "cohort-tiny", "institution_id": "inst-tiny", "course_id": "course-tiny",
         "name": "Tiny", "status": "active", "data_origin": "source_data"},
    ]
    d.tables["cohort_members"] = (
        [{"id": f"ma-{i}", "cohort_id": "cohort-1", "user_id": u,
          "enrollment_status": "active"} for i, u in enumerate(USERS)]
        + [{"id": f"mt-{i}", "cohort_id": "cohort-tiny", "user_id": f"zx-{i}",
            "enrollment_status": "active"} for i in range(1, 4)]
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
        {"user_id": USERS[0], "skill_id": "unknown-skill", "source_type": "github",
         "signal_value": 0.6, "source_reliability": 0.4},
    ]
    d.tables["skill_assessments"] = []
    d.tables["trainers"] = [
        {"id": "t1", "institution_id": "inst-1", "name": "Asha Rao",
         "email": "asha@example.test", "status": "active"},
    ]
    d.tables["trainer_skills"] = [
        {"id": "ts-1", "trainer_id": "t1", "canonical_skill_slug": "git",
         "proficiency": "advanced"},
    ]
    # ---- outcome tables ----
    d.tables["employers"] = [{"id": "emp-1", "name": "Acme"}]
    d.tables["hiring_requirements"] = [
        {"id": "req-1", "employer_id": "emp-1", "title": "Software Engineer",
         "role_key": "Software Engineer", "status": "open"},
    ]
    apps, feedbacks, skill_fbs = [], [], []
    gaps = {"docker": [0.1, 0.0, 0.2, 0.1, 0.0, 0.1],
            "sql": [-0.3, -0.2, -0.4, -0.3, -0.2, -0.3]}
    for slug, values in gaps.items():
        for i, gap in enumerate(values):
            uid = USERS[i]
            apps.append({"id": f"app-{slug}-{i}", "student_id": uid,
                         "hiring_requirement_id": "req-1", "status": "selected",
                         "applied_at": "2026-08-01T00:00:00Z"})
            feedbacks.append({"id": f"fb-{slug}-{i}", "employer_id": "emp-1",
                              "application_id": f"app-{slug}-{i}", "student_id": uid,
                              "status": "submitted", "created_at": "2026-08-10T00:00:00Z"})
            skill_fbs.append({"id": f"sfb-{slug}-{i}", "employer_feedback_id": f"fb-{slug}-{i}",
                              "skill_id": SKILLS.get(slug, "unknown-skill"),
                              "expected_level": 0.7,
                              "observed_level": round(0.7 + gap, 3)})
    apps.append({"id": "app-ts-0", "student_id": USERS[0],
                 "hiring_requirement_id": "req-1", "status": "selected",
                 "applied_at": "2026-08-01T00:00:00Z"})
    feedbacks.append({"id": "fb-ts-0", "employer_id": "emp-1",
                      "application_id": "app-ts-0", "student_id": USERS[0],
                      "status": "submitted", "created_at": "2026-08-10T00:00:00Z"})
    skill_fbs.append({"id": "sfb-ts-0", "employer_feedback_id": "fb-ts-0",
                      "skill_id": "unknown-skill", "expected_level": 0.7,
                      "observed_level": 0.7})
    d.tables["applications"] = apps
    d.tables["employer_feedback"] = feedbacks
    d.tables["employer_skill_feedback"] = skill_fbs
    d.tables["qualification_alignments"] = []
    d.tables["placement_outcomes"] = [
        {"id": f"pl-{i}", "student_id": u, "employer_id": "emp-1",
         "application_id": f"app-docker-{i}", "role_title": "Software Engineer",
         "status": "joined", "outcome_source": "employer_confirmed",
         "verification_status": "verified", "joining_date": "2026-09-01"}
        for i, u in enumerate(USERS)
    ]
    d.tables["curriculum_proposal_reviews"] = []
    return d


@pytest.fixture
def db():
    _seed_demand()
    d = _seed_db()
    from app.services import institution_service as inst
    from app.services import cohort_supply_service as coh
    from app.services import proposal_review_service as rev
    from app.services import outcome_feedback_service as out
    patches = [patch.object(m, "get_supabase_client", return_value=d)
               for m in (inst, coh, rev, out)]
    for p in patches:
        p.start()
    yield d
    for p in patches:
        p.stop()


def _flow(db):
    """Run the full ten-layer flow once; return every layer's output."""
    from app.services import course_alignment_service as al
    from app.services import cohort_supply_service as coh
    from app.services import district_training_service as dist
    from app.services import training_priority_service as prio
    from app.services import curriculum_proposal_service as prop
    from app.services import trainer_development_service as tdev
    from app.services import capacity_planning_service as cap
    from app.services import proposal_review_service as rev
    from app.services import outcome_feedback_service as out

    demand = lm.get_demand_signals(role=ROLE, city=CITY, include_raw_concepts=True)
    alignment = al.get_course_alignment("course-1", ROLE, country=COUNTRY,
                                        region=STATE, city=CITY)
    supply = coh.get_cohort_skill_supply("cohort-1")
    district = dist.get_district_training(**CTX)
    priorities = prio.get_training_priorities(**CTX)
    proposals = prop.get_curriculum_proposals(**CTX)
    docker_pid = next(p["proposal_id"] for p in proposals["proposals"]
                      if p["skill"]["id"] == "docker" and p["course_id"] == "course-1")
    trainers = tdev.get_trainer_development_signals(**CTX)
    capacity = cap.get_capacity_planning(**CTX)
    review = rev.create_review("reviewer-1", docker_pid, **CTX, decision="APPROVED")
    feedback = out.get_outcome_feedback(**CTX)
    fallback = dist.get_district_training(district=DISTRICT, role=ROLE,
                                           state=STATE, country=COUNTRY)
    tiny = dist.get_district_training(district=TINY_DISTRICT, role=ROLE,
                                      state=STATE, country=COUNTRY,
                                      city=CITY, region=STATE)
    return {"demand": demand, "alignment": alignment, "supply": supply,
            "district": district, "priorities": priorities,
            "proposals": proposals, "trainers": trainers,
            "capacity": capacity, "review": review, "feedback": feedback,
            "fallback": fallback, "tiny": tiny}


# ---------------------------------------------------------------------------
# 1–4. Identity + context preservation
# ---------------------------------------------------------------------------

def test_canonical_skill_survives_every_layer(db):
    f = _flow(db)
    assert {r["skill_slug"] for r in f["demand"] if r["skill_slug"]} >= {"docker", "kubernetes"}
    assert {r["skill"] for r in f["alignment"]["skills"]} >= {"docker", "kubernetes"}
    assert {r["skill"] for r in f["supply"]["skills"]} >= {"docker"}
    assert {r["skill"] for r in f["district"]["skills"]} >= {"docker", "kubernetes"}
    assert {r["skill"] for r in f["priorities"]["priorities"]} >= {"docker", "kubernetes"}
    assert {p["skill"]["id"] for p in f["proposals"]["proposals"]} >= {"docker", "kubernetes"}
    assert {s["skill"] for s in f["trainers"]["signals"]} >= {"docker", "kubernetes"}
    assert {r["skill"] for r in f["capacity"]["capacity"]} >= {"docker", "kubernetes"}
    assert f["review"]["skill_slug"] == "docker"
    assert {r["skill"] for r in f["feedback"]["skills"]} >= {"docker"}


def test_role_remains_canonical(db):
    f = _flow(db)
    assert roles.canonicalize_role_name(ROLE) == ROLE
    assert f["alignment"]["canonical_role"] == ROLE
    assert f["district"]["canonical_role"] == ROLE
    assert f["priorities"]["canonical_role"] == ROLE
    assert f["feedback"]["canonical_role"] == ROLE


def test_district_location_context_preserved(db):
    f = _flow(db)
    assert f["district"]["market_context"]["city"] == CITY
    assert f["district"]["market_context"]["match_type"] == "exact"
    assert f["priorities"]["market_context"]["city"] == CITY
    assert f["proposals"]["market_context"] is not None


def test_global_fallback_never_local(db):
    f = _flow(db)
    assert f["fallback"]["market_context"]["match_type"] == "fallback_global"
    assert "global fallback" in f["fallback"]["note"].lower()
    for row in f["fallback"]["skills"]:
        if row.get("market"):
            assert row["market"].get("provider_id") == "global_provider"


# ---------------------------------------------------------------------------
# 5–8. No recomputation; derivation from evidence
# ---------------------------------------------------------------------------

def test_p0_demand_not_recomputed(db):
    f = _flow(db)
    p0 = {r["skill_slug"]: r for r in f["demand"] if r["skill_slug"]}
    july = p0["docker"]
    assert july["period_start"] == "2026-07-01" and july["posting_count"] == 12
    for layer_rows, key in ((f["alignment"]["skills"], "industry"),
                            (f["priorities"]["priorities"], None)):
        for row in layer_rows:
            if row["skill"] != "docker":
                continue
            block = row if key is None else row.get(key)
            if key is None:
                block = row["evidence"]["market"]
            assert block["skill_share"] == july["skill_share"]
            assert block["posting_count"] == 12


def test_gap_math_not_recomputed(db):
    import inspect
    from app.services import training_priority_service as prio
    from app.services import curriculum_proposal_service as prop
    from app.services import district_training_service as dist
    from app.services import trainer_development_service as tdev
    from app.services import capacity_planning_service as cap
    for mod in (prio, prop, dist, tdev, cap):
        source = inspect.getsource(mod)
        assert "calculate_gaps" not in source
        assert "skill_gaps" not in source
    assert engine.gap(0.50, 0.75) == 0.25


def test_priority_derived_from_p0_evidence(db):
    f = _flow(db)
    docker = next(e for e in f["priorities"]["priorities"] if e["skill"] == "docker")
    assert docker["priority"] == "HIGH"
    assert any("0.58" in r for r in docker["reasons"])


def test_proposal_traces_to_evidence(db):
    f = _flow(db)
    docker = [p for p in f["proposals"]["proposals"]
              if p["skill"]["id"] == "docker" and p["course_id"] == "course-1"][0]
    assert docker["evidence"]["market"]["skill_share"] == pytest.approx(7 / 12, abs=1e-4)
    assert docker["priority"]["level"] == "HIGH"


# ---------------------------------------------------------------------------
# 9–12. Trainer, capacity, review, outcome honesty
# ---------------------------------------------------------------------------

def test_trainer_signals_observed_only(db):
    f = _flow(db)
    docker = next(s for s in f["trainers"]["signals"] if s["skill"] == "docker")
    assert docker["signal"] == "DEVELOPMENT_SIGNAL"
    assert docker["trainer_evidence"]["trainer_count"] == 0


def test_capacity_never_invented(db):
    f = _flow(db)
    assert all(r["capacity_status"] == "CAPACITY_DATA_INSUFFICIENT"
               for r in f["capacity"]["capacity"])
    assert "no validated capacity data" in f["capacity"]["planning_note"].lower()


def test_review_does_not_mutate_curriculum(db):
    f = _flow(db)
    assert f["review"]["to_status"] == "APPROVED"
    assert f["review"]["current_status"] == "APPROVED"
    assert len(db.tables["course_skills"]) == 3
    assert len(db.tables["curriculum_proposal_reviews"]) == 1


def test_outcome_feedback_does_not_mutate(db):
    f = _flow(db)
    docker = next(r for r in f["feedback"]["skills"] if r["skill"] == "docker")
    assert docker["signal"] == "SUPPORTIVE_SIGNAL"
    assert docker["sample"]["placement_count"] == 6
    assert len(db.tables["skill_assessments"]) == 0
    assert "caused" not in json.dumps(f["feedback"]).lower()


# ---------------------------------------------------------------------------
# 13–15. Provenance, privacy, unmapped exclusion
# ---------------------------------------------------------------------------

def test_provenance_throughout(db):
    f = _flow(db)
    assert f["alignment"]["provenance"]["engine_version"] == "course-alignment-v1"
    assert f["district"]["provenance"]["engine_version"] == "district-training-v1"
    assert f["priorities"]["provenance"]["engine_version"] == "training-priority-v1"
    assert f["proposals"]["provenance"]["engine_version"] == "curriculum-proposal-v1"
    assert f["trainers"]["provenance"]["engine_version"] == "trainer-development-signal-v1"
    assert f["capacity"]["provenance"]["engine_version"] == "capacity-planning-signal-v1"
    assert f["feedback"]["provenance"]["engine_version"] == "outcome-feedback-v1"


def test_privacy_suppression_preserved(db):
    f = _flow(db)
    assert f["tiny"]["suppressed"] is True and f["tiny"]["skills"] == []
    blob = json.dumps(f)
    for token in USERS + ["zx-1", "zx-2", "zx-3"]:
        assert token not in blob


def test_unmapped_never_in_canonical_calculations(db):
    f = _flow(db)
    for rows, key in ((f["alignment"]["skills"], None),
                      (f["district"]["skills"], None),
                      (f["priorities"]["priorities"], None),
                      (f["trainers"]["signals"], None),
                      (f["capacity"]["capacity"], None),
                      (f["feedback"]["skills"], None)):
        for row in rows:
            slug = row["skill"] if key is None else row.get(key, row)
            assert slug != "blockchain basics"
            assert "blockchain" not in str(slug).lower()
    assert {p["skill"]["id"] for p in f["proposals"]["proposals"]} <= {
        "docker", "kubernetes", "git", "sql"}
    assert f["supply"]["unmapped_concepts"]  # preserved separately, not dropped
