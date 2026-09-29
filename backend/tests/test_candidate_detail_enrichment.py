"""Employer candidate detail: assessed profile vs requirement matches.

Covers:
1. Requirement with 0 mapped skills still exposes the candidate's 5 assessments
   via candidate_skills, with skill_matches == [] (never "candidate has no skills").
2. Python 0.86 vs required 0.75 -> met.
3. Python 0.60 vs required 0.75 -> gap.
4. Required Python with no assessment -> observed None / unassessed.
5. Same user as applicant AND employer member gets employer enrichment and may
   perform both employer- and student-controlled transitions.
6. Unrelated employer member gets 404.
7. Projects without certifications -> only project evidence (no fake certs).
8. Certifications without projects -> only cert evidence.
"""

import pytest
from unittest.mock import patch
from fastapi import HTTPException

from app.services import outcome_service as svc
from app.services import employer_service as emp

STUDENT_A = "student-aaa-1111"
STUDENT_B = "student-bbb-2222"
MEMBER_A = "member-corp-a"
MEMBER_B = "member-corp-b"
EMP_A = "emp-aaaa-1111"
EMP_B = "emp-bbbb-2222"
REQ_A1 = "req-aaaa-0001"
REQ_B1 = "req-bbbb-0001"

SKILL_PY = "00000000-0000-0000-0000-000000000001"
SKILL_JS = "00000000-0000-0000-0000-000000000002"
SKILL_SQL = "00000000-0000-0000-0000-000000000003"
SKILL_REACT = "00000000-0000-0000-0000-000000000004"
SKILL_DOCKER = "00000000-0000-0000-0000-000000000005"


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
            return Result([r for r in rows if self._matches(r)])
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


def _assessment(skill_id, proficiency, confidence=0.8, evidence_count=3):
    return {
        "skill_id": skill_id,
        "proficiency": proficiency,
        "confidence": confidence,
        "evidence_count": evidence_count,
        "evidence_weight": 0.7,
        "source_diversity": 0.5,
    }


@pytest.fixture
def fdb():
    d = FakeDB()
    d.tables["employers"] = [
        {"id": EMP_A, "name": "Corp A", "status": "active", "created_by": MEMBER_A},
        {"id": EMP_B, "name": "Corp B", "status": "active", "created_by": MEMBER_B},
    ]
    d.tables["employer_members"] = [
        {"id": "m-a", "employer_id": EMP_A, "user_id": MEMBER_A, "role": "owner"},
        {"id": "m-b", "employer_id": EMP_B, "user_id": MEMBER_B, "role": "member"},
    ]
    d.tables["hiring_requirements"] = [
        {"id": REQ_A1, "employer_id": EMP_A, "title": "Backend Dev", "status": "open"},
        {"id": REQ_B1, "employer_id": EMP_B, "title": "Frontend Dev", "status": "open"},
    ]
    d.tables["hiring_requirement_skills"] = []
    d.tables["skills"] = [
        {"id": SKILL_PY, "canonical_name": "python", "display_name": "Python", "category": "Programming"},
        {"id": SKILL_JS, "canonical_name": "javascript", "display_name": "JavaScript", "category": "Frontend"},
        {"id": SKILL_SQL, "canonical_name": "sql", "display_name": "SQL", "category": "Database"},
        {"id": SKILL_REACT, "canonical_name": "react", "display_name": "React", "category": "Frontend"},
        {"id": SKILL_DOCKER, "canonical_name": "docker", "display_name": "Docker", "category": "DevOps"},
    ]
    d.tables["applications"] = [
        {
            "id": "app-a1",
            "student_id": STUDENT_A,
            "hiring_requirement_id": REQ_A1,
            "status": "applied",
            "outcome": "pending",
            "applied_at": "2026-07-01T00:00:00+00:00",
        },
    ]
    d.tables["application_events"] = []
    d.tables["profiles"] = [
        {"user_id": STUDENT_A, "full_name": "Student A", "college": "RIT",
         "degree": "B.E.", "branch": "CS", "graduation_year": 2029},
    ]
    d.tables["skill_assessments"] = []
    d.tables["projects"] = []
    d.tables["certifications"] = []
    d.tables["evidence"] = []

    patches = [
        patch.object(svc, "get_supabase_client", return_value=d),
        patch.object(emp, "get_supabase_client", return_value=d),
    ]
    for p in patches:
        p.start()
    yield d
    for p in patches:
        p.stop()


def _assessments_for(fdb, user_id, rows):
    for r in rows:
        d = dict(r)
        d["user_id"] = user_id
        fdb.tables["skill_assessments"].append(d)


def test_01_no_requirement_skills_still_shows_profile(fdb):
    _assessments_for(fdb, STUDENT_A, [
        _assessment(SKILL_PY, 0.86),
        _assessment(SKILL_JS, 0.72),
        _assessment(SKILL_SQL, 0.83),
        _assessment(SKILL_REACT, 0.81),
        _assessment(SKILL_DOCKER, 0.61),
    ])
    detail = svc.get_application_detail(MEMBER_A, "app-a1")
    assert len(detail["candidate_skills"]) == 5
    assert detail["skill_matches"] == []
    by_id = {s["skill_id"]: s for s in detail["candidate_skills"]}
    assert by_id[SKILL_PY]["proficiency"] == pytest.approx(0.86)
    assert by_id[SKILL_PY]["skill_name"] == "Python"
    assert by_id[SKILL_PY]["confidence"] == pytest.approx(0.8)
    assert by_id[SKILL_PY]["evidence_count"] == 3


