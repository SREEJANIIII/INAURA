"""
Regression coverage for the deep GitHub evidence pipeline.

Two historical defects are covered here:

  1. "only 5 repositories": profile inspection used to call
     `/users/{owner}/repos?sort=updated&per_page=5` — a single page of the five
     most recently updated repositories. Every older repository (and every
     skill only demonstrated there) was invisible to the skill engine.

  2. "metadata-only skills": repository evidence was derived from GitHub's
     top-level language summary plus a couple of root manifests. Skills proven
     inside project contents (imports, configuration, infrastructure) never
     produced signals.

The tests below pin the corrected behaviour: full pagination, a separate
repository-content analysis stage, evidence-depth grading, cross-repository
aggregation without duplicate inflation, and the unchanged reliability
hierarchy that keeps GitHub below performance-based evidence.
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.evidence.base import EvidenceDepth, VerificationStatus
from app.services.evidence.github import (
    GITHUB_RELIABILITY,
    ContentBudget,
    GitHubProvider,
    dependency_skill_names,
    extract_import_tokens,
    import_skill_counts,
    select_source_files,
    skill_mention_counts,
)
from app.services import analysis_run_service as ars
from app.services import signal_extractor as se
from app.services import skill_engine
from app.services import skill_taxonomy


# ---------------------------------------------------------------------------
# Mock GitHub server
# ---------------------------------------------------------------------------

def _response(status_code: int, json_data: Any = None, text: Optional[str] = None,
              headers: Optional[dict] = None) -> MagicMock:
    res = MagicMock(spec=httpx.Response)
    res.status_code = status_code
    res.headers = headers or {}
    if text is not None:
        res.text = text
        res.json.side_effect = Exception("not json")
    elif json_data is not None:
        res.json.return_value = json_data
        res.text = json.dumps(json_data)
    else:
        res.text = ""
        res.json.side_effect = Exception("no json")
    return res


class FakeGitHub:
    """
    Minimal in-memory GitHub used by the provider tests.

    repos: name -> {
        "meta": {...},                 # /users/{owner}/repos entry
        "languages": {...},            # /repos/{o}/{r}/languages
        "root": [names],               # /repos/{o}/{r}/contents
        "tree": [(path, size)],        # /repos/{o}/{r}/git/trees/...
        "raw": {path: text},           # raw.githubusercontent.com
        "fail": bool,                  # simulate a broken repository
    }
    """

    def __init__(self, owner: str, repos: Dict[str, dict], page_size: int = 100):
        self.owner = owner
        self.repos = repos
        self.page_size = page_size
        self.requests: List[str] = []
        self.repo_list_params: List[dict] = []

    def _repo_name_from_url(self, url: str) -> str:
        marker = f"/repos/{self.owner}/"
        if marker in url:
            return url.split(marker, 1)[1].split("/")[0].split("?")[0]
        marker_raw = f"raw.githubusercontent.com/{self.owner}/"
        if marker_raw in url:
            return url.split(marker_raw, 1)[1].split("/")[0]
        return ""

    async def get(self, url, *args, **kwargs):
        # Patched in as httpx.AsyncClient.get, so the bound `self` is the fake
        # server and the client instance never reaches this method.
        url = str(url)
        params = kwargs.get("params") or {}
        self.requests.append(url)

        if url == f"https://api.github.com/users/{self.owner}":
            return _response(200, {"login": self.owner, "public_repos": len(self.repos)})

        if url == f"https://api.github.com/users/{self.owner}/repos":
            self.repo_list_params.append(dict(params))
            per_page = int(params.get("per_page", 30))
            page = int(params.get("page", 1))
            entries = [r["meta"] for r in self.repos.values()]
            start = (page - 1) * per_page
            chunk = entries[start:start + per_page]
            has_next = start + per_page < len(entries)
            link = (
                f'<https://api.github.com/users/{self.owner}/repos?page={page + 1}>; rel="next"'
                if has_next else ""
            )
            return _response(200, chunk, headers={"link": link})

        name = self._repo_name_from_url(url)
        repo = self.repos.get(name)
        if repo is None:
            return _response(404, {"message": "Not Found"})
        if repo.get("fail"):
            return _response(500, {"message": "Internal Server Error"})
        if repo.get("network_error"):
            raise httpx.ConnectError("connection reset")

        if "raw.githubusercontent.com" in url:
            path = url.split(f"raw.githubusercontent.com/{self.owner}/{name}/", 1)[1]
            path = path.split("/", 1)[1] if "/" in path else path
            content = (repo.get("raw") or {}).get(path)
            if content is None:
                return _response(404)
            return _response(200, text=content)

        if url.endswith("/languages"):
            return _response(200, repo.get("languages") or {})
        if "/contents/.github/workflows" in url:
            wf = [
                {"name": p.rsplit("/", 1)[-1]}
                for p, _ in (repo.get("tree") or [])
                if p.startswith(".github/workflows/")
            ]
            return _response(200, wf) if wf else _response(404)
        if url.endswith("/contents"):
            return _response(200, [{"name": n} for n in (repo.get("root") or [])])
        if "/git/trees/" in url:
            tree = [
                {"path": p, "type": "blob", "size": s}
                for p, s in (repo.get("tree") or [])
            ]
            return _response(200, {"tree": tree})
        return _response(404)


def _repo_meta(owner: str, name: str, **overrides) -> dict:
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


def _run(coro):
    return asyncio.run(coro)


# ===========================================================================
# 1. A profile with more than five repositories is fully paginated
# ===========================================================================

def test_profile_with_more_than_five_repositories_is_fully_paginated():
    owner = "many_repos_dev"
    repos = {}
    for i in range(1, 251):
        name = f"repo-{i}"
        repos[name] = {
            "meta": _repo_meta(owner, name, language="Python"),
            "languages": {"Python": 9000},
            "root": ["requirements.txt"],
            "tree": [("app.py", 900)],
            "raw": {"requirements.txt": "requests\n", "app.py": "import os\n"},
        }

    gh = FakeGitHub(owner, repos)
    with patch.object(httpx.AsyncClient, "get", new=gh.get):
        res = _run(GitHubProvider().verify({"source_url": f"https://github.com/{owner}"}))

    assert res.status == VerificationStatus.VERIFIED
    assert res.raw_metadata["repositories_fetched"] == 250
    assert res.raw_metadata["repositories_inspected"] == 250

    # Pagination must walk pages with a full page size — never the old cap of 5.
    assert len(gh.repo_list_params) == 3
    assert [p["page"] for p in gh.repo_list_params] == [1, 2, 3]
    for p in gh.repo_list_params:
        assert int(p["per_page"]) == 100
        assert int(p["per_page"]) > 5


def test_regression_five_repository_cap_is_gone():
    """The exact original bug: only the 5 newest repositories reached the engine."""
    owner = "capped_dev"
    repos = {}
    for i in range(1, 13):
        name = f"proj-{i}"
        repos[name] = {
            "meta": _repo_meta(
                owner, name, language="Python",
                pushed_at=(datetime.now(timezone.utc) - timedelta(days=i * 30)).isoformat(),
            ),
            "languages": {"Python": 12000},
            "root": ["requirements.txt"],
            "tree": [("main.py", 800)],
            "raw": {"requirements.txt": "flask\n", "main.py": "import os\n"},
        }
    # The 11th-oldest repository is the only place Rust exists.
    repos["proj-11"]["languages"] = {"Rust": 40000}
    repos["proj-11"]["root"] = ["Cargo.toml"]
    repos["proj-11"]["tree"] = [
        ("Cargo.toml", 300), ("src/main.rs", 1200), ("src/lib.rs", 900), ("src/api.rs", 800)
    ]
    repos["proj-11"]["raw"] = {"Cargo.toml": "[dependencies]\nserde = \"1\"\n"}

    gh = FakeGitHub(owner, repos)
    with patch.object(httpx.AsyncClient, "get", new=gh.get):
        res = _run(GitHubProvider().verify({"source_url": f"https://github.com/{owner}"}))

    assert res.raw_metadata["repositories_fetched"] == 12
    inspected = {r["name"] for r in res.raw_metadata["repositories"]}
    assert {"proj-6", "proj-9", "proj-11", "proj-12"} <= inspected

    skills = {s.skill for s in res.signals}
    assert "Rust" in skills, "A skill only present in an older repository must still be found"

    # And no request may ask GitHub for a truncated repository page.
    assert all(int(p["per_page"]) > 5 for p in gh.repo_list_params)


# ===========================================================================
# 2. Older repositories are included, not just the newest few
# ===========================================================================

def test_old_repositories_are_included_regardless_of_update_time():
    owner = "veteran"
    repos = {
        "fresh-app": {
            "meta": _repo_meta(owner, "fresh-app", language="Python"),
            "languages": {"Python": 20000},
            "root": ["requirements.txt"],
            "tree": [("app.py", 1000)],
            "raw": {"requirements.txt": "flask\n", "app.py": "import os\n"},
        },
        "ancient-go-service": {
            "meta": _repo_meta(
                owner, "ancient-go-service", language="Go",
                pushed_at=(datetime.now(timezone.utc) - timedelta(days=365 * 7)).isoformat(),
            ),
            "languages": {"Go": 60000},
            "root": ["go.mod"],
            "tree": [
                ("go.mod", 200), ("cmd/main.go", 2000),
                ("internal/server.go", 3000), ("internal/store.go", 1500),
            ],
            "raw": {"go.mod": "module example.com/x\n\nrequire github.com/gin-gonic/gin v1.9.0\n"},
        },
    }

    gh = FakeGitHub(owner, repos)
    with patch.object(httpx.AsyncClient, "get", new=gh.get):
        res = _run(GitHubProvider().verify({"source_url": f"https://github.com/{owner}"}))

    names = {r["name"] for r in res.raw_metadata["repositories"]}
    assert "ancient-go-service" in names
    skills = {s.skill: s for s in res.signals}
    assert "Go" in skills
    assert skills["Go"].depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION


# ===========================================================================
# 3. Discovery and content analysis are separate stages
# ===========================================================================

def test_repository_discovery_is_separate_from_content_analysis():
    owner = "stages_dev"
    repos = {
        "svc": {
            "meta": _repo_meta(owner, "svc", language="Python"),
            "languages": {"Python": 15000},
            "root": ["requirements.txt", "README.md"],
            "tree": [("requirements.txt", 40), ("README.md", 300), ("src/main.py", 900)],
            "raw": {
                "requirements.txt": "fastapi\n",
                "README.md": "# svc\nA service.",
                "src/main.py": "from fastapi import FastAPI\n",
            },
        }
    }
    gh = FakeGitHub(owner, repos)
    provider = GitHubProvider()

    async def _discovery_only():
        async with httpx.AsyncClient() as client:
            return await provider._fetch_profile_repositories(client, owner)

    with patch.object(httpx.AsyncClient, "get", new=gh.get):
        discovered, meta = _run(_discovery_only())

    # Stage 1 enumerates repositories and reads no repository content at all.
    assert len(discovered) == 1
    assert meta["pages_fetched"] == 1
    assert all("raw.githubusercontent.com" not in u for u in gh.requests)
    assert all("/git/trees/" not in u for u in gh.requests)

    gh.requests.clear()
    with patch.object(httpx.AsyncClient, "get", new=gh.get):
        res = _run(provider.verify({"source_url": f"https://github.com/{owner}"}))

    # Stage 2 inspects structure and reads prioritized project artifacts.
    assert any("/git/trees/" in u for u in gh.requests)
    assert any(u.endswith("src/main.py") for u in gh.requests)
    assert any(u.endswith("README.md") for u in gh.requests)
    inspection = res.raw_metadata["repositories"][0]["inspection"]
    assert inspection["source_files_sampled"] == ["src/main.py"]
    assert inspection["readme_present"] is True
    assert inspection["content_fetches"] >= 2


def test_content_reads_stay_within_budget_and_skip_vendor_paths():
    owner = "bounded_dev"
    tree = [("README.md", 200)]
    tree += [(f"src/module_{i}.py", 1200) for i in range(40)]
    tree += [(f"node_modules/pkg{i}/index.js", 5000) for i in range(30)]
    tree += [("dist/bundle.min.js", 900000)]
    repos = {
        "big": {
            "meta": _repo_meta(owner, "big", language="Python"),
            "languages": {"Python": 90000},
            "root": ["README.md"],
            "tree": tree,
            "raw": {p: "import os\n" for p, _ in tree},
        }
    }
    gh = FakeGitHub(owner, repos)
    with patch.object(httpx.AsyncClient, "get", new=gh.get):
        res = _run(GitHubProvider().verify({"source_url": f"https://github.com/{owner}"}))

    inspection = res.raw_metadata["repositories"][0]["inspection"]
    assert len(inspection["source_files_sampled"]) <= 6
    assert inspection["content_fetches"] <= 10
    raw_requests = [u for u in gh.requests if "raw.githubusercontent.com" in u]
    assert all("node_modules" not in u for u in raw_requests)
    assert all(".min.js" not in u for u in raw_requests)


# ===========================================================================
# 4. Evidence comes from project contents, not only language metadata
# ===========================================================================

def test_implementation_and_configuration_evidence_without_language_metadata():
    owner = "content_dev"
    compose = (
        "services:\n"
        "  db:\n"
        "    image: postgres:16\n"
        "    environment:\n"
        "      POSTGRES_USER: app\n"
        "      POSTGRES_PASSWORD: secret\n"
    )
    main_py = (
        "from fastapi import FastAPI\n"
        "import pandas as pd\n"
        "from pandas import DataFrame\n"
        "app = FastAPI()\n"
    )
    repos = {
        "api": {
            # GitHub reports NO language statistics for this repository.
            "meta": _repo_meta(owner, "api", language=None),
            "languages": {},
            "root": ["docker-compose.yml", "README.md"],
            "tree": [
                ("docker-compose.yml", 400),
                ("README.md", 100),
                ("src/main.py", 900),
            ],
            "raw": {
                "docker-compose.yml": compose,
                "README.md": "# api",
                "src/main.py": main_py,
            },
        }
    }
    gh = FakeGitHub(owner, repos)
    with patch.object(httpx.AsyncClient, "get", new=gh.get):
        res = _run(GitHubProvider().verify({"source_url": f"https://github.com/{owner}"}))

    skills = {s.skill: s for s in res.signals}
    # Derived from imports inside real source files:
    assert "REST APIs" in skills
    assert "Pandas" in skills
    assert skills["Pandas"].depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert "source_usage" in skills["Pandas"].metadata.get("evidence_kinds", [])
    # Derived from configuration file contents:
    assert "PostgreSQL" in skills
    assert skills["PostgreSQL"].depth >= EvidenceDepth.LEVEL_2_CONFIG
    assert "Docker" in skills


def test_dependency_manifest_evidence_is_taxonomy_driven():
    """Any manifest dependency resolving to a canonical skill becomes evidence."""
    resolved = dependency_skill_names({"react", "tailwindcss", "mongoose", "unknown-lib-xyz"})
    assert resolved.get("React") == "react"
    assert "Unknown-Lib-Xyz" not in resolved
    assert all(skill_taxonomy.normalize_skill(s) == s for s in resolved)


def test_import_extraction_is_language_agnostic():
    py = "from fastapi import FastAPI\nimport pandas as pd\n"
    ts = "import React from 'react';\nconst x = require('express');\n"
    java = "package a;\nimport org.springframework.boot.SpringApplication;\n"
    rust = "use serde::Serialize;\n"

    assert "fastapi" in extract_import_tokens(py)
    assert "react" in extract_import_tokens(ts)
    assert "express" in extract_import_tokens(ts)
    assert any(t.startswith("org.springframework") for t in extract_import_tokens(java))
    assert "serde::serialize" in extract_import_tokens(rust)

    counts = import_skill_counts(extract_import_tokens(py + ts + java))
    assert counts.get("REST APIs", 0) >= 1
    assert counts.get("Pandas", 0) >= 1
    assert counts.get("React", 0) >= 1
    assert counts.get("Spring Boot", 0) >= 1


def test_source_file_selection_prioritizes_implementation_and_diversifies():
    candidates = [
        ("node_modules/x/index.js", 90000),   # caller filters these out before selection
        ("src/main.py", 4000),
        ("src/util.py", 500),
        ("scripts/tmp.py", 100),
        ("src/App.tsx", 3000),
        ("src/helper.tsx", 200),
    ]
    picked = select_source_files(candidates, limit=3)
    assert "src/main.py" in picked
    assert any(p.endswith(".tsx") for p in picked), "multiple languages must be sampled"
    assert len(picked) == 3


# ===========================================================================
# 5. Documentation-only evidence stays weaker than implementation evidence
# ===========================================================================

def test_documentation_only_evidence_is_weakest_tier():
    provider = GitHubProvider()
    now = datetime.now(timezone.utc)

    doc_only = provider._build_result_from_inspection(
        "dev", "notes",
        {
            "name": "notes",
            "description": "Notes about Kubernetes and Terraform",
            "readme_text": "I plan to learn Kubernetes deployment strategies.",
            "languages": {},
            "root_files": ["README.md"],
            "top_files": [],
            "tree_scanned": True,
        },
        now,
    )
    doc_skills = {s.skill: s for s in doc_only.signals}
    assert "Kubernetes" in doc_skills
    k_doc = doc_skills["Kubernetes"]
    assert k_doc.depth == EvidenceDepth.LEVEL_1_MENTION
    assert k_doc.signal_strength == pytest.approx(0.40)
    assert k_doc.metadata.get("documentation_only") is True

    implemented = provider._build_result_from_inspection(
        "dev", "platform",
        {
            "name": "platform",
            "description": "",
            "languages": {"Go": 40000},
            "root_files": ["go.mod"],
            "top_files": ["k8s/deployment.yaml"],
            "has_k8s_manifests": True,
            "k8s_manifest_count": 3,
            "tree_scanned": True,
        },
        now,
    )
    k_impl = {s.skill: s for s in implemented.signals}["Kubernetes"]
    assert k_impl.depth > k_doc.depth
    assert k_impl.signal_strength > k_doc.signal_strength

    doc_prof, _, _, _ = skill_engine.proficiency([k_doc.to_dict()])
    impl_prof, _, _, _ = skill_engine.proficiency([k_impl.to_dict()])
    assert doc_prof < impl_prof


def test_documentation_mention_never_overrides_implementation_in_same_repo():
    provider = GitHubProvider()
    res = provider._build_result_from_inspection(
        "dev", "svc",
        {
            "name": "svc",
            "description": "Python Python Python service",
            "readme_text": "Python Python Python Python Python",
            "languages": {"Python": 40000},
            "root_files": ["requirements.txt"],
            "top_files": ["app/main.py"],
            "python_deps": ["fastapi", "pytest"],
            "tree_scanned": True,
        },
        datetime.now(timezone.utc),
    )
    py = [s for s in res.signals if s.skill == "Python"]
    assert len(py) == 1
    assert py[0].depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert py[0].metadata.get("documentation_only") is not True


# ===========================================================================
# 6 & 7. Aggregation across repositories without duplicate inflation
# ===========================================================================

def _inspection_repo(owner: str, name: str, inspection: dict, **meta) -> dict:
    base = _repo_meta(owner, name, **meta)
    base["inspection"] = inspection
    return base


def test_multiple_repositories_aggregate_into_one_signal_per_skill():
    owner = "poly_dev"
    repos = [
        _inspection_repo(owner, "svc-a", {
            "languages": {"Python": 30000},
            "root_files": ["requirements.txt"],
            "top_files": ["app/main.py", "tests/test_main.py"],
            "python_deps": ["fastapi", "pytest"],
        }),
        _inspection_repo(owner, "svc-b", {
            "languages": {"Python": 12000},
            "root_files": ["requirements.txt"],
            "top_files": ["worker.py"],
            "python_deps": ["celery"],
        }),
        _inspection_repo(owner, "ui", {
            "languages": {"TypeScript": 22000},
            "root_files": ["package.json"],
            "package_json_deps": ["react", "next"],
            "top_files": ["src/App.tsx"],
        }),
    ]
    res = _run(GitHubProvider().verify(
        {"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}
    ))

    by_skill: Dict[str, list] = {}
    for s in res.signals:
        by_skill.setdefault(s.skill, []).append(s)
    for skill, sigs in by_skill.items():
        assert len(sigs) == 1, f"{skill} produced {len(sigs)} signals instead of one aggregate"

    python = by_skill["Python"][0]
    assert python.metadata["repo_count"] == 2
    assert {r["name"] for r in python.metadata["repositories"]} == {"svc-a", "svc-b"}
    assert "React" in by_skill and "Next.js" in by_skill


def test_repeated_evidence_inside_one_repository_does_not_inflate_proficiency():
    """Language + manifest + many imports + README repetition = one bounded signal."""
    provider = GitHubProvider()
    res = provider._build_result_from_inspection(
        "dev", "heavy",
        {
            "name": "heavy",
            "description": "pandas pandas pandas",
            "readme_text": "pandas " * 50,
            "languages": {"Python": 90000},
            "root_files": ["requirements.txt"],
            "top_files": ["src/a.py", "src/b.py", "tests/test_a.py"],
            "python_deps": ["pandas", "pandas", "pytest"],
            "import_tokens": {"pandas": 40, "pandas.io": 12},
            "tree_scanned": True,
        },
        datetime.now(timezone.utc),
    )
    pandas_sigs = [s for s in res.signals if s.skill == "Pandas"]
    assert len(pandas_sigs) == 1
    sig = pandas_sigs[0]
    assert sig.signal_strength <= EvidenceDepth.get_strength_for_depth(EvidenceDepth.LEVEL_4_SUBSTANTIAL)
    prof, weight, count, _ = skill_engine.proficiency([sig.to_dict()])
    assert count == 1
    assert weight == pytest.approx(GITHUB_RELIABILITY)
    assert prof <= 0.85 + 1e-9


def test_same_skill_across_many_repositories_stays_bounded():
    owner = "repeat_dev"
    repos = [
        _inspection_repo(owner, f"svc-{i}", {
            "languages": {"Python": 30000},
            "root_files": ["requirements.txt"],
            "top_files": ["app/main.py", "tests/test_main.py"],
            "python_deps": ["fastapi", "pytest"],
        })
        for i in range(12)
    ]
    res = _run(GitHubProvider().verify(
        {"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}
    ))
    python = [s for s in res.signals if s.skill == "Python"]
    assert len(python) == 1
    assert python[0].metadata["repo_count"] == 12
    prof, _, count, _ = skill_engine.proficiency([python[0].to_dict()])
    assert count == 1
    assert prof <= 0.85 + 1e-9, "12 repositories must not push GitHub evidence to certainty"


# ===========================================================================
# 8. GitHub stays below performance-based evidence
# ===========================================================================

def test_github_reliability_ranks_below_performance_based_evidence():
    # SUPPORTING tier after the 2026-09-11 recalibration (0.70 -> 0.60 -> 0.40).
    assert GITHUB_RELIABILITY == pytest.approx(0.40)
    assert se.SOURCE_RELIABILITY["github"] == pytest.approx(GITHUB_RELIABILITY)
    assert se.SOURCE_RELIABILITY["assessment"] > se.SOURCE_RELIABILITY["github"]
    for stronger in ("leetcode", "codeforces", "kaggle", "syllabus", "coursework"):
        assert se.SOURCE_RELIABILITY[stronger] > se.SOURCE_RELIABILITY["github"]
    # GitHub is supporting evidence: after the 2026-09-11 recalibration only
    # self-declared claims weigh less. Credentials and self-reported documents
    # now weigh more than an artifact, by product decision.
    assert se.SOURCE_RELIABILITY["self_declared"] < se.SOURCE_RELIABILITY["github"]
    assert se.SOURCE_RELIABILITY["github"] == pytest.approx(0.40)

    github_sig = {"skill": "Python", "signal_strength": 0.85, "source": "github",
                  "source_reliability": GITHUB_RELIABILITY}
    perf_sig = {"skill": "Python", "signal_strength": 0.40, "source": "leetcode",
                "source_reliability": se.SOURCE_RELIABILITY["leetcode"]}
    prof, _, _, _ = skill_engine.proficiency([github_sig, perf_sig])
    midpoint = (0.85 + 0.40) / 2
    assert prof < midpoint, "the performance-based signal must carry more weight"


def test_deep_github_evidence_does_not_exceed_depth_strength_ceiling():
    owner = "ceiling_dev"
    repos = [
        _inspection_repo(owner, "everything", {
            "languages": {"Python": 200000},
            "root_files": ["requirements.txt", "Dockerfile", "docker-compose.yml"],
            "top_files": ["src/main.py", "tests/test_main.py", ".github/workflows/ci.yml"],
            "python_deps": ["fastapi", "pytest", "pandas", "sqlalchemy"],
            "import_tokens": {"fastapi": 30, "pandas": 30},
            "has_workflows": True,
            "readme_text": "python fastapi docker kubernetes aws",
        })
    ]
    res = _run(GitHubProvider().verify(
        {"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}
    ))
    for sig in res.signals:
        assert sig.signal_strength <= 0.85
        assert sig.source_reliability == pytest.approx(GITHUB_RELIABILITY)
        prof, _, _, _ = skill_engine.proficiency([sig.to_dict()])
        assert prof <= 0.85 + 1e-9


# ===========================================================================
# 9. Broken repositories never stop the analysis
# ===========================================================================

def test_failed_and_empty_repositories_do_not_stop_the_analysis():
    owner = "messy_dev"
    repos = {
        "good": {
            "meta": _repo_meta(owner, "good", language="Python"),
            "languages": {"Python": 20000},
            "root": ["requirements.txt", "README.md"],
            "tree": [("src/main.py", 900), ("README.md", 50)],
            "raw": {
                "requirements.txt": "fastapi\n",
                "src/main.py": "from fastapi import FastAPI\n",
                "README.md": "# good",
            },
        },
        "broken": {
            "meta": _repo_meta(owner, "broken", language="C++"),
            "fail": True,
        },
        "offline": {
            "meta": _repo_meta(owner, "offline", language="Java"),
            "network_error": True,
        },
        "empty": {
            "meta": _repo_meta(owner, "empty", language=None, size=0),
        },
        "also-good": {
            "meta": _repo_meta(owner, "also-good", language="Go"),
            "languages": {"Go": 30000},
            "root": ["go.mod"],
            "tree": [("go.mod", 100), ("cmd/main.go", 1500), ("internal/a.go", 800)],
            "raw": {"go.mod": "module x\n"},
        },
    }
    gh = FakeGitHub(owner, repos)
    with patch.object(httpx.AsyncClient, "get", new=gh.get):
        res = _run(GitHubProvider().verify({"source_url": f"https://github.com/{owner}"}))

    assert res.status == VerificationStatus.VERIFIED
    assert res.raw_metadata["repositories_fetched"] == 5
    assert res.raw_metadata["repositories_inspected"] >= 2
    assert res.raw_metadata["repositories_failed"] >= 1
    assert res.raw_metadata["repositories_skipped"] >= 1

    skills = {s.skill for s in res.signals}
    assert "REST APIs" in skills
    assert "Go" in skills
    assert any("broken" in w or "offline" in w for w in res.warnings)


# ===========================================================================
# 10. Canonical normalization
# ===========================================================================

def test_extracted_skills_use_canonical_normalization():
    owner = "canon_dev"
    repos = [
        _inspection_repo(owner, "alpha", {
            "languages": {"TypeScript": 20000},
            "root_files": ["package.json"],
            "package_json_deps": ["React", "next", "postgres"],
            "top_files": ["src/App.tsx"],
            "import_tokens": {"react": 4, "reactjs": 1, "React.js": 1},
        }),
        _inspection_repo(owner, "beta", {
            "languages": {"JavaScript": 8000},
            "root_files": ["package.json"],
            "package_json_deps": ["react.js"],
            "top_files": ["index.js"],
        }),
    ]
    res = _run(GitHubProvider().verify(
        {"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}
    ))
    names = [s.skill for s in res.signals]
    assert len(names) == len(set(names)), "no duplicate skill identities"
    assert "React" in names
    assert "ReactJS" not in names and "react" not in names
    assert "PostgreSQL" in names and "postgres" not in names
    for name in names:
        assert skill_taxonomy.normalize_skill(name) == name


def test_skill_mention_counts_returns_canonical_names_only():
    counts = skill_mention_counts("We used Postgres, ReactJS and Docker. Docker everywhere.")
    assert "PostgreSQL" in counts
    assert "React" in counts
    assert counts["Docker"] >= 2
    for name in counts:
        assert skill_taxonomy.normalize_skill(name) == name


# ===========================================================================
# 11. The live analysis path carries the deeper evidence through
# ===========================================================================

def test_live_analysis_path_uses_deep_github_evidence():
    """
    Mirrors run_analysis: verified GitHub evidence -> signal extraction ->
    canonical normalization -> grouping -> skill assessments.
    """
    owner = "live_dev"
    repos = [
        _inspection_repo(owner, "older-data-project", {
            # No GitHub language stats at all: evidence must come from content.
            "languages": {},
            "root_files": ["README.md"],
            "top_files": ["src/pipeline.py"],
            "import_tokens": {"pandas": 6, "sklearn.linear_model": 3},
            "config_text": "image: postgres:15\nPOSTGRES_DB: app\n",
            "config_files_sampled": ["docker-compose.yml"],
            "readme_text": "Data pipeline project.",
            "tree_scanned": True,
        }, pushed_at=(datetime.now(timezone.utc) - timedelta(days=365 * 5)).isoformat()),
        _inspection_repo(owner, "newer-web-app", {
            "languages": {"TypeScript": 30000},
            "root_files": ["package.json"],
            "package_json_deps": ["react", "express"],
            "top_files": ["src/App.tsx", "server/index.ts"],
        }),
    ]
    verification = _run(GitHubProvider().verify(
        {"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}
    ))
    assert verification.status == VerificationStatus.VERIFIED

    # Evidence row exactly as evidence_service.verify_evidence_item persists it.
    evidence = [{
        "id": "ev-github-profile",
        "evidence_type": "github",
        "source_url": f"https://github.com/{owner}",
        "verification_status": VerificationStatus.VERIFIED,
        "metadata": {
            "verification_status": VerificationStatus.VERIFIED,
            "verified_signals": [s.to_dict() for s in verification.signals],
            "inspection": verification.raw_metadata,
        },
    }]

    raw_signals = ars.extract_skill_signals(evidence, [], [])
    signals = ars.normalize_signals(raw_signals, None)
    grouped = ars.aggregate_skills(signals)

    # Skills proven only by repository *contents* survive to the engine.
    assert "Pandas" in grouped
    assert "Scikit-learn" in grouped
    assert "PostgreSQL" in grouped
    assert "React" in grouped
    for sigs in grouped.values():
        for sig in sigs:
            assert sig["source_type"] == "github"
            assert sig["source_reliability"] == pytest.approx(GITHUB_RELIABILITY)

    req_map = ars.build_requirements_map(
        [
            {"skill": "Pandas", "required_level": 0.7, "importance": 0.6},
            {"skill": "React", "required_level": 0.8, "importance": 0.8},
        ],
        None,
    )
    assessments = {a["canonical_name"]: a for a in ars.calculate_assessments(grouped, req_map, None)}
    assert assessments["Pandas"]["proficiency"] > 0
    assert assessments["Pandas"]["evidence_count"] == 1
    assert assessments["React"]["proficiency"] > 0
    assert assessments["Pandas"]["proficiency"] <= 0.85


def test_evidence_verified_by_older_pipeline_is_refreshed_on_analysis_run():
    """
    Live-path guard: GitHub evidence verified before the deep pipeline existed
    must be re-inspected (cache bypassed) on the next analysis run, otherwise
    users keep seeing the old shallow signals.
    """
    from app.services.evidence.base import EVIDENCE_PIPELINE_VERSION

    legacy = {
        "id": "ev-legacy",
        "evidence_type": "github",
        "source_url": "https://github.com/someone",
        "verification_status": VerificationStatus.VERIFIED,
        "metadata": {"verification_status": VerificationStatus.VERIFIED, "verified_signals": []},
    }
    current = {
        "id": "ev-current",
        "evidence_type": "github",
        "source_url": "https://github.com/someone-else",
        "verification_status": VerificationStatus.VERIFIED,
        "metadata": {
            "verification_status": VerificationStatus.VERIFIED,
            "verified_signals": [],
            "evidence_pipeline_version": EVIDENCE_PIPELINE_VERSION,
        },
    }
    fresh = {"id": "ev-new", "evidence_type": "github", "source_url": "https://github.com/new"}

    assert ars.evidence_refresh_state(legacy) == (False, True)
    assert ars.evidence_refresh_state(current) == (False, False)
    assert ars.evidence_refresh_state(fresh)[0] is True


# ===========================================================================
# 12. Existing scoring formulas are unchanged
# ===========================================================================

def test_scoring_formulas_remain_unchanged():
    assert EvidenceDepth.DEPTH_STRENGTH_MAP == {
        EvidenceDepth.LEVEL_0_URL_ONLY: 0.0,
        EvidenceDepth.LEVEL_1_MENTION: 0.40,
        EvidenceDepth.LEVEL_2_CONFIG: 0.60,
        EvidenceDepth.LEVEL_3_IMPLEMENTATION: 0.75,
        EvidenceDepth.LEVEL_4_SUBSTANTIAL: 0.85,
    }
    # Reliability values are recalibrated in evidence_weights (GitHub 0.70 ->
    # 0.60 -> 0.40); the depth->strength map and the weighted-average formula
    # itself are unchanged.
    assert GITHUB_RELIABILITY == 0.40

    sigs = [
        {"signal_strength": 0.80, "source_reliability": 0.70},
        {"signal_strength": 0.40, "source_reliability": 0.85},
    ]
    expected = (0.80 * 0.70 + 0.40 * 0.85) / (0.70 + 0.85)
    prof, weight, count, avg = skill_engine.proficiency(sigs)
    assert prof == pytest.approx(expected)
    assert weight == pytest.approx(1.55)
    assert count == 2
    assert avg == pytest.approx(0.60)


def test_content_budget_bounds_expensive_reads():
    budget = ContentBudget(2)
    assert budget.take() is True
    assert budget.take() is True
    assert budget.take() is False
    assert budget.remaining == 0
