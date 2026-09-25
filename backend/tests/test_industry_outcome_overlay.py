"""Phase 3C/3D/3E tests: overlay merge, emerging isolation, retrieval paths.

- flag OFF default: no overlay keys, build_overlay never called
- flag ON: overlay on curated rows only, curated values byte-identical
- failure fallback: curated rows unchanged
- build_requirements_map drops overlay keys (structural proof)
- emerging: non-curated only, status fixed, never in req_map
- retrieval: shared enrichment carries overlay on both paths
"""

import pytest
from unittest.mock import patch, MagicMock

from app.core.config import get_settings
from app.services import industry_service
from app.services import industry_outcome_service as ios
from app.services import analysis_run_service as ars


@pytest.fixture
def flag_off():
    s = get_settings()
    prev = s.outcome_overlay_enabled
    s.outcome_overlay_enabled = False
    yield
    s.outcome_overlay_enabled = prev


@pytest.fixture
def flag_on():
    s = get_settings()
    prev = s.outcome_overlay_enabled
    s.outcome_overlay_enabled = True
    yield
    s.outcome_overlay_enabled = prev


def _rows():
    return [
        {"role": "Software Engineer", "skill": "PostgreSQL", "skill_category": "Databases",
         "required_level": 0.7, "importance": 0.8, "demand": 0.75,
         "interview_relevance": 0.6, "industry_confidence": 0.9, "source_quality": 0.9,
         "source": "O*NET 15-1252", "evidence_strength": "strong"},
        {"role": "Software Engineer", "skill": "Python", "skill_category": "Programming",
         "required_level": 0.8, "importance": 0.9, "demand": 0.9,
         "interview_relevance": 0.8, "industry_confidence": 0.9, "source_quality": 0.9,
         "source": "O*NET 15-1252", "evidence_strength": "strong"},
    ]


def _overlay(skill="PostgreSQL"):
    return {
        "observed_demand": 0.6, "observed_skill_gap": 0.2,
        "outcome_sample": {"requirements_n": 4, "applied_n": 8, "feedback_count": 6},
        "outcome_window": {"window_from": "2026-06-01", "window_to": "2026-09-01",
                           "basis": "applied_at for counts; feedback created_at for gap"},
        "outcome_provenance": {"signal_version": "industry-outcome-signal-v1",
                               "scope": "role", "location": "GLOBAL",
                               "role": "Software Engineer", "skill": skill},
        "stale": False,
    }


def test_flag_defaults_off():
    # Fresh Settings (not the cached singleton) must default OFF.
    from app.core.config import Settings
    assert Settings().outcome_overlay_enabled is False


def test_merge_skipped_when_flag_off(flag_off):
    with patch.object(ios, "build_overlay") as bo:
        out = industry_service._attach_outcome_overlays(_rows(), "Software Engineer")
    bo.assert_not_called()
    assert all("outcome_overlay" not in r for r in out)


def test_merge_attaches_only_matching_curated_row(flag_on):
    def fake_overlay(role, skill):
        return _overlay(skill) if skill == "PostgreSQL" else None

    with patch.object(ios, "build_overlay", side_effect=fake_overlay):
        out = industry_service._attach_outcome_overlays(_rows(), "Software Engineer")
    by_skill = {r["skill"]: r for r in out}
    assert by_skill["PostgreSQL"]["outcome_overlay"]["observed_demand"] == 0.6
    assert "outcome_overlay" not in by_skill["Python"]


def test_curated_values_byte_identical_with_overlay(flag_on):
    before = _rows()
    with patch.object(ios, "build_overlay", side_effect=lambda r, s: _overlay(s)):
        out = industry_service._attach_outcome_overlays(before, "Software Engineer")
    for b, a in zip(before, out):
        for k, v in b.items():
            assert a[k] == v, f"curated field {k} changed"


def test_merge_failure_returns_rows_unchanged(flag_on):
    with patch.object(ios, "build_overlay", side_effect=RuntimeError("db down")):
        out = industry_service._attach_outcome_overlays(_rows(), "Software Engineer")
    assert out == _rows()


