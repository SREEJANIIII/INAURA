import asyncio
import pytest
from datetime import datetime, timezone

from app.services.evidence.base import EvidenceDepth, VerificationStatus
from app.services.evidence.leetcode import (
    LeetCodeProvider,
    DSA_PILLARS,
    ADVANCED_PILLARS,
    normalize_tag_slug,
    normalize_tag_display_name,
)
from app.services import signal_extractor as se
from app.services import skill_engine


def test_tag_normalization_mappings():
    """Verify tag slugs and display names are cleanly normalized."""
    assert normalize_tag_slug("Depth-First Search") == "depth-first-search"
    assert normalize_tag_slug("  Breadth-First Search  ") == "breadth-first-search"
    assert normalize_tag_slug("Binary_Search_Tree") == "binary-search-tree"
    assert normalize_tag_slug("Dynamic Programming") == "dynamic-programming"
    assert normalize_tag_slug("Two Pointers") == "two-pointers"

    assert normalize_tag_display_name("Depth-First Search") == "DFS"
    assert normalize_tag_display_name("breadth-first-search") == "BFS"
    assert normalize_tag_display_name("Binary Search Tree") == "BST"
    assert normalize_tag_display_name("graph-theory") == "Graph"
    assert normalize_tag_display_name("dynamic-programming") == "Dynamic Programming"


def test_problem_list_extraction_and_deduplication():
    """
    Test extraction from a list of solved problems:
    1. Deduplicates identical submissions (same problem ID or title)
    2. Correctly counts problems_with_topic and topic_occurrences
    3. Multi-tag within the same pillar (DFS + BFS + Union Find) counts as 1 problem in Graphs
    """
    async def _run():
        provider = LeetCodeProvider()
        problems = [
            {"id": "1", "title": "Two Sum", "difficulty": "Easy", "tags": ["Array", "Hash Table"]},
            {"id": "1", "title": "Two Sum", "difficulty": "Easy", "tags": ["Array", "Hash Table"]},  # Duplicate
            {"id": "15", "title": "3Sum", "difficulty": "Medium", "tags": ["Array", "Two Pointers", "Sorting"]},
            {"id": "15", "title": "3Sum", "difficulty": "Medium", "tags": ["Array", "Two Pointers", "Sorting"]},  # Duplicate
            {
                "id": "200",
                "title": "Number of Islands",
                "difficulty": "Medium",
                "tags": ["Depth-First Search", "Breadth-First Search", "Union Find", "Matrix"],
            },
            {
                "id": "300",
                "title": "Longest Increasing Subsequence",
                "difficulty": "Medium",
                "tags": ["Dynamic Programming", "Binary Search"],
            },
        ]

        ev = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/coder",
            "mock_inspection": {
                "username": "coder",
                "problems": problems,
            },
        }

        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED

        dsa_signal = next(s for s in res.signals if s.skill == "Data Structures & Algorithms")
        meta = dsa_signal.metadata

        # Assert duplicate entries were deduplicated (4 unique problems)
        assert meta["total_solved"] == 4
        assert meta["easy"] == 1
        assert meta["medium"] == 3
        assert meta["hard"] == 0

        # Assert topic metrics
        assert meta["topic_data_status"] == "available"
        assert meta["problems_with_topic"] == 4
        # Total tag occurrences across 4 unique problems: 2 + 3 + 4 + 2 = 11
        assert meta["topic_occurrences"] == 11

        breakdown = meta["pillar_breakdown"]
        # Number of Islands has DFS, BFS, Union Find -> exactly 1 problem counted in Graphs pillar
        assert breakdown["Graphs"]["solved"] == 1
        # Two Sum, 3Sum, Number of Islands (Matrix) -> 3 problems in Arrays & Strings
        assert breakdown["Arrays & Strings"]["solved"] == 3
        # 3Sum (Sorting), LIS (Binary Search) -> 2 problems in Searching & Sorting
        assert breakdown["Searching & Sorting"]["solved"] == 2
        # LIS (Dynamic Programming) -> 1 problem in Dynamic Programming
        assert breakdown["Dynamic Programming"]["solved"] == 1

    asyncio.run(_run())


