"""Person 2 Step 2: Applications & Application Events Unit & Security Tests.

Verifies:
1. Student can create/save an application.
2. Student can apply.
3. Student can withdraw when valid.
4. Duplicate application protection.
5. Student can only see their own applications.
6. Employer can only see applications for its own requirements.
7. Employer A cannot access Employer B applications.
8. Wrong actor receives 403.
9. Invalid state transition receives 400.
10. Terminal states reject further transitions.
11. Every valid transition creates an event.
12. Application events are immutable/append-only.
13. Application timeline is correctly ordered.
14. Requirement ownership is enforced.
15. Unauthorized access does not leak application information.
"""

import pytest
from unittest.mock import patch
from fastapi import HTTPException

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
REQ_A_CLOSED = "req-aaaa-closed"
REQ_B1 = "req-bbbb-0001"


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
        self.db.deleted_from.append(self.table)
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals)))
        return self

    def order(self, col, desc=False):
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
        raise AssertionError(f"unknown op: {self.op}")


class FakeDB:
    def __init__(self):
        self.tables: dict[str, list] = {}
        self.deleted_from: list[str] = []

    def table(self, name):
        return FakeQuery(self, name)


@pytest.fixture
def db():
    d = FakeDB()
    d.tables["employers"] = [
        {"id": EMP_A, "name": "Company Alpha", "status": "active"},
        {"id": EMP_B, "name": "Company Beta", "status": "active"},
    ]
    d.tables["employer_members"] = [
        {"id": "m-a", "employer_id": EMP_A, "user_id": MEMBER_A, "role": "member"},
        {"id": "m-b", "employer_id": EMP_B, "user_id": MEMBER_B, "role": "member"},
    ]
    d.tables["hiring_requirements"] = [
        {"id": REQ_A1, "employer_id": EMP_A, "title": "Alpha Backend Role", "status": "open"},
        {"id": REQ_A_CLOSED, "employer_id": EMP_A, "title": "Alpha Closed Role", "status": "closed"},
        {"id": REQ_B1, "employer_id": EMP_B, "title": "Beta Frontend Role", "status": "open"},
    ]
    d.tables["applications"] = []
    d.tables["application_events"] = []

    p1 = patch.object(svc, "get_supabase_client", return_value=d)
    p2 = patch.object(emp, "get_supabase_client", return_value=d)
    p1.start()
    p2.start()
    yield d
    p1.stop()
    p2.stop()


# ---------------------------------------------------------------------------
# 1. Student can save an application
# ---------------------------------------------------------------------------

def test_student_can_save_application(db):
    app = svc.create_application(STUDENT_A, REQ_A1, initial_status="saved", note="Bookmarked")
    assert app["student_id"] == STUDENT_A
    assert app["hiring_requirement_id"] == REQ_A1
    assert app["status"] == "saved"
    assert app["applied_at"] is None
    assert app["outcome"] is None
    assert app["employer_id"] == EMP_A

    # An event must be created
    events = [e for e in db.tables["application_events"] if e["application_id"] == app["id"]]
    assert len(events) == 1
    assert events[0]["from_status"] is None
    assert events[0]["to_status"] == "saved"
    assert events[0]["actor"] == STUDENT_A
    assert events[0]["note"] == "Bookmarked"


# ---------------------------------------------------------------------------
# 2. Student can apply directly
# ---------------------------------------------------------------------------

def test_student_can_apply_directly(db):
    app = svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")
    assert app["status"] == "applied"
    assert app["applied_at"] is not None
    assert app["outcome"] == "pending"

    events = [e for e in db.tables["application_events"] if e["application_id"] == app["id"]]
    assert len(events) == 1
    assert events[0]["to_status"] == "applied"
    assert events[0]["actor"] == STUDENT_A


# ---------------------------------------------------------------------------
# 3. Transition from saved to applied via reapply
# ---------------------------------------------------------------------------

def test_saved_to_applied_transition(db):
    saved = svc.create_application(STUDENT_A, REQ_A1, initial_status="saved")
    assert saved["status"] == "saved"

    # Re-applying transitions the existing application
    applied = svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")
    assert applied["id"] == saved["id"]
    assert applied["status"] == "applied"
    assert applied["applied_at"] is not None

    events = [e for e in db.tables["application_events"] if e["application_id"] == saved["id"]]
    assert len(events) == 2
    assert events[1]["from_status"] == "saved"
    assert events[1]["to_status"] == "applied"


