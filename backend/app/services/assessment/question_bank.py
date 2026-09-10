"""
Curated INAURA skill-assessment question bank (prototype).

Design constraints:
  * Deterministic grading only — no LLM is involved in scoring.
  * Questions probe competence (concept / application / debugging / decision),
    not vocabulary trivia.
  * The bank is content, not logic: selection, grading and scoring code below
    is fully generic, so adding a skill means adding questions, never code.
  * Skill identity always goes through the canonical taxonomy.

This is a prototype instrument. A short quiz is a weak proxy for human
proficiency; it is used as one (strong) evidence source, never as a verdict.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import random
import re

from ..skill_taxonomy import normalize_skill, normalize_skill_slug

ASSESSMENT_VERSION = "assessment-v1"

# Prototype sizing: 3-7 questions per attempt.
MIN_QUESTIONS = 3
MAX_QUESTIONS = 7
DEFAULT_QUESTION_COUNT = 5

QUESTION_KINDS = ("concept", "application", "debugging", "decision")
DIFFICULTIES = ("easy", "medium", "hard")


def normalize_answer(text: str) -> str:
    """Normalize a free-text answer for deterministic comparison."""
    cleaned = str(text or "").strip().lower()
    cleaned = re.sub(r"[\s\-_]+", " ", cleaned)
    cleaned = re.sub(r"[^\w\s()+/]", "", cleaned)
    return cleaned.strip()


@dataclass(frozen=True)
class AssessmentQuestion:
    """One deterministically gradable question."""

    id: str
    skill: str                                   # canonical display name
    difficulty: str
    kind: str
    prompt: str
    explanation: str
    options: Tuple[Tuple[str, str], ...] = ()    # (option_id, option_text)
    correct_option: Optional[str] = None
    accepted_answers: Tuple[str, ...] = ()
    version: str = ASSESSMENT_VERSION

    @property
    def is_multiple_choice(self) -> bool:
        return bool(self.options)

    def public_dict(self) -> dict:
        """Question as sent to the client — never includes the answer key."""
        return {
            "id": self.id,
            "skill": self.skill,
            "difficulty": self.difficulty,
            "kind": self.kind,
            "prompt": self.prompt,
            "type": "multiple_choice" if self.is_multiple_choice else "short_answer",
            "options": [{"id": oid, "text": text} for oid, text in self.options],
            "version": self.version,
        }

    def grade(self, response: Optional[str]) -> bool:
        """Deterministic grading. Returns True when the response is correct."""
        if response is None:
            return False
        raw = str(response).strip()
        if not raw:
            return False
        if self.is_multiple_choice:
            return raw.strip().lower() == str(self.correct_option or "").lower()
        answer = normalize_answer(raw)
        return any(answer == normalize_answer(a) for a in self.accepted_answers)


def _mc(
    qid: str,
    skill: str,
    difficulty: str,
    kind: str,
    prompt: str,
    options: List[Tuple[str, str]],
    correct: str,
    explanation: str,
) -> AssessmentQuestion:
    return AssessmentQuestion(
        id=qid,
        skill=skill,
        difficulty=difficulty,
        kind=kind,
        prompt=prompt,
        options=tuple(options),
        correct_option=correct,
        explanation=explanation,
    )


def _sa(
    qid: str,
    skill: str,
    difficulty: str,
    kind: str,
    prompt: str,
    accepted: List[str],
    explanation: str,
) -> AssessmentQuestion:
    return AssessmentQuestion(
        id=qid,
        skill=skill,
        difficulty=difficulty,
        kind=kind,
        prompt=prompt,
        accepted_answers=tuple(accepted),
        explanation=explanation,
    )


RAW_QUESTIONS: List[AssessmentQuestion] = [
    # ---------------------------------------------------------------- Python
    _mc(
        "py-001", "Python", "medium", "concept",
        "What does this print?\n\n    a = [1, 2, 3]\n    b = a\n    b.append(4)\n    print(len(a))",
        [("a", "3"), ("b", "4"), ("c", "TypeError"), ("d", "Nothing — b is a copy")],
        "b",
        "`b = a` binds another name to the same list object; append mutates the shared object, so len(a) is 4.",
    ),
    _mc(
        "py-002", "Python", "medium", "debugging",
        "A helper misbehaves across calls:\n\n    def collect(item, acc=[]):\n        acc.append(item)\n        return acc\n\n"
        "collect('a') returns ['a'], then collect('b') returns ['a', 'b']. Why?",
        [
            ("a", "Python caches return values of pure functions"),
            ("b", "The default argument is evaluated once at definition time and reused"),
            ("c", "Lists are always global in Python"),
            ("d", "append() returns the module-level list"),
        ],
        "b",
        "Default arguments are evaluated once when the function is defined. Use `acc=None` and create the list inside.",
    ),
    _mc(
        "py-003", "Python", "easy", "application",
        "Which expression builds a list of the squares of the even numbers from 0 to 9?",
        [
            ("a", "[x*x for x in range(10) if x % 2 == 0]"),
            ("b", "[x*x if x % 2 == 0 for x in range(10)]"),
            ("c", "[x % 2 == 0 for x in range(10)]"),
            ("d", "{x: x*x for x in range(10)}"),
        ],
        "a",
        "The filter clause follows the loop in a comprehension; option b is a syntax error.",
    ),
    _mc(
        "py-004", "Python", "medium", "decision",
        "You must check membership ('is this id present?') millions of times against a collection of 1,000,000 ids. "
        "Which container should you choose and why?",
        [
            ("a", "list — membership scans are cache friendly"),
            ("b", "set — average O(1) hash lookup instead of O(n) scanning"),
            ("c", "tuple — immutability makes lookups faster"),
            ("d", "It makes no difference; all Python containers use hashing"),
        ],
        "b",
        "`in` on a list is a linear scan; sets and dicts hash the key for average constant-time membership.",
    ),
    _sa(
        "py-005", "Python", "hard", "concept",
        "Which Python language feature guarantees that a file opened with `with open(path) as f:` is closed even "
        "when the block raises an exception? Answer with the feature name (two words).",
        ["context manager", "context managers", "the context manager", "context manager protocol"],
        "The `with` statement uses the context manager protocol; `__exit__` runs on normal completion and on exceptions.",
    ),

    # ------------------------------------------------------------------- SQL
    _mc(
        "sql-001", "SQL", "easy", "concept",
        "You need every customer row, plus their orders when any exist. Which join do you use?",
        [
            ("a", "INNER JOIN customers/orders"),
            ("b", "LEFT JOIN orders onto customers"),
            ("c", "CROSS JOIN customers and orders"),
            ("d", "RIGHT JOIN customers onto orders"),
        ],
        "b",
        "A LEFT JOIN keeps all rows of the left table and fills unmatched right-hand columns with NULL.",
    ),
    _mc(
        "sql-002", "SQL", "medium", "debugging",
        "This query errors or filters nothing as expected:\n\n"
        "    SELECT dept, COUNT(*) c FROM emp WHERE COUNT(*) > 5 GROUP BY dept;\n\nWhat is wrong?",
        [
            ("a", "COUNT(*) needs a column argument"),
            ("b", "Aggregate filters belong in HAVING, which runs after GROUP BY; WHERE runs before"),
            ("c", "GROUP BY must precede WHERE in the text of the query"),
            ("d", "You must alias the table before grouping"),
        ],
        "b",
        "WHERE filters rows before grouping, so it cannot see aggregates. Use `HAVING COUNT(*) > 5`.",
    ),
    _mc(
        "sql-003", "SQL", "medium", "decision",
        "A 20-million-row table is queried constantly with `WHERE email = ?` and written to rarely. "
        "What is the appropriate action and its main trade-off?",
        [
            ("a", "Add an index on email; indexes add storage and slow down writes"),
            ("b", "Add an index on every column; there is no downside"),
            ("c", "Switch to SELECT * so the planner can optimize freely"),
            ("d", "Nothing — full scans are fine because the table is read-heavy"),
        ],
        "a",
        "A selective index on the filtered column turns the scan into a lookup; the cost is extra storage and write amplification.",
    ),
    _mc(
        "sql-004", "SQL", "easy", "debugging",
        "`SELECT * FROM users WHERE deleted_at = NULL` returns zero rows although many rows have a NULL deleted_at. Why?",
        [
            ("a", "NULL comparisons with = are never true; you must use IS NULL"),
            ("b", "NULL columns are excluded from SELECT *"),
            ("c", "The column must be indexed to be comparable"),
            ("d", "NULL only works inside aggregate functions"),
        ],
        "a",
        "NULL means unknown, so `= NULL` evaluates to unknown for every row. Use `IS NULL` / `IS NOT NULL`.",
    ),
    _mc(
        "sql-005", "SQL", "medium", "concept",
        "Two updates (debit one account, credit another) must both apply or neither. Which property of a transaction guarantees this?",
        [
            ("a", "Consistency"), ("b", "Isolation"), ("c", "Atomicity"), ("d", "Durability"),
        ],
        "c",
        "Atomicity makes the transaction all-or-nothing; a failure rolls back every statement in it.",
    ),

    # ------------------------------------------------- Data Structures & Algo
    _mc(
        "dsa-001", "Data Structures & Algorithms", "easy", "concept",
        "What is the worst-case time complexity of binary search over a sorted array of n elements?",
        [("a", "O(1)"), ("b", "O(log n)"), ("c", "O(n)"), ("d", "O(n log n)")],
        "b",
        "Each comparison halves the remaining range, giving logarithmic worst-case time.",
    ),
    _mc(
        "dsa-002", "Data Structures & Algorithms", "medium", "decision",
        "You must support get(key) and put(key, value) in O(1) average time plus eviction of the least recently used entry. "
        "Which structure combination fits?",
        [
            ("a", "A sorted array with binary search"),
            ("b", "A hash map plus a doubly linked list"),
            ("c", "A min-heap keyed by insertion time"),
            ("d", "A balanced BST keyed by access count"),
        ],
        "b",
        "The hash map gives O(1) lookup; the doubly linked list gives O(1) reordering and eviction at the tail.",
    ),
    _mc(
        "dsa-003", "Data Structures & Algorithms", "medium", "debugging",
        "This binary search never terminates for some inputs:\n\n"
        "    while lo < hi:\n        mid = (lo + hi) // 2\n        if arr[mid] < target: lo = mid\n        else: hi = mid\n\nWhat is the defect?",
        [
            ("a", "mid must be computed as lo + (hi - lo) // 2 to avoid overflow"),
            ("b", "`lo = mid` can leave the range unchanged when hi == lo + 1; it must be lo = mid + 1"),
            ("c", "The loop condition should be lo != hi"),
            ("d", "arr must be sorted in descending order"),
        ],
        "b",
        "With hi == lo + 1, mid == lo, so `lo = mid` makes no progress and the loop spins forever.",
    ),
    _sa(
        "dsa-004", "Data Structures & Algorithms", "hard", "application",
        "Which algorithm detects a cycle in a singly linked list using O(1) extra space? "
        "Answer with its common name (e.g. '<something> algorithm').",
        [
            "floyds cycle detection algorithm", "floyds cycle detection", "floyd cycle detection",
            "floyds tortoise and hare", "tortoise and hare", "tortoise and hare algorithm",
            "floyds algorithm", "two pointer", "two pointers", "fast and slow pointers",
        ],
        "Floyd's tortoise-and-hare advances one pointer by 1 and another by 2; they meet inside a cycle, using constant space.",
    ),
    _mc(
        "dsa-005", "Data Structures & Algorithms", "medium", "application",
        "You need the k largest items from a stream of n values with k << n, using O(k) memory. Best approach?",
        [
            ("a", "Sort everything, then take the last k — O(n log n) and O(n) memory"),
            ("b", "Keep a min-heap of size k and push/pop as items arrive"),
            ("c", "Keep a max-heap of all n items"),
            ("d", "Scan k times, removing the maximum each pass"),
        ],
        "b",
        "A size-k min-heap keeps the current top k in O(n log k) time and O(k) memory, and works on a stream.",
    ),

    # ------------------------------------------------------------- REST APIs
    _mc(
        "rest-001", "REST APIs", "medium", "concept",
        "Which statement about idempotency is correct?",
        [
            ("a", "POST is idempotent because it validates input"),
            ("b", "PUT is idempotent: repeating the same request leaves the resource in the same state"),
            ("c", "GET is not idempotent because responses may differ over time"),
            ("d", "DELETE is never idempotent because the second call fails"),
        ],
        "b",
        "PUT replaces a resource with a given representation, so repeating it converges to the same state; POST typically creates a new resource each time.",
    ),
    _mc(
        "rest-002", "REST APIs", "easy", "application",
        "A POST /orders request successfully creates a new order. Which status code should the API return?",
        [("a", "200 OK"), ("b", "201 Created"), ("c", "202 Accepted"), ("d", "204 No Content")],
        "b",
        "201 signals that a new resource was created, usually with a Location header pointing to it.",
    ),
    _mc(
        "rest-003", "REST APIs", "medium", "debugging",
        "Your API returns 500 when a client omits a required field. Reviewers call this a bug. Why?",
        [
            ("a", "500 means the server failed; invalid client input should be 4xx (e.g. 400/422)"),
            ("b", "It should return 404, since the valid resource was not found"),
            ("c", "It should return 200 with an error message in the body"),
            ("d", "Nothing is wrong — any error can use 500"),
        ],
        "a",
        "5xx tells clients the server is at fault and the request may be retried; validation failures are 4xx and are not retryable unchanged.",
    ),
    _mc(
        "rest-004", "REST APIs", "medium", "decision",
        "GET /events must serve a collection that grows to millions of rows. What is the right design?",
        [
            ("a", "Return the whole collection and let clients filter"),
            ("b", "Paginate with bounded page size (limit/offset or cursor) and document the default"),
            ("c", "Require a POST body so the response can be larger"),
            ("d", "Return a random sample to keep responses small"),
        ],
        "b",
        "Bounded, paginated responses keep latency and memory predictable; cursors are preferred for deep or shifting datasets.",
    ),
    _mc(
        "rest-005", "REST APIs", "medium", "concept",
        "What does it mean that REST is stateless?",
        [
            ("a", "The server may not store any data at all"),
            ("b", "Each request carries everything needed to process it; the server keeps no client session between requests"),
            ("c", "Responses may never be cached"),
            ("d", "Clients must send every request over the same TCP connection"),
        ],
        "b",
        "Statelessness concerns per-client session state between requests, not persistent application data. It is what makes horizontal scaling simple.",
    ),

    # ------------------------------------------------------------------- Git
    _mc(
        "git-001", "Git", "medium", "decision",
        "You pushed a broken commit to a shared main branch an hour ago. What is the safe fix?",
        [
            ("a", "git reset --hard HEAD~1 and force-push"),
            ("b", "git revert <sha> and push the new commit"),
            ("c", "Delete the branch and recreate it"),
            ("d", "git commit --amend and force-push"),
        ],
        "b",
        "revert adds an inverse commit, so collaborators' history stays valid. Rewriting published history breaks everyone else's clones.",
    ),
    _mc(
        "git-002", "Git", "medium", "concept",
        "What is the practical difference between `git merge main` and `git rebase main` on your feature branch?",
        [
            ("a", "merge creates a merge commit and preserves history; rebase replays your commits onto main, rewriting their hashes"),
            ("b", "They are identical; rebase is just an alias"),
            ("c", "merge discards your commits; rebase keeps them"),
            ("d", "rebase can only be used on the main branch"),
        ],
        "a",
        "Rebase produces a linear history by creating new commits; because hashes change, avoid rebasing commits others already pulled.",
    ),
    _mc(
        "git-003", "Git", "easy", "debugging",
        "A file with API keys was committed and pushed. It is now in .gitignore, but Git still tracks changes to it. Why?",
        [
            ("a", ".gitignore only affects untracked files; the file must be removed from the index (git rm --cached)"),
            ("b", ".gitignore only works in the repository root"),
            ("c", "Git ignores .gitignore for files containing secrets"),
            ("d", "You must run git gc before .gitignore takes effect"),
        ],
        "a",
        "Ignore rules apply to untracked paths. Stop tracking with `git rm --cached`, commit, and rotate the exposed secret — history still contains it.",
    ),
    _mc(
        "git-004", "Git", "medium", "application",
        "Git reports a merge conflict in app.py. What is the correct sequence?",
        [
            ("a", "git checkout --theirs always, then push"),
            ("b", "Edit the file to resolve the markers, git add app.py, then complete the merge/commit"),
            ("c", "Delete the file and commit"),
            ("d", "Run git merge --abort, then push anyway"),
        ],
        "b",
        "Conflicts are resolved in the working tree; staging the resolved file marks it resolved and the merge commit finishes the operation.",
    ),
    _sa(
        "git-005", "Git", "medium", "concept",
        "What is the Git term for the state where HEAD points directly at a commit instead of a branch? "
        "Answer with the two-word term.",
        ["detached head", "detached head state", "a detached head"],
        "In detached HEAD, new commits belong to no branch and can be lost once you check out something else.",
    ),

    # ---------------------------------------------------------------- Docker
    _mc(
        "docker-001", "Docker", "easy", "concept",
        "What is the relationship between an image and a container?",
        [
            ("a", "They are the same thing with different names"),
            ("b", "An image is an immutable filesystem/config template; a container is a running instance of it"),
            ("c", "A container is compiled into an image at runtime"),
            ("d", "An image can only produce one container ever"),
        ],
        "b",
        "Images are immutable build artifacts; containers add a writable layer and a running process on top.",
    ),
    _mc(
        "docker-002", "Docker", "medium", "decision",
        "Why do well-written Dockerfiles copy the dependency manifest and install dependencies BEFORE copying the rest of the source?",
        [
            ("a", "The package manager cannot see source files"),
            ("b", "Layer caching: dependency layers are reused whenever only application code changed"),
            ("c", "It reduces the final image's number of environment variables"),
            ("d", "COPY must always be the last instruction"),
        ],
        "b",
        "Each instruction is a cached layer invalidated by changed inputs. Installing before copying source keeps the slow install cached across code edits.",
    ),
    _mc(
        "docker-003", "Docker", "medium", "application",
        "A Postgres container loses all data whenever it is recreated. What fixes it?",
        [
            ("a", "Mount a named volume at the database data directory"),
            ("b", "Add EXPOSE 5432 to the Dockerfile"),
            ("c", "Run the container with --restart always"),
            ("d", "Increase the container memory limit"),
        ],
        "a",
        "The container's writable layer dies with the container; volumes (or bind mounts) persist data independently of its lifecycle.",
    ),
    _mc(
        "docker-004", "Docker", "medium", "debugging",
        "`docker run myapp` exits immediately with code 0 and no error. Most likely cause?",
        [
            ("a", "The image is corrupt"),
            ("b", "The container's main process finished — nothing runs in the foreground"),
            ("c", "The host firewall blocked the port"),
            ("d", "Docker requires the -d flag to run any container"),
        ],
        "b",
        "A container lives exactly as long as PID 1. If the entrypoint/CMD exits (e.g. a script that ends, or a server started in the background), the container stops.",
    ),
    _mc(
        "docker-005", "Docker", "medium", "concept",
        "What does EXPOSE 8000 in a Dockerfile actually do?",
        [
            ("a", "Publishes port 8000 on the host automatically"),
            ("b", "Documents the port as metadata; publishing still requires -p/ports mapping"),
            ("c", "Opens the host firewall for port 8000"),
            ("d", "Forces the application to bind to 8000"),
        ],
        "b",
        "EXPOSE is documentation/metadata for tooling. Reaching the service from the host needs `-p host:container` (or a compose ports entry).",
    ),

    # ----------------------------------------------------------------- React
    _mc(
        "react-001", "React", "medium", "concept",
        "Why does React require a stable `key` when rendering a list?",
        [
            ("a", "Keys are used as CSS identifiers"),
            ("b", "Keys let the reconciler match elements across renders so state and DOM nodes are preserved correctly"),
            ("c", "Keys are required only for TypeScript projects"),
            ("d", "Keys define the render order"),
        ],
        "b",
        "Without stable keys (array indexes on a reordering list are unstable), React can associate the wrong DOM node/state with an item.",
    ),
    _mc(
        "react-002", "React", "medium", "debugging",
        "This component re-renders forever:\n\n    useEffect(() => { setCount(count + 1); });\n\nWhat is the defect?",
        [
            ("a", "setCount cannot be called inside useEffect"),
            ("b", "The effect has no dependency array, so it runs after every render and each run triggers another render"),
            ("c", "count must be stored in a ref"),
            ("d", "useEffect must return a cleanup function"),
        ],
        "b",
        "Omitting the dependency array means 'run after every render'. Setting state re-renders, which reruns the effect — an infinite loop.",
    ),
    _mc(
        "react-003", "React", "medium", "application",
        "Several updates in one handler each depend on the previous value of `count`. What is the correct pattern?",
        [
            ("a", "setCount(count + 1) repeatedly"),
            ("b", "setCount(prev => prev + 1) — the functional updater sees the latest queued state"),
            ("c", "Mutate count directly, then call forceUpdate"),
            ("d", "Wrap each call in setTimeout"),
        ],
        "b",
        "`count` is captured from the render closure; the functional updater receives the pending value, so batched updates compose correctly.",
    ),
    _mc(
        "react-004", "React", "easy", "concept",
        "What makes an <input> a controlled component?",
        [
            ("a", "It has a ref attached"),
            ("b", "Its value comes from React state and changes flow through onChange"),
            ("c", "It is wrapped in a <form> element"),
            ("d", "It uses defaultValue instead of value"),
        ],
        "b",
        "A controlled input renders from state and reports edits via onChange, so React state is the single source of truth.",
    ),
    _mc(
        "react-005", "React", "medium", "decision",
        "Two sibling components must stay in sync with the same filter value. What is the first thing to do?",
        [
            ("a", "Duplicate the state in both siblings and sync it in effects"),
            ("b", "Lift the state to their closest common parent and pass it down"),
            ("c", "Store the value on window"),
            ("d", "Add a global state library immediately"),
        ],
        "b",
        "Lifting state to the nearest common ancestor is the standard fix; context or a store is only warranted once prop drilling becomes unmanageable.",
    ),

    # --------------------------------------------------------------- Testing
    _mc(
        "test-001", "Testing", "easy", "concept",
        "What best distinguishes a unit test from an integration test?",
        [
            ("a", "Unit tests are written first; integration tests are written last"),
            ("b", "A unit test exercises one component in isolation; an integration test exercises components working together"),
            ("c", "Unit tests run in CI; integration tests run locally"),
            ("d", "Unit tests may not use assertions"),
        ],
        "b",
        "The distinction is scope and isolation, not tooling or timing.",
    ),
    _mc(
        "test-002", "Testing", "medium", "debugging",
        "A test passes locally but fails in CI roughly one run in five. Which cause is most likely?",
        [
            ("a", "CI machines run a different language version of your assertions"),
            ("b", "The test depends on shared/ordering-sensitive state, real time, or the network"),
            ("c", "The assertion library is broken"),
            ("d", "Tests always behave randomly"),
        ],
        "b",
        "Flakiness usually comes from hidden shared state, timing/sleep assumptions, or real I/O. Isolate and inject those dependencies.",
    ),
    _mc(
        "test-003", "Testing", "medium", "decision",
        "You are unit-testing a function that calls a third-party payment HTTP API. What should the test do?",
        [
            ("a", "Call the real API to guarantee realism"),
            ("b", "Stub/mock the HTTP boundary and assert behaviour on success and failure responses"),
            ("c", "Skip testing until a sandbox account exists"),
            ("d", "Assert only that no exception is raised"),
        ],
        "b",
        "Mocking the boundary keeps the unit test fast and deterministic and lets you cover error paths; real calls belong in a separate contract/integration suite.",
    ),
    _mc(
        "test-004", "Testing", "medium", "concept",
        "A service has 95% line coverage but a bug ships in a covered function. What does this show?",
        [
            ("a", "Coverage measures which lines executed, not whether behaviour was asserted correctly"),
            ("b", "Coverage was measured incorrectly"),
            ("c", "95% coverage is too low to be meaningful"),
            ("d", "The bug must be in the 5% uncovered lines"),
        ],
        "a",
        "Lines can execute without any meaningful assertion. Coverage is a gap-finding tool, not a correctness metric.",
    ),
    _mc(
        "test-005", "Testing", "medium", "application",
        "Which regression test is most valuable immediately after fixing a production bug?",
        [
            ("a", "A test asserting the module imports successfully"),
            ("b", "A test that reproduces the exact failing input and asserts the corrected output"),
            ("c", "A test that raises overall coverage by a few percent"),
            ("d", "A snapshot test of the whole response"),
        ],
        "b",
        "Pinning the specific failure keeps that defect from returning and documents the intended behaviour.",
    ),
]


def _index_bank() -> Dict[str, List[AssessmentQuestion]]:
    """Index questions by canonical skill slug; skip anything non-canonical."""
    index: Dict[str, List[AssessmentQuestion]] = {}
    for q in RAW_QUESTIONS:
        slug = normalize_skill_slug(q.skill)
        if not slug:
            continue
        index.setdefault(slug, []).append(q)
    return index


QUESTION_BANK: Dict[str, List[AssessmentQuestion]] = _index_bank()

# Canonical display name per slug present in the bank.
BANK_SKILLS: Dict[str, str] = {
    slug: (normalize_skill(qs[0].skill) or qs[0].skill) for slug, qs in QUESTION_BANK.items()
}


def skill_slug(skill: str) -> Optional[str]:
    """Canonical slug for any skill spelling, or None if unknown to the taxonomy."""
    return normalize_skill_slug(str(skill or ""))


def has_questions(skill: str) -> bool:
    slug = skill_slug(skill)
    return bool(slug and len(QUESTION_BANK.get(slug, [])) >= MIN_QUESTIONS)


def assessable_skills() -> List[str]:
    """Canonical display names of every skill the bank can assess."""
    return sorted(BANK_SKILLS[slug] for slug in QUESTION_BANK if len(QUESTION_BANK[slug]) >= MIN_QUESTIONS)


def questions_for_skill(skill: str) -> List[AssessmentQuestion]:
    slug = skill_slug(skill)
    return list(QUESTION_BANK.get(slug or "", []))


def get_question(question_id: str) -> Optional[AssessmentQuestion]:
    for questions in QUESTION_BANK.values():
        for q in questions:
            if q.id == question_id:
                return q
    return None


def select_questions(
    skill: str,
    limit: int = DEFAULT_QUESTION_COUNT,
    seed: Optional[str] = None,
) -> List[AssessmentQuestion]:
    """
    Select a bounded question set for one attempt.

    Ordering is shuffled per attempt (seeded, so a resumed attempt is stable)
    while the selection itself stays inside the configured 3-7 range.
    """
    pool = questions_for_skill(skill)
    if not pool:
        return []
    count = max(MIN_QUESTIONS, min(MAX_QUESTIONS, int(limit or DEFAULT_QUESTION_COUNT)))
    count = min(count, len(pool))
    rng = random.Random(seed if seed is not None else 0)
    ordered = sorted(pool, key=lambda q: q.id)
    rng.shuffle(ordered)
    return ordered[:count]


def validate_bank() -> List[str]:
    """
    Structural self-check of the bank. Returns a list of problems (empty = OK).
    Used by tests so malformed content fails loudly rather than silently
    grading everyone as wrong.
    """
    problems: List[str] = []
    seen_ids = set()
    for slug, questions in QUESTION_BANK.items():
        if len(questions) < MIN_QUESTIONS:
            problems.append(f"{slug}: only {len(questions)} question(s), minimum is {MIN_QUESTIONS}")
        for q in questions:
            if q.id in seen_ids:
                problems.append(f"duplicate question id: {q.id}")
            seen_ids.add(q.id)
            if q.difficulty not in DIFFICULTIES:
                problems.append(f"{q.id}: unknown difficulty '{q.difficulty}'")
            if q.kind not in QUESTION_KINDS:
                problems.append(f"{q.id}: unknown kind '{q.kind}'")
            if not q.prompt.strip() or not q.explanation.strip():
                problems.append(f"{q.id}: missing prompt or explanation")
            if q.is_multiple_choice:
                option_ids = [oid for oid, _ in q.options]
                if len(option_ids) < 3:
                    problems.append(f"{q.id}: needs at least 3 options")
                if len(set(option_ids)) != len(option_ids):
                    problems.append(f"{q.id}: duplicate option ids")
                if q.correct_option not in option_ids:
                    problems.append(f"{q.id}: correct_option '{q.correct_option}' not among options")
                if q.accepted_answers:
                    problems.append(f"{q.id}: multiple-choice question must not define accepted_answers")
            else:
                if not q.accepted_answers:
                    problems.append(f"{q.id}: short-answer question has no accepted answers")
                if q.correct_option:
                    problems.append(f"{q.id}: short-answer question must not define correct_option")
            if normalize_skill(q.skill) != q.skill:
                problems.append(f"{q.id}: skill '{q.skill}' is not a canonical taxonomy name")
    return problems
