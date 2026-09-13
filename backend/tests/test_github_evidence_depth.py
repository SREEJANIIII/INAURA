"""
Layered GitHub evidence-depth tests (incremental improvement).

Pins the five-level distinction without replacing existing analysis:

  L1 mention       - README/description/topics only ("Built with React")
  L2 dependency    - declared in package.json/requirements (never imported)
  L3 implementation- imported/configured in >=1 sampled source file
  L4 substantial   - used across multiple files/patterns (+ tests/workflows)

Also covers: comment stripping, vendor/generated exclusion, structured
metadata, multi-file and mixed-technology repositories, and end-to-end flow
through signal_extractor -> normalize -> aggregate -> skill_engine.

Conceptual framing (no overclaim):
"INAURA performs repository-level code and artifact inspection to extract
evidence of demonstrated technical skills."
"""

import asyncio
from datetime import datetime, timezone

import pytest

from app.services.evidence.base import EvidenceDepth
from app.services.evidence.github import (
    GitHubProvider,
    _is_skippable_path,
    _strip_code_comments,
    detect_usage_patterns,
    extract_import_tokens,
)
from app.services import analysis_run_service as ars
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


# ---------------------------------------------------------------------------
# 1. README-only -> Level 1 weak (per-repo), rejected at profile aggregation
# ---------------------------------------------------------------------------

def test_readme_only_is_level1_weak():
    res = _direct("dev", "site", {
        "name": "site",
        "description": "",
        "readme_text": "Built with React",
        "languages": {},
        "root_files": ["README.md"],
        "top_files": [],
        "tree_scanned": True,
    })
    by_skill = {s.skill: s for s in res.signals}
    assert "React" in by_skill
    sig = by_skill["React"]
    assert sig.depth == EvidenceDepth.LEVEL_1_MENTION
    assert sig.signal_strength == pytest.approx(0.40)
    assert sig.metadata.get("evidence_kind") == "documentation"
    assert sig.metadata.get("documentation_only") is True


def test_readme_only_rejected_at_profile_aggregation():
    owner = "readme_only_dev"
    repos = [
        _inspection_repo(owner, "notes", {
            "name": "notes",
            "readme_text": "Built with React. React is great.",
            "description": "React notes",
            "languages": {},
            "root_files": ["README.md"],
            "top_files": [],
            "tree_scanned": True,
        })
    ]
    res = _verify_mock(owner, repos)
    assert "React" not in {s.skill for s in res.signals}


# ---------------------------------------------------------------------------
# 2. Dependency-only -> Level 2
# ---------------------------------------------------------------------------

def test_dependency_only_is_level2():
    res = _direct("dev", "web", {
        "name": "web",
        "description": "",
        "readme_text": "",
        "languages": {},
        "root_files": ["package.json"],
        "top_files": [],
        "package_json_deps": ["react"],
        "tree_scanned": True,
    })
    by_skill = {s.skill: s for s in res.signals}
    assert "React" in by_skill
    sig = by_skill["React"]
    assert sig.depth == EvidenceDepth.LEVEL_2_CONFIG
    assert sig.signal_strength == pytest.approx(0.60)
    assert sig.metadata.get("evidence_kind") == "dependency_manifest"


def test_dependency_only_profile_keeps_weak_level2():
    owner = "dep_only_dev"
    repos = [
        _inspection_repo(owner, "dep-only", {
            "name": "dep-only",
            "languages": {},
            "root_files": ["package.json"],
            "top_files": [],
            "package_json_deps": ["react"],
            "tree_scanned": True,
        })
    ]
    res = _verify_mock(owner, repos)
    by_skill = {s.skill: s for s in res.signals}
    assert "React" in by_skill
    assert by_skill["React"].depth == EvidenceDepth.LEVEL_2_CONFIG


def test_installed_but_never_used_remains_weak():
    """A declared dependency without imports/patterns must not reach L3/L4."""
    dep_only = _direct("dev", "dep", {
        "name": "dep",
        "languages": {},
        "root_files": ["package.json"],
        "top_files": [],
        "package_json_deps": ["react"],
        "import_tokens": {},
        "source_files_sampled": [],
        "tree_scanned": True,
    })
    dep_sig = {s.skill: s for s in dep_only.signals}["React"]
    used = _direct("dev", "used", {
        "name": "used",
        "languages": {"TypeScript": 20000},
        "root_files": ["package.json"],
        "top_files": ["src/App.tsx"],
        "package_json_deps": ["react"],
        "import_tokens": {"react": 2},
        "source_files_sampled": ["src/App.tsx"],
        "tree_scanned": True,
        "ext_file_counts": {".tsx": 1},
    })
    used_sig = {s.skill: s for s in used.signals}["React"]
    assert dep_sig.depth == EvidenceDepth.LEVEL_2_CONFIG
    assert used_sig.depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert dep_sig.signal_strength < used_sig.signal_strength


