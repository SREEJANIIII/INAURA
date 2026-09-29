"""Synthetic alignment fixture: determinism, idempotency, and outcomes.

Runs the synthetic seed against FakeDB (Auth user creation is stubbed to
deterministic demo UIDs) and then evaluates course_alignment_service
unmodified, asserting every engineered outcome: aligned, curriculum_gap,
attainment_gap, weak_supply, insufficient_data, extra cohort skills,
unmapped exclusion, all four trends, and tiny-cohort suppression — plus
privacy (no synthetic user IDs leak) and isolation (unrelated rows
untouched).
"""

import json
import pytest
from unittest.mock import patch

from app.services import synthetic_alignment_seed as synth
from app.services import institution_service as inst
from app.services import cohort_supply_service as cohort
from app.core import supabase as supabase_core
from app.services import labour_market_service as lm
from app.services import course_alignment_service as align

SKILL_SLUGS = [
    "python", "javascript", "git", "react", "typescript", "html_css",
    "nodejs", "sql", "rest_apis", "docker", "aws", "kubernetes",
    "machine_learning", "java", "cpp",
]

DEMO_UIDS = {n: f"demo-uid-{n}" for n in range(1, 14)}


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
        self._limit = None

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

    def limit(self, n):
        self._limit = n
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
        if self._limit is not None:
            rows = rows[: self._limit]
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
def fdb():
    d = FakeDB()
    d.tables["skills"] = [
        {"id": f"skill-{slug}", "canonical_name": slug,
         "display_name": slug.replace("_", " ").title(), "category": "Test"}
        for slug in SKILL_SLUGS
    ]
    # Unrelated production-looking rows the seed must never touch.
    d.tables["applications"] = [
        {"id": "real-app-1", "student_id": "real-student-1",
         "hiring_requirement_id": "real-req-1", "status": "applied"},
    ]
    d.tables["employers"] = [{"id": "real-emp-1", "name": "Real Corp"}]
    seen: set[int] = set()

    def _fake_auth_user(client, n):
        n = int(n)
        created = n not in seen
        seen.add(n)
        return DEMO_UIDS[n], created

    patches = [
        patch.object(synth, "get_supabase_client", return_value=d),
        patch.object(inst, "get_supabase_client", return_value=d),
        patch.object(cohort, "get_supabase_client", return_value=d),
        # labour_market_service imports the client lazily; patch the source.
        patch.object(supabase_core, "get_supabase_client", return_value=d),
        patch.object(cohort, "_ensure_demo_auth_user", side_effect=_fake_auth_user),
    ]
    for p in patches:
        p.start()
    yield d
    for p in patches:
        p.stop()


def _seed(fdb):
    return synth.seed_synthetic_alignment()


def _align(fdb, **kw):
    course_id = _find_id(fdb, "courses", {"code": synth.SYNTH_COURSE_CODE})
    batch_id = _find_id(fdb, "cohorts", {"code": synth.SYNTH_COHORT_CODE})
    params = {"course_id": course_id, "role": "Software Engineer",
              "country": "India", "region": "Karnataka", "city": "Bengaluru",
              "cohort_id": batch_id}
    params.update(kw)
    return align.get_course_alignment(**params)


def _find_id(fdb, table, filt):
    rows = fdb.tables.get(table, [])
    for r in rows:
        if all(str(r.get(k)) == str(v) for k, v in filt.items()):
            return r["id"]
    raise AssertionError(f"missing {table} {filt}")


def _by_skill(detail):
    return {r["skill"]: r for r in detail["skills"]}


# --- Builder determinism ----------------------------------------------------

def test_seed_builder_is_deterministic():
    assert synth.build_synthetic_seed() == synth.build_synthetic_seed()


# --- Idempotency ------------------------------------------------------------

def test_seed_is_idempotent(fdb):
    first = _seed(fdb)
    sizes_after_first = {t: len(rows) for t, rows in fdb.tables.items()}
    assert first["created"]["institutions"] == 1
    assert first["created"]["courses"] == 1
    assert first["created"]["modules"] == 5
    assert first["created"]["cohorts"] == 2
    assert first["created"]["auth_users"] == 13
    assert first["created"]["members"] == 13
    assert first["created"]["demand"] == 10
    assert first["created"]["signals"] == len(synth.build_synthetic_seed()["signals"])

    second = _seed(fdb)
    assert all(v == 0 for v in second["created"].values())
    assert second["updated"]["demand"] == 0
    assert {t: len(rows) for t, rows in fdb.tables.items()} == sizes_after_first

    third = _seed(fdb)
    assert all(v == 0 for v in third["created"].values())


# --- Graph existence --------------------------------------------------------

def test_synthetic_graph_exists(fdb):
    out = _seed(fdb)
    inst_rows = [r for r in fdb.tables["institutions"] if r.get("code") == "INAURA-SYNTH-INSTITUTE"]
    assert len(inst_rows) == 1
    assert inst_rows[0]["name"] == "INAURA Synthetic Institute"
    assert inst_rows[0]["data_origin"] == "demo_seeded"

    course_rows = [r for r in fdb.tables["courses"] if r.get("code") == "INAURA-SYNTH-FSE"]
    assert len(course_rows) == 1
    assert course_rows[0]["name"] == "Full Stack Engineering — Synthetic 2026"
    assert course_rows[0]["data_origin"] == "demo_seeded"

    mods = [r for r in fdb.tables.get("course_modules", []) if r.get("course_id") == course_rows[0]["id"]]
    assert len(mods) == 5

    for code in ("INAURA-SYNTH-FSE-2026A", "INAURA-SYNTH-FSE-TINY"):
        rows = [r for r in fdb.tables["cohorts"] if r.get("code") == code]
        assert len(rows) == 1
        assert rows[0]["data_origin"] == "demo_seeded"
    assert out["role"] == "Software Engineer"


