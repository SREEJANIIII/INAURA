"""Person 2 Step 3: Employer Feedback & Skill Feedback Unit & Security Tests.

Verifies:
1. Employer can submit feedback for its own application.
2. Employer cannot submit feedback for another employer's application.
3. Student cannot create employer feedback.
4. Student cannot modify employer feedback.
5. Duplicate final feedback is rejected.
6. Employer skill feedback is tied to the correct application.
7. Canonical skills are validated.
8. Invalid/unrelated skills are rejected where the existing schema requires requirement linkage.
9. Expected proficiency validation works.
10. Observed proficiency validation works.
11. Cross-employer skill feedback access is blocked.
12. Feedback ownership is enforced.
13. Qualification alignment can reference student's own evidence.
14. Qualification alignment can reference student's own certification.
15. Qualification alignment cannot reference both.
16. User cannot cite another student's evidence/certification.
17. RLS remains non-recursive.
18. Feedback requires interview interaction first.
"""

import pytest
from unittest.mock import patch
from fastapi import HTTPException
from pathlib import Path

from app.services import outcome_service as svc
from app.services import employer_service as emp

STUDENT_A = "student-aaa-1111"
STUDENT_B = "student-bbb-2222"
OUTSIDER = "outsider-999-9999"

MEMBER_A = "member-corp-a"
MEMBER_B = "member-corp-b"

EMP_A = "emp-aaaa-1111"
EMP_B = "emp-bbbb-2222"

REQ_A1 = "req-aaaa-0001"
REQ_B1 = "req-bbbb-0001"

SKILL_PY = "00000000-0000-0000-0000-000000000001"
SKILL_SQL = "00000000-0000-0000-0000-000000000002"
SKILL_RUST = "00000000-0000-0000-0000-000000000003"
NONEXISTENT_SKILL = "00000000-0000-0000-0000-000000000099"


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

    def eq(self, field, value):
        self.filters.append((field, "eq", str(value)))
        return self

    def in_(self, field, values):
        self.filters.append((field, "in", [str(v) for v in values]))
        return self

    def order(self, field, desc=False):
        return self

    def _matches(self, row):
        for f, op, val in self.filters:
            row_val = str(row.get(f)) if row.get(f) is not None else None
            if op == "eq":
                if row_val != str(val):
                    return False
            elif op == "in":
                if row_val not in val:
                    return False
        return True

    def execute(self):
        rows = self.db.tables.get(self.table, [])
        if self.op == "select":
            matched = [r for r in rows if self._matches(r)]
            return Result(matched)
        if self.op == "insert":
            new_rows = self.payload if isinstance(self.payload, list) else [self.payload]
            inserted = []
            for idx, r in enumerate(new_rows):
                item = dict(r)
                if "id" not in item:
                    item["id"] = f"{self.table}-{len(rows) + idx + 1}"
                rows.append(item)
                inserted.append(item)
            return Result(inserted)
        if self.op == "update":
            updated = []
            for r in rows:
                if self._matches(r):
                    r.update(self.payload)
                    updated.append(r)
            return Result(updated)
        if self.op == "delete":
            self.db.tables[self.table] = [r for r in rows if not self._matches(r)]
            return Result([])
        return Result([])


class FakeDB:
    def __init__(self):
        self.tables: dict[str, list] = {}

    def table(self, name):
        return FakeQuery(self, name)