# ---------------------------------------------------------------------------
# 3. Import/usage -> Level 3
# ---------------------------------------------------------------------------

def test_import_usage_is_level3():
    res = _direct("dev", "app", {
        "name": "app",
        "description": "",
        "languages": {"TypeScript": 15000},
        "root_files": ["package.json"],
        "top_files": ["src/App.jsx"],
        "package_json_deps": ["react"],
        "import_tokens": {"react": 1},
        "source_files_sampled": ["src/App.jsx"],
        "tree_scanned": True,
        "ext_file_counts": {".jsx": 1},
    })
    sig = {s.skill: s for s in res.signals}["React"]
    assert sig.depth == EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert sig.signal_strength == pytest.approx(0.75)
    assert sig.metadata.get("evidence_kind") == "source_usage"
    assert int(sig.metadata.get("usage_count", 0)) >= 1


def test_usage_pattern_detection_hooks_and_components():
    src = (
        "import React, { useState, useEffect } from 'react';\n"
        "function UserCard({ user }) {\n"
        "  const [count, setCount] = useState(0);\n"
        "  useEffect(() => { document.title = user.name; }, [user]);\n"
        "  return <div className=\"card\"><Avatar user={user} /></div>;\n"
        "}\n"
    )
    hits = detect_usage_patterns(src)
    assert "React" in hits
    assert "hook_useState" in hits["React"]
    assert "hook_useEffect" in hits["React"]
    assert any(p in hits["React"] for p in ("jsx_component", "component_func", "jsx_attr"))


# ---------------------------------------------------------------------------
# 4. Substantial multi-file implementation -> Level 4
# ---------------------------------------------------------------------------

def test_substantial_implementation_is_level4():
    res = _direct("dev", "dashboard", {
        "name": "dashboard",
        "description": "",
        "languages": {"TypeScript": 60000},
        "root_files": ["package.json"],
        "top_files": ["src/App.tsx", "src/components/UserCard.tsx", "src/routes/Home.tsx", "tests/app.test.tsx"],
        "package_json_deps": ["react", "react-dom", "react-router-dom", "typescript", "jest", "tailwindcss"],
        "import_tokens": {"react": 5, "react-router-dom": 2},
        "source_files_sampled": ["src/App.tsx", "src/components/UserCard.tsx", "src/routes/Home.tsx"],
        "usage_patterns": {"React": {"hook_useState": 2, "hook_useEffect": 2, "jsx_component": 3, "router": 1}},
        "usage_files": {"React": ["src/App.tsx", "src/components/UserCard.tsx", "src/routes/Home.tsx"]},
        "tree_scanned": True,
        "ext_file_counts": {".tsx": 6, ".ts": 2},
        "has_workflows": True,
    })
    sig = {s.skill: s for s in res.signals}["React"]
    assert sig.depth == EvidenceDepth.LEVEL_4_SUBSTANTIAL
    assert sig.signal_strength == pytest.approx(0.85)
    assert len(sig.metadata.get("relevant_files", [])) >= 2
    assert len(sig.metadata.get("detected_usage_patterns", [])) >= 2


def test_multiple_implementation_files_stronger_than_single():
    single = _direct("dev", "single", {
        "name": "single",
        "languages": {"TypeScript": 15000},
        "root_files": ["package.json"],
        "top_files": ["src/App.tsx"],
        "package_json_deps": ["react"],
        "import_tokens": {"react": 1},
        "source_files_sampled": ["src/App.tsx"],
        "tree_scanned": True,
        "ext_file_counts": {".tsx": 1},
    })
    multi = _direct("dev", "multi", {
        "name": "multi",
        "languages": {"TypeScript": 60000},
        "root_files": ["package.json"],
        "top_files": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"],
        "package_json_deps": ["react"],
        "import_tokens": {"react": 5},
        "source_files_sampled": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"],
        "usage_patterns": {"React": {"hook_useState": 3, "jsx_component": 3}},
        "usage_files": {"React": ["src/App.tsx", "src/components/A.tsx", "src/components/B.tsx"]},
        "tree_scanned": True,
        "ext_file_counts": {".tsx": 4},
        "has_workflows": True,
    })
    s_single = {s.skill: s for s in single.signals}["React"]
    s_multi = {s.skill: s for s in multi.signals}["React"]
    assert s_single.depth == EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert s_multi.depth == EvidenceDepth.LEVEL_4_SUBSTANTIAL
    assert s_multi.signal_strength > s_single.signal_strength


# ---------------------------------------------------------------------------
# 5. False positives: comments, vendor, lock, build output
# ---------------------------------------------------------------------------

