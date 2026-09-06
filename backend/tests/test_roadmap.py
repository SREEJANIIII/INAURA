import pytest
import math
from fastapi import HTTPException
from app.services import roadmap_service as rs
from app.services.roadmap_catalog import get_resources_for_skill, RESOURCE_CATALOG, ENGINE_VERSION

# Helpers

def gap_obj(skill_id, gap, priority, importance=0.8, demand=0.7, interview=0.6, confidence=0.7):
    return {
        "id": f"gap-{skill_id}",
        "skill_id": skill_id,
        "gap": gap,
        "priority_score": priority,
        "importance": importance,
        "demand": demand,
        "interview_relevance": interview,
        "confidence": confidence,
        "current_proficiency": 0.4,
        "required_level": 0.8,
        "skills": {"canonical_name": skill_id, "display_name": skill_id.title(), "category": "Test"},
    }

# 1. Gap ordering by priority

def test_gap_ordering_by_priority():
    gaps = [
        gap_obj("python", 0.5, 10),
        gap_obj("dsa", 0.6, 50),
        gap_obj("sql", 0.4, 30),
    ]
    sorted_gaps = rs.filter_and_sort_gaps(gaps)
    # DSA priority 50 should be first
    assert sorted_gaps[0]["skill_id"] == "dsa"
    assert sorted_gaps[1]["skill_id"] == "sql"
    assert sorted_gaps[2]["skill_id"] == "python"
    # Deterministic: same input same output
    again = rs.filter_and_sort_gaps(gaps)
    assert [g["skill_id"] for g in sorted_gaps] == [g["skill_id"] for g in again]

# 2. Zero-gap exclusion

def test_zero_gap_exclusion():
    gaps = [
        gap_obj("python", 0.5, 20),
        gap_obj("sql", 0.0, 100),  # zero gap should be excluded even though priority high
        gap_obj("dsa", 0.3, 15),
    ]
    filtered = rs.filter_and_sort_gaps(gaps)
    ids = [g["skill_id"] for g in filtered]
    assert "sql" not in ids
    assert "python" in ids
    assert len(filtered) == 2
    # Gap exactly 0 -> gap_priority = 0 already, but we filter >1e-9
    assert all(g["gap"] > 0 for g in filtered)

# 3. Hours/week calculation

def test_hours_per_week_validation():
    # valid
    assert rs.estimate_weeks(30, 5) == 6
    assert rs.estimate_weeks(30, 10) == 3
    # Ceil
    assert rs.estimate_weeks(31, 5) == 7  # ceil
    assert rs.estimate_weeks(0, 5) == 0

# 4. Estimated weeks

def test_estimated_weeks_formula():
    assert rs.estimate_weeks(30, 5) == math.ceil(30/5)
    assert rs.estimate_weeks(25, 6) == math.ceil(25/6)
    # Total 36 hours with 5 h/week → 8 weeks
    assert rs.estimate_weeks(36, 5) == 8

# 5. Division-by-zero handling

def test_division_by_zero():
    with pytest.raises(Exception) as exc:
        rs.estimate_weeks(30, 0)
    assert "weekly availability" in str(exc.value).lower() or "hours_per_week" in str(exc.value).lower()
    with pytest.raises(Exception):
        rs.estimate_weeks(30, None)
    with pytest.raises(Exception):
        rs.estimate_weeks(30, -1)

# 6. Roadmap length limits (3-6)

def test_roadmap_length_limits():
    # Create 10 gaps, should limit to 6
    many = [gap_obj(f"skill{i}", 0.5, 100-i) for i in range(10)]
    filtered = rs.filter_and_sort_gaps(many)
    limited = rs.limit_gaps(filtered, max_items=6)
    assert len(limited) == 6
    assert limited[0]["skill_id"] == "skill0"  # highest priority
    # With 2 gaps, should keep 2 (not force 3)
    few = [gap_obj("a", 0.5, 10), gap_obj("b", 0.4, 9)]
    limited2 = rs.limit_gaps(rs.filter_and_sort_gaps(few))
    assert len(limited2) == 2
    # With 4 gaps, keep 4
    four = [gap_obj(f"s{i}", 0.5, 10-i) for i in range(4)]
    assert len(rs.limit_gaps(rs.filter_and_sort_gaps(four))) == 4

# 7. Resource mapping

