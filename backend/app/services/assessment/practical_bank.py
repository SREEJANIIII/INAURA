"""
Curated practical (work-sample) task bank — Layer 2 of skill assessment.

Design constraints (mirror the MCQ question bank):
  * Deterministic structural grading only — no LLM is involved in scoring.
  * Checks look for required solution structure (clauses, constructs, edge-case
    handling), not exact output. Untrusted code is NEVER executed server-side.
  * The bank is content, not logic: selection, grading and scoring code below
    is fully generic, so adding a skill means adding tasks, never code.
  * Skill identity always goes through the canonical taxonomy.

Prototype instrument: a structural check is a weak proxy for real ability; it
is used as one evidence source with an honest ``prototype_instrument`` flag,
never as a verdict.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import re

from ..skill_taxonomy import normalize_skill, normalize_skill_slug

PRACTICAL_VERSION = "practical-v1"

TASK_TYPES = ("coding", "sql", "debugging", "build", "analysis")


@dataclass(frozen=True)
class PracticalCheck:
    """One deterministic structural check on a submission."""

    id: str
    description: str
    dimension: str
    pattern: str  # regex, matched case-insensitively against the submission
    weight: float = 1.0


@dataclass(frozen=True)
class PracticalTask:
    """One work-sample task for a single canonical skill."""

    id: str
    skill: str  # canonical display name
    task_type: str
    title: str
    prompt: str
    starter_code: str = ""
    language: str = ""
    estimated_minutes: int = 20
    dimensions: Tuple[Tuple[str, str], ...] = ()  # (dimension_id, label)
    checks: Tuple[PracticalCheck, ...] = ()
    version: str = PRACTICAL_VERSION

    def public_dict(self) -> dict:
        """Task as sent to the client — includes the starter, never a solution."""
        return {
            "id": self.id,
            "skill": self.skill,
            "task_type": self.task_type,
            "title": self.title,
            "prompt": self.prompt,
            "starter_code": self.starter_code,
            "language": self.language,
            "estimated_minutes": self.estimated_minutes,
            "dimensions": [{"id": did, "label": label} for did, label in self.dimensions],
            "check_count": len(self.checks),
            "version": self.version,
        }


def _check(cid: str, description: str, dimension: str, pattern: str, weight: float = 1.0) -> PracticalCheck:
    return PracticalCheck(id=cid, description=description, dimension=dimension, pattern=pattern, weight=weight)


RAW_PRACTICAL_TASKS: List[PracticalTask] = [
    PracticalTask(
        id="dsa-two-sum",
        skill="Data Structures & Algorithms",
        task_type="coding",
        title="Two Sum",
        prompt=(
            "Given an array of integers nums and an integer target, return indices of the two "
            "numbers that add up to target. Assume exactly one solution exists and do not use "
            "the same element twice. Aim for better than O(n^2) time and handle edge cases "
            "(empty input, no solution) explicitly."
        ),
        starter_code="def two_sum(nums, target):\n    # Your implementation here\n    pass\n",
        language="python",
        estimated_minutes=25,
        dimensions=(
            ("correctness", "Correctness"),
            ("edge_cases", "Edge cases"),
            ("approach", "Approach & complexity"),
        ),
        checks=(
            _check("dsa-ts-def", "Defines a solution function", "correctness", r"def\s+\w+\s*\(", 1.0),
            _check("dsa-ts-return", "Returns a result", "correctness", r"\breturn\b", 1.0),
            _check("dsa-ts-loop", "Iterates over the input", "correctness", r"\b(for|while)\b", 1.0),
            _check("dsa-ts-efficient", "Uses an efficient lookup or two-pointer approach", "approach", r"(\{|\bdict\b|\bhash|\bsort\b|two.?pointer|left|right)", 1.0),
            _check("dsa-ts-edge", "Handles edge cases explicitly", "edge_cases", r"(if\s+not\b|len\s*\(|==\s*0|try\b|raise\b|return\s+(\[\]|None|-1))", 1.0),
        ),
    ),
    PracticalTask(
        id="python-debug-max",
        skill="Python",
        task_type="debugging",
        title="Fix the buggy max finder",
        prompt=(
            "The function below is supposed to return the largest number in a list, or None "
            "for an empty list, but it has bugs. Rewrite it correctly: handle the empty-list "
            "edge case, compare elements properly, and return the result."
        ),
        starter_code=(
            "def find_max(values):\n"
            "    biggest = 0\n"
            "    for v in values:\n"
            "        if v = biggest:\n"
            "            biggest = v\n"
        ),
        language="python",
        estimated_minutes=15,
        dimensions=(
            ("correctness", "Correctness"),
            ("edge_cases", "Edge cases"),
            ("implementation", "Implementation"),
        ),
        checks=(
            _check("py-dbg-def", "Defines the function", "implementation", r"def\s+find_max\s*\(", 1.0),
            _check("py-dbg-compare", "Compares with a comparison operator", "correctness", r"(>|>=|<|<=|max\s*\()", 1.0),
            _check("py-dbg-return", "Returns the result", "correctness", r"\breturn\b", 1.0),
            _check("py-dbg-empty", "Handles the empty-list edge case", "edge_cases", r"(if\s+not\b|len\s*\(.*\)\s*==\s*0|==\s*\[\]|try\b|None)", 1.0),
            _check("py-dbg-loop", "Iterates over the values", "implementation", r"\b(for|while|max\s*\()", 1.0),
        ),
    ),
    PracticalTask(
        id="sql-top-customers",
        skill="SQL",
        task_type="sql",
        title="Top customers by revenue",
        prompt=(
            "Tables: customers(id, name, country) and orders(id, customer_id, amount, status, created_at). "
            "Write a query returning the top 5 customers by total completed order amount in 2025: "
            "customer name, country, and total revenue. Filter to status = 'completed', aggregate per "
            "customer, sort by revenue descending."
        ),
        starter_code="-- Write your SQL query below\nSELECT\n",
        language="sql",
        estimated_minutes=20,
        dimensions=(
            ("query_correctness", "Query correctness"),
            ("joins_filtering", "Joins & filtering"),
            ("aggregation", "Aggregation & sorting"),
        ),
        checks=(
            _check("sql-tc-select", "Selects the required columns", "query_correctness", r"\bselect\b", 1.0),
            _check("sql-tc-join", "Joins customers and orders", "joins_filtering", r"\bjoin\b", 1.0),
            _check("sql-tc-where", "Filters to completed orders", "joins_filtering", r"\bwhere\b", 1.0),
            _check("sql-tc-group", "Aggregates per customer", "aggregation", r"\bgroup\s+by\b", 1.0),
            _check("sql-tc-order", "Sorts and limits to the top 5", "aggregation", r"(\border\s+by\b.*\blimit\b|\blimit\b.*\border\s+by\b|\border\s+by\b)", 1.0),
        ),
    ),
    PracticalTask(
        id="java-reverse-string",
        skill="Java",
        task_type="coding",
        title="Reverse words in a string",
        prompt=(
            "Write a Java method that reverses the order of words in a sentence "
            "(e.g. \"hello world\" -> \"world hello\"). Handle null/empty input and extra "
            "whitespace between words."
        ),
        starter_code="public class WordReverser {\n    public static String reverseWords(String sentence) {\n        // Your implementation here\n        return null;\n    }\n}\n",
        language="java",
        estimated_minutes=20,
        dimensions=(
            ("correctness", "Correctness"),
            ("edge_cases", "Edge cases"),
            ("implementation", "Implementation"),
        ),
        checks=(
            _check("java-rw-method", "Defines the method", "implementation", r"(public|private|protected)?\s*static\s+String\s+\w+\s*\(", 1.0),
            _check("java-rw-split", "Splits the sentence into words", "correctness", r"(\.split\s*\(|StringTokenizer|Pattern)", 1.0),
            _check("java-rw-loop", "Reorders with a loop or builder", "correctness", r"(\bfor\b|\bwhile\b|StringBuilder|StringBuffer|Collections\s*\.\s*reverse)", 1.0),
            _check("java-rw-null", "Handles null or empty input", "edge_cases", r"(==\s*null|null\s*==|isEmpty\s*\(|length\s*\(\)\s*==\s*0|trim\s*\()", 1.0),
            _check("java-rw-return", "Returns the result", "correctness", r"\breturn\b", 1.0),
        ),
    ),
    PracticalTask(
        id="javascript-debounce",
        skill="JavaScript",
        task_type="debugging",
        title="Fix the broken debounce",
        prompt=(
            "The debounce helper below should delay invoking fn until wait milliseconds have "
            "passed without another call, but it fires too often and loses arguments. Rewrite it "
            "correctly using a timer, preserving this-context and arguments."
        ),
        starter_code=(
            "function debounce(fn, wait) {\n"
            "  fn.apply(this, arguments);\n"
            "  setTimeout(fn, wait);\n"
            "}\n"
        ),
        language="javascript",
        estimated_minutes=15,
        dimensions=(
            ("correctness", "Correctness"),
            ("implementation", "Implementation"),
            ("edge_cases", "Edge cases"),
        ),
        checks=(
            _check("js-db-func", "Defines the debounce function", "implementation", r"function\s+\w+\s*\(|=>|const\s+\w+\s*=", 1.0),
            _check("js-db-timeout", "Uses a timer", "correctness", r"\bsetTimeout\b", 1.0),
            _check("js-db-clear", "Cancels the previous timer", "edge_cases", r"\bclearTimeout\b", 1.0),
            _check("js-db-args", "Preserves context and arguments", "correctness", r"(\.apply\s*\(|\.call\s*\(|\.\.\.\s*args|arguments)", 1.0),
            _check("js-db-return", "Returns the debounced function", "implementation", r"\breturn\b", 1.0),
        ),
    ),
    PracticalTask(
        id="react-user-list",
        skill="React",
        task_type="debugging",
        title="Fix the user list component",
        prompt=(
            "The component below should fetch users from /api/users on mount, show a loading "
            "state, render each user with a stable key, and handle fetch errors. Identify the "
            "bugs (effect dependencies, state updates, list keys, error handling) and rewrite it."
        ),
        starter_code=(
            "function UserList() {\n"
            "  const [users, setUsers] = useState();\n"
            "  useEffect(() => {\n"
            "    fetch('/api/users').then(r => r.json()).then(setUsers);\n"
            "  });\n"
            "  return <ul>{users.map(u => <li>{u.name}</li>)}</ul>;\n"
            "}\n"
        ),
        language="jsx",
        estimated_minutes=20,
        dimensions=(
            ("correctness", "Correctness"),
            ("implementation", "Implementation"),
            ("edge_cases", "Edge cases"),
        ),
        checks=(
            _check("react-ul-effect", "Fetches once on mount with a dependency array", "correctness", r"useEffect\s*\([\s\S]*?,\s*\[\s*\]", 1.0),
            _check("react-ul-state", "Initializes state safely", "implementation", r"useState\s*\(\s*(\[\]|\{\}|null|''|\"\")\s*\)", 1.0),
            _check("react-ul-key", "Renders list items with a stable key", "correctness", r"\bkey\s*=", 1.0),
            _check("react-ul-loading", "Handles loading or error state", "edge_cases", r"(loading|error|catch|finally|\?\.)", 1.0),
            _check("react-ul-return", "Returns rendered output", "implementation", r"\breturn\b", 1.0),
        ),
    ),
]


def _index_tasks() -> Dict[str, List[PracticalTask]]:
    """Index tasks by canonical skill slug; skip anything non-canonical."""
    index: Dict[str, List[PracticalTask]] = {}
    for t in RAW_PRACTICAL_TASKS:
        slug = normalize_skill_slug(t.skill)
        if not slug:
            continue
        index.setdefault(slug, []).append(t)
    return index


TASK_BANK: Dict[str, List[PracticalTask]] = _index_tasks()


def skill_slug(skill: str) -> Optional[str]:
    return normalize_skill_slug(str(skill or ""))


def has_practical(skill: str) -> bool:
    slug = skill_slug(skill)
    return bool(slug and len(TASK_BANK.get(slug, [])) > 0)


def tasks_for_skill(skill: str) -> List[PracticalTask]:
    slug = skill_slug(skill)
    return list(TASK_BANK.get(slug or "", []))


def get_task(task_id: str) -> Optional[PracticalTask]:
    for tasks in TASK_BANK.values():
        for t in tasks:
            if t.id == task_id:
                return t
    return None


def select_task(skill: str) -> Optional[PracticalTask]:
    """Deterministic task choice for a skill (first task; bank holds one per skill)."""
    tasks = tasks_for_skill(skill)
    return tasks[0] if tasks else None


def grade_task_submission(task: PracticalTask, code: Optional[str]) -> Tuple[float, List[dict]]:
    """
    Deterministically grade one practical submission.

    Each check is a case-insensitive regex over the submitted text; the score
    is the weight-weighted fraction of passed checks. Returns
    (score, per_check_results). Never executes the submission.
    """
    text = str(code or "")
    total_weight = sum(max(0.0, float(c.weight or 0.0)) for c in task.checks)
    passed_weight = 0.0
    results: List[dict] = []
    for c in task.checks:
        try:
            passed = bool(re.search(c.pattern, text, flags=re.IGNORECASE | re.DOTALL))
        except re.error:
            passed = False
        weight = max(0.0, float(c.weight or 0.0))
        if passed:
            passed_weight += weight
        results.append({
            "check_id": c.id,
            "dimension": c.dimension,
            "description": c.description,
            "passed": passed,
            "weight": weight,
        })
    score = round(passed_weight / total_weight, 4) if total_weight > 0 else 0.0
    return max(0.0, min(1.0, score)), results


def dimension_scores(task: PracticalTask, check_results: List[dict]) -> Dict[str, float]:
    """Aggregate passed-check weights per dimension to [0, 1] scores."""
    by_dim: Dict[str, Dict[str, float]] = {}
    for c, r in zip(task.checks, check_results):
        entry = by_dim.setdefault(c.dimension, {"passed": 0.0, "total": 0.0})
        entry["total"] += max(0.0, float(c.weight or 0.0))
        if r.get("passed"):
            entry["passed"] += max(0.0, float(c.weight or 0.0))
    return {
        dim: round(vals["passed"] / vals["total"], 4) if vals["total"] > 0 else 0.0
        for dim, vals in by_dim.items()
    }


def validate_practical_bank() -> List[str]:
    """Structural self-check of the practical bank. Returns problems (empty = OK)."""
    problems: List[str] = []
    seen_ids = set()
    for slug, tasks in TASK_BANK.items():
        for t in tasks:
            if t.id in seen_ids:
                problems.append(f"duplicate task id: {t.id}")
            seen_ids.add(t.id)
            if t.task_type not in TASK_TYPES:
                problems.append(f"{t.id}: unknown task_type '{t.task_type}'")
            if not t.prompt.strip() or not t.title.strip():
                problems.append(f"{t.id}: missing title or prompt")
            if normalize_skill(t.skill) != t.skill:
                problems.append(f"{t.id}: skill '{t.skill}' is not a canonical taxonomy name")
            if not t.checks:
                problems.append(f"{t.id}: task has no grading checks")
            dim_ids = {did for did, _ in t.dimensions}
            for c in t.checks:
                if c.weight is None or float(c.weight) <= 0:
                    problems.append(f"{t.id}/{c.id}: check weight must be positive")
                if c.dimension not in dim_ids:
                    problems.append(f"{t.id}/{c.id}: unknown dimension '{c.dimension}'")
                try:
                    re.compile(c.pattern)
                except re.error as e:
                    problems.append(f"{t.id}/{c.id}: invalid regex: {e}")
    return problems