def test_commented_imports_are_ignored():
    text = (
        "# import pandas as pd\n"
        "// import React from 'react'\n"
        "/* import os */\n"
        "<!-- import something -->\n"
        "from fastapi import FastAPI\n"
    )
    tokens = extract_import_tokens(text)
    assert "fastapi" in tokens
    assert "pandas" not in tokens
    assert "react" not in tokens
    assert "os" not in tokens


def test_commented_hooks_are_not_usage():
    commented = "// useState(0)\n# useEffect(() => {})\n/* <MyComponent /> */\nconst x = 1;\n"
    assert detect_usage_patterns(commented).get("React", []) == []
    real = "import { useState } from 'react';\nconst [x] = useState(0);\n"
    assert "hook_useState" in detect_usage_patterns(real)["React"]


def test_strip_code_comments_handles_common_styles():
    assert "import" not in _strip_code_comments("# import pandas")
    assert "import" not in _strip_code_comments("// import React")
    assert "useState" not in _strip_code_comments("/* useState(0) */")
    assert "from fastapi import FastAPI" in _strip_code_comments("from fastapi import FastAPI\n")


def test_vendor_generated_lock_build_paths_are_skippable():
    for p in [
        "node_modules/react/index.js",
        "vendor/bundle.js",
        "dist/bundle.min.js",
        "build/output.js",
        ".next/static/chunks/app.js",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "src/app.min.js",
        "__pycache__/module.pyc",
        ".git/objects/ab/cd",
    ]:
        assert _is_skippable_path(p.lower()) is True, p
    for p in [
        "src/App.jsx",
        "src/components/UserCard.tsx",
        "app/main.py",
        "server/index.ts",
    ]:
        assert _is_skippable_path(p.lower()) is False, p


def test_substring_dep_does_not_create_false_react():
    """'interaction-observer' contains 'react' as substring but is not React."""
    res = _direct("dev", "lib", {
        "name": "lib",
        "languages": {},
        "root_files": ["package.json"],
        "top_files": [],
        "package_json_deps": ["interaction-observer"],
        "tree_scanned": True,
    })
    assert "React" not in {s.skill for s in res.signals}


# ---------------------------------------------------------------------------
# 6. Mixed-technology repository grades each skill independently
# ---------------------------------------------------------------------------

def test_mixed_technologies_graded_independently():
    res = _direct("dev", "fullstack", {
        "name": "fullstack",
        "description": "",
        "languages": {"Python": 40000, "TypeScript": 30000},
        "root_files": ["package.json", "requirements.txt", "Dockerfile", "docker-compose.yml"],
        "top_files": ["src/App.tsx", "api/main.py"],
        "package_json_deps": ["react"],
        "python_deps": ["fastapi"],
        "import_tokens": {"react": 2, "fastapi": 2},
        "source_files_sampled": ["src/App.tsx", "api/main.py"],
        "tree_scanned": True,
        "ext_file_counts": {".tsx": 2, ".py": 2},
    })
    by_skill = {s.skill: s for s in res.signals}
    assert by_skill["React"].depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert by_skill["REST APIs"].depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert by_skill["Python"].depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert by_skill["Docker"].depth >= EvidenceDepth.LEVEL_2_CONFIG
    # Canonical identities only
    for name in by_skill:
        from app.services.skill_taxonomy import normalize_skill
        assert normalize_skill(name) == name


# ---------------------------------------------------------------------------
# 7. Structured metadata present on every signal (no raw contents exposed)
# ---------------------------------------------------------------------------

def test_structured_metadata_present_and_safe():
    res = _direct("dev", "app", {
        "name": "app",
        "description": "",
        "languages": {"TypeScript": 20000},
        "root_files": ["package.json"],
        "top_files": ["src/App.tsx"],
        "package_json_deps": ["react"],
        "import_tokens": {"react": 2},
        "source_files_sampled": ["src/App.tsx"],
        "usage_patterns": {"React": {"hook_useState": 1}},
        "usage_files": {"React": ["src/App.tsx"]},
        "tree_scanned": True,
        "ext_file_counts": {".tsx": 1},
    })
    assert res.signals, "expected at least one signal"
    for sig in res.signals:
        m = sig.metadata
        for key in (
            "repository_name", "language", "evidence_depth", "evidence_count",
            "files_analyzed", "implementation_files", "relevant_files",
            "detected_usage_patterns", "reason",
        ):
            assert key in m, f"missing metadata '{key}' for {sig.skill}"
        assert m["evidence_depth"] == sig.depth
        assert isinstance(m["relevant_files"], list)
        assert isinstance(m["detected_usage_patterns"], list)
        # No raw file bodies leak into metadata
        for v in m.values():
            if isinstance(v, str):
                assert len(v) < 5000