@pytest.fixture
def fdb():
    d = FakeDB()
    d.tables["employers"] = [
        {"id": EMP_A, "name": "Corp A", "status": "active", "created_by": MEMBER_A},
        {"id": EMP_B, "name": "Corp B", "status": "active", "created_by": MEMBER_B},
    ]
    d.tables["employer_members"] = [
        {"id": "m-a", "employer_id": EMP_A, "user_id": MEMBER_A, "role": "member"},
        {"id": "m-b", "employer_id": EMP_B, "user_id": MEMBER_B, "role": "member"},
    ]
    d.tables["hiring_requirements"] = [
        {"id": REQ_A1, "employer_id": EMP_A, "title": "Backend Python Engineer", "status": "open"},
        {"id": REQ_B1, "employer_id": EMP_B, "title": "Frontend React Dev", "status": "open"},
    ]
    d.tables["hiring_requirement_skills"] = [
        {"id": "hrs-1", "hiring_requirement_id": REQ_A1, "skill_id": SKILL_PY, "importance": "required"},
        {"id": "hrs-2", "hiring_requirement_id": REQ_A1, "skill_id": SKILL_SQL, "importance": "preferred"},
    ]
    d.tables["skills"] = [
        {"id": SKILL_PY, "canonical_name": "python", "display_name": "Python"},
        {"id": SKILL_SQL, "canonical_name": "sql", "display_name": "SQL"},
        {"id": SKILL_RUST, "canonical_name": "rust", "display_name": "Rust"},
    ]
    d.tables["applications"] = [
        {
            "id": "app-a1-interview",
            "student_id": STUDENT_A,
            "hiring_requirement_id": REQ_A1,
            "status": "interview",
            "outcome": "pending",
            "applied_at": "2026-07-01T00:00:00+00:00",
        },
        {
            "id": "app-a2-screening",
            "student_id": STUDENT_A,
            "hiring_requirement_id": REQ_A1,
            "status": "screening",
            "outcome": "pending",
            "applied_at": "2026-07-01T00:00:00+00:00",
        },
        {
            "id": "app-b1-interview",
            "student_id": STUDENT_B,
            "hiring_requirement_id": REQ_B1,
            "status": "interview",
            "outcome": "pending",
            "applied_at": "2026-07-01T00:00:00+00:00",
        },
    ]
    d.tables["application_events"] = []
    d.tables["employer_feedback"] = []
    d.tables["employer_skill_feedback"] = []
    d.tables["evidence"] = [
        {"id": "ev-A", "user_id": STUDENT_A},
        {"id": "ev-M", "user_id": MEMBER_A},
    ]
    d.tables["certifications"] = [
        {"id": "cert-A", "user_id": STUDENT_A},
        {"id": "cert-M", "user_id": MEMBER_A},
    ]
    d.tables["qualification_alignments"] = []

    patches = [
        patch.object(svc, "get_supabase_client", return_value=d),
        patch.object(emp, "get_supabase_client", return_value=d),
    ]
    for p in patches:
        p.start()
    yield d
    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# Tests 1-18
# ---------------------------------------------------------------------------

def test_01_employer_can_submit_feedback_for_own_application(fdb):
    payload = {
        "technical_ability": 4,
        "communication": 5,
        "overall_rating": 4,
        "interview_summary": "Strong problem solver",
        "overall_comment": "Excellent culture fit",
        "skills": [
            {"skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": 0.7, "comment": "Great Python foundations"},
        ],
    }
    fb = svc.submit_feedback(MEMBER_A, "app-a1-interview", payload)
    assert fb["overall_rating"] == 4
    assert fb["employer_id"] == EMP_A
    assert fb["student_id"] == STUDENT_A
    assert len(fb["skills"]) == 1
    assert fb["skills"][0]["skill_gap"] == pytest.approx(0.1)
    assert fb["skills"][0]["skill_name"] == "Python"
    assert len(fdb.tables["employer_feedback"]) == 1


def test_02_employer_cannot_submit_feedback_for_another_employer_application(fdb):
    payload = {"overall_rating": 4, "skills": []}
    # MEMBER_B belongs to EMP_B, attempting to submit on app-a1-interview (EMP_A)
    with pytest.raises(HTTPException) as exc:
        svc.submit_feedback(MEMBER_B, "app-a1-interview", payload)
    assert exc.value.status_code in (403, 404)


def test_03_student_cannot_create_employer_feedback(fdb):
    payload = {"overall_rating": 5, "skills": []}
    # STUDENT_A attempts to submit feedback on own application
    with pytest.raises(HTTPException) as exc:
        svc.submit_feedback(STUDENT_A, "app-a1-interview", payload)
    assert exc.value.status_code in (403, 404)