# ---------------------------------------------------------------------------
# 4. Duplicate application protection & closed requirement
# ---------------------------------------------------------------------------

def test_duplicate_application_protection(db):
    svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")
    with pytest.raises(HTTPException) as exc:
        svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")
    assert exc.value.status_code == 400
    assert "Already applied" in exc.value.detail


def test_cannot_apply_to_closed_requirement(db):
    with pytest.raises(HTTPException) as exc:
        svc.create_application(STUDENT_A, REQ_A_CLOSED, initial_status="applied")
    assert exc.value.status_code == 400
    assert "Requirement is not open" in exc.value.detail


# ---------------------------------------------------------------------------
# 5. Student isolation: only sees own applications
# ---------------------------------------------------------------------------

def test_student_isolation(db):
    app_a = svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")
    app_b = svc.create_application(STUDENT_B, REQ_A1, initial_status="applied")

    # Student A lists only their own
    list_a = svc.list_applications(STUDENT_A)
    assert len(list_a) == 1
    assert list_a[0]["id"] == app_a["id"]

    # Student B lists only their own
    list_b = svc.list_applications(STUDENT_B)
    assert len(list_b) == 1
    assert list_b[0]["id"] == app_b["id"]

    # Student B cannot get Student A's detail (404)
    with pytest.raises(HTTPException) as exc:
        svc.get_application_detail(STUDENT_B, app_a["id"])
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 6. Employer can only see applications for its own requirements
# ---------------------------------------------------------------------------

def test_employer_sees_only_own_requirements(db):
    app_a = svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")
    app_b = svc.create_application(STUDENT_A, REQ_B1, initial_status="applied")

    # Employer A member only sees app_a
    apps_for_emp_a = svc.list_applications_for_employer(MEMBER_A, EMP_A)
    assert len(apps_for_emp_a) == 1
    assert apps_for_emp_a[0]["id"] == app_a["id"]

    # Employer B member only sees app_b
    apps_for_emp_b = svc.list_applications_for_employer(MEMBER_B, EMP_B)
    assert len(apps_for_emp_b) == 1
    assert apps_for_emp_b[0]["id"] == app_b["id"]


# ---------------------------------------------------------------------------
# 7. Employer A cannot access Employer B applications
# ---------------------------------------------------------------------------

def test_cross_employer_isolation(db):
    svc.create_application(STUDENT_A, REQ_B1, initial_status="applied")

    # Member of Corp A attempting to list Corp B's applications gets 404
    with pytest.raises(HTTPException) as exc:
        svc.list_applications_for_employer(MEMBER_A, EMP_B)
    assert exc.value.status_code == 404

    # Member of Corp A attempting to list Corp B requirement applications gets 404
    with pytest.raises(HTTPException) as exc2:
        svc.list_applications_for_requirement(MEMBER_A, REQ_B1)
    assert exc2.value.status_code == 404


# ---------------------------------------------------------------------------
# 8. Actor authorization: wrong actor receives 403
# ---------------------------------------------------------------------------

def test_wrong_actor_receives_403(db):
    app = svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")

    # Student trying to advance to screening receives 403
    with pytest.raises(HTTPException) as exc:
        svc.transition_status(app["id"], STUDENT_A, "screening")
    assert exc.value.status_code == 403
    assert "employer-controlled" in exc.value.detail

    # Employer member advances to screening
    svc.transition_status(app["id"], MEMBER_A, "screening")

    # Student trying to advance to interview receives 403
    with pytest.raises(HTTPException) as exc2:
        svc.transition_status(app["id"], STUDENT_A, "interview")
    assert exc2.value.status_code == 403

    # Employer trying to withdraw receives 403 (withdrawing is student-controlled)
    with pytest.raises(HTTPException) as exc3:
        svc.transition_status(app["id"], MEMBER_A, "withdrawn")
    assert exc3.value.status_code == 403
    assert "student-controlled" in exc3.value.detail


# ---------------------------------------------------------------------------
# 9. Invalid state transition receives 400
# ---------------------------------------------------------------------------

def test_invalid_state_transition_receives_400(db):
    app = svc.create_application(STUDENT_A, REQ_A1, initial_status="saved")

    # saved cannot jump directly to interview or selected
    with pytest.raises(HTTPException) as exc1:
        svc.transition_status(app["id"], STUDENT_A, "interview")
    assert exc1.value.status_code == 400

    with pytest.raises(HTTPException) as exc2:
        svc.transition_status(app["id"], MEMBER_A, "selected")
    assert exc2.value.status_code == 400


