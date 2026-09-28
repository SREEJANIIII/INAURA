"""P0 #2: institution / course / curriculum supply tests.

FakeDB pattern mirrors test_employer_foundation.py (patch
institution_service.get_supabase_client). No live Supabase needed; all logic
is deterministic.
"""

import pytest
from unittest.mock import patch
from fastapi import HTTPException
from pydantic import ValidationError
from pathlib import Path

from app.services import institution_service as svc
from app.schemas import institutions as schemas

SKILL_REACT = "11111111-1111-1111-1111-111111111111"
SKILL_PYTHON = "22222222-2222-2222-2222-222222222222"
SKILL_SQL = "33333333-3333-3333-3333-333333333333"


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


@pytest.fixture
def db():
    d = FakeDB()
    d.tables["skills"] = [
        {"id": SKILL_REACT, "canonical_name": "react", "display_name": "React"},
        {"id": SKILL_PYTHON, "canonical_name": "python", "display_name": "Python"},
        {"id": SKILL_SQL, "canonical_name": "sql", "display_name": "SQL"},
    ]
    p = patch.object(svc, "get_supabase_client", return_value=d)
    p.start()
    yield d
    p.stop()


def _institution(db, **kw):
    base = {"name": "Test Institute", "institution_type": "college",
            "district": "Bengaluru Urban", "state": "Karnataka"}
    base.update(kw)
    return svc.create_institution(base)


def _course(db, inst_id, **kw):
    base = {"name": "Web Development", "status": "active"}
    base.update(kw)
    return svc.create_course(inst_id, base)


# ---------------------------------------------------------------------------
# 1–3. Institution creation / retrieval / filtering
# ---------------------------------------------------------------------------

def test_institution_creation(db):
    inst = _institution(db)
    assert inst["name"] == "Test Institute"
    assert inst["id"] and inst["status"] == "active"


def test_institution_retrieval(db):
    inst = _institution(db)
    assert svc.get_institution(inst["id"])["id"] == inst["id"]
    with pytest.raises(HTTPException) as exc:
        svc.get_institution("missing-id")
    assert exc.value.status_code == 404


def test_institution_filtering(db):
    _institution(db, name="ITI North", institution_type="iti", district="Tumakuru")
    _institution(db, name="Poly South", institution_type="polytechnic", district="Bengaluru Urban")
    assert {i["name"] for i in svc.list_institutions(district="Tumakuru")} == {"ITI North"}
    assert {i["name"] for i in svc.list_institutions(state="Karnataka")} >= {"ITI North", "Poly South"}
    assert [i["name"] for i in svc.list_institutions(institution_type="iti")] == ["ITI North"]
    with pytest.raises(HTTPException) as exc:
        svc.create_institution({"name": "Bad", "institution_type": "kingdom"})
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 4–6. Course creation / retrieval / belonging
# ---------------------------------------------------------------------------

def test_course_creation(db):
    inst = _institution(db)
    course = _course(db, inst["id"])
    assert course["institution_id"] == inst["id"]


def test_course_retrieval(db):
    inst = _institution(db)
    course = _course(db, inst["id"])
    assert svc.get_course(course["id"])["name"] == "Web Development"
    with pytest.raises(HTTPException) as exc:
        svc.get_course("missing-id")
    assert exc.value.status_code == 404


def test_course_belongs_to_institution(db):
    inst_a = _institution(db, name="Inst A")
    inst_b = _institution(db, name="Inst B", district="Mysuru")
    _course(db, inst_a["id"], name="Shared Name")
    names_b = [c["name"] for c in svc.list_courses(inst_b["id"])]
    assert "Shared Name" not in names_b
    with pytest.raises(HTTPException) as exc:
        svc.create_course("missing-inst", {"name": "Ghost Course"})
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 7–8. Module creation / ordering
# ---------------------------------------------------------------------------

def test_module_creation(db):
    inst = _institution(db)
    course = _course(db, inst["id"])
    mod = svc.create_module(course["id"], {"name": "Basics", "sequence": 0})
    assert mod["course_id"] == course["id"]


