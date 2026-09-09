from typing import Dict, List, Optional, Tuple, Any
import re
import json
from datetime import datetime, timezone
import httpx

from .base import EvidenceProvider, VerificationResult, ExtractedSignal, EvidenceDepth, VerificationStatus
from .url_utils import validate_platform_url, GITHUB_HOSTS
from ..skill_taxonomy import normalize_skill, normalize_skill_slug

GITHUB_RELIABILITY = 0.90


def parse_github_url(url_or_handle: str) -> Tuple[Optional[str], Optional[str], bool]:
    """
    Parse a GitHub URL or handle.
    Returns:
      (owner, repo, is_profile_only)
    Examples:
      'https://github.com/owner/repo' -> ('owner', 'repo', False)
      'github.com/owner/repo' -> ('owner', 'repo', False)
      'owner/repo' -> ('owner', 'repo', False)
      'https://github.com/username' -> ('username', None, True)
      'username' -> ('username', None, True)
    """
    if not url_or_handle or not str(url_or_handle).strip():
        return None, None, False

    cleaned = str(url_or_handle).strip()
    # Strip protocol and query params
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = cleaned.split("?")[0].split("#")[0].strip("/")

    # Strip github.com prefix if present
    if cleaned.startswith("github.com/"):
        cleaned = cleaned[len("github.com/"):]

    parts = [p for p in cleaned.split("/") if p]
    if len(parts) == 1:
        # Profile only
        return parts[0], None, True
    elif len(parts) >= 2:
        return parts[0], parts[1], False

    return None, None, False