# ---------------------------------------------------------------------------
# 10. Terminal states reject further transitions
# ---------------------------------------------------------------------------

def test_terminal_states_reject_further_transitions(db):
    app = svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")

    # Employer rejects
    svc.transition_status(app["id"], MEMBER_A, "rejected")

    # Trying any further transition from rejected must 400
    with pytest.raises(HTTPException) as exc1:
        svc.transition_status(app["id"], MEMBER_A, "screening")
    assert exc1.value.status_code == 400
    assert "terminal" in exc1.value.detail

    with pytest.raises(HTTPException) as exc2:
        svc.transition_status(app["id"], STUDENT_A, "withdrawn")
    assert exc2.value.status_code == 400
    assert "terminal" in exc2.value.detail


# ---------------------------------------------------------------------------
# 11. Student can withdraw from valid states
# ---------------------------------------------------------------------------

def test_student_withdrawal_outcomes(db):
    # Withdraw from applied -> outcome is 'withdrawn'
    app1 = svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")
    w1 = svc.transition_status(app1["id"], STUDENT_A, "withdrawn")
    assert w1["status"] == "withdrawn"
    assert w1["outcome"] == "withdrawn"

    # Withdraw from offer_received -> outcome is 'declined_offer'
    app2 = svc.create_application(STUDENT_B, REQ_A1, initial_status="applied")
    svc.transition_status(app2["id"], MEMBER_A, "screening")
    svc.transition_status(app2["id"], MEMBER_A, "interview")
    svc.transition_status(app2["id"], MEMBER_A, "offer_received")
    w2 = svc.transition_status(app2["id"], STUDENT_B, "withdrawn")
    assert w2["status"] == "withdrawn"
    assert w2["outcome"] == "declined_offer"


# ---------------------------------------------------------------------------
# 12. Application events are immutable and append-only
# ---------------------------------------------------------------------------

def test_application_events_immutable_append_only(db):
    app = svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")
    svc.transition_status(app["id"], MEMBER_A, "screening", note="Resume screened")
    svc.transition_status(app["id"], MEMBER_A, "interview", note="Scheduled round 1")
    svc.transition_status(app["id"], MEMBER_A, "offer_received", note="Offer made")
    svc.transition_status(app["id"], MEMBER_A, "selected", note="Offer accepted and selected")

    events = [e for e in db.tables["application_events"] if e["application_id"] == app["id"]]
    assert len(events) == 5
    assert [e["to_status"] for e in events] == ["applied", "screening", "interview", "offer_received", "selected"]

    # No delete operation was ever invoked on application_events
    assert "application_events" not in db.deleted_from


# ---------------------------------------------------------------------------
# 13. Application timeline ordered correctly
# ---------------------------------------------------------------------------

def test_timeline_ordering(db):
    app = svc.create_application(STUDENT_A, REQ_A1, initial_status="saved")
    svc.transition_status(app["id"], STUDENT_A, "applied")
    svc.transition_status(app["id"], MEMBER_A, "screening")

    detail = svc.get_application_detail(STUDENT_A, app["id"])
    assert "events" in detail
    assert len(detail["events"]) == 3
    assert detail["events"][0]["to_status"] == "saved"
    assert detail["events"][1]["to_status"] == "applied"
    assert detail["events"][2]["to_status"] == "screening"


# ---------------------------------------------------------------------------
# 14. Requirement ownership enforced (no stored employer_id duplicate)
# ---------------------------------------------------------------------------

def test_no_stored_employer_id_on_applications(db):
    app = svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")
    raw_row = [r for r in db.tables["applications"] if r["id"] == app["id"]][0]

    # In database row: hiring_requirement_id exists, employer_id must NOT be stored
    assert "hiring_requirement_id" in raw_row
    assert "employer_id" not in raw_row

    # In service response: employer_id is attached dynamically via join
    assert app["employer_id"] == EMP_A


# ---------------------------------------------------------------------------
# 15. Unauthorized access does not leak application information
# ---------------------------------------------------------------------------

def test_unauthorized_access_does_not_leak(db):
    app = svc.create_application(STUDENT_A, REQ_A1, initial_status="applied")

    # Outsider querying detail receives 404, not 403 or payload
    with pytest.raises(HTTPException) as exc:
        svc.get_application_detail(OUTSIDER, app["id"])
    assert exc.value.status_code == 404
    assert exc.value.detail == "Application not found"
