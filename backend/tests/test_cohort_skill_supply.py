"""P0 #3: cohort skill supply tests.

FakeDB pattern mirrors test_institution_course_supply.py (patch
cohort_supply_service.get_supabase_client). Skill math is asserted against
the existing skill_engine functions directly — no invented semantics.
"""

import json
import uuid
import pytest
from unittest.mock import patch
from fastapi import HTTPException
from pydantic import ValidationError
from pathlib import Path

from app.services import cohort_supply_service as svc
from app.services import skill_engine as engine
from app.services import evidence_weights as ew
from app.schemas import cohorts as schemas

INST_1 = "inst-1"
COURSE_1 = "course-1"
COURSE_2 = "course-2"
SKILL_REACT = "11111111-1111-1111-1111-111111111111"
SKILL_PYTHON = "22222222-2222-2222-2222-222222222222"
SKILL_SQL = "33333333-3333-3333-3333-333333333333"
SKILL_UNKNOWN = "99999999-9999-9999-9999-999999999999"

U1, U2, U3, U4, U5, U6 = (f"user-{i}" for i in range(1, 7))


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
        self.auth = FakeAuth(FakeAuthAdmin())

    def table(self, name):
        return FakeQuery(self, name)


class FakeAuthUser:
    """Minimal stand-in for supabase_auth.User (attribute access only)."""

    def __init__(self, id, email, user_metadata=None):
        self.id = id
        self.email = email
        self.user_metadata = user_metadata or {}
        self.app_metadata = {}


class FakeUserResponse:
    """Minimal stand-in for supabase_auth.UserResponse."""

    def __init__(self, user):
        self.user = user


class FakeAuthAdmin:
    """Fake Supabase Auth Admin API (service-role only in production).

    Stores users by lower-cased email. IDs are random UUID4s — deliberately
    NOT uuid5-derived — so tests prove cohort_members uses the actual
    returned Auth UUID rather than any locally computed value.
    """

    def __init__(self, initial=None):
        self.users_by_email: dict[str, FakeAuthUser] = {}
        self.create_calls: list = []
        for u in initial or []:
            self.users_by_email[str(u.email).strip().lower()] = u

    def list_users(self, page=None, per_page=None):
        users = sorted(self.users_by_email.values(), key=lambda u: str(u.email))
        if page is None or per_page is None:
            return list(users)
        start = (int(page) - 1) * int(per_page)
        return users[start:start + int(per_page)]

    def create_user(self, attributes):
        attrs = dict(attributes or {})
        email = str(attrs.get("email") or "").strip()
        key = email.lower()
        self.create_calls.append(dict(attrs))
        if key in self.users_by_email:
            raise Exception("User already exists")
        user = FakeAuthUser(
            id=str(uuid.uuid4()),
            email=email,
            user_metadata=dict(attrs.get("user_metadata") or {}),
        )
        self.users_by_email[key] = user
        return FakeUserResponse(user)


class FakeAuth:
    def __init__(self, admin):
        self.admin = admin


@pytest.fixture
def db():
    d = FakeDB()
    d.tables["skills"] = [
        {"id": SKILL_REACT, "canonical_name": "react", "display_name": "React", "category": "Frontend"},
        {"id": SKILL_PYTHON, "canonical_name": "python", "display_name": "Python", "category": "Programming"},
        {"id": SKILL_SQL, "canonical_name": "sql", "display_name": "SQL", "category": "Databases"},
    ]
    d.tables["institutions"] = [{"id": INST_1, "name": "Test Institute"}]
    d.tables["courses"] = [
        {"id": COURSE_1, "institution_id": INST_1, "name": "Web Dev"},
        {"id": COURSE_2, "institution_id": INST_1, "name": "Data"},
    ]
    p = patch.object(svc, "get_supabase_client", return_value=d)
    p.start()
    yield d
    p.stop()


def _cohort(db, **kw):
    base = {"institution_id": INST_1, "course_id": COURSE_1, "name": "Batch 2026-A"}
    base.update(kw)
    return svc.create_cohort(base)


