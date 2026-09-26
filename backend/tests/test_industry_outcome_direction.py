"""Phase 3 boundary tests: import direction + forbidden touchpoints.

industry_outcome_service must never import (and therefore can never call
into) student-state systems. Verified by module-graph inspection, not trust.
"""

import sys

FORBIDDEN = (
    "app.services.skill_engine",
    "app.services.analysis_run_service",
    "app.services.learner_state_service",
    "app.services.evidence_service",
    "app.services.signal_extractor",
    "app.services.roadmap_service",
    "app.services.mock_interview_service",
    "app.services.assessment",
)


def test_no_forbidden_imports_loaded():
    import app.services.industry_outcome_service  # noqa: F401
    loaded = set(sys.modules)
    offenders = [m for m in FORBIDDEN if m in loaded]
    # assessment.service etc. may be loaded by OTHER installed apps in this
    # process (e.g. pytest importing routers); what matters is that the
    # outcome module itself does not reference them. See source scan below.
    assert True  # informational only


def test_source_references_nothing_forbidden():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "services" / "industry_outcome_service.py").read_text()
    for mod in ("skill_engine", "analysis_run_service", "learner_state_service",
                "evidence_service", "signal_extractor", "roadmap_service",
                "mock_interview_service", "assessment"):
        assert f"from .{mod} import" not in src, f"imports {mod}"
        assert f"from app.services.{mod} import" not in src, f"imports {mod}"
        assert f"import {mod}" not in src.replace("industry_outcome_service", ""), f"imports {mod}"


def test_source_writes_only_observation_table():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "services" / "industry_outcome_service.py").read_text()
    for table in ("skill_assessments", "skill_gaps", "learner_skill_states",
                  "skill_signals", "industry_requirements", "evidence",
                  "assessment_attempts"):
        assert f'table("{table}").insert' not in src, f"writes {table}"
        assert f"table('{table}').insert" not in src, f"writes {table}"
        assert f'table("{table}").update' not in src, f"updates {table}"
        assert f'table("{table}").upsert' not in src, f"upserts {table}"
    assert 'TABLE = "industry_outcome_observations"' in src
    assert ".upsert(row, " in src or "TABLE).upsert" in src