def test_requirements_map_drops_overlay_keys():
    reqs = [dict(_rows()[0], outcome_overlay=_overlay())]
    m = ars.build_requirements_map(reqs, None)
    assert "outcome_overlay" not in m["PostgreSQL"]
    assert set(m["PostgreSQL"]) == {
        "skill", "category", "required_level", "importance", "demand",
        "interview", "interview_relevance", "industry_confidence",
        "source_quality", "evidence_strength", "published_at", "description",
        "source", "source_url", "source_version", "source_reference",
        "source_occupation", "mapping_version", "retrieved_at",
        "role_relevance", "evidence_context",
    }


def test_build_overlay_returns_none_when_suppressed():
    fake_client = MagicMock()
    with patch.object(ios, "_ensure_client", return_value=fake_client):
        with patch.object(ios, "_latest_rows", return_value=[{
                "min_n_met": False, "observed_demand": 0.9,
                "role": "R", "skill": "S", "scope": "role", "location": "GLOBAL"}]):
            assert ios.build_overlay("R", "S") is None


def test_build_overlay_returns_none_when_table_missing():
    with patch.object(ios, "_ensure_client", side_effect=Exception("nope")):
        assert ios.build_overlay("R", "S") is None


def test_emerging_excludes_curated_and_labels_status():
    rows = [
        {"skill": "Rust", "skill_id": None, "min_n_met": True,
         "observed_demand": 0.5, "observed_skill_gap": 0.3,
         "requirements_n": 3, "applied_n": 8, "feedback_count": 6,
         "window_from": "2026-06-01", "window_to": "2026-09-01",
         "role": "Software Engineer", "scope": "role", "location": "GLOBAL"},
        {"skill": "Python", "skill_id": None, "min_n_met": True,
         "observed_demand": 0.9, "observed_skill_gap": 0.1,
         "requirements_n": 9, "applied_n": 30, "feedback_count": 12,
         "window_from": "2026-06-01", "window_to": "2026-09-01",
         "role": "Software Engineer", "scope": "role", "location": "GLOBAL"},
        {"skill": "Go", "skill_id": None, "min_n_met": False,
         "observed_demand": None, "observed_skill_gap": None,
         "requirements_n": 1, "applied_n": 2, "feedback_count": 1,
         "window_from": "2026-06-01", "window_to": "2026-09-01",
         "role": "Software Engineer", "scope": "role", "location": "GLOBAL"},
    ]
    fake_client = MagicMock()
    with patch.object(ios, "_ensure_client", return_value=fake_client):
        with patch.object(ios, "_latest_rows", return_value=rows):
            out = ios.get_emerging("Software Engineer", None, {"python"})
    assert [e["skill"] for e in out] == ["Rust"]
    assert out[0]["status"] == "observed_not_required"


def test_retrieval_shared_enrichment_carries_overlay():
    from app.services.retrieval_service import _enrich_with_catalog
    item = {"role": "Software Engineer", "skill": "PostgreSQL", "similarity": 0.8}
    index = {("software engineer", "postgresql"):
             dict(_rows()[0], outcome_overlay=_overlay())}
    enriched = _enrich_with_catalog(item, index)
    assert enriched["outcome_overlay"]["observed_demand"] == 0.6
    # curated enrichment still fills gaps
    assert enriched["source"] == "O*NET 15-1252"


def test_retrieval_fallback_rows_pass_overlay_through():
    # Fallback path uses list_by_role rows verbatim: overlay survives iff attached.
    rows = [dict(_rows()[0], outcome_overlay=_overlay())]
    with patch.object(industry_service, "list_by_role", return_value=rows):
        from app.services.retrieval_service import _rank_items
        ranked, _ = _rank_items(rows, "Software Engineer", "postgres database", 5)
    assert ranked[0]["outcome_overlay"]["observed_skill_gap"] == 0.2
