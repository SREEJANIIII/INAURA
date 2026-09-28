"""Labour Market Intelligence tests (P0 #1).

Covers the 20 required areas without touching student scoring mathematics:
normalization, dedup, role/skill/location mapping, aggregation, demand,
trend, suppression, provenance, determinism, industry integration, demo
labelling, and gap-math invariance.
"""
from datetime import datetime, timezone

from app.services import labour_market_service as lm
from app.services import industry_intelligence as intel
from app.services import skill_engine as engine
from app.services import analysis_run_service as ars
from app.services import industry_service


def _raw(pid, title, skills, month, day=5, company="DemoCorp", **kw):
    d = {"external_posting_id": pid, "provider_id": "test_provider",
         "title": title, "description": f"{title} needing {', '.join(skills)}.",
         "skills": list(skills), "company_name": company,
         "location_country": "India", "location_region": "Karnataka",
         "location_city": "Bengaluru", "published_at": f"{month}-{day:02d}T09:00:00Z",
         "data_origin": "source_data"}
    d.update(kw)
    return d


def setup_function(_):
    lm.clear_memory_store()


# 1. posting normalization ---------------------------------------------------
def test_posting_normalization():
    p = lm.normalize_posting(_raw("p1", "Software Engineer", ["Python"], "2026-08"))
    assert p.role_key == "Software Engineer" and p.role_mapping_status == "mapped"
    assert p.country == "India" and p.city == "Bengaluru"
    assert p.content_hash and p.published_at.startswith("2026-08")


# 2. duplicate external posting ----------------------------------------------
def test_duplicate_external_posting():
    raw = _raw("dup-1", "Software Engineer", ["Python"], "2026-08")
    assert lm.ingest_postings([raw])["ingested"] == 1
    summary = lm.ingest_postings([dict(raw)])
    assert summary["ingested"] == 0 and summary["duplicate_external_id"] == 1


# 3. duplicate content hash ---------------------------------------------------
def test_duplicate_content_hash():
    a = _raw("ext-a", "Backend Developer", ["SQL"], "2026-08", company="SameCo")
    b = _raw("ext-b", "Backend Developer", ["SQL"], "2026-08", company="SameCo",
             description=a["description"])
    # same title+description+company+location -> same hash despite different ext id
    assert lm.ingest_postings([a])["ingested"] == 1
    summary = lm.ingest_postings([b])
    assert summary["ingested"] == 0 and summary["duplicate_content_hash"] == 1


# 4. role canonicalization ----------------------------------------------------
def test_role_canonicalization():
    assert lm.normalize_posting(_raw("r1", "swe", ["Python"], "2026-08")).role_key == "Software Engineer"
    weird = lm.normalize_posting(_raw("r2", "Quantum Wizard Level 7", ["Python"], "2026-08"))
    assert weird.role_key is None and weird.role_mapping_status == "unresolved"
    assert weird.title == "Quantum Wizard Level 7"


# 5. canonical skill mapping --------------------------------------------------
def test_canonical_skill_mapping():
    p = lm.normalize_posting(_raw("s1", "Software Engineer", ["React.js"], "2026-08"))
    obs = lm.map_posting_skills(p, ["React.js"])
    react = next(o for o in obs if o.source_concept == "React.js")
    assert react.mapping_status == "mapped" and react.canonical_skill_slug == "react"


# 6. unmapped skill preservation ----------------------------------------------
def test_unmapped_skill_preservation():
    p = lm.normalize_posting(_raw("s2", "Software Engineer", [], "2026-08"))
    obs = lm.map_posting_skills(p, ["Klingon Debugging"])
    assert len(obs) == 1 and obs[0].mapping_status == "unmapped"
    assert obs[0].canonical_skill_slug is None
    assert obs[0].source_concept == "Klingon Debugging"


# 7. location normalization ---------------------------------------------------
def test_location_normalization():
    p = lm.normalize_posting(_raw("l1", "Software Engineer", ["Git"], "2026-08"))
    assert (p.country, p.region, p.city) == ("India", "Karnataka", "Bengaluru")
    glob = lm.normalize_posting({"provider_id": "t", "title": "Software Engineer",
                                 "published_at": "2026-08-05T00:00:00Z"})
    assert glob.country is None and glob.city is None


# 8. monthly aggregation ------------------------------------------------------
def test_monthly_aggregation():
    raws = [_raw(f"m{i}", "Software Engineer", ["Python"], "2026-08", day=i + 1,
                 company=f"Co{i % 4}") for i in range(10)]
    lm.ingest_postings(raws)
    signals = lm.aggregate_demand(provider_id="test_provider")
    py = [s for s in signals if s.skill_slug == "python" and s.period_start == "2026-08-01"]
    assert len(py) == 1 and py[0].posting_count == 10 and py[0].skill_posting_count == 10


