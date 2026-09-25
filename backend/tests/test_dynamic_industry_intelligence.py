"""Dynamic Industry Intelligence regression tests (Person 1).

Covers the Definition-of-Done checklist without rebuilding O*NET/ESCO,
the canonical taxonomy, the gap engine, or retrieval:
 1. O*NET requirements still work
 2. ESCO mappings still work
 3. Canonical normalization still works
 4. Dynamic requirements representable
 5. Location-specific requirements work
 6. Global/default fallback when location unavailable
 7. Missing location data does not break
 8. Freshness classification correct
 9. Emerging/rising states don't break existing requirements
10. Provenance preserved (source vs derived vs demo)
11. Dynamic requirements feed the EXISTING gap engine
12. Retrieval consumes dynamic requirements
13. No duplicate taxonomy introduced
14. Flutter/mobile behavior intact
15. Existing industry-service invariants hold
+ taxonomy/industry consistency audit
"""
import asyncio
from datetime import datetime, timezone

from app.services import industry_service
from app.services import industry_roles
from app.services import retrieval_service as rs
from app.services import skill_taxonomy as taxonomy
from app.services import skill_engine as engine
from app.services import analysis_run_service as ars
from app.services import industry_intelligence as intel

FIXED_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _run(coro):
    return asyncio.run(coro)


# 1. O*NET requirements still work ------------------------------------------------
def test_onet_requirements_still_work():
    reqs = industry_service.list_by_role("Software Engineer")
    onet = [r for r in reqs if "O*NET" in str(r.get("source", ""))]
    assert len(onet) >= 5, "O*NET-grounded SWE rows must remain"
    for r in onet:
        for dim in ("required_level", "importance", "demand", "interview_relevance", "industry_confidence"):
            assert 0.0 <= float(r[dim]) <= 1.0


# 2. ESCO mappings still work ----------------------------------------------------
def test_esco_mappings_still_work():
    reqs = industry_service.list_by_role("Software Engineer")
    esco = [r for r in reqs if "ESCO" in str(r.get("source", ""))]
    assert len(esco) >= 5
    assert any("2512.4" in str(r.get("source_occupation", "")) for r in esco)


# 3. Canonical normalization still works -----------------------------------------
def test_canonical_normalization_still_works():
    assert taxonomy.normalize_skill("ReactJS") == "React"
    assert taxonomy.normalize_skill("postgres") == "PostgreSQL"
    assert taxonomy.normalize_skill_slug("React Native") == "react_native"
    for r in industry_service.get_all(limit=500):
        assert taxonomy.normalize_skill(r["skill"]) == r["skill"]


# 4. Dynamic requirement data can be represented ----------------------------------
def test_dynamic_signals_representable():
    sigs = intel.get_dynamic_signals("Software Engineer")
    assert len(sigs) >= 2
    for s in sigs:
        for dim in ("required_level", "importance", "demand", "interview_relevance", "industry_confidence"):
            assert 0.0 <= float(s[dim]) <= 1.0
        assert s["source"] and s["evidence_context"]
        assert s["collected_at"] and s["data_origin"] == intel.ORIGIN_DEMO


# 5. Location-specific requirements work -----------------------------------------
def test_location_specific_requirements():
    loc = intel.normalize_location("Bengaluru")
    assert loc["scope"] == "city" and loc["city"] == "Bengaluru" and not loc["is_global"]
    india = intel.normalize_location({"country": "India"})
    assert india["scope"] == "country" and india["is_global"] is False
    assert intel.normalize_location(None)["is_global"] is True
    assert intel.normalize_location("Global")["is_global"] is True


# 6. Global/default fallback when location unavailable ---------------------------
def test_global_fallback_for_unknown_location():
    view = intel.build_role_intelligence("Software Engineer", location="Bengaluru")
    assert view["location_match"] == "fallback_global"
    assert len(view["skills"]) > 0
    # No fabricated Bengaluru demand: every skill falls back to global baseline/demo
    for s in view["skills"]:
        assert s["location_match"] in ("global", "fallback_global")


