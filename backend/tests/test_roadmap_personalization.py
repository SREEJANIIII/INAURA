"""
Tests for Roadmap Personalization Engine:
- Answers the 10 personalized questions for each skill gap.
- Answers the 5 Whys ("Why am I learning this?", "Why now?", "Why this much time?", "Why this resource?", "How will INAURA know that I learned it?").
- Verifies demonstrated capabilities vs missing capabilities from evidence.
- Verifies generalized behavior across canonical skills (REST APIs, SQL, Machine Learning, etc.) and fallback skills.
- Verifies deterministic, evidence-traceable explanations.
"""

import pytest
from app.services import roadmap_personalization_service as rps
from app.services.learner_state_service import LearnerSkillState


def _sig(skill, strength=0.75, depth=3, source="github", metadata=None):
    return {
        "skill": skill,
        "canonical_name": skill,
        "source": source,
        "source_type": source,
        "signal_strength": strength,
        "signal_value": strength,
        "depth": depth,
        "metadata": metadata or {},
    }


def test_rest_apis_personalization_demonstrates_and_misses():
    """
    Given FastAPI & Express backend with CRUD endpoints and JWT auth evidence:
    - Demonstrates: CRUD routes, framework usage, JWT auth
    - Misses: pagination, rate limiting, error handling, versioning
    """
    grouped_signals = {
        "REST APIs": [
            _sig("REST APIs", depth=3, metadata={
                "project_name": "task-api",
                "relevant_files": ["app/api/v1/routes.py", "app/main.py"],
                "detected_usage_patterns": ["fastapi_app", "route_decorator", "api_router"],
            }),
            _sig("REST APIs", depth=3, source="github", metadata={
                "project_name": "express-backend",
                "relevant_files": ["server/routes/auth.js"],
                "detected_usage_patterns": ["express_route"],
            }),
        ],
        "Application Security": [
            _sig("Application Security", depth=3, metadata={"project_name": "express-backend", "relevant_files": ["middleware/jwt.js"]}),
        ],
    }

    gap = {
        "skill_id": "skill_rest",
        "canonical_name": "rest_apis",
        "current_proficiency": 0.55,
        "required_level": 0.80,
        "gap": 0.25,
        "importance": 0.90,
        "demand": 0.85,
        "interview_relevance": 0.85,
        "confidence": 0.82,
        "priority_score": 45.0,
    }

    learner_states = {
        "python": LearnerSkillState(
            user_id="test-user",
            skill_slug="python",
            skill_name="Python",
            state_classification="KNOWN",
            proficiency=0.85,
            confidence=0.90,
            required_level=0.80,
            gap=0.0,
            evidence_coverage=0.9,
            evidence_strength=0.85,
            evidence_count=5,
            evidence_depth=4,
            evidence_recency_days=10,
            active_sources=["github"],
            evidence_ids=["ev-1"],
            reasoning="Verified via assessments",
        )
    }

    explanation = rps.build_skill_personalization(
        gap_dict=gap,
        target_role="Backend Developer",
        user_hours_per_week=10,
        learner_states=learner_states,
        grouped_signals=grouped_signals,
        skills_map={},
    )

    # 1. Check basic percentages and stats
    assert explanation["current_proficiency_pct"] == 55
    assert explanation["required_level_pct"] == 80
    assert explanation["gap_pct"] == 25
    assert explanation["confidence_pct"] == 82
    assert explanation["importance_pct"] == 90

    # 2. Demonstrated vs Missing capabilities
    dem = explanation["demonstrated_capabilities"]
    miss = explanation["missing_capabilities"]

    assert any("framework" in d.lower() or "rest" in d.lower() or "endpoint" in d.lower() for d in dem)
    assert any("validation" in m.lower() or "error" in m.lower() or "rate" in m.lower() or "document" in m.lower() for m in miss)

    # 3. Traceable supporting evidence
    ev = explanation["supporting_evidence"]
    assert any("task-api" in e or "express-backend" in e for e in ev)

    # 4. Five Whys check
    five_whys = explanation["five_whys"]
    assert "Backend Developer" in five_whys["why_learning"]
    assert "55%" in five_whys["why_learning"]
    assert "80%" in five_whys["why_learning"]
    assert "priority" in five_whys["why_now"].lower()
    assert "hours allocated" in five_whys["why_time"].lower()
    assert "missing capabilities" in five_whys["why_resource"].lower()
    assert "how_validated" in five_whys

    # 5. Readable summary block
    summary = explanation["readable_summary"]
    assert "Skill: Rest Apis" in summary or "Skill: REST APIs" in summary
    assert "Current proficiency: 55%" in summary
    assert "Confidence: 82%" in summary
    assert "Gap: 25 percentage points" in summary
    assert "Evidence:" in summary
    assert "Missing evidence:" in summary
    assert "Validation criteria:" in summary


