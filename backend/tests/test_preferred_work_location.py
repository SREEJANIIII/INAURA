"""Deterministic regression coverage for the optional career location preference."""

from app.schemas.profile import ProfileCreate, ProfileUpdate
from app.services import analysis_run_service as ars
from app.services import industry_intelligence as intel


def _profile_payload(**overrides):
    payload = {
        "full_name": "Aarav Sharma",
        "college": "INAURA University",
        "degree": "B.Tech",
        "branch": "Computer Science",
        "current_year": "Final Year",
        "graduation_year": 2027,
        "career_interests": ["Software Engineer"],
        "hours_per_week": 10,
    }
    payload.update(overrides)
    return payload


def test_profile_location_is_optional_and_backward_compatible():
    profile = ProfileCreate(**_profile_payload())
    assert profile.preferred_work_location is None
    located = ProfileCreate(**_profile_payload(preferred_work_location="Bengaluru, Karnataka, India"))
    assert located.preferred_work_location == "Bengaluru, Karnataka, India"


def test_profile_location_can_be_cleared():
    assert ProfileUpdate(preferred_work_location="").preferred_work_location == ""


def test_analysis_requirement_load_passes_preferred_location(monkeypatch):
    observed = {}

    def build_role_intelligence(role, location=None):
        observed["role"] = role
        observed["location"] = location
        return {"skills": [{"skill": "Python", "mapping_status": "mapped"}], "role": role}

    monkeypatch.setattr(intel, "build_role_intelligence", build_role_intelligence)
    monkeypatch.setattr(intel, "to_gap_engine_requirements", lambda view: [{"skill": "Python", "required_level": 0.75}])
    requirements = ars.load_industry_requirements("Software Engineer", "Bengaluru, Karnataka, India")
    assert requirements[0]["skill"] == "Python"
    assert observed == {"role": "Software Engineer", "location": "Bengaluru, Karnataka, India"}
