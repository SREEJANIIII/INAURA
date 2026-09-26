"""Career Track Integration tests: student <-> employer closed loop.

Uses mocked Supabase clients (no live DB). Verifies the integration contract:
one canonical application row, actor-scoped access, employer transitions
visible to students, append-only events, feedback/assessment separation,
placement authorization, cross-tenant isolation, PII-free discovery, and the
open-roles discovery endpoint used by the student apply flow.
"""

import inspect
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services import outcome_service as svc


class _Query:
    def __init__(self, client, table):
        self._client = client
        self._table = table
        self.ops = []

    def select(self, *a, **k):
        self.ops.append(("select", a))
        return self

    def order(self, *a, **k):
        self.ops.append(("order", a, k))
        return self

    def limit(self, *a, **k):
        self.ops.append(("limit", a))
        return self

    def eq(self, col, val):
        self.ops.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.ops.append(("in_", col, list(vals)))
        return self

    def insert(self, payload):
        self.ops.append(("insert", payload))
        return self

    def update(self, payload):
        self.ops.append(("update", payload))
        return self

    def execute(self):
        self._client.queries.append((self._table, self.ops))
        return SimpleNamespace(data=self._client._pop(self._table, self.ops))


class _FakeClient:
    """Table -> queue of result rows. Records every query for filter assertions."""

    def __init__(self, tables):
        self._tables = {k: [list(v) for v in vals] for k, vals in tables.items()}
        self.queries = []

    def table(self, name):
        return _Query(self, name)

    def _pop(self, table, ops):
        queue = self._tables.get(table, [])
        if queue:
            return queue.pop(0)
        # Default per-table echo for inserts/updates so flows complete.
        for op in ops:
            if op[0] == "insert":
                payload = op[1]
                rows = payload if isinstance(payload, list) else [payload]
                return [{**r, "id": r.get("id", f"{table}-1")} for r in rows]
            if op[0] == "update":
                return [{"id": f"{table}-1", **op[1]}]
        return []


def _ops_for(client, table, op):
    return [o for t, ops in client.queries if t == table for o in ops if o[0] == op]


# 1. Student lists only their own applications -------------------------------

def test_student_list_scoped_by_student_id():
    rows = [
        {"id": "a1", "student_id": "s1", "hiring_requirement_id": "r1", "status": "applied"},
        {"id": "a2", "student_id": "s1", "hiring_requirement_id": "r2", "status": "saved"},
    ]
    fake = _FakeClient({
        "applications": [rows],
        "hiring_requirements": [[
            {"id": "r1", "employer_id": "e1", "title": "Backend Intern"},
            {"id": "r2", "employer_id": "e2", "title": "Data Intern"},
        ]],
        "employers": [[{"id": "e1", "name": "ABC"}, {"id": "e2", "name": "XYZ"}]],
    })
    with patch.object(svc, "_ensure_client", return_value=fake):
        out = svc.list_applications("s1")
    eqs = _ops_for(fake, "applications", "eq")
    assert ("eq", "student_id", "s1") in eqs
    assert {r["id"] for r in out} == {"a1", "a2"}


# 2. Employer lists only their requirements' applications ---------------------

def test_employer_list_isolated_by_membership():
    fake = _FakeClient({
        "hiring_requirements": [[{"id": "r1", "title": "Backend Intern"}]],
        "applications": [[{"id": "a1", "student_id": "s9", "hiring_requirement_id": "r1", "status": "applied"}]],
        "profiles": [[{"user_id": "s9", "full_name": "Sam"}]],
    })
    with patch.object(svc.emp, "require_employer_access", return_value={"role": "owner"}), \
         patch.object(svc, "_ensure_client", return_value=fake):
        out = svc.list_applications_for_employer("owner-1", "emp-A")
    assert out[0]["candidate_name"] == "Sam"
    assert out[0]["employer_id"] == "emp-A"


def test_employer_b_cannot_list_employer_a():
    with patch.object(svc.emp, "require_employer_access",
                      side_effect=HTTPException(status_code=404, detail="Employer not found")):
        with pytest.raises(HTTPException) as exc:
            svc.list_applications_for_employer("stranger", "emp-A")
    assert exc.value.status_code == 404


# 3. Employer transition is visible to the student (same canonical row) -------

def test_employer_transition_visible_to_student():
    app = {"id": "app-1", "student_id": "s1", "hiring_requirement_id": "r1", "status": "applied"}
    fake = _FakeClient({
        "applications": [[{"id": "app-1", "student_id": "s1", "hiring_requirement_id": "r1",
                           "status": "screening"}]],
    })
    with patch.object(svc, "_get_application", return_value=dict(app)), \
         patch.object(svc, "_actor_type_for", return_value="employer"), \
         patch.object(svc.emp, "_requirement_employer", return_value={"employer_id": "e1"}), \
         patch.object(svc, "_ensure_client", return_value=fake):
        updated = svc.transition_status("app-1", "owner-1", "screening", note="Shortlisted")
    assert updated["status"] == "screening"
    inserts = [o for t, ops in fake.queries if t == "application_events" for o in ops if o[0] == "insert"]
    assert inserts and inserts[0][1]["to_status"] == "screening"
    assert inserts[0][1]["from_status"] == "applied"


# 4/5. Students cannot progress the funnel or mark themselves selected --------

def test_student_cannot_take_employer_transition():
    app = {"id": "app-1", "student_id": "s1", "hiring_requirement_id": "r1", "status": "applied"}
    with patch.object(svc, "_get_application", return_value=app), \
         patch.object(svc, "_actor_type_for", return_value="student"):
        with pytest.raises(HTTPException) as exc:
            svc.transition_status("app-1", "s1", "screening")
    assert exc.value.status_code == 403


