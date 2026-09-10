from typing import Dict, List, Optional, Tuple, Any
import re
import json
from datetime import datetime, timezone
import httpx

from .base import EvidenceProvider, VerificationResult, ExtractedSignal, EvidenceDepth, VerificationStatus
from .url_utils import validate_platform_url, GITHUB_HOSTS
from ..skill_taxonomy import normalize_skill, normalize_skill_slug

# GitHub is supporting evidence (MEDIUM), not a definitive skill test.
# Performance-based sources (LeetCode/Codeforces/Kaggle 0.85) and verified
# coursework (0.80) outrank it; resume/LinkedIn (0.50/0.40) rank below.
GITHUB_RELIABILITY = 0.70

# Cap on extra raw manifest fetches per repository inspection (rate-limit safety).
MAX_EXTRA_MANIFEST_FETCHES = 4

# Extension -> canonical skill for implementation-file counting.
# Only skills present in the canonical taxonomy are listed (no invented skills).
EXTENSION_SKILL_MAP: Dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".h": "C++",
    ".c": "C",
    ".cs": "C#",
    ".swift": "Swift",
    ".dart": "Flutter",
    ".sql": "SQL",
    ".tf": "Terraform",
}

# Canonical skill -> GitHub language stats keys that count as bytes evidence.
LANGUAGE_SKILL_KEYS: Dict[str, tuple] = {
    "Python": ("Python",),
    "JavaScript": ("JavaScript",),
    "TypeScript": ("TypeScript",),
    "Java": ("Java",),
    "Kotlin": ("Kotlin",),
    "Go": ("Go",),
    "Rust": ("Rust",),
    "C++": ("C++",),
    "C": ("C",),
    "C#": ("C#",),
    "Swift": ("Swift",),
    "Flutter": ("Dart",),
    "SQL": ("SQL", "PLpgSQL", "TSQL", "PLSQL"),
    "Terraform": ("HCL",),
}

# Canonical skill -> build/dependency manifest basenames proving project setup.
SKILL_MANIFESTS: Dict[str, tuple] = {
    "Python": ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock"),
    "JavaScript": ("package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"),
    "TypeScript": ("package.json", "tsconfig.json"),
    "Java": ("pom.xml", "build.gradle", "build.gradle.kts"),
    "Kotlin": ("build.gradle", "build.gradle.kts"),
    "Go": ("go.mod", "go.sum"),
    "Rust": ("Cargo.toml", "Cargo.lock"),
    "C++": ("CMakeLists.txt", "Makefile"),
    "C": ("CMakeLists.txt", "Makefile"),
    "C#": (".csproj", ".sln"),
    "Swift": ("Package.swift",),
    "Flutter": ("pubspec.yaml",),
    "Terraform": (".terraform.lock.hcl",),
}

# Ecosystem manifests fetched as raw text (priority order) with their parser.
# Each parser returns lowercase dependency names using only stdlib parsing.
ECOSYSTEM_MANIFESTS: tuple = (
    ("pyproject.toml", "pyproject"),
    ("setup.py", "setuppy"),
    ("Pipfile", "pipfile"),
    ("go.mod", "gomod"),
    ("Cargo.toml", "cargo"),
    ("Gemfile", "gemfile"),
    ("composer.json", "composer"),
    ("pubspec.yaml", "pubspec"),
    ("build.sbt", "sbt"),
    ("Package.swift", "swiftpm"),
)

# Web framework dependency -> canonical REST APIs skill (same precedent as
# the existing fastapi/flask/django -> REST APIs mapping).
REST_FRAMEWORK_DEPS = frozenset({
    "gin", "echo", "fiber", "mux", "gorilla/mux", "chi",
    "actix-web", "actix", "rocket", "axum", "warp",
    "rails", "laravel", "symfony",
    "nest", "nestjs", "fastify", "koa", "hapi",
})

