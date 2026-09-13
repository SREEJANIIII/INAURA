"""
Phase 3: actual technology usage detection tests.

Verifies the mentioned < declared < imported < used < substantial chain
(usage_status metadata, EvidenceDepth-compatible), taxonomy-constrained
API-usage patterns, string-literal/comment safety, generated/vendor
exclusion, false-positive names, framework-specific usage, and downstream
compatibility (ExtractedSignal, signal_extractor, skill_engine,
analysis_run_service). Builds on Phases 1-2; does not replace them.

Conceptual framing (no overclaim):
"INAURA performs repository-level code and artifact inspection to extract
evidence of demonstrated technical skills." Matching is local static
inspection only: repository code is never executed and never sent to
external services.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from app.services.evidence.base import EvidenceDepth
from app.services.evidence.github import (
    GitHubProvider,
    detect_usage_patterns,
    extract_import_tokens,
)
from app.services.evidence.usage_status import (
    MENTIONED,
    DECLARED,
    IMPORTED,
    USED,
    SUBSTANTIAL,
    NONE,
    STATUS_TO_DEPTH,
    classify_usage_status,
    status_to_depth,
    status_weight,
    strip_string_literals,
    validate_patterns_against_taxonomy,
)
from app.services import analysis_run_service as ars
from app.services import signal_extractor as se
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
# 1. Usage-status concept: taxonomy of demonstration, depth-compatible
# ---------------------------------------------------------------------------

def test_pattern_table_is_taxonomy_constrained():
    # No invented skills: every pattern key resolves via the canonical taxonomy.
    assert validate_patterns_against_taxonomy() == []


def test_status_maps_onto_evidence_depth():
    assert STATUS_TO_DEPTH == {
        NONE: 0,
        MENTIONED: 1,
        DECLARED: 2,
        IMPORTED: 3,
        USED: 3,
        SUBSTANTIAL: 4,
    }
    assert status_to_depth(MENTIONED) == EvidenceDepth.LEVEL_1_MENTION
    assert status_to_depth(DECLARED) == EvidenceDepth.LEVEL_2_CONFIG
    assert status_to_depth(IMPORTED) == EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert status_to_depth(USED) == EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert status_to_depth(SUBSTANTIAL) == EvidenceDepth.LEVEL_4_SUBSTANTIAL
    assert status_weight(MENTIONED) < status_weight(DECLARED) < status_weight(IMPORTED)
    assert status_weight(IMPORTED) < status_weight(USED) < status_weight(SUBSTANTIAL)


def test_classify_usage_status_ladder():
    assert classify_usage_status() == NONE
    assert classify_usage_status(has_mention=True) == MENTIONED
    assert classify_usage_status(has_mention=True, has_dependency=True) == DECLARED
    assert classify_usage_status(has_dependency=True, import_count=1) == IMPORTED
    assert classify_usage_status(import_count=2, has_dependency=True) == IMPORTED
    assert classify_usage_status(import_count=1, has_api_usage=True) == USED
    assert classify_usage_status(distinct_patterns=1, usage_files=1) == USED
    assert classify_usage_status(
        import_count=4, distinct_patterns=2, usage_files=3, has_tests_or_workflows=True
    ) == SUBSTANTIAL
    # Deterministic.
    kwargs = dict(import_count=2, distinct_patterns=1, usage_files=2)
    assert classify_usage_status(**kwargs) == classify_usage_status(**kwargs)


# ---------------------------------------------------------------------------
# 2. TensorFlow chain: mentioned < declared < imported < used < substantial
# ---------------------------------------------------------------------------

_TF_DEP = {
    "name": "ml-dep",
    "languages": {},
    "root_files": ["package.json"],
    "top_files": [],
    "package_json_deps": ["tensorflow"],
    "tree_scanned": True,
}


def test_tensorflow_dependency_only_is_declared_weak():
    res = _direct("dev", "ml-dep", dict(_TF_DEP))
    sig = {s.skill: s for s in res.signals}["Deep Learning"]
    assert sig.depth == EvidenceDepth.LEVEL_2_CONFIG
    assert sig.signal_strength == pytest.approx(0.60)
    assert sig.metadata["usage_status"] == DECLARED


def test_tensorflow_import_only_is_imported():
    res = _direct("dev", "ml-imp", {
        "name": "ml-imp",
        "languages": {"Python": 8000},
        "root_files": ["requirements.txt"],
        "top_files": ["src/model.py"],
        "python_deps": ["tensorflow"],
        "import_tokens": {"tensorflow": 1},
        "source_files_sampled": ["src/model.py"],
        "tree_scanned": True,
        "ext_file_counts": {".py": 1},
    })
    sig = {s.skill: s for s in res.signals}["Deep Learning"]
    assert sig.depth == EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert sig.metadata["usage_status"] == IMPORTED


def test_tensorflow_api_usage_is_used():
    res = _direct("dev", "ml-used", {
        "name": "ml-used",
        "languages": {"Python": 20000},
        "root_files": ["requirements.txt"],
        "top_files": ["src/model.py"],
        "python_deps": ["tensorflow"],
        "import_tokens": {"tensorflow": 2},
        "source_files_sampled": ["src/model.py"],
        "usage_patterns": {"Deep Learning": {"tf_keras_model": 1, "model_lifecycle": 1}},
        "usage_files": {"Deep Learning": ["src/model.py"]},
        "tree_scanned": True,
        "ext_file_counts": {".py": 1},
    })
    sig = {s.skill: s for s in res.signals}["Deep Learning"]
    assert sig.depth == EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert sig.metadata["usage_status"] == USED
    assert "tf_keras_model" in sig.metadata["detected_usage_patterns"]
    # API usage carries strictly more information than a bare import.
    assert len(sig.metadata["detected_usage_patterns"]) >= 1


def test_tensorflow_substantial_across_files():
    res = _direct("dev", "ml-sub", {
        "name": "ml-sub",
        "languages": {"Python": 90000},
        "root_files": ["requirements.txt"],
        "top_files": ["src/model.py", "src/train.py", "src/evaluate.py",
                      "tests/test_model.py"],
        "python_deps": ["tensorflow", "pytest"],
        "import_tokens": {"tensorflow": 5, "keras": 2},
        "source_files_sampled": ["src/model.py", "src/train.py", "src/evaluate.py"],
        "usage_patterns": {"Deep Learning": {"tf_keras_model": 2, "model_lifecycle": 3}},
        "usage_files": {"Deep Learning": ["src/model.py", "src/train.py", "src/evaluate.py"]},
        "tree_scanned": True,
        "ext_file_counts": {".py": 5},
        "has_workflows": True,
    })
    sig = {s.skill: s for s in res.signals}["Deep Learning"]
    assert sig.depth == EvidenceDepth.LEVEL_4_SUBSTANTIAL
    assert sig.signal_strength == pytest.approx(0.85)
    assert sig.metadata["usage_status"] == SUBSTANTIAL
    assert len(sig.metadata["relevant_files"]) >= 2


def test_tensorflow_chain_ordering():
    dep = {s.skill: s for s in _direct("dev", "a", dict(_TF_DEP)).signals}["Deep Learning"]
    imp = {s.skill: s for s in _direct("dev", "b", {
        "name": "b", "languages": {"Python": 8000},
        "root_files": ["requirements.txt"], "top_files": ["src/model.py"],
        "python_deps": ["tensorflow"], "import_tokens": {"tensorflow": 1},
        "source_files_sampled": ["src/model.py"],
        "tree_scanned": True, "ext_file_counts": {".py": 1},
    }).signals}["Deep Learning"]
    sub = {s.skill: s for s in _direct("dev", "c", {
        "name": "c", "languages": {"Python": 90000},
        "root_files": ["requirements.txt"],
        "top_files": ["src/model.py", "src/train.py", "src/evaluate.py"],
        "python_deps": ["tensorflow", "pytest"],
        "import_tokens": {"tensorflow": 5},
        "source_files_sampled": ["src/model.py", "src/train.py", "src/evaluate.py"],
        "usage_patterns": {"Deep Learning": {"tf_keras_model": 2, "model_lifecycle": 3}},
        "usage_files": {"Deep Learning": ["src/model.py", "src/train.py", "src/evaluate.py"]},
        "tree_scanned": True, "ext_file_counts": {".py": 5},
        "has_workflows": True,
    }).signals}["Deep Learning"]
    assert dep.signal_strength < imp.signal_strength < sub.signal_strength
    assert dep.metadata["usage_status"] == DECLARED
    assert imp.metadata["usage_status"] == IMPORTED
    assert sub.metadata["usage_status"] == SUBSTANTIAL


# ---------------------------------------------------------------------------
# 3. README-only mention stays mentioned/L1
# ---------------------------------------------------------------------------

def test_readme_only_is_mentioned():
    res = _direct("dev", "notes", {
        "name": "notes", "description": "", "readme_text": "Built with TensorFlow",
        "languages": {}, "root_files": ["README.md"], "top_files": [],
        "tree_scanned": True,
    })
    sig = {s.skill: s for s in res.signals}["Deep Learning"]
    assert sig.depth == EvidenceDepth.LEVEL_1_MENTION
    assert sig.metadata["usage_status"] == MENTIONED


# ---------------------------------------------------------------------------
# 4. Comments, string literals, generated code are not usage
# ---------------------------------------------------------------------------

def test_commented_tensorflow_is_not_usage():
    text = (
        "# import tensorflow as tf\n"
        "# model = tf.keras.Sequential()\n"
        "# model.fit(X, y)\n"
        "import os\n"
    )
    assert extract_import_tokens(text).get("tensorflow") is None
    assert "Deep Learning" not in detect_usage_patterns(text)


def test_string_literals_are_not_api_usage():
    text = (
        'note = "call model.fit() after tf.keras.Sequential()"\n'
        'label = "tensorflow is great"\n'
        "import os\n"
    )
    hits = detect_usage_patterns(text)
    assert "Deep Learning" not in hits
    assert strip_string_literals('x = "model.fit()"') == 'x = ""'


def test_real_usage_survives_stripping():
    text = (
        "import tensorflow as tf\n"
        "model = tf.keras.Sequential()\n"
        "model.fit(X_train, y_train, epochs=5)\n"
        "model.evaluate(X_test, y_test)\n"
    )
    assert extract_import_tokens(text).get("tensorflow") == 1
    hits = detect_usage_patterns(text)
    assert "tf_keras_model" in hits["Deep Learning"]
    assert "model_lifecycle" in hits["Deep Learning"]


def test_generated_and_lock_files_cannot_inflate():
    res = _direct("dev", "vendored", {
        "name": "vendored", "description": "",
        "languages": {}, "root_files": ["package.json"],
        "top_files": ["node_modules/react/index.js", "dist/bundle.min.js"],
        "import_tokens": {"react": 5, "tensorflow": 4},
        "source_files_sampled": ["node_modules/react/index.js", "dist/bundle.min.js"],
        "usage_files": {"React": ["node_modules/react/index.js"],
                        "Deep Learning": ["dist/bundle.min.js"]},
        "tree_scanned": True, "ext_file_counts": {},
    })
    by_skill = {s.skill: s for s in res.signals}
    for skill in ("React", "Deep Learning"):
        assert skill not in by_skill or by_skill[skill].depth <= EvidenceDepth.LEVEL_2_CONFIG


# ---------------------------------------------------------------------------
# 5. False-positive technology names
# ---------------------------------------------------------------------------

def test_springfield_is_not_spring_boot():
    res = _direct("dev", "lib", {
        "name": "lib", "languages": {}, "root_files": ["package.json"],
        "top_files": [], "package_json_deps": ["springfield"],
        "tree_scanned": True,
    })
    assert "Spring Boot" not in {s.skill for s in res.signals}
    # Raw import tokens are unmapped strings; the false-positive guard is that
    # they never resolve to a canonical skill through the taxonomy.
    from app.services.evidence.github import import_skill_counts
    tokens = extract_import_tokens("from springfield import beans")
    assert "Spring Boot" not in import_skill_counts(tokens)


def test_contest_and_latest_are_not_testing():
    res = _direct("dev", "web", {
        "name": "web", "languages": {"Python": 12000},
        "root_files": ["requirements.txt"], "top_files": ["app.py"],
        "python_deps": ["contest", "latest"],
        "tree_scanned": True, "ext_file_counts": {".py": 1},
    })
    assert "Testing" not in {s.skill for s in res.signals}


def test_unrelated_filename_is_at_most_mentioned():
    res = _direct("dev", "notes", {
        "name": "notes", "description": "my tensorflow notes file",
        "readme_text": "tensorflow study notes",
        "languages": {}, "root_files": ["README.md"],
        "top_files": ["tensorflow_notes.txt"],
        "tree_scanned": True,
    })
    by_skill = {s.skill: s for s in res.signals}
    assert "Deep Learning" not in by_skill or \
        by_skill["Deep Learning"].depth <= EvidenceDepth.LEVEL_1_MENTION


# ---------------------------------------------------------------------------
# 6. Framework-specific usage (source-text level)
# ---------------------------------------------------------------------------

def test_spring_annotations_detected():
    text = (
        "@RestController\n@RequestMapping(\"/api/users\")\n"
        "public class UserController {\n"
        "  @Autowired private UserService service;\n"
        "  @GetMapping(\"/{id}\")\n"
        "  public ResponseEntity<User> get(@PathVariable Long id) { return service.find(id); }\n"
        "}\n@SpringBootApplication\npublic class App { public static void main(String[] a) { SpringApplication.run(App.class, a); } }\n"
    )
    hits = detect_usage_patterns(text)
    assert "rest_controller" in hits["Spring Boot"]
    assert "web_mapping" in hits["Spring Boot"]
    assert "boot_application" in hits["Spring Boot"]
    assert "application_run" in hits["Spring Boot"]


def test_django_usage_detected():
    text = (
        "from django.db import models\n"
        "class Post(models.Model):\n    title = models.CharField(max_length=200)\n"
        "urlpatterns = [path('posts/', views.PostList.as_view()), path('admin/', admin.site.urls)]\n"
        "def listing(request):\n    qs = Post.objects.filter(published=True)\n    return JsonResponse({'count': qs.count()})\n"
    )
    hits = detect_usage_patterns(text)
    assert "django_model" in hits["REST APIs"]
    assert "django_urls" in hits["REST APIs"]
    assert "django_path" in hits["REST APIs"]
    assert "django_orm" in hits["REST APIs"]
    assert "django_response" in hits["REST APIs"]


def test_sql_queries_detected():
    text = (
        "cursor.execute(\"SELECT id, name FROM users WHERE active = 1\")\n"
        "cursor.execute(\"INSERT INTO audit_log (user_id) VALUES (%s)\", (uid,))\n"
    )
    hits = detect_usage_patterns(text)
    # SQL keywords inside string literals must not count; cursor.execute does.
    assert "sql_cursor" in hits["SQL"]


def test_sql_select_outside_strings_detected():
    assert "sql_select" in detect_usage_patterns("rows = SELECT id FROM users")["SQL"]


def test_dockerfile_usage_detected():
    text = "FROM python:3.11-slim\nWORKDIR /app\nCOPY . .\nRUN pip install -r requirements.txt\nCMD [\"python\", \"app.py\"]\n"
    hits = detect_usage_patterns(text)
    assert "docker_from" in hits["Docker"]
    assert "docker_run" in hits["Docker"]


def test_kubernetes_manifest_detected():
    text = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\n"
    hits = detect_usage_patterns(text)
    assert "k8s_api" in hits["Kubernetes"]
    assert "k8s_kind" in hits["Kubernetes"]


def test_cicd_workflow_detected():
    text = (
        "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/checkout@v4\n      - run: pytest -q\n"
    )
    hits = detect_usage_patterns(text)
    assert "workflow_trigger" in hits["CI/CD"]
    assert "workflow_jobs" in hits["CI/CD"]
    assert "workflow_runner" in hits["CI/CD"]
    assert "workflow_action" in hits["CI/CD"]
    assert "workflow_run_step" in hits["CI/CD"]


def test_database_clients_detected():
    assert "mysql_client" in detect_usage_patterns("const db = mysql.createConnection(cfg);")["MySQL"]
    assert "pymysql_connect" in detect_usage_patterns("conn = pymysql.connect(host='db');")["MySQL"]
    assert "redis_client" in detect_usage_patterns("client = redis.Redis(host='localhost');")["Redis"]
    assert "redis_commands" in detect_usage_patterns("client.setex(key, 60, value);")["Redis"]


def test_express_and_fastapi_routes_detected():
    assert "express_init" in detect_usage_patterns("const app = express();")["Express"]
    assert "route_handler" in detect_usage_patterns("app.get('/users', handler);")["Express"]
    assert "fastapi_app" in detect_usage_patterns("app = FastAPI();")["REST APIs"]
    assert "route_decorator" in detect_usage_patterns('@app.get("/items")\ndef read(): ...')["REST APIs"]


def test_scikit_learn_api_detected():
    text = (
        "from sklearn.model_selection import train_test_split\n"
        "X_train, X_test, y_train, y_test = train_test_split(X, y)\n"
        "scaler = StandardScaler()\n"
        "clf = RandomForestClassifier(n_estimators=100)\n"
        "print(accuracy_score(y_test, clf.predict(X_test)))\n"
    )
    hits = detect_usage_patterns(text)
    assert "sklearn_model_selection" in hits["Scikit-learn"]
    assert "sklearn_preprocessing" in hits["Scikit-learn"]
    assert "sklearn_estimator" in hits["Scikit-learn"]
    assert "sklearn_metrics" in hits["Scikit-learn"]


# ---------------------------------------------------------------------------
# 7. Framework integration: Spring + SQL through the provider
# ---------------------------------------------------------------------------

def test_spring_boot_used_through_provider():
    res = _direct("dev", "svc", {
        "name": "svc", "description": "",
        "languages": {"Java": 60000}, "root_files": ["pom.xml"],
        "top_files": ["src/main/java/com/x/UserController.java"],
        "java_frameworks": ["spring_boot"], "java_file_count": 4,
        "import_tokens": {"org.springframework.boot.SpringApplication": 1},
        "source_files_sampled": ["src/main/java/com/x/UserController.java"],
        "usage_patterns": {"Spring Boot": {"rest_controller": 1}},
        "usage_files": {"Spring Boot": ["src/main/java/com/x/UserController.java"]},
        "tree_scanned": True,
    })
    by_skill = {s.skill: s for s in res.signals}
    assert "Spring Boot" in by_skill
    assert by_skill["Spring Boot"].metadata["usage_status"] == USED
    assert by_skill["Spring Boot"].metadata["detected_usage_patterns"]


def test_sql_used_through_provider():
    res = _direct("dev", "db", {
        "name": "db", "description": "",
        "languages": {"SQL": 25000}, "root_files": ["schema.sql"],
        "top_files": ["db/schema.sql", "db/queries.sql"],
        "source_files_sampled": ["db/schema.sql", "db/queries.sql"],
        "usage_patterns": {"SQL": {"sql_select": 2, "sql_ddl": 1}},
        "usage_files": {"SQL": ["db/schema.sql", "db/queries.sql"]},
        "tree_scanned": True, "ext_file_counts": {".sql": 2},
    })
    by_skill = {s.skill: s for s in res.signals}
    assert "SQL" in by_skill
    assert by_skill["SQL"].depth >= EvidenceDepth.LEVEL_3_IMPLEMENTATION
    assert by_skill["SQL"].metadata["usage_status"] in (USED, SUBSTANTIAL)


def test_config_infra_usage_from_config_text():
    res = _direct("dev", "ops", {
        "name": "ops", "description": "",
        "languages": {}, "root_files": ["Dockerfile", "docker-compose.yml"],
        "top_files": ["Dockerfile", "docker-compose.yml"],
        "config_text": "FROM python:3.11-slim\nRUN pip install -r requirements.txt\n",
        "config_files_sampled": ["Dockerfile"],
        "tree_scanned": True,
    })
    by_skill = {s.skill: s for s in res.signals}
    assert "Docker" in by_skill
    assert by_skill["Docker"].metadata["detected_usage_patterns"]


# ---------------------------------------------------------------------------
# 8. Multiple implementation sites + no double counting
# ---------------------------------------------------------------------------

def test_multiple_sites_no_double_counting():
    res = _direct("dev", "multi", {
        "name": "multi", "description": "",
        "languages": {"Python": 60000}, "root_files": ["requirements.txt"],
        "top_files": ["src/a.py", "src/b.py", "src/c.py"],
        "python_deps": ["tensorflow"], "import_tokens": {"tensorflow": 6},
        "source_files_sampled": ["src/a.py", "src/b.py", "src/c.py"],
        "usage_patterns": {"Deep Learning": {"tf_keras_model": 2, "model_lifecycle": 3}},
        "usage_files": {"Deep Learning": ["src/a.py", "src/b.py", "src/c.py"]},
        "tree_scanned": True, "ext_file_counts": {".py": 3},
        "has_workflows": True,
    })
    names = [s.skill for s in res.signals]
    assert len(names) == len(set(names))
    sig = {s.skill: s for s in res.signals}["Deep Learning"]
    assert sig.depth == EvidenceDepth.LEVEL_4_SUBSTANTIAL
    assert sig.metadata["usage_status"] == SUBSTANTIAL
    assert sig.signal_strength <= EvidenceDepth.get_strength_for_depth(
        EvidenceDepth.LEVEL_4_SUBSTANTIAL) + 1e-9


# ---------------------------------------------------------------------------
# 9. Compatibility: signals flow through extractor, engine, run service
# ---------------------------------------------------------------------------

def test_signals_remain_compatible_downstream():
    owner = "usage_flow"
    repos = [_inspection_repo(owner, "ml", {
        "name": "ml", "languages": {"Python": 40000},
        "root_files": ["requirements.txt"],
        "top_files": ["src/model.py", "src/train.py"],
        "python_deps": ["tensorflow"],
        "import_tokens": {"tensorflow": 3},
        "source_files_sampled": ["src/model.py", "src/train.py"],
        "usage_patterns": {"Deep Learning": {"tf_keras_model": 1, "model_lifecycle": 2}},
        "usage_files": {"Deep Learning": ["src/model.py", "src/train.py"]},
        "tree_scanned": True, "ext_file_counts": {".py": 2},
    })]
    verification = _verify_mock(owner, repos)
    assert verification.status == "verified"
    by_skill = {s.skill: s for s in verification.signals}
    assert "Deep Learning" in by_skill
    assert by_skill["Deep Learning"].metadata["usage_status"] in (USED, SUBSTANTIAL)

    evidence = [{
        "id": "ev-github-ml",
        "evidence_type": "github",
        "source_url": f"https://github.com/{owner}",
        "mock_inspection": {
            "name": "ml",
            "languages": {"Python": 40000},
            "root_files": ["requirements.txt"],
            "top_files": ["src/model.py"],
            "python_deps": ["tensorflow"],
            "import_tokens": {"tensorflow": 2},
            "source_files_sampled": ["src/model.py"],
            "usage_patterns": {"Deep Learning": {"model_lifecycle": 1}},
            "usage_files": {"Deep Learning": ["src/model.py"]},
            "tree_scanned": True,
            "ext_file_counts": {".py": 1},
        },
    }]
    signals = se.extract_signals(evidence, [], [])
    dl_signals = [s for s in signals if s["canonical_name"] == "Deep Learning"]
    assert dl_signals
    for sig in dl_signals:
        for key in ("skill", "canonical_name", "signal_strength", "signal_value",
                    "source", "source_type", "source_reliability", "reason",
                    "explanation", "metadata"):
            assert key in sig
    prof, _, _, _ = skill_engine.proficiency(dl_signals)
    assert 0.0 < prof <= 0.85 + 1e-9

    raw = ars.extract_skill_signals(evidence, [], [])
    grouped = ars.aggregate_skills(ars.normalize_signals(raw, None))
    assert "Deep Learning" in grouped