# 7. Missing location data does not break ----------------------------------------
def test_missing_location_does_not_break():
    for loc in (None, "", {}, {"scope": "global"}):
        view = intel.build_role_intelligence("Backend Developer", location=loc)
        assert view["location"]["is_global"] is True
        assert len(view["skills"]) >= 6
    # Retrieval + gap map also tolerate missing location
    res = _run(rs.retrieve("Backend Developer", location=None))
    assert res["count"] > 0
    assert ars.build_requirements_map(intel.to_gap_engine_requirements(
        intel.build_role_intelligence("Backend Developer", location=None)))


# 8. Freshness calculated correctly ----------------------------------------------
def test_freshness_classification():
    assert intel.classify_freshness(published_at="2026-05-01", now=FIXED_NOW)["state"] == "current"
    assert intel.classify_freshness(published_at="2021-01-01", now=FIXED_NOW)["state"] == "aging"
    assert intel.classify_freshness(published_at="2010-01-01", now=FIXED_NOW)["state"] == "stale"
    assert intel.classify_freshness(now=FIXED_NOW)["state"] == "unknown"
    # View carries freshness per skill
    view = intel.build_role_intelligence("Software Engineer", now=FIXED_NOW)
    for s in view["skills"]:
        assert s["freshness"] in ("current", "aging", "stale", "unknown")


# 9. Emerging/rising states don't break existing requirements --------------------
def test_trend_states_coexist_with_baseline():
    view = intel.build_role_intelligence("Software Engineer")
    by_skill = {s["skill"]: s for s in view["skills"]}
    assert by_skill["React"]["trend"] == "rising"
    assert by_skill["Data Structures & Algorithms"]["trend"] == "stable"
    for s in view["skills"]:
        assert s["trend"] in ("stable", "rising", "emerging", "declining", "insufficient_data")
    rising = intel.get_rising_emerging(view)
    assert any(s["skill"] == "React" for s in rising)
    # Baseline-only role has no dynamics but stays valid
    be = intel.build_role_intelligence("Backend Developer")
    assert all(s["trend"] == "stable" for s in be["skills"])


# 10. Provenance preserved --------------------------------------------------------
def test_provenance_preserved_and_tiered():
    view = intel.build_role_intelligence("Software Engineer")
    origins = set(view["data_origins"])
    assert "source_data" in origins and "demo_seeded" in origins
    react = next(s for s in view["skills"] if s["skill"] == "React")
    assert react["data_origin"] == "demo_seeded"
    assert "Demo" in react["source"] and "not live" in react["source"].lower()
    assert react["evidence_context"] and react["collected_at"]
    # Unmapped concept preserved verbatim, never forced
    unmapped = [s for s in view["skills"] if s.get("mapping_status") == "unmapped"]
    assert len(unmapped) == 1
    assert unmapped[0]["source_concept"] == "Prompt Engineering for LLMs"
    assert unmapped[0]["trend"] == "emerging"
    # Baseline provenance untouched
    dsa = next(s for s in view["skills"] if s["skill"] == "Data Structures & Algorithms")
    assert "O*NET" in dsa["source"]


