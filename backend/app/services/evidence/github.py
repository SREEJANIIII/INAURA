from typing import Dict, List, Optional, Tuple, Any, Set
import re
import json
import os
import logging
import asyncio
from datetime import datetime, timezone
import httpx

from .base import EvidenceProvider, VerificationResult, ExtractedSignal, EvidenceDepth, VerificationStatus
from .url_utils import validate_platform_url, GITHUB_HOSTS
from ..evidence_weights import reliability as source_reliability
from ..skill_taxonomy import (
    normalize_skill,
    normalize_skill_slug,
    extract_known_skills_from_text,
    get_canonical_skill,
)
from .github_validation import validate_aggregated_signal as _validate_aggregated
from .github_validation import validate_repo_signal as _validate_repo_signal

logger = logging.getLogger(__name__)

# GitHub is supporting evidence (MEDIUM), not a definitive skill test.
# Repository contents prove technology exposure, not personal mastery, so the
# INAURA assessment (0.95), performance platforms (0.85) and verified
# coursework (0.80) outrank it; resume/LinkedIn (0.50/0.40) rank below.
# Value is owned by services.evidence_weights (single source of truth).
GITHUB_RELIABILITY = source_reliability("github")

# Cap on extra raw manifest fetches per repository inspection (rate-limit safety).
MAX_EXTRA_MANIFEST_FETCHES = 4

# Controlled profile inspection concurrency limit (conservative 3-5 range)
DEFAULT_PROFILE_CONCURRENCY = 4

# Maximum profile pages safety ceiling (50 pages * 100 per page = 5,000 repos)
MAX_PROFILE_PAGES = 50

# ---------------------------------------------------------------------------
# Bounded repository *content* inspection limits.
# Repository discovery (cheap, always runs for every repository) is separate
# from content inspection (expensive raw file reads). Content reads are capped
# per repository and, for profile inspections, share a profile-wide budget so
# analysing every repository of a large profile stays practical.
# ---------------------------------------------------------------------------
MAX_README_CHARS = 20000
MAX_SOURCE_FILES_PER_REPO = 6
MAX_SOURCE_FILE_BYTES = 200_000       # skip huge/generated source blobs
MAX_SOURCE_TEXT_CHARS = 40000         # per-file text kept for import scanning
MAX_CONFIG_FILES_PER_REPO = 3
MAX_CONFIG_TEXT_CHARS = 12000
# README + sampled sources + sampled configs per repository
MAX_CONTENT_FETCHES_PER_REPO = 1 + MAX_SOURCE_FILES_PER_REPO + MAX_CONFIG_FILES_PER_REPO
# Profile-wide ceiling on content reads (repository discovery is never capped).
DEFAULT_PROFILE_CONTENT_BUDGET = 600

# Vendored / generated / dependency directories that carry no authorship
# evidence and must never be downloaded.
SKIP_PATH_MARKERS = (
    "node_modules/", "bower_components/", "vendor/", "third_party/", "thirdparty/",
    "dist/", "build/", "out/", "target/", "obj/", ".next/", ".nuxt/", "coverage/",
    "__pycache__/", "site-packages/", "venv/", ".venv/", "env/", "migrations/",
    "generated/", "gen/", ".git/", "docs/_build/", "public/vendor/",
)
SKIP_FILE_MARKERS = (".min.js", ".min.css", ".bundle.js", ".lock", ".map", "-lock.json")

# Paths that usually hold the repository's real implementation.
PRIORITY_PATH_MARKERS = (
    "src/", "app/", "lib/", "api/", "server/", "backend/", "frontend/", "core/",
    "services/", "internal/", "pkg/", "cmd/", "main/",
)
PRIORITY_FILE_STEMS = (
    "main", "app", "index", "server", "api", "routes", "models", "views",
    "handler", "handlers", "service", "services", "settings", "config", "urls",
)

# Configuration / infrastructure files whose *contents* carry technical evidence.
CONFIG_CONTENT_BASENAMES = (
    "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    "dockerfile", "procfile", "nginx.conf", "vercel.json", "netlify.toml",
    "render.yaml", "railway.json", "serverless.yml", "serverless.yaml",
    "next.config.js", "next.config.mjs", "next.config.ts", "vite.config.js",
    "vite.config.ts", "webpack.config.js", "tailwind.config.js", "tailwind.config.ts",
    "application.properties", "application.yml", "application.yaml",
    ".env.example", ".env.sample", ".env.template", "makefile",
)
CONFIG_CONTENT_SUFFIXES = (".tf", ".tfvars")
CONFIG_CONTENT_DIR_MARKERS = (
    ".github/workflows/", "k8s/", "kubernetes/", "helm/", "charts/", "terraform/",
)

# Source extensions eligible for import/usage scanning (superset of the
# extension->skill map: these are read for the imports they contain).
SOURCE_SCAN_EXTENSIONS = (
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java", ".kt", ".kts",
    ".go", ".rs", ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".cs", ".swift",
    ".dart", ".rb", ".php", ".scala", ".m", ".mm",
)

# Language-agnostic import/usage patterns. Each pattern yields a raw module
# token which is normalized through the canonical taxonomy — no per-technology
# special cases live here.
IMPORT_PATTERNS = (
    re.compile(r"^\s*(?:from|import)\s+([A-Za-z0-9_.]+)", re.M),          # Python / Java / Kotlin / Swift
    re.compile(r"""\bfrom\s+['"]([^'"\n]+)['"]""", re.M),                  # ES modules
    re.compile(r"""\brequire\(\s*['"]([^'"\n]+)['"]\s*\)""", re.M),        # CommonJS
    re.compile(r"""\bimport\(\s*['"]([^'"\n]+)['"]\s*\)""", re.M),         # dynamic import
    re.compile(r"^\s*use\s+([A-Za-z0-9_:]+)", re.M),                       # Rust
    re.compile(r"^\s*using\s+([A-Za-z0-9_.]+)\s*;", re.M),                 # C#
    re.compile(r"""^\s*#include\s*[<"]([A-Za-z0-9_./]+)[>"]""", re.M),      # C / C++
    re.compile(r"""^\s*(?:_\s+)?"([A-Za-z0-9_./\-]+)"\s*$""", re.M),        # Go import block entries
    re.compile(r"""^\s*(?:require|gem)\s+['"]([^'"\n]+)['"]""", re.M),      # Ruby
)

# Minimum token length considered for canonical mapping. Guards against
# two-letter taxonomy aliases ('ml', 'np', 'ts', 'js') matching noise.
MIN_TOKEN_LEN = 3

# Activity thresholds for classification
REPO_ACTIVE_DAYS = 365 * 2
REPO_STALE_YEARS = 3.0

# Reliable patterns identifying tutorial, demo, or template repositories
TUTORIAL_DEMO_PATTERNS = re.compile(
    r"\b(tutorial|tutorials|course|coursework|assignment|homework|demo|demos|"
    r"template|templates|boilerplate|sample|samples|playground|sandbox|study|"
    r"100[-_]?days|exercises?|practice|starter[-_]?kit|learning)\b",
    re.IGNORECASE,
)

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


def _flatten_text(text: str) -> str:
    """Lowercase text with separator punctuation collapsed to single spaces."""
    return " " + re.sub(r"[\s\.\-_/]+", " ", str(text or "").lower()) + " "


def skill_mention_counts(text: str) -> Dict[str, int]:
    """
    Count canonical-skill mentions in free text using the shared taxonomy.

    Reuses `extract_known_skills_from_text` for detection (so GitHub never
    invents a skill identity) and then counts alias occurrences so callers can
    distinguish a single passing mention from repeated, structural usage.
    Aliases shorter than MIN_TOKEN_LEN are ignored to avoid noise ('ml', 'np').
    """
    if not text or not str(text).strip():
        return {}

    flat = _flatten_text(text)
    counts: Dict[str, int] = {}
    for definition in extract_known_skills_from_text(str(text)):
        phrases = {definition.display_name, definition.canonical_name, definition.id}
        phrases.update(definition.aliases)
        total = 0
        for phrase in phrases:
            cleaned = re.sub(r"[\s\.\-_/]+", " ", str(phrase).strip().lower()).strip()
            if len(cleaned) < MIN_TOKEN_LEN:
                continue
            total += len(re.findall(r"(?<![\w+#])" + re.escape(cleaned) + r"(?![\w+#])", flat))
        if total > 0:
            counts[definition.display_name] = counts.get(definition.display_name, 0) + total
    return counts


def _import_token_candidates(raw_token: str) -> List[str]:
    """
    Expand one raw import/usage token into canonical-lookup candidates.
    'sklearn.linear_model' -> ['sklearn.linear_model', 'sklearn']
    '@testing-library/react' -> ['@testing-library/react', 'testing-library', 'react']
    'org.springframework.boot.SpringApplication' -> [..., 'springframework', 'boot', ...]
    """
    token = str(raw_token or "").strip().strip("\"';")
    if not token:
        return []
    token = token.lstrip("./")
    candidates: List[str] = [token]
    segments = re.split(r"[./:@\\]+", token)
    for seg in segments:
        if seg and seg not in candidates:
            candidates.append(seg)
    return [c for c in candidates if len(c) >= MIN_TOKEN_LEN]


