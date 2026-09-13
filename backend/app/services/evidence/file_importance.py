"""
Deterministic file-importance classification for GitHub evidence (Phase 2).

Not all repository files contribute equally to skill evidence. This module
assigns every inspected path a deterministic importance tier so that
meaningful source-code implementation contributes more evidence than
documentation, metadata, or generated files.

Tiers (lowest -> highest):
  IGNORE    (0) - vendored, generated, binary, cache, minified, lock (for
                  implementation purposes). Never contributes evidence.
  LOW       (1) - README, documentation, changelog, license, comments-only
                  files, basic metadata. Documentation mentions only.
  MEDIUM    (2) - dependency manifests, Dockerfiles, compose files,
                  configuration, CI configuration, env templates, framework
                  configuration. Dependency/configuration evidence.
  HIGH      (3) - application source code, API implementations, services,
                  controllers, components, hooks, utilities, models, tests.
                  Implementation evidence.
  VERY_HIGH (4) - repository-level aggregate only: multiple related HIGH
                  files with corroborating usage patterns and tests/workflows
                  indicating substantial feature/architecture implementation.
                  Per-file maximum is HIGH; VERY_HIGH is earned by the
                  combination of files, never by a filename alone.

Design rules:
- Deterministic: same inputs always yield the same tier (no randomness,
  network, or time dependence).
- Not filename-alone: base tier comes from path + extension + file type +
  repository structure, then adjusted by actual detected evidence
  (imports/usages/patterns). A README stays LOW no matter how often it
  repeats a keyword; a config never becomes HIGH without source evidence.
- Separate from skill score: importance influences which evidence tier a
  file may support (caps depth), it never directly computes proficiency.
  Final skill scores still flow through EvidenceDepth strengths and the
  existing weighted-average proficiency formula.
- No double counting: importance never creates extra signals; the existing
  one-signal-per-skill-per-repository rule is preserved.
"""

from typing import Dict, List, Optional, Tuple, Any
import re

# Tier constants (ints compare deterministically).
IGNORE = 0
LOW = 1
MEDIUM = 2
HIGH = 3
VERY_HIGH = 4

LABELS: Dict[int, str] = {
    IGNORE: "ignore",
    LOW: "low",
    MEDIUM: "medium",
    HIGH: "high",
    VERY_HIGH: "very_high",
}

LABEL_TO_TIER: Dict[str, int] = {v: k for k, v in LABELS.items()}

# Influence weight of a file's evidence contribution. Kept separate from
# source_reliability and signal_strength: it modulates per-file evidence,
# never directly becomes proficiency.
WEIGHTS: Dict[int, float] = {
    IGNORE: 0.0,
    LOW: 0.25,
    MEDIUM: 0.5,
    HIGH: 0.8,
    VERY_HIGH: 1.0,
}

# Maximum EvidenceDepth a tier may support (compatibility with EvidenceDepth).
# IGNORE supports nothing; LOW caps at L1 mention; MEDIUM caps at L2 config;
# HIGH allows L3 implementation; VERY_HIGH allows L4 substantial.
MAX_DEPTH_BY_TIER: Dict[int, int] = {
    IGNORE: 0,
    LOW: 1,
    MEDIUM: 2,
    HIGH: 3,
    VERY_HIGH: 4,
}

# --- Canonical marker sets (single source of truth for importance) ---
# Kept consistent with the GitHub provider's skip/priority sets; the provider
# re-exports these names so existing imports keep working.

IGNORE_PATH_MARKERS = (
    "node_modules/", "bower_components/", "vendor/", "third_party/", "thirdparty/",
    "dist/", "build/", "out/", "target/", "obj/", ".next/", ".nuxt/", "coverage/",
    "__pycache__/", "site-packages/", "venv/", ".venv/", "env/", "migrations/",
    "generated/", "gen/", ".git/", "docs/_build/", "public/vendor/",
    ".cache/", "__tests__/.cache/", ".pytest_cache/", ".mypy_cache/",
    ".parcel-cache/", ".turbo/", ".vercel/", ".serverless/",
)