def test_02_requirement_match_met(fdb):
    fdb.tables["hiring_requirement_skills"].append(
        {"id": "hrs-1", "hiring_requirement_id": REQ_A1, "skill_id": SKILL_PY,
         "importance": "required", "required_level": 0.75})
    _assessments_for(fdb, STUDENT_A, [_assessment(SKILL_PY, 0.86)])
    detail = svc.get_application_detail(MEMBER_A, "app-a1")
    assert len(detail["skill_matches"]) == 1
    m = detail["skill_matches"][0]
    assert m["skill_name"] == "Python"
    assert m["importance"] == "required"
    assert m["required_level"] == pytest.approx(0.75)
    assert m["observed_level"] == pytest.approx(0.86)
    assert m["status"] == "met"


def test_03_requirement_match_gap(fdb):
    fdb.tables["hiring_requirement_skills"].append(
        {"id": "hrs-1", "hiring_requirement_id": REQ_A1, "skill_id": SKILL_PY,
         "importance": "required", "required_level": 0.75})
    _assessments_for(fdb, STUDENT_A, [_assessment(SKILL_PY, 0.60)])
    detail = svc.get_application_detail(MEMBER_A, "app-a1")
    m = detail["skill_matches"][0]
    assert m["observed_level"] == pytest.approx(0.60)
    assert m["status"] == "gap"


def test_04_required_but_unassessed(fdb):
    fdb.tables["hiring_requirement_skills"].append(
        {"id": "hrs-1", "hiring_requirement_id": REQ_A1, "skill_id": SKILL_PY,
         "importance": "required", "required_level": 0.75})
    detail = svc.get_application_detail(MEMBER_A, "app-a1")
    m = detail["skill_matches"][0]
    assert m["observed_level"] is None
    assert m["status"] == "unassessed"
    # No fabrication: profile is empty, not zeroes
    assert detail["candidate_skills"] == []


def test_05_same_user_student_and_employer(fdb):
    # MEMBER_A applies to their own company's requirement
    fdb.tables["applications"].append({
        "id": "app-self",
        "student_id": MEMBER_A,
        "hiring_requirement_id": REQ_A1,
        "status": "applied",
        "outcome": "pending",
        "applied_at": "2026-07-02T00:00:00+00:00",
    })
    fdb.tables["profiles"].append(
        {"user_id": MEMBER_A, "full_name": "Owner A", "college": "RIT",
         "degree": "B.E.", "branch": "CS", "graduation_year": 2028})
    _assessments_for(fdb, MEMBER_A, [_assessment(SKILL_PY, 0.9)])
    detail = svc.get_application_detail(MEMBER_A, "app-self")
    assert detail["candidate_profile"]["full_name"] == "Owner A"
    assert len(detail["candidate_skills"]) == 1
    # Employer-controlled transition works for the dual-role user
    moved = svc.transition_status("app-self", MEMBER_A, "screening")
    assert moved["status"] == "screening"
    # Student-controlled transition also works for the dual-role user
    fdb.tables["applications"].append({
        "id": "app-self-2",
        "student_id": MEMBER_A,
        "hiring_requirement_id": REQ_A1,
        "status": "applied",
        "outcome": "pending",
        "applied_at": "2026-07-02T00:00:00+00:00",
    })
    withdrawn = svc.transition_status("app-self-2", MEMBER_A, "withdrawn")
    assert withdrawn["status"] == "withdrawn"


def test_06_unrelated_employer_denied(fdb):
    with pytest.raises(HTTPException) as exc:
        svc.get_application_detail(MEMBER_B, "app-a1")
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc2:
        svc.transition_status("app-a1", MEMBER_B, "screening")
    assert exc2.value.status_code == 404


def test_07_projects_without_certifications(fdb):
    fdb.tables["projects"].append({
        "id": "proj-1", "user_id": STUDENT_A, "name": "Shop API",
        "description": "REST API for a shop", "technologies": ["python", "fastapi"],
        "project_url": "https://example.com/shop", "github_url": None,
    })
    fdb.tables["evidence"].append({
        "id": "ev-1", "user_id": STUDENT_A, "evidence_type": "github",
        "title": "github.com/student-a/shop", "source_url": "https://github.com/student-a/shop",
    })
    detail = svc.get_application_detail(MEMBER_A, "app-a1")
    kinds = [e["type"] for e in detail["candidate_evidence"]]
    assert "project" in kinds
    assert "certification" not in kinds
    assert "github" in kinds
    proj = next(e for e in detail["candidate_evidence"] if e["type"] == "project")
    assert proj["technologies"] == ["python", "fastapi"]
    assert proj["url"] == "https://example.com/shop"


def test_08_certifications_without_projects(fdb):
    fdb.tables["certifications"].append({
        "id": "cert-1", "user_id": STUDENT_A, "name": "AWS Cloud Practitioner",
        "issuing_org": "Amazon", "certificate_url": "https://example.com/cert",
    })
    detail = svc.get_application_detail(MEMBER_A, "app-a1")
    kinds = [e["type"] for e in detail["candidate_evidence"]]
    assert "certification" in kinds
    assert "project" not in kinds
    cert = next(e for e in detail["candidate_evidence"] if e["type"] == "certification")
    assert cert["issuing_org"] == "Amazon"
    assert cert["url"] == "https://example.com/cert"