def test_module_ordering(db):
    inst = _institution(db)
    course = _course(db, inst["id"])
    svc.create_module(course["id"], {"name": "Second", "sequence": 2})
    svc.create_module(course["id"], {"name": "First", "sequence": 1})
    assert [m["name"] for m in svc.list_modules(course["id"])] == ["First", "Second"]
    updated = svc.update_module(
        next(m["id"] for m in svc.list_modules(course["id"]) if m["name"] == "First"),
        {"sequence": 5},
    )
    assert updated["sequence"] == 5


# ---------------------------------------------------------------------------
# 9–13. Skill mapping, canonical resolution, raw + unmapped preservation
# ---------------------------------------------------------------------------

def test_course_skill_mapping(db):
    inst = _institution(db)
    course = _course(db, inst["id"])
    row = svc.attach_course_skill(course["id"], {"source_concept": "ReactJS", "coverage": "intermediate"})
    assert row["mapping_status"] == "mapped" and row["canonical_skill_slug"] == "react"
    assert row["skill_id"] == SKILL_REACT and row["module_id"] is None


def test_module_skill_mapping(db):
    inst = _institution(db)
    course = _course(db, inst["id"])
    mod = svc.create_module(course["id"], {"name": "Frontend", "sequence": 1})
    row = svc.attach_course_skill(course["id"], {"module_id": mod["id"],
                                                 "source_concept": "React", "coverage": "introductory"})
    assert row["module_id"] == mod["id"]


def test_canonical_skill_resolution(db):
    for variant in ("React.js", "ReactJS", "react"):
        r = svc.resolve_skill(variant)
        assert r["mapping_status"] == "mapped" and r["canonical_skill_slug"] == "react", variant
    for variant in ("Flutter", "Flutter development"):
        r = svc.resolve_skill(variant)
        assert r["mapping_status"] == "mapped" and r["canonical_skill_slug"] == "flutter", variant


def test_raw_concept_preservation(db):
    inst = _institution(db)
    course = _course(db, inst["id"])
    row = svc.attach_course_skill(course["id"], {"source_concept": "  React.js  "})
    assert row["source_concept"] == "React.js"


def test_unmapped_concept_preservation(db):
    inst = _institution(db)
    course = _course(db, inst["id"])
    row = svc.attach_course_skill(course["id"], {"source_concept": "Blockchain Basics"})
    assert row["mapping_status"] == "unmapped"
    assert row["canonical_skill_slug"] is None and row["skill_id"] is None
    assert row["source_concept"] == "Blockchain Basics"
    # Unmapped rows are retrievable via the unmapped filter
    assert any(s["source_concept"] == "Blockchain Basics"
               for s in svc.list_course_skills(course["id"], mapping_status="unmapped"))


# ---------------------------------------------------------------------------
# 14–15. Duplicate prevention
# ---------------------------------------------------------------------------

def test_duplicate_course_prevention(db):
    inst = _institution(db)
    _course(db, inst["id"], name="Web Development")
    # Service-level guard (case-insensitive)
    with pytest.raises(HTTPException) as exc:
        _course(db, inst["id"], name="web development")
    assert exc.value.status_code == 409
    # Same name in a different institution is fine
    other = _institution(db, name="Other Inst", district="Mysuru")
    assert _course(db, other["id"], name="Web Development")["name"] == "Web Development"


def test_duplicate_skill_mapping_prevention(db):
    inst = _institution(db)
    course = _course(db, inst["id"])
    svc.attach_course_skill(course["id"], {"source_concept": "React"})
    # Same canonical skill via a different alias still collides
    with pytest.raises(HTTPException) as exc:
        svc.attach_course_skill(course["id"], {"source_concept": "React.js"})
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        svc.attach_course_skill(course["id"], {"source_concept": "Blockchain Basics"})
        svc.attach_course_skill(course["id"], {"source_concept": "blockchain basics"})
    assert exc.value.status_code == 409


