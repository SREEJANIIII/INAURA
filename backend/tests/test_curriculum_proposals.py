"""P1.2: curriculum change proposal tests.

Fixtures: deterministic P0 #1 demand (memory store) + FakeDB district
(institutions/courses/modules/cohorts/signals/trainers) patched into
institution_service and cohort_supply_service, which the proposal engine
composes without modification — and, critically, without mutation.
"""

import json
import re
import pytest
from unittest.mock import patch
from fastapi import HTTPException
from pathlib import Path

from app.services import curriculum_proposal_service as svc
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
    plan = {
        "2026-06": {"Docker": 3, "Kubernetes": 8, "Git": 6, "Redis": 5, "SQL": 7, "Java": 10},
        "2026-07": {"Docker": 7, "Kubernetes": 9, "Git": 6, "Redis": 5, "SQL": 7, "Java": 4},
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
        {"id": "course-2", "institution_id": "inst-1", "name": "Backend Basics",
         "data_origin": "source_data", "delivery_mode": "offline", "status": "active"},
    ]
    d.tables["course_modules"] = [
        {"id": "m-docker", "course_id": "course-1", "name": "Containers", "sequence": 1},
        {"id": "m-git", "course_id": "course-1", "name": "Version Control", "sequence": 2},
        {"id": "m-redis", "course_id": "course-1", "name": "Caching Basics", "sequence": 3},
        {"id": "m-java", "course_id": "course-1", "name": "JVM Basics", "sequence": 4},
        {"id": "m-sql", "course_id": "course-2", "name": "Databases", "sequence": 1},
    ]

    def _cs(cid, slug, module, coverage, mapped=True):
        return {"id": f"cs-{cid}-{slug}", "course_id": cid, "module_id": module,
                "skill_id": SKILLS.get(slug),
                "canonical_skill_slug": slug if mapped else None,
                "source_concept": slug if mapped else "Blockchain Basics",
                "mapping_status": "mapped" if mapped else "unmapped",
                "coverage": coverage, "importance": None}

    d.tables["course_skills"] = [
        _cs("course-1", "docker", "m-docker", "intermediate"),
        _cs("course-1", "git", "m-git", "intermediate"),
        _cs("course-1", "redis", "m-redis", "introductory"),
        _cs("course-1", "java", "m-java", "intermediate"),
        _cs("course-1", "blockchain", None, None, mapped=False),
        _cs("course-2", "sql", "m-sql", "intermediate"),
        _cs("course-2", "typescript", None, "introductory"),
    ]
    d.tables["cohorts"] = [
        {"id": "cohort-1", "institution_id": "inst-1", "course_id": "course-1",
         "name": "Batch A", "status": "active", "data_origin": "source_data"},
        {"id": "cohort-2", "institution_id": "inst-1", "course_id": "course-2",
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
        _sig(USERS[0], "redis", "github", 0.60),
        _sig(USERS[0], "java", "assessment", 0.80),
        _sig(USERS[1], "java", "assessment", 0.80),
        _sig("v-1", "sql", "assessment", 0.80),
        _sig("v-2", "sql", "assessment", 0.80),
        _sig("v-3", "sql", "github", 0.60),
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


def _proposals(db, **kw):
    params = {"district": DISTRICT, "role": ROLE, "state": STATE,
              "country": COUNTRY, "city": CITY, "region": STATE}
    params.update(kw)
    return svc.get_curriculum_proposals(**params)


def _one(proposals, course_id, skill):
    return next(p for p in proposals["proposals"]
                if p["course_id"] == course_id and p["skill"]["id"] == skill)


# ---------------------------------------------------------------------------
# 1–5. Action-type rules
# ---------------------------------------------------------------------------

def test_add_skill_when_curriculum_missing(db):
    p = _one(_proposals(db), "course-1", "kubernetes")
    assert p["action"]["type"] == "ADD_SKILL"
    assert p["current_state"]["curriculum_status"] == "missing"
    assert any("absent" in r.lower() for r in p["rationale"])


def test_increase_coverage_when_taught_but_weak(db):
    p = _one(_proposals(db), "course-1", "redis")
    assert p["action"]["type"] == "INCREASE_COVERAGE"
    assert p["current_state"]["coverage"] == "introductory"


def test_add_practical_assessment_when_covered_but_weak(db):
    p = _one(_proposals(db), "course-1", "docker")
    assert p["action"]["type"] == "ADD_PRACTICAL_ASSESSMENT"
    assert p["current_state"]["coverage"] == "intermediate"
    assert p["current_state"]["learner_attainment"] == "weak"


def test_update_module_only_with_module_evidence(db):
    p = _one(_proposals(db), "course-1", "java")
    assert p["action"]["type"] == "UPDATE_MODULE"
    assert p["proposed_change"]["module_ids"] == ["m-java"]
    assert p["proposed_change"]["module_names"] == ["JVM Basics"]


def test_review_content_fallback(db):
    p = _one(_proposals(db), "course-2", "sql")
    assert p["action"]["type"] == "REVIEW_CONTENT"
    assert p["current_state"]["learner_attainment"] == "moderate"


def test_declining_without_module_falls_back_to_review():
    row = {"skill": "java", "display_name": "Java",
           "industry": {"trend": "declining", "skill_share": 0.33,
                        "provider_id": "test_provider", "period": {},
                        "evidence_suppressed": False},
           "curriculum": {"taught": True},
           "cohort": {"verified_coverage": 0.3},
           "alignment": {"curriculum_status": "covered",
                         "attainment_status": "moderate",
                         "demand_status": "declining",
                         "overall_status": "weak_supply"}}
    prio = {"priority": "MEDIUM", "status": "actionable_gap", "reasons": [],
            "evidence": {}}
    out = svc.build_proposal(
        {"id": "c1", "name": "C1"}, {"id": "i1", "name": "I1"},
        DISTRICT, ROLE, row, prio, [], "exact")
    assert out["action"]["type"] == "REVIEW_CONTENT"
    assert out["proposed_change"]["module_ids"] == []


# ---------------------------------------------------------------------------
# 6–10. No-proposal cases
# ---------------------------------------------------------------------------

def test_no_proposal_for_insufficient_evidence(db):
    out = _proposals(db)
    assert "typescript" not in {p["skill"]["id"] for p in out["proposals"]}


def test_no_proposal_for_low_priority(db):
    out = _proposals(db)
    # Covered + strong + stable in course-1 stays informational (no proposal),
    # while the same skill missing in course-2 is a genuine medium gap.
    assert not [p for p in out["proposals"]
                if p["skill"]["id"] == "git" and p["course_id"] == "course-1"]
    git_c2 = _one(out, "course-2", "git")
    assert git_c2["action"]["type"] == "ADD_SKILL"
    assert git_c2["priority"]["level"] == "MEDIUM"


def test_high_priority_propagation(db):
    out = _proposals(db)
    assert {"docker", "kubernetes"} <= {p["skill"]["id"] for p in out["proposals"]
                                        if p["priority"]["level"] == "HIGH"}


def test_medium_priority_propagation(db):
    out = _proposals(db)
    assert {"redis", "sql", "java"} <= {p["skill"]["id"] for p in out["proposals"]
                                        if p["priority"]["level"] == "MEDIUM"}


def test_aligned_skill_creates_no_proposal(db):
    out = _proposals(db)
    assert not [p for p in out["proposals"]
                if p["skill"]["id"] == "git" and p["course_id"] == "course-1"]


# ---------------------------------------------------------------------------
# 11–13. Deterministic titles + rationale + traceability
# ---------------------------------------------------------------------------

def test_deterministic_title_generation(db):
    out = _proposals(db)
    assert _one(out, "course-1", "kubernetes")["title"] == "Add Kubernetes to the curriculum"
    assert _one(out, "course-1", "docker")["title"] == "Add practical assessment coverage for Docker"
    assert _one(out, "course-1", "redis")["title"] == "Increase Redis curriculum coverage"
    assert _one(out, "course-1", "java")["title"] == "Review Java module content"
    assert _one(out, "course-2", "sql")["title"] == "Review SQL curriculum coverage"
    assert _one(_proposals(db), "course-1", "kubernetes")["title"] == \
        _one(out, "course-1", "kubernetes")["title"]


def test_deterministic_rationale_generation(db):
    first = _one(_proposals(db), "course-1", "docker")["rationale"]
    second = _one(_proposals(db), "course-1", "docker")["rationale"]
    assert first == second and len(first) >= 3
    assert first[-1] == "Proposed for human review."


def test_rationale_traceability(db):
    out = _proposals(db)
    docker = _one(out, "course-1", "docker")
    share = docker["evidence"]["market"]["skill_share"]
    assert any(f"{share:.1%}" in r or f"{share:.2f}" in r for r in docker["rationale"])
    assert any("17%" in r for r in docker["rationale"])  # 1/6 verified learner coverage
    k8s = _one(out, "course-1", "kubernetes")
    assert k8s["evidence"]["curriculum"]["courses_teaching"] == 0
    assert any("absent" in r.lower() for r in k8s["rationale"])
    for p in out["proposals"]:
        for forbidden in ("will improve placements", "employers strongly prefer",
                          "should definitely be changed", "obsolete"):
            assert forbidden not in " ".join(p["rationale"]).lower()


# ---------------------------------------------------------------------------
# 14–17. Evidence, provenance, fallback, location
# ---------------------------------------------------------------------------

def test_evidence_packet_preservation(db):
    docker = _one(_proposals(db), "course-1", "docker")
    ev = docker["evidence"]
    assert ev["market"]["trend"] == "rising"
    assert ev["market"]["posting_count"] == 12
    assert ev["learner_supply"]["verified_learner_count"] >= 1
    assert ev["trainer"]["trainer_count"] == 1
    assert "priority_confidence" not in json.dumps(ev).lower()
    assert "proposal_confidence" not in json.dumps(docker).lower()


def test_provenance_preservation(db):
    out = _proposals(db)
    assert out["provenance"]["engine_version"] == "curriculum-proposal-v1"
    assert out["provenance"]["priority_engine_version"] == "training-priority-v1"
    assert out["provenance"]["computed_at"]
    for p in out["proposals"]:
        assert p["provenance"]["engine_version"] == "curriculum-proposal-v1"
        assert "does not modify curriculum data" in p["provenance"]["note"]


def test_global_fallback_labeling(db):
    out = _proposals(db, city=None, region=None)
    assert out["market_context"]["match_type"] == "fallback_global"
    for p in out["proposals"]:
        assert p["market_context"]["match_type"] == "fallback_global"
    assert any("global fallback" in r.lower()
               for p in out["proposals"] for r in p["rationale"])


def test_exact_location_semantics(db):
    out = _proposals(db)
    assert out["market_context"].get("city") == CITY
    assert all("global fallback" not in r.lower()
               for p in out["proposals"] for r in p["rationale"])


# ---------------------------------------------------------------------------
# 18–20. Roles, courses, modules
# ---------------------------------------------------------------------------

def test_role_normalization(db):
    full = _proposals(db, role=ROLE)
    alias = _proposals(db, role="swe")
    assert {p["proposal_id"] for p in alias["proposals"]} == \
        {p["proposal_id"] for p in full["proposals"]}


def test_unmapped_role_behavior(db):
    out = svc.get_curriculum_proposals(district=DISTRICT, role="Quantum Wizard")
    assert out["role_mapping_status"] == "unmapped" and out["proposals"] == []


def test_multiple_courses(db):
    out = _proposals(db)
    k8s = [p for p in out["proposals"] if p["skill"]["id"] == "kubernetes"]
    assert len(k8s) == 2
    assert {p["course_id"] for p in k8s} == {"course-1", "course-2"}
    assert k8s[0]["proposal_id"] != k8s[1]["proposal_id"]
    assert k8s[0]["institution_id"] == k8s[1]["institution_id"] == "inst-1"


def test_module_mapping_present(db):
    docker = _one(_proposals(db), "course-1", "docker")
    assert docker["proposed_change"]["target"] == "course"
    java = _one(_proposals(db), "course-1", "java")
    assert java["proposed_change"]["target"] == "module"


def test_module_mapping_absent(db):
    sql = _one(_proposals(db), "course-2", "sql")
    assert sql["proposed_change"]["module_ids"] == ["m-sql"]
    # ADD_SKILL targets the course itself, never an invented module
    k8s = _one(_proposals(db), "course-1", "kubernetes")
    assert k8s["proposed_change"] == {
        "action_type": "ADD_SKILL", "skill": "kubernetes", "target": "course",
        "module_ids": [], "module_names": [],
    }


def test_no_invented_module(db):
    blob = json.dumps(_proposals(db)).lower()
    assert "docker fundamentals" not in blob
    for p in _proposals(db)["proposals"]:
        if p["action"]["type"] == "UPDATE_MODULE":
            assert len(p["proposed_change"]["module_ids"]) >= 1


# ---------------------------------------------------------------------------
# 24–26. No invented specifics / recommendations
# ---------------------------------------------------------------------------

def test_no_invented_hours(db):
    blob = json.dumps(_proposals(db)).lower()
    assert "hour" not in blob and "session" not in blob
    for p in _proposals(db)["proposals"]:
        assert set(p["proposed_change"]) == {
            "action_type", "skill", "target", "module_ids", "module_names"}


def test_no_invented_seats(db):
    blob = json.dumps(_proposals(db)).lower()
    assert not re.search(r"add \d+ seats?", blob)
    assert "seat" not in blob


def test_no_trainer_recommendations(db):
    blob = json.dumps(_proposals(db)).lower()
    for phrase in ("should hire", "hire a trainer", "assign a trainer",
                   "recruit", "train the trainer"):
        assert phrase not in blob


# ---------------------------------------------------------------------------
# 27–30. No mutation, no LLM, privacy
# ---------------------------------------------------------------------------

def test_no_automatic_curriculum_mutation(db):
    before = json.dumps(db.tables, sort_keys=True, default=str)
    _proposals(db)
    svc.get_curriculum_proposals(district=DISTRICT, role=ROLE, state=STATE,
                                 country=COUNTRY, course_id="course-1")
    assert json.dumps(db.tables, sort_keys=True, default=str) == before


def test_no_llm_invocation():
    text = Path(__file__).resolve().parents[1] / "app" / "services" / \
        "curriculum_proposal_service.py"
    lowered = text.read_text().lower()
    for token in ("gemini", "groq", "openai", "anthropic", "chatcompletion",
                  "generate_content", "llm_client", "import llm"):
        assert token not in lowered


def test_privacy_suppression(db):
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
    out = svc.get_curriculum_proposals(district="Tiny District", role=ROLE,
                                       state=STATE, country=COUNTRY)
    assert out["proposals"] == []


def test_no_user_ids_in_serialized_output(db):
    blob = json.dumps(_proposals(db))
    for u in USERS:
        assert u not in blob
    for v in ("v-1", "v-2", "v-3"):
        assert v not in blob


# ---------------------------------------------------------------------------
# 31–35. Schema, API, status
# ---------------------------------------------------------------------------

def test_schema_validation(db):
    from app.schemas.curriculum_proposals import CurriculumProposalsResponse
    parsed = CurriculumProposalsResponse.model_validate(_proposals(db))
    assert parsed.summary.total == len(parsed.proposals) > 0
    assert all(p.action.status == "PENDING_REVIEW" for p in parsed.proposals)


def test_api_routes_registered_and_guarded():
    from app.main import app
    from app.core.security import get_current_user
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/v1/industry/curriculum-proposals" in paths
    assert "/api/v1/industry/curriculum-proposals/{proposal_id}" in paths
    for r in app.routes:
        if hasattr(r, "path") and str(r.path).startswith("/api/v1/industry/curriculum-proposals"):
            assert get_current_user in [d.call for d in r.dependant.dependencies], r.path


def test_api_filtering(db):
    base = {"district": DISTRICT, "role": ROLE, "state": STATE,
            "country": COUNTRY, "city": CITY, "region": STATE}
    assert len(svc.get_curriculum_proposals(**base, action_type="ADD_SKILL")["proposals"]) == 7
    assert len(svc.get_curriculum_proposals(**base, priority="HIGH")["proposals"]) == 4
    assert len(svc.get_curriculum_proposals(**base, course_id="course-1")["proposals"]) == 5
    assert len(svc.get_curriculum_proposals(**base, skill="docker")["proposals"]) == 2
    assert len(svc.get_curriculum_proposals(**base, status="PENDING_REVIEW")["proposals"]) == 11
    for bad in ({"action_type": "DELETE_COURSE"}, {"priority": "URGENT"},
                {"status": "APPROVED"}):
        with pytest.raises(HTTPException) as exc:
            svc.get_curriculum_proposals(**base, **bad)
        assert exc.value.status_code == 400


def test_status_defaults_to_pending_review(db):
    out = _proposals(db)
    assert {p["action"]["status"] for p in out["proposals"]} == {"PENDING_REVIEW"}


def test_proposal_does_not_imply_approval(db):
    blob = json.dumps(_proposals(db)).lower()
    assert "approved" not in blob and "implemented" not in blob


def test_proposal_detail_lookup(db):
    out = _proposals(db)
    pid = _one(out, "course-1", "docker")["proposal_id"]
    base = {"district": DISTRICT, "role": ROLE, "state": STATE,
            "country": COUNTRY, "city": CITY, "region": STATE}
    one = svc.get_curriculum_proposal(pid, **base)
    assert one["proposal_id"] == pid and one["market_context"]
    with pytest.raises(HTTPException) as exc:
        svc.get_curriculum_proposal("prop-missing", **base)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 36–42. Compatibility + gap math
# ---------------------------------------------------------------------------

def test_p0_1_compatibility():
    assert lm.calculate_demand(100, 45) == {"skill_share": 0.45, "demand": 0.45}
    assert lm.DemoPostingProvider().is_live is False


def test_p0_2_compatibility():
    from app.services import institution_service as inst
    assert inst.resolve_skill("React.js")["canonical_skill_slug"] == "react"
    assert [c["code"] for c in inst.build_demo_seed()["courses"]] == ["DEMO-FSWD", "DEMO-MAD", "DEMO-DA"]


def test_p0_3_compatibility():
    from app.services import cohort_supply_service as coh
    assert coh.MIN_ACTIVE_MEMBERS_FOR_SKILL_DETAIL == 5
    assert coh.build_demo_seed()["cohort"]["code"] == "DEMO-FSWD-2026A"


def test_p0_4_compatibility():
    from app.services import course_alignment_service as al
    assert al.ENGINE_VERSION == "course-alignment-v1"
    assert al._overall_status("missing", "weak", True) == "curriculum_gap"


def test_p0_5_compatibility():
    from app.services import district_training_service as dist
    assert dist.ENGINE_VERSION == "district-training-v1"


def test_p1_1_priority_consistency(db):
    from app.services import training_priority_service as prio
    assert prio.ENGINE_VERSION == "training-priority-v1"
    base = {"district": DISTRICT, "role": ROLE, "state": STATE,
            "country": COUNTRY, "city": CITY, "region": STATE}
    pmap = {e["skill"]: e["priority"] for e in prio.get_training_priorities(**base)["priorities"]}
    assert pmap["docker"] == "HIGH" and pmap["typescript"] == "INSUFFICIENT_EVIDENCE"
    docker = _one(_proposals(db), "course-1", "docker")
    assert docker["priority"]["level"] == pmap["docker"]
    assert docker["priority"]["status"] == "actionable_gap"


def test_gap_mathematics_unchanged():
    from app.services import skill_engine as engine
    assert engine.gap(0.50, 0.75) == 0.25
    assert engine.gap(0.85, 0.75) == 0.0