def test_04_student_cannot_modify_employer_feedback():
    # Feedback is immutable by design — no update/delete methods exist
    assert not hasattr(svc, "update_feedback")
    assert not hasattr(svc, "delete_feedback")
    assert not hasattr(svc, "update_skill_feedback")
    assert not hasattr(svc, "delete_skill_feedback")


def test_05_duplicate_final_feedback_is_rejected(fdb):
    payload = {"overall_rating": 4, "skills": []}
    svc.submit_feedback(MEMBER_A, "app-a1-interview", payload)
    # Second submission on same application must fail
    with pytest.raises(HTTPException) as exc:
        svc.submit_feedback(MEMBER_A, "app-a1-interview", payload)
    assert exc.value.status_code == 400
    assert "already submitted" in exc.value.detail.lower()


def test_06_employer_skill_feedback_tied_to_correct_application(fdb):
    payload = {
        "overall_rating": 4,
        "skills": [
            {"skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": 0.6},
        ],
    }
    fb = svc.submit_feedback(MEMBER_A, "app-a1-interview", payload)
    skill_rows = fdb.tables["employer_skill_feedback"]
    assert len(skill_rows) == 1
    assert skill_rows[0]["employer_feedback_id"] == fb["id"]
    assert skill_rows[0]["skill_id"] == SKILL_PY


def test_07_canonical_skills_are_validated(fdb):
    payload = {
        "overall_rating": 4,
        "skills": [
            {"skill_id": NONEXISTENT_SKILL, "expected_level": 0.5, "observed_level": 0.5},
        ],
    }
    with pytest.raises(HTTPException) as exc:
        svc.submit_feedback(MEMBER_A, "app-a1-interview", payload)
    assert exc.value.status_code == 400
    assert "unknown skill_id" in exc.value.detail.lower()


def test_08_invalid_unrelated_skills_are_rejected_where_requirement_linkage_required(fdb):
    # REQ_A1 has SKILL_PY and SKILL_SQL attached in hiring_requirement_skills.
    # SKILL_RUST exists in canonical skills, but is unrelated to REQ_A1.
    payload = {
        "overall_rating": 4,
        "skills": [
            {"skill_id": SKILL_RUST, "expected_level": 0.7, "observed_level": 0.5},
        ],
    }
    with pytest.raises(HTTPException) as exc:
        svc.submit_feedback(MEMBER_A, "app-a1-interview", payload)
    assert exc.value.status_code == 400
    assert "not linked" in exc.value.detail.lower()


def test_09_expected_proficiency_validation_works(fdb):
    payload_high = {
        "overall_rating": 4,
        "skills": [{"skill_id": SKILL_PY, "expected_level": 1.5, "observed_level": 0.5}],
    }
    with pytest.raises(HTTPException) as exc1:
        svc.submit_feedback(MEMBER_A, "app-a1-interview", payload_high)
    assert exc1.value.status_code == 400
    assert "expected_level" in exc1.value.detail.lower()

    payload_low = {
        "overall_rating": 4,
        "skills": [{"skill_id": SKILL_PY, "expected_level": -0.2, "observed_level": 0.5}],
    }
    with pytest.raises(HTTPException) as exc2:
        svc.submit_feedback(MEMBER_A, "app-a1-interview", payload_low)
    assert exc2.value.status_code == 400


def test_10_observed_proficiency_validation_works(fdb):
    payload_high = {
        "overall_rating": 4,
        "skills": [{"skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": 2.0}],
    }
    with pytest.raises(HTTPException) as exc1:
        svc.submit_feedback(MEMBER_A, "app-a1-interview", payload_high)
    assert exc1.value.status_code == 400
    assert "observed_level" in exc1.value.detail.lower()

    payload_low = {
        "overall_rating": 4,
        "skills": [{"skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": -0.1}],
    }
    with pytest.raises(HTTPException) as exc2:
        svc.submit_feedback(MEMBER_A, "app-a1-interview", payload_low)
    assert exc2.value.status_code == 400