def test_remove_skill_mapping(db):
    inst = _institution(db)
    course = _course(db, inst["id"])
    row = svc.attach_course_skill(course["id"], {"source_concept": "React"})
    svc.remove_course_skill(course["id"], row["id"])
    assert svc.list_course_skills(course["id"]) == []
    with pytest.raises(HTTPException) as exc:
        svc.remove_course_skill(course["id"], row["id"])
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 16–17. Trainers
# ---------------------------------------------------------------------------

def test_trainer_creation(db):
    inst = _institution(db)
    tr = svc.create_trainer(inst["id"], {"name": "Asha Rao", "email": "asha@example.test"})
    assert tr["institution_id"] == inst["id"]
    assert [t["name"] for t in svc.list_trainers(inst["id"])] == ["Asha Rao"]


def test_trainer_skill_mapping(db):
    inst = _institution(db)
    tr = svc.create_trainer(inst["id"], {"name": "Asha Rao"})
    row = svc.attach_trainer_skill(tr["id"], {"source_concept": "Python", "proficiency": "advanced"})
    assert row["canonical_skill_slug"] == "python" and row["proficiency"] == "advanced"
    with pytest.raises(HTTPException) as exc:
        svc.attach_trainer_skill(tr["id"], {"source_concept": "Blockchain Basics"})
    assert exc.value.status_code == 400
    svc.remove_trainer_skill(tr["id"], row["id"])
    assert svc.list_trainer_skills(tr["id"]) == []


# ---------------------------------------------------------------------------
# 18. Foreign-key integrity
# ---------------------------------------------------------------------------

def test_foreign_key_integrity(db):
    inst = _institution(db)
    course_a = _course(db, inst["id"], name="Course A")
    course_b = _course(db, inst["id"], name="Course B")
    mod_b = svc.create_module(course_b["id"], {"name": "B Module", "sequence": 1})
    # Module from another course is rejected
    with pytest.raises(HTTPException) as exc:
        svc.attach_course_skill(course_a["id"], {"module_id": mod_b["id"], "source_concept": "React"})
    assert exc.value.status_code == 400
    # Unknown module is rejected
    with pytest.raises(HTTPException) as exc:
        svc.attach_course_skill(course_a["id"], {"module_id": "nope", "source_concept": "React"})
    assert exc.value.status_code == 404
    # Deleting another course's mapping through this course is rejected
    row_b = svc.attach_course_skill(course_b["id"], {"source_concept": "React"})
    with pytest.raises(HTTPException) as exc:
        svc.remove_course_skill(course_a["id"], row_b["id"])
    assert exc.value.status_code == 404
    # Bad coverage is rejected, not stored
    with pytest.raises(HTTPException) as exc:
        svc.attach_course_skill(course_a["id"], {"source_concept": "SQL", "coverage": "expert"})
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 19. RLS / migration-text regression
# ---------------------------------------------------------------------------

def _migration_text() -> str:
    base = Path(__file__).resolve().parents[1] / "supabase"
    names = sorted(p.name for p in base.glob("031*.sql"))
    assert len(names) == 1, f"expected exactly one 031 migration, found {names}"
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
    # Policies must not join other tables (non-recursive by construction)
    in_policy = False
    for line in text.splitlines():
        s = line.strip().lower()
        if s.startswith("create policy"):
            in_policy = True
        elif in_policy and s.startswith("revoke all"):
            in_policy = False
        if in_policy:
            assert "exists (select" not in s and " join " not in s, f"recursive-looking policy: {line}"
    # Authenticated reads only; service_role writes
    assert "to authenticated" in lower and "to service_role" in lower


def test_migration_numbering_does_not_touch_history():
    base = Path(__file__).resolve().parents[1] / "supabase"
    names = sorted(p.name for p in base.glob("*.sql"))
    assert "030_labour_market_intelligence.sql" in names
    assert "031_institution_course_supply.sql" in names
    assert not list(base.glob("034*.sql"))


# ---------------------------------------------------------------------------
# 20. Deterministic demo seed
# ---------------------------------------------------------------------------

