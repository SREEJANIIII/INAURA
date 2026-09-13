"""
Phase 4: evidence provenance and traceability tests.

Verifies every skill assessment is explainable back through the chain:
Skill Score -> Skill -> Signals -> Evidence -> Source -> Repository ->
Relevant file/artifact -> Evidence depth/reason.

Builds on the existing provenance structures (ExtractedSignal,
build_evidence_sources, per-signal metadata); scoring formulas unchanged.
"""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from app.services.evidence.base import EvidenceDepth
from app.services.evidence.github import GitHubProvider
from app.services import analysis_run_service as ars
from app.services import signal_extractor as se
from app.services import skill_engine


def _run(coro):
    return asyncio.run(coro)


def _repo_meta(owner, name, **overrides):
    meta = {
        "id": abs(hash(name)) % 10_000_000,
        "name": name,
        "full_name": f"{owner}/{name}",
        "html_url": f"https://github.com/{owner}/{name}",
        "description": "",
        "language": None,
        "fork": False,
        "archived": False,
        "disabled": False,
        "size": 2500,
        "default_branch": "main",
        "topics": [],
        "pushed_at": datetime.now(timezone.utc).isoformat(),
        "stargazers_count": 0,
    }
    meta.update(overrides)
    return meta


def _inspection_repo(owner, name, inspection, **meta):
    base = _repo_meta(owner, name, **meta)
    base["inspection"] = inspection
    return base