def _sig(uid, skill_id, source, value):
    return {"user_id": uid, "skill_id": skill_id, "source_type": source,
            "signal_value": value, "source_reliability": ew.reliability(source)}


def _seed_signals(db, rows):
    db.tables.setdefault("skill_signals", []).extend(rows)


def _seed_assessments(db, rows):
    db.tables.setdefault("skill_assessments", []).extend(rows)


# ---------------------------------------------------------------------------
# 1–4. Cohort creation, belonging, consistency
# ---------------------------------------------------------------------------

def test_cohort_creation(db):
    c = _cohort(db)
    assert c["institution_id"] == INST_1 and c["course_id"] == COURSE_1
    assert c["status"] == "draft"


def test_cohort_retrieval_and_listing(db):
    c = _cohort(db)
    assert svc.get_cohort(c["id"])["id"] == c["id"]
    assert [x["id"] for x in svc.list_cohorts(course_id=COURSE_1)] == [c["id"]]
    assert svc.list_cohorts(course_id=COURSE_2) == []
    with pytest.raises(HTTPException) as exc:
        svc.get_cohort("missing")
    assert exc.value.status_code == 404


def test_institution_course_consistency(db):
    with pytest.raises(HTTPException) as exc:
        svc.create_cohort({"institution_id": "other-inst", "course_id": COURSE_1, "name": "Bad"})
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        svc.create_cohort({"institution_id": INST_1, "course_id": "nope", "name": "Bad"})
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        svc.create_cohort({"institution_id": INST_1, "course_id": COURSE_1,
                           "name": "X", "start_date": "2026-09-01", "end_date": "2026-01-01"})
    assert exc.value.status_code == 400
    # Duplicate name in same course rejected; other courses fine
    _cohort(db, name="Batch X")
    with pytest.raises(HTTPException) as exc:
        _cohort(db, name="batch x")
    assert exc.value.status_code == 409
    assert _cohort(db, course_id=COURSE_2, name="Batch X")["course_id"] == COURSE_2


# ---------------------------------------------------------------------------
# 5–8. Membership, duplicates, lifecycle, retrieval
# ---------------------------------------------------------------------------

def test_cohort_membership(db):
    c = _cohort(db)
    m = svc.add_member(c["id"], U1)
    assert m["cohort_id"] == c["id"] and m["user_id"] == U1
    assert m["enrollment_status"] == "active"


def test_duplicate_membership_prevention(db):
    c = _cohort(db)
    svc.add_member(c["id"], U1)
    with pytest.raises(HTTPException) as exc:
        svc.add_member(c["id"], U1)
    assert exc.value.status_code == 409


def test_membership_lifecycle_and_history(db):
    c = _cohort(db)
    m1 = svc.add_member(c["id"], U1)
    out = svc.update_member(c["id"], m1["id"], "withdrawn")
    assert out["enrollment_status"] == "withdrawn" and out["exited_at"]
    # History retained: the withdrawn row still exists
    assert len(svc.list_members(c["id"])) == 1
    # Re-joining after withdrawal creates a new active row
    m2 = svc.add_member(c["id"], U1)
    assert m2["id"] != m1["id"]
    # Reactivating the old row while another is active is rejected
    with pytest.raises(HTTPException) as exc:
        svc.update_member(c["id"], m1["id"], "active")
    assert exc.value.status_code == 409
    # DELETE withdraws softly, never hard-deletes
    svc.remove_member(c["id"], m2["id"])
    rows = svc.list_members(c["id"])
    assert len(rows) == 2
    assert {r["enrollment_status"] for r in rows} == {"withdrawn"}
    # Unknown member transitions 404
    with pytest.raises(HTTPException) as exc:
        svc.update_member(c["id"], "missing", "completed")
    assert exc.value.status_code == 404


