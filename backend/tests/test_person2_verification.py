"""Person 2 live-logic verification with an in-memory PostgREST fake.

Simulates two students + one employer member + one outsider against the REAL
service code (no Supabase needed). Verifies: employer isolation, student
isolation, transition authorization, event append-only behavior, feedback
isolation, placement authorization, qualification grounding ownership,
dashboard denominators/rates, Person 1 PII-free contract, and RLS SQL text
(no anon grants).
"""

import re
import pytest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException

from app.services import outcome_service as out
from app.services import employer_service as emp

STUDENT_A = "student-A"
STUDENT_B = "student-B"
MEMBER = "member-1"
OUTSIDER = "outsider-1"
EMP = "emp-1"
REQ = "req-1"
SKILL = "11111111-1111-1111-1111-111111111111"


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
        self.db.deleted_from.append(self.table)
        return self

    def upsert(self, payload, on_conflict=None):
        self.op = "upsert"
        self.payload = payload
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals)))
        return self

    def order(self, col):
        return self

    def _apply(self, rows):
        for kind, col, val in self.filters:
            if kind == "eq":
                rows = [r for r in rows if str(r.get(col)) == str(val)]
            else:
                rows = [r for r in rows if str(r.get(col)) in {str(v) for v in val}]
        return rows

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "select":
            return Result(self._apply(rows))
        if self.op in ("insert", "upsert"):
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            for it in items:
                it.setdefault("id", f"{self.table}-{len(rows) + 1}")
                rows.append(dict(it))
            return Result(items if isinstance(self.payload, list) else items)
        if self.op == "update":
            matched = self._apply(rows)
            for r in matched:
                r.update(self.payload)
            return Result(matched)
        if self.op == "delete":
            kept = [r for r in rows if r not in self._apply(rows)]
            self.db.tables[self.table] = kept
            return Result([])
        raise AssertionError("unknown op")


class FakeDB:
    def __init__(self):
        self.tables: dict[str, list] = {}
        self.deleted_from: list[str] = []

    def table(self, name):
        return FakeQuery(self, name)


@pytest.fixture
def db():
    d = FakeDB()
    d.tables["employer_members"] = [
        {"id": "m1", "employer_id": EMP, "user_id": MEMBER, "role": "member"},
    ]
    d.tables["employers"] = [
        {"id": EMP, "name": "Acme", "contact_email": "hr@acme.test",
         "created_by": MEMBER, "status": "active"},
    ]
    d.tables["hiring_requirements"] = [
        {"id": REQ, "employer_id": EMP, "title": "Backend Intern", "status": "open"},
    ]
    d.tables["skills"] = [{"id": SKILL}]
    d.tables["applications"] = [
        {"id": "app-A", "student_id": STUDENT_A, "hiring_requirement_id": REQ,
         "status": "interview", "outcome": "pending", "applied_at": "2026-07-01T00:00:00+00:00"},
    ]
    d.tables["application_events"] = []
    d.tables["employer_feedback"] = []
    d.tables["employer_skill_feedback"] = []
    d.tables["placement_outcomes"] = []
    d.tables["evidence"] = [{"id": "ev-A", "user_id": STUDENT_A}]
    d.tables["certifications"] = []
    d.tables["qualification_alignments"] = []
    d.tables["hiring_requirement_skills"] = []
    patches = [
        patch.object(out, "get_supabase_client", return_value=d),
        patch.object(emp, "get_supabase_client", return_value=d),
    ]
    for p in patches:
        p.start()
    yield d
    for p in patches:
        p.stop()


# --- Employer isolation ---

def test_outsider_cannot_read_employer(db):
    with pytest.raises(HTTPException) as e:
        emp.get_employer(OUTSIDER, EMP)
    assert e.value.status_code == 404


def test_member_sees_employer_but_non_owner_loses_contact_email(db):
    row = emp.get_employer(MEMBER, EMP)
    assert row["name"] == "Acme"
    assert "contact_email" not in row


def test_outsider_cannot_list_employer_applications(db):
    with pytest.raises(HTTPException) as e:
        out.list_applications_for_employer(OUTSIDER, EMP)
    assert e.value.status_code == 404


def test_member_can_list_employer_applications(db):
    rows = out.list_applications_for_employer(MEMBER, EMP)
    assert len(rows) == 1 and rows[0]["employer_id"] == EMP


# --- Student isolation ---

def test_student_b_cannot_read_student_a_application(db):
    with pytest.raises(HTTPException) as e:
        out.get_application_detail(STUDENT_B, "app-A")
    assert e.value.status_code == 404


def test_student_a_reads_own_application_with_derived_employer(db):
    detail = out.get_application_detail(STUDENT_A, "app-A")
    assert detail["employer_id"] == EMP  # derived via join, not stored
    assert detail["events"] == []


# --- Transition authorization end-to-end ---

def test_student_cannot_advance_to_screening(db):
    with pytest.raises(HTTPException) as e:
        out.transition_status("app-A", STUDENT_A, "offer_received")
    # interview->offer_received is employer-controlled
    assert e.value.status_code == 403


def test_employer_member_advances_and_event_appended(db):
    row = out.transition_status("app-A", MEMBER, "offer_received", note="good round")
    assert row["status"] == "offer_received"
    assert row["outcome"] == "pending"
    assert len(db.tables["application_events"]) == 1
    ev = db.tables["application_events"][0]
    assert (ev["from_status"], ev["to_status"], ev["actor"]) == ("interview", "offer_received", MEMBER)
    assert "application_events" not in [t for t in db.deleted_from]
    assert db.tables["applications"][0]["applied_at"] == "2026-07-01T00:00:00+00:00"


