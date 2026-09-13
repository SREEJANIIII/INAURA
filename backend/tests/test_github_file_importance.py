"""
Phase 2: deterministic GitHub file-importance weighting tests.

Verifies IGNORE/LOW/MEDIUM/HIGH/VERY_HIGH classification, its influence on
evidence depth (not on the final skill score formula), vendor/generated
exclusion, required metadata, no double counting, and EvidenceDepth
compatibility. Builds on Phase 1; does not rewrite it.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from app.services.evidence.base import EvidenceDepth
from app.services.evidence.file_importance import (
    IGNORE, LOW, MEDIUM, HIGH, VERY_HIGH,
    LABELS, WEIGHTS, MAX_DEPTH_BY_TIER,
    classify_file_importance,
    assess_repository_importance,
    importance_weight,
    max_supported_depth,
)
from app.services.evidence.github import GitHubProvider
from app.services import analysis_run_service as ars


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
# 1. Unit: IGNORE classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "node_modules/react/index.js",
    "node_modules/pkg/index.js",
    "dist/bundle.js",
    "dist/bundle.min.js",
    "build/output.js",
    ".next/static/chunks/app.js",
    ".nuxt/dist/client.js",
    "coverage/lcov-report/index.html",
    "vendor/bundle.js",
    "third_party/lib/helper.py",
    "app.exe",
    "lib/native.dll",
    "assets/logo.png",
    "docs/_build/html/index.html",
    "src/app.min.js",
    "src/app.bundle.js",
    "src/app.js.map",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "__pycache__/module.pyc",
    ".git/objects/ab/cdef",
    ".cache/results.json",
    "archive.zip",
])
def test_ignore_paths(path):
    assert classify_file_importance(path) == IGNORE
    assert max_supported_depth(IGNORE) == 0
    assert importance_weight(IGNORE) == pytest.approx(0.0)


def test_ignore_huge_blob():
    assert classify_file_importance("src/big.py", size=500_000) == IGNORE


# ---------------------------------------------------------------------------
# 2. Unit: LOW classification (README/docs/metadata/comments-only)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "README.md",
    "readme.rst",
    "CHANGELOG.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "docs/guide.md",
    "documentation/api.txt",
    ".gitignore",
    ".editorconfig",
])
def test_low_paths(path):
    assert classify_file_importance(path) == LOW


def test_comments_only_source_is_low():
    tier = classify_file_importance(
        "src/app.py",
        evidence={"has_imports": False, "import_count": 0,
                  "has_patterns": False, "pattern_count": 0,
                  "comments_only": True},
    )
    assert tier == LOW


def test_low_never_upgrades_from_mentions():
    # Even with heavy import-looking evidence hints, docs stay LOW:
    # importance must not be driven by keyword frequency alone.
    tier = classify_file_importance(
        "README.md",
        evidence={"has_imports": True, "import_count": 10,
                  "has_patterns": True, "pattern_count": 5,
                  "comments_only": False},
    )
    assert tier == LOW


# ---------------------------------------------------------------------------
# 3. Unit: MEDIUM classification (manifests/configs/CI/env/framework config)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "Dockerfile",
    "docker-compose.yml",
    "compose.yaml",
    ".github/workflows/ci.yml",
    "Jenkinsfile",
    ".env.example",
    "tsconfig.json",
    "vite.config.ts",
    "application.yml",
    "k8s/deployment.yaml",
])
def test_medium_paths(path):
    assert classify_file_importance(path) == MEDIUM


def test_medium_never_becomes_high_from_mentions():
    tier = classify_file_importance(
        "package.json",
        evidence={"has_imports": True, "import_count": 5,
                  "has_patterns": True, "pattern_count": 3},
    )
    assert tier == MEDIUM


# ---------------------------------------------------------------------------
# 4. Unit: HIGH classification (source + tests)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "src/App.tsx",
    "src/components/UserCard.tsx",
    "src/hooks/useAuth.ts",
    "api/main.py",
    "server/controllers/user.py",
    "app/services/billing.py",
    "src/models/user.py",
    "src/utils/format.ts",
    "src/engine/pipeline.py",
    "tests/test_main.py",
    "src/App.test.tsx",
    "__tests__/app.test.tsx",
])
def test_high_paths(path):
    assert classify_file_importance(path) == HIGH


def test_single_high_file_with_patterns_can_be_very_high():
    tier = classify_file_importance(
        "src/services/billing.py",
        evidence={"has_imports": True, "import_count": 3,
                  "has_patterns": True, "pattern_count": 2},
    )
    assert tier == VERY_HIGH


def test_single_plain_source_stays_high():
    assert classify_file_importance("src/App.tsx") == HIGH


# ---------------------------------------------------------------------------
# 5. Unit: determinism, weights, depth caps
# ---------------------------------------------------------------------------

def test_deterministic_and_ordered():
    assert classify_file_importance("src/App.tsx") == classify_file_importance("src/App.tsx")
    assert IGNORE < LOW < MEDIUM < HIGH < VERY_HIGH
    assert WEIGHTS[IGNORE] < WEIGHTS[LOW] < WEIGHTS[MEDIUM] < WEIGHTS[HIGH] < WEIGHTS[VERY_HIGH]
    assert MAX_DEPTH_BY_TIER == {IGNORE: 0, LOW: 1, MEDIUM: 2, HIGH: 3, VERY_HIGH: 4}
    assert LABELS[VERY_HIGH] == "very_high"


def test_repository_aggregate_levels():
    assert assess_repository_importance({})["level"] == IGNORE
    assert assess_repository_importance({"README.md": LOW})["level"] == LOW
    assert assess_repository_importance({"package.json": MEDIUM})["level"] == MEDIUM
    assert assess_repository_importance({"src/a.py": HIGH})["level"] == HIGH
    # Single HIGH file never VERY_HIGH.
    single = assess_repository_importance(
        {"src/a.py": HIGH},
        {"has_tests": True, "has_workflows": True,
         "pattern_files": 1, "distinct_patterns": 3, "usage_files": 1},
    )
    assert single["level"] == HIGH
    # Multiple HIGH + patterns + tests -> VERY_HIGH.
    multi = assess_repository_importance(
        {"src/a.py": HIGH, "src/b.py": HIGH, "src/c.py": HIGH},
        {"has_tests": True, "has_workflows": True,
         "pattern_files": 3, "distinct_patterns": 3, "usage_files": 3},
    )
    assert multi["level"] == VERY_HIGH
    # IGNORE-only repo stays IGNORE.
    assert assess_repository_importance(
        {"node_modules/x.js": IGNORE, "dist/b.js": IGNORE})["level"] == IGNORE


# ---------------------------------------------------------------------------
# 6. Integration: required file types map to expected depth + importance
# ---------------------------------------------------------------------------

def test_readme_maps_to_low_l1():
    res = _direct("dev", "site", {
        "name": "site", "description": "", "readme_text": "Built with React",
        "languages": {}, "root_files": ["README.md"], "top_files": [],
        "tree_scanned": True,
    })
    sig = {s.skill: s for s in res.signals}["React"]
    assert sig.depth == EvidenceDepth.LEVEL_1_MENTION
    assert sig.metadata["file_importance"] == "low"
    assert any("README" in f for f in sig.metadata["relevant_files"])


def test_package_json_maps_to_medium_l2():
    res = _direct("dev", "web", {
        "name": "web", "description": "", "readme_text": "",
        "languages": {}, "root_files": ["package.json"], "top_files": [],
        "package_json_deps": ["react"], "tree_scanned": True,
    })
    sig = {s.skill: s for s in res.signals}["React"]
    assert sig.depth == EvidenceDepth.LEVEL_2_CONFIG
    assert sig.metadata["file_importance"] == "medium"


def test_requirements_maps_to_medium_l2():
    res = _direct("dev", "svc", {
        "name": "svc", "description": "",
        "languages": {"Python": 400}, "root_files": ["requirements.txt"],
        "top_files": [], "python_deps": ["pandas"],
        "tree_scanned": True, "ext_file_counts": {},
    })
    by_skill = {s.skill: s for s in res.signals}
    assert by_skill["Pandas"].depth == EvidenceDepth.LEVEL_2_CONFIG
    assert by_skill["Pandas"].metadata["file_importance"] in ("medium", "low")


def test_source_file_maps_to_high_l3():
    res = _direct("dev", "app", {
        "name": "app", "description": "",
        "languages": {"TypeScript": 15000}, "root_files": ["package.json"],
        "top_files": ["src/App.jsx"], "package_json_deps": ["react"],
        "import_tokens": {"react": 1}, "source_files_sampled": ["src/App.jsx"],
        "tree_scanned": True, "ext_file_counts": {".jsx": 1},
    })
    sig = {s.skill: s for s in res.signals}["React"]
    assert sig.depth == EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert sig.metadata["file_importance"] in ("high", "very_high")


def test_test_file_is_high_importance():
    assert classify_file_importance("tests/test_main.py") == HIGH
    assert classify_file_importance("src/App.test.tsx") == HIGH


def test_configuration_maps_to_medium():
    res = _direct("dev", "ops", {
        "name": "ops", "description": "",
        "languages": {}, "root_files": ["docker-compose.yml"],
        "top_files": ["docker-compose.yml"],
        "config_text": "services:\n  db:\n    image: postgres:16\n    image: postgres:16\n",
        "config_files_sampled": ["docker-compose.yml"],
        "tree_scanned": True,
    })
    by_skill = {s.skill: s for s in res.signals}
    assert by_skill["PostgreSQL"].depth == EvidenceDepth.LEVEL_2_CONFIG
    assert by_skill["PostgreSQL"].metadata["file_importance"] == "medium"


def test_substantial_multi_file_is_very_high_l4():
    res = _direct("dev", "dashboard", {
        "name": "dashboard", "description": "",
        "languages": {"TypeScript": 60000}, "root_files": ["package.json"],
        "top_files": ["src/App.tsx", "src/components/UserCard.tsx",
                      "src/routes/Home.tsx", "tests/app.test.tsx"],
        "package_json_deps": ["react", "react-dom", "typescript", "jest"],
        "import_tokens": {"react": 5},
        "source_files_sampled": ["src/App.tsx", "src/components/UserCard.tsx", "src/routes/Home.tsx"],
        "usage_patterns": {"React": {"hook_useState": 2, "jsx_component": 3}},
        "usage_files": {"React": ["src/App.tsx", "src/components/UserCard.tsx", "src/routes/Home.tsx"]},
        "tree_scanned": True, "ext_file_counts": {".tsx": 6, ".ts": 2},
        "has_workflows": True,
    })
    sig = {s.skill: s for s in res.signals}["React"]
    assert sig.depth == EvidenceDepth.LEVEL_4_SUBSTANTIAL
    assert sig.metadata["file_importance"] == "very_high"


# ---------------------------------------------------------------------------
# 7. Generated/vendor/build output cannot increase evidence
# ---------------------------------------------------------------------------

def test_vendor_files_cannot_produce_implementation():
    res = _direct("dev", "vendored", {
        "name": "vendored", "description": "",
        "languages": {}, "root_files": ["package.json"],
        "top_files": ["node_modules/react/index.js"],
        "package_json_deps": [],
        "import_tokens": {"react": 5},
        "source_files_sampled": ["node_modules/react/index.js"],
        "usage_files": {"React": ["node_modules/react/index.js"]},
        "tree_scanned": True, "ext_file_counts": {},
    })
    by_skill = {s.skill: s for s in res.signals}
    # Vendor-only usage must not become L3/L4 implementation evidence.
    assert "React" not in by_skill or by_skill["React"].depth <= EvidenceDepth.LEVEL_2_CONFIG


def test_build_output_cannot_produce_implementation():
    res = _direct("dev", "built", {
        "name": "built", "description": "",
        "languages": {}, "root_files": ["package.json"],
        "top_files": ["dist/bundle.min.js"],
        "import_tokens": {"react": 5},
        "source_files_sampled": ["dist/bundle.min.js"],
        "usage_files": {"React": ["dist/bundle.min.js"]},
        "tree_scanned": True, "ext_file_counts": {},
    })
    by_skill = {s.skill: s for s in res.signals}
    assert "React" not in by_skill or by_skill["React"].depth <= EvidenceDepth.LEVEL_2_CONFIG


# ---------------------------------------------------------------------------
# 8. README + source strictly stronger than README alone
# ---------------------------------------------------------------------------

def test_readme_plus_source_stronger_than_readme_alone():
    readme_only = _direct("dev", "notes", {
        "name": "notes", "description": "", "readme_text": "Built with React",
        "languages": {}, "root_files": ["README.md"], "top_files": [],
        "tree_scanned": True,
    })
    with_source = _direct("dev", "app", {
        "name": "app", "description": "", "readme_text": "Built with React",
        "languages": {"TypeScript": 15000}, "root_files": ["package.json", "README.md"],
        "top_files": ["src/App.jsx"], "package_json_deps": ["react"],
        "import_tokens": {"react": 2}, "source_files_sampled": ["src/App.jsx"],
        "tree_scanned": True, "ext_file_counts": {".jsx": 1},
    })
    r_sig = {s.skill: s for s in readme_only.signals}["React"]
    s_sig = {s.skill: s for s in with_source.signals}["React"]
    assert s_sig.depth > r_sig.depth
    assert s_sig.signal_strength > r_sig.signal_strength
    assert WEIGHTS[HIGH] > WEIGHTS[LOW]
    assert s_sig.metadata["file_importance"] in ("high", "very_high")
    assert r_sig.metadata["file_importance"] == "low"


# ---------------------------------------------------------------------------
# 9. No double counting + required metadata + EvidenceDepth compatibility
# ---------------------------------------------------------------------------

def test_no_double_counting_one_signal_per_skill():
    res = _direct("dev", "multi", {
        "name": "multi", "description": "",
        "languages": {"TypeScript": 60000, "Python": 40000},
        "root_files": ["package.json", "requirements.txt"],
        "top_files": ["src/a.tsx", "src/b.tsx", "src/c.tsx", "api/x.py", "api/y.py"],
        "package_json_deps": ["react"], "python_deps": ["fastapi"],
        "import_tokens": {"react": 8, "fastapi": 6},
        "source_files_sampled": ["src/a.tsx", "src/b.tsx", "api/x.py"],
        "usage_patterns": {"React": {"hook_useState": 3, "jsx_component": 3}},
        "usage_files": {"React": ["src/a.tsx", "src/b.tsx"]},
        "tree_scanned": True, "ext_file_counts": {".tsx": 3, ".py": 2},
        "has_workflows": True,
    })
    names = [s.skill for s in res.signals]
    assert len(names) == len(set(names))
    for sig in res.signals:
        assert sig.signal_strength <= EvidenceDepth.get_strength_for_depth(
            EvidenceDepth.LEVEL_4_SUBSTANTIAL) + 1e-9


def test_required_metadata_present():
    res = _direct("dev", "app", {
        "name": "app", "description": "",
        "languages": {"TypeScript": 20000}, "root_files": ["package.json"],
        "top_files": ["src/App.tsx"], "package_json_deps": ["react"],
        "import_tokens": {"react": 2}, "source_files_sampled": ["src/App.tsx"],
        "tree_scanned": True, "ext_file_counts": {".tsx": 1},
    })
    assert res.signals
    for sig in res.signals:
        m = sig.metadata
        for key in ("file_importance", "evidence_depth", "relevant_files", "reason"):
            assert key in m, f"missing '{key}' for {sig.skill}"
        assert m["evidence_depth"] == sig.depth
        assert isinstance(m["relevant_files"], list) and m["relevant_files"]
        assert isinstance(m["reason"], str) and m["reason"]
        assert m["file_importance"] in ("ignore", "low", "medium", "high", "very_high")


def test_evidence_depth_system_unchanged():
    assert EvidenceDepth.DEPTH_STRENGTH_MAP == {
        EvidenceDepth.LEVEL_0_URL_ONLY: 0.0,
        EvidenceDepth.LEVEL_1_MENTION: 0.40,
        EvidenceDepth.LEVEL_2_CONFIG: 0.60,
        EvidenceDepth.LEVEL_3_IMPLEMENTATION: 0.75,
        EvidenceDepth.LEVEL_4_SUBSTANTIAL: 0.85,
    }


def test_end_to_end_flow_preserved():
    owner = "flow_imp"
    repos = [_inspection_repo(owner, "web", {
        "languages": {"TypeScript": 40000}, "root_files": ["package.json"],
        "top_files": ["src/App.tsx", "src/components/Card.tsx"],
        "package_json_deps": ["react"], "import_tokens": {"react": 3},
        "source_files_sampled": ["src/App.tsx", "src/components/Card.tsx"],
        "usage_patterns": {"React": {"hook_useState": 2, "jsx_component": 2}},
        "usage_files": {"React": ["src/App.tsx", "src/components/Card.tsx"]},
        "tree_scanned": True, "ext_file_counts": {".tsx": 2},
        "has_workflows": True,
    })]
    verification = _verify_mock(owner, repos)
    assert verification.status == "verified"
    evidence = [{
        "id": "ev-github-profile", "evidence_type": "github",
        "source_url": f"https://github.com/{owner}",
        "verification_status": "verified",
        "metadata": {
            "verification_status": "verified",
            "verified_signals": [s.to_dict() for s in verification.signals],
            "inspection": verification.raw_metadata,
        },
    }]
    raw = ars.extract_skill_signals(evidence, [], [])
    signals = ars.normalize_signals(raw, None)
    grouped = ars.aggregate_skills(signals)
    assert "React" in grouped