def test_tag_problem_counts_graphql_extraction():
    """Verify parsing from LeetCode GraphQL tagProblemCounts structure."""
    async def _run():
        provider = LeetCodeProvider()
        tag_counts = {
            "fundamental": [
                {"tagName": "Array", "tagSlug": "array", "problemsSolved": 80},
                {"tagName": "String", "tagSlug": "string", "problemsSolved": 60},
                {"tagName": "Two Pointers", "tagSlug": "two-pointers", "problemsSolved": 30},
                {"tagName": "Matrix", "tagSlug": "matrix", "problemsSolved": 20},
            ],
            "intermediate": [
                {"tagName": "Depth-First Search", "tagSlug": "depth-first-search", "problemsSolved": 40},
                {"tagName": "Breadth-First Search", "tagSlug": "breadth-first-search", "problemsSolved": 35},
                {"tagName": "Tree", "tagSlug": "tree", "problemsSolved": 45},
                {"tagName": "Binary Search", "tagSlug": "binary-search", "problemsSolved": 30},
            ],
            "advanced": [
                {"tagName": "Dynamic Programming", "tagSlug": "dynamic-programming", "problemsSolved": 50},
                {"tagName": "Union Find", "tagSlug": "union-find", "problemsSolved": 20},
            ],
        }

        ev = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/graph_master",
            "mock_inspection": {
                "username": "graph_master",
                "total_solved": 200,
                "easy_solved": 50,
                "medium_solved": 120,
                "hard_solved": 30,
                "tag_problem_counts": tag_counts,
            },
        }

        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED

        dsa_signal = next(s for s in res.signals if s.skill == "Data Structures & Algorithms")
        meta = dsa_signal.metadata

        assert meta["topic_data_status"] == "available"
        assert meta["topic_occurrences"] > 200

        # Graphs pillar receives DFS (40), BFS (35), Union Find (20) with overlap discount: >= 40
        assert meta["pillar_breakdown"]["Graphs"]["solved"] >= 40
        assert "Graphs" in meta["covered_topics"]
        assert "Dynamic Programming" in meta["covered_topics"]
        assert "Arrays & Strings" in meta["covered_topics"]

    asyncio.run(_run())


def test_pillar_classification_and_missing_pillars():
    """Verify classification thresholds: covered (>=15), moderate (5-14), weak (1-4), missing (0)."""
    async def _run():
        provider = LeetCodeProvider()
        topics = {
            "Arrays & Strings": 35,      # covered
            "Trees": 18,                 # covered
            "Graphs": 10,                # moderate
            "Searching & Sorting": 6,    # moderate
            "Dynamic Programming": 3,    # weak
            "Linked Lists": 2,           # weak
            # Stacks & Queues: 0 (missing)
            # Greedy: 0 (missing)
            # Backtracking: 0 (missing)
        }

        ev = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/intermediate_coder",
            "mock_inspection": {
                "username": "intermediate_coder",
                "total_solved": 74,
                "easy_solved": 30,
                "medium_solved": 40,
                "hard_solved": 4,
                "topics": topics,
            },
        }

        res = await provider.verify(ev)
        dsa_signal = next(s for s in res.signals if s.skill == "Data Structures & Algorithms")
        meta = dsa_signal.metadata

        assert set(meta["covered_topics"]) == {"Arrays & Strings", "Trees"}
        assert set(meta["moderate_topics"]) == {"Graphs", "Searching & Sorting"}
        assert set(meta["weak_topics"]) == {"Dynamic Programming", "Linked Lists"}
        assert set(meta["missing_topics"]) == {"Stacks & Queues", "Greedy", "Backtracking"}

        # Check facts list contains missing pillars warning
        missing_fact = next((f for f in res.facts if "Missing DSA Pillars" in f), None)
        assert missing_fact is not None

    asyncio.run(_run())


