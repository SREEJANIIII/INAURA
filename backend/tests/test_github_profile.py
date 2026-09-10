import asyncio
import pytest
from typing import Optional, Any
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import httpx

from app.services.evidence.base import (
    EvidenceDepth,
    VerificationStatus,
    ExtractedSignal,
    VerificationResult,
)
from app.services.evidence.github import (
    GitHubProvider,
    parse_github_url,
    GITHUB_RELIABILITY,
    _classify_repository,
)
from app.services import signal_extractor as se
from app.services import skill_engine


# Helper to build mock HTTP responses
def _make_response(status_code: int, json_data: Any = None, headers: Optional[dict] = None) -> MagicMock:
    res = MagicMock(spec=httpx.Response)
    res.status_code = status_code
    res.headers = headers or {}
    if json_data is not None:
        res.json.return_value = json_data
        if isinstance(json_data, (dict, list)):
            import json
            res.text = json.dumps(json_data)
        else:
            res.text = str(json_data)
    else:
        res.text = ""
        res.json.side_effect = Exception("No JSON")
    return res


# ===========================================================================
# 1. TEST 1: SINGLE-PAGE PROFILE (< 100 REPOSITORIES)
# ===========================================================================

def test_single_page_profile_fetches_all_repositories():
    async def _test():
        provider = GitHubProvider()
        owner = "singlepage_dev"

        # 20 repositories in single page
        repos_data = [
            {
                "id": i,
                "name": f"project-{i}",
                "full_name": f"{owner}/project-{i}",
                "html_url": f"https://github.com/{owner}/project-{i}",
                "description": f"Test repo {i}",
                "language": "Python" if i % 2 == 0 else "TypeScript",
                "stargazers_count": i,
                "fork": False,
                "archived": False,
                "size": 1500,
                "pushed_at": datetime.now(timezone.utc).isoformat(),
            }
            for i in range(1, 21)
        ]

        async def mock_get(self, url, *args, **kwargs):
            url_str = str(url)
            if url_str == f"https://api.github.com/users/{owner}":
                return _make_response(200, {"login": owner, "public_repos": 20})
            if url_str == f"https://api.github.com/users/{owner}/repos":
                return _make_response(200, repos_data, headers={"link": ""})
            if "/languages" in url_str:
                return _make_response(200, {"Python": 12000})
            if "/contents" in url_str:
                return _make_response(200, [{"name": "requirements.txt"}])
            if "/git/trees" in url_str:
                return _make_response(200, {"tree": [{"path": "main.py"}]})
            return _make_response(404)

        with patch.object(httpx.AsyncClient, "get", new=mock_get):
            res = await provider.verify({"source_url": f"https://github.com/{owner}"})

        assert res.status == VerificationStatus.VERIFIED
        assert res.raw_metadata["repositories_fetched"] == 20
        assert res.raw_metadata["repositories_inspected"] == 20
        assert len(res.raw_metadata["repositories"]) == 20
        inspected_names = {r["name"] for r in res.raw_metadata["repositories"]}
        for i in range(1, 21):
            assert f"project-{i}" in inspected_names

    asyncio.run(_test())


# ===========================================================================
# 2. TEST 2: MULTI-PAGE PROFILE (137 REPOSITORIES ACROSS MULTIPLE PAGES)
# ===========================================================================

