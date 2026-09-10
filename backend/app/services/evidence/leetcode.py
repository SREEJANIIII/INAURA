import httpx
import math
from typing import List, Dict, Tuple, Optional, Any, Set
from datetime import datetime, timezone
from dataclasses import dataclass, field
from collections import defaultdict

from .base import EvidenceProvider, VerificationResult, ExtractedSignal, EvidenceDepth, VerificationStatus
from .url_utils import validate_platform_url, extract_username_from_path, LEETCODE_HOSTS
from ..evidence_weights import reliability as source_reliability
from ..skill_taxonomy import normalize_skill

LEETCODE_RELIABILITY = source_reliability("leetcode")

# Documented heuristic weights for difficulty-calibrated problem solving
WEIGHT_EASY = 0.15
WEIGHT_MEDIUM = 0.85
WEIGHT_HARD = 2.0

# 9 Canonical DSA Pillars for Topic Breadth Assessment
DSA_PILLARS = [
    "Arrays & Strings",
    "Linked Lists",
    "Stacks & Queues",
    "Trees",
    "Graphs",
    "Searching & Sorting",
    "Dynamic Programming",
    "Greedy",
    "Backtracking",
]

# Advanced pillars requiring deeper algorithmic reasoning
ADVANCED_PILLARS = {"Dynamic Programming", "Graphs", "Trees", "Backtracking"}

# Mapping from normalized tag slugs to canonical DSA pillars
TAG_SLUG_TO_PILLAR: Dict[str, str] = {
    # Arrays & Strings
    "array": "Arrays & Strings",
    "string": "Arrays & Strings",
    "two-pointers": "Arrays & Strings",
    "sliding-window": "Arrays & Strings",
    "prefix-sum": "Arrays & Strings",
    "matrix": "Arrays & Strings",
    "simulation": "Arrays & Strings",
    "string-matching": "Arrays & Strings",
    "hash-table": "Arrays & Strings",
    "hash-map": "Arrays & Strings",

    # Linked Lists
    "linked-list": "Linked Lists",
    "doubly-linked-list": "Linked Lists",

    # Stacks & Queues
    "stack": "Stacks & Queues",
    "queue": "Stacks & Queues",
    "monotonic-stack": "Stacks & Queues",
    "monotonic-queue": "Stacks & Queues",

    # Trees
    "tree": "Trees",
    "binary-tree": "Trees",
    "binary-search-tree": "Trees",
    "bst": "Trees",
    "trie": "Trees",
    "segment-tree": "Trees",
    "binary-indexed-tree": "Trees",

    # Graphs
    "graph": "Graphs",
    "graph-theory": "Graphs",
    "depth-first-search": "Graphs",
    "dfs": "Graphs",
    "breadth-first-search": "Graphs",
    "bfs": "Graphs",
    "union-find": "Graphs",
    "shortest-path": "Graphs",
    "topological-sort": "Graphs",
    "minimum-spanning-tree": "Graphs",
    "eulerian-circuit": "Graphs",
    "strongly-connected-component": "Graphs",
    "bipartite": "Graphs",

    # Searching & Sorting
    "binary-search": "Searching & Sorting",
    "sorting": "Searching & Sorting",
    "quickselect": "Searching & Sorting",
    "divide-and-conquer": "Searching & Sorting",
    "bucket-sort": "Searching & Sorting",
    "radix-sort": "Searching & Sorting",
    "counting-sort": "Searching & Sorting",

    # Dynamic Programming
    "dynamic-programming": "Dynamic Programming",
    "dp": "Dynamic Programming",
    "memoization": "Dynamic Programming",
    "bitmask": "Dynamic Programming",

    # Greedy
    "greedy": "Greedy",

    # Backtracking
    "backtracking": "Backtracking",
    "recursion": "Backtracking",
}

# Display name normalizations for common tags
TAG_DISPLAY_NAME_MAP: Dict[str, str] = {
    "depth-first-search": "DFS",
    "dfs": "DFS",
    "breadth-first-search": "BFS",
    "bfs": "BFS",
    "binary-search-tree": "BST",
    "bst": "BST",
    "graph-theory": "Graph",
    "dynamic-programming": "Dynamic Programming",
    "dp": "Dynamic Programming",
    "two-pointers": "Two Pointers",
    "sliding-window": "Sliding Window",
    "binary-search": "Binary Search",
    "linked-list": "Linked List",
    "union-find": "Union Find",
}