def test_student_cannot_mark_self_selected():
    app = {"id": "app-1", "student_id": "s1", "hiring_requirement_id": "r1", "status": "offer_received"}
    with patch.object(svc, "_get_application", return_value=app), \
         patch.object(svc, "_actor_type_for", return_value="student"):
        with pytest.raises(HTTPException) as exc:
            svc.transition_status("app-1", "s1", "selected")
    assert exc.value.status_code == 403


# 6. Events remain append-only -------------------------------------------------

def test_events_have_no_update_or_delete_path():
    assert not hasattr(svc, "update_application_event")
    assert not hasattr(svc, "delete_application_event")
    src = inspect.getsource(svc.transition_status)
    assert src.count('table("application_events").update') == 0
    assert src.count('table("application_events").delete') == 0


# 7. Feedback never writes skill assessments -----------------------------------

def test_feedback_writes_never_touch_assessments():
    src = inspect.getsource(svc.submit_feedback)
    assert "skill_assessments" not in src
    module_src = inspect.getsource(svc)
    assert 'table("skill_assessments").update' not in module_src
    assert 'table("skill_assessments").insert' not in module_src
    assert 'table("skill_assessments").delete' not in module_src


# 8. Feedback retrieval stays inside the relationship --------------------------

def test_student_reads_own_application_feedback():
    app = {"id": "app-1", "student_id": "s1", "hiring_requirement_id": "r1", "status": "interview"}
    fake = _FakeClient({
        "employer_feedback": [[{"id": "f1", "overall_rating": 4}]],
        "employer_skill_feedback": [[{"id": "s1", "skill_id": "sk1",
                                      "expected_level": 0.8, "observed_level": 0.6}]],
    })
    with patch.object(svc, "_get_application", return_value=app), \
         patch.object(svc, "_feedback_access", return_value=None), \
         patch.object(svc, "_ensure_client", return_value=fake):
        out = svc.get_feedback("s1", "app-1")
    assert out["id"] == "f1"
    assert out["skills"][0]["skill_gap"] == pytest.approx(0.2)


def test_stranger_cannot_read_feedback():
    app = {"id": "app-1", "student_id": "s1", "hiring_requirement_id": "r1", "status": "interview"}
    with patch.object(svc, "_get_application", return_value=app), \
         patch.object(svc, "_feedback_access",
                      side_effect=HTTPException(status_code=404, detail="Application not found")):
        with pytest.raises(HTTPException) as exc:
            svc.get_feedback("stranger", "app-1")
    assert exc.value.status_code == 404


# 9/11. Placement ownership -----------------------------------------------------

def test_placement_owner_reads_outsider_cannot():
    row = {"id": "p1", "student_id": "s1", "employer_id": "e1", "status": "joined"}
    fake = _FakeClient({"placement_outcomes": [[dict(row)]]})
    with patch.object(svc, "_ensure_client", return_value=fake):
        assert svc.get_placement_detail("s1", "p1")["id"] == "p1"
    fake2 = _FakeClient({"placement_outcomes": [[dict(row)]]})
    with patch.object(svc, "_ensure_client", return_value=fake2), \
         patch.object(svc.emp, "get_membership", return_value=None):
        with pytest.raises(HTTPException) as exc:
            svc.get_placement_detail("s2", "p1")
    assert exc.value.status_code == 404


def test_student_application_detail_hidden_from_stranger():
    app = {"id": "app-1", "student_id": "s1", "hiring_requirement_id": "r1", "status": "applied"}
    with patch.object(svc, "_get_application", return_value=app), \
         patch.object(svc, "_actor_type_for", return_value=None):
        with pytest.raises(HTTPException) as exc:
            svc.get_application_detail("s2", "app-1")
    assert exc.value.status_code == 404


# Open-roles discovery: public hiring fields only --------------------------------

def _open_roles_fake():
    return _FakeClient({
        "hiring_requirements": [[
            {"id": "r1", "employer_id": "e1", "title": "Backend Intern",
             "role_key": "backend", "location": "Bengaluru", "employment_type": "internship",
             "description": "Build APIs", "created_at": "2026-09-20T00:00:00+00:00"},
        ]],
        "employers": [[{"id": "e1", "name": "ABC"}]],
        "hiring_requirement_skills": [[
            {"hiring_requirement_id": "r1", "skill_id": "sk1",
             "importance": "required", "required_level": 0.8}]],
        "skills": [[{"id": "sk1", "display_name": "Python", "canonical_name": "python"}]],
        "applications": [[{"id": "a1", "hiring_requirement_id": "r1", "status": "applied"}]],
    })


def test_open_roles_lists_open_with_employer_and_skills():
    with patch.object(svc, "_ensure_client", return_value=_open_roles_fake()):
        out = svc.list_open_roles("s1")
    assert len(out) == 1
    role = out[0]
    assert role["title"] == "Backend Intern"
    assert role["employer_name"] == "ABC"
    assert role["skills"][0]["skill_name"] == "Python"
    assert role["application"] == {"id": "a1", "status": "applied"}


def test_open_roles_filters_open_and_carries_no_pii():
    fake = _open_roles_fake()
    with patch.object(svc, "_ensure_client", return_value=fake):
        out = svc.list_open_roles("s1", search="backend")
    eqs = [o for t, ops in fake.queries if t == "hiring_requirements" for o in ops if o[0] == "eq"]
    assert ("eq", "status", "open") in eqs
    blob = str(out)
    for forbidden in ("members", "contact_email", "phone", "overall_comment", "student_id"):
        assert forbidden not in blob


def test_open_roles_route_registered():
    from app.api.v1.endpoints.outcomes import router
    paths = [getattr(r, "path", "") for r in router.routes]
    assert "/outcomes/open-roles" in paths