def test_signal_format_compatible_with_engine():
    res = _direct("dev", "app", {
        "name": "app",
        "languages": {"TypeScript": 20000},
        "root_files": ["package.json"],
        "top_files": ["src/App.tsx"],
        "package_json_deps": ["react"],
        "import_tokens": {"react": 2},
        "source_files_sampled": ["src/App.tsx"],
        "tree_scanned": True,
        "ext_file_counts": {".tsx": 1},
    })
    for sig in res.signals:
        d = sig.to_dict()
        for key in ("skill", "canonical_name", "signal_strength", "signal_value",
                    "depth", "reason", "explanation", "source_reliability", "metadata"):
            assert key in d
        assert 0.0 <= d["signal_strength"] <= 1.0
        assert 0 <= d["depth"] <= 4


# ---------------------------------------------------------------------------
# 8. End-to-end flow: provider -> extractor -> normalize -> aggregate -> engine
# ---------------------------------------------------------------------------

def test_evidence_flows_through_analysis_pipeline():
    owner = "flow_dev"
    repos = [
        _inspection_repo(owner, "web", {
            "languages": {"TypeScript": 40000},
            "root_files": ["package.json"],
            "top_files": ["src/App.tsx", "src/components/Card.tsx"],
            "package_json_deps": ["react"],
            "import_tokens": {"react": 3},
            "source_files_sampled": ["src/App.tsx", "src/components/Card.tsx"],
            "usage_patterns": {"React": {"hook_useState": 2, "jsx_component": 2}},
            "usage_files": {"React": ["src/App.tsx", "src/components/Card.tsx"]},
            "tree_scanned": True,
            "ext_file_counts": {".tsx": 2},
            "has_workflows": True,
        }),
    ]
    verification = _verify_mock(owner, repos)
    assert verification.status == "verified"
    evidence = [{
        "id": "ev-github-profile",
        "evidence_type": "github",
        "source_url": f"https://github.com/{owner}",
        "verification_status": "verified",
        "metadata": {
            "verification_status": "verified",
            "verified_signals": [s.to_dict() for s in verification.signals],
            "inspection": verification.raw_metadata,
        },
    }]
    raw = ars.extract_skill_signals(evidence, [], [])
    assert any(str(s.get("source") or s.get("source_type")).lower() == "github" for s in raw)
    signals = ars.normalize_signals(raw, None)
    grouped = ars.aggregate_skills(signals)
    assert "React" in grouped
    req_map = ars.build_requirements_map(
        [{"skill": "React", "required_level": 0.8, "importance": 0.8}], None
    )
    assessments = {a["canonical_name"]: a for a in ars.calculate_assessments(grouped, req_map, None)}
    assert assessments["React"]["proficiency"] > 0
    assert assessments["React"]["evidence_count"] >= 1
    # Depth ordering preserved through the engine: L2 < L3 <= L4 strength
    assert EvidenceDepth.get_strength_for_depth(2) < EvidenceDepth.get_strength_for_depth(3)
    assert EvidenceDepth.get_strength_for_depth(3) <= EvidenceDepth.get_strength_for_depth(4)


def test_depth_strength_map_unchanged():
    assert EvidenceDepth.DEPTH_STRENGTH_MAP == {
        EvidenceDepth.LEVEL_0_URL_ONLY: 0.0,
        EvidenceDepth.LEVEL_1_MENTION: 0.40,
        EvidenceDepth.LEVEL_2_CONFIG: 0.60,
        EvidenceDepth.LEVEL_3_IMPLEMENTATION: 0.75,
        EvidenceDepth.LEVEL_4_SUBSTANTIAL: 0.85,
    }
    assert EvidenceDepth.get_strength_for_depth(EvidenceDepth.LEVEL_1_MENTION) == pytest.approx(0.40)
    assert EvidenceDepth.get_strength_for_depth(EvidenceDepth.LEVEL_2_CONFIG) == pytest.approx(0.60)
    assert EvidenceDepth.get_strength_for_depth(EvidenceDepth.LEVEL_3_IMPLEMENTATION) == pytest.approx(0.75)
    assert EvidenceDepth.get_strength_for_depth(EvidenceDepth.LEVEL_4_SUBSTANTIAL) == pytest.approx(0.85)


def test_weighted_average_formula_unchanged():
    sigs = [
        {"signal_strength": 0.80, "source_reliability": 0.40},
        {"signal_strength": 0.40, "source_reliability": 0.85},
    ]
    expected = (0.80 * 0.40 + 0.40 * 0.85) / (0.40 + 0.85)
    prof, weight, count, _ = skill_engine.proficiency(sigs)
    assert prof == pytest.approx(expected)
    assert count == 2