def test_sql_personalization_with_query_evidence():
    """
    Given student has basic SELECT query evidence but lacks transactions & indexing.
    """
    grouped_signals = {
        "SQL": [
            _sig("SQL", depth=3, metadata={
                "project_name": "analytics-tool",
                "relevant_files": ["queries/reports.sql"],
                "detected_usage_patterns": ["sql_select", "sql_query"],
            }),
        ],
    }

    gap = {
        "skill_id": "skill_sql",
        "canonical_name": "sql",
        "current_proficiency": 0.40,
        "required_level": 0.75,
        "gap": 0.35,
        "importance": 0.85,
        "demand": 0.80,
        "interview_relevance": 0.75,
        "confidence": 0.65,
        "priority_score": 38.0,
    }

    explanation = rps.build_skill_personalization(
        gap_dict=gap,
        target_role="Data Engineer",
        user_hours_per_week=15,
        learner_states={},
        grouped_signals=grouped_signals,
        skills_map={},
    )

    assert explanation["gap_pct"] == 35
    assert len(explanation["demonstrated_capabilities"]) >= 1
    # Missing should include optimization / transactions
    assert any("optimize" in m.lower() or "schema" in m.lower() or "modify" in m.lower() for m in explanation["missing_capabilities"])
    assert "analytics-tool" in str(explanation["supporting_evidence"])


def test_zero_evidence_skill_is_honest():
    """
    When user has zero evidence for a skill:
    - Reports zero evidence honestly (does not claim confirmed inability).
    - Prescribes diagnostic learning unit.
    - Low confidence with diagnostic rationale.
    """
    gap = {
        "skill_id": "skill_k8s",
        "canonical_name": "kubernetes",
        "current_proficiency": 0.0,
        "required_level": 0.70,
        "gap": 0.70,
        "importance": 0.75,
        "demand": 0.80,
        "interview_relevance": 0.65,
        "confidence": 0.10,
        "priority_score": 25.0,
    }

    explanation = rps.build_skill_personalization(
        gap_dict=gap,
        target_role="DevOps Engineer",
        user_hours_per_week=10,
        learner_states={},
        grouped_signals={},
        skills_map={},
    )

    assert explanation["current_proficiency_pct"] == 0
    assert explanation["confidence_pct"] == 10
    assert len(explanation["demonstrated_capabilities"]) == 0
    assert len(explanation["missing_capabilities"]) >= 2
    assert "diagnostic" in explanation["confidence_rationale"].lower()
    assert "No active implementation evidence" in explanation["supporting_evidence"][0]


def test_personalize_tasks_targets_missing_areas():
    """
    Verifies that personalize_tasks_for_skill updates task titles and descriptions
    to focus directly on the missing capabilities rather than generic labels.
    """
    raw_tasks = [
        {"task_type": "learn", "title": "Learn Skill", "description": "Study basics", "estimated_minutes": 60},
        {"task_type": "practice", "title": "Practice Skill", "description": "Practice exercises", "estimated_minutes": 90},
        {"task_type": "build", "title": "Build Project", "description": "Build project", "estimated_minutes": 180},
        {"task_type": "validate", "title": "Validate", "description": "Verify code", "estimated_minutes": 60},
    ]

    explanation = {
        "skill_name": "REST APIs",
        "gap_pct": 25,
        "confidence_pct": 82,
        "demonstrated_capabilities": ["FastAPI routing", "CRUD endpoints"],
        "missing_capabilities": ["Cursor pagination", "Token-bucket rate limiting"],
        "validation_criteria": "Submit API repo with 429 rate limit test suite",
    }

    customized = rps.personalize_tasks_for_skill("rest_apis", raw_tasks, explanation)

    assert "Cursor pagination" in customized[0]["title"] or "Cursor pagination" in customized[0]["description"]
    assert "Cursor pagination" in customized[1]["title"] or "Cursor pagination" in customized[1]["description"]
    assert customized[3]["validation_method"] == "Submit API repo with 429 rate limit test suite"
    assert customized[0]["personalization_context"]["primary_gap"] == "Cursor pagination"
