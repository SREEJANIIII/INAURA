"""Tests for Person 2 Step 5: Outcome Aggregation -> industry-outcome-signal-v1.

Verifies:
1. Exact 14-key contract schema & zero PII in responses.
2. Time window handling, defaults, ISO parsing, and 400 error on invalid/inverted windows.
3. Distinct requirements count (requirements_n).
4. Application counts (applied_n): excludes saved-only (null applied_at); includes withdrawn and rejected.
5. Funnel counts: interview_count (interview, offer_received, selected), selection_count (selected).
6. Placement counts: linked joined only; unlinked and non-joined excluded.
7. Feedback count: unique employer_feedback records (no double-counting from skill feedback).
8. Role signal suppression gates: applied_n >= 10 and feedback_count >= 5.
9. Skill signal demand formula: requesting_requirements / requirements_n.
10. Skill signal gap formula: mean(expected_level - observed_level); preserves negative gaps.
11. Skill signal suppression gates: applied_n >= 5 and feedback_count >= 5.
12. Skill resolution: supports canonical name or UUID.
13. Student isolation: prohibited reverse influence (read-only, no touch on student state).
"""

import pytest
from unittest.mock import patch
from fastapi import HTTPException
from app.services import outcome_service as svc
from app.schemas.outcomes import IndustryOutcomeSignal
from app.schemas.industry_outcomes import IndustryOutcomeSignalV1


class Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.filters = []
        self.op = "select"
        self.payload = None

    def select(self, cols="*"):
        self.op = "select"
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals)))
        return self

    def _apply(self, rows):
        filtered = rows
        for kind, col, val in self.filters:
            if kind == "eq":
                filtered = [r for r in filtered if str(r.get(col)) == str(val)]
            elif kind == "in":
                val_set = {str(v) for v in val}
                filtered = [r for r in filtered if str(r.get(col)) in val_set]
        return filtered

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "select":
            return Result(self._apply(rows))
        raise AssertionError(f"unexpected op: {self.op}")


class FakeDB:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return FakeQuery(self, name)


@pytest.fixture
def fdb():
    db = FakeDB()
    db.tables["hiring_requirements"] = []
    db.tables["hiring_requirement_skills"] = []
    db.tables["applications"] = []
    db.tables["employer_feedback"] = []
    db.tables["employer_skill_feedback"] = []
    db.tables["placement_outcomes"] = []
    db.tables["skills"] = [
        {"id": "00000000-0000-0000-0000-000000000001", "canonical_name": "python", "display_name": "Python"},
        {"id": "00000000-0000-0000-0000-000000000002", "canonical_name": "sql", "display_name": "SQL"},
        {"id": "00000000-0000-0000-0000-000000000003", "canonical_name": "docker", "display_name": "Docker"},
    ]
    with patch.object(svc, "get_supabase_client", return_value=db):
        yield db


SKILL_PY = "00000000-0000-0000-0000-000000000001"
SKILL_SQL = "00000000-0000-0000-0000-000000000002"
SKILL_DOCKER = "00000000-0000-0000-0000-000000000003"

CONTRACT_KEYS = {
    "signal_version", "role", "location", "skill", "time_window", "denominators",
    "application_count", "interview_count", "selection_count", "placement_count",
    "feedback_count", "observed_demand", "observed_skill_gap", "min_n_met",
}

FORBIDDEN_PII = {
    "user_id", "student_id", "employer_id", "application_id", "placement_id",
    "feedback_id", "email", "phone", "contact_email", "name", "comment",
    "notes", "overall_comment", "student_notes",
}


# ===========================================================================
# 1. Contract & PII Absence
# ===========================================================================

def test_01_exact_14_key_contract_and_pydantic_validation(fdb):
    sig = svc.get_industry_signals()
    assert set(sig.keys()) == CONTRACT_KEYS
    assert sig["signal_version"] == "industry-outcome-signal-v1"
    # Validate against both Pydantic models
    IndustryOutcomeSignal.model_validate(sig)
    IndustryOutcomeSignalV1.model_validate(sig)


