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
from ...core.config import get_settings
from ..skill_taxonomy import (
    normalize_skill,
    normalize_skill_slug,
    extract_known_skills_from_text,
    get_canonical_skill,
)
from .github_validation import validate_aggregated_signal as _validate_aggregated
from .github_validation import validate_repo_signal as _validate_repo_signal
from .engineering_practices import (
    aggregate_practices as _aggregate_practices,
    analyze_engineering_practices as _analyze_practices,
    detect_error_handling as _detect_error_handling,
    merge_error_counts as _merge_error_counts,
)
from .usage_status import (
    API_USAGE_PATTERNS as _PHASE3_API_PATTERNS,
    STRING_SENSITIVE_PATTERN_IDS as _PHASE3_STRING_SENSITIVE_IDS,
    MENTIONED as _US_MENTIONED,
    DECLARED as _US_DECLARED,
    IMPORTED as _US_IMPORTED,
    USED as _US_USED,
    SUBSTANTIAL as _US_SUBSTANTIAL,
    STATUS_ORDER as _STATUS_ORDER,
    STATUS_TO_DEPTH as _STATUS_TO_DEPTH,
    status_to_depth as _status_to_depth,
    classify_usage_status as _classify_usage_status,
    strip_string_literals as _strip_string_literals,
)
from .file_importance import (
    classify_file_importance as _classify_file_importance,
    assess_repository_importance as _assess_repo_importance,
    importance_weight as _importance_weight,
    max_supported_depth as _max_depth_for_tier,
    label as _importance_label,
    IGNORE as _FI_IGNORE,
    LOW as _FI_LOW,
    MEDIUM as _FI_MEDIUM,
    HIGH as _FI_HIGH,
    VERY_HIGH as _FI_VERY_HIGH,
)

logger = logging.getLogger(__name__)

# GitHub is supporting evidence (MEDIUM), not a definitive skill test.
# Repository contents prove technology exposure, not personal mastery, so the
# INAURA assessment (0.95), performance platforms (0.85) and verified
# coursework (0.80) outrank it; resume/LinkedIn (0.50/0.40) rank below.
# Value is owned by services.evidence_weights (single source of truth).
GITHUB_RELIABILITY = source_reliability("github")

# ---------------------------------------------------------------------------
# Provenance coherence helpers – enforce a single consistent contract for the
# final accepted signal. A repository must never display substantial
# implementation while its depth is only Mention, and usage_status must not
# claim stronger evidence than the final accepted depth supports.
# ---------------------------------------------------------------------------
def _coerce_status_to_depth(status: str, depth: int) -> str:
    """Cap a usage_status so its implied depth never exceeds the accepted depth."""
    try:
        d = int(depth)
    except (TypeError, ValueError):
        d = 1
    s = str(status or "").lower()
    s_depth = _STATUS_TO_DEPTH.get(s, 0)
    if s_depth <= d:
        return s if s in _STATUS_TO_DEPTH else s
    # downgrade to the strongest status that fits within depth
    if d <= 0:
        return "none"
    if d == 1:
        return _US_MENTIONED
    if d == 2:
        return _US_DECLARED
    if d == 3:
        # imported and used both map to 3; downgrade substantial -> used
        return _US_USED
    return _US_SUBSTANTIAL

def _coerce_importance_to_depth(label: str, depth: int) -> str:
    """Ensure file_importance label does not imply stronger evidence than depth."""
    # Map depth to minimal required tier: 0 ignore,1 low,2 medium,3 high,4 very_high
    depth_to_label = {0: "ignore", 1: "low", 2: "medium", 3: "high", 4: "very_high"}
    expected = depth_to_label.get(int(depth) if isinstance(depth, int) else 0, "low")
    rank = {"ignore": 0, "low": 1, "medium": 2, "high": 3, "very_high": 4}
    cur = str(label or "").lower()
    if rank.get(cur, 1) <= rank.get(expected, 1):
        return cur  # keep weaker or equal – never upgrade
    return expected

def _status_rank(status: str) -> int:
    try:
        return _STATUS_ORDER.index(str(status or "").lower())
    except ValueError:
        return -1

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
MAX_GITHUB_RETRIES = 2
MIN_SAFE_REMAINING_REQUESTS = 2
_INSPECTION_CACHE: Dict[str, Tuple[Dict[str, Any], List[ExtractedSignal]]] = {}

# Vendored / generated / dependency directories that carry no authorship
# evidence and must never be downloaded.
SKIP_PATH_MARKERS = (
    "node_modules/", "bower_components/", "vendor/", "third_party/", "thirdparty/",
    "dist/", "build/", "out/", "target/", "obj/", ".next/", ".nuxt/", "coverage/",
    "__pycache__/", "site-packages/", "venv/", ".venv/", "env/", "migrations/",
    "generated/", "gen/", ".git/", "docs/_build/", "public/vendor/",
)
# Lockfiles, minified bundles and sourcemaps carry no authorship evidence and
# must never inflate implementation counts (pnpm/yarn/npm, pip, cargo, etc.).
SKIP_FILE_MARKERS = (
    ".min.js", ".min.css", ".bundle.js",
    ".lock", ".map", "-lock.json", "-lock.yaml", "-lock.yml",
    "pnpm-lock.yaml", "package-lock.json", "yarn.lock",
    ".pyc", ".pyo", ".o", ".obj", ".exe", ".dll", ".so", ".bin",
)

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

# ---------------------------------------------------------------------------
# Repository-level implementation inspection.
#
# INAURA performs repository-level code and artifact inspection to extract
# evidence of demonstrated technical skills. It does not claim to understand
# every line of code: it looks for layered, corroborating artifacts —
# documentation mentions, dependency declarations, imports, framework-specific
# API usage, and substantial multi-file implementation — and grades evidence
# depth accordingly (EvidenceDepth L1 < L2 < L3 < L4).
# ---------------------------------------------------------------------------

_COMMENT_BLOCK_PATTERNS = (
    re.compile(r"/\*.*?\*/", re.S),          # C-style /* ... */
    re.compile(r"<!--.*?-->", re.S),         # HTML/XML <!-- ... -->
    re.compile(r'"""[\s\S]*?"""', re.S),     # Python triple-double docstrings
    re.compile(r"'''[\s\S]*?'''", re.S),     # Python triple-single docstrings
)


def _strip_code_comments(text: str) -> str:
    """
    Remove comments/docstrings from source text before import/usage scanning.

    A technology mentioned only inside comments must not count as
    implementation evidence (e.g. ``# import pandas`` or ``// import React``).
    This is a heuristic inspection aid, not a full parser: string literals
    that look like comments may be stripped conservatively, which is
    acceptable because imports/usage require corroboration elsewhere.
    """
    if not text:
        return ""
    stripped = str(text)
    for pat in _COMMENT_BLOCK_PATTERNS:
        stripped = pat.sub("\n", stripped)
    lines: List[str] = []
    for line in stripped.splitlines():
        s = line.strip()
        # Full-line comments in common languages
        if s.startswith(("#", "//", "--", "*", "<!--")):
            lines.append("")
            continue
        # Inline trailing comments: cut at // or # preceded by whitespace,
        # and at -- for SQL/Lua style. Keep it conservative to avoid
        # breaking URLs (https://) or anchors (# in CSS).
        cut = len(line)
        m = re.search(r"\s//(?!/)", line)
        if m:
            cut = min(cut, m.start())
        m2 = re.search(r"\s#[^\n]*$", line)
        # Only treat # as comment outside of common non-code contexts:
        # require the line to look like code (contains = ( : ; { } or import).
        if m2 and re.search(r"[=(:;{}]|^\s*(import|from|use|using|require|gem|include)\b", line):
            cut = min(cut, m2.start())
        lines.append(line[:cut] if cut < len(line) else line)
    return "\n".join(lines)


# Canonical skill -> [(pattern_id, regex)] for framework-specific API usage.
# Each pattern signals *actual implementation* (hooks, components, routes,
# handlers, queries), not a mere keyword mention. Matching is performed on
# comment-stripped source text.
FRAMEWORK_USAGE_PATTERNS: Dict[str, List[Tuple[str, str]]] = {
    "React": [
        ("hook_useState", r"\buseState\s*\("),
        ("hook_useEffect", r"\buseEffect\s*\("),
        ("hook_generic", r"\buse(?:Context|Reducer|Memo|Callback|Ref|Id|Transition|DeferredValue|ImperativeHandle|LayoutEffect|SyncExternalStore)\s*\("),
        ("component_class", r"\bextends\s+(?:React\.)?(?:Component|PureComponent)\b"),
        ("component_func", r"\bfunction\s+[A-Z]\w*\s*\("),
        ("jsx_component", r"<[A-Z]\w*[\s/>]"),
        ("react_api", r"\bReact\s*\.\s*(?:createElement|Fragment|StrictMode|Suspense|lazy|memo|forwardRef|createContext|useState|useEffect)\b"),
        ("react_dom", r"\b(?:ReactDOM|createRoot|hydrateRoot)\s*\.?\s*\(?"),
        ("jsx_attr", r"\bclassName\s*="),
        ("state_mgmt", r"\b(?:Redux|createStore|configureStore|useSelector|useDispatch|Recoil|Zustand|MobX|Context\.Provider)\b"),
        ("router", r"\b(?:BrowserRouter|HashRouter|Routes|Route|Link|useNavigate|useParams|useLocation)\b"),
    ],
    "Next.js": [
        ("next_import", r"""from\s+['"]next(?:/[\w-]+)?['"]"""),
        ("data_fetch", r"\b(?:getServerSideProps|getStaticProps|getStaticPaths|generateStaticParams|generateMetadata)\b"),
        ("next_api", r"\b(?:NextRequest|NextResponse|notFound|redirect|revalidatePath|revalidateTag)\b"),
        ("next_component", r"""from\s+['"]next/(?:link|image|head|router|navigation)['"]"""),
    ],
    "Express": [
        ("express_init", r"\bexpress\s*\(\s*\)"),
        ("route_handler", r"\bapp\s*\.\s*(?:get|post|put|delete|patch|use|listen)\s*\("),
        ("router", r"\bRouter\s*\(\s*\)"),
        ("middleware", r"\bapp\s*\.\s*use\s*\("),
    ],
    "Node.js": [
        ("node_require", r"""\brequire\(\s*['"](?:fs|path|http|https|express|node:[\w-]+)['"]\s*\)"""),
        ("node_import", r"""from\s+['"](?:fs|path|http|https|node:[\w-]+)['"]"""),
        ("server_listen", r"\.listen\s*\(\s*\d+"),
        ("process_api", r"\bprocess\s*\.\s*(?:env|argv|exit|nextTick)\b"),
    ],
    "TypeScript": [
        ("type_annotation", r":\s*(?:string|number|boolean|void|never|unknown|any)\b"),
        ("interface_def", r"\binterface\s+\w+"),
        ("type_alias", r"\btype\s+\w+\s*="),
        ("generic", r"<[A-Z]\w*(?:,\s*[A-Z]\w*)*>"),
        ("ts_directive", r"//\s*@ts-"),
    ],
    "REST APIs": [
        ("fastapi_app", r"\bFastAPI\s*\("),
        ("flask_app", r"\bFlask\s*\("),
        ("django_view", r"\b(?:APIView|ViewSet|Response|serializers?)\b"),
        ("route_decorator", r"@app\s*\.\s*(?:route|get|post|put|delete|patch)\s*\("),
        ("api_router", r"\bAPIRouter\s*\("),
        ("http_client", r"\b(?:fetch\s*\(|axios\s*\.\s*(?:get|post|put|delete)|XMLHttpRequest)\b"),
        ("express_route", r"\b(?:app|router)\s*\.\s*(?:get|post|put|delete|patch)\s*\(\s*['\"]/"),
    ],
    "PostgreSQL": [
        ("pg_import", r"\b(?:psycopg2|asyncpg|pg|postgres)\b"),
        ("sql_ddl", r"\bCREATE\s+TABLE\b"),
        ("sql_query", r"\bSELECT\b.+?\bFROM\b"),
        ("pg_config", r"\bPOSTGRES(?:_DB|_USER|_PASSWORD)?\b"),
    ],
    "MongoDB": [
        ("mongo_import", r"\b(?:mongoose|pymongo|mongodb)\b"),
        ("mongo_api", r"\b(?:Schema|model\s*\(|MongoClient|ObjectId|findOne|aggregate)\b"),
    ],
    "Docker": [
        ("docker_from", r"^\s*FROM\s+\S+",),
        ("docker_run", r"^\s*(?:RUN|COPY|CMD|ENTRYPOINT|WORKDIR|EXPOSE)\b"),
    ],
    "Kubernetes": [
        ("k8s_kind", r"kind\s*:\s*(?:Deployment|Service|Ingress|ConfigMap|Secret|StatefulSet|DaemonSet|Job|CronJob)"),
        ("k8s_api", r"apiVersion\s*:\s*(?:apps/v1|v1|networking\.k8s\.io/v1)"),
    ],
    "Testing": [
        ("test_def", r"\b(?:def\s+test_\w+|test\s*\(|it\s*\(|describe\s*\(|expect\s*\(|assert\w*\s*\(?)\b"),
        ("test_import", r"\b(?:pytest|unittest|jest|mocha|vitest|cypress|playwright|supertest|junit|testng|mockito)\b"),
    ],
}

