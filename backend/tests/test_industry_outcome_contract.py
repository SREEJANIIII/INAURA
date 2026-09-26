"""Phase 3A tests: observation/overlay/emerging/refresh contracts.

- exact key-sets, PII absence, type validation, threshold constants,
  optional-field behavior. No DB needed.
"""

import pytest

from app.schemas import industry_outcomes as S
from app.schemas.industry_outcomes import (
    OutcomeOverlay, ObservationOut, EmergingSkillOut, ObservationRefreshResponse,
    IndustryOutcomeSignalV1,
)
from app.services import industry_outcome_service as ios


def _sample(**kw):
    return {"requirements_n": 4, "applied_n": 8, "feedback_count": 6, **kw}


def _window(**kw):
    return {"window_from": "2026-06-01", "window_to": "2026-09-01",
            "basis": S.TIME_WINDOW_BASIS, **kw}


def _prov(**kw):
    return {"signal_version": S.SIGNAL_VERSION, "scope": "role",
            "location": "GLOBAL", "role": "Software Engineer",
            "skill": "PostgreSQL", **kw}


def test_overlay_exact_key_set():
    o = OutcomeOverlay(observed_demand=0.6, observed_skill_gap=0.2,
                       outcome_sample=_sample(), outcome_window=_window(),
                       outcome_provenance=_prov(), stale=False)
    assert set(o.model_dump()) == {"observed_demand", "observed_skill_gap",
                                   "outcome_sample", "outcome_window",
                                   "outcome_provenance", "stale"}


def test_overlay_metrics_optional_but_sample_window_required():
    o = OutcomeOverlay(outcome_sample=_sample(), outcome_window=_window(),
                       outcome_provenance=_prov())
    assert o.observed_demand is None and o.observed_skill_gap is None
    assert o.stale is False


def test_no_pii_fields_anywhere():
    for cls in (OutcomeOverlay, ObservationOut, EmergingSkillOut,
                IndustryOutcomeSignalV1, ObservationRefreshResponse):
        names = set(cls.model_fields)
        for forbidden in ("user_id", "student_id", "employer_id", "application_id",
                          "email", "comment", "summary", "resume", "feedback_text",
                          "contact_email", "name"):
            assert forbidden not in names, f"{cls.__name__} has {forbidden}"


def test_signal_mirror_matches_live_contract_keys():
    expected = {"signal_version", "role", "location", "skill", "time_window",
                "denominators", "application_count", "interview_count",
                "selection_count", "placement_count", "feedback_count",
                "observed_demand", "observed_skill_gap", "min_n_met"}
    assert set(IndustryOutcomeSignalV1.model_fields) == expected


def test_threshold_constants_are_approved_values():
    assert (S.CITY_MIN_APPLIED, S.CITY_MIN_FEEDBACK) == (5, 5)
    assert (S.ROLE_MIN_APPLIED, S.ROLE_MIN_FEEDBACK) == (10, 5)
    assert (ios.CITY_MIN_APPLIED, ios.CITY_MIN_FEEDBACK) == (5, 5)
    assert (ios.ROLE_MIN_APPLIED, ios.ROLE_MIN_FEEDBACK) == (10, 5)


def test_global_threshold_isolated_and_provisional():
    assert ios.PROVISIONAL_GLOBAL_MIN_APPLIED == 25
    assert ios.PROVISIONAL_GLOBAL_MIN_FEEDBACK == 10
    assert "PROVISIONAL" in ios.__doc__


def test_scope_sentinels_no_null_ambiguity():
    assert S.GLOBAL_LOCATION == "GLOBAL"
    assert set(S.ALLOWED_SCOPES) == {"city", "role", "global"}


def test_emerging_status_fixed():
    e = EmergingSkillOut(skill="Rust", outcome_sample=_sample(),
                         outcome_window=_window())
    assert e.status == "observed_not_required"


def test_location_normalizer_deterministic_no_allowlist():
    assert ios.normalize_location("  new   york ") == "New York"
    assert ios.normalize_location("bengaluru") == "Bengaluru"
    assert ios.normalize_location("") is None
    assert ios.normalize_location(None) is None
    assert ios.normalize_location("   ") is None


def test_window_defaults_trailing_90d_day_snapped():
    f, t = ios._parse_window(None, None)
    assert (t - f).days == 90
    assert (t.hour, t.minute) == (0, 0)
    with pytest.raises(Exception):
        ios._parse_window("2026-09-01", "2026-06-01")