def test_member_retrieval_filters(db):
    c = _cohort(db)
    m1 = svc.add_member(c["id"], U1)
    svc.add_member(c["id"], U2)
    svc.update_member(c["id"], m1["id"], "completed")
    assert [m["user_id"] for m in svc.list_members(c["id"], enrollment_status="active")] == [U2]
    assert len(svc.list_members(c["id"])) == 2


# ---------------------------------------------------------------------------
# Supply fixtures: 5 active members, mixed evidence
# ---------------------------------------------------------------------------

def _supply_cohort(db):
    c = _cohort(db, status="active")
    for u in (U1, U2, U3, U4, U5):
        svc.add_member(c["id"], u)
    _seed_signals(db, [
        _sig(U1, SKILL_REACT, "github", 0.70),
        _sig(U1, SKILL_REACT, "project", 0.60),
        _sig(U2, SKILL_REACT, "assessment", 0.85),
        _sig(U3, SKILL_REACT, "leetcode", 0.70),
        _sig(U4, SKILL_REACT, "self_declared", 0.60),
        _sig(U5, SKILL_REACT, "resume", 0.50),
        _sig(U1, SKILL_PYTHON, "kaggle", 0.75),
        _sig(U2, SKILL_PYTHON, "github", 0.60),
    ])
    _seed_assessments(db, [
        {"user_id": U1, "skill_id": SKILL_PYTHON, "proficiency": 0.72,
         "confidence": 0.66, "evidence_weight": 1.5, "source_diversity": 2, "evidence_count": 3},
    ])
    return c


def _supply_row(supply, slug):
    return next(s for s in supply["skills"] if s["skill"] == slug)


# ---------------------------------------------------------------------------
# 9–10. Canonical reuse + existing skill-state retrieval
# ---------------------------------------------------------------------------

def test_canonical_skills_reused_no_second_taxonomy(db):
    assert not hasattr(svc, "RAW_TAXONOMY")
    assert not hasattr(svc, "SkillDefinition")
    c = _supply_cohort(db)
    supply = svc.get_cohort_skill_supply(c["id"])
    assert {s["skill"] for s in supply["skills"]} == {"react", "python"}
    react = _supply_row(supply, "react")
    assert react["display_name"] == "React" and react["category"] == "Frontend"


def test_existing_skill_state_is_source(db):
    c = _supply_cohort(db)
    supply = svc.get_cohort_skill_supply(c["id"])
    assert supply["provenance"]["member_signal_rows"] == 8
    assert supply["provenance"]["member_assessment_rows"] == 1
    assert supply["provenance"]["supply_type"] == "verified_learner_supply"


# ---------------------------------------------------------------------------
# 11–13. Qualification, coverage
# ---------------------------------------------------------------------------

def test_evidence_qualification_excludes_self_report_only(db):
    c = _supply_cohort(db)
    react = _supply_row(svc.get_cohort_skill_supply(c["id"]), "react")
    # U1 (github+project), U2 (assessment), U3 (leetcode) evidenced;
    # U4 self_declared-only and U5 resume-only are assessed, not evidenced.
    assert react["assessed_member_count"] == 5
    assert react["evidenced_member_count"] == 3
    assert react["skill_coverage"] == pytest.approx(3 / 5)


def test_verified_qualification_requires_assessment(db):
    c = _supply_cohort(db)
    supply = svc.get_cohort_skill_supply(c["id"])
    assert _supply_row(supply, "react")["verified_member_count"] == 1
    assert _supply_row(supply, "react")["verified_coverage"] == pytest.approx(1 / 5)
    assert _supply_row(supply, "python")["verified_member_count"] == 0
    assert _supply_row(supply, "python")["verification_rate"] == 0.0


# ---------------------------------------------------------------------------
# 14–16. Proficiency / evidence / confidence aggregation reuse engine math
# ---------------------------------------------------------------------------

