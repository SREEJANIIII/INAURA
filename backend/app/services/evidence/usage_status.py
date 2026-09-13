"""
Technology usage-status detection for GitHub evidence (Phase 3).

Distinguishes, per canonical skill and repository:

  mentioned    - technology appears in README/description/topics only.
  declared     - technology is declared as a dependency (manifest) but never
                 imported or used in sampled implementation.
  imported     - technology is imported in >=1 sampled source file but no API
                 usage pattern is observed.
  used         - technology's API is actually exercised (framework calls,
                 routes, components, queries, manifests, workflow steps).
  substantial  - technology is used across multiple implementation sites with
                 corroborating patterns (and usually tests/workflows).

The status maps onto the existing EvidenceDepth system (mentioned->L1,
declared->L2, imported/used->L3, substantial->L4) so all downstream stages
(ExtractedSignal, signal_extractor, skill_engine, analysis_run_service) keep
working unchanged. Status is recorded as signal metadata; it never replaces
the proficiency formula.

Safety rules (no overclaim, no side effects):
- Local static inspection only: regular expressions over fetched file text.
  INAURA never executes arbitrary repository code and never sends repository
  source code to external services.
- Comments, documentation, string literals (where inappropriate), generated,
  lock, and vendored files must not count as usage. Import-style patterns
  that inherently live inside string literals (``from 'next/link'``) are
  matched on comment-stripped text; every other API pattern is matched on
  comment- AND string-stripped text.
- No technology is invented here: every pattern-table key must resolve
  through the canonical skill taxonomy (see validate_patterns_against_
  taxonomy, exercised by tests). The table stays focused (~40 patterns for
  8 skills); hundreds of technologies are deliberately NOT hard-coded.
"""

from typing import Dict, List, Tuple
import re

# Internal usage-status concept. Names are chosen to read naturally in
# metadata ("usage_status": "used") and to map 1:1 onto EvidenceDepth.
MENTIONED = "mentioned"
DECLARED = "declared"
IMPORTED = "imported"
USED = "used"
SUBSTANTIAL = "substantial"
NONE = "none"

STATUS_ORDER: Tuple[str, ...] = (NONE, MENTIONED, DECLARED, IMPORTED, USED, SUBSTANTIAL)

# Equivalent EvidenceDepth level for each status (existing architecture).
STATUS_TO_DEPTH: Dict[str, int] = {
    NONE: 0,
    MENTIONED: 1,
    DECLARED: 2,
    IMPORTED: 3,
    USED: 3,
    SUBSTANTIAL: 4,
}

# Diagnostic influence weight of a status tier. Kept separate from
# source_reliability and signal_strength: it describes how strongly a file's
# evidence was demonstrated, it never directly becomes a skill score.
STATUS_WEIGHTS: Dict[str, float] = {
    NONE: 0.0,
    MENTIONED: 0.25,
    DECLARED: 0.5,
    IMPORTED: 0.65,
    USED: 0.8,
    SUBSTANTIAL: 1.0,
}


def status_to_depth(status: str) -> int:
    """Map a usage status onto its equivalent EvidenceDepth integer."""
    return STATUS_TO_DEPTH.get(str(status or "").lower(), 0)


def status_weight(status: str) -> float:
    """Diagnostic influence weight for a status (separate from scoring)."""
    return STATUS_WEIGHTS.get(str(status or "").lower(), 0.0)


def classify_usage_status(
    *,
    has_mention: bool = False,
    has_dependency: bool = False,
    import_count: int = 0,
    has_api_usage: bool = False,
    distinct_patterns: int = 0,
    usage_files: int = 0,
    implementation_files: int = 0,
    has_tests_or_workflows: bool = False,
) -> str:
    """
    Deterministic usage status from layered repository evidence.

    - mentioned:    docs mention only.
    - declared:     manifest dependency, never imported/used.
    - imported:     imported in >=1 file, no API usage observed.
    - used:         API usage observed in >=1 file.
    - substantial: multi-file/multi-pattern usage, usually corroborated.
    """
    try:
        imports = int(import_count or 0)
    except (TypeError, ValueError):
        imports = 0
    try:
        patterns = int(distinct_patterns or 0)
    except (TypeError, ValueError):
        patterns = 0
    try:
        files = int(usage_files or 0)
    except (TypeError, ValueError):
        files = 0
    try:
        impl_files = int(implementation_files or 0)
    except (TypeError, ValueError):
        impl_files = 0

    api_used = bool(has_api_usage) or patterns >= 1 or files >= 1
    if api_used or imports >= 1:
        multi_file = files >= 2 or impl_files >= 3
        multi_signal = imports >= 3 or patterns >= 2
        corroborated = bool(has_tests_or_workflows)
        if (multi_file and multi_signal) or (multi_signal and corroborated) or files >= 3:
            return SUBSTANTIAL
        if api_used:
            return USED
        return IMPORTED
    if bool(has_dependency):
        return DECLARED
    if bool(has_mention):
        return MENTIONED
    return NONE


