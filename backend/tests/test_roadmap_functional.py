"""Functional test for Phase 4D Roadmap — verifies spec 23 steps 1-12 with mocked DB"""
import pytest
import asyncio
import math
from fastapi import HTTPException

def test_functional_roadmap_e2e(monkeypatch):
    from app.services import roadmap_service as rs
    from app.services.roadmap_catalog import get_resources_for_skill

    # In-memory fake DB
    store = {
        "profiles": {"user1": {"user_id": "user1", "hours_per_week": 5, "full_name": "Test User", "college": "X", "degree": "B.Tech", "branch": "CSE", "current_year": "3rd", "graduation_year": 2026, "career_interests": ["AI/ML Engineer"], "profile_completed": True}},
        "analysis_results": [
            {"id": "ana1", "user_id": "user1", "target_role": "AI/ML Engineer", "skill_component": 0.6, "industry_component": 0.7, "evidence_component": 0.5, "readiness_score": 0.62, "assessment_count": 5, "gap_count": 5, "engine_version": "4C-v1", "created_at": "2026-01-01T00:00:00Z"}
        ],
        "skill_gaps": [
            {"id": "gap1", "user_id": "user1", "analysis_result_id": "ana1", "skill_id": "skill_python", "target_role": "AI/ML Engineer", "required_level": 0.8, "current_proficiency": 0.2, "confidence": 0.7, "gap": 0.6, "importance": 0.9, "demand": 0.9, "interview_relevance": 0.85, "priority_score": 28.0, "explanation": "gap python", "skills": {"canonical_name": "python", "display_name": "Python", "category": "Programming"}},
            {"id": "gap2", "user_id": "user1", "analysis_result_id": "ana1", "skill_id": "skill_dsa", "target_role": "AI/ML Engineer", "required_level": 0.85, "current_proficiency": 0.3, "confidence": 0.65, "gap": 0.55, "importance": 0.95, "demand": 0.9, "interview_relevance": 0.95, "priority_score": 32.0, "explanation": "gap dsa", "skills": {"canonical_name": "dsa", "display_name": "Data Structures & Algorithms", "category": "Core CS"}},
            {"id": "gap3", "user_id": "user1", "analysis_result_id": "ana1", "skill_id": "skill_ml", "target_role": "AI/ML Engineer", "required_level": 0.9, "current_proficiency": 0.1, "confidence": 0.6, "gap": 0.8, "importance": 0.95, "demand": 0.9, "interview_relevance": 0.85, "priority_score": 35.0, "explanation": "gap ml", "skills": {"canonical_name": "machine_learning", "display_name": "Machine Learning", "category": "ML"}},
            {"id": "gap4", "user_id": "user1", "analysis_result_id": "ana1", "skill_id": "skill_docker", "target_role": "AI/ML Engineer", "required_level": 0.75, "current_proficiency": 0.4, "confidence": 0.6, "gap": 0.35, "importance": 0.7, "demand": 0.7, "interview_relevance": 0.6, "priority_score": 12.0, "explanation": "gap docker", "skills": {"canonical_name": "docker", "display_name": "Docker", "category": "DevOps"}},
            {"id": "gap5", "user_id": "user1", "analysis_result_id": "ana1", "skill_id": "skill_sql", "target_role": "AI/ML Engineer", "required_level": 0.8, "current_proficiency": 0.5, "confidence": 0.65, "gap": 0.3, "importance": 0.8, "demand": 0.85, "interview_relevance": 0.7, "priority_score": 15.0, "explanation": "gap sql", "skills": {"canonical_name": "sql", "display_name": "SQL", "category": "Database"}},
        ],
        "skills": [
            {"id": "skill_python", "canonical_name": "python", "display_name": "Python", "category": "Programming"},
            {"id": "skill_dsa", "canonical_name": "dsa", "display_name": "Data Structures & Algorithms", "category": "Core CS"},
            {"id": "skill_ml", "canonical_name": "machine_learning", "display_name": "Machine Learning", "category": "ML"},
            {"id": "skill_docker", "canonical_name": "docker", "display_name": "Docker", "category": "DevOps"},
            {"id": "skill_sql", "canonical_name": "sql", "display_name": "SQL", "category": "Database"},
        ],
        "roadmaps": [],
        "roadmap_items": [],
        "roadmap_resources": [],
        "roadmap_milestones": [],
    }

    # Helper fake query builder
    class FakeQuery:
        def __init__(self, table, store):
            self.table = table
            self.store = store
            self.filters = []
            self.order_col = None
            self.order_desc = False
            self.limit_n = None
            self.single_flag = False
            self.select_args = ""

        def select(self, *args, **kwargs):
            if args:
                self.select_args = " ".join(str(a) for a in args)
            return self
        def eq(self, col, val):
            self.filters.append((col, val))
            return self
        def order(self, col, desc=False, **kwargs):
            self.order_col = col
            self.order_desc = desc
            return self
        def limit(self, n):
            self.limit_n = n
            return self
        def single(self):
            self.single_flag = True
            return self
        def update(self, data):
            # For update, store data and apply on execute
            self._update_data = data
            return self
        def insert(self, data):
            self._insert_data = data
            # Simulate insert: create id if missing
            import uuid
            if isinstance(data, dict):
                if "id" not in data:
                    data["id"] = str(uuid.uuid4())
                # Ensure timestamps
                store[self.table].append(data)
                self._insert_result = [data]
            else:
                self._insert_result = data
            return self
        def delete(self):
            return self
        def execute(self):
            # Handle update case
            if hasattr(self, "_update_data"):
                # Apply to matching rows
                matched = self._apply_filters(store.get(self.table, []))
                for row in matched:
                    row.update(self._update_data)
                # Return updated rows
                return type("obj", (), {"data": matched})()
            if hasattr(self, "_insert_result"):
                return type("obj", (), {"data": self._insert_result})()
            # Select case
            data = store.get(self.table, [])
            filtered = self._apply_filters(data)
            # Simulate join for roadmap_items + roadmaps
            if self.table == "roadmap_items" and "roadmaps" in self.select_args:
                enriched = []
                for row in filtered:
                    roadmap = next((r for r in store.get("roadmaps", []) if r["id"] == row.get("roadmap_id")), None)
                    new_row = dict(row)
                    if roadmap:
                        new_row["roadmaps"] = {"user_id": roadmap["user_id"]}
                    else:
                        new_row["roadmaps"] = None
                    enriched.append(new_row)
                filtered = enriched
            if self.order_col:
                # Simple sort
                try:
                    filtered = sorted(filtered, key=lambda x: x.get(self.order_col, ""), reverse=self.order_desc)
                except:
                    pass
            if self.limit_n is not None:
                filtered = filtered[:self.limit_n]
            if self.single_flag:
                if not filtered:
                    raise Exception("0 rows")
                return type("obj", (), {"data": filtered[0]})()
            return type("obj", (), {"data": filtered})()

        def _apply_filters(self, data):
            res = data
            for col, val in self.filters:
                res = [r for r in res if r.get(col) == val]
            return res

    class FakeClient:
        def table(self, name):
            # Map names used in code
            mapping = {
                "profiles": "profiles",
                "analysis_results": "analysis_results",
                "skill_gaps": "skill_gaps",
                "skills": "skills",
                "roadmaps": "roadmaps",
                "roadmap_items": "roadmap_items",
                "roadmap_resources": "roadmap_resources",
                "roadmap_milestones": "roadmap_milestones",
            }
            t = mapping.get(name, name)
            return FakeQuery(t, store)
        def __getattr__(self, name):
            # For storage etc fallback
            raise AttributeError(name)

    fake_client = FakeClient()
    monkeypatch.setattr(rs, "_client", lambda: fake_client)
    # Patch profile_service.get_profile to use store
    import app.services.profile_service as ps
    monkeypatch.setattr(ps, "get_profile", lambda uid: store["profiles"].get(uid))
    monkeypatch.setattr(rs.profile_service, "get_profile", lambda uid: store["profiles"].get(uid))

    # Step 1-2: profile exists, analysis completed -> already mocked

    # Step 4: Generate roadmap
    result = asyncio.run(rs.generate_roadmap("user1", "AI/ML Engineer"))

    # Step 5: Verify roadmap exists
    assert result is not None
    assert result["target_role"] == "AI/ML Engineer"
    assert result["engine_version"] == "4D-v1"
    assert len(store["roadmaps"]) == 1
    roadmap_id = result["id"]

    # Step 6: Verify items exist (3-6 items, we expect 5 gaps -> 5 items limited to 6)
    assert len(store["roadmap_items"]) >= 3 and len(store["roadmap_items"]) <= 6
    assert len(store["roadmap_items"]) == 5  # we had 5 gaps
    # Verify ordering by priority: highest priority first (ml 35, dsa 32, python 28, sql 15, docker 12)
    items_sorted = sorted(store["roadmap_items"], key=lambda x: x["sequence_order"])
    # First should be machine_learning (priority 35)
    assert items_sorted[0]["skill_id"] == "skill_ml"
    assert items_sorted[0]["sequence_order"] == 1

    # Step 7: Verify milestones exist
    assert len(store["roadmap_milestones"]) >= 1
    # For 5 items we expect 3 milestones
    assert len(store["roadmap_milestones"]) == 3

    # Step 8: Verify resources exist (1-3 per item)
    assert len(store["roadmap_resources"]) >= len(store["roadmap_items"])  # at least 1 per item
    for it in store["roadmap_items"]:
        res_for_item = [r for r in store["roadmap_resources"] if r["roadmap_item_id"] == it["id"]]
        assert 1 <= len(res_for_item) <= 3
        for r in res_for_item:
            assert r["url"].startswith("https://")
            assert r["resource_type"] in ("course","documentation","tutorial","article","video","practice","project_reference")

    # Step 9: Verify estimated weeks = ceil(total_hours / hours_per_week)
    total = result["total_estimated_hours"]
    weeks = result["estimated_weeks"]
    assert weeks == math.ceil(total / 5)

    # Step 10: Update an item to completed, verify progress changes
    first_item_id = items_sorted[0]["id"]
    # Initial progress should be 0
    assert result["progress"] == 0
    updated = rs.update_roadmap_item("user1", first_item_id, {"completion_percentage": 100, "status": "completed"})
    assert updated["completion_percentage"] == 100
    assert updated["status"] == "completed"
    # Verify progress recalculates: 1 of 5 items at 100 => 20%
    new_progress = rs.calculate_progress(store["roadmap_items"])
    assert new_progress == pytest.approx(20.0)

    # Step 12: Verify another user cannot access it
    store["profiles"]["user2"] = {"user_id": "user2", "hours_per_week": 10, "full_name": "Other", "college": "Y", "degree": "B.Tech", "branch": "ECE", "current_year": "2nd", "graduation_year": 2027, "career_interests": ["Backend Developer"], "profile_completed": True}
    with pytest.raises(HTTPException) as exc:
        rs.get_items_for_roadmap("user2", roadmap_id)
    assert exc.value.status_code in (403,404)
    with pytest.raises(HTTPException) as exc2:
        rs.update_roadmap_item("user2", first_item_id, {"completion_percentage": 50})
    assert exc2.value.status_code in (403,404)

    # Additional: check why_it_matters contains actual values
    for it in store["roadmap_items"]:
        assert "is prioritized because" in it["why_it_matters"]
        assert "confidence" in it["why_it_matters"].lower()