def test_multi_page_profile_137_repositories():
    async def _test():
        provider = GitHubProvider()
        owner = "prolific_dev"

        # Page 1: 100 repositories
        page1_repos = [
            {
                "id": i,
                "name": f"repo-{i}",
                "full_name": f"{owner}/repo-{i}",
                "html_url": f"https://github.com/{owner}/repo-{i}",
                "description": f"Repo #{i}",
                "language": "Python",
                "stargazers_count": 2,
                "fork": False,
                "archived": False,
                "size": 2000,
                "pushed_at": datetime.now(timezone.utc).isoformat(),
            }
            for i in range(1, 101)
        ]

        # Page 2: 37 repositories
        page2_repos = [
            {
                "id": i,
                "name": f"repo-{i}",
                "full_name": f"{owner}/repo-{i}",
                "html_url": f"https://github.com/{owner}/repo-{i}",
                "description": f"Repo #{i}",
                "language": "Go",
                "stargazers_count": 5,
                "fork": False,
                "archived": False,
                "size": 3000,
                "pushed_at": datetime.now(timezone.utc).isoformat(),
            }
            for i in range(101, 138)
        ]

        async def mock_get(self, url, *args, **kwargs):
            url_str = str(url)
            params = kwargs.get("params", {})
            if url_str == f"https://api.github.com/users/{owner}":
                return _make_response(200, {"login": owner, "public_repos": 137})

            if url_str == f"https://api.github.com/users/{owner}/repos":
                page = params.get("page", 1)
                if page == 1:
                    return _make_response(
                        200,
                        page1_repos,
                        headers={"link": f'<https://api.github.com/users/{owner}/repos?page=2&per_page=100>; rel="next"'},
                    )
                elif page == 2:
                    return _make_response(
                        200,
                        page2_repos,
                        headers={"link": f'<https://api.github.com/users/{owner}/repos?page=1&per_page=100>; rel="prev"'},
                    )
                return _make_response(200, [])

            if "/languages" in url_str:
                if "repo-10" in url_str or "repo-11" in url_str:
                    return _make_response(200, {"Go": 8000})
                return _make_response(200, {"Python": 15000})
            if "/contents" in url_str:
                return _make_response(200, [{"name": "requirements.txt"}])
            if "/git/trees" in url_str:
                return _make_response(200, {"tree": [{"path": "main.py"}]})
            return _make_response(404)

        with patch.object(httpx.AsyncClient, "get", new=mock_get):
            res = await provider.verify({"source_url": f"https://github.com/{owner}"})

        assert res.status == VerificationStatus.VERIFIED
        assert res.raw_metadata["repositories_fetched"] == 137
        assert res.raw_metadata["public_repositories"] == 137
        assert len(res.raw_metadata["repositories"]) == 137
        assert res.raw_metadata["repositories_inspected"] == 137

        repo_names = {r["name"] for r in res.raw_metadata["repositories"]}
        assert "repo-1" in repo_names
        assert "repo-100" in repo_names
        assert "repo-101" in repo_names
        assert "repo-137" in repo_names

    asyncio.run(_test())


# ===========================================================================
# 3. TEST 3: OLD 5-REPOSITORY BUG IS FIXED
# ===========================================================================

def test_profile_inspects_beyond_first_five_repositories():
    async def _test():
        provider = GitHubProvider()
        owner = "builder10"

        repos_data = [
            {
                "id": i,
                "name": f"repo-{i}",
                "full_name": f"{owner}/repo-{i}",
                "html_url": f"https://github.com/{owner}/repo-{i}",
                "description": f"Project {i}",
                "language": "Rust" if i == 8 else "Python",
                "stargazers_count": i,
                "fork": False,
                "archived": False,
                "size": 2500,
                "pushed_at": datetime.now(timezone.utc).isoformat(),
            }
            for i in range(1, 11)
        ]

        async def mock_get(self, url, *args, **kwargs):
            url_str = str(url)
            if url_str == f"https://api.github.com/users/{owner}":
                return _make_response(200, {"login": owner, "public_repos": 10})
            if url_str == f"https://api.github.com/users/{owner}/repos":
                return _make_response(200, repos_data)
            if "repo-8/languages" in url_str:
                return _make_response(200, {"Rust": 30000})
            if "repo-8/contents" in url_str:
                return _make_response(200, [{"name": "Cargo.toml"}, {"name": "Dockerfile"}])
            if "/languages" in url_str:
                return _make_response(200, {"Python": 10000})
            if "/contents" in url_str:
                return _make_response(200, [{"name": "requirements.txt"}])
            if "/git/trees" in url_str:
                return _make_response(200, {"tree": [{"path": "src/main.rs" if "repo-8" in url_str else "app.py"}]})
            return _make_response(404)

        with patch.object(httpx.AsyncClient, "get", new=mock_get):
            res = await provider.verify({"source_url": f"https://github.com/{owner}"})

        assert res.status == VerificationStatus.VERIFIED
        assert res.raw_metadata["repositories_fetched"] == 10
        skills = {s.skill: s for s in res.signals}
        assert "Rust" in skills, "Rust in repo-8 must be detected, fixing the 5-repo limitation"
        assert "Docker" in skills, "Docker in repo-8 must be detected, fixing the 5-repo limitation"
        assert "Python" in skills

        names = {r["name"] for r in res.raw_metadata["repositories"]}
        for i in range(6, 11):
            assert f"repo-{i}" in names

    asyncio.run(_test())