# ---------------------------------------------------------------------------
# String-literal stripping (for API-usage matching where literals are noise).
# ---------------------------------------------------------------------------

_STRING_LITERAL_RE = re.compile(
    r"('''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\"|"      # triple-quoted blocks
    r"'(?:[^'\\\n]|\\.)*'|"                        # single-quoted
    r'"(?:[^"\\\n]|\\.)*"|'                        # double-quoted
    r"`(?:[^`\\]|\\.)*`)",                         # backticks (JS/TS/Go)
    re.S,
)


def strip_string_literals(text: str) -> str:
    """
    Remove string-literal contents so technology words inside strings do not
    count as API usage (e.g. ``print("call model.fit()")`` or
    ``x = "tensorflow is great"``).

    Import-style patterns (``require('express')``) inherently live inside
    string literals and are therefore matched BEFORE stripping; every other
    API pattern is matched AFTER stripping.
    """
    if not text:
        return ""
    try:
        return _STRING_LITERAL_RE.sub('""', str(text))
    except Exception:
        return str(text)


# ---------------------------------------------------------------------------
# Taxonomy-constrained API-usage patterns (new for Phase 3).
#
# Keys MUST be canonical taxonomy display names (validated by
# validate_patterns_against_taxonomy). Each pattern requires an API-shaped
# construct (calls, decorators, annotations, queries, manifests, workflow
# keys) -- never a bare keyword.
# ---------------------------------------------------------------------------

# Pattern ids in this set are matched on comment-stripped text WITH string
# literals intact, because the construct itself contains a quoted module
# specifier. All other ids are matched on comment- AND string-stripped text.
STRING_SENSITIVE_PATTERN_IDS = frozenset({
    "django_path",
})