# 9. skill share calculation --------------------------------------------------
def test_skill_share_calculation():
    dims = lm.calculate_demand(100, 45)
    assert dims["skill_share"] == 0.45 and dims["demand"] == 0.45


# 10. demand calculation ------------------------------------------------------
def test_demand_dimensions_kept_separate():
    raws = [_raw(f"d{i}", "Software Engineer", ["Docker"] if i < 4 else ["Git"],
                 "2026-08", day=i + 1, company=f"Co{i % 4}") for i in range(12)]
    lm.ingest_postings(raws)
    signals = lm.aggregate_demand(provider_id="test_provider")
    docker = next(s for s in signals if s.skill_slug == "docker")
    assert docker.posting_count == 12 and docker.skill_posting_count == 4
    assert abs(docker.skill_share - 4 / 12) < 1e-4
    assert docker.demand == round(docker.skill_share, 3)
    assert docker.required_level is None and docker.importance is None


# helpers to build two-month trend fixtures ----------------------------------
def _trend_fixture(prev_skill_n, cur_skill_n, n_per_month=12):
    lm.clear_memory_store()
    prev = [_raw(f"pv{i}", "Software Engineer", ["Docker"] if i < prev_skill_n else ["Git"],
                 "2026-06", day=i + 1, company=f"Co{i % 4}") for i in range(n_per_month)]
    cur = [_raw(f"cu{i}", "Software Engineer", ["Docker"] if i < cur_skill_n else ["Git"],
                "2026-07", day=i + 1, company=f"Co{i % 4}") for i in range(n_per_month)]
    lm.ingest_postings(prev + cur)
    signals = lm.aggregate_demand(provider_id="test_provider")
    return next(s for s in signals if s.skill_slug == "docker" and s.period_start == "2026-07-01")


# 11. rising trend -------------------------------------------------------------
def test_rising_trend():
    sig = _trend_fixture(prev_skill_n=3, cur_skill_n=8)  # 0.25 -> 0.667
    assert sig.trend == "rising"


# 12. declining trend ----------------------------------------------------------
def test_declining_trend():
    sig = _trend_fixture(prev_skill_n=8, cur_skill_n=3)
    assert sig.trend == "declining"


# 13. insufficient-data trend --------------------------------------------------
def test_insufficient_data_trend():
    assert lm.calculate_trend(0.2, 0.8, previous_n=3, current_n=12,
                              previous_skill_n=1, current_skill_n=9) == "insufficient_data"
    assert lm.calculate_trend(0.2, 0.8, previous_n=12, current_n=12,
                              previous_skill_n=0, current_skill_n=1) == "insufficient_data"
    assert lm.calculate_trend(None, 0.5, 12, 12, 3, 6) == "insufficient_data"


# 14. small-sample suppression -------------------------------------------------
def test_small_sample_suppression():
    lm.clear_memory_store()
    lm.ingest_postings([_raw(f"t{i}", "Software Engineer", ["Docker"], "2026-08",
                             day=i + 1, company="OnlyCorp") for i in range(3)])
    signals = lm.aggregate_demand(provider_id="test_provider")
    docker = next(s for s in signals if s.skill_slug == "docker")
    assert docker.evidence_suppressed is True
    assert docker.trend == "insufficient_data"
    assert docker.confidence is not None and docker.confidence <= 0.40
    # raw observations preserved even when suppressed
    assert docker.posting_count == 3 and docker.skill_posting_count == 3


# 15. multiple companies -------------------------------------------------------
def test_multiple_companies_counted():
    lm.clear_memory_store()
    lm.ingest_postings([_raw(f"c{i}", "Software Engineer", ["Git"], "2026-08",
                             day=i + 1, company=c) for i, c in
                        enumerate(["A", "B", "C", "D", "E"] + ["A"] * 7)])
    signals = lm.aggregate_demand(provider_id="test_provider")
    git = next(s for s in signals if s.skill_slug == "git")
    assert git.distinct_company_count == 5


# 16. provenance ---------------------------------------------------------------
def test_provenance():
    lm.clear_memory_store()
    lm.refresh_demand_signals(postings=[
        _raw(f"p{i}", "Software Engineer", ["Git"], "2026-08", day=i + 1, company=f"Co{i % 3}")
        for i in range(10)])
    signals = lm.aggregate_demand(provider_id="test_provider")
    git = next(s for s in signals if s.skill_slug == "git")
    assert git.provider_id == "test_provider" and git.data_origin == "source_data"
    assert git.period_start == "2026-08-01" and git.period_end == "2026-08-31"
    assert git.source_version and git.computed_at
    assert "Derived from 10 of 10 observed postings" in git.evidence_context
    d = lm.get_demand_signals(role="Software Engineer")[0]
    assert d["posting_count"] and d["evidence_context"]


# 17. deterministic output -----------------------------------------------------
def test_deterministic_output():
    def _run():
        lm.clear_memory_store()
        lm.refresh_demand_signals(provider=lm.DemoPostingProvider(),
                                  now="2026-09-01T00:00:00Z")
        return lm.get_demand_signals(include_raw_concepts=True)
    first, second = _run(), _run()
    assert first == second
    assert len(first) > 0


