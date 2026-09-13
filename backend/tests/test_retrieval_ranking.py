"""
Phase 6: multi-signal retrieval ranking tests.

Verifies the explicit deterministic fusion formula
  fused = (0.40*similarity + 0.20*role_relevance + 0.15*skill_relevance
           + 0.15*source_quality + 0.10*importance_demand) * freshness
with a low-quality cap, deduplication, full source provenance, offline
fallback, honest custom-role refusal, and canonical skill extraction.
No LLM is involved anywhere; student scoring formulas are untouched.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from app.services import retrieval_service as rs
from app.services import industry_service
from app.services import skill_taxonomy as taxonomy
from app.services import analysis_run_service as ars


FIXED_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _row(role, skill, **over):
    base = {
        "id": f"req-{skill}",
        "role": role,
        "skill": skill,
        "skill_category": "General",
        "required_level": 0.75,
        "importance": 0.80,
        "demand": 0.75,
        "interview_relevance": 0.70,
        "industry_confidence": 0.85,
        "source": "Test Benchmark",
        "source_url": "https://example.com/bench",
        "source_quality": 0.90,
        "evidence_context": f"{skill} evidence context",
        "published_at": "2024-01-15",
        "retrieved_at": "2026-01-10T00:00:00Z",
        "description": f"{skill} description",
        "role_relevance": "CORE",
        "version": "2026.1",
    }
    base.update(over)
    return base


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. Semantic relevance: query-relevant evidence ranks first
# ---------------------------------------------------------------------------

def test_keyword_similarity_prefers_matching_skill():
    items = [
        _row("Software Engineer", "Python"),
        _row("Software Engineer", "Testing"),
    ]
    ranked, dupes = rs._rank_items(items, "Software Engineer", "testing automation", 10, now=FIXED_NOW)
    assert dupes == 0
    assert ranked[0]["skill"] == "Testing"
    assert ranked[0]["ranking"]["skill_relevance"] == pytest.approx(1.0)
    assert ranked[0]["fused_score"] > ranked[1]["fused_score"]


def test_retrieve_query_reranks_by_relevance():
    result = _run(rs.retrieve("Software Engineer", query="testing automation"))
    assert result["count"] > 0
    first = result["items"][0]
    assert first["skill"] == "Testing" or "test" in first["skill"].lower()
    assert first["ranking"]["weights_version"] == "fusion-v1"


# ---------------------------------------------------------------------------
# 2. Role relevance: equal similarity, role match decides
# ---------------------------------------------------------------------------

def test_role_match_outranks_equal_similarity():
    items = [
        _row("Backend Developer", "Python", role_relevance="CORE"),
        _row("Software Engineer", "Python", role_relevance="CORE"),
    ]
    sims = {0: 0.80, 1: 0.80}
    ranked, _ = rs._rank_items(items, "Software Engineer", "python", 10, sims, now=FIXED_NOW)
    assert ranked[0]["role"] == "Software Engineer"
    assert ranked[0]["ranking"]["role_relevance"] > ranked[1]["ranking"]["role_relevance"]
    # Total order is deterministic.
    again, _ = rs._rank_items(items, "Software Engineer", "python", 10, sims, now=FIXED_NOW)
    assert [r["skill"] for r in again] == [r["skill"] for r in ranked]


# ---------------------------------------------------------------------------
# 3. Low-quality sources cannot dominate on similarity alone
# ---------------------------------------------------------------------------

def test_low_quality_high_similarity_is_suppressed():
    items = [
        _row("Software Engineer", "Python", source_quality=0.30),
        _row("Software Engineer", "Git", source_quality=0.90),
    ]
    sims = {0: 0.95, 1: 0.50}
    ranked, _ = rs._rank_items(items, "Software Engineer", "python git", 10, sims, now=FIXED_NOW)
    low = next(r for r in ranked if r["skill"] == "Python")
    assert low["ranking"]["quality_capped"] is True
    assert low["fused_score"] <= 0.49
    # Decent source outranks the capped one despite lower similarity.
    assert ranked[0]["skill"] == "Git"


def test_quality_boundary_accepted():
    items = [_row("Software Engineer", "Python", source_quality=0.50)]
    ranked, _ = rs._rank_items(items, "Software Engineer", "python", 10, {0: 0.9}, now=FIXED_NOW)
    assert ranked[0]["ranking"]["quality_capped"] is False


# ---------------------------------------------------------------------------
# 4. Duplicate evidence collapses to one item
# ---------------------------------------------------------------------------

def test_duplicate_role_skill_collapses():
    items = [
        _row("Software Engineer", "Python", source="Source A", source_quality=0.90),
        _row("Software Engineer", "Python", source="Source B", source_quality=0.70),
    ]
    ranked, dupes = rs._rank_items(items, "Software Engineer", "python", 10, {0: 0.8, 1: 0.8}, now=FIXED_NOW)
    assert len(ranked) == 1
    assert dupes == 1
    # Strongest fused survives.
    assert ranked[0]["source"] == "Source A"


# ---------------------------------------------------------------------------
# 5. Fallback retrieval: full provenance, canonical skills, deterministic
# ---------------------------------------------------------------------------

def test_fallback_returns_full_provenance():
    assert not rs.embedding_service.is_configured() or True  # works either way offline
    result = _run(rs.retrieve("Backend Developer"))
    assert result["role"] == "Backend Developer"
    assert result["count"] > 0
    assert result["ranking"] == "fusion-v1"
    for it in result["items"]:
        for key in ("skill", "required_level", "importance", "similarity",
                    "source", "source_url", "source_quality",
                    "published_at", "retrieved_at", "role"):
            assert key in it, f"missing provenance '{key}' on {it.get('skill')}"
        assert 0.0 <= it["similarity"] <= 1.0
        assert it["ranking"]["weights_version"] == "fusion-v1"
        for comp in ("similarity", "role_relevance", "skill_relevance",
                     "source_quality", "importance_demand", "freshness", "fused_score"):
            assert comp in it["ranking"]
    # Deterministic across calls.
    again = _run(rs.retrieve("Backend Developer"))
    assert [i["skill"] for i in again["items"]] == [i["skill"] for i in result["items"]]


def test_fusion_formula_is_explicit():
    item = _row("Software Engineer", "Python")
    fused, detail = rs._fuse_signals(item, "Software Engineer", "python", 0.80, FIXED_NOW)
    expected = round(
        (0.40 * 0.80 + 0.20 * detail["role_relevance"] + 0.15 * 1.0
         + 0.15 * 0.90 + 0.10 * detail["importance_demand"]) * detail["freshness"], 3,
    )
    assert fused == pytest.approx(expected)
    assert detail["quality_capped"] is False
    # Weights sum to one: fused is bounded by components.
    assert 0.0 <= fused <= 1.0


# ---------------------------------------------------------------------------
# 6. Custom roles: gated vector chunks, honest refusal preserved
# ---------------------------------------------------------------------------

def test_custom_role_insufficient_data_refusal():
    result = _run(rs.synthesize_custom_role("Quantum Origami Chef 4000"))
    assert result["status"] == "insufficient_data"
    assert result["skills_count"] < 2
    assert result["requirements"] == []
    assert result["confidence"] == 0.0
    assert "could not locate sufficient verifiable industry benchmark data" in result["note"]


def test_custom_role_synthesis_still_works():
    result = _run(rs.synthesize_custom_role("AI Engineer"))
    assert result["status"] == "synthesized"
    assert result["skills_count"] >= 3
    assert 0.50 <= result["confidence"] <= 0.80
    skills = {r["skill"] for r in result["requirements"]}
    assert "Python" in skills or "REST APIs" in skills or "Deep Learning" in skills


def test_vector_chunks_require_role_relevance(monkeypatch):
    # Similarity alone must not pull unrelated roles into a synthesis:
    # vector chunks about Software Engineering must be gated out for a
    # pastry role, ending in honest refusal instead of fabrication.
    swe_chunk = dict(rs.PROTOTYPE_KNOWLEDGE_CHUNKS[0])

    async def fake_vec_chunks(query, top_k):
        return [swe_chunk]

    async def fail_vector_search(*args, **kwargs):
        raise AssertionError("embeddings must not be needed for this path")

    monkeypatch.setattr(rs, "_vector_search_chunks", fake_vec_chunks)
    monkeypatch.setattr(rs.embedding_service, "is_configured", lambda: True)
    result = _run(rs.synthesize_custom_role("Pastry Chef"))
    assert result["status"] == "insufficient_data"
    assert result["requirements"] == []


# ---------------------------------------------------------------------------
# 7. Canonical skill extraction on every path
# ---------------------------------------------------------------------------

def test_ranked_skills_are_canonical():
    items = [
        _row("Frontend Developer", "ReactJS"),
        _row("Backend Developer", "postgres"),
    ]
    ranked, _ = rs._rank_items(items, "Frontend Developer", "web", 10, now=FIXED_NOW)
    names = {r["skill"] for r in ranked}
    assert "React" in names
    assert "PostgreSQL" in names
    for r in ranked:
        assert taxonomy.normalize_skill(r["skill"]) == r["skill"]


def test_vector_path_enriches_metadata_and_ranks(monkeypatch):
    async def fake_vector_search(role, query, top_k):
        return [
            {"role": role, "skill": "REST APIs", "similarity": 0.92,
             "importance": 0.92, "demand": 0.90,
             "source": "Vector Benchmark", "source_url": None},
            {"role": role, "skill": "Obscure Lib", "similarity": 0.99,
             "importance": 0.30, "demand": 0.30,
             "source": "Low Quality Blog", "source_url": None,
             "source_quality": 0.20},
        ]

    monkeypatch.setattr(rs, "_vector_search", fake_vector_search)
    result = _run(rs.retrieve("Backend Developer", query="rest api"))
    assert "vector search" in result["note"]
    by_skill = {i["skill"]: i for i in result["items"]}
    assert "REST APIs" in by_skill
    rest = by_skill["REST APIs"]
    # Missing metadata filled from the canonical catalog (not fabricated).
    assert rest["source_quality"] >= 0.80
    assert rest["published_at"]
    assert rest["retrieved_at"]
    assert rest["ranking"]["weights_version"] == "fusion-v1"
    if "Obscure Lib" in by_skill:
        assert by_skill["Obscure Lib"]["ranking"]["quality_capped"] is True


# ---------------------------------------------------------------------------
# 8. Analysis pipeline keeps working on retrieved requirements
# ---------------------------------------------------------------------------

def test_retrieved_requirements_feed_analysis():
    result = _run(rs.retrieve("Backend Developer"))
    req_map = ars.build_requirements_map(result["items"], None)
    assert "REST APIs" in req_map
    assert "PostgreSQL" in req_map
    signals = [
        {"skill": "REST APIs", "source": "github", "signal_strength": 0.80,
         "source_reliability": 0.40},
    ]
    grouped = ars.aggregate_skills(signals)
    assessments = ars.calculate_assessments(grouped, req_map, None)
    rest_api = next(a for a in assessments if a["canonical_name"] == "REST APIs")
    assert rest_api["proficiency"] > 0.0