def test_deterministic_demo_seed(db):
    assert svc.build_demo_seed() == svc.build_demo_seed()
    first = svc.seed_demo_data()
    assert first["created"]["institutions"] == 1
    assert first["created"]["courses"] == 3
    assert first["data_origin"] == "demo_seeded"
    second = svc.seed_demo_data()
    assert second["created"] == {k: 0 for k in second["created"]}
    assert second["skipped"]["institutions"] == 1
    assert second["skipped"]["courses"] == 3

    inst_id = first["institution_id"]
    courses = {c["code"]: c for c in svc.list_courses(inst_id)}
    assert set(courses) == {"DEMO-FSWD", "DEMO-MAD", "DEMO-DA"}
    fswd = courses["DEMO-FSWD"]
    assert fswd["data_origin"] == "demo_seeded"
    coverage = svc.get_course_coverage(fswd["id"])
    assert coverage["counts"]["modules"] == 5
    slugs = {s["canonical_skill_slug"] for s in
             [sk for m in coverage["modules"] for sk in m["skills"]]}
    assert {"html_css", "javascript", "react", "rest_apis", "nodejs", "sql"} <= slugs
    da = courses["DEMO-DA"]
    da_skills = svc.list_course_skills(da["id"])
    unmapped = [s for s in da_skills if s["mapping_status"] == "unmapped"]
    assert len(unmapped) == 1 and unmapped[0]["source_concept"] == "Blockchain Basics"
    assert unmapped[0]["canonical_skill_slug"] is None


# ---------------------------------------------------------------------------
# Coverage view (Phase 10: which skills does this course teach?)
# ---------------------------------------------------------------------------

def test_course_coverage_view(db):
    inst = _institution(db)
    course = _course(db, inst["id"])
    mod = svc.create_module(course["id"], {"name": "M1", "sequence": 1})
    svc.attach_course_skill(course["id"], {"module_id": mod["id"],
                                           "source_concept": "React", "coverage": "intermediate"})
    svc.attach_course_skill(course["id"], {"source_concept": "Docker", "coverage": "introductory"})
    cov = svc.get_course_coverage(course["id"])
    assert cov["course"]["id"] == course["id"]
    assert cov["counts"] == {"modules": 1, "skills": 2, "mapped": 2, "unmapped": 0}
    assert cov["modules"][0]["skills"][0]["canonical_skill_slug"] == "react"
    assert cov["course_level_skills"][0]["source_concept"] == "Docker"


# ---------------------------------------------------------------------------
# 21. API schema validation
# ---------------------------------------------------------------------------

def test_api_validation():
    with pytest.raises(ValidationError):
        schemas.InstitutionCreate(name="x")  # too short
    with pytest.raises(ValidationError):
        schemas.InstitutionCreate(name="Valid Name", institution_type="kingdom")
    with pytest.raises(ValidationError):
        schemas.CourseSkillCreate(source_concept="React", coverage="expert")
    with pytest.raises(ValidationError):
        schemas.CourseCreate(name="Valid", delivery_mode="telepathy")
    ok = schemas.CourseSkillCreate(source_concept="React", coverage="intermediate")
    assert ok.coverage == "intermediate"


# ---------------------------------------------------------------------------
# 22. Existing labour-market behavior untouched
# ---------------------------------------------------------------------------

def test_labour_market_behavior_unchanged():
    from app.services import labour_market_service as lm
    from app.services import industry_intelligence as intel
    from app.services import skill_engine as engine

    assert lm.calculate_demand(100, 45) == {"skill_share": 0.45, "demand": 0.45}
    demo = lm.DemoPostingProvider()
    assert demo.is_live is False and demo.data_origin == "demo_seeded"
    assert any(p["provider_id"] == "inaura_demo_seed_v1" for p in intel.list_providers())
    # Gap mathematics invariant
    assert engine.gap(0.50, 0.75) == 0.25
    assert engine.gap(0.85, 0.75) == 0.0
    # No second taxonomy introduced
    import app.services.institution_service as inst_svc
    assert not hasattr(inst_svc, "RAW_TAXONOMY")
    assert not hasattr(inst_svc, "SkillDefinition")