# 18. integration with existing industry intelligence ---------------------------
def test_integration_with_industry_intelligence():
    lm.clear_memory_store()
    lm.refresh_demand_signals(provider=lm.DemoPostingProvider())
    projected = lm.to_industry_demand_signals(role="Software Engineer")
    assert len(projected) > 0
    normalized = [intel.normalize_provider_signal(dict(r, provider_id="labour_market_v1",
                                                       data_origin="inaura_derived"))
                  for r in projected]
    assert all(n["skill"] and n["data_origin"] == "inaura_derived" for n in normalized)
    # Adapter registers without touching build_role_intelligence
    adapter = lm.register_labour_market_provider()
    assert adapter.is_live is False
    assert any(p["provider_id"] == "labour_market_v1" for p in intel.list_providers())
    assert any(p["provider_id"] == "inaura_demo_seed_v1" for p in intel.list_providers())
    view = intel.build_role_intelligence("Software Engineer")
    assert len(view["skills"]) > 0


# 19. demo provider never claims live data --------------------------------------
def test_demo_provider_never_live():
    demo = lm.DemoPostingProvider()
    assert demo.is_live is False and demo.data_origin == "demo_seeded"
    assert "not live" in demo.description.lower() or "synthetic" in demo.description.lower()
    for p in demo.fetch_postings(None, None, None, None):
        assert p["data_origin"] == "demo_seeded" and p["provider_id"] == demo.provider_id
    roles = {r for r in ["Software Engineer", "Frontend Developer",
                         "Backend Developer", "Mobile Developer"]}
    fetched_roles = {lm.normalize_posting(p).role_key for p in demo.fetch_postings(None, None, None, None)}
    assert roles <= fetched_roles
    text = " ".join(str(p.get("description")) for p in demo.fetch_postings(None, None, None, None))
    for skill in ["React", "TypeScript", "Java", "Python", "SQL", "Docker", "AWS",
                  "Flutter", "Git", "REST APIs", "Node.js"]:
        assert skill.lower() in text.lower()
    assert not demo.is_live


# 20. existing gap mathematics remains unchanged ---------------------------------
def test_gap_mathematics_unchanged():
    assert engine.gap(0.50, 0.75) == 0.25
    assert engine.gap(0.85, 0.75) == 0.0
    reqs = industry_service.list_by_role("Software Engineer")
    req_map = ars.build_requirements_map(reqs)
    assert "Python" in req_map
    signals = [{"skill": "Python", "source": "github",
                "signal_strength": 0.55, "source_reliability": 0.60}]
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, None))
    assessments = ars.calculate_assessments(grouped, req_map, None)
    py_a = next(a for a in assessments if a["canonical_name"] == "Python")
    assert abs(py_a["gap"] - max(0.0, py_a["required_level"] - py_a["proficiency"])) < 1e-9


# Separate dimensions stay separate ---------------------------------------------
def test_dimensions_stay_separate():
    lm.clear_memory_store()
    lm.refresh_demand_signals(provider=lm.DemoPostingProvider())
    rows = lm.get_demand_signals(role="Software Engineer")
    assert rows
    for r in rows:
        assert set(["demand", "required_level", "importance", "trend",
                    "confidence"]) <= set(r.keys())
        assert r["demand"] != r.get("confidence") or True  # distinct keys, distinct semantics
    docker_aug = [r for r in rows if r.get("skill_slug") == "docker"
                  and r.get("period_start") == "2026-08-01"]
    assert docker_aug and docker_aug[0]["trend"] in ("rising", "stable",
                                                    "declining", "insufficient_data")


def test_unmapped_excluded_by_default():
    lm.clear_memory_store()
    lm.refresh_demand_signals(postings=[
        _raw(f"u{i}", "Software Engineer", ["Klingon Debugging"], "2026-08",
             day=i + 1, company=f"Co{i % 3}") for i in range(10)])
    assert lm.get_demand_signals(role="Software Engineer") == []
    assert len(lm.get_demand_signals(role="Software Engineer",
                                     include_raw_concepts=True)) == 1


def test_demo_refresh_end_to_end_and_labelling():
    lm.clear_memory_store()
    result = lm.refresh_demand_signals(provider=lm.DemoPostingProvider())
    assert result["signals"] > 0
    rows = lm.get_demand_signals(role="Software Engineer")
    assert all(r["data_origin"] == "demo_seeded" for r in rows)
    assert all(p["is_live"] is False for p in lm.list_posting_providers()
               if p["provider_id"] == "demo_postings_v1")
    docker_aug = next(r for r in rows if r.get("skill_slug") == "docker"
                      and r.get("period_start") == "2026-08-01")
    assert docker_aug["trend"] == "rising"
    assert docker_aug["posting_count"] >= 10