# ===========================================================================
# 4. TEST 4: ZERO REPOSITORIES (EMPTY PROFILE DOES NOT CRASH)
# ===========================================================================

def test_zero_repositories_profile_succeeds_without_crashing():
    async def _test():
        provider = GitHubProvider()
        owner = "newbie"

        async def mock_get(self, url, *args, **kwargs):
            url_str = str(url)
            if url_str == f"https://api.github.com/users/{owner}":
                return _make_response(200, {"login": owner, "public_repos": 0})
            if url_str == f"https://api.github.com/users/{owner}/repos":
                return _make_response(200, [])
            return _make_response(404)

        with patch.object(httpx.AsyncClient, "get", new=mock_get):
            res = await provider.verify({"source_url": f"https://github.com/{owner}"})

        assert res.status == VerificationStatus.VERIFIED
        assert res.raw_metadata["public_repositories"] == 0
        assert res.raw_metadata["repositories_fetched"] == 0
        assert res.raw_metadata["repositories_inspected"] == 0
        assert len(res.signals) == 0
        assert len(res.raw_metadata["repositories"]) == 0
        assert "0 public repositories" in res.message

    asyncio.run(_test())


# ===========================================================================
# 5. TEST 5: FORK REPOSITORIES CLASSIFIED AND DISCOUNTED
# ===========================================================================

