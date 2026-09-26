"""Phase 3F: student-impact release gate (end-to-end at the exact seam).

Simulates: baseline analysis -> Person 2 outcome overlay attached upstream ->
re-run. Asserts student proficiency, confidence, assessment results, and ALL
gap arithmetic fields are byte-identical with the overlay present, proving:

  Employer feedback -> observation -> industry context
  does NOT become Employer feedback -> student proficiency.

Also asserts run_analysis source has no outcome touchpoints (the pipeline
cannot even see the overlay: build_requirements_map drops unknown keys).
"""

import copy

from app.services import analysis_run_service as ars


def _curated():
    return [
        {"role": "Software Engineer", "skill": "PostgreSQL",
         "skill_category": "Databases", "required_level": 0.7,
         "importance": 0.8, "demand": 0.75, "interview_relevance": 0.6,
         "industry_confidence": 0.9, "source_quality": 0.9,
         "source": "O*NET 15-1252", "evidence_strength": "strong"},
        {"role": "Software Engineer", "skill": "Python",
         "skill_category": "Programming", "required_level": 0.8,
         "importance": 0.9, "demand": 0.9, "interview_relevance": 0.8,
         "industry_confidence": 0.9, "source_quality": 0.9,
         "source": "O*NET 15-1252", "evidence_strength": "strong"},
    ]


def _overlayed():
    rows = _curated()
    rows[0] = dict(rows[0], outcome_overlay={
        "observed_demand": 0.95, "observed_skill_gap": 0.9,
        "outcome_sample": {"requirements_n": 9, "applied_n": 40, "feedback_count": 20},
        "outcome_window": {"window_from": "2026-06-01", "window_to": "2026-09-01",
                           "basis": "applied_at for counts; feedback created_at for gap"},
        "outcome_provenance": {"signal_version": "industry-outcome-signal-v1",
                               "scope": "role", "location": "GLOBAL",
                               "role": "Software Engineer", "skill": "PostgreSQL"},
        "stale": False,
    })
    return rows


MATH_FIELDS = ("required_level", "current_proficiency", "confidence", "gap",
               "importance", "demand", "interview_relevance", "priority_score",
               "priority", "industry_confidence")


def _run(requirements):
    req_map = ars.build_requirements_map(requirements, None)
    assessments = ars.calculate_assessments({}, req_map, None, overrides={})
    gaps = ars.calculate_gaps(assessments, "Software Engineer")
    return assessments, gaps


def _math_snapshot(assessments, gaps):
    a = sorted((x["canonical_name"], x["proficiency"], x["confidence"],
                x.get("assessment_score"), x["evidence_count"]) for x in assessments)
    g = sorted((x["canonical_name"],) + tuple(x[f] for f in MATH_FIELDS) for x in gaps)
    return a, g


def test_overlay_leaves_student_state_identical():
    base_a, base_g = _run(_curated())
    over_a, over_g = _run(_overlayed())
    assert _math_snapshot(base_a, base_g) == _math_snapshot(over_a, over_g)


def test_overlay_leaves_state_identical_with_evidence_signals():
    sigs = {"PostgreSQL": [
        {"skill": "PostgreSQL", "canonical_name": "PostgreSQL",
         "source": "github", "source_type": "github",
         "signal_strength": 0.6, "source_reliability": 0.4,
         "metadata": {}}]}
    m1 = ars.build_requirements_map(_curated(), None)
    m2 = ars.build_requirements_map(_overlayed(), None)
    a1 = ars.calculate_assessments(copy.deepcopy(sigs), m1, None, overrides={})
    a2 = ars.calculate_assessments(copy.deepcopy(sigs), m2, None, overrides={})
    g1 = ars.calculate_gaps(a1, "Software Engineer")
    g2 = ars.calculate_gaps(a2, "Software Engineer")
    assert _math_snapshot(a1, g1) == _math_snapshot(a2, g2)
    # proficiency actually reflects evidence (test is non-vacuous)
    pg = next(x for x in a1 if x["canonical_name"] == "PostgreSQL")
    assert pg["proficiency"] > 0


def test_run_analysis_source_has_no_outcome_touchpoints():
    import pathlib
    for name in ("analysis_run_service.py", "skill_engine.py",
                 "roadmap_service.py", "learner_state_service.py",
                 "signal_extractor.py"):
        src = (pathlib.Path(__file__).resolve().parents[1] / "app"
               / "services" / name).read_text()
        assert "outcome_overlay" not in src, f"{name} references overlay"
        assert "industry_outcome" not in src, f"{name} references outcome service"
        assert "observed_demand" not in src, f"{name} references observed fields"


def test_no_new_gap_math_inputs():
    # Gap arithmetic reads exactly these assessment fields; overlay adds none.
    import inspect
    src = inspect.getsource(ars.calculate_gaps)
    for f in MATH_FIELDS:
        assert f in src
    assert "observed_" not in src
    assert "outcome_" not in src