def test_student_withdraws_from_offer_with_declined_outcome(db):
    db.tables["applications"][0]["status"] = "offer_received"
    row = out.transition_status("app-A", STUDENT_A, "withdrawn")
    assert row["status"] == "withdrawn" and row["outcome"] == "declined_offer"


# --- Feedback isolation ---

def test_feedback_flow_member_submits_student_reads_stranger_blocked(db):
    fb = out.submit_feedback(MEMBER, "app-A", {
        "overall_rating": 4, "overall_comment": "Strong basics",
        "skills": [{"skill_id": SKILL, "expected_level": 0.7, "observed_level": 0.5}],
    })
    assert fb["skills"][0]["skill_gap"] == pytest.approx(0.2)
    seen = out.get_feedback(STUDENT_A, "app-A")
    assert seen["overall_rating"] == 4
    with pytest.raises(HTTPException) as e:
        out.get_feedback(STUDENT_B, "app-A")
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e2:
        out.submit_feedback(MEMBER, "app-A", {"overall_rating": 5, "skills": []})
    assert e2.value.status_code == 400  # one summative record enforced


# --- Placement authorization ---

def test_placement_student_creates_stranger_cannot_update_member_confirms(db):
    pl = out.create_placement(STUDENT_A, {"employer_id": EMP, "application_id": "app-A",
                                          "role_title": "Backend Intern", "status": "joined"})
    assert pl["outcome_source"] == "student_reported" and pl["verification_status"] == "unverified"
    with pytest.raises(HTTPException) as e:
        out.update_placement(STUDENT_B, pl["id"], {"role_title": "Hacker"})
    assert e.value.status_code == 404
    confirmed = out.confirm_placement(MEMBER, pl["id"])
    assert confirmed["verification_status"] == "verified"
    assert confirmed["outcome_source"] == "employer_confirmed"
    with pytest.raises(HTTPException) as e2:
        out.confirm_placement(OUTSIDER, pl["id"])
    assert e2.value.status_code == 404


# --- Qualification grounding ownership ---

def test_alignment_rejects_other_users_evidence(db):
    with pytest.raises(HTTPException) as e:
        out.create_alignment(MEMBER, {"hiring_requirement_id": REQ,
                                      "course_name": "DBMS", "evidence_id": "ev-A"})
    assert e.value.status_code == 403  # ev-A belongs to STUDENT_A


def test_alignment_generic_mapping_without_grounding_ok(db):
    row = out.create_alignment(MEMBER, {"hiring_requirement_id": REQ, "course_name": "DBMS"})
    assert row["course_name"] == "DBMS" and row["evidence_id"] is None


# --- Dashboard denominators/rates on real code ---

def test_dashboard_rates_and_denominators(db):
    db.tables["applications"].extend([
        {"id": "a2", "student_id": STUDENT_A, "hiring_requirement_id": REQ,
         "status": "selected", "outcome": "selected", "applied_at": "2026-07-02T00:00:00+00:00"},
        {"id": "a3", "student_id": STUDENT_A, "hiring_requirement_id": REQ,
         "status": "saved", "outcome": None, "applied_at": None},
    ])
    db.tables["placement_outcomes"].append(
        {"id": "p1", "student_id": STUDENT_A, "employer_id": EMP, "application_id": "a2",
         "role_title": "Backend Intern", "status": "joined"})
    d = out.get_dashboard(STUDENT_A)
    assert d["denominators"] == {"applied_n": 2, "selected_n": 1}
    assert d["rates"]["interview_rate"] == pytest.approx(1.0)  # interview + selected both reached interview+
    assert d["rates"]["offer_rate"] == pytest.approx(0.5)  # selected reached offer-or-beyond
    assert d["rates"]["selection_rate"] == pytest.approx(0.5)
    assert d["rates"]["joining_rate_selection_base"] == pytest.approx(1.0)
    assert d["rates"]["joining_rate_application_base"] == pytest.approx(0.5)
    assert d["unlinked_placements_n"] == 0


# --- Person 1 contract shape ---

def test_industry_signal_pii_free_and_suppressed_on_small_n(db):
    sig = out.get_industry_signals(role=None, location=None)
    assert set(sig) == {"signal_version", "role", "location", "skill", "time_window",
                        "denominators", "application_count", "interview_count",
                        "selection_count", "placement_count", "feedback_count",
                        "observed_demand", "observed_skill_gap", "min_n_met"}
    assert sig["min_n_met"] is False
    assert sig["observed_skill_gap"] is None and sig["observed_demand"] is None


# --- RLS SQL text: no anon grants anywhere in Person 2 migrations ---

def test_migrations_grant_no_anon():
    base = Path(__file__).resolve().parents[1] / "supabase"
    for name in ("026_employers.sql", "027_outcomes.sql"):
        text = (base / name).read_text()
        assert "revoke all" in text.lower()
        for line in text.splitlines():
            s = line.strip().lower()
            if s.startswith("grant ") and " to " in s:
                targets = s.split(" to ", 1)[1]
                assert "anon" not in targets, f"{name}: anon grant found: {line}"
        assert "enable row level security" in text.lower()