def test_student_a_narrow_concentration_penalty():
    """
    Student A: 300 problems solved, but 270 in Arrays & Strings, 20 in Stacks, 10 in Searching.
    Missing 6 pillars (Trees, Graphs, DP, Backtracking, Greedy, Linked Lists).
    Top 2 pillars account for 290/300 = 96.7% of practice (>75%).
    Concentration penalty must severely lower breadth score and keep DSA signal modest.
    """
    async def _run():
        provider = LeetCodeProvider()
        ev = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/student_a",
            "mock_inspection": {
                "username": "student_a",
                "total_solved": 300,
                "easy_solved": 220,
                "medium_solved": 75,
                "hard_solved": 5,
                "topics": {
                    "Arrays & Strings": 270,
                    "Stacks & Queues": 20,
                    "Searching & Sorting": 10,
                },
            },
        }

        res = await provider.verify(ev)
        dsa_signal = next(s for s in res.signals if s.skill == "Data Structures & Algorithms")
        meta = dsa_signal.metadata

        # Concentration penalty ensures breadth score is low despite 300 total problems
        assert meta["topic_breadth_score"] <= 0.25
        assert len(meta["missing_topics"]) == 6
        assert "Trees" in meta["missing_topics"]
        assert "Graphs" in meta["missing_topics"]
        assert "Dynamic Programming" in meta["missing_topics"]

        # Signal strength must NOT be high expert level
        assert dsa_signal.signal_strength <= 0.52
        assert dsa_signal.depth in (EvidenceDepth.LEVEL_1_MENTION, EvidenceDepth.LEVEL_2_CONFIG)

    asyncio.run(_run())


def test_student_b_broad_and_deep_mastery():
    """
    Student B: Same 300 problems solved, but balanced across all 9 DSA pillars with 60 Hard problems.
    All 9 pillars covered. No concentration penalty. High breadth and depth scores.
    """
    async def _run():
        provider = LeetCodeProvider()
        ev = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/student_b",
            "mock_inspection": {
                "username": "student_b",
                "total_solved": 300,
                "easy_solved": 50,
                "medium_solved": 190,
                "hard_solved": 60,
                "topics": {
                    "Arrays & Strings": 45,
                    "Linked Lists": 25,
                    "Stacks & Queues": 25,
                    "Trees": 45,
                    "Graphs": 45,
                    "Searching & Sorting": 35,
                    "Dynamic Programming": 45,
                    "Greedy": 20,
                    "Backtracking": 15,
                },
            },
        }

        res = await provider.verify(ev)
        dsa_signal = next(s for s in res.signals if s.skill == "Data Structures & Algorithms")
        meta = dsa_signal.metadata

        # All pillars covered
        assert meta["topic_breadth_score"] >= 0.95
        assert meta["topic_depth_score"] >= 0.90
        assert len(meta["missing_topics"]) == 0
        assert len(meta["covered_topics"]) == 9

        # Strong substantial implementation level
        assert dsa_signal.signal_strength >= 0.82
        assert dsa_signal.depth == EvidenceDepth.LEVEL_4_SUBSTANTIAL

    asyncio.run(_run())


def test_student_a_vs_student_b_contrast():
    """
    CORE OBJECTIVE ASSERTION:
    A student with 300 problems concentrated in Arrays/Strings must NOT receive the same
    DSA assessment as a student with 300 problems covering all pillars.
    Difference in signal strength must be >= 0.30.
    """
    async def _run():
        provider = LeetCodeProvider()

        ev_a = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/alice_arrays",
            "mock_inspection": {
                "username": "alice_arrays",
                "total_solved": 300,
                "easy_solved": 220,
                "medium_solved": 75,
                "hard_solved": 5,
                "topics": {
                    "Arrays & Strings": 270,
                    "Stacks & Queues": 20,
                    "Searching & Sorting": 10,
                },
            },
        }
        ev_b = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/bob_balanced",
            "mock_inspection": {
                "username": "bob_balanced",
                "total_solved": 300,
                "easy_solved": 50,
                "medium_solved": 190,
                "hard_solved": 60,
                "topics": {
                    "Arrays & Strings": 45,
                    "Linked Lists": 25,
                    "Stacks & Queues": 25,
                    "Trees": 45,
                    "Graphs": 45,
                    "Searching & Sorting": 35,
                    "Dynamic Programming": 45,
                    "Greedy": 20,
                    "Backtracking": 15,
                },
            },
        }

        res_a = await provider.verify(ev_a)
        res_b = await provider.verify(ev_b)

        sig_a = next(s for s in res_a.signals if s.skill == "Data Structures & Algorithms")
        sig_b = next(s for s in res_b.signals if s.skill == "Data Structures & Algorithms")

        diff = sig_b.signal_strength - sig_a.signal_strength
        assert diff >= 0.30, f"Expected difference >= 0.30, got {diff:.2f} (A: {sig_a.signal_strength}, B: {sig_b.signal_strength})"
        assert sig_a.signal_strength <= 0.52
        assert sig_b.signal_strength >= 0.82

    asyncio.run(_run())