def test_proficiency_aggregation_matches_engine(db):
    c = _supply_cohort(db)
    react = _supply_row(svc.get_cohort_skill_supply(c["id"]), "react")
    u1 = [_sig(U1, SKILL_REACT, "github", 0.70), _sig(U1, SKILL_REACT, "project", 0.60)]
    u2 = [_sig(U2, SKILL_REACT, "assessment", 0.85)]
    u3 = [_sig(U3, SKILL_REACT, "leetcode", 0.70)]
    expected = [engine.proficiency_with_prior(s)[0] for s in (u1, u2, u3)]
    assert react["average_proficiency"] == pytest.approx(sum(expected) / 3, abs=1e-4)
    assert react["median_proficiency"] == pytest.approx(sorted(expected)[1], abs=1e-4)
    assert react["min_proficiency"] == pytest.approx(min(expected), abs=1e-4)
    assert react["max_proficiency"] == pytest.approx(max(expected), abs=1e-4)


def test_evidence_strength_preserved(db):
    c = _supply_cohort(db)
    react = _supply_row(svc.get_cohort_skill_supply(c["id"]), "react")
    assert react["qualifying_signal_count"] == 4  # 2 + 1 + 1
    assert react["source_distribution"] == {
        "assessment": 1, "github": 1, "leetcode": 1,
        "project": 1, "resume": 1, "self_declared": 1,
    }
    assert react["tier_distribution"]["low"] == 2
    assert react["tier_distribution"]["supporting"] == 1
    python = _supply_row(svc.get_cohort_skill_supply(c["id"]), "python")
    assert python["average_evidence_count"] == pytest.approx(3.0)


def test_confidence_aggregation_matches_engine(db):
    c = _supply_cohort(db)
    python = _supply_row(svc.get_cohort_skill_supply(c["id"]), "python")
    u1 = [_sig(U1, SKILL_PYTHON, "kaggle", 0.75)]
    u2 = [_sig(U2, SKILL_PYTHON, "github", 0.60)]
    expected = [engine.confidence_from_signals(s)[0] for s in (u1, u2)]
    assert python["average_confidence"] == pytest.approx(sum(expected) / 2, abs=1e-4)


# ---------------------------------------------------------------------------
# 17–18. Unmapped concepts
# ---------------------------------------------------------------------------

def test_unmapped_concepts_preserved_and_excluded(db):
    c = _supply_cohort(db)
    _seed_signals(db, [_sig(U1, SKILL_UNKNOWN, "github", 0.70),
                       _sig(U2, SKILL_UNKNOWN, "project", 0.50)])
    supply = svc.get_cohort_skill_supply(c["id"])
    assert {s["skill"] for s in supply["skills"]} == {"react", "python"}
    assert supply["unmapped_concepts"] == [
        {"skill_id": SKILL_UNKNOWN, "member_count": 2, "signal_count": 2}]


# ---------------------------------------------------------------------------
# 19–22. Empty / no-evidence / self-only / verified members
# ---------------------------------------------------------------------------

def test_empty_cohort_behavior(db):
    c = _cohort(db)
    supply = svc.get_cohort_skill_supply(c["id"])
    assert supply["member_count"] == 0 and supply["skills"] == []
    assert supply["suppressed"] is False


def test_member_with_no_evidence_counts_in_denominator_only(db):
    c = _cohort(db)
    for u in (U1, U2, U3, U4, U5):
        svc.add_member(c["id"], u)
    _seed_signals(db, [_sig(U1, SKILL_REACT, "github", 0.70)])
    react = _supply_row(svc.get_cohort_skill_supply(c["id"]), "react")
    assert react["assessed_member_count"] == 1
    assert react["evidenced_member_count"] == 1
    assert react["cohort_size"] == 5
    assert react["skill_coverage"] == pytest.approx(1 / 5)


def test_assessment_row_counts_as_evidenced(db):
    c = _cohort(db)
    for u in (U1, U2, U3, U4, U5):
        svc.add_member(c["id"], u)
    _seed_assessments(db, [
        {"user_id": U3, "skill_id": SKILL_SQL, "proficiency": 0.55,
         "confidence": 0.50, "evidence_weight": 1.0, "source_diversity": 1, "evidence_count": 2},
    ])
    sql = _supply_row(svc.get_cohort_skill_supply(c["id"]), "sql")
    assert sql["evidenced_member_count"] == 1
    assert sql["verified_member_count"] == 0
    assert sql["average_proficiency"] == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# 23. Determinism