# Phase 3: merge taxonomy-constrained API-usage patterns (Deep Learning,
# Scikit-learn, Spring Boot, Django/REST, SQL, MySQL, Redis, CI/CD) into the
# single reusable detection table. No technology is invented: every key must
# resolve through the canonical taxonomy (see usage_status.
# validate_patterns_against_taxonomy, exercised by tests).
for _phase3_skill, _phase3_patterns in _PHASE3_API_PATTERNS.items():
    _existing_ids = {pid for pid, _ in FRAMEWORK_USAGE_PATTERNS.get(_phase3_skill, [])}
    FRAMEWORK_USAGE_PATTERNS.setdefault(_phase3_skill, []).extend(
        (pid, rx) for pid, rx in _phase3_patterns if pid not in _existing_ids
    )

# Pattern ids matched on comment-stripped text WITH string literals intact,
# because the construct itself contains a quoted module specifier
# (e.g. ``from 'next/link'``). Every other pattern is matched on comment-
# AND string-stripped text so words inside string literals never count as
# API usage.
_STRING_SENSITIVE_PATTERN_IDS = frozenset({
    "next_import", "next_component", "node_require", "node_import",
    "express_route",
}) | set(_PHASE3_STRING_SENSITIVE_IDS)

_COMPILED_USAGE_PATTERNS: Dict[str, List[Tuple[str, "re.Pattern"]]] = {
    skill: [(pid, re.compile(rx, re.I | re.M)) for pid, rx in patterns]
    for skill, patterns in FRAMEWORK_USAGE_PATTERNS.items()
}


def detect_usage_patterns(text: str) -> Dict[str, List[str]]:
    """
    Detect framework-specific implementation patterns in a single file/text.

    Returns canonical skill -> sorted list of matched pattern ids. A single
    keyword mention is insufficient: patterns require API-shaped usage
    (hooks, components, routes, handlers, queries, model calls).

    False-positive guards: comments and docstrings are stripped before every
    match; string-literal contents are additionally stripped for all API
    patterns except import-style constructs that inherently live inside
    string literals (``require('express')``). Matching is local static
    inspection only -- repository code is never executed and never sent to
    external services.
    """
    if not text or not str(text).strip():
        return {}
    text_c = _strip_code_comments(str(text))
    if not text_c.strip():
        return {}
    try:
        text_cs = _strip_string_literals(text_c)
    except Exception:
        text_cs = text_c
    hits: Dict[str, List[str]] = {}
    for skill, compiled in _COMPILED_USAGE_PATTERNS.items():
        matched: List[str] = []
        for pid, rx in compiled:
            target = text_c if pid in _STRING_SENSITIVE_PATTERN_IDS else text_cs
            try:
                if rx.search(target):
                    matched.append(pid)
            except Exception:
                continue
        if matched:
            hits[skill] = sorted(set(matched))
    return hits


def merge_pattern_counts(
    acc: Dict[str, Dict[str, int]],
    file_hits: Dict[str, List[str]],
) -> Dict[str, Dict[str, int]]:
    """Accumulate per-file pattern hits into skill -> {pattern: file_count}."""
    for skill, pids in (file_hits or {}).items():
        bucket = acc.setdefault(skill, {})
        for pid in pids:
            bucket[pid] = bucket.get(pid, 0) + 1
    return acc