# 11. Dynamic requirements feed the EXISTING gap engine ---------------------------
def test_dynamic_requirements_feed_existing_gap_engine():
    view = intel.build_role_intelligence("Software Engineer")
    reqs = intel.to_gap_engine_requirements(view)
    assert any(r["skill"] == "React" for r in reqs)
    # Unmapped concepts excluded so taxonomy cannot drift
    assert not any("Prompt Engineering" in r["skill"] for r in reqs)
    req_map = ars.build_requirements_map(reqs)
    assert "React" in req_map
    # Existing engine math: gap = max(0, required - current)
    assert req_map["React"]["required_level"] == 0.80
    assert engine.gap(0.55, 0.80) == 0.25
    signals = [{"skill": "React", "source": "github",
                "signal_strength": 0.55, "source_reliability": 0.60}]
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, None))
    assessments = ars.calculate_assessments(grouped, req_map, None)
    react_a = next(a for a in assessments if a["canonical_name"] == "React")
    assert react_a["required_level"] == 0.80
    assert abs(react_a["gap"] - max(0.0, 0.80 - react_a["proficiency"])) < 1e-9
    gaps = ars.calculate_gaps(assessments, "Software Engineer")
    assert any(g["canonical_name"] == "React" for g in gaps)


# 12. Retrieval consumes dynamic requirements -------------------------------------
def test_retrieval_consumes_dynamic_requirements():
    res = _run(rs.retrieve("Software Engineer", query="react components"))
    skills = [i["skill"] for i in res["items"]]
    assert "React" in skills
    react = next(i for i in res["items"] if i["skill"] == "React")
    assert react["trend"] == "rising" and react["data_origin"] == "demo_seeded"
    for it in res["items"]:
        assert taxonomy.normalize_skill(it["skill"]) == it["skill"]
        assert it["ranking"]["weights_version"] == "fusion-v1"
    # Location-aware retrieval degrades gracefully, stays canonical
    loc_res = _run(rs.retrieve("Software Engineer", query="react", location="Bengaluru"))
    assert loc_res["count"] > 0


# 13. No duplicate taxonomy introduced --------------------------------------------
def test_no_duplicate_taxonomy():
    import app.services.skill_taxonomy as st
    import app.services.industry_intelligence as ii

    assert not hasattr(ii, "RAW_TAXONOMY")
    assert not hasattr(ii, "SkillDefinition")
    audit = taxonomy.audit_taxonomy_consistency(
        role_requirements=[{"skill": s["skill"]} for s in
                           intel.to_gap_engine_requirements(
                               intel.build_role_intelligence("Software Engineer"))],
    )
    assert audit["invalid_role_requirements"] == []


# 14. Flutter/mobile behavior intact ----------------------------------------------
def test_mobile_behavior_intact():
    assert taxonomy.normalize_skill("flutter development") == "Flutter"
    assert taxonomy.normalize_skill_slug("rn") == "react_native"
    mob = industry_service.list_by_role("Mobile Developer")
    assert {"Flutter", "React Native", "Android", "iOS"} <= {r["skill"] for r in mob}
    res = _run(rs.retrieve("Mobile Developer", query="flutter app development"))
    assert res["count"] > 0
    intel_view = intel.build_role_intelligence("Mobile Developer")
    assert len(intel_view["skills"]) >= 6


# 15. Existing industry-service invariants hold ------------------------------------
def test_existing_industry_invariants_hold():
    roles = industry_service.list_roles()
    for expected in ("Software Engineer", "Backend Developer", "Frontend Developer",
                     "Mobile Developer", "Cybersecurity Engineer"):
        assert expected in roles
    agg = industry_service.aggregate_requirements([{
        "role": "Test Role", "skill": "Python", "required_level": 0.80,
        "importance": 0.85, "demand": 0.80, "interview_relevance": 0.70,
        "source": "Source A", "source_quality": 0.90, "published_at": "2024-01-01"}])
    assert agg[0]["skill"] == "Python" and agg[0]["required_level"] == 0.80
    assert industry_service.classify_requirement_evidence(0, 0.9, 0.9) == "insufficient"
    assert industry_roles.canonicalize_role_name("swe") == "Software Engineer"


# + Consistency audit --------------------------------------------------------------
def test_taxonomy_industry_consistency_audit():
    reqs = industry_service.get_all(limit=500)
    audit = taxonomy.audit_taxonomy_consistency(role_requirements=reqs)
    assert audit["invalid_role_requirements"] == []
    assert audit["alias_collisions"] == []