IGNORE_FILE_MARKERS = (
    ".min.js", ".min.css", ".bundle.js", ".bundle.css",
    ".lock", ".map", "-lock.json", "-lock.yaml", "-lock.yml",
    "pnpm-lock.yaml", "package-lock.json", "yarn.lock",
    ".pyc", ".pyo", ".o", ".obj", ".exe", ".dll", ".so", ".bin",
)

# Binary / media / archive / font extensions: never implementation evidence.
BINARY_EXTENSIONS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".obj", ".a", ".lib",
    ".pyc", ".pyo", ".class",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".rar", ".7z", ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".lock", ".map",
})

# Cache / temp / editor artifacts.
CACHE_BASENAMES = frozenset({
    ".ds_store", "thumbs.db", ".cache",
})

# Documentation basenames (LOW). Matched as exact basename or prefix.
DOC_BASENAMES = (
    "readme", "changelog", "changes", "contributing", "license", "licence",
    "notice", "authors", "code_of_conduct", "codeofconduct",
)

DOC_DIRS = ("docs/", "documentation/", "wiki/", "examples/docs/")

DOC_EXTENSIONS = frozenset({".md", ".mdx", ".rst", ".txt", ".adoc"})

# Basic metadata files (LOW).
METADATA_BASENAMES = frozenset({
    ".gitignore", ".gitattributes", ".editorconfig", ".nvmrc",
    ".python-version", "codeowners",
})

# Dependency manifests + container/config/CI/env/framework config (MEDIUM).
MEDIUM_MANIFEST_BASENAMES = frozenset({
    "package.json",
    "requirements.txt", "requirements-dev.txt", "requirements-test.txt",
    "pyproject.toml", "setup.py", "setup.cfg", "pipfile",
    "go.mod", "go.sum", "cargo.toml", "gemfile",
    "composer.json", "pubspec.yaml", "build.sbt", "package.swift",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "cmakelists.txt", "makefile",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "compose.yml", "compose.yaml", "containerfile",
    "tsconfig.json", "tsconfig.base.json",
    "vite.config.js", "vite.config.ts", "webpack.config.js",
    "tailwind.config.js", "tailwind.config.ts",
    "next.config.js", "next.config.mjs", "next.config.ts",
    "vercel.json", "netlify.toml", "render.yaml", "railway.json",
    "serverless.yml", "serverless.yaml", "procfile", "nginx.conf",
    "application.properties", "application.yml", "application.yaml",
    ".env.example", ".env.sample", ".env.template",
})

MEDIUM_CONFIG_DIRS = (
    ".github/workflows/", ".circleci/", ".gitlab/",
    "k8s/", "kubernetes/", "helm/", "charts/", "terraform/",
)

MEDIUM_CONFIG_SUFFIXES = (".tf", ".tfvars",)

# Source extensions that may carry HIGH implementation evidence.
SOURCE_EXTENSIONS = frozenset({
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".java", ".kt", ".kts", ".go", ".rs",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hh",
    ".cs", ".swift", ".dart", ".rb", ".php", ".scala",
    ".m", ".mm", ".sql",
})

# Repository structure markers where real implementation usually lives.
IMPLEMENTATION_DIR_MARKERS = (
    "src/", "app/", "lib/", "api/", "server/", "backend/", "frontend/",
    "core/", "services/", "internal/", "pkg/", "cmd/", "main/",
    "controllers/", "controller/", "routes/", "handlers/", "handler/",
    "middleware/", "models/", "model/", "views/", "components/",
    "component/", "hooks/", "utils/", "util/", "helpers/", "helper/",
    "shared/", "common/", "features/", "modules/", "domain/",
    "usecases/", "use_cases/", "application/", "infrastructure/",
    "algorithms/", "algos/", "engine/", "pipeline/",
)