def normalize_tag_slug(tag: str) -> str:
    """Normalize raw tag string to clean hyphenated lowercase slug."""
    if not tag:
        return ""
    s = tag.strip().lower().replace("_", "-").replace(" ", "-")
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")


def normalize_tag_display_name(tag: str) -> str:
    """Normalize tag name for presentation."""
    slug = normalize_tag_slug(tag)
    return TAG_DISPLAY_NAME_MAP.get(slug, tag.strip())

@dataclass
class LeetCodeTopicSummary:
    """Structured DSA topic coverage, breadth, and depth analysis."""
    status: str  # "available" | "unavailable"
    breadth_score: float  # [0.0, 1.0]
    depth_score: float    # [0.0, 1.0]
    covered_pillars: List[str]   # >= 15 solved
    moderate_pillars: List[str]  # 5-14 solved
    weak_pillars: List[str]      # 1-4 solved
    missing_pillars: List[str]   # 0 solved
    pillar_breakdown: Dict[str, Dict[str, Any]]
    problems_with_topic: int
    topic_occurrences: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "breadth_score": self.breadth_score,
            "depth_score": self.depth_score,
            "covered_pillars": self.covered_pillars,
            "moderate_pillars": self.moderate_pillars,
            "weak_pillars": self.weak_pillars,
            "missing_pillars": self.missing_pillars,
            "pillar_breakdown": self.pillar_breakdown,
            "problems_with_topic": self.problems_with_topic,
            "topic_occurrences": self.topic_occurrences,
        }


