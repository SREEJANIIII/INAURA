"""
Engineering-practice analysis for GitHub evidence (Phase 10).

A SEPARATE analytical dimension from technical skill proficiency: it grades
observable repository engineering practices (testing, docs, error handling,
structure, API design, dependency management, CI/CD, containerization,
security practices, maintainability) from deterministic, inspectable facts.

This is NOT a generic "code quality AI score" and it is NOT mixed into
technical skill proficiency or readiness anywhere: scores here never enter
signal_strength, source_reliability, or the proficiency weighted average.

Safety rules (no overclaim, no side effects):
- Local static inspection only: regular expressions over already-fetched
  file text plus repository structure facts. INAURA never executes
  repository code and never sends repository source to external services.
- Every finding carries provenance (indicator, detail, file paths). Raw
  file contents are never stored in findings.
- Comments, docstrings, string literals, vendored, generated, lock, and
  minified files never count as practice evidence.
- Security findings describe OBSERVED practices only and never certify
  safety: the security dimension always states it cannot guarantee
  security, and its confidence is capped at "medium" no matter how many
  indicators are present.
"""

from typing import Any, Dict, List, Tuple
import re

from .file_importance import IGNORE, classify_file_importance

# Canonical dimensions, in stable output order.
DIMENSIONS: Tuple[str, ...] = (
    "testing",
    "documentation",
    "error_handling",
    "project_structure",
    "api_design",
    "dependency_management",
    "ci_cd",
    "containerization",
    "security_practices",
    "code_maintainability",
)

CONFIDENCE_LEVELS: Tuple[str, ...] = ("low", "medium", "high")

MODEL_VERSION = "practices-v1"

# ---------------------------------------------------------------------------
# Local text stripping for error-handling scans.
#
# Deliberately self-contained (mirrors the comment/string handling used by
# the skill pipeline) so this module never imports the GitHub provider and
# no import cycle is possible.
# ---------------------------------------------------------------------------

_BLOCK_COMMENT_RES = (
    re.compile(r"/\*.*?\*/", re.S),
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r'"""[\s\S]*?"""', re.S),
    re.compile(r"'''[\s\S]*?'''", re.S),
)

_STRING_LITERAL_RE = re.compile(
    r"('''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\"|"
    r"'(?:[^'\\\n]|\\.)*'|"
    r'"(?:[^"\\\n]|\\.)*"|'
    r"`(?:[^`\\]|\\.)*`)",
    re.S,
)


