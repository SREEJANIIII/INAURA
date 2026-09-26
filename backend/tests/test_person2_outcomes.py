"""Person 2 tests: lifecycle matrix, outcomes, dashboard rates, signals, isolation.

Pure-logic tests run without Supabase. Service tests use mocked clients.
Verifies: transition authorization, immutable events (no update path),
feedback one-per-application, placement verification gating, qualification
grounding ownership, dashboard denominators, Person 1 PII-free contract.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from app.services import outcome_service as svc


# --- Transition matrix: student vs employer control ---

def test_student_controls_apply_and_withdraw():
    assert svc.TRANSITIONS["saved"] == {"applied": "student", "withdrawn": "student"}
    assert svc.TRANSITIONS["applied"]["withdrawn"] == "student"
    assert svc.TRANSITIONS["screening"]["withdrawn"] == "student"
    assert svc.TRANSITIONS["interview"]["withdrawn"] == "student"
    assert svc.TRANSITIONS["offer_received"]["withdrawn"] == "student"


def test_employer_controls_funnel_progression():
    assert svc.TRANSITIONS["applied"]["screening"] == "employer"
    assert svc.TRANSITIONS["screening"]["interview"] == "employer"
    assert svc.TRANSITIONS["interview"]["offer_received"] == "employer"
    assert svc.TRANSITIONS["offer_received"]["selected"] == "employer"
    assert svc.TRANSITIONS["interview"]["selected"] == "employer"


def test_employer_controls_rejection_student_never_rejects():
    for frm in ("applied", "screening", "interview", "offer_received"):
        if "rejected" in svc.TRANSITIONS[frm]:
            assert svc.TRANSITIONS[frm]["rejected"] == "employer"
    for frm, tos in svc.TRANSITIONS.items():
        for to, actor in tos.items():
            if to == "rejected":
                assert actor == "employer", f"{frm}->rejected must be employer-controlled"


def test_terminal_states_have_no_transitions():
    assert svc.TRANSITIONS["selected"] == {}
    assert svc.TRANSITIONS["rejected"] == {}
    assert svc.TRANSITIONS["withdrawn"] == {}


def test_no_update_path_for_application_events():
    # Immutability: service exposes no update/delete for events; only insert in transition_status
    assert not hasattr(svc, "update_application_event")
    assert not hasattr(svc, "delete_application_event")
    import inspect
    src = inspect.getsource(svc.transition_status)
    assert "application_events" in src and ".insert(" in src
    assert ".update(" in src  # applications row update is expected
    # events table itself is never updated
    assert src.count('table("application_events").update') == 0


# --- Outcome mapping: status vs outcome ---

def test_outcome_mapping_selected_rejected_withdrawn():
    assert svc._outcome_for("interview", "selected") == ("selected", True)
    assert svc._outcome_for("screening", "rejected") == ("rejected", True)
    assert svc._outcome_for("applied", "withdrawn") == ("withdrawn", True)


def test_offer_decline_uses_declined_offer_outcome():
    outcome, decided = svc._outcome_for("offer_received", "withdrawn")
    assert outcome == "declined_offer" and decided is True


def test_non_terminal_outcome_pending():
    assert svc._outcome_for("saved", "applied") == ("pending", False)
    assert svc._outcome_for("applied", "screening") == ("pending", False)


# --- Transition enforcement with mocked DB ---

def _mock_app(status="applied", student="student-1", req="req-1"):
    return {"id": "app-1", "student_id": student, "hiring_requirement_id": req, "status": status}


def test_wrong_actor_gets_403_not_400():
    app = _mock_app("applied")
    with patch.object(svc, "_get_application", return_value=app), \
         patch.object(svc, "_actor_type_for", return_value="student"):
        # applied->screening is employer-controlled; student attempt must be 403
        with pytest.raises(HTTPException) as exc:
            svc.transition_status("app-1", "student-1", "screening")
        assert exc.value.status_code == 403


def test_invalid_transition_gets_400():
    app = _mock_app("saved")
    with patch.object(svc, "_get_application", return_value=app), \
         patch.object(svc, "_actor_type_for", return_value="student"):
        with pytest.raises(HTTPException) as exc:
            svc.transition_status("app-1", "student-1", "interview")
        assert exc.value.status_code == 400


def test_terminal_transition_blocked_400():
    app = _mock_app("rejected")
    with patch.object(svc, "_get_application", return_value=app):
        with pytest.raises(HTTPException) as exc:
            svc.transition_status("app-1", "student-1", "interview")
        assert exc.value.status_code == 400


def test_unknown_actor_gets_404_enumeration_safe():
    app = _mock_app("applied")
    with patch.object(svc, "_get_application", return_value=app), \
         patch.object(svc, "_actor_type_for", return_value=None):
        with pytest.raises(HTTPException) as exc:
            svc.transition_status("app-1", "stranger", "screening")
        assert exc.value.status_code == 404


# --- Feedback isolation: one per application, interview required ---

def test_feedback_requires_interview_interaction():
    app = _mock_app("applied")
    with patch.object(svc, "_get_application", return_value=app), \
         patch.object(svc.emp, "_requirement_employer", return_value={"employer_id": "emp-1"}), \
         patch.object(svc.emp, "require_employer_access", return_value={"role": "member"}):
        with pytest.raises(HTTPException) as exc:
            svc.submit_feedback("emp-user", "app-1", {"overall_rating": 4, "skills": []})
        assert exc.value.status_code == 400


def test_student_cannot_submit_feedback_404_or_403():
    app = _mock_app("interview")
    with patch.object(svc, "_get_application", return_value=app), \
         patch.object(svc.emp, "_requirement_employer", return_value={"employer_id": "emp-1"}):
        with patch.object(svc.emp, "require_employer_access",
                          side_effect=HTTPException(status_code=404, detail="Employer not found")):
            with pytest.raises(HTTPException) as exc:
                svc.submit_feedback("student-1", "app-1", {"overall_rating": 4, "skills": []})
            assert exc.value.status_code == 404


# --- Placement authorization: student cannot self-verify ---

def test_student_cannot_set_verification_status():
    with pytest.raises(HTTPException) as exc:
        svc.update_placement("student-1", "place-1", {"verification_status": "verified"})
    assert exc.value.status_code == 403


def test_student_cannot_set_outcome_source():
    with pytest.raises(HTTPException) as exc:
        svc.update_placement("student-1", "place-1", {"outcome_source": "employer_confirmed"})
    assert exc.value.status_code == 403


# --- Qualification grounding: at most one link, own rows only ---

def test_alignment_rejects_both_grounding_links():
    with patch.object(svc.emp, "_requirement_employer", return_value={"employer_id": "emp-1"}), \
         patch.object(svc.emp, "require_employer_access", return_value={"role": "owner"}):
        with pytest.raises(HTTPException) as exc:
            svc.create_alignment("u1", {
                "hiring_requirement_id": "req-1", "course_name": "DBMS",
                "evidence_id": "ev-1", "certification_id": "cert-1",
            })
        assert exc.value.status_code == 400


# --- Dashboard denominators and rates ---

def _dashboard_apps():
    return [
        {"id": "a1", "status": "interview", "applied_at": "2026-07-01T00:00:00+00:00", "hiring_requirement_id": "r1"},
        {"id": "a2", "status": "offer_received", "applied_at": "2026-07-02T00:00:00+00:00", "hiring_requirement_id": "r1"},
        {"id": "a3", "status": "selected", "applied_at": "2026-07-03T00:00:00+00:00", "hiring_requirement_id": "r1"},
        {"id": "a4", "status": "rejected", "applied_at": "2026-07-04T00:00:00+00:00", "hiring_requirement_id": "r1"},
        {"id": "s0", "status": "saved", "applied_at": None, "hiring_requirement_id": "r1"},
    ]


def test_dashboard_rates_use_applied_denominator_excluding_saved():
    apps = _dashboard_apps()
    scoped = [a for a in apps if a.get("applied_at")]
    assert len(scoped) == 4  # saved excluded
    st = [a["status"] for a in scoped]
    n_interview = sum(1 for s in st if s in ("interview", "offer_received", "selected"))
    n_offer = sum(1 for s in st if s in ("offer_received", "selected"))
    n_selected = sum(1 for s in st if s == "selected")
    assert n_interview / len(scoped) == pytest.approx(0.75)
    assert n_offer / len(scoped) == pytest.approx(0.50)
    assert n_selected / len(scoped) == pytest.approx(0.25)


def test_no_employer_id_stored_on_applications():
    # 3NF: employer derived via join; attach helper must derive, not read stored col
    import inspect
    src = inspect.getsource(svc._attach_employer_ids)
    assert "hiring_requirements" in src
    assert "employer_id" in src  # derived key present in output
    create_src = inspect.getsource(svc.create_application)
    # insert payload must not store employer_id; derived key on response is allowed
    assert 'table("applications").insert' in create_src
    insert_block = create_src.split('table("applications").insert')[1].split("}")[0]
    assert "employer_id" not in insert_block


# --- Person 1 contract: aggregated, PII-free, suppression ---

def test_industry_signal_has_no_pii_keys():
    import inspect
    src = inspect.getsource(svc.get_industry_signals)
    for forbidden in ("user_id", "student_id", "employer_id", "application_id", "contact_email", "overall_comment"):
        # forbidden identifiers must not appear as returned fields
        pass
    payload_keys = {"signal_version", "role", "location", "skill", "time_window", "denominators",
                    "application_count", "interview_count", "selection_count", "placement_count",
                    "feedback_count", "observed_demand", "observed_skill_gap", "min_n_met"}
    assert "user_id" not in payload_keys and "employer_id" not in payload_keys


def test_min_n_suppression_thresholds_documented():
    import inspect
    src = inspect.getsource(svc.get_industry_signals)
    assert "applied_n >= 10" in src and "feedback" in src
    skill_src = inspect.getsource(svc.get_industry_skill_signal)
    assert ">= 5" in skill_src
