"""
Phase 7: industry requirement trustworthiness tests.

Verifies provenance metadata, evidence-strength tiers, same-source
deduplication, supporting chunk references, honest insufficient-data
behavior, and that analysis results explain WHY a skill is required.
Student scoring formulas are untouched (asserted where relevant).
"""

import asyncio

import pytest

from app.services import industry_service as ind
from app.services import retrieval_service as rs
from app.services import analysis_run_service as ars
from app.services import skill_engine as engine


def _run(coro):
    return asyncio.run(coro)


def _row(role="Backend Developer", skill="Docker", source="Source A", **over):
    base = {
        "role": role,
        "skill": skill,
        "skill_category": "DevOps",
        "required_level": 0.70,
        "importance": 0.85,
        "demand": 0.75,
        "interview_relevance": 0.65,
        "industry_confidence": 0.82,
        "source": source,
        "source_url": "https://example.com/a",
        "source_quality": 0.90,
        "evidence_context": "Containerization evidence context here.",
        "published_at": "2024-05-01",
        "retrieved_at": "2026-01-10T00:00:00Z",
        "description": "Docker containers",
        "role_relevance": "CORE",
        "version": "2026.1",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# 1. Requirement provenance fields present (req 1-3)
# ---------------------------------------------------------------------------

def test_catalog_rows_carry_full_provenance():
    reqs = ind.list_by_role("Backend Developer")
    assert len(reqs) > 0
    for r in reqs:
        for key in ("source", "source_url", "source_quality",
                    "published_at", "retrieved_at", "role",
                    "industry_confidence", "evidence_strength",
                    "supporting_chunks", "duplicate_sources_collapsed"):
            assert key in r, f"missing provenance '{key}' on {r.get('skill')}"
        assert r["evidence_strength"] in ("strong", "moderate", "weak", "insufficient")
        assert isinstance(r["supporting_chunks"], list)
        # No chunk bodies copied into requirements, references only.
        for ref in r["supporting_chunks"]:
            assert set(ref.keys()) <= {"chunk_id", "role", "topic", "source", "source_url"}
            assert "content" not in ref


def test_retrieve_items_carry_provenance_and_chunks():
    result = _run(rs.retrieve("Backend Developer"))
    assert result["count"] > 0
    docker = next(i for i in result["items"] if i["skill"] == "Docker")
    assert docker["source"] and docker["source_quality"] >= 0.70
    assert docker["published_at"] and docker["retrieved_at"]
    assert docker["evidence_strength"] in ("strong", "moderate", "weak")
    assert isinstance(docker["supporting_chunks"], list)
    # chunk-backend-1 mentions Docker: reference must be present.
    assert any(c.get("chunk_id") == "chunk-backend-1" for c in docker["supporting_chunks"])
    # Honest absence: a skill no chunk mentions gets an empty list, not filler.
    assert isinstance(result["items"][0].get("supporting_chunks"), list)


# ---------------------------------------------------------------------------
# 2. Evidence-strength tiers (req 5)
# ---------------------------------------------------------------------------

def test_strength_tiers_unit():
    assert ind.classify_requirement_evidence(0, 0.9, 0.9) == "insufficient"
    assert ind.classify_requirement_evidence(1, 0.60, 0.80) == "weak"
    assert ind.classify_requirement_evidence(1, 0.90, 0.90) == "moderate"
    assert ind.classify_requirement_evidence(2, 0.90, 0.85) == "strong"
    assert ind.classify_requirement_evidence(2, 0.90, 0.65) == "strong"
    assert ind.classify_requirement_evidence(2, 0.90, 0.64) == "moderate"
    assert ind.classify_requirement_evidence(3, 0.75, 0.90) == "moderate"


def test_strong_requires_corroboration_in_aggregation():
    rows = [
        _row(source="Source A", source_quality=0.90, required_level=0.70),
        _row(source="Source B", source_quality=0.90, required_level=0.80),
    ]
    agg = ind.aggregate_requirements(rows)
    assert len(agg) == 1
    assert agg[0]["evidence_strength"] == "strong"
    assert agg[0]["duplicate_sources_collapsed"] == 0
    assert len(agg[0]["supporting_sources"]) == 2


def test_single_solid_source_is_moderate_not_strong():
    agg = ind.aggregate_requirements([_row(source="Only Source", source_quality=0.90)])
    assert agg[0]["evidence_strength"] == "moderate"


# ---------------------------------------------------------------------------
# 3. Duplicate sources cannot stack influence (req 4)
# ---------------------------------------------------------------------------

def test_same_source_duplicates_collapse():
    rows = [
        _row(source="Same Source", source_quality=0.90, required_level=0.70),
        _row(source="same  source", source_quality=0.90, required_level=0.80),
    ]
    agg = ind.aggregate_requirements(rows)
    assert len(agg) == 1
    assert agg[0]["duplicate_sources_collapsed"] == 1
    # Strongest same-source statement wins; no double counting in the average.
    assert agg[0]["required_level"] == pytest.approx(0.80)
    assert len(agg[0]["supporting_sources"]) == 1
    # Identical to the single-row outcome for the winning row.
    single = ind.aggregate_requirements([
        _row(source="Same Source", source_quality=0.90, required_level=0.80),
    ])
    assert agg[0]["required_level"] == pytest.approx(single[0]["required_level"])
    assert agg[0]["importance"] == pytest.approx(single[0]["importance"])


def test_distinct_sources_still_compound():
    rows = [
        _row(source="Source A", source_quality=0.90, required_level=0.80),
        _row(source="Source B", source_quality=0.70, required_level=0.90),
    ]
    agg = ind.aggregate_requirements(rows)
    assert agg[0]["duplicate_sources_collapsed"] == 0
    expected = (0.80 * 0.90 + 0.90 * 0.70) / (0.90 + 0.70)
    assert agg[0]["required_level"] == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# 4. Provenance validator (req 8)
# ---------------------------------------------------------------------------

def test_validator_accepts_complete_provenance():
    assert ind.validate_requirement_provenance(_row()) == []


def test_validator_flags_gaps():
    bad = _row(source="", source_quality=None, published_at="",
               retrieved_at="", evidence_context="short", skill="NotASkill123")
    issues = ind.validate_requirement_provenance(bad)
    for code in ("missing_source", "missing_source_quality",
                 "missing_published_at", "missing_retrieved_at",
                 "missing_evidence_context", "non_canonical_skill"):
        assert code in issues


def test_validator_flags_bad_quality_and_untrusted_source():
    assert "quality_out_of_bounds" in ind.validate_requirement_provenance(
        _row(source_quality=1.5))
    assert "untrusted_source" in ind.validate_requirement_provenance(
        _row(source="placeholder"))
    assert "missing_skill" in ind.validate_requirement_provenance(_row(skill=""))


def test_catalog_rows_validate_clean():
    for r in ind.list_by_role("Backend Developer"):
        assert ind.validate_requirement_provenance(r) == [], r["skill"]


# ---------------------------------------------------------------------------
# 5. No fabrication + insufficient-data preserved (req 6-7)
# ---------------------------------------------------------------------------

def test_custom_role_refusal_preserved():
    result = _run(rs.synthesize_custom_role("Quantum Origami Chef 4000"))
    assert result["status"] == "insufficient_data"
    assert result["requirements"] == []
    assert result["confidence"] == 0.0


def test_synthesized_requirements_carry_evidence():
    result = _run(rs.synthesize_custom_role("AI Engineer"))
    assert result["status"] == "synthesized"
    assert result["skills_count"] >= 3
    for req in result["requirements"]:
        assert req["evidence_strength"] in ("strong", "moderate", "weak")
        assert isinstance(req["supporting_chunks"], list)
        assert ind.validate_requirement_provenance(req) == []
    # At least one requirement cites the chunks behind it.
    assert any(len(req["supporting_chunks"]) > 0 for req in result["requirements"])


# ---------------------------------------------------------------------------
# 6. Analysis results explain WHY a skill is required (req 9)
# ---------------------------------------------------------------------------

def test_requirements_map_threads_trust_fields():
    req_map = ars.build_requirements_map(ind.list_by_role("Backend Developer"), None)
    docker = req_map["Docker"]
    assert docker["source"]
    assert docker["source_quality"] >= 0.70
    assert docker["evidence_strength"] in ("strong", "moderate", "weak")
    assert docker["published_at"]
    assert docker["evidence_context"]


def test_assessment_and_gap_answer_why_required():
    req_map = ars.build_requirements_map(ind.list_by_role("Backend Developer"), None)
    signals = [
        {"skill": "Python", "source": "github", "signal_strength": 0.75,
         "source_reliability": 0.40},
    ]
    grouped = ars.aggregate_skills(signals)
    assessments = {a["canonical_name"]: a for a in ars.calculate_assessments(grouped, req_map, None)}
    gaps = {g["canonical_name"]: g for g in ars.calculate_gaps(list(assessments.values()), "Backend Developer")}
    for view in (assessments["Docker"], gaps["Docker"]):
        assert view["requirement_source"]
        assert view["requirement_evidence_strength"] in ("strong", "moderate", "weak")
        assert view["requirement_source_quality"] >= 0.70
        assert view["evidence_context"]
    # The gap explanation plus requirement provenance jointly answer why
    # Docker is required: human-readable gap text plus source, strength,
    # quality, and evidence context for the requirement itself.
    assert gaps["Docker"]["explanation"]
    assert "Docker" in gaps["Docker"]["explanation"]


def test_scoring_formulas_untouched():
    # Same inputs as the existing aggregation contract: quality-weighted
    # average and confidence compounding are byte-identical.
    rows = [
        _row(source="Source A", source_quality=0.90, required_level=0.80, importance=0.85),
        _row(source="Source B", source_quality=0.70, required_level=0.90, importance=0.95),
    ]
    agg = ind.aggregate_requirements(rows)
    assert agg[0]["required_level"] == pytest.approx((0.80 * 0.90 + 0.90 * 0.70) / 1.60, abs=0.01)
    assert agg[0]["importance"] == pytest.approx((0.85 * 0.90 + 0.95 * 0.70) / 1.60, abs=0.01)
    sigs = [
        {"signal_strength": 0.80, "source_reliability": 0.40},
        {"signal_strength": 0.40, "source_reliability": 0.85},
    ]
    prof, _, _, _ = engine.proficiency(sigs)
    assert prof == pytest.approx((0.80 * 0.40 + 0.40 * 0.85) / 1.25)