# Extra ORM/migration libraries -> canonical DBMS skill.
EXTRA_ORM_LIBS = frozenset({
    "gorm", "diesel", "sqlx", "activerecord", "eloquent",
    "entityframework", "efcore",
})

# Extra precise test library names (exact/prefixed matching only, same as
# the existing known_test_libs mechanism — no substring false positives).
EXTRA_TEST_LIBS = frozenset({
    "testify", "junit", "testng", "mockito", "assertj",
    "xunit", "nunit", "mstest", "gtest", "catch2", "phpunit", "rspec",
})

# Styling dependencies -> canonical CSS skill.
CSS_DEPS = frozenset({"tailwind", "tailwindcss", "sass", "scss", "less"})

# Filenames/paths marking Kubernetes manifests or non-GitHub CI configs.
K8S_MARKERS = (
    "deployment.yaml", "deployment.yml", "service.yaml", "service.yml",
    "ingress.yaml", "ingress.yml", "kustomization.yaml", "kustomization.yml",
    "chart.yaml", "chart.yml", "helmfile.yaml", "helmfile.yml",
)
K8S_DIR_MARKERS = ("k8s/", "kubernetes/", "helm/", "charts/")
CI_CONFIG_MARKERS = (
    "jenkinsfile", ".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml",
    "circle.yml", ".circleci/config.yml", "buildspec.yml",
)


def _clean_dep_name(raw: str) -> str:
    """Normalize a dependency token: lowercase, strip version specs/extras."""
    token = str(raw or "").strip().lower()
    token = re.split(r"[<>=!~\s;,\[\]]+", token)[0].strip("\"' ")
    return token


