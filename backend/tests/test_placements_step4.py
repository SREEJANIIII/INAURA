"""Person 2 Step 4: Placement Outcomes + Joining Tracking Unit & Security Tests.

Verifies:
1. Student can view own placement
2. Student cannot view another student's placement
3. Employer can access own placement
4. Employer cannot access another employer's placement
5. Linked application derives employer correctly
6. Linked application cannot use conflicting employer
7. Linked application student mismatch is rejected
8. Unlinked placement requires valid employer
9. Joined status requires joined_at
10. Invalid placement transition rejected
11. Unauthorized transition rejected
12. Application -> joining denominator is correct
13. Selection -> joining denominator is correct
14. Saved-only applications excluded
15. Unlinked placements are counted separately
16. Existing application funnel metrics do not regress
17. RLS remains non-recursive
18. Existing Step 1/2/3 behavior does not regress
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
    ]
    d.tables["applications"] = [
        {
            "id": "app-a1-selected",
            "student_id": STUDENT_A,
            "hiring_requirement_id": REQ_A1,
            "status": "selected",
            "outcome": "selected",
            "applied_at": "2026-07-01T00:00:00+00:00",
        },
        {
            "id": "app-a2-interview",
            "student_id": STUDENT_A,
            "hiring_requirement_id": REQ_A1,
            "status": "interview",
            "outcome": "pending",
            "applied_at": "2026-07-02T00:00:00+00:00",
        },
        {
            "id": "app-b1-selected",
            "student_id": STUDENT_B,
            "hiring_requirement_id": REQ_B1,
            "status": "selected",
            "outcome": "selected",
            "applied_at": "2026-07-03T00:00:00+00:00",
        },
        {
            "id": "app-saved-only",
            "student_id": STUDENT_A,
            "hiring_requirement_id": REQ_A1,
            "status": "saved",
            "outcome": None,
            "applied_at": None,
        },
    ]
    d.tables["application_events"] = []
    d.tables["employer_feedback"] = []
    d.tables["employer_skill_feedback"] = []
    d.tables["placement_outcomes"] = []
    d.tables["evidence"] = []
    d.tables["certifications"] = []
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


def test_01_student_can_view_own_placement(fdb):
    pl = svc.create_placement(STUDENT_A, {
        "application_id": "app-a1-selected",
        "role_title": "Junior Python Dev",
        "status": "offer_accepted",
    })
    assert pl["student_id"] == STUDENT_A
    assert pl["employer_id"] == EMP_A
    assert pl["employer_name"] == "Corp A"
    assert pl["requirement_title"] == "Backend Python Engineer"

    rows = svc.list_placements(STUDENT_A)
    assert len(rows) == 1
    assert rows[0]["id"] == pl["id"]
    assert rows[0]["role_title"] == "Junior Python Dev"

    detail = svc.get_placement_detail(STUDENT_A, pl["id"])
    assert detail["id"] == pl["id"]
    assert detail["employer_name"] == "Corp A"


def test_02_student_cannot_view_another_students_placement(fdb):
    pl_a = svc.create_placement(STUDENT_A, {
        "application_id": "app-a1-selected",
        "role_title": "Backend Dev",
        "status": "selected",
    })
    # Student B lists placements -> does not see Student A's placement
    rows_b = svc.list_placements(STUDENT_B)
    assert len(rows_b) == 0

    # Student B tries to fetch Student A's placement detail -> 404
    with pytest.raises(HTTPException) as exc:
        svc.get_placement_detail(STUDENT_B, pl_a["id"])
    assert exc.value.status_code == 404

    # Student B tries to update Student A's placement -> 404
    with pytest.raises(HTTPException) as exc_up:
        svc.update_placement(STUDENT_B, pl_a["id"], {"role_title": "Hijacked Role"})
    assert exc_up.value.status_code == 404


def test_03_employer_can_access_own_placement(fdb):
    pl = svc.create_placement(STUDENT_A, {
        "application_id": "app-a1-selected",
        "role_title": "Backend Dev",
        "status": "selected",
    })
    # Member A can view placements for Corp A
    emp_rows = svc.list_placements_for_employer(MEMBER_A, EMP_A)
    assert len(emp_rows) == 1
    assert emp_rows[0]["id"] == pl["id"]

    # Member A can confirm placement
    confirmed = svc.confirm_placement(MEMBER_A, pl["id"], verified=True)
    assert confirmed["verification_status"] == "verified"
    assert confirmed["outcome_source"] == "employer_confirmed"


def test_04_employer_cannot_access_another_employers_placement(fdb):
    pl_a = svc.create_placement(STUDENT_A, {
        "application_id": "app-a1-selected",
        "role_title": "Backend Dev",
        "status": "selected",
    })
    # Member B tries to list placements for EMP_A -> 404 (access denied)
    with pytest.raises(HTTPException) as exc1:
        svc.list_placements_for_employer(MEMBER_B, EMP_A)
    assert exc1.value.status_code == 404

    # Member B tries to confirm EMP_A's placement -> 404
    with pytest.raises(HTTPException) as exc2:
        svc.confirm_placement(MEMBER_B, pl_a["id"])
    assert exc2.value.status_code == 404

    # Member B tries to update EMP_A's placement -> 404
    with pytest.raises(HTTPException) as exc3:
        svc.update_placement(MEMBER_B, pl_a["id"], {"status": "not_joined"})
    assert exc3.value.status_code == 404


def test_05_linked_application_derives_employer_correctly(fdb):
    # Omit employer_id entirely; it must be derived from the application requirement
    pl = svc.create_placement(STUDENT_A, {
        "application_id": "app-a1-selected",
        "role_title": "Software Engineer",
        "status": "selected",
    })
    assert pl["employer_id"] == EMP_A
    assert pl["application_id"] == "app-a1-selected"


def test_06_linked_application_cannot_use_conflicting_employer(fdb):
    # Pass conflicting employer_id EMP_B for application that belongs to EMP_A
    with pytest.raises(HTTPException) as exc:
        svc.create_placement(STUDENT_A, {
            "application_id": "app-a1-selected",
            "employer_id": EMP_B,
            "role_title": "Software Engineer",
            "status": "selected",
        })
    assert exc.value.status_code == 400
    assert "employer_id does not match" in exc.value.detail.lower()


def test_07_linked_application_student_mismatch_is_rejected(fdb):
    # STUDENT_B tries to create placement linked to STUDENT_A's application
    with pytest.raises(HTTPException) as exc:
        svc.create_placement(STUDENT_B, {
            "application_id": "app-a1-selected",
            "role_title": "Software Engineer",
            "status": "selected",
        })
    assert exc.value.status_code == 400
    assert "different student" in exc.value.detail.lower()


def test_08_unlinked_placement_requires_valid_employer(fdb):
    # Missing employer_id for unlinked placement -> 400
    with pytest.raises(HTTPException) as exc1:
        svc.create_placement(STUDENT_A, {
            "role_title": "Freelance Dev",
            "status": "selected",
        })
    assert exc1.value.status_code == 400
    assert "employer_id is required" in exc1.value.detail.lower()

    # Non-existent employer_id -> 400
    with pytest.raises(HTTPException) as exc2:
        svc.create_placement(STUDENT_A, {
            "employer_id": "emp-nonexistent-999",
            "role_title": "Freelance Dev",
            "status": "selected",
        })
    assert exc2.value.status_code == 400
    assert "does not exist" in exc2.value.detail.lower()

    # Valid unlinked placement
    pl = svc.create_placement(STUDENT_A, {
        "employer_id": EMP_A,
        "role_title": "Direct Hire Dev",
        "status": "selected",
    })
    assert pl["application_id"] is None
    assert pl["employer_id"] == EMP_A


def test_09_joined_status_requires_joined_at(fdb):
    # 1. create_placement with status joined and joining_date=None -> 400
    with pytest.raises(HTTPException) as exc1:
        svc.create_placement(STUDENT_A, {
            "employer_id": EMP_A,
            "role_title": "Dev",
            "status": "joined",
            "joining_date": None,
        })
    assert exc1.value.status_code == 400
    assert "joining_date is required" in exc1.value.detail.lower()

    # 2. create_placement with valid joining_date -> succeeds
    pl = svc.create_placement(STUDENT_A, {
        "employer_id": EMP_A,
        "role_title": "Dev",
        "status": "selected",
    })

    # 3. update_placement to joined without joining_date -> 400
    with pytest.raises(HTTPException) as exc2:
        svc.update_placement(STUDENT_A, pl["id"], {"status": "joined"})
    assert exc2.value.status_code == 400
    assert "joining_date is required" in exc2.value.detail.lower()

    # 4. update_placement to joined with joining_date -> succeeds
    updated = svc.update_placement(STUDENT_A, pl["id"], {
        "status": "joined",
        "joining_date": "2026-08-15",
    })
    assert updated["status"] == "joined"
    assert updated["joining_date"] == "2026-08-15"


def test_10_invalid_placement_transition_rejected(fdb):
    pl = svc.create_placement(STUDENT_A, {
        "employer_id": EMP_A,
        "role_title": "Dev",
        "status": "selected",
    })
    # Terminal transition to joined
    svc.update_placement(STUDENT_A, pl["id"], {"status": "joined", "joining_date": "2026-08-15"})

    # Attempt transition from terminal state 'joined' to 'selected' -> 400
    with pytest.raises(HTTPException) as exc1:
        svc.update_placement(STUDENT_A, pl["id"], {"status": "selected"})
    assert exc1.value.status_code == 400
    assert "terminal" in exc1.value.detail.lower()

    # Create another in 'selected' and attempt invalid transition to 'screening' -> 400
    pl2 = svc.create_placement(STUDENT_A, {
        "employer_id": EMP_A,
        "role_title": "Dev",
        "status": "selected",
    })
    with pytest.raises(HTTPException) as exc2:
        svc.update_placement(STUDENT_A, pl2["id"], {"status": "screening"})
    assert exc2.value.status_code == 400
    assert "invalid placement transition" in exc2.value.detail.lower()


def test_11_unauthorized_transition_rejected(fdb):
    pl = svc.create_placement(STUDENT_A, {
        "employer_id": EMP_A,
        "role_title": "Dev",
        "status": "selected",
    })
    # Student attempts employer-controlled transition 'selected' -> 'not_joined' -> 403
    with pytest.raises(HTTPException) as exc1:
        svc.update_placement(STUDENT_A, pl["id"], {"status": "not_joined"})
    assert exc1.value.status_code == 403
    assert "employer-controlled" in exc1.value.detail.lower()

    # Employer attempts student-controlled transition 'selected' -> 'declined' -> 403
    with pytest.raises(HTTPException) as exc2:
        svc.update_placement(MEMBER_A, pl["id"], {"status": "declined"})
    assert exc2.value.status_code == 403
    assert "student-controlled" in exc2.value.detail.lower()

    # Student attempts self-verification -> 403
    with pytest.raises(HTTPException) as exc3:
        svc.update_placement(STUDENT_A, pl["id"], {"verification_status": "verified"})
    assert exc3.value.status_code == 403


def test_12_application_to_joining_denominator_is_correct(fdb):
    # Setup applications:
    # app-a1-selected (applied_at present)
    # app-a2-interview (applied_at present)
    # app-saved-only (applied_at is None -> excluded)
    # 1 linked joined placement
    svc.create_placement(STUDENT_A, {
        "application_id": "app-a1-selected",
        "role_title": "Dev",
        "status": "joined",
        "joining_date": "2026-08-01",
    })

    dash = svc.get_dashboard(STUDENT_A)
    # Applied count: 2 (app-a1-selected and app-a2-interview)
    assert dash["denominators"]["applied_n"] == 2
    assert dash["applied_count"] == 2
    # Linked joined count: 1
    assert dash["joined_count"] == 1
    # application_to_joining_rate = 1 / 2 = 0.5
    assert dash["rates"]["application_to_joining_rate"] == pytest.approx(0.5)


def test_13_selection_to_joining_denominator_is_correct(fdb):
    # app-a1-selected has status='selected'
    # app-a2-interview has status='interview'
    # 1 linked joined placement
    svc.create_placement(STUDENT_A, {
        "application_id": "app-a1-selected",
        "role_title": "Dev",
        "status": "joined",
        "joining_date": "2026-08-01",
    })

    dash = svc.get_dashboard(STUDENT_A)
    # selected_count: 1
    assert dash["denominators"]["selected_n"] == 1
    assert dash["selected_count"] == 1
    # selection_to_joining_rate = 1 / 1 = 1.0
    assert dash["rates"]["selection_to_joining_rate"] == pytest.approx(1.0)


def test_14_saved_only_applications_excluded(fdb):
    dash_before = svc.get_dashboard(STUDENT_A)
    # app-saved-only exists in fdb fixture with status='saved', applied_at=None
    # Denominator applied_n must be 2, NOT 3
    assert dash_before["denominators"]["applied_n"] == 2
    assert dash_before["funnel"]["saved"] == 0  # not in scoped applied applications


def test_15_unlinked_placements_are_counted_separately(fdb):
    # Create 1 linked joined placement and 1 unlinked joined placement
    svc.create_placement(STUDENT_A, {
        "application_id": "app-a1-selected",
        "role_title": "Linked Dev",
        "status": "joined",
        "joining_date": "2026-08-01",
    })
    svc.create_placement(STUDENT_A, {
        "employer_id": EMP_A,
        "role_title": "Unlinked Dev",
        "status": "joined",
        "joining_date": "2026-08-01",
    })

    dash = svc.get_dashboard(STUDENT_A)
    # unlinked_placements_n / unlinked_placement_count = 1
    assert dash["unlinked_placements_n"] == 1
    assert dash["unlinked_placement_count"] == 1

    # linked joined placements should only be 1 (unlinked is excluded from funnel numerator)
    assert dash["joined_count"] == 1
    assert dash["rates"]["selection_to_joining_rate"] == pytest.approx(1.0)


def test_16_existing_application_funnel_metrics_do_not_regress(fdb):
    dash = svc.get_dashboard(STUDENT_A)
    # Check that standard funnel keys exist and are non-negative
    for k in ("saved", "applied", "screening", "interview", "offer_received", "selected", "rejected", "withdrawn"):
        assert k in dash["funnel"]
    for r in ("interview_rate", "offer_rate", "selection_rate", "joining_rate_selection_base", "joining_rate_application_base"):
        assert r in dash["rates"]
    assert "applied_n" in dash["denominators"]
    assert "selected_n" in dash["denominators"]
    assert "top_required_skills" in dash
    assert "top_observed_gaps" in dash
    assert "window" in dash


def test_17_rls_remains_non_recursive():
    # Verify migration 028 security definer functions and placement policy
    m28_path = Path("backend/supabase/028_person2_rls_recursion_fix.sql")
    assert m28_path.exists()
    content = m28_path.read_text(encoding="utf-8")
    assert "create or replace function public.employer_role_of" in content
    assert "create policy \"Students manage own placements\"" in content
    assert "create policy \"Employer members view placements\"" in content
    assert "public.employer_role_of(employer_id) is not null" in content


def test_18_existing_step1_2_3_behavior_does_not_regress(fdb):
    # Step 1: Employer membership check
    mem = emp.get_membership(MEMBER_A, EMP_A)
    assert mem["role"] == "member"

    # Step 2: Application transitions
    trans = svc.transition_status("app-a2-interview", MEMBER_A, "offer_received", note="Good interview")
    assert trans["status"] == "offer_received"

    # Step 3: Employer feedback submission
    fb = svc.submit_feedback(MEMBER_A, "app-a2-interview", {
        "overall_rating": 5,
        "overall_comment": "Top candidate",
        "skills": [{"skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": 0.9}],
    })
    assert fb["status"] == "submitted"
    assert fb["overall_rating"] == 5
    assert len(fb["skills"]) == 1