def test_11_cross_employer_skill_feedback_access_is_blocked(fdb):
    # MEMBER_A submits feedback on app-a1-interview
    svc.submit_feedback(MEMBER_A, "app-a1-interview", {
        "overall_rating": 4,
        "skills": [{"skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": 0.7}],
    })
    # MEMBER_B (Corp B) attempts to read feedback for app-a1-interview (Corp A)
    with pytest.raises(HTTPException) as exc:
        svc.get_feedback(MEMBER_B, "app-a1-interview")
    assert exc.value.status_code in (403, 404)


def test_12_feedback_ownership_is_enforced(fdb):
    svc.submit_feedback(MEMBER_A, "app-a1-interview", {
        "overall_rating": 4,
        "overall_comment": "Great interview",
        "skills": [{"skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": 0.7}],
    })
    # Student A (the applicant) can read own feedback
    fb_student = svc.get_feedback(STUDENT_A, "app-a1-interview")
    assert fb_student["overall_rating"] == 4
    assert fb_student["skills"][0]["skill_name"] == "Python"

    # Member A (the employer) can read feedback
    fb_employer = svc.get_feedback(MEMBER_A, "app-a1-interview")
    assert fb_employer["overall_rating"] == 4

    # Student B (unrelated student) cannot read feedback
    with pytest.raises(HTTPException) as exc:
        svc.get_feedback(STUDENT_B, "app-a1-interview")
    assert exc.value.status_code == 404


def test_13_qualification_alignment_can_reference_students_own_evidence(fdb):
    # MEMBER_A can ground in own evidence
    row = svc.create_alignment(MEMBER_A, {
        "hiring_requirement_id": REQ_A1,
        "course_name": "CS 101",
        "evidence_id": "ev-M",
    })
    assert row["course_name"] == "CS 101"
    assert row["evidence_id"] == "ev-M"


def test_14_qualification_alignment_can_reference_students_own_certification(fdb):
    # MEMBER_A can ground in own certification
    row = svc.create_alignment(MEMBER_A, {
        "hiring_requirement_id": REQ_A1,
        "course_name": "AWS Architecture",
        "certification_id": "cert-M",
    })
    assert row["course_name"] == "AWS Architecture"
    assert row["certification_id"] == "cert-M"


def test_15_qualification_alignment_cannot_reference_both(fdb):
    with pytest.raises(HTTPException) as exc:
        svc.create_alignment(MEMBER_A, {
            "hiring_requirement_id": REQ_A1,
            "course_name": "Invalid Alignment",
            "evidence_id": "ev-M",
            "certification_id": "cert-M",
        })
    assert exc.value.status_code == 400
    assert "at most one" in exc.value.detail.lower()


def test_16_user_cannot_cite_another_students_evidence_or_certification(fdb):
    # MEMBER_A attempts to cite STUDENT_A's evidence
    with pytest.raises(HTTPException) as exc1:
        svc.create_alignment(MEMBER_A, {
            "hiring_requirement_id": REQ_A1,
            "course_name": "Cheating Ev",
            "evidence_id": "ev-A",
        })
    assert exc1.value.status_code == 403

    # MEMBER_A attempts to cite STUDENT_A's certification
    with pytest.raises(HTTPException) as exc2:
        svc.create_alignment(MEMBER_A, {
            "hiring_requirement_id": REQ_A1,
            "course_name": "Cheating Cert",
            "certification_id": "cert-A",
        })
    assert exc2.value.status_code == 403


def test_17_rls_remains_non_recursive():
    # Verify migration 028 has the SECURITY DEFINER functions and policies
    m28_path = Path("backend/supabase/028_person2_rls_recursion_fix.sql")
    assert m28_path.exists()
    content = m28_path.read_text(encoding="utf-8")
    assert "create or replace function public.employer_role_of" in content
    assert "create or replace function public.feedback_employer_role" in content
    assert "security definer" in content
    assert "Employer members manage feedback" in content
    assert "Read skill feedback via parent" in content


def test_18_feedback_requires_interview_interaction_first(fdb):
    # app-a2-screening is in 'screening' status, not interview or beyond
    with pytest.raises(HTTPException) as exc:
        svc.submit_feedback(MEMBER_A, "app-a2-screening", {"overall_rating": 4, "skills": []})
    assert exc.value.status_code == 400
    assert "interview interaction" in exc.value.detail.lower()