def test_02_zero_pii_in_output(fdb):
    # Seed data with PII in database rows
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "employer_id": "emp-secret", "role_key": "backend", "location": "Bengaluru"}]
    fdb.tables["applications"] = [{"id": "app-1", "student_id": "student-secret", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"}]
    fdb.tables["employer_feedback"] = [{"id": "fb-1", "application_id": "app-1", "created_at": "2026-07-10T00:00:00+00:00", "overall_comment": "Top performer", "contact_email": "hr@secret.com"}]
    fdb.tables["placement_outcomes"] = [{"id": "pl-1", "application_id": "app-1", "status": "joined", "student_id": "student-secret"}]

    sig = svc.get_industry_signals(role="backend")
    for key in sig:
        assert key not in FORBIDDEN_PII
        assert not any(forbidden in str(key).lower() for forbidden in ("user_id", "student_id", "employer_id", "application_id"))

    # Also check stringified payload for forbidden sensitive tokens
    raw_str = str(sig)
    assert "student-secret" not in raw_str
    assert "emp-secret" not in raw_str
    assert "Top performer" not in raw_str
    assert "hr@secret.com" not in raw_str


# ===========================================================================
# 2. Window Parsing & Validation
# ===========================================================================

def test_03_time_window_defaults_and_structure(fdb):
    sig = svc.get_industry_signals(from_s="2026-01-01T00:00:00+00:00", to_s="2026-06-30T00:00:00+00:00")
    tw = sig["time_window"]
    assert tw["from"] == "2026-01-01T00:00:00+00:00"
    assert tw["to"] == "2026-06-30T00:00:00+00:00"
    assert tw["basis"] == "applied_at for counts; feedback created_at for gap"


def test_04_invalid_time_window_raises_400(fdb):
    with pytest.raises(HTTPException) as exc:
        svc.get_industry_signals(from_s="not-a-date")
    assert exc.value.status_code == 400


def test_05_inverted_time_window_raises_400(fdb):
    with pytest.raises(HTTPException) as exc:
        svc.get_industry_signals(from_s="2026-09-01", to_s="2026-06-01")
    assert exc.value.status_code == 400
    assert "Invalid time window" in exc.value.detail


# ===========================================================================
# 3. Requirements, Applications, Funnel & Placement Counts
# ===========================================================================

def test_06_requirements_n_distinct_count(fdb):
    fdb.tables["hiring_requirements"] = [
        {"id": "req-1", "role_key": "backend", "location": "Bengaluru"},
        {"id": "req-2", "role_key": "backend", "location": "Bengaluru"},
        {"id": "req-3", "role_key": "frontend", "location": "Bengaluru"},
    ]
    sig = svc.get_industry_signals(role="backend")
    assert sig["denominators"]["requirements_n"] == 2


def test_07_applied_n_excludes_saved_only(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    fdb.tables["applications"] = [
        {"id": "app-1", "hiring_requirement_id": "req-1", "status": "saved", "applied_at": None},
        {"id": "app-2", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"},
    ]
    sig = svc.get_industry_signals(role="backend")
    assert sig["denominators"]["applied_n"] == 1
    assert sig["application_count"] == 1


def test_08_applied_n_includes_withdrawn_and_rejected(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    fdb.tables["applications"] = [
        {"id": "app-1", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"},
        {"id": "app-2", "hiring_requirement_id": "req-1", "status": "withdrawn", "applied_at": "2026-07-02T00:00:00+00:00"},
        {"id": "app-3", "hiring_requirement_id": "req-1", "status": "rejected", "applied_at": "2026-07-03T00:00:00+00:00"},
    ]
    sig = svc.get_industry_signals(role="backend")
    assert sig["denominators"]["applied_n"] == 3
    assert sig["application_count"] == 3


def test_09_funnel_counts_interview_and_selected(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    fdb.tables["applications"] = [
        {"id": "app-1", "hiring_requirement_id": "req-1", "status": "screening", "applied_at": "2026-07-01T00:00:00+00:00"},
        {"id": "app-2", "hiring_requirement_id": "req-1", "status": "interview", "applied_at": "2026-07-02T00:00:00+00:00"},
        {"id": "app-3", "hiring_requirement_id": "req-1", "status": "offer_received", "applied_at": "2026-07-03T00:00:00+00:00"},
        {"id": "app-4", "hiring_requirement_id": "req-1", "status": "selected", "applied_at": "2026-07-04T00:00:00+00:00"},
    ]
    sig = svc.get_industry_signals(role="backend")
    assert sig["interview_count"] == 3  # interview, offer_received, selected
    assert sig["selection_count"] == 1  # selected only


def test_10_placement_count_only_linked_and_joined(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    fdb.tables["applications"] = [
        {"id": "app-1", "hiring_requirement_id": "req-1", "status": "selected", "applied_at": "2026-07-01T00:00:00+00:00"},
        {"id": "app-2", "hiring_requirement_id": "req-1", "status": "selected", "applied_at": "2026-07-02T00:00:00+00:00"},
    ]
    fdb.tables["placement_outcomes"] = [
        # Linked and joined -> MUST COUNT
        {"id": "pl-1", "application_id": "app-1", "status": "joined"},
        # Linked but NOT joined -> MUST NOT COUNT
        {"id": "pl-2", "application_id": "app-2", "status": "placed"},
        # Unlinked and joined -> MUST NOT COUNT
        {"id": "pl-3", "application_id": None, "employer_id": "emp-1", "status": "joined"},
    ]
    sig = svc.get_industry_signals(role="backend")
    assert sig["placement_count"] == 1


def test_11_feedback_count_unique_records(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    fdb.tables["applications"] = [
        {"id": "app-1", "hiring_requirement_id": "req-1", "status": "interview", "applied_at": "2026-07-01T00:00:00+00:00"},
    ]
    fdb.tables["employer_feedback"] = [
        {"id": "fb-1", "application_id": "app-1", "created_at": "2026-07-05T00:00:00+00:00"},
    ]
    # Multiple skill feedback rows under the SAME employer feedback
    fdb.tables["employer_skill_feedback"] = [
        {"id": "sfb-1", "employer_feedback_id": "fb-1", "skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": 0.6},
        {"id": "sfb-2", "employer_feedback_id": "fb-1", "skill_id": SKILL_SQL, "expected_level": 0.7, "observed_level": 0.7},
    ]
    sig = svc.get_industry_signals(role="backend")
    assert sig["feedback_count"] == 1  # 1 unique feedback record, not 2


# ===========================================================================
# 4. Role Suppression Gates
# ===========================================================================

def test_12_role_min_n_suppression_when_applied_below_10(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    # 9 applications (needs 10)
    fdb.tables["applications"] = [
        {"id": f"app-{i}", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"}
        for i in range(9)
    ]
    # 6 feedbacks (>= 5)
    fdb.tables["employer_feedback"] = [
        {"id": f"fb-{i}", "application_id": f"app-{i}", "created_at": "2026-07-05T00:00:00+00:00"}
        for i in range(6)
    ]
    fdb.tables["employer_skill_feedback"] = [
        {"id": f"sfb-{i}", "employer_feedback_id": f"fb-{i}", "expected_level": 0.8, "observed_level": 0.6}
        for i in range(6)
    ]
    sig = svc.get_industry_signals(role="backend")
    assert sig["min_n_met"] is False
    assert sig["observed_demand"] is None
    assert sig["observed_skill_gap"] is None
    assert sig["application_count"] == 9
    assert sig["feedback_count"] == 6


def test_13_role_min_n_suppression_when_feedback_below_5(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    # 12 applications (>= 10)
    fdb.tables["applications"] = [
        {"id": f"app-{i}", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"}
        for i in range(12)
    ]
    # Only 4 feedbacks (needs 5)
    fdb.tables["employer_feedback"] = [
        {"id": f"fb-{i}", "application_id": f"app-{i}", "created_at": "2026-07-05T00:00:00+00:00"}
        for i in range(4)
    ]
    sig = svc.get_industry_signals(role="backend")
    assert sig["min_n_met"] is False
    assert sig["observed_demand"] is None
    assert sig["observed_skill_gap"] is None
    assert sig["application_count"] == 12
    assert sig["feedback_count"] == 4


def test_14_role_min_n_met_when_thresholds_satisfied(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    # 10 applications (>= 10)
    fdb.tables["applications"] = [
        {"id": f"app-{i}", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"}
        for i in range(10)
    ]
    # 5 feedbacks (>= 5) with expected 0.8, observed 0.6 -> gap 0.2
    fdb.tables["employer_feedback"] = [
        {"id": f"fb-{i}", "application_id": f"app-{i}", "created_at": "2026-07-05T00:00:00+00:00"}
        for i in range(5)
    ]
    fdb.tables["employer_skill_feedback"] = [
        {"id": f"sfb-{i}", "employer_feedback_id": f"fb-{i}", "expected_level": 0.8, "observed_level": 0.6}
        for i in range(5)
    ]
    sig = svc.get_industry_signals(role="backend")
    assert sig["min_n_met"] is True
    assert sig["observed_skill_gap"] == pytest.approx(0.2, 0.001)


# ===========================================================================
# 5. Skill Signal: Demand, Gap & Thresholds
# ===========================================================================

def test_15_skill_signal_exact_schema_and_keys(fdb):
    sig = svc.get_industry_skill_signal(skill_id=SKILL_PY)
    assert set(sig.keys()) == CONTRACT_KEYS
    assert sig["skill"] == "python" or sig["skill"] == SKILL_PY
    IndustryOutcomeSignal.model_validate(sig)


def test_16_skill_signal_demand_calculation(fdb):
    # 4 requirements total, 3 request Python
    fdb.tables["hiring_requirements"] = [
        {"id": f"req-{i}", "role_key": "backend"} for i in range(1, 5)
    ]
    fdb.tables["hiring_requirement_skills"] = [
        {"hiring_requirement_id": "req-1", "skill_id": SKILL_PY},
        {"hiring_requirement_id": "req-2", "skill_id": SKILL_PY},
        {"hiring_requirement_id": "req-3", "skill_id": SKILL_PY},
        {"hiring_requirement_id": "req-4", "skill_id": SKILL_SQL},
    ]
    # 5 applications, 5 feedbacks to meet sample threshold
    fdb.tables["applications"] = [
        {"id": f"app-{i}", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"}
        for i in range(5)
    ]
    fdb.tables["employer_feedback"] = [
        {"id": f"fb-{i}", "application_id": f"app-{i}", "created_at": "2026-07-05T00:00:00+00:00"}
        for i in range(5)
    ]
    fdb.tables["employer_skill_feedback"] = [
        {"id": f"sfb-{i}", "employer_feedback_id": f"fb-{i}", "skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": 0.6}
        for i in range(5)
    ]
    sig = svc.get_industry_skill_signal(skill_id=SKILL_PY, role="backend")
    assert sig["min_n_met"] is True
    # 3 out of 4 requirements = 0.75
    assert sig["observed_demand"] == pytest.approx(0.75, 0.001)


def test_17_skill_signal_demand_none_when_no_requirements(fdb):
    sig = svc.get_industry_skill_signal(skill_id=SKILL_PY, role="non_existent")
    assert sig["denominators"]["requirements_n"] == 0
    assert sig["observed_demand"] is None


def test_18_skill_signal_gap_mean_calculation(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    fdb.tables["hiring_requirement_skills"] = [{"hiring_requirement_id": "req-1", "skill_id": SKILL_PY}]
    fdb.tables["applications"] = [
        {"id": f"app-{i}", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"}
        for i in range(5)
    ]
    fdb.tables["employer_feedback"] = [
        {"id": f"fb-{i}", "application_id": f"app-{i}", "created_at": "2026-07-05T00:00:00+00:00"}
        for i in range(5)
    ]
    # Gaps: 0.1, 0.2, 0.3, 0.4, 0.5 -> Mean = 0.3
    fdb.tables["employer_skill_feedback"] = [
        {"id": f"sfb-{i}", "employer_feedback_id": f"fb-{i}", "skill_id": SKILL_PY, "expected_level": 0.5 + i * 0.1, "observed_level": 0.4 + i * 0.0}
        for i in range(5)
    ]
    sig = svc.get_industry_skill_signal(skill_id=SKILL_PY, role="backend")
    assert sig["min_n_met"] is True
    assert sig["observed_skill_gap"] == pytest.approx(0.3, 0.001)


def test_19_skill_signal_gap_negative_when_candidate_exceeds(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    fdb.tables["hiring_requirement_skills"] = [{"hiring_requirement_id": "req-1", "skill_id": SKILL_PY}]
    fdb.tables["applications"] = [
        {"id": f"app-{i}", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"}
        for i in range(5)
    ]
    fdb.tables["employer_feedback"] = [
        {"id": f"fb-{i}", "application_id": f"app-{i}", "created_at": "2026-07-05T00:00:00+00:00"}
        for i in range(5)
    ]
    # Expected 0.6, Observed 0.8 -> Gap = -0.2
    fdb.tables["employer_skill_feedback"] = [
        {"id": f"sfb-{i}", "employer_feedback_id": f"fb-{i}", "skill_id": SKILL_PY, "expected_level": 0.6, "observed_level": 0.8}
        for i in range(5)
    ]
    sig = svc.get_industry_skill_signal(skill_id=SKILL_PY, role="backend")
    assert sig["min_n_met"] is True
    assert sig["observed_skill_gap"] == pytest.approx(-0.2, 0.001)


def test_20_skill_signal_suppression_when_applied_below_5(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    fdb.tables["hiring_requirement_skills"] = [{"hiring_requirement_id": "req-1", "skill_id": SKILL_PY}]
    # 4 applications (needs 5)
    fdb.tables["applications"] = [
        {"id": f"app-{i}", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"}
        for i in range(4)
    ]
    fdb.tables["employer_feedback"] = [
        {"id": f"fb-{i}", "application_id": f"app-{i}", "created_at": "2026-07-05T00:00:00+00:00"}
        for i in range(4)
    ]
    fdb.tables["employer_skill_feedback"] = [
        {"id": f"sfb-{i}", "employer_feedback_id": f"fb-{i}", "skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": 0.6}
        for i in range(4)
    ]
    sig = svc.get_industry_skill_signal(skill_id=SKILL_PY, role="backend")
    assert sig["min_n_met"] is False
    assert sig["observed_demand"] is None
    assert sig["observed_skill_gap"] is None


def test_21_skill_signal_suppression_when_feedback_below_5(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    fdb.tables["hiring_requirement_skills"] = [{"hiring_requirement_id": "req-1", "skill_id": SKILL_PY}]
    # 6 applications (>= 5)
    fdb.tables["applications"] = [
        {"id": f"app-{i}", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"}
        for i in range(6)
    ]
    # But only 3 skill feedbacks (needs 5)
    fdb.tables["employer_feedback"] = [
        {"id": f"fb-{i}", "application_id": f"app-{i}", "created_at": "2026-07-05T00:00:00+00:00"}
        for i in range(3)
    ]
    fdb.tables["employer_skill_feedback"] = [
        {"id": f"sfb-{i}", "employer_feedback_id": f"fb-{i}", "skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": 0.6}
        for i in range(3)
    ]
    sig = svc.get_industry_skill_signal(skill_id=SKILL_PY, role="backend")
    assert sig["min_n_met"] is False
    assert sig["observed_demand"] is None
    assert sig["observed_skill_gap"] is None


# ===========================================================================
# 6. Skill Resolution: Canonical Name & UUID
# ===========================================================================

def test_22_skill_resolution_by_canonical_name_or_uuid(fdb):
    fdb.tables["hiring_requirements"] = [{"id": "req-1", "role_key": "backend"}]
    fdb.tables["hiring_requirement_skills"] = [{"hiring_requirement_id": "req-1", "skill_id": SKILL_PY}]
    fdb.tables["applications"] = [
        {"id": f"app-{i}", "hiring_requirement_id": "req-1", "status": "applied", "applied_at": "2026-07-01T00:00:00+00:00"}
        for i in range(5)
    ]
    fdb.tables["employer_feedback"] = [
        {"id": f"fb-{i}", "application_id": f"app-{i}", "created_at": "2026-07-05T00:00:00+00:00"}
        for i in range(5)
    ]
    fdb.tables["employer_skill_feedback"] = [
        {"id": f"sfb-{i}", "employer_feedback_id": f"fb-{i}", "skill_id": SKILL_PY, "expected_level": 0.8, "observed_level": 0.6}
        for i in range(5)
    ]

    # Query using UUID
    sig_uuid = svc.get_industry_skill_signal(skill_id=SKILL_PY, role="backend")
    assert sig_uuid["min_n_met"] is True
    assert sig_uuid["observed_demand"] == 1.0

    # Query using canonical name "python"
    sig_name = svc.get_industry_skill_signal(skill_id="python", role="backend")
    assert sig_name["min_n_met"] is True
    assert sig_name["observed_demand"] == 1.0
    assert sig_name["observed_skill_gap"] == sig_uuid["observed_skill_gap"]


# ===========================================================================
# 7. Student Isolation & Prohibited Reverse Influence
# ===========================================================================

def test_23_student_isolation_no_student_tables_written(fdb):
    initial_tables = {k: list(v) for k, v in fdb.tables.items()}
    # Execute signals
    svc.get_industry_signals(role="backend")
    svc.get_industry_skill_signal(skill_id=SKILL_PY, role="backend")
    # Verify no tables modified
    for table_name, rows in fdb.tables.items():
        assert rows == initial_tables.get(table_name, [])


def test_24_source_integrity_no_student_math_touchpoints():
    import inspect
    sig_src = inspect.getsource(svc.get_industry_signals)
    skill_src = inspect.getsource(svc.get_industry_skill_signal)
    combined = sig_src + "\n" + skill_src

    # Forbidden student mutation touchpoints & DB writes
    for forbidden in (
        "skill_assessments", "skill_gaps", "learner_skill_states",
        "calculate_assessments", "calculate_gaps", "update_learner_state",
    ):
        assert forbidden not in combined, f"Forbidden touchpoint '{forbidden}' found in outcome signals implementation"

    for table in (
        "skill_assessments", "skill_gaps", "learner_skill_states",
        "skill_signals", "industry_requirements", "evidence",
        "assessment_attempts", "applications", "placement_outcomes",
        "employer_feedback", "employer_skill_feedback",
    ):
        for op in (".insert(", ".update(", ".delete(", ".upsert("):
            assert f'"{table}"{op}' not in combined
            assert f"'{table}'{op}" not in combined