API_USAGE_PATTERNS: Dict[str, List[Tuple[str, str]]] = {
    "Deep Learning": [
        ("tf_keras_model", r"\btf\s*\.\s*keras\s*\.\s*Sequential\s*\("),
        ("keras_layer", r"\blayers\s*\.\s*(?:Dense|Conv2D|Conv1D|LSTM|GRU|Embedding|Dropout|Flatten|MaxPooling2D|BatchNormalization)\s*\("),
        ("model_lifecycle", r"\bmodel\s*\.\s*(?:compile|fit|evaluate|predict|save)\s*\("),
        ("torch_module_def", r"\(\s*(?:torch\s*\.\s*)?nn\s*\.\s*Module\s*\)"),
        ("torch_layer", r"\bnn\s*\.\s*(?:Linear|Conv2d|Conv1d|LSTM|GRU|Embedding|Dropout|BatchNorm\d*d|Sequential|ModuleList|ConvTranspose2d)\s*\("),
        ("torch_data", r"\b(?:DataLoader|TensorDataset)\s*\("),
        ("torch_optim", r"\boptim\s*\.\s*(?:Adam|SGD|AdamW|RMSprop|Adagrad)\s*\("),
        ("torch_functional", r"\bF\s*\.\s*(?:relu|softmax|cross_entropy|mse_loss|nll_loss)\s*\("),
    ],
    "Scikit-learn": [
        ("sklearn_estimator", r"\b(?:RandomForest(?:Regressor|Classifier)|LogisticRegression|LinearRegression|SV[CR]|KMeans|SVC|SVR|GradientBoosting(?:Regressor|Classifier)|DecisionTree(?:Regressor|Classifier)|MLP(?:Regressor|Classifier))\s*\("),
        ("sklearn_preprocessing", r"\b(?:StandardScaler|MinMaxScaler|OneHotEncoder|LabelEncoder|SimpleImputer|TfidfVectorizer|CountVectorizer)\s*\("),
        ("sklearn_model_selection", r"\b(?:train_test_split|GridSearchCV|RandomizedSearchCV|cross_val_score|StratifiedKFold|KFold)\s*\("),
        ("sklearn_pipeline", r"\b(?:Pipeline|ColumnTransformer|make_pipeline|FeatureUnion)\s*\("),
        ("sklearn_metrics", r"\b(?:accuracy_score|f1_score|roc_auc_score|mean_squared_error|mean_absolute_error|classification_report|confusion_matrix|r2_score|precision_score|recall_score)\s*\("),
        ("sklearn_namespace", r"\bsklearn\s*\.\s*(?:pipeline|ensemble|preprocessing|model_selection|metrics|compose|feature_extraction)\b"),
    ],
    "Spring Boot": [
        ("rest_controller", r"@\s*(?:RestController|Controller)\b"),
        ("service_component", r"@\s*(?:Service|Repository|Component)\b"),
        ("entity", r"@\s*Entity\b"),
        ("dependency_injection", r"@\s*(?:Autowired|Value)\b"),
        ("web_mapping", r"@\s*(?:GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\b"),
        ("response_entity", r"\bResponseEntity\s*(?:<|\.|\()"),
        ("application_run", r"\bSpringApplication\s*\.\s*run\s*\("),
        ("data_repository", r"\b(?:JpaRepository|CrudRepository|PagingAndSortingRepository)\b"),
        ("boot_application", r"@\s*SpringBootApplication\b"),
    ],
    "REST APIs": [
        ("django_model", r"\(\s*(?:models\s*\.\s*)?Model\s*\)"),
        ("django_serializer", r"\bModelSerializer\b"),
        ("django_urls", r"\burlpatterns\s*="),
        ("django_path", r"""\bpath\s*\(\s*['"]"""),
        ("django_orm", r"\bobjects\s*\.\s*(?:filter|get|create|all|exclude|order_by|annotate)\s*\("),
        ("django_response", r"\bJsonResponse\s*\("),
    ],
    "SQL": [
        ("sql_select", r"\bSELECT\b.+?\bFROM\b"),
        ("sql_insert", r"\bINSERT\s+INTO\b"),
        ("sql_update", r"\bUPDATE\b.+?\bSET\b"),
        ("sql_delete", r"\bDELETE\s+FROM\b"),
        ("sql_ddl", r"\bCREATE\s+TABLE\b"),
        ("sql_join", r"\bJOIN\b.+?\bON\b"),
        ("sql_cursor", r"\bcursor\s*\.\s*execute\s*\("),
    ],
    "MySQL": [
        ("mysql_client", r"\bmysql\s*\.\s*create(?:Connection|Pool)\s*\("),
        ("pymysql_connect", r"\bpymysql\s*\.\s*connect\s*\("),
        ("mysqldb_connect", r"\bMySQLdb\s*\.\s*connect\s*\("),
    ],
    "Redis": [
        ("redis_client", r"\bredis\s*\.\s*(?:Redis|StrictRedis|createClient|Cluster)\s*[\(\.]"),
        ("redis_commands", r"\.(?:setex|hset|hget|hgetall|lpush|rpush|zadd|sadd|publish|expire|setnx)\s*\("),
        ("ioredis_client", r"\bnew\s+Redis\s*\("),
    ],
    "CI/CD": [
        ("workflow_trigger", r"(?m)^\s*on\s*:\s*(?:push|pull_request|\[)"),
        ("workflow_jobs", r"(?m)^\s*jobs\s*:"),
        ("workflow_runner", r"\bruns-on\s*:"),
        ("workflow_action", r"\buses\s*:\s*actions/"),
        ("workflow_run_step", r"(?m)^\s*(?:-\s*)?run\s*:"),
    ],
}


def validate_patterns_against_taxonomy() -> List[str]:
    """
    Return pattern-table keys that do NOT resolve through the canonical skill
    taxonomy. Empty list means the table is fully taxonomy-constrained.
    """
    from ..skill_taxonomy import normalize_skill

    unmapped: List[str] = []
    for key in API_USAGE_PATTERNS.keys():
        try:
            if normalize_skill(key) != key:
                unmapped.append(key)
        except Exception:
            unmapped.append(key)
    return unmapped