def _strip_for_error_scan(text: str) -> str:
    """Remove block comments/docstrings, line comments, and string literals."""
    cleaned = str(text or "")
    for pattern in _BLOCK_COMMENT_RES:
        cleaned = pattern.sub("\n", cleaned)
    try:
        cleaned = _STRING_LITERAL_RE.sub('""', cleaned)
    except Exception:
        pass
    kept: List[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if stripped.startswith(("#", "//", "--", "*", "<!--")):
            continue
        kept.append(line)
    return "\n".join(kept)


# ---------------------------------------------------------------------------
# Error-handling detection (per sampled source file).
# ---------------------------------------------------------------------------

# Indicator -> compiled pattern. Each pattern requires a code-shaped
# construct, never a bare keyword.
_ERROR_PATTERNS: Tuple[Tuple[str, Any], ...] = (
    ("try_blocks", re.compile(r"^\s*try\s*[:{]", re.M)),
    ("handlers", re.compile(
        r"^\s*except\b"              # Python
        r"|\bcatch\s*\("             # JavaScript / Java / C#
        r"|\bif\s+err\s*!=\s*nil\b"  # Go-style error checks
        r"|\bfinally\s*[{:]",
        re.M,
    )),
    ("raise_throw", re.compile(r"^\s*raise\b|\bthrow\b", re.M)),
    ("validation", re.compile(
        r"\b(pydantic|BaseModel|marshmallow|Schema|zod|Joi|joi|"
        r"class-validator|express-validator|Yup|yup|valibot|"
        r"djoser|serializers)\b"
    )),
    ("error_responses", re.compile(
        r"\b(HTTPException|abort\s*\(|status_code\s*=\s*[45]\d\d|"
        r"res\s*\.\s*status\s*\(\s*[45])"
    )),
)


def detect_error_handling(text: str) -> Dict[str, int]:
    """
    Count error-handling constructs in one source file's text.
    Returns indicator -> occurrence count (empty when none found).
    Comments, docstrings, and string literals are stripped first so prose
    such as `"try this at home"` never counts as error handling.
    """
    counts: Dict[str, int] = {}
    cleaned = _strip_for_error_scan(text)
    if not cleaned.strip():
        return counts
    for name, pattern in _ERROR_PATTERNS:
        try:
            found = len(pattern.findall(cleaned))
        except Exception:
            found = 0
        if found > 0:
            counts[name] = found
    return counts


def merge_error_counts(
    acc_counts: Dict[str, int],
    acc_files: Dict[str, List[str]],
    file_hits: Dict[str, int],
    path: str,
) -> None:
    """Accumulate per-file error-handling hits (mirrors usage-pattern merge)."""
    for name, count in (file_hits or {}).items():
        acc_counts[name] = acc_counts.get(name, 0) + int(count or 0)
        bucket = acc_files.setdefault(name, [])
        if path not in bucket:
            bucket.append(path)


# ---------------------------------------------------------------------------
# CI test-step detection (scanned over sampled configuration text).
# ---------------------------------------------------------------------------

CI_TEST_COMMANDS: Tuple[str, ...] = (
    "pytest", "jest", "vitest", "mocha", "coverage run", "coverage xml",
    "npm test", "npm run test", "npx jest", "go test", "cargo test",
    "phpunit", "rspec", "gradle test", "./gradlew test", "mvn test",
    "mvn verify", "dotnet test", "ctest",
)


def detect_ci_test_steps(config_text: str) -> List[str]:
    """
    Return the test commands literally present in configuration text
    (workflow YAML, CI configs). Matched case-insensitively on whole
    command tokens; documentation prose is never scanned here.
    """
    flat = f"\n{str(config_text or '').lower()}\n"
    found: List[str] = []
    for command in CI_TEST_COMMANDS:
        token = command.lower()
        # Whole-token match: bounded by non-identifier characters so that
        # e.g. "pytest" does not match "pytester".
        if re.search(r"(?<![\w\-])" + re.escape(token) + r"(?![\w\-])", flat):
            found.append(command)
    # De-duplicate while preserving documented order.
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------------------
# Dimension evaluation.
#
# Each dimension declares indicators as (weight, present, detail, files).
# Weights sum to 1.0 per dimension; score = sum of present weights (capped).
# Confidence reflects corroboration, not strength:
#   0 indicators -> "low" (absent), 1 -> "low", 2 -> "medium", 3+ -> "high".
# Security confidence is additionally capped at "medium": static inspection
# cannot verify runtime posture, and absence of findings proves nothing.
# ---------------------------------------------------------------------------

# Manifest basenames signaling dependency management (mirrors the provider's
# manifest sets; kept local so this module never imports the provider).
_MANIFEST_BASENAMES = (
    "package.json", "requirements.txt", "pyproject.toml", "setup.py",
    "setup.cfg", "Pipfile", "go.mod", "Cargo.toml", "Gemfile",
    "composer.json", "pubspec.yaml", "build.sbt", "Package.swift",
    "pom.xml", "build.gradle", "build.gradle.kts",
)
_LOCKFILE_BASENAMES = (
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Pipfile.lock",
    "poetry.lock", "Cargo.lock", "go.sum", "Gemfile.lock",
    "composer.lock", "pubspec.lock", "packages.lock.json",
)
_LINT_CONFIG_BASENAMES = (
    ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
    "eslint.config.js", "eslint.config.mjs", "eslint.config.ts",
    "ruff.toml", ".ruff.toml", ".flake8", "mypy.ini", ".mypy.ini",
    ".golangci.yml", ".golangci.yaml", "rubocop.yml", ".rubocop.yml",
)
_OPENAPI_BASENAMES = (
    "openapi.yaml", "openapi.yml", "openapi.json",
    "swagger.yaml", "swagger.yml", "swagger.json",
)


def _lower_set(values: Any) -> set:
    return {str(v).lower() for v in (values or []) if str(v or "").strip()}


def _basenames(paths: Any) -> set:
    return {str(p).lower().rsplit("/", 1)[-1] for p in (paths or []) if str(p or "").strip()}


def _build_dimension(
    name: str,
    indicators: List[Tuple[str, float, bool, str, Any]],
    reason_absent: str,
    confidence_cap: str = "high",
) -> Dict[str, Any]:
    """Assemble one dimension result from (indicator, weight, present, detail, files)."""
    findings = [
        {
            "indicator": indicator,
            "present": bool(present),
            "detail": str(detail),
            "files": [str(f) for f in (files or [])][:6],
        }
        for (indicator, _weight, present, detail, files) in indicators
    ]
    score = round(min(1.0, sum(w for (_, w, p, _, _) in indicators if p)), 3)
    present_count = sum(1 for f in findings if f["present"])
    if present_count == 0:
        confidence = "low"
    elif present_count == 1:
        confidence = "low"
    elif present_count == 2:
        confidence = "medium"
    else:
        confidence = "high"
    order = {"low": 0, "medium": 1, "high": 2}
    if order[confidence] > order[confidence_cap]:
        confidence = confidence_cap
    if present_count == 0:
        reason = reason_absent
    else:
        shown = "; ".join(f["detail"] for f in findings if f["present"])
        missing = [f["indicator"] for f in findings if not f["present"]]
        reason = f"{shown}."
        if missing:
            # Explainability: state plainly which indicators were NOT
            # observed so a partial score is auditable.
            reason += f" Missing: {', '.join(missing)}."
    return {
        "dimension": name,
        "score": score,
        "confidence": confidence,
        "present": present_count > 0,
        "findings": findings,
        "reason": reason,
    }


# Known test-framework dependency names (exact/prefixed matching only, so
# incidental substrings such as "contest" or "latest" never count). Mirrors
# the provider's matching semantics without importing the provider module.
_KNOWN_TEST_LIBS = frozenset({
    "jest", "mocha", "vitest", "cypress", "playwright", "supertest", "chai",
    "jasmine", "ava", "testing-library", "@testing-library/react",
    "pytest", "pytest-cov", "unittest", "nose", "tox", "coverage",
    "testify", "junit", "testng", "mockito", "assertj",
    "xunit", "nunit", "mstest", "gtest", "catch2", "phpunit", "rspec",
})

_TEST_FILE_MARKERS = ("test", "tests", "__tests__", "spec")

# Source-file extensions eligible as implementation evidence.
_SOURCE_EXTENSIONS = frozenset({
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java",
    ".kt", ".kts", ".go", ".rs", ".cpp", ".cc", ".cxx", ".c", ".h",
    ".hpp", ".cs", ".swift", ".dart", ".rb", ".php", ".scala",
})


def _is_test_file(path: str) -> bool:
    low = str(path or "").lower()
    dot = low.rfind(".")
    if dot <= 0 or low[dot:] not in _SOURCE_EXTENSIONS:
        return False
    return any(m in low for m in _TEST_FILE_MARKERS)


# Known test-framework dependency names (exact/prefixed matching only, so
# incidental substrings such as "contest" or "latest" never count). Mirrors
# the provider's matching semantics without importing the provider module.
_KNOWN_TEST_LIBS = frozenset({
    "jest", "mocha", "vitest", "cypress", "playwright", "supertest", "chai",
    "jasmine", "ava", "testing-library", "@testing-library/react",
    "pytest", "pytest-cov", "unittest", "nose", "tox", "coverage",
    "testify", "junit", "testng", "mockito", "assertj",
    "xunit", "nunit", "mstest", "gtest", "catch2", "phpunit", "rspec",
})

# Dependency manifest basenames signaling dependency management.
_MANIFEST_BASENAMES = (
    "package.json", "requirements.txt", "pyproject.toml", "setup.py",
    "setup.cfg", "Pipfile", "go.mod", "Cargo.toml", "Gemfile",
    "composer.json", "pubspec.yaml", "build.sbt", "Package.swift",
    "pom.xml", "build.gradle", "build.gradle.kts",
)

# Lockfiles pinning resolved dependency versions.
_LOCKFILE_BASENAMES = (
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Pipfile.lock",
    "poetry.lock", "Cargo.lock", "go.sum", "Gemfile.lock",
    "composer.lock", "pubspec.lock", "packages.lock.json",
)

# Linter/formatter configuration basenames (filename evidence only;
# tool-specific sections inside manifests are not inspected).
_LINT_CONFIG_BASENAMES = (
    ".eslintrc", "eslint.config.js", "eslint.config.mjs", "eslint.config.ts",
    "ruff.toml", ".ruff.toml", ".flake8", "mypy.ini", ".mypy.ini",
    ".golangci.yml", ".golangci.yaml", ".rubocop.yml",
)

# API contract basenames.
_OPENAPI_BASENAMES = (
    "openapi.yaml", "openapi.yml", "openapi.json",
    "swagger.yaml", "swagger.yml", "swagger.json",
)


def _test_libs_in_deps(deps: Any) -> List[str]:
    """Dependency names matching known test frameworks (exact/prefixed only)."""
    found: List[str] = []
    for raw in (deps or []):
        dep = str(raw or "").lower().strip()
        if not dep:
            continue
        if dep in _KNOWN_TEST_LIBS:
            found.append(str(raw))
            continue
        for lib in _KNOWN_TEST_LIBS:
            if (dep.startswith(f"{lib}-") or dep.startswith(f"{lib}_")
                    or dep.startswith(f"@{lib}/") or dep.endswith(f"-{lib}")
                    or dep.endswith(f"/{lib}")):
                found.append(str(raw))
                break
            if dep.startswith("@types/") and dep.replace("@types/", "") == lib:
                found.append(str(raw))
                break
    return list(dict.fromkeys(found))


def _is_ignored_path(path: str) -> bool:
    """Vendored / generated / binary / cache paths never count as evidence."""
    try:
        return classify_file_importance(str(path)) == IGNORE
    except Exception:
        return False


def _top_level_dirs(paths: Any) -> List[str]:
    """Distinct top-level directories across repository paths."""
    dirs: List[str] = []
    for raw in (paths or []):
        clean = str(raw or "").replace("\\", "/")
        if "/" not in clean or _is_ignored_path(clean):
            continue
        top = clean.split("/", 1)[0].lower()
        if top and top not in ("", ".") and top not in dirs:
            dirs.append(top)
    return dirs


def analyze_engineering_practices(inspection: Any) -> Dict[str, Any]:
    """
    Analyze one repository's engineering practices from its inspection facts.

    Input is the same inspection dict the skill pipeline consumes (every read
    is defensive: missing keys simply yield absent dimensions). Output is a
    stable 10-dimension report; every finding carries provenance (indicator,
    detail, file paths) and no raw file contents are ever stored.

    These scores are a SEPARATE dimension: they never enter ExtractedSignal
    strength, source reliability, proficiency, or readiness.
    """
    inspection = inspection if isinstance(inspection, dict) else {}
    repo_name = str(inspection.get("name") or inspection.get("full_name") or "repository")

    root_files = [str(f) for f in (inspection.get("root_files") or [])]
    root_lower = {f.lower() for f in root_files}
    top_files = [str(f) for f in (inspection.get("top_files") or [])]
    # Unfiltered basenames: lockfiles and manifests are classified IGNORE for
    # source scanning, but their PRESENCE is positive dependency-management
    # evidence, so presence checks must not use the filtered lists below.
    all_bases_unfiltered = (
        {f.lower().rsplit("/", 1)[-1] for f in root_files}
        | {f.lower().rsplit("/", 1)[-1] for f in top_files}
    )
    # Authorable files only: vendored / generated / binary / cache paths
    # never count as practice evidence.
    authorable = [f for f in (root_files + top_files) if not _is_ignored_path(f)]
    authorable_bases = {f.lower().rsplit("/", 1)[-1] for f in authorable}
    sampled_configs = [str(f) for f in (inspection.get("config_files_sampled") or [])]
    config_text = str(inspection.get("config_text") or "")
    readme_text = str(inspection.get("readme_text") or "")
    readme_present = bool(readme_text) or bool(inspection.get("readme_present"))
    usage_patterns = inspection.get("usage_patterns") or {}
    usage_files = inspection.get("usage_files") or {}

    def _pattern_names(entry: Any) -> set:
        if isinstance(entry, dict):
            return {str(k) for k in entry.keys()}
        if isinstance(entry, (list, tuple, set)):
            return {str(v) for v in entry}
        return set()

    def _test_files() -> List[str]:
        # Presence always requires at least one path: bare counts without
        # file provenance never assert a practice (mirrors error handling).
        hits = []
        for f in authorable:
            if _is_test_file(f) and f not in hits:
                hits.append(f)
            if len(hits) >= 10:
                break
        return hits[:10]

    def _files_in_dirs(markers: Tuple[str, ...]) -> List[str]:
        hits = []
        for f in authorable:
            low = f.lower().replace("\\", "/")
            if any(m in low for m in markers) and f not in hits:
                hits.append(f)
            if len(hits) >= 10:
                break
        return hits

    # -- shared derived facts -------------------------------------------
    # Test-file presence requires paths: a bare tree count without file
    # provenance never asserts the practice (same rule as error handling).
    test_files = _test_files()
    has_test_files = bool(test_files)

    all_deps: List[str] = []
    for key in ("package_json_deps", "python_deps", "eco_manifest_deps",
                "eco_python_deps", "dependencies", "java_build_deps"):
        try:
            for dep in (inspection.get(key) or []):
                if str(dep or "").strip():
                    all_deps.append(str(dep))
        except TypeError:
            continue
    test_frameworks = _test_libs_in_deps(all_deps)
    testing_pattern_names = _pattern_names(
        usage_patterns.get("Testing") if isinstance(usage_patterns, dict) else None
    )
    if not test_frameworks and testing_pattern_names:
        test_frameworks = ["detected test usage patterns"]

    coverage_basenames = {
        "pytest.ini", "tox.ini", "jest.config.js", "jest.config.ts",
        "jest.config.mjs", "jest.config.cjs", "vitest.config.js",
        "vitest.config.ts", ".coveragerc", "coverage.xml",
        "codecov.yml", ".codecov.yml",
    }
    coverage_files = sorted(
        {f for f in authorable if f.lower().rsplit("/", 1)[-1] in coverage_basenames}
    )[:6]
    ci_test_commands = detect_ci_test_steps(config_text)
    ci_test_files = list(sampled_configs) if ci_test_commands else []

    docs_files = sorted({
        f for f in authorable
        if ("/docs/" in f.lower().replace("\\", "/")
            or "/documentation/" in f.lower().replace("\\", "/"))
    })[:10]
    changelog_files = sorted(
        {f for f in authorable if f.lower().rsplit("/", 1)[-1].startswith("changelog")})[:3]
    contributing_files = sorted(
        {f for f in authorable if f.lower().rsplit("/", 1)[-1].startswith("contributing")})[:3]

    error_counts: Dict[str, int] = {}
    error_files: Dict[str, List[str]] = {}
    raw_counts = inspection.get("error_indicators") or {}
    raw_files = inspection.get("error_files") or {}
    if isinstance(raw_counts, dict):
        for name, count in raw_counts.items():
            try:
                total = int(count or 0)
            except (TypeError, ValueError):
                total = 0
            if total > 0:
                error_counts[str(name)] = total
    if isinstance(raw_files, dict):
        for name, files in raw_files.items():
            kept = [str(f) for f in (files or [])
                    if str(f) and not _is_ignored_path(str(f))][:6]
            if kept:
                error_files[str(name)] = kept
            elif isinstance(files, list) and files:
                # File mapping provided but every file is vendored/generated:
                # record the exclusion so counts alone cannot resurrect it.
                error_files[str(name)] = []

    def _err_present(name: str) -> bool:
        """Presence requires at least one non-ignored file behind the
        indicator. Bare counts without file provenance never assert a
        practice (every finding must be traceable to files)."""
        return bool(error_files.get(name))
    try_files = error_files.get("try_blocks", [])
    handler_files = error_files.get("handlers", [])

    def _err_sites(name: str) -> int:
        """Observed site count, falling back to file count when only file
        provenance was provided."""
        try:
            total = int(error_counts.get(name, 0) or 0)
        except (TypeError, ValueError):
            total = 0
        if total <= 0:
            total = len(error_files.get(name, []))
        return total

    try_handler_files = sorted(set(try_files) & set(handler_files))
    sustained_handlers = len(handler_files) >= 2
    try_present = (
        (_err_present("try_blocks") and _err_present("handlers"))
        or sustained_handlers
    )
    error_file_union: List[str] = []
    for files in error_files.values():
        for f in files:
            if f not in error_file_union:
                error_file_union.append(f)
            if len(error_file_union) >= 6:
                break
    impl_dirs = ("src/", "app/", "lib/", "api/", "server/", "backend/",
                 "frontend/", "core/", "services/", "internal/", "pkg/",
                 "cmd/", "main/")
    src_layout = sorted(
        {f for f in authorable
         if any(m in f.lower().replace("\\", "/") for m in impl_dirs)})[:10]
    tests_dirs = _files_in_dirs(("test", "tests", "__tests__", "spec"))
    layered_markers = ("api/", "services/", "models/", "controllers/",
                       "routes/", "handlers/", "middleware/", "views/",
                       "components/")
    layered_present = sorted(
        {m.strip("/") for m in layered_markers
         if any(m in f.lower().replace("\\", "/") for f in authorable)})
    top_dirs: List[str] = []
    for f in authorable:
        clean = f.replace("\\", "/")
        if "/" in clean:
            top = clean.split("/", 1)[0].lower()
            if top and top not in top_dirs:
                top_dirs.append(top)

    rest_patterns = _pattern_names(
        usage_patterns.get("REST APIs") if isinstance(usage_patterns, dict) else None
    )
    route_pattern_ids = {"fastapi_app", "flask_app", "route_decorator",
                         "api_router", "express_route"}
    route_files: List[str] = []
    if isinstance(usage_files, dict):
        for f in (usage_files.get("REST APIs") or []):
            if str(f) and not _is_ignored_path(str(f)) and str(f) not in route_files:
                route_files.append(str(f))
            if len(route_files) >= 6:
                break
    has_route_patterns = bool(rest_patterns & route_pattern_ids)
    openapi_files = sorted({f for f in authorable
                            if f.lower().rsplit("/", 1)[-1] in _OPENAPI_BASENAMES})[:6]
    versioned_paths: List[str] = []
    for f in authorable:
        if re.search(r"/v\d+(?:[./]|$)", f.lower().replace("\\", "/")):
            versioned_paths.append(f)
        if len(versioned_paths) >= 6:
            break

    manifests = sorted({b for b in _MANIFEST_BASENAMES
                        if b in all_bases_unfiltered})[:8]
    lockfiles = sorted({b for b in _LOCKFILE_BASENAMES
                        if b in all_bases_unfiltered})[:8]
    parsed_dep_count = len(all_deps)

    has_workflows = bool(inspection.get("has_workflows"))
    workflow_files = sorted(
        {f for f in authorable if ".github/workflows/" in f.lower().replace("\\", "/")})[:6]
    ci_basenames = ("jenkinsfile", ".gitlab-ci.yml", ".travis.yml",
                    "azure-pipelines.yml", "circle.yml", "buildspec.yml")
    ci_config_files = sorted(
        {f for f in authorable
         if f.lower().rsplit("/", 1)[-1] in ci_basenames
         or ".circleci/config.yml" in f.lower().replace("\\", "/")})[:6]
    has_ci_config = bool(inspection.get("has_ci_config")) or bool(ci_config_files)
    ci_present = has_workflows or has_ci_config

    has_dockerfile = any("dockerfile" in f.lower().rsplit("/", 1)[-1] for f in authorable)
    dockerfile_files = sorted(
        {f for f in authorable if "dockerfile" in f.lower().rsplit("/", 1)[-1]})[:3]
    compose_basenames = ("docker-compose.yml", "docker-compose.yaml",
                         "compose.yml", "compose.yaml")
    has_compose = any(b in authorable_bases for b in compose_basenames)
    compose_files = sorted(
        {f for f in authorable if f.lower().rsplit("/", 1)[-1] in compose_basenames})[:3]
    multistage = bool(re.search(r"^\s*FROM\s+\S+\s+AS\s+\w+", config_text, re.M | re.I))
    dockerignore_files = sorted(
        {f for f in authorable if f.lower().rsplit("/", 1)[-1] == ".dockerignore"})[:3]

    env_example_files = sorted(
        {f for f in authorable if f.lower().rsplit("/", 1)[-1] in
         (".env.example", ".env.sample", ".env.template")})[:3]
    auth_libs = sorted({d for d in all_deps if any(
        marker in d.lower() for marker in
        ("jsonwebtoken", "jwt", "bcrypt", "passport", "auth0", "next-auth",
         "passlib", "pyjwt", "oauthlib"))})[:6]
    gitignore_present = ".gitignore" in root_lower
    nonroot_user = False
    try:
        users = re.findall(r"^\s*USER\s+(\S+)", config_text, re.M | re.I)
        nonroot_user = any(u.strip().strip("\"'").lower() not in ("root", "0") for u in users)
    except Exception:
        nonroot_user = False

    lint_files = sorted(
        {f for f in authorable
         if any(f.lower().rsplit("/", 1)[-1] == name
                or f.lower().rsplit("/", 1)[-1].startswith(name)
                for name in _LINT_CONFIG_BASENAMES)})[:6]
    ts_patterns = _pattern_names(
        usage_patterns.get("TypeScript") if isinstance(usage_patterns, dict) else None
    )
    typing_present = bool(ts_patterns & {"type_annotation", "interface_def", "type_alias"})
    typing_files: List[str] = []
    if typing_present and isinstance(usage_files, dict):
        for f in (usage_files.get("TypeScript") or []):
            if str(f) and not _is_ignored_path(str(f)) and str(f) not in typing_files:
                typing_files.append(str(f))
            if len(typing_files) >= 6:
                break
    # Breadth across the observed tree (not just the capped sample): paths
    # are structural facts, so the full listing is the honest denominator.
    module_dirs = [d for d in _top_level_dirs(authorable)]

    # -- dimensions ------------------------------------------------------
    dimensions: Dict[str, Dict[str, Any]] = {}

    dimensions["testing"] = _build_dimension(
        "testing",
        [
            ("test_files", 0.40, bool(test_files),
             f"{len(test_files)} test file(s) observed"
             if test_files else "no test files observed",
             test_files),
            ("test_frameworks", 0.30, bool(test_frameworks),
             f"test framework dependencies: {', '.join(test_frameworks[:4])}"
             if test_frameworks else "no test framework dependency observed",
             []),
            ("coverage_config", 0.15, bool(coverage_files),
             f"coverage configuration: {', '.join(coverage_files)}"
             if coverage_files else "no coverage configuration observed",
             coverage_files),
            ("ci_test_execution", 0.15, bool(ci_test_commands),
             f"CI executes tests via: {', '.join(ci_test_commands)}"
             if ci_test_commands else "no test execution step observed in sampled CI configuration",
             ci_test_files),
        ],
        f"Repository '{repo_name}' shows no testing evidence in sampled files.",
    )

    readme_len = len(readme_text)
    dimensions["documentation"] = _build_dimension(
        "documentation",
        [
            ("readme", 0.40, readme_present,
             "README present" if readme_present else "no README observed",
             ([str(inspection.get("readme_path") or "README.md")] if readme_present else [])),
            ("readme_depth", 0.20, readme_len >= 500,
             f"README length {readme_len} characters"
             if readme_present else "no README content to measure",
             []),
            ("docs_directory", 0.20, bool(docs_files),
             f"documentation directory files: {', '.join(docs_files[:4])}"
             if docs_files else "no dedicated documentation directory observed",
             docs_files),
            ("changelog", 0.10, bool(changelog_files),
             f"changelog: {', '.join(changelog_files)}"
             if changelog_files else "no changelog observed",
             changelog_files),
            ("contributing", 0.10, bool(contributing_files),
             f"contributing guide: {', '.join(contributing_files)}"
             if contributing_files else "no contributing guide observed",
             contributing_files),
        ],
        f"Repository '{repo_name}' shows no documentation evidence.",
    )

    dimensions["error_handling"] = _build_dimension(
        "error_handling",
        [
            ("try_except", 0.30, try_present,
             ("paired try/exception handling observed"
              if error_counts.get("try_blocks", 0) > 0 and error_counts.get("handlers", 0) > 0
              else ("sustained error checks observed across files" if sustained_handlers
                    else "no paired try/exception handling observed")),
             sorted(set(try_handler_files + handler_files))[:6] or error_file_union[:6]),
            ("raising_errors", 0.25, _err_present("raise_throw"),
             f"{_err_sites('raise_throw')} raise/throw site(s) observed"
             if _err_present("raise_throw") else "no explicit error raising observed",
             (error_files.get("raise_throw", []) if isinstance(error_files, dict) else [])),
            ("validation", 0.25, _err_present("validation"),
             "input validation library usage observed"
             if _err_present("validation") else "no input validation library usage observed",
             (error_files.get("validation", []) if isinstance(error_files, dict) else [])),
            ("error_responses", 0.20, _err_present("error_responses"),
             "structured error responses observed"
             if _err_present("error_responses") else "no structured error responses observed",
             (error_files.get("error_responses", []) if isinstance(error_files, dict) else [])),
        ],
        f"Repository '{repo_name}' shows no error-handling evidence in sampled files. "
        "Absence of observed patterns is not proof the code lacks error handling.",
    )

    dimensions["project_structure"] = _build_dimension(
        "project_structure",
        [
            ("source_layout", 0.35, bool(src_layout),
             f"implementation directories observed: "
             f"{', '.join(sorted({f.split('/')[0] for f in src_layout if '/' in f})[:4]) or 'src layout'}"
             if src_layout else "no conventional source layout observed",
             src_layout[:6]),
            ("tests_directory", 0.25, bool(tests_dirs),
             "separate tests directory observed"
             if tests_dirs else "no separate tests directory observed",
             tests_dirs[:6]),
            ("layered_concerns", 0.25, len(layered_present) >= 2,
             f"layered concerns observed: {', '.join(layered_present)}"
             if len(layered_present) >= 2 else "no layered (api/services/models-style) separation observed",
             []),
            ("module_breadth", 0.15, len(top_dirs) >= 4,
             f"{len(top_dirs)} top-level directories"
             if len(top_dirs) >= 4 else "few top-level directories observed",
             []),
        ],
        f"Repository '{repo_name}' shows no conventional project-structure evidence.",
    )

    dimensions["api_design"] = _build_dimension(
        "api_design",
        [
            ("route_definitions", 0.50, has_route_patterns,
             "REST route definitions observed in implementation"
             if has_route_patterns else "no REST route definitions observed in sampled files",
             route_files),
            ("openapi_spec", 0.30, bool(openapi_files),
             f"OpenAPI/Swagger contract: {', '.join(openapi_files)}"
             if openapi_files else "no OpenAPI/Swagger contract observed",
             openapi_files),
            ("versioned_paths", 0.20, bool(versioned_paths),
             f"versioned API paths observed: {', '.join(versioned_paths[:3])}"
             if versioned_paths else "no versioned API paths observed",
             versioned_paths),
        ],
        f"Repository '{repo_name}' shows no API design evidence.",
    )

    dimensions["dependency_management"] = _build_dimension(
        "dependency_management",
        [
            ("manifests", 0.50, bool(manifests),
             f"dependency manifests: {', '.join(manifests)}"
             if manifests else "no dependency manifest observed",
             []),
            ("lockfiles", 0.30, bool(lockfiles),
             f"lockfiles pinning resolved versions: {', '.join(lockfiles)}"
             if lockfiles else "no lockfile observed; resolved versions are not pinned",
             []),
            ("parsed_dependencies", 0.20, parsed_dep_count > 0,
             f"{parsed_dep_count} declared dependencies parsed"
             if parsed_dep_count else "no declared dependencies parsed",
             []),
        ],
        f"Repository '{repo_name}' shows no dependency-management evidence.",
    )

    dimensions["ci_cd"] = _build_dimension(
        "ci_cd",
        [
            ("ci_present", 0.50, ci_present,
             "CI configuration present (GitHub Actions workflows)"
             if bool(inspection.get("has_workflows"))
             else ("non-GitHub CI configuration present" if has_ci_config
                   else "no CI configuration observed"),
             (workflow_files or ci_config_files)[:6]),
            ("multiple_workflows", 0.20, len(workflow_files) >= 2,
             f"{len(workflow_files)} workflow files"
             if len(workflow_files) >= 2 else "single or no workflow file observed",
             workflow_files),
            ("ci_test_execution", 0.30, bool(ci_test_commands),
             f"CI executes tests via: {', '.join(ci_test_commands)}"
             if ci_test_commands else "no test execution step observed in sampled CI configuration",
             ci_test_files),
        ],
        f"Repository '{repo_name}' shows no CI/CD evidence.",
    )

    dimensions["containerization"] = _build_dimension(
        "containerization",
        [
            ("dockerfile", 0.40, has_dockerfile,
             f"Dockerfile observed: {', '.join(dockerfile_files)}"
             if has_dockerfile else "no Dockerfile observed",
             dockerfile_files),
            ("compose", 0.30, has_compose,
             f"compose orchestration observed: {', '.join(compose_files)}"
             if has_compose else "no compose orchestration observed",
             compose_files),
            ("multistage_build", 0.15, multistage,
             "multi-stage Docker build observed"
             if multistage else "no multi-stage Docker build observed in sampled configuration",
             [f for f in sampled_configs if "dockerfile" in f.lower()][:3]),
            ("dockerignore", 0.15, bool(dockerignore_files),
             f".dockerignore observed: {', '.join(dockerignore_files)}"
             if dockerignore_files else "no .dockerignore observed",
             dockerignore_files),
        ],
        f"Repository '{repo_name}' shows no containerization evidence.",
    )

    security_reason_suffix = (
        " Static inspection describes observed practices only; it cannot "
        "guarantee security, and absence of findings is not proof of safety."
    )
    dimensions["security_practices"] = _build_dimension(
        "security_practices",
        [
            ("environment_templates", 0.30, bool(env_example_files),
             f"environment templates observed: {', '.join(env_example_files)}"
             if env_example_files else "no environment template observed",
             env_example_files),
            ("auth_libraries", 0.30, bool(auth_libs),
             f"authentication/authorization libraries: {', '.join(auth_libs)}"
             if auth_libs else "no authentication/authorization library observed",
             []),
            ("gitignore", 0.20, gitignore_present,
             ".gitignore present (helps keep secrets out of commits)"
             if gitignore_present else "no .gitignore observed at repository root",
             ([".gitignore"] if gitignore_present else [])),
            ("non_root_container_user", 0.20, nonroot_user,
             "container runs as a non-root USER"
             if nonroot_user else "no non-root container USER observed in sampled configuration",
             [f for f in sampled_configs if "dockerfile" in f.lower()][:3]
             if nonroot_user else []),
        ],
        f"Repository '{repo_name}' shows no security-practice evidence." + security_reason_suffix,
        confidence_cap="medium",
    )
    if dimensions["security_practices"]["present"]:
        dimensions["security_practices"]["reason"] += security_reason_suffix

    dimensions["code_maintainability"] = _build_dimension(
        "code_maintainability",
        [
            ("lint_format_config", 0.35, bool(lint_files),
             f"linter/formatter configuration: {', '.join(lint_files)}"
             if lint_files else "no linter/formatter configuration observed",
             lint_files),
            ("static_typing", 0.35, typing_present,
             "static type annotations observed in implementation"
             if typing_present else "no static type annotations observed in sampled files",
             typing_files),
            ("modular_layout", 0.30, len(module_dirs) >= 3,
             f"modular layout across {len(module_dirs)} top-level areas"
             if len(module_dirs) >= 3 else "no broad modular layout observed",
             []),
        ],
        f"Repository '{repo_name}' shows no maintainability evidence in sampled files.",
    )

    ordered = {dim: dimensions[dim] for dim in DIMENSIONS}
    return {
        "version": MODEL_VERSION,
        "repository": str(inspection.get("full_name") or repo_name),
        "dimensions": ordered,
        "summary": summarize_practices({"dimensions": ordered}),
    }


def summarize_practices(practices: Any) -> str:
    """One-paragraph human-readable summary of a practices report."""
    try:
        dimensions = (practices or {}).get("dimensions") or {}
    except AttributeError:
        return "No engineering-practice evidence analyzed."
    strong = [d for d, r in dimensions.items()
              if isinstance(r, dict) and r.get("present") and float(r.get("score", 0) or 0) >= 0.5]
    weak = [d for d, r in dimensions.items()
            if isinstance(r, dict) and r.get("present") and 0 < float(r.get("score", 0) or 0) < 0.5]
    absent = [d for d in DIMENSIONS if d not in strong and d not in weak
              and isinstance(dimensions.get(d), dict)]
    parts = []
    if strong:
        parts.append("established practice in " + ", ".join(strong))
    if weak:
        parts.append("emerging practice in " + ", ".join(weak))
    if absent:
        parts.append("no evidence observed for " + ", ".join(absent))
    if not parts:
        return "No engineering-practice evidence analyzed."
    return "Engineering practices: " + "; ".join(parts) + "."


def aggregate_practices(items: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Combine per-repository practice reports into a profile-level summary.
    Deterministic: per dimension, the best observed score wins; evidence
    repositories union; findings merge per indicator (present OR, files
    union capped). Never invents evidence for repositories not analyzed.
    """
    cleaned = [(str(name), rep) for (name, rep) in (items or [])
               if isinstance(rep, dict) and isinstance(rep.get("dimensions"), dict)]
    dimensions: Dict[str, Dict[str, Any]] = {}
    for dim in DIMENSIONS:
        present_repos: List[str] = []
        best_score = 0.0
        best_reason = ""
        best_confidence = "low"
        merged: Dict[str, Dict[str, Any]] = {}
        order = {"low": 0, "medium": 1, "high": 2}
        for repo_name, rep in cleaned:
            entry = rep["dimensions"].get(dim)
            if not isinstance(entry, dict):
                continue
            try:
                score = float(entry.get("score", 0.0) or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            if entry.get("present"):
                if repo_name not in present_repos:
                    present_repos.append(repo_name)
                if score > best_score:
                    best_score = score
                    best_reason = str(entry.get("reason", ""))
                    best_confidence = str(entry.get("confidence", "low"))
            for finding in (entry.get("findings") or []):
                if not isinstance(finding, dict) or not finding.get("indicator"):
                    continue
                slot = merged.setdefault(str(finding["indicator"]), {
                    "indicator": str(finding["indicator"]),
                    "present": False,
                    "detail": "",
                    "files": [],
                })
                if finding.get("present"):
                    slot["present"] = True
                    slot["detail"] = str(finding.get("detail") or slot["detail"])
                for f in (finding.get("files") or []):
                    if str(f) not in slot["files"] and len(slot["files"]) < 6:
                        slot["files"].append(str(f))
        if present_repos:
            confidence = "high" if len(present_repos) >= 2 else best_confidence
            if dim == "security_practices" and order.get(confidence, 0) > order["medium"]:
                confidence = "medium"
            dimensions[dim] = {
                "dimension": dim,
                "score": round(best_score, 3),
                "confidence": confidence,
                "present": True,
                "repositories": present_repos[:10],
                "findings": [merged[k] for k in sorted(merged)],
                "reason": (best_reason + f" Observed in {len(present_repos)} of "
                           f"{len(cleaned)} repositories.").strip(),
            }
        else:
            dimensions[dim] = {
                "dimension": dim,
                "score": 0.0,
                "confidence": "low",
                "present": False,
                "repositories": [],
                "findings": [],
                "reason": "No evidence observed in analyzed repositories.",
            }
    return {
        "version": MODEL_VERSION,
        "repositories_analyzed": len(cleaned),
        "dimensions": dimensions,
        "summary": summarize_practices({"dimensions": dimensions}),
    }