# ---------------------------------------------------------------------------

def test_deterministic_aggregation(db):
    c = _supply_cohort(db)
    first = svc.get_cohort_skill_supply(c["id"])
    second = svc.get_cohort_skill_supply(c["id"])
    assert first == second


# ---------------------------------------------------------------------------
# 24. Privacy / small cohorts
# ---------------------------------------------------------------------------

def test_small_cohort_suppression(db):
    c = _cohort(db)
    for u in (U1, U2, U3):
        svc.add_member(c["id"], u)
    _seed_signals(db, [_sig(U1, SKILL_REACT, "assessment", 0.90)])
    supply = svc.get_cohort_skill_supply(c["id"])
    assert supply["suppressed"] is True
    assert supply["skills"] == [] and supply["member_count"] == 3
    assert "minimum" in supply["note"].lower()


# ---------------------------------------------------------------------------
# 25–27. Authorization, validation, no leakage
# ---------------------------------------------------------------------------

def test_api_routes_require_auth():
    from app.main import app
    from app.core.security import get_current_user

    targets = [r for r in app.routes if hasattr(r, "path") and (
        r.path.startswith("/api/v1/cohorts") or r.path.endswith("/cohorts")
        or r.path.endswith("/cohort-supply"))]
    assert len(targets) >= 10, [r.path for r in targets]
    for r in targets:
        calls = [d.call for d in r.dependant.dependencies]
        assert get_current_user in calls, r.path


def test_api_validation():
    with pytest.raises(ValidationError):
        schemas.CohortCreate(institution_id=INST_1, course_id=COURSE_1, name="x")
    with pytest.raises(ValidationError):
        schemas.CohortMemberUpdate(enrollment_status="graduated")
    with pytest.raises(ValidationError):
        schemas.CohortUpdate(status="archived_soon")


def test_no_individual_evidence_leakage(db):
    c = _supply_cohort(db)
    supply = svc.get_cohort_skill_supply(c["id"])
    blob = json.dumps(supply)
    for u in (U1, U2, U3, U4, U5):
        assert u not in blob
    assert "signal_value" not in blob and "self_declared" not in json.dumps(supply["skills"][0].get("provenance", {}))


def test_course_cohort_supply_combines_cohorts(db):
    c1 = _cohort(db, name="Batch A")
    c2 = _cohort(db, name="Batch B")
    for u in (U1, U2, U3, U4, U5):
        svc.add_member(c1["id"], u)
    for u in (U3, U4, U5, U6, "user-7"):
        svc.add_member(c2["id"], u)
    _seed_signals(db, [_sig(U1, SKILL_REACT, "github", 0.70),
                       _sig(U6, SKILL_REACT, "assessment", 0.80)])
    combined = svc.get_course_cohort_supply(COURSE_1)
    assert combined["member_count"] == 7  # U3/U4/U5 deduped
    assert len(combined["cohorts"]) == 2
    react = next(s for s in combined["skills"] if s["skill"] == "react")
    assert react["evidenced_member_count"] == 2
    assert react["verified_member_count"] == 1


# ---------------------------------------------------------------------------
# RLS regression (static migration-text assertions)
# ---------------------------------------------------------------------------

def _migration_text() -> str:
    base = Path(__file__).resolve().parents[1] / "supabase"
    names = sorted(p.name for p in base.glob("032*.sql"))
    assert len(names) == 1, f"expected exactly one 032 migration, found {names}"
    return (base / names[0]).read_text()