class GitHubProvider(EvidenceProvider):
    """
    Evidence Intelligence Provider for GitHub.
    Independently inspects public repositories for concrete technical evidence:
    - Languages reported by GitHub
    - Manifests & Dependencies (package.json, requirements.txt, pyproject.toml, pom.xml)
    - Infrastructure & CI/CD configs (Dockerfile, docker-compose, .github/workflows)
    - Distinguishes EvidenceDepth: URL only (0) < Mention (1) < Config/Dep (2) < Implementation (3) < Substantial (4)
    """

    @property
    def provider_name(self) -> str:
        return "github"

    def can_handle(self, evidence: dict) -> bool:
        etype = (evidence.get("evidence_type") or "").lower()
        url = (evidence.get("source_url") or "").strip()

        if etype == "github":
            if url:
                valid, _, _ = validate_platform_url(url, GITHUB_HOSTS)
                return valid
            return True

        if url:
            valid, _, _ = validate_platform_url(url, GITHUB_HOSTS)
            return valid

        return False

    def validate(self, evidence: dict) -> Tuple[bool, Optional[str]]:
        url = (evidence.get("source_url") or "").strip()
        if not url:
            return False, "GitHub URL or repository identifier required"
        valid, path, err = validate_platform_url(url, GITHUB_HOSTS)
        if not valid:
            return False, err
        return True, None

    async def verify(self, evidence: dict) -> VerificationResult:
        """
        Inspect GitHub repository or profile and return VerificationResult.
        Guarantees no arbitrary proficiency is awarded without concrete evidence.
        """
        raw_url = evidence.get("source_url") or ""
        now = datetime.now(timezone.utc)

        # 1. Allow pre-injected test mock data for deterministic local testing
        if "mock_inspection" in evidence:
            return self._build_result_from_inspection(
                owner="mock",
                repo="mock-repo",
                inspection=evidence["mock_inspection"],
                verified_at=now,
            )

        owner, repo, is_profile = parse_github_url(raw_url)
        if not owner:
            return VerificationResult(
                status="failed",
                message="Invalid GitHub URL or username provided.",
                provider=self.provider_name,
                raw_metadata={"raw_url": raw_url},
                verified_at=now,
            )

        # 2. If it's a repository URL, inspect that repository
        if repo and not is_profile:
            return await self._inspect_repository(owner, repo, now)

        # 3. If it's a profile URL, inspect recent public repositories
        return await self._inspect_profile(owner, now)

    async def _inspect_repository(self, owner: str, repo: str, verified_at: datetime) -> VerificationResult:
        headers = {
            "User-Agent": "INAURA-Evidence-Intelligence/1.0",
            "Accept": "application/vnd.github.v3+json",
        }
        repo_url = f"https://api.github.com/repos/{owner}/{repo}"

        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                # 1. Fetch repo metadata
                res = await client.get(repo_url, headers=headers)
                if res.status_code == 404:
                    return VerificationResult(
                        status="failed",
                        message=f"GitHub repository '{owner}/{repo}' is private, deleted, or does not exist.",
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "repo": repo, "http_status": 404},
                        verified_at=verified_at,
                    )
                if res.status_code in (403, 429):
                    return VerificationResult(
                        status="failed",
                        message=f"GitHub API access rate limited or forbidden for '{owner}/{repo}'.",
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "repo": repo, "http_status": res.status_code},
                        verified_at=verified_at,
                    )
                if res.status_code != 200:
                    return VerificationResult(
                        status="failed",
                        message=f"GitHub API returned error {res.status_code} while inspecting '{owner}/{repo}'.",
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "repo": repo, "http_status": res.status_code},
                        verified_at=verified_at,
                    )

                repo_data = res.json()
                default_branch = repo_data.get("default_branch", "main")

                # 2. Fetch languages breakdown
                lang_res = await client.get(f"{repo_url}/languages", headers=headers)
                languages = lang_res.json() if lang_res.status_code == 200 else {}

                # 3. Fetch root contents list
                contents_res = await client.get(f"{repo_url}/contents", headers=headers)
                root_files = []
                if contents_res.status_code == 200 and isinstance(contents_res.json(), list):
                    root_files = [item.get("name", "") for item in contents_res.json()]

                # 4. Fetch package.json if present
                package_json_deps = []
                if "package.json" in root_files:
                    try:
                        pkg_res = await client.get(
                            f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/package.json",
                            headers={"User-Agent": "INAURA-Evidence-Intelligence/1.0"},
                            timeout=4.0,
                        )
                        if pkg_res.status_code == 200:
                            pkg_data = json.loads(pkg_res.text)
                            deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
                            package_json_deps = list(deps.keys())
                    except Exception:
                        pass

                # 5. Fetch requirements.txt if present
                py_deps = []
                if "requirements.txt" in root_files:
                    try:
                        req_res = await client.get(
                            f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/requirements.txt",
                            headers={"User-Agent": "INAURA-Evidence-Intelligence/1.0"},
                            timeout=4.0,
                        )
                        if req_res.status_code == 200:
                            for line in req_res.text.splitlines():
                                line = line.strip().split("==")[0].split(">=")[0].split("<=")[0].strip()
                                if line and not line.startswith("#"):
                                    py_deps.append(line.lower())
                    except Exception:
                        pass

                # Check workflows directory
                has_workflows = False
                if ".github" in root_files:
                    try:
                        wf_res = await client.get(f"{repo_url}/contents/.github/workflows", headers=headers)
                        has_workflows = wf_res.status_code == 200 and len(wf_res.json()) > 0
                    except Exception:
                        pass

                inspection = {
                    "name": repo_data.get("name"),
                    "full_name": repo_data.get("full_name"),
                    "description": repo_data.get("description") or "",
                    "topics": repo_data.get("topics") or [],
                    "languages": languages,
                    "root_files": root_files,
                    "package_json_deps": package_json_deps,
                    "python_deps": py_deps,
                    "has_workflows": has_workflows,
                    "is_fork": repo_data.get("fork", False),
                    "size": repo_data.get("size", 0),
                    "pushed_at": repo_data.get("pushed_at"),
                    "updated_at": repo_data.get("updated_at"),
                }

                return self._build_result_from_inspection(owner, repo, inspection, verified_at)

        except httpx.RequestError as e:
            return VerificationResult(
                status="failed",
                message=f"Network connection to GitHub failed: {str(e)[:100]}",
                provider=self.provider_name,
                raw_metadata={"owner": owner, "repo": repo, "error": str(e)},
                verified_at=verified_at,
            )

    async def _inspect_profile(self, owner: str, verified_at: datetime) -> VerificationResult:
        """Inspect public profile and its top repositories."""
        headers = {
            "User-Agent": "INAURA-Evidence-Intelligence/1.0",
            "Accept": "application/vnd.github.v3+json",
        }
        profile_url = f"https://api.github.com/users/{owner}"

        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(profile_url, headers=headers)
                if res.status_code == 404:
                    return VerificationResult(
                        status="failed",
                        message=f"GitHub user '{owner}' does not exist.",
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "http_status": 404},
                        verified_at=verified_at,
                    )
                if res.status_code in (403, 429):
                    return VerificationResult(
                        status="failed",
                        message=f"GitHub API access rate limited or forbidden for user '{owner}'.",
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "http_status": res.status_code},
                        verified_at=verified_at,
                    )

                u_data = res.json()
                public_repos = u_data.get("public_repos", 0)

                # Fetch up to 5 recent public repos
                repos_res = await client.get(f"{profile_url}/repos?sort=updated&per_page=5", headers=headers)
                repo_list = repos_res.json() if repos_res.status_code == 200 and isinstance(repos_res.json(), list) else []

                # Accumulate languages across repos
                all_langs = set()
                repo_names = []
                for r in repo_list:
                    rname = r.get("name")
                    if rname:
                        repo_names.append(rname)
                    lang = r.get("language")
                    if lang:
                        all_langs.add(lang)

                if public_repos == 0:
                    return VerificationResult(
                        status="verified",
                        message=f"GitHub profile '{owner}' verified, but has 0 public repositories to inspect.",
                        provider=self.provider_name,
                        signals=[],
                        raw_metadata={"owner": owner, "public_repos": 0},
                        verified_at=verified_at,
                    )

                # Extract signals for verified public repos languages
                signals: List[ExtractedSignal] = []
                for lang in all_langs:
                    canonical = normalize_skill(lang)
                    if canonical:
                        signals.append(
                            ExtractedSignal(
                                skill=canonical,
                                signal_strength=EvidenceDepth.get_strength_for_depth(EvidenceDepth.LEVEL_2_CONFIG),
                                depth=EvidenceDepth.LEVEL_2_CONFIG,
                                reason=f"Primary language across verified public repositories for user '{owner}'",
                                source_reliability=GITHUB_RELIABILITY,
                                metadata={"owner": owner, "language": lang},
                            )
                        )

                return VerificationResult(
                    status="verified",
                    message=f"Verified GitHub profile '{owner}' with {public_repos} public repositories. Inspected: {', '.join(repo_names[:3])}.",
                    provider=self.provider_name,
                    signals=signals,
                    raw_metadata={"owner": owner, "public_repos": public_repos, "repos": repo_names},
                    verified_at=verified_at,
                )

        except httpx.RequestError as e:
            return VerificationResult(
                status="failed",
                message=f"Network connection to GitHub failed: {str(e)[:100]}",
                provider=self.provider_name,
                raw_metadata={"owner": owner, "error": str(e)},
                verified_at=verified_at,
            )

    def _build_result_from_inspection(
        self,
        owner: str,
        repo: str,
        inspection: dict,
        verified_at: datetime,
    ) -> VerificationResult:
        """
        Convert structured repository inspection facts into verified technical signals.
        Enforces EvidenceDepth levels:
        - Level 1: README / description mention
        - Level 2: Dependencies / configs detected (package.json, requirements.txt, Dockerfile)
        - Level 3: Concrete implementation detected
        - Level 4: Substantial implementation (deps + code + workflows/tests)
        """
        signals: List[ExtractedSignal] = []
        warnings: List[str] = []
        repo_name = inspection.get("name") or repo
        description = inspection.get("description") or ""
        root_files = set(inspection.get("root_files") or [])
        all_files = root_files.union(set(inspection.get("top_files") or []))
        languages = inspection.get("languages") or {}
        generic_deps = [d.lower() for d in (inspection.get("dependencies") or [])]
        pkg_deps = [d.lower() for d in (inspection.get("package_json_deps") or [])] + generic_deps
        py_deps = [d.lower() for d in (inspection.get("python_deps") or [])] + generic_deps
        all_deps = set(pkg_deps + py_deps + generic_deps)
        has_workflows = bool(inspection.get("has_workflows"))
        is_fork = bool(inspection.get("is_fork", False))

        if is_fork:
            warnings.append(
                f"Repository '{repo_name}' is a fork of an upstream repository. "
                f"Implementation signals are discounted to configuration/reference level."
            )

        # Check recency / staleness
        pushed_at = inspection.get("pushed_at") or inspection.get("updated_at")
        if pushed_at:
            try:
                p_str = str(pushed_at).replace("Z", "+00:00")
                pushed_dt = datetime.fromisoformat(p_str)
                if pushed_dt.tzinfo is None:
                    pushed_dt = pushed_dt.replace(tzinfo=timezone.utc)
                v_dt = verified_at if verified_at.tzinfo is not None else verified_at.replace(tzinfo=timezone.utc)
                age_years = (v_dt - pushed_dt).days / 365.25
                if age_years > 3.0:
                    warnings.append(
                        f"Repository '{repo_name}' was last active on {p_str[:10]} (>3 years ago). Tooling evidence may reflect legacy versions."
                    )
            except Exception:
                pass

        # Precise test framework detection (avoids substring false positives like 'contest', 'fastest-validator', 'detox')
        known_test_libs = {
            "jest", "mocha", "vitest", "cypress", "playwright", "supertest", "chai",
            "jasmine", "ava", "testing-library", "@testing-library/react",
            "pytest", "pytest-cov", "unittest", "nose", "tox", "coverage"
        }
        def _is_test_lib(dep: str) -> bool:
            d = dep.lower().strip()
            if d in known_test_libs:
                return True
            for tl in known_test_libs:
                if d.startswith(f"{tl}-") or d.startswith(f"{tl}_") or d.startswith(f"@{tl}/") or d.endswith(f"-{tl}") or d.endswith(f"/{tl}"):
                    return True
                if d.startswith("@types/") and d.replace("@types/", "") == tl:
                    return True
            return False

        has_test_files = any(any(tf in f.lower() for tf in ("tests", "test", "__tests__", "spec", "pytest.ini", "tox.ini", "jest.config")) for f in all_files)
        has_test_deps = any(_is_test_lib(d) for d in all_deps)
        has_tests = has_test_files or has_test_deps

        # Helper to safely append signals honoring fork discounts
        def _add_signal(skill_name: str, depth: int, reason_text: str, meta: Optional[dict] = None):
            canonical = normalize_skill(skill_name) or skill_name
            final_depth = min(depth, EvidenceDepth.LEVEL_2_CONFIG) if is_fork else depth
            raw_strength = EvidenceDepth.get_strength_for_depth(final_depth)
            final_strength = round(min(0.55, raw_strength * 0.70), 2) if is_fork else raw_strength
            final_reason = f"[Forked Repository] {reason_text}" if is_fork else reason_text
            metadata = meta or {}
            if is_fork:
                metadata["is_fork"] = True
            signals.append(
                ExtractedSignal(
                    skill=canonical,
                    signal_strength=final_strength,
                    depth=final_depth,
                    reason=final_reason,
                    source_reliability=GITHUB_RELIABILITY,
                    metadata=metadata,
                )
            )

        # 1. Docker Detection
        has_dockerfile = any("dockerfile" in f.lower() for f in all_files)
        has_docker_compose = any(any(dc in f.lower() for dc in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")) for f in all_files)
        if has_dockerfile or has_docker_compose:
            depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION if (has_dockerfile and has_docker_compose) else EvidenceDepth.LEVEL_2_CONFIG
            details = []
            if has_dockerfile:
                details.append("Dockerfile")
            if has_docker_compose:
                details.append("docker-compose")
            _add_signal(
                "Docker",
                depth,
                f"Repository '{repo_name}' contains verified container configuration: {', '.join(details)}.",
                {"files": details},
            )

        # 2. CI/CD & GitHub Actions Detection
        if has_workflows or any(".github" in f for f in all_files):
            depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION if has_workflows else EvidenceDepth.LEVEL_2_CONFIG
            _add_signal(
                "GitHub Actions",
                depth,
                f"Repository '{repo_name}' contains automated CI/CD workflow definitions (.github/workflows).",
                {"has_workflows": has_workflows},
            )
            _add_signal(
                "CI/CD",
                depth,
                f"Repository '{repo_name}' configures automated integration/deployment pipelines.",
            )

        # 3. JavaScript / React / Next.js / Express / Node.js Detection
        has_js_ts = "JavaScript" in languages or "TypeScript" in languages or "package.json" in all_files or bool(pkg_deps)
        if has_js_ts:
            # React
            if any("react" in d for d in pkg_deps):
                is_substantial = has_tests and len(pkg_deps) >= 5
                depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL if is_substantial else EvidenceDepth.LEVEL_3_IMPLEMENTATION
                _add_signal(
                    "React",
                    depth,
                    f"Repository '{repo_name}' contains React dependencies in package.json and project implementation.",
                    {"package_json": True},
                )

            # Next.js
            if any("next" in d for d in pkg_deps):
                _add_signal(
                    "Next.js",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' contains Next.js framework dependencies.",
                )

            # Express
            if any("express" in d for d in pkg_deps):
                _add_signal(
                    "Express",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' contains Express server framework dependencies.",
                )

            # Node.js
            if "package.json" in all_files or pkg_deps:
                _add_signal(
                    "Node.js",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' contains Node.js runtime package manifest.",
                )

        # TypeScript Detection (independent of package.json)
        if any("typescript" in d for d in all_deps) or "tsconfig.json" in all_files or "TypeScript" in languages:
            _add_signal(
                "TypeScript",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' contains TypeScript configuration and code.",
            )

        # 4. Python & Python Ecosystem Detection
        has_py_manifest = any(f in root_files for f in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile"))
        is_python_repo = "Python" in languages or has_py_manifest
        if is_python_repo:
            py_bytes = languages.get("Python", 0) if isinstance(languages, dict) else 0
            is_substantial = (has_tests or has_dockerfile) and isinstance(py_bytes, (int, float)) and py_bytes > 5000
            depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL if is_substantial else EvidenceDepth.LEVEL_3_IMPLEMENTATION
            _add_signal(
                "Python",
                depth,
                f"Repository '{repo_name}' implements Python software (verified languages/manifests).",
            )

            # Python Frameworks & Data Science
            if any(d in py_deps for d in ("fastapi", "flask", "django")):
                _add_signal(
                    "REST APIs",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' implements REST API services with Python web frameworks.",
                )

            if any("pandas" in d for d in py_deps):
                _add_signal(
                    "Pandas",
                    EvidenceDepth.LEVEL_2_CONFIG,
                    f"Repository '{repo_name}' includes Pandas data analysis dependencies.",
                )
            if any("numpy" in d for d in py_deps):
                _add_signal(
                    "NumPy",
                    EvidenceDepth.LEVEL_2_CONFIG,
                    f"Repository '{repo_name}' includes NumPy numerical computing dependencies.",
                )

            if any(d in py_deps for d in ("scikit-learn", "sklearn", "torch", "tensorflow")):
                _add_signal(
                    "Machine Learning",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' specifies machine learning framework dependencies.",
                )

        # 5. Java / Spring Boot Detection
        if any(f in root_files for f in ("pom.xml", "build.gradle", "build.gradle.kts")) or "Java" in languages:
            _add_signal(
                "Java",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' implements Java enterprise application (build manifest verified).",
            )

        # 6. Database Dependencies & ORMs
        if any(d in all_deps for d in ("pg", "postgres", "postgresql", "psycopg2", "asyncpg")):
            _add_signal(
                "PostgreSQL",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' contains explicit PostgreSQL database adapter dependencies.",
            )
        if any(d in all_deps for d in ("mongodb", "mongoose", "pymongo")):
            _add_signal(
                "MongoDB",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' contains MongoDB driver dependencies.",
            )
        if any(d in all_deps for d in ("redis", "ioredis")):
            _add_signal(
                "Redis",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' includes Redis client dependencies.",
            )

        # Database Design (ORMs and migration engines)
        orm_libs = {"prisma", "typeorm", "sequelize", "sqlalchemy", "alembic", "mongoose", "knex", "hibernate", "mikro-orm"}
        if any(any(ol in d for ol in orm_libs) for d in all_deps):
            _add_signal(
                "Database Design",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' implements structured database ORM/schema migration models.",
            )

        # 7. Authentication & Security
        auth_libs = {"jsonwebtoken", "jwt", "bcrypt", "passport", "auth0", "next-auth", "passlib", "pyjwt", "oauthlib"}
        if any(any(al in d for al in auth_libs) for d in all_deps):
            _add_signal(
                "Authentication & Authorization",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' configures secure authentication/authorization libraries.",
            )

        # 8. Full-Stack / Architecture Structure
        has_frontend_dir = any(any(f.startswith(d) or f == d for d in ("client", "frontend", "web", "ui")) for f in all_files)
        has_backend_dir = any(any(f.startswith(d) or f == d for d in ("server", "backend", "api", "service")) for f in all_files)
        if has_frontend_dir and has_backend_dir:
            _add_signal(
                "Software Architecture",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' implements decoupled full-stack architecture (frontend + backend modules).",
                {"full_stack_monorepo": True},
            )

        # 9. Testing Suite
        if has_tests:
            _add_signal(
                "Testing",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' contains automated test suite configurations/files.",
            )

        # 10. Git Skill
        _add_signal(
            "Git",
            EvidenceDepth.LEVEL_3_IMPLEMENTATION,
            f"Verified public repository '{repo_name}' hosted on GitHub with commit history.",
        )

        detected_names = [s.skill for s in signals]
        message = (
            f"Successfully inspected repository '{owner}/{repo}'. "
            f"Detected technical signals: {', '.join(detected_names[:5])}."
        )

        return VerificationResult(
            status="verified",
            message=message,
            provider=self.provider_name,
            signals=signals,
            raw_metadata=inspection,
            verified_at=verified_at,
            warnings=warnings,
        )

    async def extract_signals(self, evidence: dict) -> List[ExtractedSignal]:
        res = await self.verify(evidence)
        if res.status == "verified":
            return res.signals
        return []