# Filename stems signaling implementation roles (never sufficient alone).
IMPLEMENTATION_STEMS = frozenset({
    "main", "app", "index", "server", "api", "routes", "models", "views",
    "handler", "handlers", "service", "services", "controller", "controllers",
    "component", "components", "hook", "hooks", "util", "utils",
    "helper", "helpers", "model", "schema", "schemas", "store", "stores",
    "engine", "pipeline", "algorithm", "algorithms",
})

# Test path markers: tests are HIGH (valuable implementation evidence) but a
# single test file alone never yields VERY_HIGH.
TEST_MARKERS = ("test", "tests", "__tests__", "spec", "e2e")


def _normalize(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().lower()


def _basename(path_lower: str) -> str:
    return path_lower.rsplit("/", 1)[-1]


def _stem(base: str) -> str:
    stem = base.rsplit(".", 1)[0] if "." in base else base
    # Strip common suffixes: UserCard.test.tsx -> usercard; app.spec.ts -> app
    for suffix in (".test", ".spec", "-test", "-spec", "_test", "_spec"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem


def _is_test_path(path_lower: str) -> bool:
    return any(m in path_lower for m in TEST_MARKERS)


def is_binary_or_cache(path: str) -> bool:
    """True for binaries, media, archives, sourcemaps, cache artifacts."""
    low = _normalize(path)
    base = _basename(low)
    if base in CACHE_BASENAMES:
        return True
    dot = base.rfind(".")
    ext = base[dot:] if dot > 0 else ""
    if ext in BINARY_EXTENSIONS:
        return True
    return False


def _base_tier_from_structure(path: str, size: Optional[int] = None) -> int:
    """
    Base tier from path + extension + file type + repository structure only.
    No content evidence is consulted here; evidence adjusts afterwards.
    """
    low = _normalize(path)
    if not low:
        return IGNORE
    base = _basename(low)
    dot = base.rfind(".")
    ext = base[dot:] if dot > 0 else ""

    # 1. IGNORE: vendored / generated / binary / cache / minified / lock.
    if any(m in low for m in IGNORE_PATH_MARKERS):
        return IGNORE
    if any(m in low for m in IGNORE_FILE_MARKERS):
        return IGNORE
    if is_binary_or_cache(low):
        return IGNORE
    # Lockfiles for implementation purposes (manifests for setup at most).
    if base in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml",
                "pipfile.lock", "poetry.lock", "cargo.lock", "go.sum",
                ".terraform.lock.hcl"):
        return IGNORE
    # Generated markers in filename.
    if any(m in base for m in ("generated", ".gen.", "_gen.", ".g.", ".pb.")):
        return IGNORE
    # Minified/bundled.
    if base.endswith((".min.js", ".min.css")) or ".bundle." in base:
        return IGNORE
    # Huge blobs are likely generated bundles, not authored implementation.
    try:
        if size is not None and int(size) > 200_000:
            return IGNORE
    except (TypeError, ValueError):
        pass

    # 2. LOW: documentation and basic metadata.
    name_no_ext = base.rsplit(".", 1)[0]
    if any(base == d or base.startswith(d + ".") or base.startswith(d + "_") or base.startswith(d + "-")
           for d in DOC_BASENAMES):
        return LOW
    if any(d in low for d in DOC_DIRS):
        # Docs folder .md/.txt/.rst are LOW even if they mention code.
        if ext in DOC_EXTENSIONS or not ext:
            return LOW
    if base in METADATA_BASENAMES:
        return LOW

    # 3. MEDIUM: manifests, container/compose, configs, CI, env templates,
    #    framework configuration. Checked BEFORE the generic documentation
    #    extension fallback so manifest .txt files (requirements.txt) are not
    #    misclassified as LOW documentation.
    if base in MEDIUM_MANIFEST_BASENAMES or base.startswith("dockerfile"):
        return MEDIUM
    # Compose shorthand without extension (provenance details use bare names).
    if base in ("docker-compose", "compose"):
        return MEDIUM
    # Requirements variants (requirements-dev.txt, requirements-test.txt).
    if base.startswith("requirements") and ext in (".txt", ".in"):
        return MEDIUM
    if any(m in low for m in MEDIUM_CONFIG_DIRS) and base.endswith(
        (".yml", ".yaml", ".tf", ".json")
    ):
        return MEDIUM
    if base.endswith(MEDIUM_CONFIG_SUFFIXES):
        return MEDIUM
    if base in (".env.example", ".env.sample", ".env.template"):
        return MEDIUM
    if low.endswith(("/jenkinsfile", "jenkinsfile")) or base in (
        ".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml",
        "circle.yml", "buildspec.yml",
    ):
        return MEDIUM

    # 4. HIGH: real source files and tests.
    if ext in SOURCE_EXTENSIONS:
        # Test files are HIGH by policy (valuable, but not VERY_HIGH alone).
        if _is_test_path(low):
            return HIGH
        # Implementation directories or meaningful stems strengthen the
        # classification, but any source extension outside IGNORE/DOCS is at
        # least HIGH-candidate — structure is corroborating, not required.
        return HIGH

    # 5. Unknown / other: conservative MEDIUM for yaml/json/toml/ini/cfg that
    #    look like configuration, else LOW (do not invent implementation).
    if ext in (".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf", ".env"):
        return MEDIUM
    return LOW


def classify_file_importance(
    path: str,
    size: Optional[int] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Deterministic file-importance tier combining structure and evidence.

    Args:
        path: repository-relative file path.
        size: optional file size in bytes (huge blobs -> IGNORE).
        evidence: optional per-file detected evidence, e.g.
            {"has_imports": bool, "import_count": int,
             "has_patterns": bool, "pattern_count": int,
             "comments_only": bool, "is_test": bool}

    Rules:
    - IGNORE never upgrades (vendor/generated/binary/cache/lock/minified).
    - LOW docs/metadata never become HIGH from keyword frequency; a
      comments-only source file is downgraded to LOW.
    - MEDIUM configs never become HIGH from mentions alone.
    - HIGH requires a source extension (plus optional structure/evidence
      corroboration); per-file VERY_HIGH additionally requires substantial
      in-file evidence (multiple patterns or repeated imports in an
      implementation location).
    """
    base_tier = _base_tier_from_structure(path, size)
    if base_tier == IGNORE:
        return IGNORE
    ev = evidence or {}
    comments_only = bool(ev.get("comments_only", False))
    has_imports = bool(ev.get("has_imports", False)) or int(ev.get("import_count", 0) or 0) > 0
    has_patterns = bool(ev.get("has_patterns", False)) or int(ev.get("pattern_count", 0) or 0) > 0
    pattern_count = int(ev.get("pattern_count", 0) or 0)
    import_count = int(ev.get("import_count", 0) or 0)

    # Comments-only source file: no real implementation -> LOW.
    if comments_only and base_tier == HIGH:
        return LOW

    # LOW stays LOW regardless of keyword frequency (no upgrade from mentions).
    if base_tier == LOW:
        return LOW

    # MEDIUM stays MEDIUM: configuration proves setup, not implementation.
    if base_tier == MEDIUM:
        return MEDIUM

    # HIGH -> VERY_HIGH only with substantial in-file evidence in an
    # implementation location (never by filename alone).
    if base_tier == HIGH:
        low = _normalize(path)
        in_impl_dir = any(m in low for m in IMPLEMENTATION_DIR_MARKERS)
        substantial_in_file = (
            (pattern_count >= 2)
            or (import_count >= 3 and has_patterns)
            or (pattern_count >= 1 and import_count >= 2 and in_impl_dir)
        )
        if substantial_in_file:
            return VERY_HIGH
        return HIGH

    return base_tier


def assess_repository_importance(
    file_tiers: Dict[str, int],
    evidence_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Repository-level importance aggregate (determines VERY_HIGH/substantial).

    VERY_HIGH requires multiple related HIGH/VERY_HIGH implementation files
    with corroborating evidence (usage patterns and tests or workflows).
    A single file, however important, never yields repository VERY_HIGH.

    Returns {"level": int, "label": str, "reason": str, "counts": {...}}.
    """
    counts = {LABELS[IGNORE]: 0, LABELS[LOW]: 0, LABELS[MEDIUM]: 0,
              LABELS[HIGH]: 0, LABELS[VERY_HIGH]: 0}
    for tier in (file_tiers or {}).values():
        try:
            counts[LABELS[int(tier)]] += 1
        except (KeyError, TypeError, ValueError):
            continue
    high_files = counts[LABELS[HIGH]] + counts[LABELS[VERY_HIGH]]
    ev = evidence_summary or {}
    has_tests = bool(ev.get("has_tests", False))
    has_workflows = bool(ev.get("has_workflows", False))
    pattern_files = int(ev.get("pattern_files", 0) or 0)
    distinct_patterns = int(ev.get("distinct_patterns", 0) or 0)
    usage_files = int(ev.get("usage_files", 0) or 0)

    if high_files >= 3 and (pattern_files >= 2 or distinct_patterns >= 2 or usage_files >= 2) \
            and (has_tests or has_workflows):
        return {
            "level": VERY_HIGH,
            "label": LABELS[VERY_HIGH],
            "reason": (
                f"substantial implementation: {high_files} high-importance files "
                f"with usage patterns across {max(pattern_files, usage_files)} file(s)"
                f"{' and tests/workflows' if (has_tests or has_workflows) else ''}"
            ),
            "counts": counts,
        }
    if high_files >= 2 and (pattern_files >= 1 or distinct_patterns >= 1 or usage_files >= 2):
        # Multiple related implementation files with usage: still VERY_HIGH
        # candidate even without tests (tests strengthen but are not strictly
        # required when multi-file usage is proven).
        return {
            "level": VERY_HIGH,
            "label": LABELS[VERY_HIGH],
            "reason": (
                f"multi-file implementation: {high_files} high-importance files "
                f"with corroborating usage evidence"
            ),
            "counts": counts,
        }
    if high_files >= 1:
        return {
            "level": HIGH,
            "label": LABELS[HIGH],
            "reason": f"implementation present in {high_files} high-importance file(s)",
            "counts": counts,
        }
    medium_files = counts[LABELS[MEDIUM]]
    if medium_files >= 1:
        return {
            "level": MEDIUM,
            "label": LABELS[MEDIUM],
            "reason": f"configuration present in {medium_files} medium-importance file(s)",
            "counts": counts,
        }
    low_files = counts[LABELS[LOW]]
    if low_files >= 1:
        return {
            "level": LOW,
            "label": LABELS[LOW],
            "reason": f"documentation present in {low_files} low-importance file(s)",
            "counts": counts,
        }
    return {
        "level": IGNORE,
        "label": LABELS[IGNORE],
        "reason": "no analyzable files (all ignored or absent)",
        "counts": counts,
    }


def importance_weight(tier: int) -> float:
    """Per-file evidence influence weight (separate from skill scoring)."""
    try:
        return WEIGHTS[int(tier)]
    except (KeyError, TypeError, ValueError):
        return 0.0


def max_supported_depth(tier: int) -> int:
    """Maximum EvidenceDepth integer a file tier may support."""
    try:
        return MAX_DEPTH_BY_TIER[int(tier)]
    except (KeyError, TypeError, ValueError):
        return 0


def label(tier: int) -> str:
    """Human-readable tier label."""
    return LABELS.get(int(tier), "ignore") if isinstance(tier, int) else "ignore"