def test_rls_reference_model_no_recursion():
    text = _migration_text()
    lower = text.lower()
    assert "enable row level security" in lower
    assert "revoke all" in lower
    for line in text.splitlines():
        s = line.strip().lower()
        if s.startswith("grant ") and " to " in s:
            assert "anon" not in s.split(" to ", 1)[1], f"anon grant: {line}"
    in_policy = False
    for line in text.splitlines():
        s = line.strip().lower()
        if s.startswith("create policy"):
            in_policy = True
        elif in_policy and (s.startswith("revoke all") or s.startswith("grant ")):
            in_policy = False
        if in_policy:
            assert "exists (select" not in s and " join " not in s, f"recursive-looking policy: {line}"
    assert "to authenticated" in lower and "to service_role" in lower


def test_migration_numbering_intact():
    base = Path(__file__).resolve().parents[1] / "supabase"
    names = sorted(p.name for p in base.glob("*.sql"))
    assert "031_institution_course_supply.sql" in names
    assert "032_cohort_skill_supply.sql" in names
    assert "033_curriculum_proposal_reviews.sql" in names
    assert not list(base.glob("034*.sql"))


# ---------------------------------------------------------------------------
# Demo seed
# ---------------------------------------------------------------------------

def _seed_p0_2_demo(db):
    db.tables["institutions"].append({"id": "demo-inst", "code": "INAURA-DEMO-TC",
                                      "name": "INAURA Demo Skill Training Centre"})
    db.tables["courses"].append({"id": "demo-course", "institution_id": "demo-inst",
                                 "code": "DEMO-FSWD", "name": "Full Stack Web Development"})


def test_deterministic_demo_seed(db):
    assert svc.build_demo_seed() == svc.build_demo_seed()
    seed = svc.build_demo_seed()
    assert seed["cohort"]["code"] == "DEMO-FSWD-2026A"
    assert seed["member_ns"] == [1, 2, 3, 4, 5, 6]
    assert len(seed["signals"]) == 16
    assert all(s["metadata"].get("demo_seeded") for s in seed["signals"])
    # Evidence semantics preserved: same skills/sources/values, no assessments.
    assert {s["skill_slug"] for s in seed["signals"]} == {"react", "python", "sql"}
    assert {s["source_type"] for s in seed["signals"]} >= {
        "github", "project", "assessment", "leetcode", "self_declared", "resume",
        "kaggle", "certification",
    }


def test_demo_seed_requires_p0_2_demo(db):
    # P0#2 demo institution/course absent in this fixture
    with pytest.raises(HTTPException) as exc:
        svc.seed_demo_data()
    assert exc.value.status_code == 404


def test_demo_seed_end_to_end(db):
    _seed_p0_2_demo(db)
    first = svc.seed_demo_data()
    assert first["created"] == {"auth_users": 6, "cohorts": 1, "members": 6, "signals": 16}
    assert first["skipped"] == {"auth_users": 0, "cohorts": 0, "members": 0, "signals": 0}
    assert first["data_origin"] == "demo_seeded"
    second = svc.seed_demo_data()
    assert second["created"] == {"auth_users": 0, "cohorts": 0, "members": 0, "signals": 0}
    assert second["skipped"] == {"auth_users": 6, "cohorts": 1, "members": 6, "signals": 16}

    supply = svc.get_cohort_skill_supply(first["cohort_id"])
    assert supply["suppressed"] is False and supply["member_count"] == 6
    react = next(s for s in supply["skills"] if s["skill"] == "react")
    assert react["assessed_member_count"] == 6
    assert react["evidenced_member_count"] == 4
    assert react["verified_member_count"] == 2
    assert react["skill_coverage"] == pytest.approx(4 / 6, abs=1e-4)
    assert set(react["source_distribution"]) >= {"github", "assessment", "self_declared"}
    python = next(s for s in supply["skills"] if s["skill"] == "python")
    assert python["evidenced_member_count"] == 4 and python["verified_member_count"] == 1