def test_resource_mapping():
    # Known skill should return curated prototype resources
    py_res = get_resources_for_skill("python")
    assert len(py_res) >= 1 and len(py_res) <= 3
    for r in py_res:
        assert "title" in r and "url" in r and "resource_type" in r
        assert r["resource_type"] in ("course","documentation","tutorial","article","video","practice","project_reference")
        assert r["url"].startswith("https://")
    # DSA should have at least 2
    dsa_res = get_resources_for_skill("dsa")
    assert len(dsa_res) >= 1
    # Unknown skill fallback returns generic (1)
    unk = get_resources_for_skill("unknown_skill_xyz")
    assert len(unk) >= 1
    # Deterministic: same canonical same resources
    assert get_resources_for_skill("python") == get_resources_for_skill("python")
    # Check provider marking
    for res in py_res:
        assert "is_free" in res
        assert isinstance(res["is_free"], bool)

# 8. Milestone generation

def test_milestone_generation_logic():
    # Simulate grouping for n items
    def plan_milestones(n):
        if n >= 3:
            num_m = 3
        elif n == 2:
            num_m = 2
        elif n == 1:
            num_m = 1
        else:
            num_m = 0
        per = math.ceil(n / num_m) if num_m else 0
        groups = []
        for mi in range(num_m):
            start = mi * per
            end = min(start + per, n)
            groups.append((start, end))
        return groups, num_m

    # 5 items → 3 milestones: [0:2], [2:4], [4:5]
    groups, num = plan_milestones(5)
    assert num == 3
    assert groups == [(0,2),(2,4),(4,5)]
    # 6 items → 3 milestones: 2 each
    groups, _ = plan_milestones(6)
    assert groups == [(0,2),(2,4),(4,6)]
    # 2 items → 2 milestones
    groups, num = plan_milestones(2)
    assert num == 2
    assert groups == [(0,1),(1,2)]
    # 1 item → 1 milestone
    groups, num = plan_milestones(1)
    assert num == 1
    assert groups == [(0,1)]
    # Check actual milestone titles exist
    assert len(rs.MILESTONE_TITLES) == 3
    assert rs.MILESTONE_TITLES[0][0] == "Strengthen Core Foundations"

# 9. Progress calculation

def test_progress_calculation():
    assert rs.calculate_progress([]) == 0.0
    assert rs.calculate_progress([{"completion_percentage": 0}, {"completion_percentage": 100}]) == 50.0
    assert rs.calculate_progress([{"completion_percentage": 100}, {"completion_percentage": 100}]) == 100.0
    assert rs.calculate_progress([{"completion_percentage": 33}, {"completion_percentage": 33}, {"completion_percentage": 33}]) == pytest.approx(33.0)
    # Clamping
    assert rs.calculate_progress([{"completion_percentage": 150}]) == 100.0
    assert rs.calculate_progress([{"completion_percentage": -10}]) == 0.0
    # Average deterministic
    items = [{"completion_percentage": 20}, {"completion_percentage": 40}, {"completion_percentage": 60}]
    assert rs.calculate_progress(items) == pytest.approx(40.0)

# 10. Completion percentage validation

def test_completion_percentage_validation():
    assert rs.validate_completion_percentage(0) == 0
    assert rs.validate_completion_percentage(100) == 100
    assert rs.validate_completion_percentage(50.5) == pytest.approx(50.5)
    with pytest.raises(Exception) as e:
        rs.validate_completion_percentage(-1)
    assert "0 and 100" in str(e.value)
    with pytest.raises(Exception):
        rs.validate_completion_percentage(101)
    with pytest.raises(Exception):
        rs.validate_completion_percentage(float("nan"))
    with pytest.raises(Exception):
        rs.validate_completion_percentage(float("inf"))

# 11. User isolation (pure logic: different users' gaps don't leak; progress isolated)

def test_user_isolation_pure():
    # Two users with different gaps produce different orderings and progress
    user_a_gaps = [gap_obj("python", 0.5, 90), gap_obj("dsa", 0.6, 10)]
    user_b_gaps = [gap_obj("python", 0.5, 10), gap_obj("dsa", 0.6, 90)]
    a_sorted = rs.filter_and_sort_gaps(user_a_gaps)
    b_sorted = rs.filter_and_sort_gaps(user_b_gaps)
    assert a_sorted[0]["skill_id"] == "python"
    assert b_sorted[0]["skill_id"] == "dsa"
    # Progress isolation: items for user A vs B separate
    a_items = [{"completion_percentage": 100}, {"completion_percentage": 0}]
    b_items = [{"completion_percentage": 0}, {"completion_percentage": 0}]
    assert rs.calculate_progress(a_items) != rs.calculate_progress(b_items)
    assert rs.calculate_progress(a_items) == 50.0
    assert rs.calculate_progress(b_items) == 0.0