def test_fork_repositories_classification_and_discount():
    async def _test():
        provider = GitHubProvider()
        owner = "fork_fan"

        repos = [
            {
                "id": 1,
                "name": "my-script",
                "full_name": f"{owner}/my-script",
                "html_url": f"https://github.com/{owner}/my-script",
                "fork": False,
                "archived": False,
                "size": 1000,
                "language": "Python",
                "pushed_at": datetime.now(timezone.utc).isoformat(),
                "inspection": {
                    "languages": {"Python": 10000},
                    "root_files": ["requirements.txt"],
                    "top_files": ["app.py"],
                    "is_fork": False,
                },
            },
            {
                "id": 2,
                "name": "huge-react-app",
                "full_name": f"{owner}/huge-react-app",
                "html_url": f"https://github.com/{owner}/huge-react-app",
                "fork": True,
                "archived": False,
                "size": 50000,
                "language": "TypeScript",
                "pushed_at": datetime.now(timezone.utc).isoformat(),
                "inspection": {
                    "languages": {"TypeScript": 80000, "JavaScript": 20000},
                    "root_files": ["package.json"],
                    "package_json_deps": ["react", "next"],
                    "top_files": ["src/index.tsx"],
                    "is_fork": True,
                },
            },
        ]

        ev = {"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}
        res = await provider.verify(ev)

        assert res.status == VerificationStatus.VERIFIED
        assert res.raw_metadata["forked_repositories"] == 1
        assert res.raw_metadata["owned_repositories"] == 1

        skills = {s.skill: s for s in res.signals}
        assert "Python" in skills
        assert skills["Python"].depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION
        assert skills["Python"].signal_strength >= 0.75

        # Forked React must be discounted to config level (depth <= 2, strength <= 0.55)
        assert "React" in skills
        assert skills["React"].depth <= EvidenceDepth.LEVEL_2_CONFIG
        assert skills["React"].signal_strength <= 0.55
        assert "[Forked Repositories]" in skills["React"].reason
        assert skills["React"].metadata.get("is_fork") is True

    asyncio.run(_test())


# ===========================================================================
# 6. TEST 6: ARCHIVED REPOSITORIES PRESERVED AS HISTORICAL EVIDENCE
# ===========================================================================

def test_archived_repositories_classification_and_historical_evidence():
    async def _test():
        provider = GitHubProvider()
        owner = "veteran_coder"

        repos = [
            {
                "id": 1,
                "name": "legacy-java-project",
                "full_name": f"{owner}/legacy-java-project",
                "html_url": f"https://github.com/{owner}/legacy-java-project",
                "fork": False,
                "archived": True,
                "size": 12000,
                "language": "Java",
                "pushed_at": (datetime.now(timezone.utc) - timedelta(days=365 * 4)).isoformat(),
                "inspection": {
                    "languages": {"Java": 45000},
                    "root_files": ["pom.xml"],
                    "top_files": ["src/Main.java", "src/Service.java", "src/Dao.java"],
                    "java_file_count": 5,
                    "has_java_build_manifest": True,
                    "archived": True,
                },
            }
        ]

        ev = {"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}
        res = await provider.verify(ev)

        assert res.status == VerificationStatus.VERIFIED
        assert res.raw_metadata["archived_repositories"] == 1

        skills = {s.skill: s for s in res.signals}
        assert "Java" in skills
        java_sig = skills["Java"]
        assert java_sig.metadata.get("archived") is True
        assert java_sig.metadata.get("historical_only") is True
        assert "[Archived Repositories]" in java_sig.reason
        assert java_sig.signal_strength <= 0.70

    asyncio.run(_test())


# ===========================================================================
# 7. TEST 7: FAILED REPOSITORY ISOLATION (PROFILE ANALYSIS CONTINUES)
# ===========================================================================

def test_failed_repository_does_not_abort_entire_profile():
    async def _test():
        provider = GitHubProvider()
        owner = "mixed_status_dev"

        repos_data = [
            {
                "id": 1,
                "name": "good-project",
                "full_name": f"{owner}/good-project",
                "html_url": f"https://github.com/{owner}/good-project",
                "language": "Python",
                "fork": False,
                "archived": False,
                "size": 2000,
                "pushed_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": 2,
                "name": "corrupt-or-private-project",
                "full_name": f"{owner}/corrupt-or-private-project",
                "html_url": f"https://github.com/{owner}/corrupt-or-private-project",
                "language": "C++",
                "fork": False,
                "archived": False,
                "size": 500,
                "pushed_at": datetime.now(timezone.utc).isoformat(),
            },
        ]

        async def mock_get(self, url, *args, **kwargs):
            url_str = str(url)
            if url_str == f"https://api.github.com/users/{owner}":
                return _make_response(200, {"login": owner, "public_repos": 2})
            if url_str == f"https://api.github.com/users/{owner}/repos":
                return _make_response(200, repos_data)
            if "good-project/languages" in url_str:
                return _make_response(200, {"Python": 15000})
            if "good-project/contents" in url_str:
                return _make_response(200, [{"name": "requirements.txt"}])
            if "good-project/git/trees" in url_str:
                return _make_response(200, {"tree": [{"path": "app.py"}]})
            if "corrupt-or-private-project" in url_str:
                return _make_response(500, {"message": "Internal GitHub Error"})
            return _make_response(404)

        with patch.object(httpx.AsyncClient, "get", new=mock_get):
            res = await provider.verify({"source_url": f"https://github.com/{owner}"})

        assert res.status == VerificationStatus.VERIFIED
        assert res.raw_metadata["repositories_fetched"] == 2
        assert res.raw_metadata["repositories_inspected"] == 1
        assert res.raw_metadata["repositories_failed"] == 1
        assert any("corrupt-or-private-project" in w for w in res.warnings)

        skills = {s.skill: s for s in res.signals}
        assert "Python" in skills

    asyncio.run(_test())


# ===========================================================================
# 8. TEST 8: RATE LIMIT HANDLING (HTTP 403 / 429)
# ===========================================================================

def test_rate_limit_initial_lookup_graceful_failure():
    async def _test():
        provider = GitHubProvider()
        owner = "rate_limited_user"

        async def mock_get(self, url, *args, **kwargs):
            return _make_response(
                403,
                {"message": "API rate limit exceeded"},
                headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1773000000"},
            )

        with patch.object(httpx.AsyncClient, "get", new=mock_get):
            res = await provider.verify({"source_url": f"https://github.com/{owner}"})

        assert res.status == VerificationStatus.FAILED
        assert "rate limited" in res.message.lower()
        assert len(res.signals) == 0

    asyncio.run(_test())


def test_rate_limit_during_pagination_returns_partial_evidence():
    async def _test():
        provider = GitHubProvider()
        owner = "huge_portfolio_user"

        page1_repos = [
            {
                "id": i,
                "name": f"project-{i}",
                "full_name": f"{owner}/project-{i}",
                "html_url": f"https://github.com/{owner}/project-{i}",
                "language": "Python",
                "fork": False,
                "archived": False,
                "size": 1000,
                "pushed_at": datetime.now(timezone.utc).isoformat(),
            }
            for i in range(1, 101)
        ]

        async def mock_get(self, url, *args, **kwargs):
            url_str = str(url)
            params = kwargs.get("params", {})
            if url_str == f"https://api.github.com/users/{owner}":
                return _make_response(200, {"login": owner, "public_repos": 150})
            if url_str == f"https://api.github.com/users/{owner}/repos":
                page = params.get("page", 1)
                if page == 1:
                    return _make_response(
                        200,
                        page1_repos,
                        headers={"link": f'<https://api.github.com/users/{owner}/repos?page=2&per_page=100>; rel="next"'},
                    )
                return _make_response(
                    429,
                    {"message": "Too many requests"},
                    headers={"x-ratelimit-remaining": "0"},
                )
            if "/languages" in url_str:
                return _make_response(200, {"Python": 5000})
            if "/contents" in url_str:
                return _make_response(200, [{"name": "requirements.txt"}])
            if "/git/trees" in url_str:
                return _make_response(200, {"tree": [{"path": "main.py"}]})
            return _make_response(404)

        with patch.object(httpx.AsyncClient, "get", new=mock_get):
            res = await provider.verify({"source_url": f"https://github.com/{owner}"})

        assert res.status == VerificationStatus.VERIFIED
        assert res.raw_metadata["repositories_fetched"] == 100
        assert any("rate limit" in w.lower() for w in res.warnings)
        assert len(res.signals) > 0

    asyncio.run(_test())


# ===========================================================================
# 9. TEST 9: AGGREGATION (NO UNCONTROLLED DUPLICATE SIGNALS)
# ===========================================================================

def test_aggregation_deduplicates_same_skill_across_repositories():
    async def _test():
        provider = GitHubProvider()
        owner = "python_dev"

        # 4 independent repositories, all implementing Python
        repos = [
            {
                "id": 1,
                "name": "web-service",
                "full_name": f"{owner}/web-service",
                "fork": False,
                "archived": False,
                "size": 5000,
                "language": "Python",
                "pushed_at": datetime.now(timezone.utc).isoformat(),
                "inspection": {
                    "languages": {"Python": 25000},
                    "root_files": ["requirements.txt", "Dockerfile"],
                    "top_files": ["app/main.py", "tests/test_main.py"],
                    "python_deps": ["fastapi", "pytest"],
                    "is_fork": False,
                },
            },
            {
                "id": 2,
                "name": "data-pipeline",
                "full_name": f"{owner}/data-pipeline",
                "fork": False,
                "archived": False,
                "size": 4000,
                "language": "Python",
                "pushed_at": datetime.now(timezone.utc).isoformat(),
                "inspection": {
                    "languages": {"Python": 18000},
                    "root_files": ["requirements.txt"],
                    "top_files": ["pipeline.py"],
                    "python_deps": ["pandas"],
                    "is_fork": False,
                },
            },
            {
                "id": 3,
                "name": "cli-utility",
                "full_name": f"{owner}/cli-utility",
                "fork": False,
                "archived": False,
                "size": 2000,
                "language": "Python",
                "pushed_at": datetime.now(timezone.utc).isoformat(),
                "inspection": {
                    "languages": {"Python": 8000},
                    "root_files": ["setup.py"],
                    "top_files": ["cli.py"],
                    "is_fork": False,
                },
            },
            {
                "id": 4,
                "name": "ml-experiment",
                "full_name": f"{owner}/ml-experiment",
                "fork": False,
                "archived": False,
                "size": 3000,
                "language": "Python",
                "pushed_at": datetime.now(timezone.utc).isoformat(),
                "inspection": {
                    "languages": {"Python": 12000},
                    "root_files": ["requirements.txt"],
                    "top_files": ["train.py"],
                    "python_deps": ["torch"],
                    "is_fork": False,
                },
            },
        ]

        ev = {"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}
        res = await provider.verify(ev)

        assert res.status == VerificationStatus.VERIFIED

        # Check Python signals: MUST BE EXACTLY ONE AGGREGATED SIGNAL, NOT 4 DUPLICATES!
        py_signals = [s for s in res.signals if s.skill == "Python"]
        assert len(py_signals) == 1, f"Expected exactly 1 aggregated Python signal, got {len(py_signals)}"

        sig = py_signals[0]
        # Maximum depth LEVEL_4_SUBSTANTIAL preserved (from web-service which had tests + >5000 bytes)
        assert sig.depth == EvidenceDepth.LEVEL_4_SUBSTANTIAL
        assert sig.signal_strength == 0.85
        assert "4 public repositories" in sig.reason
        assert sig.metadata["repo_count"] == 4
        assert sig.metadata["owned_count"] == 4

        # Check Git signals: MUST BE EXACTLY ONE AGGREGATED SIGNAL, NOT 4 DUPLICATES!
        git_signals = [s for s in res.signals if s.skill == "Git"]
        assert len(git_signals) == 1, f"Expected exactly 1 aggregated Git signal, got {len(git_signals)}"

        # Verify skill engine calculation: ONE GitHub signal weight (0.70)
        prof, weight, count, avg_val = skill_engine.proficiency([sig.to_dict()])
        assert weight == GITHUB_RELIABILITY
        assert prof == 0.85

    asyncio.run(_test())


# ===========================================================================
# 10. TEST 10: PROVENANCE PRESERVATION
# ===========================================================================

def test_provenance_preserves_repositories_urls_and_status():
    async def _test():
        provider = GitHubProvider()
        owner = "provenance_master"

        repos = [
            {
                "id": 101,
                "name": "frontend-web",
                "full_name": f"{owner}/frontend-web",
                "html_url": f"https://github.com/{owner}/frontend-web",
                "fork": False,
                "archived": False,
                "size": 8000,
                "language": "TypeScript",
                "pushed_at": datetime.now(timezone.utc).isoformat(),
                "inspection": {
                    "languages": {"TypeScript": 25000},
                    "root_files": ["package.json"],
                    "package_json_deps": ["react"],
                    "top_files": ["src/App.tsx"],
                    "is_fork": False,
                },
            },
            {
                "id": 102,
                "name": "upstream-react-docs",
                "full_name": f"{owner}/upstream-react-docs",
                "html_url": f"https://github.com/{owner}/upstream-react-docs",
                "fork": True,
                "archived": False,
                "size": 3000,
                "language": "TypeScript",
                "pushed_at": datetime.now(timezone.utc).isoformat(),
                "inspection": {
                    "languages": {"TypeScript": 5000},
                    "root_files": ["package.json"],
                    "package_json_deps": ["react"],
                    "top_files": ["docs/guide.tsx"],
                    "is_fork": True,
                },
            },
        ]

        ev = {"source_url": f"https://github.com/{owner}", "mock_profile_repos": repos}
        res = await provider.verify(ev)

        react_sig = next(s for s in res.signals if s.skill == "React")
        assert "repositories" in react_sig.metadata
        provenance = react_sig.metadata["repositories"]

        assert len(provenance) == 2
        repo1_info = next(r for r in provenance if r["name"] == "frontend-web")
        assert repo1_info["url"] == f"https://github.com/{owner}/frontend-web"
        assert repo1_info["fork"] is False
        assert repo1_info["archived"] is False

        repo2_info = next(r for r in provenance if r["name"] == "upstream-react-docs")
        assert repo2_info["url"] == f"https://github.com/{owner}/upstream-react-docs"
        assert repo2_info["fork"] is True
        assert repo2_info["archived"] is False

    asyncio.run(_test())


# ===========================================================================
# 11. TEST 11: DIRECT REPOSITORY REGRESSION
# ===========================================================================

def test_direct_repository_inspection_continues_to_work_unchanged():
    async def _test():
        provider = GitHubProvider()

        ev = {
            "evidence_type": "github",
            "source_url": "https://github.com/alice/microservice",
            "mock_inspection": {
                "name": "microservice",
                "languages": {"Python": 18000},
                "root_files": ["requirements.txt", "Dockerfile"],
                "top_files": ["app.py", "tests/test_api.py"],
                "package_json_deps": [],
                "python_deps": ["fastapi", "pytest", "redis"],
                "is_fork": False,
            },
        }

        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED
        skills = {s.skill: s for s in res.signals}

        assert "Python" in skills
        assert "REST APIs" in skills
        assert "Docker" in skills
        assert "Redis" in skills
        assert "Testing" in skills
        assert "Git" in skills

        assert res.raw_metadata.get("name") == "microservice"

    asyncio.run(_test())


# ===========================================================================
# 12. REPOSITORY CLASSIFIER UNIT TESTS
# ===========================================================================

def test_classify_repository_dimensions():
    now = datetime.now(timezone.utc)

    # 1. Owned active
    r_owned = {"name": "cool-tool", "fork": False, "archived": False, "size": 1000, "pushed_at": now.isoformat()}
    c = _classify_repository(r_owned, "alice", now)
    assert c["classification"] == "owned_active"
    assert c["is_owned"] is True
    assert c["is_active"] is True

    # 2. Fork
    r_fork = {"name": "awesome-lib", "fork": True, "archived": False, "size": 5000, "pushed_at": now.isoformat()}
    c_fork = _classify_repository(r_fork, "alice", now)
    assert c_fork["classification"] == "fork"
    assert c_fork["is_fork"] is True

    # 3. Archived
    r_archived = {"name": "old-code", "fork": False, "archived": True, "size": 2000, "pushed_at": (now - timedelta(days=500)).isoformat()}
    c_arch = _classify_repository(r_archived, "alice", now)
    assert c_arch["classification"] == "archived"
    assert c_arch["is_archived"] is True

    # 4. Low evidence (empty)
    r_empty = {"name": "empty-repo", "fork": False, "archived": False, "size": 0, "language": None}
    c_empty = _classify_repository(r_empty, "alice", now)
    assert c_empty["classification"] == "low_evidence"
    assert c_empty["is_low_evidence"] is True

    # 5. Tutorial / demo
    r_tutorial = {"name": "react-tutorial-demo", "fork": False, "archived": False, "size": 500, "pushed_at": now.isoformat()}
    c_tut = _classify_repository(r_tutorial, "alice", now)
    assert c_tut["classification"] == "tutorial_demo"
    assert c_tut["is_tutorial_demo"] is True