def test_demo_auth_user_creation_uses_reserved_emails_and_marker(db):
    _seed_p0_2_demo(db)
    svc.seed_demo_data()
    admin = db.auth.admin
    assert len(admin.create_calls) == 6
    seen = set()
    for call in admin.create_calls:
        email = str(call.get("email"))
        assert email.startswith("demo-student-") and email.endswith("@demo.invalid")
        assert ".invalid" in email and "example" not in email
        assert call.get("email_confirm") is True
        assert "password" not in call, "demo seed must not set/hardcode passwords"
        meta = call.get("user_metadata") or {}
        assert meta.get("demo_seeded") is True
        assert meta.get("demo_student_n") in (1, 2, 3, 4, 5, 6)
        seen.add(email)
    assert seen == {f"demo-student-{n}@demo.invalid" for n in range(1, 7)}


def test_previously_existing_demo_auth_user_is_reused(db):
    _seed_p0_2_demo(db)
    pre = FakeAuthUser(id="pre-existing-uuid-0001", email="demo-student-1@demo.invalid",
                       user_metadata={"demo_seeded": True, "demo_student_n": 1})
    db.auth.admin.users_by_email["demo-student-1@demo.invalid"] = pre
    out = svc.seed_demo_data()
    assert out["created"]["auth_users"] == 5
    assert out["skipped"]["auth_users"] == 1
    members = db.tables["cohort_members"]
    assert "pre-existing-uuid-0001" in {m["user_id"] for m in members}
    # No duplicate for the pre-existing email.
    assert sum(1 for c in db.auth.admin.create_calls
               if str(c.get("email")).lower() == "demo-student-1@demo.invalid") == 0


def test_seed_does_not_create_duplicate_auth_users_on_rerun(db):
    _seed_p0_2_demo(db)
    first = svc.seed_demo_data()
    n_users_after_first = len(db.auth.admin.users_by_email)
    assert n_users_after_first == 6
    calls_after_first = len(db.auth.admin.create_calls)
    second = svc.seed_demo_data()
    assert len(db.auth.admin.users_by_email) == n_users_after_first
    assert len(db.auth.admin.create_calls) == calls_after_first
    assert second["created"]["auth_users"] == 0
    assert second["skipped"]["auth_users"] == 6
    assert first["cohort_id"] == second["cohort_id"]


def test_cohort_members_use_actual_auth_user_ids(db):
    _seed_p0_2_demo(db)
    svc.seed_demo_data()
    auth_ids = {u.id for u in db.auth.admin.users_by_email.values()}
    member_ids = {m["user_id"] for m in db.tables["cohort_members"]}
    assert len(member_ids) == 6
    assert member_ids <= auth_ids
    # Signal rows use the same real Auth UUIDs.
    signal_ids = {s["user_id"] for s in db.tables.get("skill_signals", [])}
    assert signal_ids <= auth_ids
    assert signal_ids == member_ids


def test_existing_cohort_from_partial_seed_is_completed(db):
    _seed_p0_2_demo(db)
    # Simulate the failed previous run: cohort exists, members/signals missing.
    db.tables.setdefault("cohorts", []).append({
        "id": "partial-cohort-id",
        "institution_id": "demo-inst",
        "course_id": "demo-course",
        "name": "Full Stack Web Development — Batch 2026-A",
        "code": "DEMO-FSWD-2026A",
        "status": "active",
        "data_origin": "demo_seeded",
    })
    out = svc.seed_demo_data()
    assert out["cohort_id"] == "partial-cohort-id"
    assert out["created"]["cohorts"] == 0
    assert out["skipped"]["cohorts"] == 1
    assert out["created"]["members"] == 6
    assert out["created"]["signals"] == 16
    assert len([c for c in db.tables["cohorts"] if c.get("code") == "DEMO-FSWD-2026A"]) == 1


def test_partial_auth_users_only_missing_are_created(db):
    _seed_p0_2_demo(db)
    for n in (1, 2, 3):
        email = f"demo-student-{n}@demo.invalid"
        db.auth.admin.users_by_email[email] = FakeAuthUser(
            id=f"kept-uuid-{n}", email=email,
            user_metadata={"demo_seeded": True, "demo_student_n": n})
    out = svc.seed_demo_data()
    assert out["created"]["auth_users"] == 3
    assert out["skipped"]["auth_users"] == 3
    member_ids = {m["user_id"] for m in db.tables["cohort_members"]}
    assert {"kept-uuid-1", "kept-uuid-2", "kept-uuid-3"} <= member_ids