def test_volume_diminishing_returns():
    """
    Grinding 250 additional problems strictly in the same topic yields minimal signal gain (< 0.08).
    Volume alone without topic growth suffers diminishing returns.
    """
    async def _run():
        provider = LeetCodeProvider()

        ev_250 = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/grinder",
            "mock_inspection": {
                "username": "grinder",
                "total_solved": 250,
                "easy_solved": 185,
                "medium_solved": 60,
                "hard_solved": 5,
                "topics": {
                    "Arrays & Strings": 225,
                    "Stacks & Queues": 15,
                    "Searching & Sorting": 10,
                },
            },
        }
        ev_500 = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/grinder",
            "mock_inspection": {
                "username": "grinder",
                "total_solved": 500,
                "easy_solved": 360,
                "medium_solved": 130,
                "hard_solved": 10,
                "topics": {
                    "Arrays & Strings": 450,
                    "Stacks & Queues": 35,
                    "Searching & Sorting": 15,
                },
            },
        }

        res_250 = await provider.verify(ev_250)
        res_500 = await provider.verify(ev_500)

        sig_250 = next(s for s in res_250.signals if s.skill == "Data Structures & Algorithms")
        sig_500 = next(s for s in res_500.signals if s.skill == "Data Structures & Algorithms")

        gain = sig_500.signal_strength - sig_250.signal_strength
        assert gain < 0.08, f"Expected gain < 0.08 for 250 extra single-topic problems, got {gain:.2f}"

    asyncio.run(_run())


def test_topic_data_unavailable_graceful_fallback():
    """
    When profile or mock does not supply topic statistics, provider falls back cleanly
    to difficulty-weighted problem index with topic_data_status = 'unavailable' without failing.
    DSA proficiency is conservatively capped (<= 0.35) so missing topic data never falsely awards 66%.
    Problem Solving signal appropriately credits the problem count.
    """
    async def _run():
        provider = LeetCodeProvider()
        ev = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/legacy_user",
            "mock_inspection": {
                "username": "legacy_user",
                "total_solved": 120,
                "easy_solved": 30,
                "medium_solved": 80,
                "hard_solved": 10,
            },
        }

        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED

        dsa_signal = next(s for s in res.signals if s.skill == "Data Structures & Algorithms")
        meta = dsa_signal.metadata

        assert meta["topic_data_status"] == "unavailable"
        assert meta["total_solved"] == 120
        # Conservative estimate capped at <= 0.35 without topic data
        assert dsa_signal.signal_strength <= 0.35
        assert dsa_signal.signal_strength >= 0.12
        assert dsa_signal.depth in (EvidenceDepth.LEVEL_1_MENTION, EvidenceDepth.LEVEL_2_CONFIG)

        # Problem Solving signal appropriately rewards the 120 problems solved
        ps_signal = next(s for s in res.signals if s.skill == "Problem Solving")
        assert ps_signal.signal_strength >= 0.35

    asyncio.run(_run())