class LeetCodeProvider(EvidenceProvider):
    """
    Evidence Intelligence Provider for LeetCode.
    Extracts verifiable facts:
    - Solved problems by difficulty (Easy, Medium, Hard)
    - Topic coverage across 9 canonical DSA pillars
    - Topic breadth and concentration metrics
    - Topic depth (advanced algorithmic categories + hard problems)
    - Contest participation and rating
    - Global ranking / top percentage
    Scopes evidence strictly to:
    - Data Structures & Algorithms
    - Problem Solving
    - Competitive Programming (if contest active)
    """

    @property
    def provider_name(self) -> str:
        return "leetcode"

    def can_handle(self, evidence: dict) -> bool:
        etype = (evidence.get("evidence_type") or "").lower()
        url = (evidence.get("source_url") or "").strip()

        if etype == "leetcode":
            if url:
                valid, _, _ = validate_platform_url(url, LEETCODE_HOSTS)
                return valid
            return True

        if url:
            valid, _, _ = validate_platform_url(url, LEETCODE_HOSTS)
            return valid

        return False

    def validate(self, evidence: dict) -> Tuple[bool, Optional[str]]:
        url = (evidence.get("source_url") or "").strip()
        if not url:
            return False, "LeetCode URL or username required"
        valid, path, err = validate_platform_url(url, LEETCODE_HOSTS)
        if not valid:
            return False, err
        username = extract_username_from_path(path or "", "leetcode")
        if not username:
            return False, "Could not extract LeetCode username from URL"
        return True, None

    async def verify(self, evidence: dict) -> VerificationResult:
        now = datetime.now(timezone.utc)
        url = (evidence.get("source_url") or "").strip()

        # 1. Deterministic offline mock inspection support
        if "mock_inspection" in evidence:
            return self._build_result_from_inspection(evidence["mock_inspection"], now)

        # 2. Validate input and extract username
        valid, path, err = validate_platform_url(url, LEETCODE_HOSTS)
        if not valid:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Invalid LeetCode URL or handle: {err}",
                provider=self.provider_name,
                raw_metadata={"raw_url": url},
                verified_at=now,
            )

        username = extract_username_from_path(path or "", "leetcode")
        if not username:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message="Could not extract LeetCode username from provided URL.",
                provider=self.provider_name,
                raw_metadata={"raw_url": url},
                verified_at=now,
            )

        # 3. Query LeetCode Public GraphQL API including tagProblemCounts
        query = """
        query getUserProfile($username: String!) {
          matchedUser(username: $username) {
            username
            submitStatsGlobal {
              acSubmissionNum {
                difficulty
                count
              }
            }
            profile {
              ranking
              reputation
            }
            tagProblemCounts {
              fundamental {
                tagName
                tagSlug
                problemsSolved
              }
              intermediate {
                tagName
                tagSlug
                problemsSolved
              }
              advanced {
                tagName
                tagSlug
                problemsSolved
              }
            }
          }
          userContestRanking(username: $username) {
            rating
            globalRanking
            totalParticipants
            topPercentage
            attendedContestsCount
          }
        }
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Referer": "https://leetcode.com",
        }

        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.post(
                    "https://leetcode.com/graphql",
                    json={"query": query, "variables": {"username": username}},
                    headers=headers,
                )

                if resp.status_code == 429:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        message="LeetCode API rate limit reached. Please retry shortly.",
                        provider=self.provider_name,
                        raw_metadata={"username": username, "http_status": 429},
                        verified_at=now,
                        warnings=["Rate limited by LeetCode GraphQL endpoint"],
                    )

                if resp.status_code != 200:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        message=f"LeetCode service responded with HTTP status {resp.status_code}.",
                        provider=self.provider_name,
                        raw_metadata={"username": username, "http_status": resp.status_code},
                        verified_at=now,
                    )

                data = resp.json()
                data_obj = data.get("data") or {}
                matched_user = data_obj.get("matchedUser")

                if not matched_user:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        message=f"LeetCode user '{username}' does not exist or profile is private.",
                        provider=self.provider_name,
                        raw_metadata={"username": username},
                        verified_at=now,
                    )

                # Extract problem counts
                subs = (matched_user.get("submitStatsGlobal") or {}).get("acSubmissionNum") or []
                easy_c, med_c, hard_c, total_c = 0, 0, 0, 0
                for s in subs:
                    diff = s.get("difficulty", "").lower()
                    cnt = int(s.get("count", 0))
                    if diff == "all":
                        total_c = cnt
                    elif diff == "easy":
                        easy_c = cnt
                    elif diff == "medium":
                        med_c = cnt
                    elif diff == "hard":
                        hard_c = cnt

                if total_c == 0 and (easy_c + med_c + hard_c > 0):
                    total_c = easy_c + med_c + hard_c

                # Extract contest stats
                contest = data_obj.get("userContestRanking") or {}
                rating = float(contest.get("rating") or 0.0)
                global_rank = int(contest.get("globalRanking") or 0)
                top_pct = float(contest.get("topPercentage") or 0.0)
                attended = int(contest.get("attendedContestsCount") or 0)

                # Extract tag problem counts
                tag_counts = matched_user.get("tagProblemCounts")

                inspection = {
                    "username": username,
                    "total_solved": total_c,
                    "easy_solved": easy_c,
                    "medium_solved": med_c,
                    "hard_solved": hard_c,
                    "contest_rating": rating,
                    "contest_ranking": global_rank,
                    "top_percentage": top_pct,
                    "contests_attended": attended,
                    "tag_problem_counts": tag_counts,
                }

                return self._build_result_from_inspection(inspection, now)

        except (httpx.RequestError, Exception) as e:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Network connection to LeetCode failed: {str(e)[:100]}",
                provider=self.provider_name,
                raw_metadata={"username": username, "error": str(e)},
                verified_at=now,
                warnings=["Network timeout or unreachable external endpoint"],
            )

    def _extract_topic_summary(
        self, facts: dict, total_solved: int, hard_solved: int
    ) -> Tuple[LeetCodeTopicSummary, int, int, int, int]:
        """
        Extract topic coverage, breadth, and depth across 9 canonical DSA pillars.
        Supports:
        1. Problem-level list ('problems') with deduplication and pillar mapping
        2. GraphQL tagProblemCounts format ('tag_problem_counts')
        3. Pre-aggregated dictionary ('topics' or 'topic_counts')
        Returns (summary, total_solved, easy_solved, medium_solved, hard_solved).
        """
        pillar_counts: Dict[str, int] = defaultdict(int)
        problems_with_topic = 0
        topic_occurrences = 0
        has_topic_data = False

        easy_c = int(facts.get("easy_solved", 0))
        med_c = int(facts.get("medium_solved", 0))
        hard_c = int(facts.get("hard_solved", 0))
        tot_c = total_solved

        # Format 1: Problem list
        raw_problems = facts.get("problems")
        if isinstance(raw_problems, list) and len(raw_problems) > 0:
            has_topic_data = True
            seen_problem_keys: Set[str] = set()
            unique_problems: List[dict] = []

            for p in raw_problems:
                pid = str(p.get("id") or p.get("problem_id") or p.get("title") or "").strip().lower()
                if not pid or pid in seen_problem_keys:
                    continue
                seen_problem_keys.add(pid)
                unique_problems.append(p)

            # If total_solved was unset, deduce difficulty distribution from unique problems
            if tot_c == 0 and len(unique_problems) > 0:
                tot_c = len(unique_problems)
                easy_c = sum(1 for p in unique_problems if (p.get("difficulty") or "").lower() == "easy")
                med_c = sum(1 for p in unique_problems if (p.get("difficulty") or "").lower() == "medium")
                hard_c = sum(1 for p in unique_problems if (p.get("difficulty") or "").lower() == "hard")

            for p in unique_problems:
                tags = p.get("tags") or p.get("topics") or []
                if tags:
                    problems_with_topic += 1
                topic_occurrences += len(tags)

                # Deduplicate multiple tags belonging to the same pillar for a single problem
                problem_pillars: Set[str] = set()
                for t in tags:
                    slug = normalize_tag_slug(str(t))
                    pillar = TAG_SLUG_TO_PILLAR.get(slug)
                    if pillar:
                        problem_pillars.add(pillar)

                for pillar in problem_pillars:
                    pillar_counts[pillar] += 1

        # Format 2: GraphQL tagProblemCounts structure
        raw_tag_counts = facts.get("tag_problem_counts")
        if not has_topic_data and raw_tag_counts:
            entries: List[dict] = []
            if isinstance(raw_tag_counts, dict):
                for cat in ("fundamental", "intermediate", "advanced"):
                    items = raw_tag_counts.get(cat)
                    if isinstance(items, list):
                        entries.extend(items)
                if not entries:
                    for v in raw_tag_counts.values():
                        if isinstance(v, list):
                            entries.extend(v)
            elif isinstance(raw_tag_counts, list):
                entries = raw_tag_counts

            if entries:
                has_topic_data = True
                pillar_tag_lists: Dict[str, List[int]] = defaultdict(list)
                for item in entries:
                    name = item.get("tagName") or ""
                    slug = item.get("tagSlug") or normalize_tag_slug(name)
                    cnt = int(item.get("problemsSolved") or item.get("count") or 0)
                    if cnt <= 0:
                        continue
                    topic_occurrences += cnt
                    pillar = TAG_SLUG_TO_PILLAR.get(slug)
                    if pillar:
                        pillar_tag_lists[pillar].append(cnt)

                # Estimate unique pillar solved with overlap discount
                for pillar, counts in pillar_tag_lists.items():
                    counts.sort(reverse=True)
                    est = counts[0] + int(0.35 * sum(counts[1:]))
                    pillar_counts[pillar] = min(tot_c, max(counts[0], est))

                problems_with_topic = min(tot_c, sum(pillar_counts.values()))

        # Format 3: Dictionary of topics/pillars
        raw_topics = facts.get("topics") or facts.get("topic_counts")
        if not has_topic_data and isinstance(raw_topics, dict) and len(raw_topics) > 0:
            has_topic_data = True
            pillar_tag_lists = defaultdict(list)
            for key, count in raw_topics.items():
                cnt = int(count or 0)
                if cnt <= 0:
                    continue
                topic_occurrences += cnt
                if key in DSA_PILLARS:
                    pillar_counts[key] = min(tot_c, cnt) if tot_c > 0 else cnt
                else:
                    slug = normalize_tag_slug(str(key))
                    pillar = TAG_SLUG_TO_PILLAR.get(slug)
                    if pillar:
                        pillar_tag_lists[pillar].append(cnt)

            for pillar, counts in pillar_tag_lists.items():
                if pillar not in pillar_counts:
                    counts.sort(reverse=True)
                    est = counts[0] + int(0.35 * sum(counts[1:]))
                    pillar_counts[pillar] = min(tot_c, max(counts[0], est)) if tot_c > 0 else est

            problems_with_topic = min(tot_c, sum(pillar_counts.values())) if tot_c > 0 else sum(pillar_counts.values())

        if not has_topic_data:
            empty_summary = LeetCodeTopicSummary(
                status="unavailable",
                breadth_score=0.0,
                depth_score=0.0,
                covered_pillars=[],
                moderate_pillars=[],
                weak_pillars=[],
                missing_pillars=DSA_PILLARS.copy(),
                pillar_breakdown={},
                problems_with_topic=0,
                topic_occurrences=0,
            )
            return empty_summary, tot_c, easy_c, med_c, hard_c

        # Categorize all 9 DSA Pillars
        covered_pillars: List[str] = []
        moderate_pillars: List[str] = []
        weak_pillars: List[str] = []
        missing_pillars: List[str] = []
        pillar_breakdown: Dict[str, Dict[str, Any]] = {}

        for p in DSA_PILLARS:
            solved = pillar_counts.get(p, 0)
            pct = round((solved / max(1, tot_c)) * 100.0, 1)
            if solved >= 15:
                status = "covered"
                covered_pillars.append(p)
            elif solved >= 5:
                status = "moderate"
                moderate_pillars.append(p)
            elif solved >= 1:
                status = "weak"
                weak_pillars.append(p)
            else:
                status = "missing"
                missing_pillars.append(p)

            pillar_breakdown[p] = {
                "solved": solved,
                "percentage": pct,
                "status": status,
            }

        # Calculate Topic Breadth Score with Concentration Penalty
        raw_breadth = (len(covered_pillars) * 1.0 + len(moderate_pillars) * 0.55 + len(weak_pillars) * 0.20) / 9.0

        pillar_sum = sum(pillar_counts.values())
        if pillar_sum > 0:
            sorted_counts = sorted(pillar_counts.values(), reverse=True)
            top2_sum = sum(sorted_counts[:2])
            top2_share = top2_sum / float(pillar_sum)
            # Penalize when student has 2 or 3 moderate/covered pillars but top 2 dominate >75%
            if top2_share > 0.75 and 2 <= (len(covered_pillars) + len(moderate_pillars)) < 4:
                penalty = min(0.50, (top2_share - 0.75) * 1.5)
                breadth_score = raw_breadth * (1.0 - penalty)
            else:
                breadth_score = raw_breadth
        else:
            breadth_score = 0.0

        breadth_score = round(max(0.0, min(1.0, breadth_score)), 2)

        # Calculate Topic Depth Score (Advanced Algorithmic Topics + Hard Problems)
        advanced_solved = sum(pillar_counts.get(p, 0) for p in ADVANCED_PILLARS)
        if advanced_solved >= 50:
            adv_factor = 1.0
        elif advanced_solved >= 30:
            adv_factor = 0.85
        elif advanced_solved >= 15:
            adv_factor = 0.65
        elif advanced_solved >= 5:
            adv_factor = 0.40
        elif advanced_solved >= 1:
            adv_factor = 0.20
        else:
            adv_factor = 0.0

        hard_factor = min(1.0, hard_c / 20.0)
        depth_score = round(min(1.0, 0.65 * adv_factor + 0.35 * hard_factor), 2)

        summary = LeetCodeTopicSummary(
            status="available",
            breadth_score=breadth_score,
            depth_score=depth_score,
            covered_pillars=covered_pillars,
            moderate_pillars=moderate_pillars,
            weak_pillars=weak_pillars,
            missing_pillars=missing_pillars,
            pillar_breakdown=pillar_breakdown,
            problems_with_topic=problems_with_topic,
            topic_occurrences=topic_occurrences,
        )

        return summary, tot_c, easy_c, med_c, hard_c

    def _build_result_from_inspection(self, facts: dict, verified_at: datetime) -> VerificationResult:
        username = facts.get("username") or "user"
        initial_total = int(facts.get("total_solved", 0))
        initial_hard = int(facts.get("hard_solved", 0))

        # Extract topic coverage, breadth, depth, and reconciled counts
        topic_summary, total, easy, med, hard = self._extract_topic_summary(facts, initial_total, initial_hard)

        rating = float(facts.get("contest_rating", 0.0))
        top_pct = float(facts.get("top_percentage", 0.0))
        contests = int(facts.get("contests_attended", 0))

        facts_list = [
            f"Solved {total} problems: {easy} Easy, {med} Medium, {hard} Hard",
        ]
        if topic_summary.status == "available":
            facts_list.append(
                f"DSA Topic Coverage: {len(topic_summary.covered_pillars)} covered, "
                f"{len(topic_summary.moderate_pillars)} moderate, "
                f"{len(topic_summary.missing_pillars)} unpracticed "
                f"(Breadth {int(topic_summary.breadth_score * 100)}%, Depth {int(topic_summary.depth_score * 100)}%)"
            )
            if topic_summary.missing_pillars:
                missing_preview = ", ".join(topic_summary.missing_pillars[:3])
                if len(topic_summary.missing_pillars) > 3:
                    missing_preview += f" (+{len(topic_summary.missing_pillars) - 3} more)"
                facts_list.append(f"Missing DSA Pillars: {missing_preview}")

        if rating > 0:
            facts_list.append(
                f"Contest rating {rating:.1f} (top {top_pct:.1f}% across {contests} attended contests)"
            )

        # Calculate weighted problem solving index
        weighted_score = (easy * WEIGHT_EASY) + (med * WEIGHT_MEDIUM) + (hard * WEIGHT_HARD)

        if total == 0:
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                message=f"Verified LeetCode profile '{username}', but 0 problems have been solved.",
                provider=self.provider_name,
                signals=[],
                raw_metadata={**facts, "topic_coverage": topic_summary.to_dict()},
                profile={"username": username},
                facts=facts_list,
                warnings=["Profile shows zero accepted submissions"],
                verified_at=verified_at,
            )

        # Calibrate DSA Signal Strength strictly by Topic Breadth across the 9 DSA pillars
        if topic_summary.status == "available":
            diff_index = weighted_score / max(1.0, (total * WEIGHT_MEDIUM))
            diff_factor = max(0.40, min(1.30, diff_index))

            # Pillar quality multiplier evaluates challenge difficulty & advanced topic depth
            quality_mult = (
                0.55
                + 0.20 * (diff_factor / 1.0)
                + 0.15 * topic_summary.depth_score
            )

            # DSA proficiency is strictly gated by topic breadth across the 9 canonical pillars:
            base_strength = round(min(0.88, max(0.0, topic_summary.breadth_score * quality_mult)), 2)

            if base_strength >= 0.78:
                depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL
            elif base_strength >= 0.55:
                depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION
            elif base_strength >= 0.25:
                depth = EvidenceDepth.LEVEL_2_CONFIG
            else:
                depth = EvidenceDepth.LEVEL_1_MENTION

            dsa_reason = (
                f"LeetCode profile '{username}' shows verified practice of {total} problems "
                f"({easy} Easy, {med} Medium, {hard} Hard). Topic analysis across the 9 DSA pillars: "
                f"{len(topic_summary.covered_pillars)} covered, {len(topic_summary.moderate_pillars)} moderate, "
                f"{len(topic_summary.missing_pillars)} unpracticed "
                f"(Breadth {int(topic_summary.breadth_score * 100)}%, Depth {int(topic_summary.depth_score * 100)}%)."
            )
        else:
            # Fallback: Topic breakdown across the 9 pillars is unverified
            # Since topic breadth cannot be confirmed, we MUST NOT assume multi-topic mastery.
            # Base DSA strength is conservatively capped at 0.35.
            base_strength = round(min(0.35, max(0.08, 0.08 + (weighted_score / 200.0) * 0.22)), 2)
            if base_strength >= 0.25:
                depth = EvidenceDepth.LEVEL_2_CONFIG
            else:
                depth = EvidenceDepth.LEVEL_1_MENTION

            dsa_reason = (
                f"LeetCode profile '{username}' shows verified practice of {total} problems "
                f"({easy} Easy, {med} Medium, {hard} Hard; difficulty-weighted index {weighted_score:.1f}). "
                f"Topic breakdown across the 9 DSA pillars is unverified; DSA proficiency is conservatively "
                f"capped until topic data is synced."
            )

        signals: List[ExtractedSignal] = []

        # 1. Primary Skill: Data Structures & Algorithms
        dsa_canonical = normalize_skill("Data Structures & Algorithms") or "Data Structures & Algorithms"
        dsa_metadata = {
            "total_solved": total,
            "easy": easy,
            "medium": med,
            "hard": hard,
            "weighted_score": round(weighted_score, 1),
            "topic_data_status": topic_summary.status,
            "topic_breadth_score": topic_summary.breadth_score,
            "topic_depth_score": topic_summary.depth_score,
            "covered_topics": topic_summary.covered_pillars,
            "moderate_topics": topic_summary.moderate_pillars,
            "weak_topics": topic_summary.weak_pillars,
            "missing_topics": topic_summary.missing_pillars,
            "pillar_breakdown": topic_summary.pillar_breakdown,
            "problems_with_topic": topic_summary.problems_with_topic,
            "topic_occurrences": topic_summary.topic_occurrences,
        }

        signals.append(
            ExtractedSignal(
                skill=dsa_canonical,
                signal_strength=base_strength,
                depth=depth,
                reason=dsa_reason,
                source_reliability=LEETCODE_RELIABILITY,
                metadata=dsa_metadata,
            )
        )

        # 2. Problem Solving: Evaluated on problem solving stamina, challenge difficulty, and volume
        ps_canonical = normalize_skill("Problem Solving") or "Problem Solving"
        ps_volume = 1.0 - math.exp(-total / 150.0)
        ps_diff = max(0.40, min(1.25, weighted_score / max(1.0, (total * WEIGHT_MEDIUM))))
        ps_strength = round(min(0.85, max(0.15, 0.18 + 0.65 * ps_volume * ps_diff)), 2)
        if ps_strength >= 0.75:
            ps_depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL
        elif ps_strength >= 0.55:
            ps_depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION
        elif ps_strength >= 0.25:
            ps_depth = EvidenceDepth.LEVEL_2_CONFIG
        else:
            ps_depth = EvidenceDepth.LEVEL_1_MENTION

        signals.append(
            ExtractedSignal(
                skill=ps_canonical,
                signal_strength=ps_strength,
                depth=ps_depth,
                reason=f"Demonstrated algorithmic problem solving across {total} LeetCode challenges (weighted index {weighted_score:.1f}).",
                source_reliability=LEETCODE_RELIABILITY,
                metadata={"total_solved": total, "weighted_score": round(weighted_score, 1)},
            )
        )

        # 3. Competitive Programming (Only when contest participation / rating exists)
        if rating > 1300 or contests >= 3:
            cp_strength = round(min(0.86, max(0.40, 0.45 + (max(0.0, rating - 1300) / 900.0) * 0.40)), 2)
            cp_depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL if rating >= 1800 else EvidenceDepth.LEVEL_3_IMPLEMENTATION
            cp_canonical = normalize_skill("Competitive Programming") or "Competitive Programming"
            signals.append(
                ExtractedSignal(
                    skill=cp_canonical,
                    signal_strength=cp_strength,
                    depth=cp_depth,
                    reason=(
                        f"Active LeetCode contest participant: rating {rating:.1f} "
                        f"(top {top_pct:.1f}% globally over {contests} rated contests)."
                    ),
                    source_reliability=LEETCODE_RELIABILITY,
                    metadata={"rating": rating, "contests": contests, "top_percentage": top_pct},
                )
            )

        summary_msg = f"Verified LeetCode profile '{username}': {total} problems solved ({med} Medium, {hard} Hard)."
        if topic_summary.status == "available":
            summary_msg += f" Topic breadth: {int(topic_summary.breadth_score * 100)}%."
        if rating > 0:
            summary_msg += f" Contest rating {rating:.1f}."

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message=summary_msg,
            provider=self.provider_name,
            signals=signals,
            raw_metadata={
                **facts,
                "total_solved": total,
                "easy_solved": easy,
                "medium_solved": med,
                "hard_solved": hard,
                "topic_coverage": topic_summary.to_dict(),
            },
            profile={"username": username},
            facts=facts_list,
            verified_at=verified_at,
        )

    async def extract_signals(self, evidence: dict) -> List[ExtractedSignal]:
        res = await self.verify(evidence)
        return res.signals