def extract_import_tokens(text: str) -> Dict[str, int]:
    """
    Extract raw import/usage module tokens and their occurrence counts from a
    source file, using language-agnostic patterns. Mapping tokens to skills is
    left to the canonical taxonomy so no technology is special-cased here.
    """
    tokens: Dict[str, int] = {}
    if not text:
        return tokens
    for pattern in IMPORT_PATTERNS:
        for match in pattern.findall(text[:MAX_SOURCE_TEXT_CHARS]):
            raw = match if isinstance(match, str) else (match[0] if match else "")
            raw = str(raw).strip()
            if not raw or len(raw) > 200:
                continue
            key = raw.lower()
            tokens[key] = tokens.get(key, 0) + 1
    return tokens


def import_skill_counts(import_tokens: Dict[str, int]) -> Dict[str, int]:
    """Map raw import tokens to canonical skills with aggregated usage counts."""
    counts: Dict[str, int] = {}
    for token, occurrences in (import_tokens or {}).items():
        for candidate in _import_token_candidates(token):
            canonical = normalize_skill(candidate)
            if canonical:
                counts[canonical] = counts.get(canonical, 0) + int(occurrences or 1)
                break
    return counts


def dependency_skill_names(deps: Set[str]) -> Dict[str, str]:
    """
    Map declared dependency names to canonical skills through the taxonomy.
    Returns canonical skill -> the dependency token that produced it.
    """
    resolved: Dict[str, str] = {}
    for dep in sorted({str(d or "").strip().lower() for d in (deps or set()) if d}):
        for candidate in _import_token_candidates(dep):
            canonical = normalize_skill(candidate)
            if canonical and canonical not in resolved:
                resolved[canonical] = dep
                break
    return resolved


def _is_skippable_path(path_lower: str) -> bool:
    """True for vendored, generated, or non-authored files."""
    if any(marker in path_lower for marker in SKIP_PATH_MARKERS):
        return True
    if path_lower.startswith(SKIP_PATH_MARKERS):
        return True
    return any(marker in path_lower for marker in SKIP_FILE_MARKERS)


def _source_priority(path_lower: str, size: int) -> tuple:
    """
    Rank a candidate source file: implementation directories and entry-point
    filenames first, then larger files (more implementation to observe).
    """
    base = path_lower.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0]
    in_priority_dir = any(marker in path_lower for marker in PRIORITY_PATH_MARKERS)
    is_priority_stem = stem in PRIORITY_FILE_STEMS
    is_test = "test" in path_lower or "spec" in path_lower
    return (
        1 if in_priority_dir else 0,
        1 if is_priority_stem else 0,
        0 if is_test else 1,
        min(int(size or 0), MAX_SOURCE_FILE_BYTES),
    )


def select_source_files(candidates: List[Tuple[str, int]], limit: int = MAX_SOURCE_FILES_PER_REPO) -> List[str]:
    """
    Choose a bounded, diverse sample of real implementation files.
    Files are round-robined across extensions so a polyglot repository does not
    spend its whole budget on a single language.
    """
    by_ext: Dict[str, List[Tuple[str, int]]] = {}
    for path, size in candidates:
        low = path.lower()
        dot = low.rfind(".")
        ext = low[dot:] if dot > 0 else ""
        by_ext.setdefault(ext, []).append((path, size))

    for ext in by_ext:
        by_ext[ext].sort(key=lambda item: _source_priority(item[0].lower(), item[1]), reverse=True)

    # Extensions with the strongest single candidate go first.
    ordered_exts = sorted(
        by_ext.keys(),
        key=lambda e: _source_priority(by_ext[e][0][0].lower(), by_ext[e][0][1]),
        reverse=True,
    )

    selected: List[str] = []
    round_index = 0
    while len(selected) < limit:
        added = False
        for ext in ordered_exts:
            bucket = by_ext[ext]
            if round_index < len(bucket):
                selected.append(bucket[round_index][0])
                added = True
                if len(selected) >= limit:
                    break
        if not added:
            break
        round_index += 1
    return selected


def _is_config_content_path(path_lower: str) -> bool:
    """True for configuration/infrastructure files worth reading in full."""
    base = path_lower.rsplit("/", 1)[-1]
    if base in CONFIG_CONTENT_BASENAMES or base.startswith("dockerfile"):
        return True
    if base.endswith(CONFIG_CONTENT_SUFFIXES):
        return True
    if any(marker in path_lower for marker in CONFIG_CONTENT_DIR_MARKERS) and base.endswith(
        (".yml", ".yaml", ".tf", ".json")
    ):
        return True
    return False


def compact_inspection(inspection: dict, keep_excerpt: bool = True) -> Dict[str, Any]:
    """
    Strip bulky raw file text out of an inspection payload before it is
    persisted with the evidence record. Derived facts (counts, sampled paths,
    detected dependencies) are kept so provenance survives; the raw README /
    config bodies and the full file listing are not stored per repository.
    """
    if not isinstance(inspection, dict):
        return {}
    compact = {k: v for k, v in inspection.items() if k not in
               ("readme_text", "config_text", "top_files", "import_tokens")}
    readme_text = str(inspection.get("readme_text") or "")
    if keep_excerpt and readme_text:
        compact["readme_excerpt"] = readme_text[:400]
    compact["readme_present"] = bool(readme_text) or bool(inspection.get("readme_present"))
    top_files = inspection.get("top_files") or []
    if top_files:
        compact["top_files_count"] = len(top_files)
    import_tokens = inspection.get("import_tokens") or {}
    if import_tokens:
        compact["import_token_count"] = len(import_tokens)
        compact["import_skills"] = sorted(import_skill_counts(
            {str(k).lower(): int(v or 0) for k, v in import_tokens.items()}
        ).keys())
    return compact


class ContentBudget:
    """
    Shared ceiling on expensive repository *content* reads. Repository
    discovery and metadata inspection are never limited by this budget.
    """

    def __init__(self, total: int = DEFAULT_PROFILE_CONTENT_BUDGET):
        self.total = max(0, int(total))
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.used)

    def take(self, count: int = 1) -> bool:
        if self.remaining < count:
            return False
        self.used += count
        return True


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