def test_single_topic_arrays_only_strictly_capped():
    """
    CRITICAL USER REQUIREMENT TEST:
    A student has solved 100 questions exclusively in Arrays & Strings (0 in other 8 topics).
    DSA proficiency must NOT be 66%. It must strictly be <= 15% (~0.08 - 0.12),
    accurately reflecting that only 1 of 9 pillars has been covered, and all 8 other
    pillars must be flagged as missing.
    """
    async def _run():
        provider = LeetCodeProvider()
        ev = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/arrays_only_student",
            "mock_inspection": {
                "username": "arrays_only_student",
                "total_solved": 100,
                "easy_solved": 40,
                "medium_solved": 55,
                "hard_solved": 5,
                "topics": {
                    "Arrays & Strings": 100,
                },
            },
        }

        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED

        dsa_signal = next(s for s in res.signals if s.skill == "Data Structures & Algorithms")
        meta = dsa_signal.metadata

        # Strictly 1 of 9 pillars covered, 8 missing
        assert meta["covered_topics"] == ["Arrays & Strings"]
        assert len(meta["missing_topics"]) == 8
        assert "Trees" in meta["missing_topics"]
        assert "Graphs" in meta["missing_topics"]
        assert "Dynamic Programming" in meta["missing_topics"]
        assert "Linked Lists" in meta["missing_topics"]

        # Breadth score is ~11% (1/9)
        assert meta["topic_breadth_score"] <= 0.15
        assert meta["topic_breadth_score"] >= 0.10

        # CRITICAL ASSERTION: DSA signal strength MUST be <= 0.15 (under 15%)
        assert dsa_signal.signal_strength <= 0.15, f"Expected <= 0.15, got {dsa_signal.signal_strength}"
        assert dsa_signal.signal_strength >= 0.06

        # Problem Solving signal appropriately credits the 100 problems
        ps_signal = next(s for s in res.signals if s.skill == "Problem Solving")
        assert ps_signal.signal_strength >= 0.30

        # Full skill engine integration check
        prof, _, _, _ = skill_engine.proficiency([
            {
                "skill": dsa_signal.skill,
                "signal_strength": dsa_signal.signal_strength,
                "source_reliability": dsa_signal.source_reliability,
            }
        ])
        assert prof <= 0.15, f"DSA proficiency in skill engine expected <= 0.15, got {prof}"

    asyncio.run(_run())


def test_zero_problems_solved_empty_profile():
    """Empty profile with 0 problems returns VERIFIED with 0 signals."""
    async def _run():
        provider = LeetCodeProvider()
        ev = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/new_student",
            "mock_inspection": {
                "username": "new_student",
                "total_solved": 0,
                "easy_solved": 0,
                "medium_solved": 0,
                "hard_solved": 0,
            },
        }

        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED
        assert len(res.signals) == 0
        assert res.raw_metadata["topic_coverage"]["status"] == "unavailable"

    asyncio.run(_run())


def test_signal_extractor_and_skill_engine_integration():
    """
    Verify full pipeline integration:
    LeetCodeProvider -> signal_extractor -> skill_engine.proficiency
    Preserves topic metadata and computes differentiated proficiency.
    """
    evidence_a = [
        {
            "id": "ev-a",
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/student_a",
            "mock_inspection": {
                "username": "student_a",
                "total_solved": 300,
                "easy_solved": 220,
                "medium_solved": 75,
                "hard_solved": 5,
                "topics": {
                    "Arrays & Strings": 270,
                    "Stacks & Queues": 20,
                    "Searching & Sorting": 10,
                },
            },
        }
    ]
    evidence_b = [
        {
            "id": "ev-b",
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/student_b",
            "mock_inspection": {
                "username": "student_b",
                "total_solved": 300,
                "easy_solved": 50,
                "medium_solved": 190,
                "hard_solved": 60,
                "topics": {
                    "Arrays & Strings": 45,
                    "Linked Lists": 25,
                    "Stacks & Queues": 25,
                    "Trees": 45,
                    "Graphs": 45,
                    "Searching & Sorting": 35,
                    "Dynamic Programming": 45,
                    "Greedy": 20,
                    "Backtracking": 15,
                },
            },
        }
    ]

    sigs_a = se.extract_signals(evidence_a, [], [])
    sigs_b = se.extract_signals(evidence_b, [], [])

    dsa_sig_a = [s for s in sigs_a if s["canonical_name"] == "Data Structures & Algorithms"]
    dsa_sig_b = [s for s in sigs_b if s["canonical_name"] == "Data Structures & Algorithms"]

    assert len(dsa_sig_a) == 1
    assert len(dsa_sig_b) == 1

    # Verify topic metadata is preserved on signal
    meta_a = dsa_sig_a[0]["metadata"]
    assert meta_a["topic_data_status"] == "available"
    assert "Trees" in meta_a["missing_topics"]

    # Calculate final proficiency through skill engine
    prof_a, _, _, _ = skill_engine.proficiency(dsa_sig_a)
    prof_b, _, _, _ = skill_engine.proficiency(dsa_sig_b)

    assert prof_a <= 0.52
    assert prof_b >= 0.82
    assert (prof_b - prof_a) >= 0.30