def _verify_mock(owner, repos):
    return _run(GitHubProvider().verify(
        {"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}
    ))


def _direct(owner, repo, inspection):
    return GitHubProvider()._build_result_from_inspection(
        owner, repo, inspection, datetime.now(timezone.utc)
    )


def _python_repo(name="svc"):
    return {
        "name": name,
        "languages": {"Python": 40000},
        "root_files": ["requirements.txt"],
        "top_files": ["backend/api/users.py", "backend/services/auth.py",
                      "tests/test_auth.py"],
        "python_deps": ["fastapi", "pytest"],
        "import_tokens": {"fastapi": 4},
        "source_files_sampled": ["backend/api/users.py", "backend/services/auth.py"],
        "usage_patterns": {"REST APIs": {"fastapi_app": 2, "route_decorator": 1}},
        "usage_files": {"REST APIs": ["backend/api/users.py", "backend/services/auth.py"]},
        "tree_scanned": True,
        "ext_file_counts": {".py": 4},
        "has_workflows": True,
    }


# ---------------------------------------------------------------------------
# 1. Per-repo signals carry traceability provenance (compact, no contents)
# ---------------------------------------------------------------------------

def test_per_repo_signal_provenance_keys():
    res = _direct("dev", "svc", _python_repo())
    assert res.signals
    for sig in res.signals:
        m = sig.metadata
        for key in ("provider", "repository_name", "source_url", "relevant_files",
                    "evidence_depth", "reason", "usage_status", "file_importance",
                    "observed_at"):
            assert key in m, f"missing provenance '{key}' for {sig.skill}"
        assert m["provider"] == "github"
        assert m["source_url"] == "https://github.com/dev/svc"
        assert m["evidence_depth"] == sig.depth
        assert m["reason"] == sig.reason
        assert isinstance(m["relevant_files"], list) and m["relevant_files"]
        assert isinstance(m["observed_at"], str) and m["observed_at"]


def test_per_repo_provenance_is_compact_and_safe():
    res = _direct("dev", "svc", _python_repo())
    for sig in res.signals:
        blob = json.dumps(sig.metadata, default=str)
        # Compact: paths/labels/reasons only, far below any source dump.
        assert len(blob) < 6000, f"provenance too large for {sig.skill}"
        # No full source-code contents stored as provenance.
        for banned in ("readme_text", "config_text", "import_tokens", "source_texts"):
            assert banned not in sig.metadata
        assert len(sig.metadata.get("relevant_files", [])) <= 10
        assert len(sig.metadata.get("files_analyzed", [])) <= 10


# ---------------------------------------------------------------------------
# 2. Aggregation preserves provenance (union files, max status/importance)
# ---------------------------------------------------------------------------

def test_aggregated_signal_provenance():
    owner = "prov_dev"
    repos = [
        _inspection_repo(owner, "svc-a", _python_repo("svc-a")),
        _inspection_repo(owner, "svc-b", {
            "name": "svc-b",
            "languages": {"Python": 15000},
            "root_files": ["requirements.txt"],
            "top_files": ["worker.py"],
            "python_deps": ["celery"],
            "tree_scanned": True,
            "ext_file_counts": {".py": 1},
        }),
    ]
    res = _verify_mock(owner, repos)
    by_skill = {s.skill: s for s in res.signals}
    assert "Python" in by_skill
    py = by_skill["Python"]
    m = py.metadata
    assert m["source_url"] == f"https://github.com/{owner}"
    assert m["observed_at"]
    assert m["evidence_depth"] == py.depth
    assert m["evidence_count"] == 2
    assert m["usage_status"] in ("used", "substantial", "imported", "declared")
    assert m["file_importance"] in ("high", "very_high", "medium")
    assert isinstance(m["relevant_files"], list) and m["relevant_files"]
    # Per-repository entries trace back to repo, files, depth, reason.
    assert len(m["repositories"]) == 2
    for entry in m["repositories"]:
        for key in ("full_name", "url", "depth", "files", "usage_status",
                    "file_importance", "reason"):
            assert key in entry
        assert entry["url"].startswith("https://github.com/")
        assert isinstance(entry["files"], list) and len(entry["files"]) <= 5


def test_aggregated_uses_max_usage_status():
    owner = "status_dev"
    repos = [
        _inspection_repo(owner, "dep-only", {
            "name": "dep-only", "languages": {},
            "root_files": ["package.json"], "top_files": [],
            "package_json_deps": ["react"], "tree_scanned": True,
        }),
        _inspection_repo(owner, "app", {
            "name": "app", "languages": {"TypeScript": 40000},
            "root_files": ["package.json"],
            "top_files": ["src/App.tsx", "src/components/Card.tsx"],
            "package_json_deps": ["react"],
            "import_tokens": {"react": 4},
            "source_files_sampled": ["src/App.tsx", "src/components/Card.tsx"],
            "usage_patterns": {"React": {"hook_useState": 2, "jsx_component": 2}},
            "usage_files": {"React": ["src/App.tsx", "src/components/Card.tsx"]},
            "tree_scanned": True, "ext_file_counts": {".tsx": 2},
            "has_workflows": True,
        }),
    ]
    res = _verify_mock(owner, repos)
    react = {s.skill: s for s in res.signals}["React"]
    # Strongest demonstration wins, still one signal.
    assert react.metadata["usage_status"] == "substantial"
    assert react.metadata["evidence_count"] == 2
    assert len([s for s in res.signals if s.skill == "React"]) == 1


# ---------------------------------------------------------------------------
# 3. build_evidence_sources preserves provenance (GitHub branch)
# ---------------------------------------------------------------------------

def test_build_evidence_sources_preserves_github_provenance():
    owner = "src_dev"
    res = _verify_mock(owner, [_inspection_repo(owner, "svc", _python_repo())])
    signals = se.extract_signals([{
        "id": "ev1", "evidence_type": "github",
        "source_url": f"https://github.com/{owner}",
        "verification_status": "verified",
        "metadata": {
            "verification_status": "verified",
            "verified_signals": [s.to_dict() for s in res.signals],
        },
    }], [], [])
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, None))
    req_map = ars.build_requirements_map(
        [{"skill": "Python", "required_level": 0.7, "importance": 0.8}], None)
    assessments = {a["canonical_name"]: a for a in ars.calculate_assessments(grouped, req_map, None)}
    py = assessments["Python"]
    gh = next(s for s in py["evidence_sources"] if s["source_type"] == "github")
    d = gh["details"]
    for key in ("relevant_files", "usage_status", "file_importance",
                "evidence_depth", "repositories", "evidence_count"):
        assert key in d, f"provenance '{key}' lost in evidence_sources"
    assert gh["usage_status"]
    assert gh["evidence_depth"] == gh["details"]["evidence_depth"]
    assert gh["explanation"]
    assert d["source_url"] == f"https://github.com/{owner}"
    assert len(d["relevant_files"]) <= 10
    assert len(d.get("detected_usage_patterns", [])) <= 8


def test_legacy_signals_without_provenance_still_work():
    # Old cached verified_signals predate Phases 2-4 keys: must not crash,
    # must degrade gracefully (backward compatibility).
    signals = se.extract_signals([{
        "id": "ev-old", "evidence_type": "github",
        "source_url": "https://github.com/old/repo",
        "verification_status": "verified",
        "metadata": {
            "verification_status": "verified",
            "verified_signals": [{
                "skill": "Python", "signal_strength": 0.75,
                "depth": 3, "reason": "old inspection",
                "source_reliability": 0.40, "metadata": {},
            }],
        },
    }], [], [])
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, None))
    req_map = ars.build_requirements_map(
        [{"skill": "Python", "required_level": 0.7, "importance": 0.8}], None)
    assessments = ars.calculate_assessments(grouped, req_map, None)
    assert assessments[0]["evidence_sources"]
    gh = assessments[0]["evidence_sources"][0]
    assert gh["source_type"] == "github"
    assert gh["usage_status"] == ""
    assert assessments[0]["proficiency"] > 0