def _get_github_headers() -> Dict[str, str]:
    headers = {
        "User-Agent": "INAURA-Evidence-Intelligence/1.0",
        "Accept": "application/vnd.github.v3+json",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def _check_rate_limit(res: httpx.Response) -> Tuple[bool, int, Optional[str]]:
    """
    Check if response indicates rate limiting.
    Returns: (is_limited, remaining, reset_time_iso)
    """
    remaining_header = res.headers.get("x-ratelimit-remaining")
    reset_header = res.headers.get("x-ratelimit-reset")
    remaining = int(remaining_header) if remaining_header and remaining_header.isdigit() else 100

    reset_time = None
    if reset_header and reset_header.isdigit():
        try:
            reset_dt = datetime.fromtimestamp(int(reset_header), tz=timezone.utc)
            reset_time = reset_dt.isoformat()
        except Exception:
            pass

    is_limited = res.status_code in (403, 429) or remaining <= 0
    return is_limited, remaining, reset_time


def _classify_repository(repo_data: dict, profile_owner: str, now: datetime) -> Dict[str, Any]:
    """
    Classify a repository across ownership, activity, structure, and evidence density.
    Returns a dict with primary classification string and detailed flags.
    """
    name = str(repo_data.get("name") or "")
    desc = str(repo_data.get("description") or "")
    is_fork = bool(repo_data.get("fork", False))
    is_archived = bool(repo_data.get("archived", False))
    is_disabled = bool(repo_data.get("disabled", False))
    is_template = bool(repo_data.get("is_template", False))
    size = int(repo_data.get("size") or 0)
    has_language = bool(repo_data.get("language"))

    # Ownership: belongs directly to profile user and is not an upstream fork
    owner_login = ""
    owner_obj = repo_data.get("owner")
    if isinstance(owner_obj, dict):
        owner_login = str(owner_obj.get("login") or "").lower()
    elif isinstance(owner_obj, str):
        owner_login = owner_obj.lower()
    is_owned = (not is_fork) and (not owner_login or owner_login == profile_owner.lower())

    # Activity / recency
    pushed_at = repo_data.get("pushed_at") or repo_data.get("updated_at")
    is_active = False
    is_stale = False
    if pushed_at:
        try:
            p_str = str(pushed_at).replace("Z", "+00:00")
            pushed_dt = datetime.fromisoformat(p_str)
            if pushed_dt.tzinfo is None:
                pushed_dt = pushed_dt.replace(tzinfo=timezone.utc)
            v_dt = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
            age_days = (v_dt - pushed_dt).days
            if age_days <= REPO_ACTIVE_DAYS:
                is_active = True
            elif age_days > 365 * REPO_STALE_YEARS:
                is_stale = True
        except Exception:
            pass
    else:
        is_stale = True

    # Low evidence: 0 size or disabled without code
    is_low_evidence = (size == 0 and not has_language) or is_disabled

    # Tutorial / demo / template detection
    name_low = name.lower()
    desc_low = desc.lower()
    is_tutorial_demo = (
        is_template
        or bool(TUTORIAL_DEMO_PATTERNS.search(name_low))
        or bool(TUTORIAL_DEMO_PATTERNS.search(desc_low))
    )

    # Primary classification string
    if is_fork:
        primary = "fork"
    elif is_archived:
        primary = "archived"
    elif is_low_evidence:
        primary = "low_evidence"
    elif is_tutorial_demo:
        primary = "tutorial_demo"
    elif is_active:
        primary = "owned_active"
    elif is_stale:
        primary = "owned_stale"
    else:
        primary = "owned"

    return {
        "classification": primary,
        "is_owned": is_owned,
        "is_fork": is_fork,
        "is_archived": is_archived,
        "is_active": is_active,
        "is_stale": is_stale,
        "is_low_evidence": is_low_evidence,
        "is_tutorial_demo": is_tutorial_demo,
    }


class GitHubProvider(EvidenceProvider):
    """
    Evidence Intelligence Provider for GitHub.

    Two distinct stages:
      1. Repository discovery — every accessible repository of a profile is
         enumerated through GitHub's pagination (no fixed cap, no
         'most recently updated only' shortcut).
      2. Repository content analysis — each non-empty repository is inspected
         for concrete technical evidence within bounded API/content budgets:
           - repository metadata, description, topics, language statistics
           - directory/file structure (recursive tree)
           - dependency/build manifests across ecosystems
           - README contents (documentation-level evidence)
           - a prioritized sample of real implementation files (imports/usages)
           - configuration/infrastructure files (Docker, CI, k8s, Terraform, env)
           - test structure and project architecture indicators

    Signals are graded by EvidenceDepth:
      URL only (0) < documentation mention (1) < config/dependency (2)
      < implementation (3) < substantial implementation (4)
    and are always normalized through the canonical skill taxonomy.
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

        # 3. If it's a profile URL, inspect all public repositories
        return await self._inspect_profile(owner, now, evidence=evidence)

    async def _inspect_repository_core(
        self,
        owner: str,
        repo: str,
        verified_at: datetime,
        client: httpx.AsyncClient,
        repo_data: Optional[dict] = None,
        budget: Optional[ContentBudget] = None,
    ) -> VerificationResult:
        headers = _get_github_headers()
        repo_url = f"https://api.github.com/repos/{owner}/{repo}"

        try:
            # 1. Fetch repo metadata if not provided
            if repo_data is None:
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

            # Pre-injected mock inspection support
            if "mock_inspection" in repo_data:
                return self._build_result_from_inspection(owner, repo, repo_data["mock_inspection"], verified_at)
            if "inspection" in repo_data and isinstance(repo_data["inspection"], dict) and repo_data["inspection"]:
                return self._build_result_from_inspection(owner, repo, repo_data["inspection"], verified_at)

            default_branch = repo_data.get("default_branch") or "main"

            # 2. Fetch languages breakdown
            languages = {}
            try:
                lang_res = await client.get(f"{repo_url}/languages", headers=headers)
                if lang_res.status_code in (403, 429):
                    return VerificationResult(
                        status="failed",
                        message=f"GitHub API access rate limited or forbidden for '{owner}/{repo}'.",
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "repo": repo, "http_status": lang_res.status_code},
                        verified_at=verified_at,
                    )
                if lang_res.status_code >= 500:
                    return VerificationResult(
                        status="failed",
                        message=f"GitHub API returned error {lang_res.status_code} while inspecting '{owner}/{repo}'.",
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "repo": repo, "http_status": lang_res.status_code},
                        verified_at=verified_at,
                    )
                if lang_res.status_code == 200 and isinstance(lang_res.json(), dict):
                    languages = lang_res.json()
            except Exception:
                pass
            if not languages and repo_data.get("language"):
                languages = {repo_data["language"]: int(repo_data.get("size", 10000) or 10000)}

            # 3. Fetch root contents list
            root_files = []
            try:
                contents_res = await client.get(f"{repo_url}/contents", headers=headers)
                if contents_res.status_code in (403, 429):
                    return VerificationResult(
                        status="failed",
                        message=f"GitHub API access rate limited or forbidden for '{owner}/{repo}'.",
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "repo": repo, "http_status": contents_res.status_code},
                        verified_at=verified_at,
                    )
                if contents_res.status_code >= 500:
                    return VerificationResult(
                        status="failed",
                        message=f"GitHub API returned error {contents_res.status_code} while inspecting '{owner}/{repo}'.",
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "repo": repo, "http_status": contents_res.status_code},
                        verified_at=verified_at,
                    )
                if contents_res.status_code == 200 and isinstance(contents_res.json(), list):
                    root_files = [item.get("name", "") for item in contents_res.json()]
            except Exception:
                pass

            # 4. Fetch package.json if present
            package_json_deps = []
            if "package.json" in root_files:
                try:
                    pkg_res = await client.get(
                        f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/package.json",
                        headers=_get_github_headers(),
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
                        headers=_get_github_headers(),
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
                    has_workflows = wf_res.status_code == 200 and isinstance(wf_res.json(), list) and len(wf_res.json()) > 0
                except Exception:
                    pass

            # 6. Fetch recursive file tree (capped)
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
            source_candidates: List[Tuple[str, int]] = []
            config_candidates: List[str] = []
            readme_paths: List[str] = []
            test_file_count = 0
            total_tree_files = 0
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
                        if base in CI_CONFIG_MARKERS or low in CI_CONFIG_MARKERS:
                            has_ci_config = True
                        if len(tree_top_files) < 800:
                            tree_top_files.append(low)
                            if base != low:
                                tree_top_files.append(base)

                        # --- content-inspection candidate selection ---
                        if str(entry.get("type") or "blob") != "blob":
                            continue
                        total_tree_files += 1
                        entry_size = int(entry.get("size") or 0)
                        if base.startswith("readme"):
                            readme_paths.append(path)
                        if _is_skippable_path(low):
                            continue
                        if "test" in low or "spec" in low:
                            test_file_count += 1
                        if _is_config_content_path(low):
                            config_candidates.append(path)
                        elif low.endswith(SOURCE_SCAN_EXTENSIONS) and 0 < entry_size <= MAX_SOURCE_FILE_BYTES:
                            source_candidates.append((path, entry_size))
            except Exception:
                pass

            # 7. Fetch Java build manifest contents
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
                        headers=_get_github_headers(),
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

            # 8. Fetch ecosystem manifests
            root_lower = {str(f).lower() for f in root_files}
            eco_manifest_deps: List[str] = []
            eco_python_deps: List[str] = []
            eco_manifests_found: List[str] = []
            extra_fetches = 0

            async def _fetch_raw(path: str) -> str:
                try:
                    r = await client.get(
                        f"https://raw.githubusercontent.com/{owner}/{repo}/{default_branch}/{path}",
                        headers=_get_github_headers(),
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

            # 9. STAGE: repository *content* inspection.
            # Discovery/metadata above is cheap and always runs. Below we read a
            # bounded, prioritized sample of real project artifacts: the README
            # (documentation-level evidence), implementation source files
            # (imports/usages), and configuration/infrastructure files.
            budget = budget if budget is not None else ContentBudget(MAX_CONTENT_FETCHES_PER_REPO)
            content_fetches = 0

            async def _fetch_content(path: str, cap: int) -> str:
                nonlocal content_fetches
                if content_fetches >= MAX_CONTENT_FETCHES_PER_REPO:
                    return ""
                if not budget.take(1):
                    return ""
                content_fetches += 1
                text = await _fetch_raw(path)
                return text[:cap] if text else ""

            # 9a. README — documentation-level evidence only.
            readme_text = ""
            readme_path = ""
            readme_candidates = [f for f in root_files if str(f).lower().startswith("readme")]
            readme_candidates.extend([p for p in readme_paths if p not in readme_candidates])
            if readme_candidates:
                readme_path = str(readme_candidates[0])
                readme_text = await _fetch_content(readme_path, MAX_README_CHARS)

            # 9b. Implementation source files — imports/usages evidence.
            if not source_candidates and root_files:
                # Tree unavailable (large repo / API failure): fall back to root sources.
                source_candidates = [
                    (str(f), 1)
                    for f in root_files
                    if str(f).lower().endswith(SOURCE_SCAN_EXTENSIONS)
                    and not _is_skippable_path(str(f).lower())
                ]
            sampled_source_files: List[str] = []
            import_tokens: Dict[str, int] = {}
            for path in select_source_files(source_candidates, MAX_SOURCE_FILES_PER_REPO):
                text = await _fetch_content(path, MAX_SOURCE_TEXT_CHARS)
                if not text:
                    continue
                sampled_source_files.append(path)
                for token, count in extract_import_tokens(text).items():
                    import_tokens[token] = import_tokens.get(token, 0) + count

            # 9c. Configuration / infrastructure files.
            sampled_config_files: List[str] = []
            config_text_parts: List[str] = []
            root_config_candidates = [
                str(f) for f in root_files if _is_config_content_path(str(f).lower())
            ]
            ordered_configs = root_config_candidates + [
                p for p in config_candidates if p not in root_config_candidates
            ]
            for path in ordered_configs[:MAX_CONFIG_FILES_PER_REPO]:
                text = await _fetch_content(path, MAX_CONFIG_TEXT_CHARS)
                if not text:
                    continue
                sampled_config_files.append(path)
                config_text_parts.append(text)
            config_text = "\n".join(config_text_parts)[: MAX_CONFIG_TEXT_CHARS * MAX_CONFIG_FILES_PER_REPO]

            inspection = {
                "name": repo_data.get("name") or repo,
                "full_name": repo_data.get("full_name") or f"{owner}/{repo}",
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
                "archived": repo_data.get("archived", False),
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
                # Repository content inspection (stage 2)
                "readme_path": readme_path,
                "readme_text": readme_text,
                "readme_present": bool(readme_text),
                "source_files_sampled": sampled_source_files,
                "import_tokens": import_tokens,
                "config_files_sampled": sampled_config_files,
                "config_text": config_text,
                "test_file_count": test_file_count,
                "tree_file_count": total_tree_files,
                "content_fetches": content_fetches,
                "content_budget_exhausted": budget.remaining <= 0,
            }

            result = self._build_result_from_inspection(owner, repo, inspection, verified_at)
            # Signals are built from the full text; only compact facts are
            # persisted with the evidence record.
            result.raw_metadata = compact_inspection(inspection)
            return result

        except httpx.RequestError as e:
            return VerificationResult(
                status="failed",
                message=f"Network connection to GitHub failed: {str(e)[:100]}",
                provider=self.provider_name,
                raw_metadata={"owner": owner, "repo": repo, "error": str(e)},
                verified_at=verified_at,
            )
        except Exception as e:
            return VerificationResult(
                status="failed",
                message=f"Unexpected error while inspecting repository '{owner}/{repo}': {str(e)[:100]}",
                provider=self.provider_name,
                raw_metadata={"owner": owner, "repo": repo, "error": str(e)},
                verified_at=verified_at,
            )

    async def _inspect_repository(
        self,
        owner: str,
        repo: str,
        verified_at: datetime,
        client: Optional[httpx.AsyncClient] = None,
        repo_data: Optional[dict] = None,
        budget: Optional[ContentBudget] = None,
    ) -> VerificationResult:
        """Inspect a single repository reusing an existing client or creating a bounded one."""
        if client is not None:
            return await self._inspect_repository_core(
                owner, repo, verified_at, client, repo_data=repo_data, budget=budget
            )

        try:
            async with httpx.AsyncClient(timeout=6.0) as new_client:
                return await self._inspect_repository_core(
                    owner, repo, verified_at, new_client, repo_data=repo_data, budget=budget
                )
        except httpx.RequestError as e:
            return VerificationResult(
                status="failed",
                message=f"Network connection to GitHub failed: {str(e)[:100]}",
                provider=self.provider_name,
                raw_metadata={"owner": owner, "repo": repo, "error": str(e)},
                verified_at=verified_at,
            )

    async def _fetch_repository_page(
        self,
        client: httpx.AsyncClient,
        owner: str,
        page: int,
        per_page: int = 100,
        headers: Optional[dict] = None,
    ) -> Tuple[int, List[dict], Dict[str, Any]]:
        """Fetch a single page of public repositories for a GitHub user."""
        hdrs = headers or _get_github_headers()
        url = f"https://api.github.com/users/{owner}/repos"
        params = {
            "per_page": per_page,
            "page": page,
            "sort": "updated",
        }
        try:
            res = await client.get(url, headers=hdrs, params=params)
            is_limited, remaining, reset_time = _check_rate_limit(res)
            meta = {
                "status_code": res.status_code,
                "remaining": remaining,
                "reset_time": reset_time,
                "link_header": res.headers.get("link", ""),
                "is_limited": is_limited,
            }
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    return 200, data, meta
                return 200, [], meta
            return res.status_code, [], meta
        except Exception as e:
            return 0, [], {"error": str(e), "is_limited": False}

    async def _fetch_profile_repositories(
        self,
        client: httpx.AsyncClient,
        owner: str,
        headers: Optional[dict] = None,
    ) -> Tuple[List[dict], Dict[str, Any]]:
        """
        Fetch ALL public repositories for a GitHub user using pagination.
        Handles rate limits, empty portfolios, single-page, and multi-page portfolios.
        """
        all_repos: List[dict] = []
        seen_repo_keys: Set[str] = set()
        page = 1
        per_page = 100
        warnings: List[str] = []
        meta = {
            "pages_fetched": 0,
            "rate_limited": False,
            "duplicates_skipped": 0,
            "warnings": warnings,
        }

        while page <= MAX_PROFILE_PAGES:
            logger.debug(f"GitHub profile @{owner}: fetching repositories page {page}")
            status, repos, page_meta = await self._fetch_repository_page(
                client, owner, page, per_page=per_page, headers=headers
            )
            meta["pages_fetched"] += 1

            if page_meta.get("is_limited"):
                msg = f"GitHub API rate limit reached while fetching page {page} for @{owner}."
                if page_meta.get("reset_time"):
                    msg += f" Reset at {page_meta['reset_time']}."
                warnings.append(msg)
                meta["rate_limited"] = True
                break

            if status == 404 and page == 1:
                meta["user_not_found"] = True
                break

            if status != 200 and page == 1 and not repos:
                err = page_meta.get("error") or f"HTTP {status}"
                warnings.append(f"Failed to fetch repositories for @{owner}: {err}")
                break

            if not repos:
                break

            # Pagination with sort=updated can repeat a repository if the
            # profile changes mid-walk: de-duplicate by id/full name.
            for repo_item in repos:
                if not isinstance(repo_item, dict):
                    continue
                key = str(
                    repo_item.get("id")
                    or repo_item.get("full_name")
                    or repo_item.get("name")
                    or ""
                ).lower()
                if key and key in seen_repo_keys:
                    meta["duplicates_skipped"] += 1
                    continue
                if key:
                    seen_repo_keys.add(key)
                all_repos.append(repo_item)
            logger.debug(f"GitHub profile @{owner}: fetched {len(repos)} repositories")

            # Check if this was the last page
            if len(repos) < per_page:
                break

            link_header = page_meta.get("link_header", "")
            if link_header and 'rel="next"' not in link_header:
                break

            page += 1

        logger.debug(f"GitHub profile @{owner}: total repositories = {len(all_repos)}")
        return all_repos, meta

    async def _inspect_profile_repositories(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repos_data: List[dict],
        verified_at: datetime,
        concurrency: int = DEFAULT_PROFILE_CONCURRENCY,
        budget: Optional[ContentBudget] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Tuple[ExtractedSignal, Dict[str, Any]]], List[str]]:
        """
        Concurrently inspect a portfolio of repositories under controlled concurrency.
        Safeguards against runaway rate limits and isolates individual repository failures.
        """
        sem = asyncio.Semaphore(concurrency)
        budget = budget if budget is not None else ContentBudget(DEFAULT_PROFILE_CONTENT_BUDGET)
        inspected_repos: List[Dict[str, Any]] = []
        raw_signals: List[Tuple[ExtractedSignal, Dict[str, Any]]] = []
        warnings: List[str] = []
        rate_limited = False

        async def _inspect_one(repo_meta: dict):
            nonlocal rate_limited
            repo_name = str(repo_meta.get("name") or "")
            full_name = str(repo_meta.get("full_name") or f"{owner}/{repo_name}")
            html_url = str(repo_meta.get("html_url") or f"https://github.com/{owner}/{repo_name}")
            desc = repo_meta.get("description") or ""
            stars = int(repo_meta.get("stargazers_count") or 0)
            forks = int(repo_meta.get("forks_count") or 0)
            watchers = int(repo_meta.get("watchers_count") or 0)
            pushed_at = repo_meta.get("pushed_at") or repo_meta.get("updated_at")
            primary_lang = repo_meta.get("language")

            classification_info = _classify_repository(repo_meta, owner, verified_at)

            # Check for pre-injected test mock inspection inside repository dict
            mock_insp = repo_meta.get("mock_inspection") or repo_meta.get("inspection")
            if mock_insp and isinstance(mock_insp, dict):
                res = self._build_result_from_inspection(owner, repo_name, mock_insp, verified_at)
                summary = {
                    "id": repo_meta.get("id"),
                    "name": repo_name,
                    "full_name": full_name,
                    "url": html_url,
                    "html_url": html_url,
                    "description": desc,
                    "language": primary_lang,
                    "languages": mock_insp.get("languages") or (res.raw_metadata.get("languages") or {}),
                    "stars": stars,
                    "forks": forks,
                    "watchers": watchers,
                    "fork": classification_info["is_fork"],
                    "archived": classification_info["is_archived"],
                    "disabled": bool(repo_meta.get("disabled", False)),
                    "pushed_at": pushed_at,
                    "default_branch": repo_meta.get("default_branch", "main"),
                    "topics": repo_meta.get("topics") or [],
                    "owner": repo_meta.get("owner"),
                    "classification": classification_info["classification"],
                    "classification_details": classification_info,
                    "status": "inspected",
                    "inspection": compact_inspection(res.raw_metadata),
                }
                return summary, res.signals, None

            # Skip network inspection for low evidence (empty / disabled) repos
            if classification_info["is_low_evidence"]:
                summary = {
                    "id": repo_meta.get("id"),
                    "name": repo_name,
                    "full_name": full_name,
                    "url": html_url,
                    "html_url": html_url,
                    "description": desc,
                    "language": primary_lang,
                    "languages": {},
                    "stars": stars,
                    "forks": forks,
                    "watchers": watchers,
                    "fork": classification_info["is_fork"],
                    "archived": classification_info["is_archived"],
                    "disabled": bool(repo_meta.get("disabled", False)),
                    "pushed_at": pushed_at,
                    "default_branch": repo_meta.get("default_branch", "main"),
                    "topics": repo_meta.get("topics") or [],
                    "owner": repo_meta.get("owner"),
                    "classification": classification_info["classification"],
                    "classification_details": classification_info,
                    "status": "skipped_low_evidence",
                    "inspection": {},
                }
                return summary, [], None

            if rate_limited:
                summary = {
                    "id": repo_meta.get("id"),
                    "name": repo_name,
                    "full_name": full_name,
                    "url": html_url,
                    "html_url": html_url,
                    "description": desc,
                    "language": primary_lang,
                    "stars": stars,
                    "fork": classification_info["is_fork"],
                    "archived": classification_info["is_archived"],
                    "pushed_at": pushed_at,
                    "classification": classification_info["classification"],
                    "classification_details": classification_info,
                    "status": "skipped_rate_limited",
                }
                return summary, [], "Skipped due to API rate limit"

            async with sem:
                try:
                    logger.debug(f"GitHub profile @{owner}: inspecting repository {owner}/{repo_name}")
                    result = await self._inspect_repository_core(
                        owner=owner,
                        repo=repo_name,
                        verified_at=verified_at,
                        client=client,
                        repo_data=repo_meta,
                        budget=budget,
                    )
                    if result.status == "verified":
                        summary = {
                            "id": repo_meta.get("id"),
                            "name": repo_name,
                            "full_name": full_name,
                            "url": html_url,
                            "html_url": html_url,
                            "description": desc,
                            "language": primary_lang,
                            "languages": result.raw_metadata.get("languages") or {},
                            "stars": stars,
                            "forks": forks,
                            "watchers": watchers,
                            "fork": classification_info["is_fork"],
                            "archived": classification_info["is_archived"],
                            "disabled": bool(repo_meta.get("disabled", False)),
                            "pushed_at": pushed_at,
                            "default_branch": repo_meta.get("default_branch", "main"),
                            "topics": repo_meta.get("topics") or [],
                            "owner": repo_meta.get("owner"),
                            "classification": classification_info["classification"],
                            "classification_details": classification_info,
                            "status": "inspected",
                            "inspection": compact_inspection(result.raw_metadata),
                        }
                        return summary, result.signals, None
                    else:
                        logger.debug(f"GitHub profile @{owner}: repository inspection failed for {owner}/{repo_name}: {result.message}")
                        if "rate limit" in result.message.lower() or result.raw_metadata.get("http_status") in (403, 429):
                            rate_limited = True
                        summary = {
                            "id": repo_meta.get("id"),
                            "name": repo_name,
                            "full_name": full_name,
                            "url": html_url,
                            "html_url": html_url,
                            "description": desc,
                            "language": primary_lang,
                            "stars": stars,
                            "fork": classification_info["is_fork"],
                            "archived": classification_info["is_archived"],
                            "pushed_at": pushed_at,
                            "classification": classification_info["classification"],
                            "classification_details": classification_info,
                            "status": "failed",
                            "error": result.message,
                        }
                        return summary, [], f"Inspection failed for '{owner}/{repo_name}': {result.message}"
                except Exception as e:
                    logger.debug(f"GitHub profile @{owner}: repository inspection exception for {owner}/{repo_name}: {e}")
                    summary = {
                        "id": repo_meta.get("id"),
                        "name": repo_name,
                        "full_name": full_name,
                        "url": html_url,
                        "html_url": html_url,
                        "description": desc,
                        "language": primary_lang,
                        "classification": classification_info["classification"],
                        "status": "failed",
                        "error": str(e),
                    }
                    return summary, [], f"Inspection exception for '{owner}/{repo_name}': {str(e)[:100]}"

        tasks = [_inspect_one(r) for r in repos_data]
        results = await asyncio.gather(*tasks)

        for summary, signals, warn in results:
            inspected_repos.append(summary)
            if warn:
                warnings.append(warn)
            if signals:
                for sig in signals:
                    raw_signals.append((sig, summary))

        return inspected_repos, raw_signals, warnings

    def _aggregate_profile_signals(
        self,
        owner: str,
        raw_signals: List[Tuple[ExtractedSignal, Dict[str, Any]]],
        verified_at: datetime,
    ) -> List[ExtractedSignal]:
        """
        Aggregate and deduplicate signals across all repositories on a profile.
        Preserves:
        - Canonical taxonomy skill
        - Strongest demonstrated EvidenceDepth
        - Ownership vs fork discount
        - Recency and archival status
        - Full provenance with supporting repositories list
        """
        if not raw_signals:
            return []

        # Group by canonical skill name
        by_skill: Dict[str, List[Tuple[ExtractedSignal, Dict[str, Any]]]] = {}
        for sig, repo in raw_signals:
            canonical = normalize_skill(sig.skill) or sig.skill
            by_skill.setdefault(canonical, []).append((sig, repo))

        aggregated: List[ExtractedSignal] = []

        for skill, items in by_skill.items():
            # Deduplicate by repository: keep strongest signal per repo
            repo_map: Dict[str, Tuple[ExtractedSignal, Dict[str, Any]]] = {}
            for s, r in items:
                r_key = r.get("full_name") or r.get("name") or "unknown"
                if r_key not in repo_map:
                    repo_map[r_key] = (s, r)
                else:
                    existing_s, _ = repo_map[r_key]
                    if (s.depth, s.signal_strength) > (existing_s.depth, existing_s.signal_strength):
                        repo_map[r_key] = (s, r)

            unique_items = list(repo_map.values())
            total_repos = len(unique_items)
            if total_repos == 0:
                continue

            # Classify supporting repositories
            owned_items = [
                (s, r) for s, r in unique_items
                if r.get("classification_details", {}).get("is_owned") or (not r.get("fork") and not r.get("is_fork"))
            ]
            fork_items = [
                (s, r) for s, r in unique_items
                if r.get("fork") or r.get("is_fork") or r.get("classification") == "fork"
            ]
            archived_items = [
                (s, r) for s, r in unique_items
                if r.get("archived") or r.get("is_archived") or r.get("classification") == "archived"
            ]
            active_owned = [
                (s, r) for s, r in owned_items
                if not (r.get("archived") or r.get("is_archived"))
            ]

            # Determine depth and strength
            if active_owned:
                best_sig, _ = max(active_owned, key=lambda x: (x[0].depth, x[0].signal_strength))
                final_depth = best_sig.depth
                base_strength = best_sig.signal_strength
                impl_count = sum(1 for s, _ in active_owned if s.depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION)
                if impl_count >= 2 and final_depth == EvidenceDepth.LEVEL_3_IMPLEMENTATION:
                    final_strength = min(0.82, round(base_strength + 0.03 * min(impl_count - 1, 3), 2))
                else:
                    final_strength = base_strength
            elif owned_items:
                # All owned repos are archived: preserve historical evidence with archival discount
                best_sig, _ = max(owned_items, key=lambda x: (x[0].depth, x[0].signal_strength))
                final_depth = min(best_sig.depth, EvidenceDepth.LEVEL_3_IMPLEMENTATION)
                final_strength = round(min(0.70, best_sig.signal_strength * 0.90), 2)
            else:
                # Only forks exist: strictly enforce fork discount
                best_sig, _ = max(fork_items, key=lambda x: (x[0].depth, x[0].signal_strength))
                final_depth = min(best_sig.depth, EvidenceDepth.LEVEL_2_CONFIG)
                final_strength = round(min(0.55, best_sig.signal_strength), 2)

            # Build provenance repository list
            provenance_repos = [
                {
                    "name": r.get("name"),
                    "full_name": r.get("full_name") or f"{owner}/{r.get('name')}",
                    "url": r.get("url") or r.get("html_url") or f"https://github.com/{owner}/{r.get('name')}",
                    "fork": bool(r.get("fork") or r.get("is_fork")),
                    "archived": bool(r.get("archived") or r.get("is_archived")),
                    "classification": r.get("classification", "owned_active"),
                    "depth": s.depth,
                    "signal_strength": s.signal_strength,
                }
                for s, r in unique_items
            ]

            # Build evidence explanation with provenance
            names = [r.get("name") for _, r in unique_items if r.get("name")]
            sample_names = ", ".join(names[:3])
            if len(names) > 3:
                sample_names += f" and {len(names) - 3} other(s)"

            if active_owned:
                if total_repos == 1:
                    reason = f"{skill} demonstrated in owned public repository '{names[0]}'."
                else:
                    fork_note = f", {len(fork_items)} forked" if fork_items else ""
                    arch_note = f", {len(archived_items)} archived" if archived_items else ""
                    reason = (
                        f"{skill} demonstrated across {total_repos} public repositories "
                        f"({len(owned_items)} owned{fork_note}{arch_note}), including implementation evidence (e.g., {sample_names})."
                    )
            elif owned_items:
                reason = (
                    f"[Archived Repositories] Historical evidence: {skill} demonstrated across "
                    f"{total_repos} archived repositories (e.g., {sample_names})."
                )
            else:
                reason = (
                    f"[Forked Repositories] {skill} referenced across "
                    f"{total_repos} forked repositories (e.g., {sample_names})."
                )

            # Preserve which kinds of repository evidence backed this skill
            # (documentation / configuration / dependency / source usage).
            evidence_kinds = sorted(
                {
                    str(s.metadata.get("evidence_kind"))
                    for s, _ in unique_items
                    if s.metadata.get("evidence_kind")
                }
            )
            metadata: Dict[str, Any] = {
                "owner": owner,
                "repo_count": total_repos,
                "owned_count": len(owned_items),
                "fork_count": len(fork_items),
                "archived_count": len(archived_items),
                "evidence_depth": final_depth,
                "evidence_kinds": evidence_kinds,
                "documentation_only": bool(evidence_kinds) and evidence_kinds == ["documentation"],
                "repositories": provenance_repos,
            }
            if not owned_items:
                metadata["is_fork"] = True
            if not active_owned and owned_items:
                metadata["archived"] = True
                metadata["historical_only"] = True

            # Generic evidence validation gate: reject weak/incidental candidates
            tmp_signal = ExtractedSignal(
                skill=skill,
                signal_strength=final_strength,
                depth=final_depth,
                reason=reason,
                source_reliability=GITHUB_RELIABILITY,
                metadata=metadata,
            )
            ok, _reason = _validate_aggregated(tmp_signal, metadata)
            if not ok:
                # Keep rejected for diagnostics but do not emit as final skill
                # Store reason in a side channel via metadata? Not needed for final signals
                continue
            aggregated.append(tmp_signal)

        # Sort by depth and signal_strength descending
        aggregated.sort(key=lambda s: (s.depth, s.signal_strength), reverse=True)
        return aggregated

    async def _inspect_profile(
        self,
        owner: str,
        verified_at: datetime,
        evidence: Optional[dict] = None,
    ) -> VerificationResult:
        """
        Inspect all public repositories for a GitHub profile:
        1. Fetch all repositories page-by-page (no arbitrary 5-repo limit)
        2. Collect metadata and classify each repository
        3. Inspect public repositories with bounded concurrency using a shared HTTP client
        4. Aggregate signals across repositories without duplicate skill inflation
        5. Return structured verification result with complete profile and repository provenance
        """
        headers = _get_github_headers()
        profile_url = f"https://api.github.com/users/{owner}"
        all_warnings: List[str] = []

        mock_repos = None
        if evidence and isinstance(evidence, dict):
            mock_repos = evidence.get("mock_profile_repos") or evidence.get("mock_repos")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                public_repos_count = 0

                if mock_repos is not None:
                    all_repos = list(mock_repos)
                    public_repos_count = len(all_repos)
                    logger.debug(f"GitHub profile @{owner}: loaded {len(all_repos)} repositories from mock evidence")
                else:
                    # Verify user existence via /users/{owner}
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

                    u_data = res.json() if res.status_code == 200 and isinstance(res.json(), dict) else {}
                    public_repos_count = u_data.get("public_repos", 0)

                    # Fetch ALL public repositories page-by-page
                    all_repos, fetch_meta = await self._fetch_profile_repositories(client, owner, headers=headers)
                    all_warnings.extend(fetch_meta.get("warnings", []))

                    if fetch_meta.get("rate_limited") and not all_repos:
                        return VerificationResult(
                            status="failed",
                            message=f"GitHub API rate limited while fetching repositories for user '{owner}'.",
                            provider=self.provider_name,
                            raw_metadata={"owner": owner, "rate_limited": True},
                            verified_at=verified_at,
                            warnings=all_warnings,
                        )

                    # Calibrate public_repos_count
                    public_repos_count = max(public_repos_count, len(all_repos))

                # Handle zero repositories
                if len(all_repos) == 0:
                    return VerificationResult(
                        status="verified",
                        message=f"GitHub profile '{owner}' verified, but has 0 public repositories to inspect.",
                        provider=self.provider_name,
                        signals=[],
                        raw_metadata={
                            "username": owner,
                            "profile_url": f"https://github.com/{owner}",
                            "public_repositories": 0,
                            "repositories_fetched": 0,
                            "repositories_inspected": 0,
                            "repositories_failed": 0,
                            "repositories_skipped": 0,
                            "owned_repositories": 0,
                            "forked_repositories": 0,
                            "archived_repositories": 0,
                            "active_repositories": 0,
                            "repositories": [],
                            # Backward compatibility
                            "owner": owner,
                            "public_repos": 0,
                            "repos": [],
                        },
                        verified_at=verified_at,
                        warnings=all_warnings,
                    )

                # Inspect repositories concurrently using shared HTTP client.
                # Repository discovery above is never capped; deep content
                # reads share one profile-wide budget for API/rate-limit safety.
                content_budget = ContentBudget(DEFAULT_PROFILE_CONTENT_BUDGET)
                inspected_repos, raw_signals, inspect_warnings = await self._inspect_profile_repositories(
                    client=client,
                    owner=owner,
                    repos_data=all_repos,
                    verified_at=verified_at,
                    concurrency=DEFAULT_PROFILE_CONCURRENCY,
                    budget=content_budget,
                )
                if content_budget.remaining <= 0:
                    all_warnings.append(
                        "Profile-wide repository content budget exhausted: some repositories were "
                        "analysed from structure and manifests only."
                    )
                all_warnings.extend(inspect_warnings)

                # Aggregate signals across repositories with generic validation gate
                # Compute candidates before filtering for diagnostics
                from collections import defaultdict as _dd
                _by_skill_raw: Dict[str, List] = _dd(list)
                for _sig, _repo in raw_signals:
                    _canon = normalize_skill(_sig.skill) or _sig.skill
                    _by_skill_raw.setdefault(_canon, []).append((_sig, _repo))
                candidates_detected = len(_by_skill_raw)
                signals = self._aggregate_profile_signals(owner, raw_signals, verified_at)
                candidates_accepted = len(signals)
                candidates_rejected = max(0, candidates_detected - candidates_accepted)
                # Breakdown for diagnostics
                weak_doc = sum(1 for s in signals if (s.metadata.get("evidence_kinds") == ["documentation"]))  # should be 0 after filter
                logger.debug(f"GitHub profile @{owner}: aggregation {candidates_detected} candidates -> {candidates_accepted} accepted, {candidates_rejected} rejected")

                # Compile statistics
                repos_fetched = len(all_repos)
                repos_inspected = sum(1 for r in inspected_repos if r.get("status") == "inspected")
                repos_failed = sum(1 for r in inspected_repos if r.get("status") == "failed")
                repos_skipped = sum(1 for r in inspected_repos if r.get("status") not in ("inspected", "failed"))
                owned_repos = sum(1 for r in inspected_repos if r.get("classification_details", {}).get("is_owned"))
                forked_repos = sum(1 for r in inspected_repos if r.get("fork"))
                archived_repos = sum(1 for r in inspected_repos if r.get("archived"))
                active_repos = sum(1 for r in inspected_repos if r.get("classification_details", {}).get("is_active"))

                raw_metadata = {
                    "username": owner,
                    "profile_url": f"https://github.com/{owner}",
                    "public_repositories": public_repos_count,
                    "repositories_fetched": repos_fetched,
                    "repositories_inspected": repos_inspected,
                    "repositories_failed": repos_failed,
                    "repositories_skipped": repos_skipped,
                    "owned_repositories": owned_repos,
                    "forked_repositories": forked_repos,
                    "archived_repositories": archived_repos,
                    "active_repositories": active_repos,
                    "repositories_content_analyzed": sum(
                        1
                        for r in inspected_repos
                        if int((r.get("inspection") or {}).get("content_fetches") or 0) > 0
                    ),
                    "content_fetches_used": content_budget.used,
                    "content_budget": content_budget.total,
                    "github_candidates_detected": candidates_detected,
                    "github_candidates_accepted": candidates_accepted,
                    "github_candidates_rejected": candidates_rejected,
                    "repositories": inspected_repos,
                    # Backward compatibility
                    "owner": owner,
                    "public_repos": public_repos_count,
                    "repos": [r["name"] for r in inspected_repos if r.get("name")],
                }

                detected_names = [s.skill for s in signals]
                skills_preview = f" Detected {len(signals)} technical skill(s): {', '.join(detected_names[:5])}." if signals else " No technical skills detected."
                message = (
                    f"Verified GitHub profile '{owner}' with {public_repos_count} public repositories "
                    f"({repos_inspected} inspected, {repos_failed} failed, {repos_skipped} skipped).{skills_preview}"
                )

                return VerificationResult(
                    status="verified",
                    message=message,
                    provider=self.provider_name,
                    signals=signals,
                    raw_metadata=raw_metadata,
                    verified_at=verified_at,
                    warnings=all_warnings,
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
        - Level 1: README / description / topic mention (documentation only)
        - Level 2: Dependencies / configs detected (package.json, requirements.txt, Dockerfile)
        - Level 3: Concrete implementation detected (source files, imports/usages)
        - Level 4: Substantial implementation (deps + code + workflows/tests)

        At most one signal per canonical skill is emitted per repository: the
        strongest evidence wins and weaker corroboration is kept as provenance,
        so repeated mentions inside one repository cannot inflate proficiency.
        """
        signal_map: Dict[str, ExtractedSignal] = {}
        evidence_notes: Dict[str, List[str]] = {}
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
        # Repository content evidence (stage 2 of the pipeline)
        readme_text = str(inspection.get("readme_text") or "")
        config_text = str(inspection.get("config_text") or "")
        topics = inspection.get("topics") or []
        import_tokens = {
            str(k).lower(): int(v or 0)
            for k, v in (inspection.get("import_tokens") or {}).items()
        }
        sampled_source_files = list(inspection.get("source_files_sampled") or [])
        sampled_config_files = list(inspection.get("config_files_sampled") or [])
        has_workflows = bool(inspection.get("has_workflows"))
        has_ci_config = bool(inspection.get("has_ci_config"))
        has_k8s_manifests = bool(inspection.get("has_k8s_manifests"))
        k8s_manifest_count = int(inspection.get("k8s_manifest_count") or 0)
        is_fork = bool(inspection.get("is_fork", False))
        is_archived = bool(inspection.get("archived", False) or inspection.get("is_archived", False))

        if is_fork:
            warnings.append(
                f"Repository '{repo_name}' is a fork of an upstream repository. "
                f"Implementation signals are discounted to configuration/reference level."
            )
        if is_archived:
            warnings.append(
                f"Repository '{repo_name}' is archived. Technical evidence reflects historical implementation."
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
        has_tests = has_test_files or has_test_deps or int(inspection.get("test_file_count") or 0) > 0

        # Helper to safely record signals honoring fork discounts.
        # Only the strongest evidence for a canonical skill is kept per
        # repository; weaker corroborating findings are retained as provenance.
        def _add_signal(
            skill_name: str,
            depth: int,
            reason_text: str,
            meta: Optional[dict] = None,
            only_if_absent: bool = False,
        ):
            canonical = normalize_skill(skill_name) or skill_name
            final_depth = min(depth, EvidenceDepth.LEVEL_2_CONFIG) if is_fork else depth
            raw_strength = EvidenceDepth.get_strength_for_depth(final_depth)
            final_strength = round(min(0.55, raw_strength * 0.70), 2) if is_fork else raw_strength
            final_reason = f"[Forked Repository] {reason_text}" if is_fork else reason_text
            metadata = dict(meta or {})
            if is_fork:
                metadata["is_fork"] = True
            if is_archived:
                metadata["archived"] = True
                if not is_fork:
                    final_reason = f"[Archived] {final_reason}"

            notes = evidence_notes.setdefault(canonical, [])
            existing = signal_map.get(canonical)
            if existing is not None:
                if only_if_absent:
                    return
                if len(notes) < 8:
                    notes.append(final_reason)
                if (existing.depth, existing.signal_strength) >= (final_depth, final_strength):
                    # Keep the stronger evidence: corroboration does not raise strength.
                    return
                metadata = {**existing.metadata, **metadata}
            else:
                notes.append(final_reason)

            signal_map[canonical] = ExtractedSignal(
                skill=canonical,
                signal_strength=final_strength,
                depth=final_depth,
                reason=final_reason,
                source_reliability=GITHUB_RELIABILITY,
                metadata=metadata,
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
                {"files": details, "evidence_kind": "configuration"},
            )

        # 2. CI/CD & GitHub Actions Detection
        if has_workflows or any(".github" in f for f in all_files):
            depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION if has_workflows else EvidenceDepth.LEVEL_2_CONFIG
            _add_signal(
                "GitHub Actions",
                depth,
                f"Repository '{repo_name}' contains automated CI/CD workflow definitions (.github/workflows).",
                {"has_workflows": has_workflows, "evidence_kind": "configuration"},
            )
            _add_signal(
                "CI/CD",
                depth,
                f"Repository '{repo_name}' configures automated integration/deployment pipelines.",
                {"evidence_kind": "configuration"},
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
                    {"package_json": True, "evidence_kind": "dependency_manifest"},
                )

            # Next.js
            if any("next" in d for d in pkg_deps):
                _add_signal(
                    "Next.js",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' contains Next.js framework dependencies.",
                    {"evidence_kind": "dependency_manifest"},
                )

            # Express
            if any("express" in d for d in pkg_deps):
                _add_signal(
                    "Express",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' contains Express server framework dependencies.",
                    {"evidence_kind": "dependency_manifest"},
                )

            # Node.js
            if "package.json" in all_files or pkg_deps:
                _add_signal(
                    "Node.js",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' contains Node.js runtime package manifest.",
                    {"evidence_kind": "dependency_manifest"},
                )

        # TypeScript Detection (independent of package.json)
        if any("typescript" in d for d in all_deps) or "tsconfig.json" in all_files or "TypeScript" in languages:
            _add_signal(
                "TypeScript",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' contains TypeScript configuration and code.",
                {"evidence_kind": "dependency_manifest"},
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
                {"evidence_kind": "implementation"},
            )

            # Python Frameworks & Data Science
            if any(d in py_deps for d in ("fastapi", "flask", "django")):
                _add_signal(
                    "REST APIs",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' implements REST API services with Python web frameworks.",
                    {"evidence_kind": "dependency_manifest"},
                )

            if any("pandas" in d for d in py_deps):
                _add_signal(
                    "Pandas",
                    EvidenceDepth.LEVEL_2_CONFIG,
                    f"Repository '{repo_name}' includes Pandas data analysis dependencies.",
                    {"evidence_kind": "dependency_manifest"},
                )
            if any("numpy" in d for d in py_deps):
                _add_signal(
                    "NumPy",
                    EvidenceDepth.LEVEL_2_CONFIG,
                    f"Repository '{repo_name}' includes NumPy numerical computing dependencies.",
                    {"evidence_kind": "dependency_manifest"},
                )

            if any(d in py_deps for d in ("scikit-learn", "sklearn", "torch", "tensorflow")):
                _add_signal(
                    "Machine Learning",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' specifies machine learning framework dependencies.",
                    {"evidence_kind": "dependency_manifest"},
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
                    "evidence_kind": "implementation" if java_depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION else "dependency_manifest",
                },
            )
            if has_spring:
                _add_signal(
                    "Spring Boot",
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    f"Repository '{repo_name}' declares Spring framework dependencies in its Java build manifest.",
                    {"framework": "spring_boot", "evidence_kind": "dependency_manifest"},
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
                {"source_file_count": _files, "language_bytes": _bytes, "has_build_manifest": _manifest, "evidence_kind": "implementation" if _depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION else "dependency_manifest"},
            )

        # 5c. Cross-ecosystem web frameworks -> canonical REST APIs skill.
        rest_hits = sorted({d for d in all_deps if d in REST_FRAMEWORK_DEPS})
        if rest_hits:
            _add_signal(
                "REST APIs",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' implements REST API services ({', '.join(rest_hits[:5])}).",
                {"frameworks": rest_hits[:5], "evidence_kind": "dependency_manifest"},
            )

        # 5d. Styling dependencies -> canonical CSS skill.
        css_hits = sorted({d for d in all_deps if d in CSS_DEPS})
        if css_hits:
            _add_signal(
                "CSS",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' declares styling dependencies ({', '.join(css_hits[:5])}).",
                {"dependencies": css_hits[:5], "evidence_kind": "dependency_manifest"},
            )

        # 5e. Kubernetes manifests -> canonical Kubernetes skill (config-level).
        if has_k8s_manifests:
            _add_signal(
                "Kubernetes",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' contains Kubernetes deployment manifests ({k8s_manifest_count} file(s)).",
                {"manifest_count": k8s_manifest_count, "evidence_kind": "configuration"},
            )

        # 5f. Non-GitHub CI configs (Jenkins/GitLab/Travis/Circle/Azure) -> CI/CD.
        if has_ci_config and not has_workflows:
            _add_signal(
                "CI/CD",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' configures continuous integration pipelines.",
                {"evidence_kind": "configuration"},
            )

        # 6. Database Dependencies & ORMs
        if any(d in all_deps for d in ("pg", "postgres", "postgresql", "psycopg2", "asyncpg")):
            _add_signal(
                "PostgreSQL",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' contains explicit PostgreSQL database adapter dependencies.",
                {"evidence_kind": "dependency_manifest"},
            )
        if any(d in all_deps for d in ("mongodb", "mongoose", "pymongo")):
            _add_signal(
                "MongoDB",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' contains MongoDB driver dependencies.",
                {"evidence_kind": "dependency_manifest"},
            )
        if any(d in all_deps for d in ("mysql", "mysql2", "pymysql", "mysqldb", "mysql-connector")):
            _add_signal(
                "MySQL",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' contains explicit MySQL database adapter dependencies.",
                {"evidence_kind": "dependency_manifest"},
            )
        if any(d in all_deps for d in ("redis", "ioredis")):
            _add_signal(
                "Redis",
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' includes Redis client dependencies.",
                {"evidence_kind": "dependency_manifest"},
            )

        # Database Design (ORMs and migration engines) -> canonical DBMS skill
        orm_libs = {"prisma", "typeorm", "sequelize", "sqlalchemy", "alembic", "mongoose", "knex", "hibernate", "mikro-orm"} | EXTRA_ORM_LIBS
        if any(any(ol in d for ol in orm_libs) for d in all_deps):
            _add_signal(
                "DBMS",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' implements structured database ORM/schema migration models.",
                {"evidence_kind": "implementation"},
            )

        # 7. Authentication & Security -> canonical Application Security skill
        auth_libs = {"jsonwebtoken", "jwt", "bcrypt", "passport", "auth0", "next-auth", "passlib", "pyjwt", "oauthlib"}
        if any(any(al in d for al in auth_libs) for d in all_deps):
            _add_signal(
                "Application Security",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' configures secure authentication/authorization libraries.",
                {"evidence_kind": "dependency_manifest"},
            )

        # 8. Full-Stack / Architecture Structure
        has_frontend_dir = any(any(f.startswith(d) or f == d for d in ("client", "frontend", "web", "ui")) for f in all_files)
        has_backend_dir = any(any(f.startswith(d) or f == d for d in ("server", "backend", "api", "service")) for f in all_files)
        if has_frontend_dir and has_backend_dir:
            _add_signal(
                "Software Architecture",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' implements decoupled full-stack architecture (frontend + backend modules).",
                {"full_stack_monorepo": True, "evidence_kind": "implementation"},
            )

        # 9. Testing Suite
        if has_tests:
            _add_signal(
                "Testing",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Repository '{repo_name}' contains automated test suite configurations/files.",
                {"evidence_kind": "tests"},
            )

        # 10. Git Skill
        if bool(languages) or bool(root_files) or bool(inspection.get("top_files")) or int(inspection.get("size") or 0) > 0:
            _add_signal(
                "Git",
                EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                f"Verified public repository '{repo_name}' hosted on GitHub with commit history.",
                {"evidence_kind": "implementation"},
            )

        # 11. Declared dependencies -> canonical skills (taxonomy driven).
        # Any dependency in any ecosystem manifest that resolves to a canonical
        # skill becomes configuration/dependency-level evidence. No technology
        # is special-cased here: resolution goes through normalize_skill.
        dep_skills = dependency_skill_names(all_deps)
        for dep_skill, dep_token in sorted(dep_skills.items()):
            _add_signal(
                dep_skill,
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' declares '{dep_token}' in its dependency/build manifest.",
                {"dependency": dep_token, "evidence_kind": "dependency_manifest"},
            )

        # 12. Imports / usages observed in sampled implementation files.
        # Depth scales with how often the technology is actually used and
        # whether the usage is backed by a declared dependency or tests.
        usage_counts = import_skill_counts(import_tokens)
        for use_skill, use_count in sorted(usage_counts.items()):
            declared = use_skill in dep_skills
            if use_count >= 3 and (declared or has_tests):
                use_depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL
            elif use_count >= 2 or (use_count >= 1 and declared):
                use_depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION
            else:
                use_depth = EvidenceDepth.LEVEL_2_CONFIG
            _add_signal(
                use_skill,
                use_depth,
                (
                    f"Repository '{repo_name}' imports/uses {use_skill} in {use_count} place(s) "
                    f"across inspected source files"
                    f"{' with a matching declared dependency' if declared else ''}."
                ),
                {
                    "usage_count": use_count,
                    "declared_dependency": declared,
                    "source_files_inspected": sampled_source_files[:MAX_SOURCE_FILES_PER_REPO],
                    "evidence_kind": "source_usage",
                },
            )

        # 13. Configuration / infrastructure file contents.
        # A technology repeated inside a real config file is configuration
        # evidence; a single passing mention stays documentation-level.
        for cfg_skill, cfg_count in sorted(skill_mention_counts(config_text).items()):
            cfg_depth = (
                EvidenceDepth.LEVEL_2_CONFIG if cfg_count >= 2 else EvidenceDepth.LEVEL_1_MENTION
            )
            _add_signal(
                cfg_skill,
                cfg_depth,
                (
                    f"Repository '{repo_name}' references {cfg_skill} in project configuration "
                    f"({', '.join(sampled_config_files[:3]) or 'config files'})."
                ),
                {
                    "config_mentions": cfg_count,
                    "config_files": sampled_config_files[:3],
                    "evidence_kind": "configuration",
                },
            )

        # 14. Documentation-only evidence (README / description / topics).
        # Weakest tier by design: recorded only when no stronger evidence for
        # the same skill was found anywhere else in this repository.
        doc_text = " ".join(
            [str(description or ""), " ".join(str(t) for t in topics), readme_text]
        ).strip()
        for doc_skill, doc_count in sorted(skill_mention_counts(doc_text).items()):
            _add_signal(
                doc_skill,
                EvidenceDepth.LEVEL_1_MENTION,
                (
                    f"Repository '{repo_name}' mentions {doc_skill} in its documentation "
                    f"(README/description/topics) without supporting implementation evidence."
                ),
                {
                    "documentation_only": True,
                    "mentions": doc_count,
                    "evidence_kind": "documentation",
                },
                only_if_absent=True,
            )

        # Generic evidence-validation gate: candidate -> validated
        # Weak/incidental evidence is downgraded to weak candidate, not final skill
        accepted_map: Dict[str, ExtractedSignal] = {}
        rejected_candidates: List[Dict[str, Any]] = []
        for canonical, sig in signal_map.items():
            kind = str(sig.metadata.get("evidence_kind") or "")
            ok, reason = _validate_repo_signal(canonical, sig.depth, kind, inspection)
            if not ok:
                rejected_candidates.append({
                    "skill": canonical,
                    "depth": sig.depth,
                    "evidence_kind": kind,
                    "reason": reason,
                    "signal_strength": sig.signal_strength,
                })
                continue
            accepted_map[canonical] = sig
        signal_map = accepted_map
        # Keep rejected for diagnostics/provenance
        if rejected_candidates:
            inspection["rejected_candidates"] = rejected_candidates
            inspection["rejected_count"] = len(rejected_candidates)
        inspection["candidates_detected"] = len(signal_map) + len(rejected_candidates)
        inspection["candidates_accepted"] = len(signal_map)

        # Attach corroborating evidence provenance without changing strength.
        signals: List[ExtractedSignal] = []
        for canonical, sig in signal_map.items():
            notes = evidence_notes.get(canonical) or []
            if notes:
                sig.metadata["supporting_evidence"] = notes[:5]
                sig.metadata["evidence_signal_count"] = len(notes)
            signals.append(sig)

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