def parse_manifest_deps(parser: str, text: str) -> List[str]:
    """Extract lowercase dependency names from a manifest using stdlib parsing."""
    deps: List[str] = []
    try:
        if parser == "pyproject":
            for block in re.findall(r"dependencies\s*=\s*\[(.*?)\]", text, re.S | re.I):
                for tok in re.findall(r'"([^"]+)"|\'([^\']+)\'', block):
                    name = _clean_dep_name(tok[0] or tok[1])
                    if name:
                        deps.append(name)
        elif parser == "setuppy":
            for block in re.findall(r"install_requires\s*=\s*\[(.*?)\]", text, re.S | re.I):
                for tok in re.findall(r'"([^"]+)"|\'([^\']+)\'', block):
                    name = _clean_dep_name(tok[0] or tok[1])
                    if name:
                        deps.append(name)
        elif parser == "pipfile":
            in_packages = False
            for line in text.splitlines():
                s = line.strip().lower()
                if s.startswith("["):
                    in_packages = s in ("[packages]", "[dev-packages]")
                    continue
                if in_packages and "=" in s:
                    name = _clean_dep_name(s.split("=")[0])
                    if name and not name.startswith("#"):
                        deps.append(name)
        elif parser == "gomod":
            for line in re.findall(r"^\s*(?:require\s+)?([\w.\-/]+)\s+v\d+\.\d+\.\d+",
                                   text, re.M):
                seg = line.rsplit("/", 1)[-1].lower()
                if seg and seg not in ("go",):
                    deps.append(seg)
        elif parser == "cargo":
            in_deps = False
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("["):
                    in_deps = s.lower() in ("[dependencies]", "[dev-dependencies]")
                    continue
                if in_deps and "=" in s:
                    name = s.split("=")[0].strip().strip("\"'").lower().replace("_", "-")
                    if name:
                        deps.append(name)
        elif parser == "gemfile":
            for m in re.findall(r"gem\s+['\"]([^'\"]+)['\"]", text, re.I):
                name = _clean_dep_name(m)
                if name:
                    deps.append(name)
        elif parser == "composer":
            data = json.loads(text)
            for section in ("require", "require-dev"):
                reqs = data.get(section) or {}
                if isinstance(reqs, dict):
                    for full in reqs.keys():
                        pkg = str(full).split("/")[-1].lower()
                        if pkg and pkg != "php":
                            deps.append(pkg)
        elif parser == "pubspec":
            in_deps = False
            for line in text.splitlines():
                if re.match(r"^\S.*:\s*$", line):
                    in_deps = line.strip().lower().rstrip(":") in ("dependencies", "dev_dependencies")
                    continue
                if in_deps:
                    m = re.match(r"^\s{2}([A-Za-z0-9_]+)\s*:", line)
                    if m:
                        deps.append(m.group(1).lower())
                    elif line and not line.startswith(" ") and not line.startswith("\t"):
                        in_deps = False
        elif parser == "sbt":
            for m in re.findall(r'%\s*"([^"]+)"\s*%', text):
                artifact = m.lower().split("_")[0]
                if artifact:
                    deps.append(artifact)
        elif parser == "swiftpm":
            for m in re.findall(r'\.package\([^)]*url:\s*"[^"]*/([^"/]+?)(?:\.git)?"',
                                text, re.I):
                name = m.lower()
                if name:
                    deps.append(name)
    except Exception:
        pass
    # De-duplicate preserving order
    seen = set()
    out = []
    for d in deps:
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


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

                # 6. Fetch recursive file tree (capped) to confirm real
                # implementation files in EVERY ecosystem (src/**/*.py,
                # frontend/**/*.tsx, backend/**/*.go, ...) and to locate
                # build manifests outside the repo root (multi-module).
                # Best-effort: any failure keeps the languages/root-only path.
                tree_scanned = False
                java_file_count = 0
                java_test_file_count = 0
                tree_build_paths: List[str] = []
                tree_top_files: List[str] = []
                ext_file_counts: Dict[str, int] = {}
                tree_manifest_basenames: set = set()
                tree_csproj_paths: List[str] = []
                has_k8s_manifests = False
                k8s_manifest_count = 0
                has_ci_config = False
                try:
                    tree_res = await client.get(
                        f"{repo_url}/git/trees/{default_branch}?recursive=1", headers=headers
                    )
                    if tree_res.status_code == 200 and isinstance(tree_res.json().get("tree"), list):
                        tree_scanned = True
                        entries = tree_res.json()["tree"][:3000]
                        for entry in entries:
                            path = str(entry.get("path") or "")
                            if not path:
                                continue
                            low = path.lower()
                            base = low.rsplit("/", 1)[-1]
                            if base in ("pom.xml", "build.gradle", "build.gradle.kts"):
                                tree_build_paths.append(path)
                            if base.endswith(".csproj"):
                                tree_csproj_paths.append(path)
                            tree_manifest_basenames.add(base)
                            # Per-extension implementation file counts
                            dot = base.rfind(".")
                            if dot > 0:
                                ext = base[dot:]
                                if ext in EXTENSION_SKILL_MAP:
                                    ext_file_counts[ext] = ext_file_counts.get(ext, 0) + 1
                            if low.endswith(".java"):
                                java_file_count += 1
                                if "test" in low:
                                    java_test_file_count += 1
                            # Kubernetes / extra-CI markers
                            if base in K8S_MARKERS or low.startswith(K8S_DIR_MARKERS):
                                has_k8s_manifests = True
                                k8s_manifest_count += 1
                            if base in CI_CONFIG_MARKERS:
                                has_ci_config = True
                            # Feed full paths AND basenames into the shared
                            # file checks below (docker/CI layout,
                            # frontend/backend structure incl. subdirectories).
                            if len(tree_top_files) < 800:
                                tree_top_files.append(low)
                                if base != low:
                                    tree_top_files.append(base)
                except Exception:
                    pass

                # 7. Fetch Java build manifest contents (root first, then first
                # tree hit) to infer frameworks (Spring/Hibernate) and Java
                # test frameworks (JUnit/TestNG/Mockito).
                build_system: Optional[str] = None
                java_frameworks: List[str] = []
                java_build_deps: List[str] = []
                build_manifest_found = (
                    "pom.xml" in root_files
                    or "build.gradle" in root_files
                    or "build.gradle.kts" in root_files
                    or len(tree_build_paths) > 0
                )
                manifest_candidates: List[str] = []
                for candidate in ("pom.xml", "build.gradle", "build.gradle.kts"):
                    if candidate in root_files:
                        manifest_candidates.append(candidate)
                manifest_candidates.extend([p for p in tree_build_paths if p not in manifest_candidates][:2])
                manifest_text = ""
                for candidate in manifest_candidates[:2]:
                    try:
                        raw_res = await client.get(
                            f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{candidate}",
                            headers={"User-Agent": "INAURA-Evidence-Intelligence/1.0"},
                            timeout=4.0,
                        )
                        if raw_res.status_code == 200 and raw_res.text.strip():
                            manifest_text += "\n" + raw_res.text.lower()
                            if candidate == "pom.xml":
                                build_system = build_system or "maven"
                            else:
                                build_system = build_system or "gradle"
                    except Exception:
                        continue
                if manifest_text:
                    if "spring-boot" in manifest_text or "springframework" in manifest_text:
                        java_frameworks.append("spring_boot")
                    if "hibernate" in manifest_text:
                        java_frameworks.append("hibernate")
                    for marker in ("junit", "testng", "mockito", "assertj", "surefire", "failsafe"):
                        if marker in manifest_text:
                            java_build_deps.append(marker)

                # 8. Fetch ecosystem manifests (pyproject.toml, go.mod,
                # Cargo.toml, ...) as raw text, root first then tree hits.
                # Bounded by MAX_EXTRA_MANIFEST_FETCHES for rate-limit safety.
                root_lower = {str(f).lower() for f in root_files}
                eco_manifest_deps: List[str] = []
                eco_python_deps: List[str] = []
                eco_manifests_found: List[str] = []
                extra_fetches = 0

                async def _fetch_raw(path: str) -> str:
                    try:
                        r = await client.get(
                            f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{path}",
                            headers={"User-Agent": "INAURA-Evidence-Intelligence/1.0"},
                            timeout=4.0,
                        )
                        if r.status_code == 200 and r.text.strip():
                            return r.text
                    except Exception:
                        pass
                    return ""

                for manifest_name, parser in ECOSYSTEM_MANIFESTS:
                    if extra_fetches >= MAX_EXTRA_MANIFEST_FETCHES:
                        break
                    target: Optional[str] = None
                    if manifest_name in root_lower:
                        # Recover original-case root path
                        for f in root_files:
                            if str(f).lower() == manifest_name:
                                target = str(f)
                                break
                    if target is None and manifest_name in tree_manifest_basenames:
                        target = manifest_name
                    if target is None:
                        continue
                    text = await _fetch_raw(target)
                    if not text:
                        continue
                    extra_fetches += 1
                    eco_manifests_found.append(manifest_name)
                    parsed = parse_manifest_deps(parser, text)
                    eco_manifest_deps.extend(parsed)
                    if parser in ("pyproject", "setuppy", "pipfile"):
                        eco_python_deps.extend(parsed)

                # First .csproj found in the tree (C# package references)
                if extra_fetches < MAX_EXTRA_MANIFEST_FETCHES and tree_csproj_paths:
                    text = await _fetch_raw(tree_csproj_paths[0])
                    if text:
                        extra_fetches += 1
                        eco_manifests_found.append("csproj")
                        for m in re.findall(
                            r'<PackageReference\s+Include\s*=\s*"([^"]+)"', text, re.I
                        ):
                            name = _clean_dep_name(m)
                            if name:
                                eco_manifest_deps.append(name)

                inspection = {
                    "name": repo_data.get("name"),
                    "full_name": repo_data.get("full_name"),
                    "description": repo_data.get("description") or "",
                    "topics": repo_data.get("topics") or [],
                    "languages": languages,
                    "root_files": root_files,
                    "top_files": tree_top_files,
                    "package_json_deps": package_json_deps,
                    "python_deps": py_deps,
                    "eco_manifest_deps": eco_manifest_deps,
                    "eco_python_deps": eco_python_deps,
                    "eco_manifests_found": eco_manifests_found,
                    "ext_file_counts": ext_file_counts,
                    "has_workflows": has_workflows,
                    "has_ci_config": has_ci_config,
                    "has_k8s_manifests": has_k8s_manifests,
                    "k8s_manifest_count": k8s_manifest_count,
                    "is_fork": repo_data.get("fork", False),
                    "size": repo_data.get("size", 0),
                    "pushed_at": repo_data.get("pushed_at"),
                    "updated_at": repo_data.get("updated_at"),
                    "tree_scanned": tree_scanned,
                    "java_file_count": java_file_count,
                    "java_test_file_count": java_test_file_count,
                    "has_java_build_manifest": build_manifest_found,
                    "build_system": build_system,
                    "java_frameworks": java_frameworks,
                    "java_build_deps": java_build_deps,
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
        all_files_lower = {str(f).lower() for f in all_files}
        languages = inspection.get("languages") or {}
        generic_deps = [d.lower() for d in (inspection.get("dependencies") or [])]
        pkg_deps = [d.lower() for d in (inspection.get("package_json_deps") or [])] + generic_deps
        py_deps = (
            [d.lower() for d in (inspection.get("python_deps") or [])]
            + [d.lower() for d in (inspection.get("eco_python_deps") or [])]
            + generic_deps
        )
        eco_deps = [d.lower() for d in (inspection.get("eco_manifest_deps") or [])]
        all_deps = set(pkg_deps + py_deps + eco_deps + generic_deps)
        ext_file_counts = {
            str(k).lower(): int(v) for k, v in (inspection.get("ext_file_counts") or {}).items()
        }
        if not ext_file_counts and all_files_lower:
            # Backward compatibility: fixtures listing sources via top_files
            for f in all_files_lower:
                dot = f.rfind(".")
                if dot > 0 and f[dot:] in EXTENSION_SKILL_MAP:
                    ext_file_counts[f[dot:]] = ext_file_counts.get(f[dot:], 0) + 1
        tree_scanned = bool(inspection.get("tree_scanned"))
        has_workflows = bool(inspection.get("has_workflows"))
        has_ci_config = bool(inspection.get("has_ci_config"))
        has_k8s_manifests = bool(inspection.get("has_k8s_manifests"))
        k8s_manifest_count = int(inspection.get("k8s_manifest_count") or 0)
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
        } | EXTRA_TEST_LIBS
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

        # 5. Java / JVM Detection (tiered by implementation evidence).
        # A README/description mention alone NEVER awards Java — there must be
        # supporting implementation evidence (language bytes, build manifest,
        # or actual .java source files).
        java_bytes = languages.get("Java", 0) if isinstance(languages, dict) else 0
        if not isinstance(java_bytes, (int, float)):
            java_bytes = 0
        java_file_count = int(inspection.get("java_file_count") or 0)
        if java_file_count == 0 and all_files:
            # Backward compatibility with fixtures that list sources via top_files
            java_file_count = sum(1 for f in all_files if str(f).lower().endswith(".java"))
        java_test_files = int(inspection.get("java_test_file_count") or 0)
        has_build_manifest = bool(inspection.get("has_java_build_manifest")) or any(
            f in root_files for f in ("pom.xml", "build.gradle", "build.gradle.kts")
        )
        java_frameworks = [str(x).lower() for x in (inspection.get("java_frameworks") or [])]
        java_build_deps = [str(x).lower() for x in (inspection.get("java_build_deps") or [])]
        has_spring = any("spring" in f for f in java_frameworks) or any("spring" in d for d in all_deps)
        has_java_tests = (
            java_test_files > 0
            or any(m in java_build_deps for m in ("junit", "testng", "mockito", "assertj", "surefire"))
        )
        tree_scanned = bool(inspection.get("tree_scanned"))
        has_java_footprint = "Java" in languages or has_build_manifest or java_file_count > 0

        if has_java_footprint:
            meaningful_impl = (
                java_file_count >= 3
                or (java_file_count >= 1 and has_build_manifest)
                or (java_bytes >= 5000 and has_build_manifest)
                or (java_bytes >= 20000)
                # Tree could not be scanned (API failure): preserve prior
                # behavior and trust the language/build-manifest footprint.
                or (not tree_scanned and java_file_count == 0 and ("Java" in languages or has_build_manifest))
            )
            substantial_impl = java_file_count >= 10 and (
                has_build_manifest or has_spring or has_java_tests or has_workflows
            )
            if substantial_impl:
                java_depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL
                java_detail = (
                    f"{java_file_count} Java source files with "
                    f"{'build manifest (' + str(inspection.get('build_system') or 'maven/gradle') + ') ' if has_build_manifest else ''}"
                    f"{'Spring framework ' if has_spring else ''}"
                    f"{'and automated tests ' if (has_java_tests or has_tests) else ''}"
                    f"({int(java_bytes)} bytes of Java)"
                )
            elif meaningful_impl:
                java_depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION
                java_detail = (
                    f"verified Java implementation ({java_file_count} Java source files, "
                    f"{int(java_bytes)} bytes of Java"
                    f"{', build manifest present' if has_build_manifest else ''})"
                )
            else:
                # Weak footprint only (tiny language bytes, manifest without any
                # sources, or a lone stray file): config-level signal at most.
                java_depth = EvidenceDepth.LEVEL_2_CONFIG
                java_detail = (
                    f"limited Java footprint ({int(java_bytes)} bytes of Java, "
                    f"{java_file_count} Java source files"
                    f"{', build manifest present' if has_build_manifest else ', no build manifest'})"
                )
            _add_signal(
                "Java",
                java_depth,
                f"Repository '{repo_name}' {java_detail}.",
                {
                    "java_file_count": java_file_count,
                    "java_bytes": int(java_bytes),
                    "has_build_manifest": has_build_manifest,
                    "build_system": inspection.get("build_system"),
                },
            )
            if has_spring:
                _add_signal(
                    "Spring Boot",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' declares Spring framework dependencies in its Java build manifest.",
                    {"framework": "spring_boot"},
                )

        # 5b. General ecosystem language detection (every other canonical
        # language). Python/JavaScript/TypeScript/Java keep their bespoke
        # blocks above; everything here is tiered the same way:
        # substantial implementation (L4) > meaningful sources (L3) >
        # weak footprint, e.g. manifest without sources (L2).
        # README/description mentions alone NEVER award a language.
        def _has_manifest(names: tuple) -> bool:
            for n in names:
                nl = n.lower()
                if nl in root_files or nl in all_files_lower:
                    return True
                if nl.startswith(".") and any(f.endswith(nl) for f in all_files_lower):
                    return True
            return False

        def _lang_bytes(keys: tuple) -> int:
            total = 0
            if isinstance(languages, dict):
                for k, v in languages.items():
                    if str(k) in keys and isinstance(v, (int, float)):
                        total += v
            return int(total)

        def _skill_file_count(skill: str) -> int:
            return sum(c for ext, c in ext_file_counts.items() if EXTENSION_SKILL_MAP.get(ext) == skill)

        for _skill in ("Go", "Rust", "C++", "C", "C#", "Kotlin", "Swift", "Flutter", "SQL", "Terraform"):
            _exts = [e for e, s in EXTENSION_SKILL_MAP.items() if s == _skill]
            _files = _skill_file_count(_skill)
            _bytes = _lang_bytes(LANGUAGE_SKILL_KEYS.get(_skill, ()))
            _manifest = _has_manifest(SKILL_MANIFESTS.get(_skill, ()))
            _footprint = _files > 0 or _bytes > 0 or _manifest
            if not _footprint:
                continue
            if _skill == "C" and _files == 0 and _bytes == 0:
                # CMakeLists/Makefile are shared with C++: a manifest alone
                # must not invent C evidence without C sources or bytes.
                continue
            _substantial = _files >= 10 and (_manifest or has_tests or has_workflows)
            _meaningful = (
                _files >= 3
                or (_files >= 1 and _manifest)
                or (_bytes >= 5000 and _manifest)
                or (_bytes >= 20000)
                or (not tree_scanned and (_bytes > 0 or _manifest))
            )
            if _substantial:
                _depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL
                _detail = f"substantial {_skill} implementation ({_files} source files, {_bytes} bytes)"
            elif _meaningful:
                _depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION
                _detail = (
                    f"verified {_skill} implementation ({_files} source files, {_bytes} bytes"
                    f"{', build manifest present' if _manifest else ''})"
                )
            else:
                _depth = EvidenceDepth.LEVEL_2_CONFIG
                _detail = (
                    f"limited {_skill} footprint ({_files} source files, {_bytes} bytes"
                    f"{', build manifest present' if _manifest else ', no build manifest'})"
                )
            _add_signal(
                _skill,
                _depth,
                f"Repository '{repo_name}' {_detail}.",
                {"source_file_count": _files, "language_bytes": _bytes, "has_build_manifest": _manifest},
            )

        # 5c. Cross-ecosystem web frameworks -> canonical REST APIs skill.
        rest_hits = sorted({d for d in all_deps if d in REST_FRAMEWORK_DEPS})
        if rest_hits:
            _add_signal(
                "REST APIs",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' implements REST API services ({', '.join(rest_hits[:5])}).",
                {"frameworks": rest_hits[:5]},
            )

        # 5d. Styling dependencies -> canonical CSS skill.
        css_hits = sorted({d for d in all_deps if d in CSS_DEPS})
        if css_hits:
            _add_signal(
                "CSS",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' declares styling dependencies ({', '.join(css_hits[:5])}).",
                {"dependencies": css_hits[:5]},
            )

        # 5e. Kubernetes manifests -> canonical Kubernetes skill (config-level).
        if has_k8s_manifests:
            _add_signal(
                "Kubernetes",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' contains Kubernetes deployment manifests ({k8s_manifest_count} file(s)).",
                {"manifest_count": k8s_manifest_count},
            )

        # 5f. Non-GitHub CI configs (Jenkins/GitLab/Travis/Circle/Azure) -> CI/CD.
        if has_ci_config and not has_workflows:
            _add_signal(
                "CI/CD",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' configures continuous integration pipelines.",
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
        if any(d in all_deps for d in ("mysql", "mysql2", "pymysql", "mysqldb", "mysql-connector")):
            _add_signal(
                "MySQL",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' contains explicit MySQL database adapter dependencies.",
            )
        if any(d in all_deps for d in ("redis", "ioredis")):
            _add_signal(
                "Redis",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' includes Redis client dependencies.",
            )

        # Database Design (ORMs and migration engines) -> canonical DBMS skill
        orm_libs = {"prisma", "typeorm", "sequelize", "sqlalchemy", "alembic", "mongoose", "knex", "hibernate", "mikro-orm"} | EXTRA_ORM_LIBS
        if any(any(ol in d for ol in orm_libs) for d in all_deps):
            _add_signal(
                "DBMS",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' implements structured database ORM/schema migration models.",
            )

        # 7. Authentication & Security -> canonical Application Security skill
        auth_libs = {"jsonwebtoken", "jwt", "bcrypt", "passport", "auth0", "next-auth", "passlib", "pyjwt", "oauthlib"}
        if any(any(al in d for al in auth_libs) for d in all_deps):
            _add_signal(
                "Application Security",
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