# --- Learner isolation ------------------------------------------------------

def test_synthetic_users_are_demo_only(fdb):
    _seed(fdb)
    member_uids = {m["user_id"] for m in fdb.tables.get("cohort_members", [])}
    assert member_uids == set(DEMO_UIDS.values())
    signal_uids = {s["user_id"] for s in fdb.tables.get("skill_signals", [])}
    assert signal_uids <= set(DEMO_UIDS.values())
    assert signal_uids, "expected synthetic signals"
    for s in fdb.tables.get("skill_signals", []):
        assert (s.get("metadata") or {}).get("demo_seeded") is True
    for d in fdb.tables.get("labour_market_demand_signals", []):
        assert d["data_origin"] == "demo_seeded"
        assert d["provider_id"] == "inaura_synthetic_market_v1"
    # Unrelated rows untouched.
    assert fdb.tables["applications"] == [
        {"id": "real-app-1", "student_id": "real-student-1",
         "hiring_requirement_id": "real-req-1", "status": "applied"}]
    assert fdb.tables["employers"] == [{"id": "real-emp-1", "name": "Real Corp"}]


# --- Engineered outcomes ----------------------------------------------------

def test_react_is_aligned(fdb):
    _seed(fdb)
    rows = _by_skill(_align(fdb))
    react = rows["react"]
    assert react["alignment"]["curriculum_status"] == "covered"
    assert react["alignment"]["attainment_status"] == "strong"
    assert react["alignment"]["overall_status"] == "aligned"
    assert react["alignment"]["demand_status"] == "rising"


def test_java_is_curriculum_gap(fdb):
    _seed(fdb)
    rows = _by_skill(_align(fdb))
    java = rows["java"]
    assert java["curriculum"] is None
    assert java["alignment"]["curriculum_status"] == "missing"
    assert java["alignment"]["overall_status"] == "curriculum_gap"
    assert java["alignment"]["demand_status"] == "declining"


def test_docker_is_attainment_gap(fdb):
    _seed(fdb)
    rows = _by_skill(_align(fdb))
    docker = rows["docker"]
    assert docker["alignment"]["curriculum_status"] == "weakly_covered"
    assert docker["alignment"]["attainment_status"] == "weak"
    assert docker["alignment"]["overall_status"] == "attainment_gap"


def test_sql_is_weak_supply(fdb):
    _seed(fdb)
    rows = _by_skill(_align(fdb))
    sql = rows["sql"]
    assert sql["alignment"]["attainment_status"] == "moderate"
    assert sql["alignment"]["overall_status"] == "weak_supply"


def test_kubernetes_has_insufficient_market_evidence(fdb):
    _seed(fdb)
    rows = _by_skill(_align(fdb))
    k8s = rows["kubernetes"]
    assert k8s["industry"] is None
    assert k8s["alignment"]["demand_status"] == "insufficient_market_evidence"
    assert k8s["alignment"]["overall_status"] == "insufficient_data"


def test_extra_cohort_skill_and_unmapped_excluded(fdb):
    _seed(fdb)
    detail = _align(fdb)
    assert "cpp" in detail["extra_cohort_skills"]
    assert "java" not in detail["extra_cohort_skills"]  # demanded, not extra
    assert detail["unmapped_excluded"]["course"] >= 1  # Blockchain Basics


def test_demand_trends_cover_all_states(fdb):
    _seed(fdb)
    rows = _by_skill(_align(fdb))
    assert rows["python"]["alignment"]["demand_status"] == "rising"
    assert rows["javascript"]["alignment"]["demand_status"] == "stable"
    assert rows["java"]["alignment"]["demand_status"] == "declining"
    assert rows["machine_learning"]["alignment"]["demand_status"] == "emerging"


def test_tiny_cohort_is_suppressed(fdb):
    _seed(fdb)
    tiny_id = _find_id(fdb, "cohorts", {"code": "INAURA-SYNTH-FSE-TINY"})
    detail = _align(fdb, cohort_id=tiny_id)
    assert detail["cohort_context"]["suppressed"] is True
    assert detail["skills"], "rows still render, all without evidence"
    for row in detail["skills"]:
        assert row["alignment"]["attainment_status"] == "insufficient_evidence"


def test_main_cohort_passes_detail_minimum(fdb):
    _seed(fdb)
    batch_id = _find_id(fdb, "cohorts", {"code": "INAURA-SYNTH-FSE-2026A"})
    detail = _align(fdb, cohort_id=batch_id)
    assert detail["cohort_context"]["suppressed"] is False
    assert detail["cohort_context"]["member_count"] == 10


def test_supabase_rows_normalise_skill_slug(fdb):
    """Regression: persisted demand rows carry canonical_skill_slug (the
    table has no skill_slug column). The fetch layer must restore the
    in-memory shape or course alignment sees zero demand."""
    _seed(fdb)
    rows = lm._fetch_signals_from_supabase()
    assert rows, "expected Supabase-backed demand rows"
    assert all(r.get("skill_slug") for r in rows)
    assert all(r["skill_slug"] == r["canonical_skill_slug"] for r in rows)


# --- Privacy ----------------------------------------------------------------

def test_no_learner_data_leaks(fdb):
    _seed(fdb)
    batch_id = _find_id(fdb, "cohorts", {"code": "INAURA-SYNTH-FSE-2026A"})
    blob = json.dumps(_align(fdb, cohort_id=batch_id), default=str)
    for uid in DEMO_UIDS.values():
        assert uid not in blob
    assert "demo.invalid" not in blob
    assert "user_id" not in blob