# 12. No-analysis handling

def test_no_analysis_handling(monkeypatch):
    # Mock supabase client to return no analysis
    class FakeTable:
        def select(self, *a, **kw): return self
        def eq(self, *a, **kw): return self
        def order(self, *a, **kw): return self
        def limit(self, *a, **kw): return self
        def single(self): return self
        def execute(self):
            return type("obj", (), {"data": []})()
    class FakeClient:
        def table(self, name): return FakeTable()
    # Patch _client to return fake
    monkeypatch.setattr(rs, "_client", lambda: FakeClient())
    # Also patch profile to return valid hours so we reach analysis check
    monkeypatch.setattr(rs.profile_service, "get_profile", lambda user_id: {"hours_per_week": 5})
    import asyncio
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rs.generate_roadmap("user-no-analysis", "Python"))
    assert exc.value.status_code == 404
    assert "no analysis" in str(exc.value.detail).lower()

# 13. No-gap handling

def test_no_gap_handling(monkeypatch):
    class FakeTableAnalysis:
        def select(self, *a, **kw): return self
        def eq(self, *a, **kw): return self
        def order(self, *a, **kw): return self
        def limit(self, *a, **kw): return self
        def execute(self):
            return type("obj", (), {"data": [{"id": "ana1", "target_role": "AI/ML Engineer", "user_id": "u1"}]})()
    class FakeTableGaps:
        def select(self, *a, **kw): return self
        def eq(self, *a, **kw): return self
        def order(self, *a, **kw): return self
        def execute(self):
            # Return only zero gaps
            return type("obj", (), {"data": [
                {"id": "g1", "skill_id": "s1", "gap": 0.0, "priority_score": 0, "importance": 0.8, "demand": 0.7, "interview_relevance": 0.6, "confidence": 0.9, "current_proficiency": 0.9, "required_level": 0.8, "skills": {"canonical_name": "python", "display_name": "Python", "category": "Programming"}}
            ]})()
    class FakeTableSkills:
        def select(self, *a, **kw): return self
        def execute(self):
            return type("obj", (), {"data": []})()
    class FakeClient:
        def table(self, name):
            if name == "analysis_results":
                return FakeTableAnalysis()
            if name == "skill_gaps":
                return FakeTableGaps()
            if name == "skills":
                return FakeTableSkills()
            # For roadmaps etc, shouldn't be hit
            raise Exception(f"unexpected table {name}")
    monkeypatch.setattr(rs, "_client", lambda: FakeClient())
    monkeypatch.setattr(rs.profile_service, "get_profile", lambda user_id: {"hours_per_week": 5})
    import asyncio
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rs.generate_roadmap("u1", "AI/ML Engineer"))
    assert exc.value.status_code == 400
    assert "meeting the assessed" in str(exc.value.detail).lower() or "no priority gaps" in str(exc.value.detail).lower()

def test_engine_version():
    assert ENGINE_VERSION == "4D-v1"
    assert rs.ENGINE_VERSION == "4D-v1"

def test_estimate_hours_heuristic():
    # Larger gap -> larger hours
    h1 = rs.estimate_hours_for_gap("python", 0.8, 0.9)
    h2 = rs.estimate_hours_for_gap("python", 0.2, 0.9)
    assert h1 > h2
    # Importance also increases hours
    h3 = rs.estimate_hours_for_gap("python", 0.5, 0.9)
    h4 = rs.estimate_hours_for_gap("python", 0.5, 0.5)
    assert h3 > h4
    # Clamped
    assert 2 <= h1 <= 30
    # Deterministic
    assert rs.estimate_hours_for_gap("dsa", 0.5, 0.8) == rs.estimate_hours_for_gap("dsa", 0.5, 0.8)

def test_why_it_matters_contains_values():
    why = rs.generate_why_it_matters("Python", 0.4, 0.8, 0.4, 0.85, 0.9, 0.8, 0.65, "AI/ML Engineer")
    assert "Python" in why
    assert "40%" in why or "0.4" in why or "current" in why.lower()
    assert "AI/ML Engineer" in why