def _classify_framework_depth(
    *,
    has_dependency: bool,
    import_count: int = 0,
    usage_files: int = 0,
    distinct_patterns: int = 0,
    implementation_files: int = 0,
    has_tests_or_workflows: bool = False,
) -> int:
    """
    Layered depth for a framework/library skill.

    - L1 (mention) is handled by the documentation block, not here.
    - L2 (dependency): declared in a manifest but never imported/used.
    - L3 (implementation): imported or matched by API patterns in >=1 file.
    - L4 (substantial): used across multiple files / patterns, especially
      with tests or workflows corroborating a real project.

    Importing without a declared dependency still counts as implementation
    (vendored or transitive usage); a declared dependency without any import
    or pattern match stays at configuration level.
    """
    from .base import EvidenceDepth as _Depth

    has_usage = (import_count or 0) >= 1 or (distinct_patterns or 0) >= 1 or (usage_files or 0) >= 1
    if not has_usage:
        return _Depth.LEVEL_2_CONFIG if has_dependency else _Depth.LEVEL_1_MENTION

    multi_file = (usage_files or 0) >= 2 or (implementation_files or 0) >= 3
    multi_signal = (import_count or 0) >= 3 or (distinct_patterns or 0) >= 2
    corroborated = bool(has_tests_or_workflows)
    if (multi_file and multi_signal) or (multi_signal and corroborated) or ((usage_files or 0) >= 3):
        return _Depth.LEVEL_4_SUBSTANTIAL
    return _Depth.LEVEL_3_IMPLEMENTATION

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

    Commented-out imports are ignored: the text is comment-stripped first so
    a technology mentioned only in comments never counts as implementation.
    """
    tokens: Dict[str, int] = {}
    if not text:
        return tokens
    cleaned = _strip_code_comments(str(text))[:MAX_SOURCE_TEXT_CHARS]
    for pattern in IMPORT_PATTERNS:
        for match in pattern.findall(cleaned):
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
               ("readme_text", "config_text", "top_files", "import_tokens",
                "source_texts", "import_file_map")}
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
    settings = get_settings()
    token = settings.github_token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def _response_diagnostics(res: httpx.Response) -> Dict[str, Any]:
    remaining_header = res.headers.get("x-ratelimit-remaining")
    limit_header = res.headers.get("x-ratelimit-limit")
    reset_header = res.headers.get("x-ratelimit-reset")
    try:
        remaining = int(remaining_header) if remaining_header is not None else None
    except ValueError:
        remaining = None
    try:
        limit = int(limit_header) if limit_header is not None else None
    except ValueError:
        limit = None
    reset_time = None
    if reset_header and reset_header.isdigit():
        reset_time = datetime.fromtimestamp(int(reset_header), tz=timezone.utc).isoformat()
    api_message = ""
    try:
        body = res.json()
        if isinstance(body, dict):
            api_message = str(body.get("message") or "")[:160]
    except Exception:
        pass
    if res.status_code in (429,) or (res.status_code == 403 and remaining == 0):
        category = "rate_limited"
    elif res.status_code == 401:
        category = "authentication"
    elif res.status_code == 403:
        category = "forbidden"
    elif res.status_code == 404:
        category = "not_found"
    elif res.status_code >= 500:
        category = "upstream_error"
    else:
        category = "http_error"
    return {"status_code": res.status_code, "limit": limit, "remaining": remaining, "reset_time": reset_time, "category": category, "message": api_message}


def _safe_failure_message(owner: str, repo: str, diagnostics: Dict[str, Any]) -> str:
    category = diagnostics.get("category")
    target = f"'{owner}/{repo}'" if repo else f"'{owner}'"
    if category == "authentication":
        return f"GitHub authentication failed while inspecting {target}. Reconnect GitHub access or configure a valid server token."
    if category == "rate_limited":
        suffix = f" Reset at {diagnostics['reset_time']}." if diagnostics.get("reset_time") else ""
        return f"GitHub API rate limited (quota exhausted) while inspecting {target}.{suffix}"
    if category == "forbidden":
        return f"GitHub denied access while inspecting {target}; the token lacks permission or GitHub policy blocked the request."
    if category == "not_found":
        return f"GitHub resource {target} was not found or is not accessible."
    return f"GitHub returned HTTP {diagnostics.get('status_code', 'error')} while inspecting {target}."


async def _github_get(client: httpx.AsyncClient, url: str, *, headers: Optional[dict] = None, **kwargs: Any) -> httpx.Response:
    """GET with bounded retries for network/5xx/429 failures only."""
    hdrs = headers or _get_github_headers()
    track_quota = bool(kwargs.pop("track_quota", True))
    prior_quota = getattr(client, "_inaura_github_quota", None)
    if track_quota and isinstance(prior_quota, dict) and prior_quota.get("remaining") is not None and prior_quota["remaining"] < MIN_SAFE_REMAINING_REQUESTS:
        logger.warning(
            "GitHub quota is too low for another inspection request: remaining=%s limit=%s",
            prior_quota.get("remaining"), prior_quota.get("limit"),
        )
        return httpx.Response(
            403,
            json={"message": "GitHub API quota is too low for additional inspection requests"},
            headers={
                "x-ratelimit-remaining": str(prior_quota.get("remaining", 0)),
                "x-ratelimit-limit": str(prior_quota.get("limit", "")),
                "x-ratelimit-reset": str(prior_quota.get("reset_epoch", "")),
            },
            request=httpx.Request("GET", url),
        )
    last_error: Optional[Exception] = None
    for attempt in range(MAX_GITHUB_RETRIES + 1):
        try:
            response = await client.get(url, headers=hdrs, **kwargs)
            diagnostics = _response_diagnostics(response)
            if track_quota and diagnostics.get("remaining") is not None:
                try:
                    reset_epoch = int(response.headers.get("x-ratelimit-reset", "0") or 0)
                except ValueError:
                    reset_epoch = 0
                setattr(client, "_inaura_github_quota", {**diagnostics, "reset_epoch": reset_epoch})
                logger.debug(
                    "GitHub authentication: %s; rate limit remaining=%s/%s",
                    "configured" if "Authorization" in hdrs else "not configured",
                    diagnostics.get("remaining"), diagnostics.get("limit"),
                )
            retryable = response.status_code >= 500 or response.status_code == 429
            if not retryable or attempt >= MAX_GITHUB_RETRIES:
                return response
            retry_after = response.headers.get("retry-after")
            try:
                delay = min(3.0, max(0.1, float(retry_after))) if retry_after else 0.25 * (2 ** attempt)
            except ValueError:
                delay = 0.25 * (2 ** attempt)
            await asyncio.sleep(delay)
        except httpx.RequestError as exc:
            last_error = exc
            if attempt >= MAX_GITHUB_RETRIES:
                raise
            await asyncio.sleep(0.25 * (2 ** attempt))
    if last_error:
        raise last_error
    raise RuntimeError("GitHub request failed")


def _check_rate_limit(res: httpx.Response) -> Tuple[bool, int, Optional[str]]:
    """
    Check if response indicates rate limiting.
    Returns: (is_limited, remaining, reset_time_iso)
    """
    diagnostics = _response_diagnostics(res)
    remaining = diagnostics.get("remaining")
    return diagnostics["category"] == "rate_limited", int(remaining if remaining is not None else 100), diagnostics.get("reset_time")


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
                res = await _github_get(client, repo_url, headers=headers)
                if res.status_code == 404:
                    return VerificationResult(
                        status="failed",
                        message=f"GitHub repository '{owner}/{repo}' is private, deleted, or does not exist.",
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "repo": repo, "http_status": 404},
                        verified_at=verified_at,
                    )
                if res.status_code in (401, 403, 429):
                    diagnostics = _response_diagnostics(res)
                    return VerificationResult(
                        status="failed",
                        message=_safe_failure_message(owner, repo, diagnostics),
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "repo": repo, "http_status": res.status_code, "github_error": diagnostics},
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
                lang_res = await _github_get(client, f"{repo_url}/languages", headers=headers)
                if lang_res.status_code in (401, 403, 429):
                    diagnostics = _response_diagnostics(lang_res)
                    return VerificationResult(
                        status="failed",
                        message=_safe_failure_message(owner, repo, diagnostics),
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "repo": repo, "http_status": lang_res.status_code, "github_error": diagnostics},
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
                contents_res = await _github_get(client, f"{repo_url}/contents", headers=headers)
                if contents_res.status_code in (401, 403, 429):
                    diagnostics = _response_diagnostics(contents_res)
                    return VerificationResult(
                        status="failed",
                        message=_safe_failure_message(owner, repo, diagnostics),
                        provider=self.provider_name,
                        raw_metadata={"owner": owner, "repo": repo, "http_status": contents_res.status_code, "github_error": diagnostics},
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
                    pkg_res = await _github_get(client,
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
                    req_res = await _github_get(client,
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
                    wf_res = await _github_get(client, f"{repo_url}/contents/.github/workflows", headers=headers)
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
                tree_res = await _github_get(client,
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
                        # Vendored / generated / lock artifacts must never
                        # inflate implementation evidence: skip them before
                        # counting language footprints.
                        _skippable = _is_skippable_path(low)
                        if not _skippable:
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
                    raw_res = await _github_get(client,
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
                    r = await _github_get(client,
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
            # Per-file provenance for layered depth grading:
            # which files imported which tokens, and which files matched
            # framework-specific implementation patterns.
            import_file_map: Dict[str, List[str]] = {}
            usage_pattern_counts: Dict[str, Dict[str, int]] = {}
            usage_pattern_files: Dict[str, Set[str]] = {}
            # Phase 10: error-handling constructs per sampled source file
            # (separate practices dimension; never mixed into skill signals).
            error_indicator_counts: Dict[str, int] = {}
            error_indicator_files: Dict[str, List[str]] = {}
            for path in select_source_files(source_candidates, MAX_SOURCE_FILES_PER_REPO):
                text = await _fetch_content(path, MAX_SOURCE_TEXT_CHARS)
                if not text:
                    continue
                sampled_source_files.append(path)
                for token, count in extract_import_tokens(text).items():
                    import_tokens[token] = import_tokens.get(token, 0) + count
                    lst = import_file_map.setdefault(token, [])
                    if path not in lst:
                        lst.append(path)
                try:
                    file_hits = detect_usage_patterns(text)
                except Exception:
                    file_hits = {}
                if file_hits:
                    merge_pattern_counts(usage_pattern_counts, file_hits)
                    for skill in file_hits:
                        usage_pattern_files.setdefault(skill, set()).add(path)
                try:
                    err_hits = _detect_error_handling(text)
                except Exception:
                    err_hits = {}
                if err_hits:
                    _merge_error_counts(
                        error_indicator_counts, error_indicator_files, err_hits, path
                    )

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
                "import_file_map": {k: list(v) for k, v in import_file_map.items()},
                "usage_patterns": {k: dict(v) for k, v in usage_pattern_counts.items()},
                "usage_files": {k: sorted(v) for k, v in usage_pattern_files.items()},
                "error_indicators": dict(error_indicator_counts),
                "error_files": {k: sorted(v) for k, v in error_indicator_files.items()},
                "files_analyzed": ([readme_path] if readme_path and readme_text else [])
                + list(sampled_source_files)
                + list(sampled_config_files),
                "implementation_files": list(sampled_source_files),
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
            # Repository discovery may return a partial page before quota is
            # exhausted. Do not let that discovery response prevent the
            # already-discovered repositories from being classified/inspected;
            # deep-inspection requests still share the quota guard.
            res = await _github_get(client, url, headers=hdrs, params=params, track_quota=False)
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
            cache_key = "github:" + ":".join([
                full_name.lower(),
                str(repo_meta.get("pushed_at") or repo_meta.get("updated_at") or ""),
                str(repo_meta.get("default_branch") or "main"),
            ])

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

            cached = _INSPECTION_CACHE.get(cache_key)
            if cached:
                cached_summary, cached_signals = cached
                return {**cached_summary, "cache": "revision"}, list(cached_signals), None

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
                        _INSPECTION_CACHE[cache_key] = (summary, list(result.signals))
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
                            "error_category": (result.raw_metadata.get("github_error") or {}).get("category"),
                            "inspection": compact_inspection(result.raw_metadata),
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
                        "error_category": "network_or_internal",
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
        - Strongest technology usage status (mentioned < ... < substantial)
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

            # Build provenance repository list. Each entry traces the skill
            # back to its repository, relevant files, depth, and reason --
            # paths and labels only, never source contents.
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
                    "files": list((s.metadata or {}).get("relevant_files") or [])[:5],
                    "usage_status": (s.metadata or {}).get("usage_status"),
                    "file_importance": (s.metadata or {}).get("file_importance"),
                    "reason": s.reason,
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

            # Determine the winning bucket that defines the source-level accepted
            # evidence. Per spec: owned active > owned (archived) > fork-only.
            # Source-level aggregates (relevant_files, patterns, usage_status,
            # file_importance, evidence_count, evidence_kinds) are derived ONLY
            # from this bucket so a fork's substantial files never inflate a
            # source whose final accepted depth is Mention.
            if active_owned:
                _winning_items = active_owned
            elif owned_items:
                _winning_items = owned_items
            else:
                _winning_items = fork_items

            # Preserve which kinds of repository evidence backed this skill
            # (documentation / configuration / dependency / source usage) – but
            # only from the winning bucket (accepted evidence).
            evidence_kinds = sorted(
                {
                    str(s.metadata.get("evidence_kind"))
                    for s, _ in _winning_items
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

            # Phase 3: propagate the strongest per-repository usage status
            # within the winning bucket only (no cross-bucket leakage).
            try:
                _status_rank = {str(s): i for i, s in enumerate(_STATUS_ORDER)}
                _seen_statuses = [
                    str((s.metadata or {}).get("usage_status") or "").lower()
                    for s, _ in _winning_items
                    if str((s.metadata or {}).get("usage_status") or "").lower() in _status_rank
                ]
                if _seen_statuses:
                    _raw_status = max(_seen_statuses, key=lambda s: _status_rank[s])
                    metadata["usage_status"] = _coerce_status_to_depth(_raw_status, final_depth)
                else:
                    _agg_depth = int(final_depth)
                    metadata["usage_status"] = (
                        _US_SUBSTANTIAL if _agg_depth >= 4
                        else (_US_DECLARED if _agg_depth <= 2 else _US_IMPORTED)
                    )
            except Exception:
                pass

            # Phase 4: traceability provenance on the aggregated signal – union
            # only from the winning bucket (accepted evidence), plus profile
            # URL and observation timestamp. Still one signal per skill.
            try:
                metadata.setdefault("provider", self.provider_name)
                metadata.setdefault("source_url", f"https://github.com/{owner}")
                try:
                    if verified_at is not None:
                        metadata.setdefault("observed_at", verified_at.isoformat())
                except Exception:
                    pass
                _agg_files: List[str] = []
                for _s, _ in _winning_items:
                    for _f in (list((_s.metadata or {}).get("relevant_files") or [])[:6]):
                        if _f not in _agg_files:
                            _agg_files.append(str(_f))
                        if len(_agg_files) >= 10:
                            break
                    if len(_agg_files) >= 10:
                        break
                # Coherence: if final depth is Mention, do not expose impl files
                if int(final_depth) <= 1:
                    # Keep only documentation-like files for L1
                    _filtered = [f for f in _agg_files if f.lower().endswith((".md", ".txt", ".rst")) or "readme" in f.lower()]
                    metadata["relevant_files"] = _filtered[:3] if _filtered else _agg_files[:3]
                    # L1 must not claim patterns
                    metadata["detected_usage_patterns"] = []
                else:
                    metadata["relevant_files"] = _agg_files
                    _agg_patterns: List[str] = []
                    for _s, _ in _winning_items:
                        for _p in (list((_s.metadata or {}).get("detected_usage_patterns") or [])[:6]):
                            if _p not in _agg_patterns:
                                _agg_patterns.append(str(_p))
                            if len(_agg_patterns) >= 8:
                                break
                        if len(_agg_patterns) >= 8:
                            break
                    metadata["detected_usage_patterns"] = _agg_patterns
                _imp_rank = ["ignore", "low", "medium", "high", "very_high"]
                _seen_imp = [
                    str((s.metadata or {}).get("file_importance") or "").lower()
                    for s, _ in _winning_items
                    if str((s.metadata or {}).get("file_importance") or "").lower() in _imp_rank
                ]
                if _seen_imp:
                    _raw_imp = max(_seen_imp, key=lambda v: _imp_rank.index(v))
                    metadata["file_importance"] = _coerce_importance_to_depth(_raw_imp, final_depth)
                else:
                    _agg_d = int(final_depth)
                    metadata["file_importance"] = (
                        "high" if _agg_d >= 3
                        else ("medium" if _agg_d == 2 else ("low" if _agg_d == 1 else "ignore"))
                    )
                # evidence_count reflects accepted (winning) evidence, not total
                metadata["evidence_count"] = int(len(_winning_items))
                # keep original total for audit trail
                metadata["total_repo_count"] = int(total_repos)
            except Exception:
                pass

            # Final coherence enforcement for aggregated signal: ensure usage_status,
            # file_importance and patterns do not outrank final_depth.
            # Config-level (L2) infra patterns (Docker/Kubernetes/CI) are valid
            # so we only clear impl patterns for pure documentation (L1).
            try:
                if "usage_status" in metadata:
                    metadata["usage_status"] = _coerce_status_to_depth(str(metadata.get("usage_status") or ""), final_depth)
                    if int(final_depth) <= 1 and metadata.get("detected_usage_patterns"):
                        metadata["detected_usage_patterns"] = []
                if "file_importance" in metadata:
                    metadata["file_importance"] = _coerce_importance_to_depth(str(metadata.get("file_importance") or ""), final_depth)
            except Exception:
                pass

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
        if "Authorization" not in headers:
            logger.warning("GitHub token is not configured; requests are unauthenticated.")
        else:
            logger.info("GitHub authentication: configured")

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
                    res = await _github_get(client, profile_url, headers=headers)
                    if res.status_code == 404:
                        return VerificationResult(
                            status="failed",
                            message=f"GitHub user '{owner}' does not exist.",
                            provider=self.provider_name,
                            raw_metadata={"owner": owner, "http_status": 404},
                            verified_at=verified_at,
                        )
                    if res.status_code in (401, 403, 429):
                        diagnostics = _response_diagnostics(res)
                        return VerificationResult(
                            status="failed",
                            message=_safe_failure_message(owner, "", diagnostics),
                            provider=self.provider_name,
                            raw_metadata={"owner": owner, "http_status": res.status_code, "github_error": diagnostics},
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
                    "deep_inspection_status": "complete" if repos_failed == 0 and repos_skipped == 0 else ("partial" if repos_inspected > 0 else "failed"),
                    "github_authentication_configured": "Authorization" in headers,
                    "rate_limit_diagnostics": next((
                        (r.get("inspection") or {}).get("github_error")
                        for r in inspected_repos
                        if isinstance((r.get("inspection") or {}).get("github_error"), dict)
                    ), None),
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

                # Phase 10: profile-level practices union across inspected
                # repositories (best observed score per dimension). Skill
                # signals above are unaffected.
                try:
                    _practice_items = [
                        (str(r.get("full_name") or r.get("name") or "repository"),
                         (r.get("inspection") or {}).get("engineering_practices"))
                        for r in inspected_repos
                        if r.get("status") == "inspected"
                        and isinstance((r.get("inspection") or {}).get("engineering_practices"), dict)
                    ]
                    if _practice_items:
                        raw_metadata["engineering_practices"] = _aggregate_practices(_practice_items)
                except Exception:
                    pass

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

        # --- Layered implementation evidence (incremental depth grading) ---
        # Dependency declarations, imports, and framework-specific API usage
        # are tracked separately so depth reflects demonstration, not mention:
        #   L1 documentation mention < L2 dependency/config
        #   < L3 import/usage in >=1 file < L4 substantial multi-file usage.
        # `usage_patterns` / `usage_files` come from live content inspection;
        # mock fixtures without them fall back to import counts + sampled files.
        _dep_skills_early: Dict[str, str] = dependency_skill_names(all_deps)
        _usage_counts_early: Dict[str, int] = import_skill_counts(import_tokens)
        _usage_patterns_raw = dict(inspection.get("usage_patterns") or {})
        _usage_files_raw = {str(k): list(v or []) for k, v in (inspection.get("usage_files") or {}).items()}
        _import_file_map_raw = inspection.get("import_file_map") or {}

        # --- Phase 3: infrastructure API usage from configuration text ---
        # Dockerfile / Kubernetes manifest / CI workflow bodies are scanned
        # locally (never executed, never sent externally) for API-shaped
        # constructs. Only infra skills are accepted here; application skills
        # require source-file evidence. Merged additively into the same
        # pattern/file maps so depth, importance, and status share one view.
        try:
            _cfg_text = str(config_text or "")
            if _cfg_text.strip() and sampled_config_files:
                _cfg_hits = detect_usage_patterns(_cfg_text)
                for _cfg_skill in ("Docker", "Kubernetes", "CI/CD"):
                    _cfg_pids = _cfg_hits.get(_cfg_skill) or []
                    if not _cfg_pids:
                        continue
                    _existing = _usage_patterns_raw.get(_cfg_skill)
                    if isinstance(_existing, dict):
                        for _pid in _cfg_pids:
                            _existing[_pid] = int(_existing.get(_pid, 0) or 0) + 1
                    elif isinstance(_existing, list):
                        _usage_patterns_raw[_cfg_skill] = sorted(set(list(_existing) + list(_cfg_pids)))
                    else:
                        _usage_patterns_raw[_cfg_skill] = {_pid: 1 for _pid in _cfg_pids}
                    _merged_cfg_files = sorted(set(
                        list(_usage_files_raw.get(_cfg_skill) or [])
                        + list(sampled_config_files[:3])
                    ))[:6]
                    _usage_files_raw[_cfg_skill] = _merged_cfg_files
        except Exception:
            pass

        def _fw_evidence(skill: str) -> Tuple[int, int, int, List[str]]:
            """Return (import_count, distinct_patterns, usage_file_count, usage_files) for a skill."""
            canonical = normalize_skill(skill) or skill
            import_count = int(_usage_counts_early.get(canonical, 0))
            pats = _usage_patterns_raw.get(canonical) or _usage_patterns_raw.get(skill) or {}
            if isinstance(pats, dict):
                distinct = len(pats)
            elif isinstance(pats, (list, tuple, set)):
                distinct = len(set(pats))
            else:
                distinct = 0
            ufiles = _usage_files_raw.get(canonical) or _usage_files_raw.get(skill) or []
            if isinstance(ufiles, (set, tuple)):
                ufiles = sorted(ufiles)
            ufiles = list(ufiles or [])
            if import_count >= 1 and not ufiles:
                # Mock/backfill: imports prove >=1 implementation file; do not
                # invent multi-file spread without per-file provenance.
                ufiles = list(sampled_source_files[:1]) if sampled_source_files else []
            return import_count, distinct, len(ufiles), ufiles

        def _relevant_files_for_skill(skill: str, fallback: Optional[List[str]] = None) -> List[str]:
            canonical = normalize_skill(skill) or skill
            ufiles = _usage_files_raw.get(canonical) or _usage_files_raw.get(skill) or []
            if ufiles:
                return sorted(set(str(f) for f in ufiles))[:6]
            # Map import tokens back to files for this skill
            rel: List[str] = []
            for tok, files in (_import_file_map_raw or {}).items():
                try:
                    for cand in _import_token_candidates(str(tok)):
                        if (normalize_skill(cand) or "") == canonical:
                            rel.extend(str(f) for f in (files or []))
                            break
                except Exception:
                    continue
            if rel:
                return sorted(set(rel))[:6]
            if _usage_counts_early.get(canonical, 0) >= 1 and sampled_source_files:
                return list(sampled_source_files[:3])
            return list(fallback or [])[:6]

        def _detected_patterns_for_skill(skill: str) -> List[str]:
            canonical = normalize_skill(skill) or skill
            pats = _usage_patterns_raw.get(canonical) or _usage_patterns_raw.get(skill) or {}
            if isinstance(pats, dict):
                return sorted(str(k) for k in pats.keys())
            if isinstance(pats, (list, tuple, set)):
                return sorted(str(p) for p in pats)
            return []

        # --- Phase 2: deterministic file-importance weighting ---
        # Importance is separate from the skill score: it caps which evidence
        # depth a file may support (IGNORE->L0, LOW->L1, MEDIUM->L2, HIGH->L3,
        # VERY_HIGH->L4) and is recorded as metadata. Signal strengths stay
        # depth-mapped so EvidenceDepth compatibility is preserved, and the
        # one-signal-per-skill rule prevents double counting.
        # Per-file evidence hints combine structure with actual detection:
        # a file counts as having imports/patterns only when the sampled
        # content maps prove it (never from filename or keyword frequency).
        _comments_only_files = {
            str(f).replace("\\", "/").lower()
            for f in (inspection.get("comments_only_files") or [])
        }
        _per_file_import_counts: Dict[str, int] = {}
        for _tok, _files in (_import_file_map_raw or {}).items():
            for _f in (_files or []):
                _key = str(_f).replace("\\", "/")
                _per_file_import_counts[_key] = _per_file_import_counts.get(_key, 0) + 1
        # Invert skill->files usage map to file->pattern counts.
        _per_file_pattern_counts: Dict[str, int] = {}
        for _skill_key, _files in (_usage_files_raw or {}).items():
            for _f in (_files or []):
                _key = str(_f).replace("\\", "/")
                _per_file_pattern_counts[_key] = _per_file_pattern_counts.get(_key, 0) + 1

        def _evidence_hint_for_file(path: str) -> Dict[str, Any]:
            key = str(path).replace("\\", "/")
            low_key = key.lower()
            imp = 0
            for tok_key, cnt in _per_file_import_counts.items():
                if tok_key == key or tok_key.lower() == low_key:
                    imp += int(cnt or 0)
            pat = 0
            for f_key, cnt in _per_file_pattern_counts.items():
                if f_key == key or f_key.lower() == low_key:
                    pat += int(cnt or 0)
            # Fallback for mock inspections without per-file maps: if global
            # imports exist and this is a sampled source file, attribute a
            # single import hint only when there is exactly one sampled file
            # (avoids inventing multi-file spread).
            if imp == 0 and pat == 0 and key in list(sampled_source_files):
                if len(sampled_source_files) == 1 and sum(_usage_counts_early.values()) >= 1:
                    imp = 1
            return {
                "has_imports": imp > 0,
                "import_count": imp,
                "has_patterns": pat > 0,
                "pattern_count": pat,
                "comments_only": low_key in _comments_only_files,
            }

        # Candidate files for importance: sampled content plus tree-listed
        # files and root manifests (so mock inspections without sampled lists
        # still classify dependency manifests as MEDIUM, not IGNORE).
        # IGNORE files are kept in the map (tier 0) so caps can suppress them.
        _importance_candidate_files: List[str] = []
        for _cand in (
            ([inspection.get("readme_path")] if inspection.get("readme_path") else [])
            + list(sampled_source_files)
            + list(sampled_config_files)
            + [str(f) for f in (inspection.get("top_files") or [])]
            + [str(f) for f in (inspection.get("root_files") or [])]
        ):
            if _cand and str(_cand) not in _importance_candidate_files:
                _importance_candidate_files.append(str(_cand))
        _file_tiers: Dict[str, int] = {}
        for _cand in _importance_candidate_files[:40]:
            try:
                _file_tiers[_cand] = _classify_file_importance(
                    _cand, size=None, evidence=_evidence_hint_for_file(_cand)
                )
            except Exception:
                _file_tiers[_cand] = _FI_LOW
        # Repository aggregate for VERY_HIGH gating.
        try:
            _all_pattern_files = set()
            for _files in (_usage_files_raw or {}).values():
                for _f in (_files or []):
                    _all_pattern_files.add(str(_f))
            _total_distinct_patterns = sum(
                len(v) if isinstance(v, dict) else len(set(v or []))
                for v in (_usage_patterns_raw or {}).values()
            )
            _max_usage_files = 0
            for _files in (_usage_files_raw or {}).values():
                _max_usage_files = max(_max_usage_files, len(list(_files or [])))
            # Fallback when per-file maps are absent but global usage exists.
            if not _all_pattern_files and sum(_usage_counts_early.values()) >= 1:
                _max_usage_files = max(_max_usage_files, min(len(sampled_source_files), 1))
            _repo_importance = _assess_repo_importance(
                _file_tiers,
                {
                    "has_tests": bool(has_tests),
                    "has_workflows": bool(has_workflows),
                    "pattern_files": len(_all_pattern_files),
                    "distinct_patterns": _total_distinct_patterns,
                    "usage_files": _max_usage_files,
                },
            )
        except Exception:
            _repo_importance = {"level": _FI_HIGH, "label": "high", "reason": "", "counts": {}}

        def _tier_of_file(path: str) -> int:
            try:
                if path in _file_tiers:
                    return int(_file_tiers[path])
                return int(_classify_file_importance(str(path), evidence=_evidence_hint_for_file(str(path))))
            except Exception:
                return _FI_LOW

        def _cap_depth_by_importance(
            proposed: int, relevant: Optional[List[str]]
        ) -> Tuple[int, int, str]:
            """
            Cap a proposed EvidenceDepth by file importance (upper bound only,
            never upgrades). Returns (capped_depth, max_tier, tier_label).
            Empty/unknown file lists do not cap (preserves backward compat
            for inspections without file provenance); explicitly LOW/IGNORE
            lists do cap.
            """
            try:
                prop = int(proposed)
            except (TypeError, ValueError):
                prop = 1
            rel = [str(f) for f in (relevant or []) if str(f)]
            if not rel:
                return prop, int(_repo_importance.get("level", _FI_HIGH)), str(
                    _repo_importance.get("label", "high")
                )
            tiers = [_tier_of_file(f) for f in rel]
            if all(t == _FI_IGNORE for t in tiers):
                return 0, _FI_IGNORE, "ignore"
            known = [t for t in tiers]
            max_tier = max(known) if known else _FI_LOW
            cap = _max_depth_for_tier(max_tier)
            # Composition of multiple MEDIUM configs (Dockerfile + compose,
            # workflows + CI) corroborates L3 configuration evidence without
            # any single MEDIUM file claiming implementation alone.
            if max_tier == _FI_MEDIUM and int(cap) < int(prop) <= 3:
                medium_relevant = sum(1 for t in tiers if t >= _FI_MEDIUM)
                if medium_relevant >= 2:
                    return int(prop), _FI_MEDIUM, _importance_label(_FI_MEDIUM)
            # L4 requires substantial multi-file evidence: repository VERY_HIGH
            # aggregate or a VERY_HIGH file. A single HIGH file stays L3.
            # Multi-file HIGH usage corroborated at repo level earns VERY_HIGH.
            if prop >= 4:
                repo_level = int(_repo_importance.get("level", _FI_HIGH))
                has_very_high_file = any(t >= _FI_VERY_HIGH for t in tiers)
                high_relevant = sum(1 for t in tiers if t >= _FI_HIGH)
                if has_very_high_file:
                    return prop, _FI_VERY_HIGH, _importance_label(_FI_VERY_HIGH)
                if repo_level >= _FI_VERY_HIGH and high_relevant >= 2:
                    return prop, _FI_VERY_HIGH, _importance_label(_FI_VERY_HIGH)
                if high_relevant < 2:
                    return min(prop, 3), max_tier, _importance_label(max_tier)
            return min(prop, int(cap)), max_tier, _importance_label(max_tier)

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
            # Phase 2: file importance caps depth (never upgrades, never
            # double-counts — still one signal per skill per repository).
            # Default to the repository aggregate (not HIGH) so manifest-only
            # inspections without file provenance stay MEDIUM, not HIGH.
            try:
                _repo_level_default = int(_repo_importance.get("level", _FI_MEDIUM))
                _repo_label_default = str(_repo_importance.get("label", "medium"))
            except Exception:
                _repo_level_default, _repo_label_default = _FI_MEDIUM, "medium"
            _rel_for_cap = None
            try:
                _rel_for_cap = (dict(meta or {}).get("relevant_files")
                                or dict(meta or {}).get("config_files")
                                or dict(meta or {}).get("source_files_inspected"))
            except Exception:
                _rel_for_cap = None
            _cap_tier = _repo_level_default
            _cap_label = _repo_label_default
            try:
                if _rel_for_cap:
                    final_depth, _cap_tier, _cap_label = _cap_depth_by_importance(
                        final_depth, list(_rel_for_cap)[:6]
                    )
                    if int(final_depth) <= 0:
                        # All relevant files IGNORE (vendor/generated): no evidence.
                        return
            except Exception:
                pass
            raw_strength = EvidenceDepth.get_strength_for_depth(final_depth)
            final_strength = round(min(0.55, raw_strength * 0.70), 2) if is_fork else raw_strength
            final_reason = f"[Forked Repository] {reason_text}" if is_fork else reason_text
            metadata = dict(meta or {})
            # Required Phase 2 metadata (additive; never overwrites explicit).
            metadata.setdefault("file_importance", _cap_label)
            try:
                metadata.setdefault("file_importance_score", round(float(_importance_weight(_cap_tier)), 3))
            except Exception:
                metadata.setdefault("file_importance_score", 0.5)
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

        # 1. Docker Detection (configuration; Dockerfile+compose together is stronger)
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
                {
                    "files": details,
                    "relevant_files": list(sampled_config_files[:3]) or details,
                    "detected_usage_patterns": _detected_patterns_for_skill("Docker"),
                    "evidence_kind": "configuration",
                },
            )

        # 2. CI/CD & GitHub Actions Detection
        if has_workflows or any(".github" in f for f in all_files):
            depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION if has_workflows else EvidenceDepth.LEVEL_2_CONFIG
            _add_signal(
                "GitHub Actions",
                depth,
                f"Repository '{repo_name}' contains automated CI/CD workflow definitions (.github/workflows).",
                {
                    "has_workflows": has_workflows,
                    "relevant_files": list(sampled_config_files[:3]),
                    "evidence_kind": "configuration",
                },
            )
            _add_signal(
                "CI/CD",
                depth,
                f"Repository '{repo_name}' configures automated integration/deployment pipelines.",
                {"evidence_kind": "configuration"},
            )

        # 3. JavaScript / React / Next.js / Express / Node.js Detection.
        # Layered grading (taxonomy-driven, no substring false positives):
        #   dependency declared but never imported/used -> LEVEL_2 (config)
        #   imported or matched by API patterns in >=1 file -> LEVEL_3
        #   used across multiple files/patterns (+ tests/workflows) -> LEVEL_4
        # A README mention alone never reaches this block (handled as L1 docs).
        has_js_ts = "JavaScript" in languages or "TypeScript" in languages or "package.json" in all_files or bool(pkg_deps)
        if has_js_ts:
            # React (exact taxonomy resolution avoids 'interaction' style false positives)
            if "React" in _dep_skills_early:
                _imp, _dist, _ufiles_n, _ufiles = _fw_evidence("React")
                _depth = _classify_framework_depth(
                    has_dependency=True,
                    import_count=_imp,
                    usage_files=_ufiles_n,
                    distinct_patterns=_dist,
                    implementation_files=len(sampled_source_files),
                    has_tests_or_workflows=bool(has_tests or has_workflows),
                )
                if _depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION:
                    _kind = "implementation" if _depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION and (_imp >= 1 or _dist >= 1) else "dependency_manifest"
                    # Substantial phrasing only when multi-file usage is proven
                    if _depth >= EvidenceDepth.LEVEL_4_SUBSTANTIAL:
                        _reason = (
                            f"Repository '{repo_name}' substantially implements React "
                            f"({_imp} import reference(s), {len(_detected_patterns_for_skill('React'))} usage pattern(s) "
                            f"across {max(_ufiles_n, 1)} file(s){' with tests/workflows' if (has_tests or has_workflows) else ''})."
                        )
                        _kind = "implementation"
                    elif _imp >= 1 or _dist >= 1:
                        _reason = (
                            f"Repository '{repo_name}' imports/uses React in implementation "
                            f"({_imp} reference(s){', patterns: ' + ', '.join(_detected_patterns_for_skill('React')[:3]) if _detected_patterns_for_skill('React') else ''})."
                        )
                        _kind = "source_usage"
                    else:
                        _reason = f"Repository '{repo_name}' declares React in its dependency manifest without observed imports."
                        _kind = "dependency_manifest"
                else:
                    _reason = f"Repository '{repo_name}' declares React in its dependency manifest without observed imports."
                    _kind = "dependency_manifest"
                _add_signal(
                    "React",
                    _depth,
                    _reason,
                    {
                        "package_json": True,
                        "dependency": _dep_skills_early.get("React", "react"),
                        "usage_count": _imp,
                        "detected_usage_patterns": _detected_patterns_for_skill("React"),
                        "relevant_files": _relevant_files_for_skill("React", sampled_source_files),
                        "evidence_kind": _kind,
                    },
                )

            # Next.js
            if "Next.js" in _dep_skills_early:
                _imp, _dist, _ufiles_n, _ufiles = _fw_evidence("Next.js")
                _depth = _classify_framework_depth(
                    has_dependency=True,
                    import_count=_imp,
                    usage_files=_ufiles_n,
                    distinct_patterns=_dist,
                    implementation_files=len(sampled_source_files),
                    has_tests_or_workflows=bool(has_tests or has_workflows),
                )
                _kind = "source_usage" if (_imp >= 1 or _dist >= 1) else "dependency_manifest"
                if _depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION and _kind == "source_usage":
                    _reason = f"Repository '{repo_name}' imports/uses Next.js in implementation ({_imp} reference(s))."
                else:
                    _reason = f"Repository '{repo_name}' declares Next.js in its dependency manifest without observed imports."
                _add_signal(
                    "Next.js",
                    _depth,
                    _reason,
                    {
                        "dependency": _dep_skills_early.get("Next.js", "next"),
                        "usage_count": _imp,
                        "detected_usage_patterns": _detected_patterns_for_skill("Next.js"),
                        "relevant_files": _relevant_files_for_skill("Next.js", sampled_source_files),
                        "evidence_kind": _kind,
                    },
                )

            # Express
            if "Express" in _dep_skills_early:
                _imp, _dist, _ufiles_n, _ufiles = _fw_evidence("Express")
                _depth = _classify_framework_depth(
                    has_dependency=True,
                    import_count=_imp,
                    usage_files=_ufiles_n,
                    distinct_patterns=_dist,
                    implementation_files=len(sampled_source_files),
                    has_tests_or_workflows=bool(has_tests or has_workflows),
                )
                _kind = "source_usage" if (_imp >= 1 or _dist >= 1) else "dependency_manifest"
                if _kind == "source_usage":
                    _reason = f"Repository '{repo_name}' imports/uses Express in server implementation ({_imp} reference(s))."
                else:
                    _reason = f"Repository '{repo_name}' declares Express in its dependency manifest without observed server usage."
                _add_signal(
                    "Express",
                    _depth,
                    _reason,
                    {
                        "dependency": _dep_skills_early.get("Express", "express"),
                        "usage_count": _imp,
                        "detected_usage_patterns": _detected_patterns_for_skill("Express"),
                        "relevant_files": _relevant_files_for_skill("Express", sampled_source_files),
                        "evidence_kind": _kind,
                    },
                )

            # Node.js (runtime manifest; implementation requires JS/TS sources or usage)
            if "package.json" in all_files or pkg_deps or "Node.js" in _dep_skills_early:
                _imp_n, _dist_n, _ufiles_n_n, _ = _fw_evidence("Node.js")
                _js_files = sum(c for ext, c in ext_file_counts.items() if EXTENSION_SKILL_MAP.get(ext) in ("JavaScript", "TypeScript"))
                if _js_files >= 1 or _imp_n >= 1 or _dist_n >= 1 or _usage_counts_early.get("Express", 0) >= 1 or _usage_counts_early.get("React", 0) >= 1:
                    _depth_n = EvidenceDepth.LEVEL_3_IMPLEMENTATION
                    # Substantial Node service: multiple sources + tests/workflows
                    if _js_files >= 5 and (has_tests or has_workflows):
                        _depth_n = EvidenceDepth.LEVEL_4_SUBSTANTIAL
                    _reason_n = f"Repository '{repo_name}' implements a Node.js service (package manifest with {_js_files} JS/TS source file(s))."
                    _kind_n = "implementation"
                else:
                    _depth_n = EvidenceDepth.LEVEL_2_CONFIG
                    _reason_n = f"Repository '{repo_name}' contains a Node.js package manifest without observed JS/TS implementation files."
                    _kind_n = "dependency_manifest"
                _add_signal(
                    "Node.js",
                    _depth_n,
                    _reason_n,
                    {
                        "source_file_count": _js_files,
                        "relevant_files": _relevant_files_for_skill("Node.js", sampled_source_files),
                        "evidence_kind": _kind_n,
                    },
                )

        # TypeScript Detection: layered (manifest/config alone is L2; sources/usage raise to L3/L4).
        _ts_has_dep = ("TypeScript" in _dep_skills_early) or ("tsconfig.json" in all_files)
        _ts_bytes = 0
        if isinstance(languages, dict):
            _ts_bytes = int(languages.get("TypeScript", 0) or 0)
        _ts_files = sum(c for ext, c in ext_file_counts.items() if EXTENSION_SKILL_MAP.get(ext) == "TypeScript")
        if _ts_has_dep or "TypeScript" in languages or _ts_files > 0:
            _imp_t, _dist_t, _ufiles_n_t, _ = _fw_evidence("TypeScript")
            if _ts_files >= 10 and (has_tests or has_workflows or _ts_has_dep):
                _ts_depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL
                _ts_detail = f"substantial TypeScript implementation ({_ts_files} source files, {_ts_bytes} bytes)"
                _ts_kind = "implementation"
            elif _ts_files >= 1 or _imp_t >= 1 or _dist_t >= 1 or _ts_bytes >= 5000:
                _ts_depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION
                _ts_detail = f"TypeScript implementation ({_ts_files} source files, {_ts_bytes} bytes)"
                _ts_kind = "implementation" if (_ts_files >= 1 or _imp_t >= 1) else "dependency_manifest"
            else:
                _ts_depth = EvidenceDepth.LEVEL_2_CONFIG
                _ts_detail = "TypeScript configuration without observed TypeScript sources"
                _ts_kind = "dependency_manifest"
            _add_signal(
                "TypeScript",
                _ts_depth,
                f"Repository '{repo_name}' {_ts_detail}.",
                {
                    "source_file_count": _ts_files,
                    "language_bytes": _ts_bytes,
                    "usage_count": _imp_t,
                    "detected_usage_patterns": _detected_patterns_for_skill("TypeScript"),
                    "relevant_files": _relevant_files_for_skill("TypeScript", sampled_source_files),
                    "evidence_kind": _ts_kind,
                },
            )

        # 4. Python & Python Ecosystem Detection (layered).
        # Manifest alone without sources is configuration-level; sources,
        # imports and tests raise to implementation / substantial.
        has_py_manifest = any(f in root_files for f in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile"))
        is_python_repo = "Python" in languages or has_py_manifest
        if is_python_repo:
            py_bytes = languages.get("Python", 0) if isinstance(languages, dict) else 0
            if not isinstance(py_bytes, (int, float)):
                py_bytes = 0
            py_files = sum(c for ext, c in ext_file_counts.items() if EXTENSION_SKILL_MAP.get(ext) == "Python")
            if py_files == 0 and all_files_lower:
                # Fixtures listing sources via top_files without ext counts
                py_files = sum(1 for f in all_files_lower if f.endswith(".py") and not _is_skippable_path(f))
            _py_substantial_legacy = (
                (has_tests or has_dockerfile)
                and isinstance(py_bytes, (int, float)) and py_bytes > 5000
            )
            if (py_files >= 10 and (has_py_manifest or has_tests or has_workflows or has_dockerfile)) or (
                _py_substantial_legacy and (py_files >= 2 or py_bytes >= 8000)
            ):
                py_depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL
                py_detail = f"substantial Python implementation ({py_files} source files, {int(py_bytes)} bytes)"
                py_kind = "implementation"
            elif (
                py_files >= 3
                or (py_files >= 1 and has_py_manifest)
                or (isinstance(py_bytes, (int, float)) and py_bytes >= 5000 and has_py_manifest)
                or (isinstance(py_bytes, (int, float)) and py_bytes >= 20000)
                or (not tree_scanned and py_files == 0 and ("Python" in languages or has_py_manifest))
            ):
                py_depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION
                py_detail = (
                    f"verified Python implementation ({py_files} Python source files, "
                    f"{int(py_bytes)} bytes of Python"
                    f"{', build manifest present' if has_py_manifest else ''})"
                )
                py_kind = "implementation"
            else:
                py_depth = EvidenceDepth.LEVEL_2_CONFIG
                py_detail = (
                    f"limited Python footprint ({int(py_bytes)} bytes of Python, "
                    f"{py_files} Python source files"
                    f"{', build manifest present' if has_py_manifest else ', no build manifest'})"
                )
                py_kind = "dependency_manifest"
            _add_signal(
                "Python",
                py_depth,
                f"Repository '{repo_name}' {py_detail}.",
                {
                    "source_file_count": py_files,
                    "language_bytes": int(py_bytes),
                    "has_build_manifest": has_py_manifest,
                    "relevant_files": _relevant_files_for_skill("Python", sampled_source_files),
                    "evidence_kind": py_kind,
                },
            )

            # Python Frameworks -> REST APIs (layered: dep-only is L2, usage raises to L3).
            if any(d in py_deps for d in ("fastapi", "flask", "django")):
                _imp_r, _dist_r, _uf_n_r, _ = _fw_evidence("REST APIs")
                # Also accept Python web-framework imports mapped via taxonomy
                # (fastapi/flask resolve to REST APIs) plus explicit patterns.
                _has_rest_usage = (_imp_r >= 1 or _dist_r >= 1)
                if not _has_rest_usage:
                    # Fallback: framework dep + any Python source using it
                    # (import_tokens contain fastapi/flask even if taxonomy maps oddly)
                    _has_rest_usage = any(
                        tok in ("fastapi", "flask", "django") for tok in import_tokens
                    )
                _rest_depth = (
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION if _has_rest_usage
                    else EvidenceDepth.LEVEL_2_CONFIG
                )
                _rest_kind = "source_usage" if _has_rest_usage else "dependency_manifest"
                if _has_rest_usage:
                    _rest_reason = f"Repository '{repo_name}' implements REST API services with Python web frameworks."
                else:
                    _rest_reason = (
                        f"Repository '{repo_name}' declares a Python web framework "
                        f"without observed API implementation."
                    )
                _add_signal(
                    "REST APIs",
                    _rest_depth,
                    _rest_reason,
                    {
                        "usage_count": _imp_r,
                        "detected_usage_patterns": _detected_patterns_for_skill("REST APIs"),
                        "relevant_files": _relevant_files_for_skill("REST APIs", sampled_source_files),
                        "evidence_kind": _rest_kind,
                    },
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
                # Layered: declared ML framework without observed imports stays L2.
                _ml_imp = int(_usage_counts_early.get("Machine Learning", 0) or 0)
                _ml_has_usage = _ml_imp >= 1 or any(
                    tok in ("sklearn", "scikit-learn", "torch", "tensorflow", "keras")
                    for tok in import_tokens
                )
                _ml_depth = (
                    EvidenceDepth.LEVEL_3_IMPLEMENTATION if _ml_has_usage
                    else EvidenceDepth.LEVEL_2_CONFIG
                )
                _add_signal(
                    "Machine Learning",
                    _ml_depth,
                    (
                        f"Repository '{repo_name}' imports/uses machine learning frameworks."
                        if _ml_has_usage else
                        f"Repository '{repo_name}' declares machine learning dependencies without observed usage."
                    ),
                    {
                        "usage_count": _ml_imp,
                        "relevant_files": _relevant_files_for_skill("Machine Learning", sampled_source_files),
                        "evidence_kind": "source_usage" if _ml_has_usage else "dependency_manifest",
                    },
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

        # 5c. Cross-ecosystem web frameworks -> canonical REST APIs skill (layered).
        # A framework dependency without observed imports/patterns stays at
        # configuration level; observed usage raises to implementation.
        rest_hits = sorted({d for d in all_deps if d in REST_FRAMEWORK_DEPS})
        if rest_hits and "REST APIs" not in signal_map:
            _imp_x, _dist_x, _uf_n_x, _ = _fw_evidence("REST APIs")
            _has_x_usage = (_imp_x >= 1 or _dist_x >= 1) or any(
                tok in rest_hits or tok.split("/")[-1] in rest_hits for tok in import_tokens
            )
            _x_depth = (
                EvidenceDepth.LEVEL_3_IMPLEMENTATION if _has_x_usage
                else EvidenceDepth.LEVEL_2_CONFIG
            )
            _x_kind = "source_usage" if _has_x_usage else "dependency_manifest"
            if _has_x_usage:
                _x_reason = f"Repository '{repo_name}' implements REST API services ({', '.join(rest_hits[:5])})."
            else:
                _x_reason = (
                    f"Repository '{repo_name}' declares REST framework dependencies "
                    f"({', '.join(rest_hits[:5])}) without observed API usage."
                )
            _add_signal(
                "REST APIs",
                _x_depth,
                _x_reason,
                {
                    "frameworks": rest_hits[:5],
                    "usage_count": _imp_x,
                    "detected_usage_patterns": _detected_patterns_for_skill("REST APIs"),
                    "relevant_files": _relevant_files_for_skill("REST APIs", sampled_source_files),
                    "evidence_kind": _x_kind,
                },
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
        # skill becomes configuration/dependency-level evidence (LEVEL_2).
        # A declared-but-never-imported dependency stays weak by design.
        # Reuse the early taxonomy resolution so framework blocks and this
        # generic block agree on dependency identity.
        dep_skills = _dep_skills_early
        for dep_skill, dep_token in sorted(dep_skills.items()):
            _add_signal(
                dep_skill,
                EvidenceDepth.LEVEL_2_CONFIG,
                f"Repository '{repo_name}' declares '{dep_token}' in its dependency/build manifest.",
                {
                    "dependency": dep_token,
                    "relevant_files": _relevant_files_for_skill(dep_skill, sampled_config_files or sampled_source_files),
                    "evidence_kind": "dependency_manifest",
                },
            )

        # 12. Imports / usages observed in sampled implementation files.
        # Layered depth (not mere keyword counting):
        #   L2: single import without dependency/tests/patterns (weak usage)
        #   L3: repeated imports, or import + declared dep, or API patterns
        #   L4: substantial use across multiple files/patterns (+ tests/workflows)
        # Comment-stripped imports (see extract_import_tokens) plus
        # framework-specific patterns (see detect_usage_patterns) decide.
        usage_counts = _usage_counts_early
        # Phase 3: skills observed ONLY through API-usage patterns (no
        # resolvable import token -- e.g. SQL queries in .sql files, Spring
        # annotations, workflow steps) still earn implementation signals.
        # Pattern-table keys are taxonomy-constrained, and _add_signal keeps
        # one signal per skill, so this cannot double-count evidence.
        def _skill_has_patterns(_name: str) -> bool:
            _p = _usage_patterns_raw.get(_name)
            if isinstance(_p, dict):
                return len(_p) > 0
            if isinstance(_p, (list, tuple, set)):
                return len(set(_p)) > 0
            return False

        _pattern_only_skills = set()
        for _raw_skill in (_usage_patterns_raw or {}).keys():
            _canon = normalize_skill(str(_raw_skill)) or str(_raw_skill)
            if _canon not in usage_counts and normalize_skill(_canon) == _canon \
                    and _skill_has_patterns(str(_raw_skill)):
                _pattern_only_skills.add(_canon)
        for use_skill in sorted(set(usage_counts.keys()) | _pattern_only_skills):
            use_count = int(usage_counts.get(use_skill, 0) or 0)
            declared = use_skill in dep_skills
            _imp_u, _dist_u, _uf_n_u, _uf_list_u = _fw_evidence(use_skill)
            _patterns_u = _detected_patterns_for_skill(use_skill)
            # Substantial: multi-file spread with repeated/patterned usage,
            # especially when corroborated by tests/workflows or a declared dep.
            if (
                (_uf_n_u >= 2 and (use_count >= 3 or len(_patterns_u) >= 2))
                or (_uf_n_u >= 3)
                or (use_count >= 3 and (declared or has_tests or len(_patterns_u) >= 1))
            ):
                use_depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL
                use_kind = "source_usage"
            elif use_count >= 2 or (use_count >= 1 and declared) or len(_patterns_u) >= 1:
                use_depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION
                use_kind = "source_usage"
            else:
                use_depth = EvidenceDepth.LEVEL_2_CONFIG
                use_kind = "source_usage"
            if use_count >= 1:
                _use_reason = (
                    f"Repository '{repo_name}' imports/uses {use_skill} in {use_count} place(s) "
                    f"across {max(_uf_n_u, 1)} inspected source file(s)"
                    f"{' with a matching declared dependency' if declared else ''}"
                    f"{', patterns: ' + ', '.join(_patterns_u[:3]) if _patterns_u else ''}."
                )
            else:
                # Phase 3: API usage without a resolvable import token.
                _use_reason = (
                    f"Repository '{repo_name}' uses {use_skill} API "
                    f"across {max(_uf_n_u, 1)} inspected source file(s)"
                    f"{', patterns: ' + ', '.join(_patterns_u[:3]) if _patterns_u else ''}."
                )
            _add_signal(
                use_skill,
                use_depth,
                _use_reason,
                {
                    "usage_count": use_count,
                    "declared_dependency": declared,
                    "detected_usage_patterns": _patterns_u,
                    "relevant_files": _relevant_files_for_skill(use_skill, sampled_source_files),
                    "source_files_inspected": sampled_source_files[:MAX_SOURCE_FILES_PER_REPO],
                    "evidence_kind": use_kind,
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
        _doc_relevant = ([inspection.get("readme_path")] if inspection.get("readme_path") else ["README.md"])
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
                    "relevant_files": list(_doc_relevant)[:3],
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
        # Structured metadata: every signal carries repository-level inspection
        # facts (no raw file contents) so downstream stages can audit depth.
        _files_analyzed = list(inspection.get("files_analyzed") or (
            ([inspection.get("readme_path")] if inspection.get("readme_text") else [])
            + list(sampled_source_files) + list(sampled_config_files)
        ))
        _files_analyzed = [str(f) for f in _files_analyzed if f][:10]
        _impl_files = list(inspection.get("implementation_files") or sampled_source_files)[:10]
        # Phase 3: documentation mentions per skill (for usage_status). One
        # taxonomy scan total, then per-signal lookup (no per-signal rescan).
        try:
            _doc_counts_for_status = skill_mention_counts(doc_text)
        except Exception:
            _doc_counts_for_status = {}
        _primary_lang = ""
        try:
            if isinstance(languages, dict) and languages:
                _primary_lang = str(max(languages.items(), key=lambda kv: int(kv[1] or 0) if isinstance(kv[1], (int, float)) else 0)[0])
        except Exception:
            _primary_lang = ""
        # Phase 3: documentation mentions per skill (for usage_status). One
        # taxonomy scan total, then per-signal lookup (no per-signal rescan).
        try:
            _doc_counts_for_status = skill_mention_counts(doc_text)
        except Exception:
            _doc_counts_for_status = {}
        signals: List[ExtractedSignal] = []
        for canonical, sig in signal_map.items():
            notes = evidence_notes.get(canonical) or []
            if notes:
                sig.metadata["supporting_evidence"] = notes[:5]
                sig.metadata["evidence_signal_count"] = len(notes)
            # Required structured fields (additive; existing keys preserved)
            # Phase 3: technology usage status (mentioned < declared <
            # imported < used < substantial). Equivalent to EvidenceDepth;
            # scoring formulas and signal strengths are unchanged.
            try:
                # NOTE: raw (non-backfilled) usage-file count is used here so
                # that a bare import without observed API usage stays
                # "imported" instead of being promoted to "used".
                _st_raw_ufiles = _usage_files_raw.get(canonical) or []
                _st_raw_n = len(list(_st_raw_ufiles or []))
                _st_patterns = _detected_patterns_for_skill(canonical)
                # Phase 4: language skills are "used" when source files are
                # written in that language -- even though language imports
                # resolve to other skills (e.g. `import fastapi` -> REST
                # APIs, not Python). Count relevant/top files whose extension
                # maps to this skill; this only ever rescues NONE -> USED and
                # never feeds the multi-file substantial path.
                _st_lang_files = 0
                try:
                    _st_seen_lang: Set[str] = set()
                    _st_candidates = list(sig.metadata.get("relevant_files") or [])
                    _st_candidates += [str(f) for f in (inspection.get("top_files") or [])]
                    for _st_f in _st_candidates:
                        if _st_lang_files >= 1:
                            break
                        _st_fl = str(_st_f).lower()
                        if _st_fl in _st_seen_lang:
                            continue
                        _st_seen_lang.add(_st_fl)
                        try:
                            if _is_skippable_path(_st_fl):
                                continue
                        except Exception:
                            pass
                        _st_dot = _st_fl.rfind(".")
                        _st_ext = _st_fl[_st_dot:] if _st_dot > 0 else ""
                        try:
                            if _st_ext and EXTENSION_SKILL_MAP.get(_st_ext) == canonical:
                                _st_lang_files += 1
                        except Exception:
                            continue
                except Exception:
                    _st_lang_files = 0
                sig.metadata.setdefault(
                    "usage_status",
                    _classify_usage_status(
                        has_mention=bool(_doc_counts_for_status.get(canonical)),
                        has_dependency=bool(canonical in _dep_skills_early),
                        import_count=int(_usage_counts_early.get(canonical, 0) or 0),
                        has_api_usage=bool(_st_patterns) or _st_lang_files >= 1,
                        distinct_patterns=len(_st_patterns),
                        usage_files=int(_st_raw_n or 0),
                        implementation_files=len(_impl_files),
                        has_tests_or_workflows=bool(has_tests or has_workflows),
                    ),
                )
            except Exception:
                try:
                    _fallback_depth = int(sig.depth)
                except (TypeError, ValueError):
                    _fallback_depth = 1
                sig.metadata.setdefault(
                    "usage_status",
                    _US_USED if _fallback_depth >= 3
                    else (_US_DECLARED if _fallback_depth == 2 else _US_MENTIONED),
                )
            sig.metadata.setdefault("repository_name", repo_name)
            sig.metadata.setdefault("full_name", inspection.get("full_name") or f"{owner}/{repo}")
            if _primary_lang:
                sig.metadata.setdefault("language", _primary_lang)
            if isinstance(languages, dict) and languages:
                sig.metadata.setdefault("languages", dict(languages))
            sig.metadata["evidence_depth"] = sig.depth
            sig.metadata["evidence_count"] = len(notes) or 1
            # Phase 4: traceability provenance (additive, compact, no source
            # contents). Every signal carries who observed what, where, when.
            sig.metadata.setdefault("provider", self.provider_name)
            try:
                _repo_full = str(inspection.get("full_name") or f"{owner}/{repo}").strip("/")
                sig.metadata.setdefault("source_url", f"https://github.com/{_repo_full}")
            except Exception:
                pass
            try:
                if verified_at is not None:
                    sig.metadata.setdefault("observed_at", verified_at.isoformat())
            except Exception:
                pass
            sig.metadata.setdefault("files_analyzed", _files_analyzed)
            sig.metadata.setdefault("files_analyzed_count", len(_files_analyzed))
            sig.metadata.setdefault("implementation_files", _impl_files)
            if not sig.metadata.get("relevant_files"):
                try:
                    sig.metadata["relevant_files"] = _relevant_files_for_skill(canonical, _impl_files or _files_analyzed)
                except Exception:
                    sig.metadata["relevant_files"] = (_impl_files or _files_analyzed)[:3]
            if "detected_usage_patterns" not in sig.metadata:
                try:
                    sig.metadata["detected_usage_patterns"] = _detected_patterns_for_skill(canonical)
                except Exception:
                    sig.metadata["detected_usage_patterns"] = []
            # Phase 2: file importance metadata (recomputed from final relevant
            # files so it always matches the emitted evidence; additive only).
            try:
                _final_rel = list(sig.metadata.get("relevant_files") or [])
                if _final_rel and "file_importance" not in sig.metadata:
                    _capped, _tier, _label = _cap_depth_by_importance(sig.depth, _final_rel)
                    sig.metadata["file_importance"] = _label
                    sig.metadata["file_importance_score"] = round(float(_importance_weight(_tier)), 3)
                sig.metadata.setdefault("file_importance", "medium")
                sig.metadata.setdefault("file_importance_score", 0.5)
                sig.metadata.setdefault("file_importance_breakdown", dict(_repo_importance.get("counts", {})))
                sig.metadata.setdefault("repository_importance", _repo_importance.get("label", "high"))
            except Exception:
                sig.metadata.setdefault("file_importance", "medium")
                sig.metadata.setdefault("file_importance_score", 0.5)
            # Phase 3: technology usage status (mentioned < declared <
            # imported < used < substantial). Additive metadata equivalent to
            # EvidenceDepth; scoring formulas and signal strengths unchanged.
            try:
                _st_imp, _st_dist, _st_ufn, _ = _fw_evidence(canonical)
                _st_patterns = _detected_patterns_for_skill(canonical)
                _status = _classify_usage_status(
                    has_mention=bool(_doc_counts_for_status.get(canonical)),
                    has_dependency=bool(canonical in _dep_skills_early),
                    import_count=int(_usage_counts_early.get(canonical, 0) or 0),
                    has_api_usage=bool(_st_patterns),
                    distinct_patterns=len(_st_patterns),
                    usage_files=int(_st_ufn or 0),
                    implementation_files=len(_impl_files),
                    has_tests_or_workflows=bool(has_tests or has_workflows),
                )
                sig.metadata.setdefault("usage_status", _status)
            except Exception:
                try:
                    _fallback_depth = int(sig.depth)
                except (TypeError, ValueError):
                    _fallback_depth = 1
                sig.metadata.setdefault(
                    "usage_status",
                    _US_USED if _fallback_depth >= 3
                    else (_US_DECLARED if _fallback_depth == 2 else _US_MENTIONED),
                )
            sig.metadata.setdefault("reason", sig.reason)
            signals.append(sig)

        # --- Provenance coherence enforcement (per-repository final signal) ---
        # The final accepted signal must have internally consistent depth,
        # usage_status, file_importance, relevant_files and detected patterns.
        # This is a defensive fix for any path where capping or fork discounts
        # left behind stronger metadata than the final depth supports.
        try:
            for _sig in signals:
                try:
                    _d = int(_sig.depth)
                except (TypeError, ValueError):
                    _d = 1
                # Re-derive cap from final relevant_files – if depth still exceeds
                # what its files can support, downgrade depth (never upgrade).
                _rel_final = list(_sig.metadata.get("relevant_files") or [])
                if _rel_final:
                    try:
                        _capped, _c_tier, _c_label = _cap_depth_by_importance(_d, _rel_final[:6])
                        if int(_capped) != _d:
                            _d = int(_capped)
                            _sig.depth = _d
                            _sig.metadata["evidence_depth"] = _d
                            # recompute strength for new depth (preserve fork discount)
                            _raw = EvidenceDepth.get_strength_for_depth(_d)
                            if bool(_sig.metadata.get("is_fork")):
                                _raw = round(min(0.55, _raw * 0.70), 2)
                            _sig.signal_strength = _raw
                    except Exception:
                        pass
                # Coerce file_importance to not outrank depth
                try:
                    _cur_imp = str(_sig.metadata.get("file_importance") or "medium").lower()
                    _coerced_imp = _coerce_importance_to_depth(_cur_imp, _d)
                    if _coerced_imp != _cur_imp:
                        _sig.metadata["file_importance"] = _coerced_imp
                        _tier_map = {"ignore": _FI_IGNORE, "low": _FI_LOW, "medium": _FI_MEDIUM, "high": _FI_HIGH, "very_high": _FI_VERY_HIGH}
                        _sig.metadata["file_importance_score"] = round(float(_importance_weight(_tier_map.get(_coerced_imp, _FI_MEDIUM))), 3)
                except Exception:
                    pass
                # Coerce usage_status to not outrank depth; clear impl-specific metadata when downgraded
                try:
                    _cur_st = str(_sig.metadata.get("usage_status") or "").lower()
                    if _cur_st:
                        _coerced_st = _coerce_status_to_depth(_cur_st, _d)
                        if _coerced_st != _cur_st:
                            _sig.metadata["usage_status"] = _coerced_st
                        # Depth 1 (mention) must not retain impl files or patterns
                        if _d <= 1:
                            if _sig.metadata.get("detected_usage_patterns"):
                                _sig.metadata["detected_usage_patterns"] = []
                            # Ensure relevant_files is documentation only
                            _doc_fb = ([inspection.get("readme_path")] if inspection.get("readme_path") else ["README.md"])
                            # If current files look like impl (contain src/ or high tier), replace
                            _has_impl_file = any("src/" in str(f).lower() or "app/" in str(f).lower() for f in _rel_final)
                            if _has_impl_file or not _rel_final or any(str(f).lower().endswith((".py",".js",".ts",".tsx",".java",".go",".rs")) for f in _rel_final):
                                # Keep only doc-like files for L1; fall back to README
                                _sig.metadata["relevant_files"] = [str(x) for x in _doc_fb if x][:3]
                        elif _d == 2:
                            if str(_sig.metadata.get("usage_status") or "").lower() in (_US_SUBSTANTIAL, _US_USED, _US_IMPORTED):
                                # L2 can be at most declared – keep config-level status
                                _sig.metadata["usage_status"] = _coerce_status_to_depth(_sig.metadata.get("usage_status"), 2)
                            # Keep infra config patterns (Docker/Kubernetes/CI) – they are
                            # valid configuration evidence even at L2, so do not clear.
                        elif _d == 3:
                            if str(_sig.metadata.get("usage_status") or "").lower() == _US_SUBSTANTIAL:
                                _sig.metadata["usage_status"] = _US_USED
                except Exception:
                    pass
                _sig.metadata["evidence_depth"] = int(_sig.depth)
                _sig.metadata["reason"] = _sig.reason
        except Exception:
            pass

        # Phase 2 audit trail: per-file importance and repository aggregate.
        try:
            inspection["file_importances"] = {
                str(k): _importance_label(int(v)) for k, v in list(_file_tiers.items())[:40]
            }
            inspection["repository_importance"] = _repo_importance.get("label", "high")
            inspection["repository_importance_reason"] = _repo_importance.get("reason", "")
        except Exception:
            pass

        # Phase 10: engineering-practice analysis. A SEPARATE dimension kept
        # on the inspection payload only -- signals, strengths, proficiency,
        # and readiness above are fully computed before this runs and are
        # never modified by it.
        try:
            inspection["engineering_practices"] = _analyze_practices(inspection)
        except Exception:
            pass

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