def test_sixteen_signals_inserted_with_evidence_semantics(db):
    from app.services.evidence_weights import SOURCE_RELIABILITY

    _seed_p0_2_demo(db)
    svc.seed_demo_data()
    rows = db.tables.get("skill_signals", [])
    assert len(rows) == 16
    seed = svc.build_demo_seed()
    for sig in seed["signals"]:
        assert sig["source_reliability"] == SOURCE_RELIABILITY[sig["source_type"]]
        assert sig["metadata"].get("demo_seeded") is True
    for r in rows:
        assert r["metadata"].get("demo_seeded") is True
        assert r["explanation"].startswith("Synthetic demo evidence")
        assert r["source_reliability"] == SOURCE_RELIABILITY[r["source_type"]]
    # No fabricated assessment rows.
    assert db.tables.get("skill_assessments", []) == []


def test_real_users_never_touched(db):
    _seed_p0_2_demo(db)
    real = FakeAuthUser(id="real-user-uuid-1", email="real.person@example.com",
                        user_metadata={})
    db.auth.admin.users_by_email["real.person@example.com"] = real
    n_before = len(db.auth.admin.users_by_email)
    svc.seed_demo_data()
    assert db.auth.admin.users_by_email["real.person@example.com"].id == "real-user-uuid-1"
    assert len(db.auth.admin.users_by_email) == n_before + 6
    member_ids = {m["user_id"] for m in db.tables["cohort_members"]}
    signal_ids = {s["user_id"] for s in db.tables.get("skill_signals", [])}
    assert "real-user-uuid-1" not in member_ids
    assert "real-user-uuid-1" not in signal_ids


def test_demo_auth_race_duplicate_reuses_existing(db):
    _seed_p0_2_demo(db)

    admin = db.auth.admin
    real_create = admin.create_user
    seen = {"count": 0}

    def flaky_create(attributes):
        email = str(attributes.get("email") or "").lower()
        if email == "demo-student-2@demo.invalid" and seen["count"] == 0:
            seen["count"] += 1
            # Simulate a concurrent seed having created the user first.
            existing = FakeAuthUser(id="race-winner-uuid", email=attributes["email"],
                                    user_metadata={"demo_seeded": True, "demo_student_n": 2})
            admin.users_by_email[email] = existing
            raise Exception("User already exists")
        return real_create(attributes)

    admin.create_user = flaky_create
    out = svc.seed_demo_data()
    assert out["created"]["members"] == 6
    assert "race-winner-uuid" in {m["user_id"] for m in db.tables["cohort_members"]}


# ---------------------------------------------------------------------------
# 28–29. P0 #1 + P0 #2 regression
# ---------------------------------------------------------------------------

def test_p0_1_labour_market_unchanged():
    from app.services import labour_market_service as lm
    from app.services import industry_intelligence as intel

    assert lm.calculate_demand(100, 45) == {"skill_share": 0.45, "demand": 0.45}
    demo = lm.DemoPostingProvider()
    assert demo.is_live is False and demo.data_origin == "demo_seeded"
    assert any(p["provider_id"] == "inaura_demo_seed_v1" for p in intel.list_providers())
    base = Path(__file__).resolve().parents[1] / "supabase"
    assert (base / "030_labour_market_intelligence.sql").exists()


def test_p0_2_institution_supply_unchanged():
    from app.services import institution_service as inst

    assert inst.resolve_skill("React.js")["canonical_skill_slug"] == "react"
    seed = inst.build_demo_seed()
    assert seed["institution"]["code"] == "INAURA-DEMO-TC"
    assert [c["code"] for c in seed["courses"]] == ["DEMO-FSWD", "DEMO-MAD", "DEMO-DA"]
    base = Path(__file__).resolve().parents[1] / "supabase"
    assert (base / "031_institution_course_supply.sql").exists()