# ---------------------------------------------------------------------------
# 4. Full pipeline: assessment answers "why this score?"
# ---------------------------------------------------------------------------

def _requirements():
    return [
        {"skill": "Python", "required_level": 0.75, "importance": 0.85,
         "demand": 0.80, "interview_relevance": 0.75},
    ]


def test_explanation_answers_why():
    owner = "why_dev"
    res = _verify_mock(owner, [_inspection_repo(owner, "svc", _python_repo())])
    evidence = [{
        "id": "ev-gh", "evidence_type": "github",
        "source_url": f"https://github.com/{owner}",
        "verification_status": "verified",
        "metadata": {
            "verification_status": "verified",
            "verified_signals": [s.to_dict() for s in res.signals],
        },
    }]
    leetcode = se.make_signal("Python", "leetcode", 0.60, "84 Python submissions",
                              metadata={"solved": 84})
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    from app.services.assessment import service as assessment_service
    assess_sig = assessment_service.build_assessment_signals([{
        "id": "att-1", "skill_name": "Python", "status": "completed",
        "validity": "valid", "score": 0.80, "correct_count": 4,
        "question_count": 5, "assessment_version": "assessment-v1",
        "completed_at": now.isoformat(),
    }])[0]

    raw = se.extract_signals(evidence, [], [])
    grouped = ars.aggregate_skills(ars.normalize_signals(raw + [leetcode, assess_sig], None))
    req_map = ars.build_requirements_map(_requirements(), None)
    assessments = {a["canonical_name"]: a for a in ars.calculate_assessments(grouped, req_map, None)}
    py = assessments["Python"]

    expl = ars.build_skill_evidence_explanation(py)
    assert expl["skill"] == "Python"
    assert expl["proficiency"] == pytest.approx(py["proficiency"])
    assert expl["confidence"] == pytest.approx(py["confidence"])
    # The summary names the skill and its score.
    assert "Python" in expl["summary"]
    assert str(int(round(py["proficiency"] * 100))) in expl["summary"]
    # Every source traces provider -> repository -> files -> depth -> reason.
    providers = {s["provider"] for s in expl["evidence_sources"]}
    assert {"github", "leetcode", "assessment"} <= providers
    for src in expl["evidence_sources"]:
        for key in ("provider", "repository", "files", "depth", "reason"):
            assert key in src
        assert isinstance(src["files"], list) and len(src["files"]) <= 5
    gh = next(s for s in expl["evidence_sources"] if s["provider"] == "github")
    assert gh["repository_url"].startswith("https://github.com/")
    assert gh["depth"] in (2, 3, 4)
    assert gh["reason"]


def test_explanation_with_no_evidence():
    grouped = ars.aggregate_skills(ars.normalize_signals([], None))
    req_map = ars.build_requirements_map(_requirements(), None)
    assessments = {a["canonical_name"]: a for a in ars.calculate_assessments(grouped, req_map, None)}
    expl = ars.build_skill_evidence_explanation(assessments["Python"])
    assert expl["skill"] == "Python"
    assert expl["proficiency"] == 0.0
    assert expl["evidence_sources"] == []
    assert "Python" in expl["summary"]


def test_scoring_formula_untouched_by_provenance():
    # Same evidence strengths with and without provenance keys -> same score.
    bare = se.make_signal("Python", "github", 0.75, "repo impl", metadata={})
    rich = se.make_signal("Python", "github", 0.75, "repo impl", metadata={
        "provider": "github", "repository_name": "svc",
        "source_url": "https://github.com/dev/svc",
        "relevant_files": ["a.py", "b.py"], "evidence_depth": 3,
        "reason": "repo impl", "usage_status": "used",
        "file_importance": "high", "observed_at": "2026-01-01T00:00:00+00:00",
    })
    prof_bare, _, _, _ = skill_engine.proficiency([bare])
    prof_rich, _, _, _ = skill_engine.proficiency([rich])
    assert prof_bare == pytest.approx(prof_rich) == pytest.approx(0.75)
