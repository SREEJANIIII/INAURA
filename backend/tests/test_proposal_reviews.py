"""P1.5: proposal review / approval workflow tests.

FakeDB pattern mirrors earlier phases; the reviews table starts empty.
Proposal ids resolve against the live P1.2 projection seeded below.
"""

import json
import pytest
from unittest.mock import patch
from fastapi import HTTPException
from pydantic import ValidationError
from pathlib import Path

from app.services import proposal_review_service as svc
from app.services import labour_market_service as lm
from app.schemas import proposal_reviews as schemas

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
}
USERS = [f"u-{i}" for i in range(1, 7)]
REVIEWER_1 = "reviewer-1"
REVIEWER_2 = "reviewer-2"
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
    ]
    d.tables["courses"] = [
        {"id": "course-1", "institution_id": "inst-1", "name": "Full Stack",
         "data_origin": "source_data", "delivery_mode": "hybrid", "status": "active"},
        {"id": "course-2", "institution_id": "inst-1", "name": "Backend Basics",
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
        _sig("v-1", "sql", "assessment", 0.80),
        _sig("v-2", "sql", "assessment", 0.80),
        _sig("v-3", "sql", "github", 0.60),
    ]
    d.tables["skill_assessments"] = []
    d.tables["trainers"] = [{"id": "t1", "institution_id": "inst-1", "name": "T1"}]
    d.tables["trainer_skills"] = [
        {"id": "ts-1", "trainer_id": "t1", "canonical_skill_slug": "docker"},
    ]
    d.tables["curriculum_proposal_reviews"] = []
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


def _proposal_ids(db):
    from app.services import curriculum_proposal_service as prop
    out = prop.get_curriculum_proposals(**CTX)
    assert len(out["proposals"]) > 0
    return [p["proposal_id"] for p in out["proposals"]]


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def test_create_review_approve(db):
    pid = _proposal_ids(db)[0]
    row = svc.create_review(REVIEWER_1, pid, **CTX, decision="APPROVED")
    assert row["reviewer_id"] == REVIEWER_1 and row["to_status"] == "APPROVED"
    assert row["from_status"] is None and row["current_status"] == "APPROVED"


def test_approve_reason_optional(db):
    pid = _proposal_ids(db)[0]
    row = svc.create_review(REVIEWER_1, pid, **CTX, decision="APPROVED")
    assert row["reason"] is None
    # ...but an optional reason is preserved when given.
    pid2 = _proposal_ids(db)[1]
    row2 = svc.create_review(REVIEWER_1, pid2, **CTX, decision="APPROVED",
                             reason="Matches our hiring plan.")
    assert row2["reason"] == "Matches our hiring plan."


def test_reject(db):
    pid = _proposal_ids(db)[0]
    row = svc.create_review(REVIEWER_1, pid, **CTX, decision="REJECTED",
                            reason="Out of scope this year.")
    assert row["to_status"] == "REJECTED" and row["reason"] == "Out of scope this year."


def test_defer(db):
    pid = _proposal_ids(db)[0]
    row = svc.create_review(REVIEWER_1, pid, **CTX, decision="DEFERRED",
                            reason="Awaiting lab budget.")
    assert row["to_status"] == "DEFERRED"
    st = svc.get_proposal_status(pid, **CTX)
    assert st["current_status"] == "DEFERRED" and st["decisions"] == 1


def test_missing_rejection_reason(db):
    pid = _proposal_ids(db)[0]
    with pytest.raises(HTTPException) as exc:
        svc.create_review(REVIEWER_1, pid, **CTX, decision="REJECTED")
    assert exc.value.status_code == 400


def test_missing_defer_reason(db):
    pid = _proposal_ids(db)[0]
    with pytest.raises(HTTPException) as exc:
        svc.create_review(REVIEWER_1, pid, **CTX, decision="DEFERRED", reason="  ")
    assert exc.value.status_code == 400


def test_invalid_decision(db):
    pid = _proposal_ids(db)[0]
    with pytest.raises(HTTPException) as exc:
        svc.create_review(REVIEWER_1, pid, **CTX, decision="IMPLEMENTED")
    assert exc.value.status_code == 400
    with pytest.raises(ValidationError):
        schemas.ReviewCreate(proposal_id=pid, district=DISTRICT, role=ROLE,
                             decision="MAYBE")


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

def test_invalid_transitions_from_terminal(db):
    pid = _proposal_ids(db)[0]
    svc.create_review(REVIEWER_1, pid, **CTX, decision="APPROVED")
    for nxt in ("APPROVED", "REJECTED", "DEFERRED"):
        with pytest.raises(HTTPException) as exc:
            svc.create_review(REVIEWER_2, pid, **CTX, decision=nxt,
                              reason="Second thoughts.")
        assert exc.value.status_code == 400
    pid2 = _proposal_ids(db)[1]
    svc.create_review(REVIEWER_1, pid2, **CTX, decision="REJECTED", reason="No.")
    with pytest.raises(HTTPException) as exc:
        svc.create_review(REVIEWER_1, pid2, **CTX, decision="APPROVED")
    assert exc.value.status_code == 400


def test_deferred_allows_rereview(db):
    pid = _proposal_ids(db)[0]
    svc.create_review(REVIEWER_1, pid, **CTX, decision="DEFERRED", reason="Later.")
    row = svc.create_review(REVIEWER_2, pid, **CTX, decision="APPROVED")
    assert row["from_status"] == "DEFERRED" and row["to_status"] == "APPROVED"
    st = svc.get_proposal_status(pid, **CTX)
    assert st["current_status"] == "APPROVED" and st["decisions"] == 2


def test_concurrent_review_handling(db):
    # Two reviewers decide the same pending proposal: first appends, second
    # is rejected by the transition guard; both attempts stay visible.
    pid = _proposal_ids(db)[0]
    svc.create_review(REVIEWER_1, pid, **CTX, decision="APPROVED")
    with pytest.raises(HTTPException):
        svc.create_review(REVIEWER_2, pid, **CTX, decision="REJECTED", reason="Race.")
    st = svc.get_proposal_status(pid, **CTX)
    assert st["current_status"] == "APPROVED" and len(st["history"]) == 1


def test_duplicate_review_same_reviewer(db):
    pid = _proposal_ids(db)[0]
    svc.create_review(REVIEWER_1, pid, **CTX, decision="DEFERRED", reason="Soon.")
    # Same reviewer re-deferring appends history; latest still wins.
    svc.create_review(REVIEWER_1, pid, **CTX, decision="DEFERRED", reason="Still soon.")
    st = svc.get_proposal_status(pid, **CTX)
    assert st["decisions"] == 2 and st["history"][-1]["reason"] == "Still soon."


# ---------------------------------------------------------------------------
# Validity + auth + history
# ---------------------------------------------------------------------------

def test_proposal_not_found(db):
    with pytest.raises(HTTPException) as exc:
        svc.create_review(REVIEWER_1, "prop-does-not-exist", **CTX, decision="APPROVED")
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        svc.get_proposal_status("prop-does-not-exist", **CTX)
    assert exc.value.status_code == 404


def test_authorization_reviewer_recorded(db):
    pid = _proposal_ids(db)[0]
    svc.create_review(REVIEWER_1, pid, **CTX, decision="APPROVED")
    rows = svc.list_reviews(proposal_id=pid)
    assert [r["reviewer_id"] for r in rows] == [REVIEWER_1]
    with pytest.raises(HTTPException) as exc:
        svc.create_review("", pid, **CTX, decision="APPROVED")
    assert exc.value.status_code == 401


def test_reviewer_identity_not_spoofable(db):
    # The create schema carries no reviewer field: identity always comes from
    # the authenticated caller, never the request body.
    assert "reviewer_id" not in schemas.ReviewCreate.model_fields
    assert "reviewer" not in schemas.ReviewCreate.model_fields


def test_audit_history(db):
    pid = _proposal_ids(db)[0]
    svc.create_review(REVIEWER_1, pid, **CTX, decision="DEFERRED", reason="Q3.")
    svc.create_review(REVIEWER_2, pid, **CTX, decision="REJECTED", reason="Cut.")
    st = svc.get_proposal_status(pid, **CTX)
    assert [h["to_status"] for h in st["history"]] == ["DEFERRED", "REJECTED"]
    assert [h["reviewer_id"] for h in st["history"]] == [REVIEWER_1, REVIEWER_2]
    assert all(h["created_at"] for h in st["history"])
    assert st["history"][0]["from_status"] is None
    assert st["history"][1]["from_status"] == "DEFERRED"


def test_pending_default_status(db):
    pid = _proposal_ids(db)[0]
    st = svc.get_proposal_status(pid, **CTX)
    assert st["current_status"] == "PENDING_REVIEW"
    assert st["decisions"] == 0 and st["history"] == []


def test_list_filters(db):
    pids = _proposal_ids(db)
    svc.create_review(REVIEWER_1, pids[0], **CTX, decision="APPROVED")
    svc.create_review(REVIEWER_1, pids[1], **CTX, decision="REJECTED", reason="No.")
    assert len(svc.list_reviews(decision="APPROVED")) == 1
    assert len(svc.list_reviews(district=DISTRICT)) == 2
    assert len(svc.list_reviews(proposal_id=pids[0])) == 1
    assert svc.list_reviews(decision="DEFERRED") == []
    with pytest.raises(HTTPException) as exc:
        svc.list_reviews(decision="MAYBE")
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Safety: no mutation, no implementation, RLS
# ---------------------------------------------------------------------------

def test_no_curriculum_mutation(db):
    before = json.dumps({k: v for k, v in db.tables.items()
                         if k != "curriculum_proposal_reviews"},
                        sort_keys=True, default=str)
    pid = _proposal_ids(db)[0]
    svc.create_review(REVIEWER_1, pid, **CTX, decision="APPROVED")
    after = json.dumps({k: v for k, v in db.tables.items()
                        if k != "curriculum_proposal_reviews"},
                       sort_keys=True, default=str)
    assert before == after


def test_no_automatic_implementation(db):
    pid = _proposal_ids(db)[0]
    svc.create_review(REVIEWER_1, pid, **CTX, decision="APPROVED")
    st = svc.get_proposal_status(pid, **CTX)
    assert st["current_status"] == "APPROVED"
    # Approval records a decision; curriculum rows are byte-identical.
    assert all(row["mapping_status"] == "mapped" for row in db.tables["course_skills"])
    assert "IMPLEMENTED" not in svc.TRANSITIONS
    for targets in svc.TRANSITIONS.values():
        assert "IMPLEMENTED" not in targets


def test_rls_migration_text():
    text = (Path(__file__).resolve().parents[1] / "supabase" /
            "033_curriculum_proposal_reviews.sql").read_text()
    # Strip SQL comments: assertions target executable statements, while the
    # header legitimately documents that curriculum tables are untouched.
    code = "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("--"))
    lower = code.lower()
    assert "enable row level security" in lower
    assert "reviewer_id = auth.uid()" in lower
    assert "revoke all" in lower
    for line in code.splitlines():
        s = line.strip().lower()
        if s.startswith("grant ") and " to " in s:
            assert "anon" not in s.split(" to ", 1)[1], f"anon grant: {line}"
    # Append-only for authenticated writers: no update/delete policies.
    assert "for update" not in lower and "for delete" not in lower
    # Approval must not touch curriculum tables: no DDL/DML referencing them.
    assert "course_skills" not in lower and "course_modules" not in lower
    # Non-recursive: no cross-table subqueries in policies.
    in_policy = False
    for line in code.splitlines():
        s = line.strip().lower()
        if s.startswith("create policy"):
            in_policy = True
        elif in_policy and (s.startswith("revoke all") or s.startswith("grant ")
                            or s.startswith("comment ")):
            in_policy = False
        if in_policy:
            assert "exists (select" not in s and " join " not in s


def test_api_auth_and_validation():
    from app.main import app
    from app.core.security import get_current_user
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/v1/industry/curriculum-reviews" in paths
    assert "/api/v1/industry/curriculum-reviews/{proposal_id}" in paths
    for r in app.routes:
        if hasattr(r, "path") and str(r.path).startswith("/api/v1/industry/curriculum-reviews"):
            assert get_current_user in [d.call for d in r.dependant.dependencies], r.path
    with pytest.raises(ValidationError):
        schemas.ReviewCreate(proposal_id="x", district="d", role="r",
                             decision="APPROVED", reason="x" * 2001)


def test_schema_validation(db):
    from app.schemas.proposal_reviews import ReviewResponse, ProposalStatusResponse
    pid = _proposal_ids(db)[0]
    row = svc.create_review(REVIEWER_1, pid, **CTX, decision="APPROVED")
    assert ReviewResponse.model_validate(row).to_status == "APPROVED"
    st = svc.get_proposal_status(pid, **CTX)
    assert ProposalStatusResponse.model_validate(st).current_status == "APPROVED"


# ---------------------------------------------------------------------------
# Compatibility + gap math
# ---------------------------------------------------------------------------

def test_p1_1_p1_2_compatibility():
    from app.services import training_priority_service as prio
    from app.services import curriculum_proposal_service as prop
    assert prio.ENGINE_VERSION == "training-priority-v1"
    assert prop.ENGINE_VERSION == "curriculum-proposal-v1"


def test_p0_compat_and_gap_math():
    assert lm.calculate_demand(100, 45) == {"skill_share": 0.45, "demand": 0.45}
    from app.services import skill_engine as engine
    assert engine.gap(0.50, 0.75) == 0.25
    assert engine.gap(0.85, 0.75) == 0.0
