"""Person 2 Step 1: Employer Foundation Unit & Authorization Tests.

Covers:
- Employer creation and owner bootstrapping
- Employer isolation (outsiders 404)
- Sensitive contact_email stripping for non-owners
- Role permissions (owners vs members: 403 on admin actions)
- Member management & last-owner protection (400)
- Hiring requirements CRUD authorization
- Requirement skills: canonical skill FK validation (400 for unknown)
- Requirement skills: importance and proficiency validation
- Cross-employer isolation (Employer A vs Employer B: 404)
- Student access gating (application required for requirement/skills view: 404)
- Canonical skills catalog lookup
"""

import pytest
from unittest.mock import patch
from fastapi import HTTPException

from app.services import employer_service as emp

OWNER = "user-owner"
MEMBER = "user-member"
OUTSIDER = "user-outsider"
STUDENT_APPLIED = "student-applied"
STUDENT_UNAPPLIED = "student-unapplied"

EMP_1 = "emp-1111"
EMP_2 = "emp-2222"
REQ_1 = "req-1111"
REQ_2 = "req-2222"

SKILL_PYTHON = "aaaa0000-0000-0000-0000-000000000001"
SKILL_FASTAPI = "aaaa0000-0000-0000-0000-000000000002"
UNKNOWN_SKILL = "99999999-9999-9999-9999-999999999999"


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
    d.tables["employers"] = [
        {
            "id": EMP_1,
            "name": "Acme Corp",
            "industry": "Software",
            "location": "Bengaluru",
            "contact_email": "founder@acme.test",
            "status": "active",
            "created_by": OWNER,
        },
        {
            "id": EMP_2,
            "name": "Beta Labs",
            "industry": "AI",
            "location": "Hyderabad",
            "contact_email": "hr@beta.test",
            "status": "active",
            "created_by": "other-user",
        },
    ]
    d.tables["employer_members"] = [
        {"id": "m-owner", "employer_id": EMP_1, "user_id": OWNER, "role": "owner"},
        {"id": "m-member", "employer_id": EMP_1, "user_id": MEMBER, "role": "member"},
        {"id": "m-emp2", "employer_id": EMP_2, "user_id": "other-user", "role": "owner"},
    ]
    d.tables["hiring_requirements"] = [
        {
            "id": REQ_1,
            "employer_id": EMP_1,
            "title": "Backend Engineer",
            "role_key": "software_engineer",
            "status": "open",
            "created_by": OWNER,
        },
        {
            "id": REQ_2,
            "employer_id": EMP_2,
            "title": "ML Engineer",
            "role_key": "ml_engineer",
            "status": "open",
            "created_by": "other-user",
        },
    ]
    d.tables["skills"] = [
        {"id": SKILL_PYTHON, "canonical_name": "python", "display_name": "Python", "category": "Backend"},
        {"id": SKILL_FASTAPI, "canonical_name": "fastapi", "display_name": "FastAPI", "category": "Backend"},
    ]
    d.tables["hiring_requirement_skills"] = [
        {
            "id": "hrs-1",
            "hiring_requirement_id": REQ_1,
            "skill_id": SKILL_PYTHON,
            "importance": "required",
            "required_level": 0.8,
            "note": "Async Python proficiency",
        }
    ]
    d.tables["applications"] = [
        {
            "id": "app-1",
            "student_id": STUDENT_APPLIED,
            "hiring_requirement_id": REQ_1,
            "status": "applied",
        }
    ]

    p = patch.object(emp, "get_supabase_client", return_value=d)
    p.start()
    yield d
    p.stop()


# ---------------------------------------------------------------------------
# 1. Employer creation & bootstrap
# ---------------------------------------------------------------------------

def test_create_employer_bootstraps_owner(db):
    new_emp = emp.create_employer("new-creator", {"name": "Starlight Inc", "industry": "Cloud"})
    assert new_emp["name"] == "Starlight Inc"
    assert new_emp["created_by"] == "new-creator"

    # Membership must have been bootstrapped as owner
    m = emp.get_membership("new-creator", new_emp["id"])
    assert m is not None
    assert m["role"] == "owner"


# ---------------------------------------------------------------------------
# 2. Employer isolation & contact_email privacy
# ---------------------------------------------------------------------------

def test_outsider_cannot_read_employer(db):
    with pytest.raises(HTTPException) as exc:
        emp.get_employer(OUTSIDER, EMP_1)
    assert exc.value.status_code == 404


def test_member_cannot_see_contact_email(db):
    row = emp.get_employer(MEMBER, EMP_1)
    assert row["name"] == "Acme Corp"
    assert "contact_email" not in row


def test_owner_sees_contact_email(db):
    row = emp.get_employer(OWNER, EMP_1)
    assert row["name"] == "Acme Corp"
    assert row.get("contact_email") == "founder@acme.test"


# ---------------------------------------------------------------------------
# 3. Role permissions: Owner vs Member
# ---------------------------------------------------------------------------

def test_member_cannot_update_employer_gets_403(db):
    with pytest.raises(HTTPException) as exc:
        emp.update_employer(MEMBER, EMP_1, {"name": "Hacked Name"})
    assert exc.value.status_code == 403


def test_owner_can_update_employer(db):
    updated = emp.update_employer(OWNER, EMP_1, {"name": "Acme Global"})
    assert updated["name"] == "Acme Global"


def test_member_cannot_delete_employer_gets_403(db):
    with pytest.raises(HTTPException) as exc:
        emp.delete_employer(MEMBER, EMP_1)
    assert exc.value.status_code == 403


def test_owner_can_delete_employer(db):
    emp.delete_employer(OWNER, EMP_1)
    assert "employers" in db.deleted_from


def test_member_cannot_add_member_gets_403(db):
    with pytest.raises(HTTPException) as exc:
        emp.add_member(MEMBER, EMP_1, "new-user-1", "member")
    assert exc.value.status_code == 403


def test_owner_can_add_member(db):
    row = emp.add_member(OWNER, EMP_1, "new-user-1", "member")
    assert row["user_id"] == "new-user-1"
    assert row["role"] == "member"


def test_cannot_remove_last_owner(db):
    # EMP_1 has only 1 owner (OWNER)
    with pytest.raises(HTTPException) as exc:
        emp.remove_member(OWNER, EMP_1, OWNER)
    assert exc.value.status_code == 400
    assert "Cannot remove the last owner" in exc.value.detail


# ---------------------------------------------------------------------------
# 4. Hiring Requirements CRUD & Authorization
# ---------------------------------------------------------------------------

def test_outsider_cannot_create_requirement(db):
    with pytest.raises(HTTPException) as exc:
        emp.create_requirement(OUTSIDER, EMP_1, {"title": "Frontend Lead"})
    assert exc.value.status_code == 404


def test_member_can_create_requirement(db):
    req = emp.create_requirement(MEMBER, EMP_1, {"title": "QA Engineer", "location": "Remote"})
    assert req["title"] == "QA Engineer"
    assert req["status"] == "open"


def test_member_can_update_requirement(db):
    up = emp.update_requirement(MEMBER, REQ_1, {"title": "Senior Backend Engineer", "status": "paused"})
    assert up["title"] == "Senior Backend Engineer"
    assert up["status"] == "paused"


def test_outsider_cannot_update_requirement(db):
    with pytest.raises(HTTPException) as exc:
        emp.update_requirement(OUTSIDER, REQ_1, {"title": "Intruder Edit"})
    assert exc.value.status_code == 404


def test_member_can_delete_requirement(db):
    emp.delete_requirement(MEMBER, REQ_1)
    assert "hiring_requirements" in db.deleted_from


def test_outsider_cannot_delete_requirement(db):
    with pytest.raises(HTTPException) as exc:
        emp.delete_requirement(OUTSIDER, REQ_1)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 5. Requirement Skills & Canonical Skill Validation
# ---------------------------------------------------------------------------

def test_set_skills_rejects_unknown_skill(db):
    with pytest.raises(HTTPException) as exc:
        emp.set_requirement_skills(
            MEMBER,
            REQ_1,
            [{"skill_id": UNKNOWN_SKILL, "importance": "required", "required_level": 0.5}],
        )
    assert exc.value.status_code == 400
    assert "Unknown skill_id" in exc.value.detail


def test_set_skills_rejects_invalid_importance(db):
    with pytest.raises(HTTPException) as exc:
        emp.set_requirement_skills(
            MEMBER,
            REQ_1,
            [{"skill_id": SKILL_PYTHON, "importance": "mandatory"}],
        )
    assert exc.value.status_code == 400
    assert "importance must be required or preferred" in exc.value.detail


def test_member_can_set_and_list_requirement_skills(db):
    skills = [
        {"skill_id": SKILL_PYTHON, "importance": "required", "required_level": 0.9, "note": "Core"},
        {"skill_id": SKILL_FASTAPI, "importance": "preferred", "required_level": 0.7, "note": "APIs"},
    ]
    saved = emp.set_requirement_skills(MEMBER, REQ_1, skills)
    assert len(saved) == 2
    # Verify metadata enrichment
    assert any(s.get("skill_name") == "Python" for s in saved)
    assert any(s.get("skill_name") == "FastAPI" for s in saved)

    listed = emp.list_requirement_skills(MEMBER, REQ_1)
    assert len(listed) == 2
    assert any(s.get("skill_name") == "Python" for s in listed)


def test_outsider_cannot_set_requirement_skills(db):
    with pytest.raises(HTTPException) as exc:
        emp.set_requirement_skills(
            OUTSIDER,
            REQ_1,
            [{"skill_id": SKILL_PYTHON, "importance": "required"}],
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 6. Cross-Employer Isolation & Student Isolation
# ---------------------------------------------------------------------------

def test_employer_b_member_cannot_modify_employer_a_requirement(db):
    with pytest.raises(HTTPException) as exc:
        emp.update_requirement("other-user", REQ_1, {"title": "Cross Org Mutation"})
    assert exc.value.status_code == 404


def test_student_with_application_can_read_requirement_and_skills(db):
    req = emp.get_requirement(STUDENT_APPLIED, REQ_1)
    assert req["id"] == REQ_1

    skills = emp.list_requirement_skills(STUDENT_APPLIED, REQ_1)
    assert len(skills) >= 1


def test_student_without_application_cannot_read_requirement_or_skills(db):
    with pytest.raises(HTTPException) as exc1:
        emp.get_requirement(STUDENT_UNAPPLIED, REQ_1)
    assert exc1.value.status_code == 404

    with pytest.raises(HTTPException) as exc2:
        emp.list_requirement_skills(STUDENT_UNAPPLIED, REQ_1)
    assert exc2.value.status_code == 404


def test_list_canonical_skills_catalog(db):
    catalog = emp.list_canonical_skills()
    assert len(catalog) == 2
    assert {s["canonical_name"] for s in catalog} == {"python", "fastapi"}
