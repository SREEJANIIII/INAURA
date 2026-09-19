"""
Curated Industry-Standard DSA Pattern & Compulsory Question Bank.
Structured around NeetCode / Blind 75 core algorithmic patterns.
Provides progress persistence and automated skill gap resolution for DSA.
"""

from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timezone
import logging
import re
import httpx

from ..core.supabase import get_supabase_client

logger = logging.getLogger(__name__)

ATTEMPTS_TABLE = "assessment_attempts"
GAPS_TABLE = "skill_gaps"
DSA_SKILL_KEY = "dsa"
DSA_CANONICAL_NAME = "dsa"
DSA_DISPLAY_NAME = "Data Structures & Algorithms"
CHECKLIST_VERSION = "neetcode-dsa-v1"

# 71 Compulsory Industry Questions categorized by Topic and Pattern
COMPULSORY_DSA_QUESTIONS: List[Dict[str, Any]] = [
    # --- 1. Arrays & Hashing ---
    {
        "id": "contains-duplicate",
        "title": "Contains Duplicate",
        "topic": "Arrays & Hashing",
        "pattern": "Hash Set Existence",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/duplicate-integer",
        "leetcode_url": "https://leetcode.com/problems/contains-duplicate/",
        "why_it_matters": "Fundamental O(N) time / O(N) space duplicate detection using a hash set.",
    },
    {
        "id": "valid-anagram",
        "title": "Valid Anagram",
        "topic": "Arrays & Hashing",
        "pattern": "Frequency Counting Map",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/is-anagram",
        "leetcode_url": "https://leetcode.com/problems/valid-anagram/",
        "why_it_matters": "Essential character frequency counting pattern used in string parsing and hashing.",
    },
    {
        "id": "two-sum",
        "title": "Two Sum",
        "topic": "Arrays & Hashing",
        "pattern": "One-Pass Hash Map Complement",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/two-integer-sum",
        "leetcode_url": "https://leetcode.com/problems/two-sum/",
        "why_it_matters": "The most asked interview question; tests O(N) complement lookup vs O(N^2) brute force.",
    },
    {
        "id": "group-anagrams",
        "title": "Group Anagrams",
        "topic": "Arrays & Hashing",
        "pattern": "Categorization by Hash Key",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/anagram-groups",
        "leetcode_url": "https://leetcode.com/problems/group-anagrams/",
        "why_it_matters": "Demonstrates transforming complex objects into canonical hashable map keys.",
    },
    {
        "id": "top-k-frequent-elements",
        "title": "Top K Frequent Elements",
        "topic": "Arrays & Hashing",
        "pattern": "Bucket Sort / Min-Heap",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/top-k-elements-in-list",
        "leetcode_url": "https://leetcode.com/problems/top-k-frequent-elements/",
        "why_it_matters": "Key interview pattern for achieving O(N) linear time frequency ranking.",
    },
    {
        "id": "product-of-array-except-self",
        "title": "Product of Array Except Self",
        "topic": "Arrays & Hashing",
        "pattern": "Prefix & Suffix Products",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/products-of-array-discluding-self",
        "leetcode_url": "https://leetcode.com/problems/product-of-array-except-self/",
        "why_it_matters": "Teaches prefix/suffix accumulation without using division in O(1) extra space.",
    },
    {
        "id": "longest-consecutive-sequence",
        "title": "Longest Consecutive Sequence",
        "topic": "Arrays & Hashing",
        "pattern": "Intelligent Hash Set Traversal",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/longest-consecutive-sequence",
        "leetcode_url": "https://leetcode.com/problems/longest-consecutive-sequence/",
        "why_it_matters": "Achieves strict O(N) lookup by identifying sequence start boundaries.",
    },

    # --- 2. Two Pointers ---
    {
        "id": "valid-palindrome",
        "title": "Valid Palindrome",
        "topic": "Two Pointers",
        "pattern": "Inward Converging Pointers",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/is-palindrome",
        "leetcode_url": "https://leetcode.com/problems/valid-palindrome/",
        "why_it_matters": "Foundational dual-pointer symmetry validation with character filtering.",
    },
    {
        "id": "two-sum-ii",
        "title": "Two Sum II - Input Array Is Sorted",
        "topic": "Two Pointers",
        "pattern": "Sorted Array Boundary Shrinking",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/two-integer-sum-ii",
        "leetcode_url": "https://leetcode.com/problems/two-sum-ii-input-array-is-sorted/",
        "why_it_matters": "Leverages sorted order for O(1) space dual-pointer search.",
    },
    {
        "id": "three-sum",
        "title": "3Sum",
        "topic": "Two Pointers",
        "pattern": "Sorted Anchor + Two Pointers",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/three-integer-sum",
        "leetcode_url": "https://leetcode.com/problems/3sum/",
        "why_it_matters": "Standard interview benchmark testing duplicate skipping and pointer movement.",
    },
    {
        "id": "container-with-most-water",
        "title": "Container With Most Water",
        "topic": "Two Pointers",
        "pattern": "Greedy Boundary Elimination",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/max-water-container",
        "leetcode_url": "https://leetcode.com/problems/container-with-most-water/",
        "why_it_matters": "Demonstrates why moving the shorter boundary is guaranteed to preserve the optimum.",
    },
    {
        "id": "trapping-rain-water",
        "title": "Trapping Rain Water",
        "topic": "Two Pointers",
        "pattern": "Dual Max Height Tracking",
        "difficulty": "Hard",
        "neetcode_url": "https://neetcode.io/problems/trapping-rain-water",
        "leetcode_url": "https://leetcode.com/problems/trapping-rain-water/",
        "why_it_matters": "Top FAANG interview question testing geometric boundary reasoning in O(1) space.",
    },

    # --- 3. Sliding Window ---
    {
        "id": "best-time-to-buy-and-sell-stock",
        "title": "Best Time to Buy and Sell Stock",
        "topic": "Sliding Window",
        "pattern": "Running Minimum & Peak Spread",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/buy-and-sell-crypto",
        "leetcode_url": "https://leetcode.com/problems/best-time-to-buy-and-sell-stock/",
        "why_it_matters": "One-pass dynamic sliding window calculating maximum historical spread.",
    },
    {
        "id": "longest-substring-without-repeating-characters",
        "title": "Longest Substring Without Repeating Characters",
        "topic": "Sliding Window",
        "pattern": "Dynamic Window with Set",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/longest-substring-without-duplicates",
        "leetcode_url": "https://leetcode.com/problems/longest-substring-without-repeating-characters/",
        "why_it_matters": "Classic variable-size window with hash set tracking unique character sets.",
    },
    {
        "id": "longest-repeating-character-replacement",
        "title": "Longest Repeating Character Replacement",
        "topic": "Sliding Window",
        "pattern": "Window Size vs Max Frequency",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/longest-repeating-substring-with-replacement",
        "leetcode_url": "https://leetcode.com/problems/longest-repeating-character-replacement/",
        "why_it_matters": "Window validity condition: (window_len - max_freq <= k).",
    },
    {
        "id": "permutation-in-string",
        "title": "Permutation in String",
        "topic": "Sliding Window",
        "pattern": "Fixed-Size Window Anagram Matching",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/permutation-string",
        "leetcode_url": "https://leetcode.com/problems/permutation-in-string/",
        "why_it_matters": "Fixed-length window maintaining character match counts in O(26) = O(1) updates.",
    },
    {
        "id": "minimum-window-substring",
        "title": "Minimum Window Substring",
        "topic": "Sliding Window",
        "pattern": "Dynamic Contraction Window",
        "difficulty": "Hard",
        "neetcode_url": "https://neetcode.io/problems/minimum-window-with-characters",
        "leetcode_url": "https://leetcode.com/problems/minimum-window-substring/",
        "why_it_matters": "The ultimate sliding window challenge combining character need vs have counters.",
    },

    # --- 4. Stack ---
    {
        "id": "valid-parentheses",
        "title": "Valid Parentheses",
        "topic": "Stack",
        "pattern": "LIFO Matching",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/validate-parentheses",
        "leetcode_url": "https://leetcode.com/problems/valid-parentheses/",
        "why_it_matters": "Essential syntax parsing pattern for balancing brackets and nested expressions.",
    },
    {
        "id": "min-stack",
        "title": "Min Stack",
        "topic": "Stack",
        "pattern": "Auxiliary Min Stack",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/minimum-stack",
        "leetcode_url": "https://leetcode.com/problems/min-stack/",
        "why_it_matters": "Demonstrates constant O(1) time retrieval of minimum elements in stack structures.",
    },
    {
        "id": "evaluate-reverse-polish-notation",
        "title": "Evaluate Reverse Polish Notation",
        "topic": "Stack",
        "pattern": "Operand Stack Evaluation",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/evaluate-reverse-polish-notation",
        "leetcode_url": "https://leetcode.com/problems/evaluate-reverse-polish-notation/",
        "why_it_matters": "Foundational for compiler AST evaluation and calculator engine implementation.",
    },
    {
        "id": "daily-temperatures",
        "title": "Daily Temperatures",
        "topic": "Stack",
        "pattern": "Monotonic Decreasing Stack",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/daily-temperatures",
        "leetcode_url": "https://leetcode.com/problems/daily-temperatures/",
        "why_it_matters": "Standard monotonic stack pattern for next-greater-element in linear O(N) time.",
    },
    {
        "id": "largest-rectangle-in-histogram",
        "title": "Largest Rectangle in Histogram",
        "topic": "Stack",
        "pattern": "Monotonic Stack Area Sweep",
        "difficulty": "Hard",
        "neetcode_url": "https://neetcode.io/problems/largest-rectangle-in-histogram",
        "leetcode_url": "https://leetcode.com/problems/largest-rectangle-in-histogram/",
        "why_it_matters": "Tests deep mastery of monotonic stack indices and geometric area expansion.",
    },

    # --- 5. Binary Search ---
    {
        "id": "binary-search",
        "title": "Binary Search",
        "topic": "Binary Search",
        "pattern": "Midpoint Convergence",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/binary-search",
        "leetcode_url": "https://leetcode.com/problems/binary-search/",
        "why_it_matters": "Cornerstone O(log N) divide-and-conquer search avoiding integer overflow.",
    },
    {
        "id": "search-a-2d-matrix",
        "title": "Search a 2D Matrix",
        "topic": "Binary Search",
        "pattern": "Virtual 1D Array Mapping",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/search-2d-matrix",
        "leetcode_url": "https://leetcode.com/problems/search-a-2d-matrix/",
        "why_it_matters": "Demonstrates flattening 2D row/column coordinates into a single binary search space.",
    },
    {
        "id": "koko-eating-bananas",
        "title": "Koko Eating Bananas",
        "topic": "Binary Search",
        "pattern": "Binary Search on Answer Space",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/eating-bananas",
        "leetcode_url": "https://leetcode.com/problems/koko-eating-bananas/",
        "why_it_matters": "Crucial pattern: binary searching on a monotonic feasible output range.",
    },
    {
        "id": "find-minimum-in-rotated-sorted-array",
        "title": "Find Minimum in Rotated Sorted Array",
        "topic": "Binary Search",
        "pattern": "Rotated Array Inflection Point",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/find-minimum-in-rotated-sorted-array",
        "leetcode_url": "https://leetcode.com/problems/find-minimum-in-rotated-sorted-array/",
        "why_it_matters": "Tests boundary checks when array monotonicity is broken by rotation.",
    },
    {
        "id": "search-in-rotated-sorted-array",
        "title": "Search in Rotated Sorted Array",
        "topic": "Binary Search",
        "pattern": "Sorted Half Discrimination",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/find-target-in-rotated-sorted-array",
        "leetcode_url": "https://leetcode.com/problems/search-in-rotated-sorted-array/",
        "why_it_matters": "FAANG classic requiring identification of which half is monotonically sorted.",
    },

    # --- 6. Linked List ---
    {
        "id": "reverse-linked-list",
        "title": "Reverse Linked List",
        "topic": "Linked List",
        "pattern": "Iterative Pointer Reversal",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/reverse-a-linked-list",
        "leetcode_url": "https://leetcode.com/problems/reverse-linked-list/",
        "why_it_matters": "Essential pointer manipulation without auxiliary heap allocations.",
    },
    {
        "id": "merge-two-sorted-lists",
        "title": "Merge Two Sorted Lists",
        "topic": "Linked List",
        "pattern": "Sentinel Dummy Node Splicing",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/merge-two-sorted-linked-lists",
        "leetcode_url": "https://leetcode.com/problems/merge-two-sorted-lists/",
        "why_it_matters": "Clean list concatenation using dummy heads; core part of Merge Sort.",
    },
    {
        "id": "reorder-list",
        "title": "Reorder List",
        "topic": "Linked List",
        "pattern": "Fast & Slow Pointers + Interleave",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/reorder-linked-list",
        "leetcode_url": "https://leetcode.com/problems/reorder-list/",
        "why_it_matters": "Combines list midpoint finding, in-place reversal, and alternating merge.",
    },
    {
        "id": "remove-nth-node-from-end",
        "title": "Remove Nth Node From End of List",
        "topic": "Linked List",
        "pattern": "Dual Pointer Fixed Offset",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/remove-node-from-end-of-linked-list",
        "leetcode_url": "https://leetcode.com/problems/remove-nth-node-from-end-of-list/",
        "why_it_matters": "Single-pass node deletion using a two-pointer gap equal to N.",
    },
    {
        "id": "lru-cache",
        "title": "LRU Cache",
        "topic": "Linked List",
        "pattern": "Doubly Linked List + Hash Map",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/lru-cache",
        "leetcode_url": "https://leetcode.com/problems/lru-cache/",
        "why_it_matters": "One of the most frequently asked system/data structure interview questions.",
    },

    # --- 7. Trees ---
    {
        "id": "invert-binary-tree",
        "title": "Invert Binary Tree",
        "topic": "Trees",
        "pattern": "Recursive Tree DFS Swap",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/invert-a-binary-tree",
        "leetcode_url": "https://leetcode.com/problems/invert-binary-tree/",
        "why_it_matters": "Basic recursive tree traversal and child pointer manipulation.",
    },
    {
        "id": "maximum-depth-of-binary-tree",
        "title": "Maximum Depth of Binary Tree",
        "topic": "Trees",
        "pattern": "Post-Order Depth DFS",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/depth-of-binary-tree",
        "leetcode_url": "https://leetcode.com/problems/maximum-depth-of-binary-tree/",
        "why_it_matters": "Divide-and-conquer paradigm: max(left_depth, right_depth) + 1.",
    },
    {
        "id": "subtree-of-another-tree",
        "title": "Subtree of Another Tree",
        "topic": "Trees",
        "pattern": "Subtree DFS Matching",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/subtree-of-a-binary-tree",
        "leetcode_url": "https://leetcode.com/problems/subtree-of-another-tree/",
        "why_it_matters": "Composition of tree structure verification and recursive root scanning.",
    },
    {
        "id": "lowest-common-ancestor-bst",
        "title": "Lowest Common Ancestor of a BST",
        "topic": "Trees",
        "pattern": "BST Property Splitting",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/lowest-common-ancestor-in-binary-search-tree",
        "leetcode_url": "https://leetcode.com/problems/lowest-common-ancestor-of-a-binary-search-tree/",
        "why_it_matters": "Exploits BST order property (left < root < right) for O(H) ancestor search.",
    },
    {
        "id": "binary-tree-level-order-traversal",
        "title": "Binary Tree Level Order Traversal",
        "topic": "Trees",
        "pattern": "Queue BFS by Depth",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/level-order-traversal-of-binary-tree",
        "leetcode_url": "https://leetcode.com/problems/binary-tree-level-order-traversal/",
        "why_it_matters": "Standard BFS queue snapshot loop for hierarchical tree and graph levels.",
    },
    {
        "id": "validate-binary-search-tree",
        "title": "Validate Binary Search Tree",
        "topic": "Trees",
        "pattern": "Boundary Range Invariant",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/valid-binary-search-tree",
        "leetcode_url": "https://leetcode.com/problems/validate-binary-search-tree/",
        "why_it_matters": "Passes strict (min, max) range boundaries downward to validate full BST invariants.",
    },
    {
        "id": "kth-smallest-element-in-bst",
        "title": "Kth Smallest Element in a BST",
        "topic": "Trees",
        "pattern": "In-Order Traversal",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/kth-smallest-integer-in-bst",
        "leetcode_url": "https://leetcode.com/problems/kth-smallest-element-in-a-bst/",
        "why_it_matters": "In-order traversal yields monotonic sorted order in a BST.",
    },

    # --- 8. Tries ---
    {
        "id": "implement-trie",
        "title": "Implement Trie (Prefix Tree)",
        "topic": "Tries",
        "pattern": "26-Way Tree Node Structure",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/design-word-search-data-structure",
        "leetcode_url": "https://leetcode.com/problems/implement-trie-prefix-tree/",
        "why_it_matters": "Essential for autocomplete, IP routing, and string prefix lookups.",
    },
    {
        "id": "word-search-ii",
        "title": "Word Search II",
        "topic": "Tries",
        "pattern": "Trie Pruning + Grid DFS",
        "difficulty": "Hard",
        "neetcode_url": "https://neetcode.io/problems/search-for-word-ii",
        "leetcode_url": "https://leetcode.com/problems/word-search-ii/",
        "why_it_matters": "High-tier interview problem combining prefix trees with board backtracking.",
    },

    # --- 9. Heap / Priority Queue ---
    {
        "id": "kth-largest-element-in-a-stream",
        "title": "Kth Largest Element in a Stream",
        "topic": "Heap / Priority Queue",
        "pattern": "Fixed-Size Min-Heap",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/kth-largest-integer-in-a-stream",
        "leetcode_url": "https://leetcode.com/problems/kth-largest-element-in-a-stream/",
        "why_it_matters": "Maintains top K stream elements in O(log K) insertion time.",
    },
    {
        "id": "k-closest-points-to-origin",
        "title": "K Closest Points to Origin",
        "topic": "Heap / Priority Queue",
        "pattern": "Max-Heap / Euclidean Distance",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/k-closest-points-to-origin",
        "leetcode_url": "https://leetcode.com/problems/k-closest-points-to-origin/",
        "why_it_matters": "Top-K selection using heap vs sorting trade-offs.",
    },
    {
        "id": "task-scheduler",
        "title": "Task Scheduler",
        "topic": "Heap / Priority Queue",
        "pattern": "Max-Heap + Cooldown Queue",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/task-scheduling",
        "leetcode_url": "https://leetcode.com/problems/task-scheduler/",
        "why_it_matters": "CPU process scheduling simulation with frequency greedy heuristics.",
    },
    {
        "id": "find-median-from-data-stream",
        "title": "Find Median from Data Stream",
        "topic": "Heap / Priority Queue",
        "pattern": "Dual Balanced Heaps",
        "difficulty": "Hard",
        "neetcode_url": "https://neetcode.io/problems/find-median-in-a-data-stream",
        "leetcode_url": "https://leetcode.com/problems/find-median-from-data-stream/",
        "why_it_matters": "Balances a max-heap and min-heap to fetch median in O(1) time.",
    },

    # --- 10. Backtracking ---
    {
        "id": "subsets",
        "title": "Subsets",
        "topic": "Backtracking",
        "pattern": "Binary Include/Exclude Tree",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/subsets",
        "leetcode_url": "https://leetcode.com/problems/subsets/",
        "why_it_matters": "Canonical power set generation exploring 2^N state decision branches.",
    },
    {
        "id": "combination-sum",
        "title": "Combination Sum",
        "topic": "Backtracking",
        "pattern": "Target Reduction DFS",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/combination-target-sum",
        "leetcode_url": "https://leetcode.com/problems/combination-sum/",
        "why_it_matters": "Unbounded element reuse with recursive pruning when target < 0.",
    },
    {
        "id": "permutations",
        "title": "Permutations",
        "topic": "Backtracking",
        "pattern": "Visited Element Swap Backtracking",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/permutations",
        "leetcode_url": "https://leetcode.com/problems/permutations/",
        "why_it_matters": "N! combinatorial search maintaining visited position states.",
    },
    {
        "id": "word-search",
        "title": "Word Search",
        "topic": "Backtracking",
        "pattern": "2D Grid DFS with Visited Revert",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/search-for-word",
        "leetcode_url": "https://leetcode.com/problems/word-search/",
        "why_it_matters": "Backtracking on grid cells by marking visited and restoring on backtrack.",
    },

    # --- 11. Graphs ---
    {
        "id": "number-of-islands",
        "title": "Number of Islands",
        "topic": "Graphs",
        "pattern": "Grid Flood Fill BFS/DFS",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/count-number-of-islands",
        "leetcode_url": "https://leetcode.com/problems/number-of-islands/",
        "why_it_matters": "Industry benchmark for connected component counting in a matrix.",
    },
    {
        "id": "clone-graph",
        "title": "Clone Graph",
        "topic": "Graphs",
        "pattern": "Graph DFS + Cloned Node Map",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/clone-graph",
        "leetcode_url": "https://leetcode.com/problems/clone-graph/",
        "why_it_matters": "Deep copy of cyclic graphs using a hash map for visited instances.",
    },
    {
        "id": "pacific-atlantic-water-flow",
        "title": "Pacific Atlantic Water Flow",
        "topic": "Graphs",
        "pattern": "Reverse Multi-Source Reachability",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/pacific-atlantic-water-flow",
        "leetcode_url": "https://leetcode.com/problems/pacific-atlantic-water-flow/",
        "why_it_matters": "Searches backwards from destination boundaries to source cells.",
    },
    {
        "id": "course-schedule",
        "title": "Course Schedule",
        "topic": "Graphs",
        "pattern": "Directed Graph Cycle Detection",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/course-schedule",
        "leetcode_url": "https://leetcode.com/problems/course-schedule/",
        "why_it_matters": "Top interview problem for dependency resolution and DAG cycle checks.",
    },
    {
        "id": "course-schedule-ii",
        "title": "Course Schedule II",
        "topic": "Graphs",
        "pattern": "Topological Sort (Kahn's / Post-Order)",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/course-schedule-ii",
        "leetcode_url": "https://leetcode.com/problems/course-schedule-ii/",
        "why_it_matters": "Constructs valid topological build order or detects circular deadlocks.",
    },
    {
        "id": "rotting-oranges",
        "title": "Rotting Oranges",
        "topic": "Graphs",
        "pattern": "Simultaneous Multi-Source BFS",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/rotting-fruit",
        "leetcode_url": "https://leetcode.com/problems/rotting-oranges/",
        "why_it_matters": "Queue-based BFS tracking shortest time elapsed across multiple propagation origins.",
    },

    # --- 12. 1-D Dynamic Programming ---
    {
        "id": "climbing-stairs",
        "title": "Climbing Stairs",
        "topic": "1-D Dynamic Programming",
        "pattern": "Fibonacci State Recurrence",
        "difficulty": "Easy",
        "neetcode_url": "https://neetcode.io/problems/climbing-stairs",
        "leetcode_url": "https://leetcode.com/problems/climbing-stairs/",
        "why_it_matters": "The entry door to dynamic programming: overlapping subproblems & optimal substructure.",
    },
    {
        "id": "house-robber",
        "title": "House Robber",
        "topic": "1-D Dynamic Programming",
        "pattern": "Non-Adjacent Decision Choice",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/house-robber",
        "leetcode_url": "https://leetcode.com/problems/house-robber/",
        "why_it_matters": "State transition: dp[i] = max(dp[i-1], dp[i-2] + nums[i]) with O(1) space.",
    },
    {
        "id": "longest-palindromic-substring",
        "title": "Longest Palindromic Substring",
        "topic": "1-D Dynamic Programming",
        "pattern": "Center Expansion / Interval DP",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/longest-palindromic-substring",
        "leetcode_url": "https://leetcode.com/problems/longest-palindromic-substring/",
        "why_it_matters": "Explores string center symmetries and 2D memoized palindromic bounds.",
    },
    {
        "id": "coin-change",
        "title": "Coin Change",
        "topic": "1-D Dynamic Programming",
        "pattern": "Unbounded Knapsack Min Optimization",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/coin-change",
        "leetcode_url": "https://leetcode.com/problems/coin-change/",
        "why_it_matters": "Standard minimum step dynamic programming building up from amount 0 to target.",
    },
    {
        "id": "maximum-product-subarray",
        "title": "Maximum Product Subarray",
        "topic": "1-D Dynamic Programming",
        "pattern": "Dual Min & Max State Tracking",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/maximum-product-subarray",
        "leetcode_url": "https://leetcode.com/problems/maximum-product-subarray/",
        "why_it_matters": "Handles negative multiplier signs by tracking both local minimum and maximum.",
    },
    {
        "id": "longest-increasing-subsequence",
        "title": "Longest Increasing Subsequence",
        "topic": "1-D Dynamic Programming",
        "pattern": "Subsequence Patience Sorting",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/longest-increasing-subsequence",
        "leetcode_url": "https://leetcode.com/problems/longest-increasing-subsequence/",
        "why_it_matters": "Teaches O(N^2) dynamic programming vs O(N log N) binary search optimization.",
    },

    # --- 13. 2-D Dynamic Programming ---
    {
        "id": "unique-paths",
        "title": "Unique Paths",
        "topic": "2-D Dynamic Programming",
        "pattern": "2D Grid Combinatorial DP",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/count-paths",
        "leetcode_url": "https://leetcode.com/problems/unique-paths/",
        "why_it_matters": "Transition dp[r][c] = dp[r-1][c] + dp[r][c-1] with row memory compression.",
    },
    {
        "id": "longest-common-subsequence",
        "title": "Longest Common Subsequence",
        "topic": "2-D Dynamic Programming",
        "pattern": "2D String Matrix Alignment",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/longest-common-subsequence",
        "leetcode_url": "https://leetcode.com/problems/longest-common-subsequence/",
        "why_it_matters": "Foundational diff algorithm used in Git and bioinformatics sequence alignment.",
    },
    {
        "id": "best-time-to-buy-and-sell-stock-with-cooldown",
        "title": "Best Time to Buy and Sell Stock with Cooldown",
        "topic": "2-D Dynamic Programming",
        "pattern": "State Machine DP",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/buy-and-sell-crypto-with-cooldown",
        "leetcode_url": "https://leetcode.com/problems/best-time-to-buy-and-sell-stock-with-cooldown/",
        "why_it_matters": "Models explicit state transitions (holding, sold, cooling down).",
    },

    # --- 14. Greedy ---
    {
        "id": "maximum-subarray",
        "title": "Maximum Subarray",
        "topic": "Greedy",
        "pattern": "Kadane's Algorithm",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/maximum-subarray",
        "leetcode_url": "https://leetcode.com/problems/maximum-subarray/",
        "why_it_matters": "Single-pass linear scan resetting negative prefixes in O(N) time.",
    },
    {
        "id": "jump-game",
        "title": "Jump Game",
        "topic": "Greedy",
        "pattern": "Reachability Goalpost Shift",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/jump-game",
        "leetcode_url": "https://leetcode.com/problems/jump-game/",
        "why_it_matters": "Greedy reverse destination tracking in O(N) time and O(1) space.",
    },
    {
        "id": "gas-station",
        "title": "Gas Station",
        "topic": "Greedy",
        "pattern": "Running Deficit Reset",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/gas-station",
        "leetcode_url": "https://leetcode.com/problems/gas-station/",
        "why_it_matters": "Proves why a starting point can be greedily advanced past deficit segments.",
    },

    # --- 15. Intervals ---
    {
        "id": "insert-interval",
        "title": "Insert Interval",
        "topic": "Intervals",
        "pattern": "Sequential Range Merge",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/insert-new-interval",
        "leetcode_url": "https://leetcode.com/problems/insert-interval/",
        "why_it_matters": "Clean handling of pre-overlap, overlapping merge, and post-overlap ranges.",
    },
    {
        "id": "merge-intervals",
        "title": "Merge Intervals",
        "topic": "Intervals",
        "pattern": "Sort by Start + Overlap Merge",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/merge-intervals",
        "leetcode_url": "https://leetcode.com/problems/merge-intervals/",
        "why_it_matters": "Standard calendar and resource scheduling pattern in production systems.",
    },
    {
        "id": "non-overlapping-intervals",
        "title": "Non-overlapping Intervals",
        "topic": "Intervals",
        "pattern": "Greedy Earliest End Time",
        "difficulty": "Medium",
        "neetcode_url": "https://neetcode.io/problems/non-overlapping-intervals",
        "leetcode_url": "https://leetcode.com/problems/non-overlapping-intervals/",
        "why_it_matters": "Interval scheduling theorem: picking earliest finishing intervals minimizes removals.",
    },
]

QUESTION_MAP: Dict[str, Dict[str, Any]] = {q["id"]: q for q in COMPULSORY_DSA_QUESTIONS}
VALID_QUESTION_IDS: Set[str] = set(QUESTION_MAP.keys())

# Bidirectional lookup for LeetCode slugs, NeetCode slugs, and titles
LEETCODE_SLUG_TO_QUESTION_ID: Dict[str, str] = {}
TITLE_TO_QUESTION_ID: Dict[str, str] = {}
CLEAN_TITLE_TO_QUESTION_ID: Dict[str, str] = {}

for q in COMPULSORY_DSA_QUESTIONS:
    qid = q["id"]
    LEETCODE_SLUG_TO_QUESTION_ID[qid.lower()] = qid
    title_clean = q["title"].lower().strip()
    TITLE_TO_QUESTION_ID[title_clean] = qid
    CLEAN_TITLE_TO_QUESTION_ID[re.sub(r"[^a-z0-9]", "", title_clean)] = qid

    lc_url = q.get("leetcode_url", "").strip().rstrip("/")
    if lc_url:
        lc_slug = lc_url.split("/")[-1].lower()
        LEETCODE_SLUG_TO_QUESTION_ID[lc_slug] = qid

    nc_url = q.get("neetcode_url", "").strip().rstrip("/")
    if nc_url:
        nc_slug = nc_url.split("/")[-1].lower()
        LEETCODE_SLUG_TO_QUESTION_ID[nc_slug] = qid


def extract_matching_question_ids(raw_text: str) -> Set[str]:
    """
    Extract matching question IDs from raw text (handles URLs, slugs, titles, comma lists, JSON).
    """
    matched: Set[str] = set()
    if not raw_text:
        return matched

    # 1. URLs from leetcode.com/problems/<slug> or neetcode.io/problems/<slug>
    url_pattern = re.compile(r"(?:leetcode\.com|neetcode\.io)/problems/([a-zA-Z0-9\-]+)", re.IGNORECASE)
    for m in url_pattern.finditer(raw_text):
        slug = m.group(1).lower().strip("/")
        if slug in LEETCODE_SLUG_TO_QUESTION_ID:
            matched.add(LEETCODE_SLUG_TO_QUESTION_ID[slug])

    # 2. Check full title matches in text
    text_lower = raw_text.lower()
    for t_lower, qid in TITLE_TO_QUESTION_ID.items():
        if t_lower in text_lower:
            matched.add(qid)

    # 3. Line-by-line / token parsing
    lines_and_tokens = re.split(r"[\n\r,;\t|]+", raw_text)
    for token in lines_and_tokens:
        clean_token = token.strip().lower()
        if not clean_token:
            continue
        if clean_token in LEETCODE_SLUG_TO_QUESTION_ID:
            matched.add(LEETCODE_SLUG_TO_QUESTION_ID[clean_token])
        alpha_num = re.sub(r"[^a-z0-9]", "", clean_token)
        if alpha_num in CLEAN_TITLE_TO_QUESTION_ID:
            matched.add(CLEAN_TITLE_TO_QUESTION_ID[alpha_num])

    return matched


DIFFICULTY_WEIGHTS = {
    "Easy": 1.0,
    "Medium": 2.0,
    "Hard": 3.0,
}

MAX_POINTS = sum(DIFFICULTY_WEIGHTS.get(q["difficulty"], 1.0) for q in COMPULSORY_DSA_QUESTIONS)


def get_all_topics() -> List[str]:
    topics = []
    for q in COMPULSORY_DSA_QUESTIONS:
        if q["topic"] not in topics:
            topics.append(q["topic"])
    return topics


def calculate_checklist_metrics(solved_ids: Set[str]) -> Dict[str, Any]:
    """Calculates weighted proficiency score, topic completion stats, and gap impact."""
    total_count = len(COMPULSORY_DSA_QUESTIONS)
    valid_solved = [qid for qid in solved_ids if qid in QUESTION_MAP]
    solved_count = len(valid_solved)

    user_points = sum(DIFFICULTY_WEIGHTS.get(QUESTION_MAP[qid]["difficulty"], 1.0) for qid in valid_solved)
    score = round(min(1.0, user_points / MAX_POINTS), 4) if MAX_POINTS > 0 else 0.0

    # Difficulty counts
    easy_total = sum(1 for q in COMPULSORY_DSA_QUESTIONS if q["difficulty"] == "Easy")
    med_total = sum(1 for q in COMPULSORY_DSA_QUESTIONS if q["difficulty"] == "Medium")
    hard_total = sum(1 for q in COMPULSORY_DSA_QUESTIONS if q["difficulty"] == "Hard")

    easy_solved = sum(1 for qid in valid_solved if QUESTION_MAP[qid]["difficulty"] == "Easy")
    med_solved = sum(1 for qid in valid_solved if QUESTION_MAP[qid]["difficulty"] == "Medium")
    hard_solved = sum(1 for qid in valid_solved if QUESTION_MAP[qid]["difficulty"] == "Hard")

    # Topic breakdown
    topic_stats: Dict[str, Dict[str, int]] = {}
    for q in COMPULSORY_DSA_QUESTIONS:
        t = q["topic"]
        if t not in topic_stats:
            topic_stats[t] = {"total": 0, "solved": 0}
        topic_stats[t]["total"] += 1
        if q["id"] in solved_ids:
            topic_stats[t]["solved"] += 1

    return {
        "total_questions": total_count,
        "solved_count": solved_count,
        "solved_percentage": round((solved_count / total_count * 100.0), 1) if total_count > 0 else 0.0,
        "score": score,
        "points": round(user_points, 1),
        "max_points": round(MAX_POINTS, 1),
        "difficulty": {
            "easy": {"solved": easy_solved, "total": easy_total},
            "medium": {"solved": med_solved, "total": med_total},
            "hard": {"solved": hard_solved, "total": hard_total},
        },
        "topics": topic_stats,
    }


def get_user_dsa_progress(user_id: str) -> Dict[str, Any]:
    """Load user's solved question IDs and current checklist progress from Supabase."""
    c = get_supabase_client()
    solved_ids: Set[str] = set()

    if c is not None:
        try:
            r = (
                c.table(ATTEMPTS_TABLE)
                .select("id, question_ids, score, result_summary, completed_at")
                .eq("user_id", user_id)
                .eq("skill_key", DSA_SKILL_KEY)
                .eq("assessment_version", CHECKLIST_VERSION)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if r.data:
                row = r.data[0]
                qids = row.get("question_ids") or []
                if isinstance(qids, list):
                    solved_ids = set(str(x) for x in qids)
                elif isinstance(row.get("result_summary"), dict):
                    solved_ids = set(row["result_summary"].get("solved_ids", []))
        except Exception as e:
            logger.debug("Failed to load DSA checklist attempt for %s: %s", user_id, e)

    metrics = calculate_checklist_metrics(solved_ids)
    return {
        "questions": COMPULSORY_DSA_QUESTIONS,
        "solved_ids": list(solved_ids),
        "metrics": metrics,
    }


async def save_user_dsa_progress(user_id: str, solved_question_ids: List[str]) -> Dict[str, Any]:
    """
    Persist the user's solved question checklist, calculate their DSA proficiency,
    update the assessment_attempts record, and update their DSA skill gap in skill_gaps table.
    """
    c = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()
    clean_solved = set(qid for qid in solved_question_ids if qid in QUESTION_MAP)
    metrics = calculate_checklist_metrics(clean_solved)
    score = metrics["score"]
    total_q = metrics["total_questions"]
    solved_q = metrics["solved_count"]

    # 1. Look up DSA skill_id
    dsa_skill_id: Optional[str] = None
    if c is not None:
        try:
            r_skill = c.table("skills").select("id").eq("canonical_name", DSA_CANONICAL_NAME).limit(1).execute()
            if r_skill.data:
                dsa_skill_id = r_skill.data[0]["id"]
        except Exception:
            pass

    # 2. Persist or update the assessment attempt for DSA checklist
    if c is not None:
        try:
            # Check existing attempt
            existing = (
                c.table(ATTEMPTS_TABLE)
                .select("id")
                .eq("user_id", user_id)
                .eq("skill_key", DSA_SKILL_KEY)
                .eq("assessment_version", CHECKLIST_VERSION)
                .limit(1)
                .execute()
            )

            attempt_payload = {
                "user_id": user_id,
                "skill_id": dsa_skill_id,
                "skill_key": DSA_SKILL_KEY,
                "skill_name": DSA_DISPLAY_NAME,
                "assessment_version": CHECKLIST_VERSION,
                "status": "completed",
                "validity": "valid",
                "score": score,
                "correct_count": solved_q,
                "question_count": total_q,
                "question_ids": list(clean_solved),
                "completed_at": now,
                "updated_at": now,
                "result_summary": {
                    "type": "dsa_pattern_checklist",
                    "solved_ids": list(clean_solved),
                    "solved_count": solved_q,
                    "total_questions": total_q,
                    "score": score,
                    "metrics": metrics,
                },
            }

            if existing.data:
                attempt_id = existing.data[0]["id"]
                c.table(ATTEMPTS_TABLE).update(attempt_payload).eq("id", attempt_id).execute()
            else:
                c.table(ATTEMPTS_TABLE).insert(attempt_payload).execute()
        except Exception as e:
            logger.warning("Failed to record DSA checklist attempt in DB: %s", e)

    # 3. Directly update DSA row in skill_gaps table
    gap_updated = False
    new_gap_value: Optional[float] = None
    new_prof_value: Optional[float] = None

    if c is not None and dsa_skill_id:
        try:
            gaps_query = (
                c.table(GAPS_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("skill_id", dsa_skill_id)
                .execute()
            )
            if gaps_query.data:
                for gap_row in gaps_query.data:
                    gap_id = gap_row["id"]
                    req = float(gap_row.get("required_level", 0.8) or 0.8)
                    old_prof = float(gap_row.get("current_proficiency", 0.0) or 0.0)
                    # New proficiency is scaled by checklist completion
                    # Solving 50%+ of questions covers industry requirements
                    effective_prof = min(1.0, round(score * 1.15, 4))
                    updated_prof = max(old_prof, effective_prof)
                    updated_gap = max(0.0, round(req - updated_prof, 4))
                    updated_conf = max(float(gap_row.get("confidence", 0.0) or 0.0), 0.85)

                    is_covered = updated_gap <= 0.05
                    update_data = {
                        "current_proficiency": updated_prof,
                        "gap": updated_gap,
                        "confidence": updated_conf,
                        "priority_score": 0.0 if is_covered else round(updated_gap * float(gap_row.get("importance", 0.8) or 0.8) * 10, 2),
                        "priority_category": "covered" if is_covered else gap_row.get("priority_category", "high"),
                        "actionable_advice": (
                            "DSA capability verified through NeetCode pattern checklist."
                            if is_covered
                            else "Continue completing compulsory DSA question patterns to eliminate remaining gap."
                        ),
                    }
                    c.table(GAPS_TABLE).update(update_data).eq("id", gap_id).execute()
                    gap_updated = True
                    new_gap_value = updated_gap
                    new_prof_value = updated_prof
        except Exception as e:
            logger.warning("Failed to update skill_gaps for DSA: %s", e)

    # 4. Best-effort recalculate downstream analysis
    try:
        from .assessment.service import _recalculate_analysis
        await _recalculate_analysis(user_id, DSA_CANONICAL_NAME)
    except Exception as e:
        logger.debug("Recalculate analysis skipped/failed: %s", e)

    return {
        "status": "success",
        "solved_ids": list(clean_solved),
        "metrics": metrics,
        "dsa_gap_updated": gap_updated,
        "new_proficiency": new_prof_value,
        "new_gap": new_gap_value,
        "message": (
            f"Successfully updated DSA checklist: {solved_q}/{total_q} questions solved ({metrics['solved_percentage']}%). "
            + ("DSA gap covered!" if new_gap_value is not None and new_gap_value <= 0.05 else "DSA gap reduced.")
        ),
    }


def get_user_linked_leetcode_data(user_id: str) -> Dict[str, Any]:
    """
    Look up user's linked LeetCode profile from the 'evidence' table.
    Returns {'username': Optional[str], 'known_solved_ids': Set[str]}.
    """
    c = get_supabase_client()
    result: Dict[str, Any] = {"username": None, "known_solved_ids": set()}
    if c is None:
        return result

    try:
        r = c.table("evidence").select("*").eq("user_id", user_id).eq("evidence_type", "leetcode").execute()
        if r.data:
            for row in r.data:
                meta = row.get("metadata") or {}
                if isinstance(meta, dict):
                    inspection = meta.get("inspection") or {}
                    if inspection.get("username"):
                        result["username"] = inspection["username"]

                    # Extract any problem objects if present in metadata
                    problems = inspection.get("problems") or meta.get("problems") or []
                    if isinstance(problems, list):
                        for p in problems:
                            if isinstance(p, dict):
                                for key in ("id", "slug", "titleSlug", "title"):
                                    val = str(p.get(key) or "").strip().lower()
                                    if val in LEETCODE_SLUG_TO_QUESTION_ID:
                                        result["known_solved_ids"].add(LEETCODE_SLUG_TO_QUESTION_ID[val])
                                    if val in TITLE_TO_QUESTION_ID:
                                        result["known_solved_ids"].add(TITLE_TO_QUESTION_ID[val])

                # Fallback to source_url extraction
                url = row.get("source_url") or ""
                if url and not result["username"]:
                    from .evidence.url_utils import validate_platform_url, extract_username_from_path, LEETCODE_HOSTS
                    valid, path, _ = validate_platform_url(url, LEETCODE_HOSTS)
                    if valid:
                        uname = extract_username_from_path(path or "", "leetcode")
                        if uname:
                            result["username"] = uname
    except Exception as e:
        logger.warning("Error fetching linked LeetCode evidence for user %s: %s", user_id, e)

    return result


async def fetch_leetcode_recent_ac(username: str) -> List[Dict[str, Any]]:
    """Query LeetCode's public GraphQL endpoint for recent accepted submissions."""
    query = """
    query getUserRecentAc($username: String!, $limit: Int!) {
      recentAcSubmissionList(username: $username, limit: $limit) {
        id
        title
        titleSlug
        timestamp
      }
    }
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Referer": "https://leetcode.com",
        "Origin": "https://leetcode.com",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                "https://leetcode.com/graphql",
                json={"query": query, "variables": {"username": username, "limit": 50}},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data", {}).get("recentAcSubmissionList") or []
            else:
                logger.warning("LeetCode GraphQL returned %s for %s", resp.status_code, username)
    except Exception as e:
        logger.warning("Network error fetching LeetCode recent AC for %s: %s", username, e)
    return []


async def sync_leetcode_solved(user_id: str, username: Optional[str] = None) -> Dict[str, Any]:
    """
    Sync user's solved LeetCode questions with the 71 compulsory pattern questions.
    Checks:
    1. Direct LeetCode GraphQL public recent accepted submissions (up to 50 recent).
    2. Any verified problem entries in the user's connected evidence.
    Automatically marks matching questions as solved, persists progress, and updates DSA skill gap.
    """
    target_username = (username or "").strip()
    evidence_info = get_user_linked_leetcode_data(user_id)
    if not target_username:
        target_username = evidence_info.get("username") or ""

    if not target_username:
        current_progress = get_user_dsa_progress(user_id)
        return {
            "success": False,
            "username": "",
            "synced_count": 0,
            "matched_questions": [],
            "total_recent_fetched": 0,
            "metrics": current_progress["metrics"],
            "message": "No LeetCode profile linked. Please enter your LeetCode username to sync.",
        }

    # 1. Fetch recent accepted submissions
    recent_subs = await fetch_leetcode_recent_ac(target_username)
    matched_from_api: Set[str] = set()

    for sub in recent_subs:
        slug = str(sub.get("titleSlug") or "").lower().strip()
        title = str(sub.get("title") or "").lower().strip()
        if slug in LEETCODE_SLUG_TO_QUESTION_ID:
            matched_from_api.add(LEETCODE_SLUG_TO_QUESTION_ID[slug])
        elif title in TITLE_TO_QUESTION_ID:
            matched_from_api.add(TITLE_TO_QUESTION_ID[title])

    # 2. Merge with any known solved problems from evidence
    all_matched = matched_from_api | evidence_info.get("known_solved_ids", set())

    # 3. Load user's current progress
    current_progress = get_user_dsa_progress(user_id)
    current_solved: Set[str] = set(current_progress.get("solved_ids", []))

    newly_matched = all_matched - current_solved
    combined_solved = current_solved | all_matched

    if newly_matched:
        # Save updated progress and update skill gap
        save_result = await save_user_dsa_progress(user_id, list(combined_solved))
        matched_names = [QUESTION_MAP[qid]["title"] for qid in newly_matched if qid in QUESTION_MAP]
        return {
            "success": True,
            "username": target_username,
            "synced_count": len(newly_matched),
            "matched_questions": matched_names,
            "total_recent_fetched": len(recent_subs),
            "metrics": save_result["metrics"],
            "message": (
                f"Successfully synced {len(newly_matched)} question{'s' if len(newly_matched) != 1 else ''} "
                f"from LeetCode (@{target_username})! Your DSA progress has been updated."
            ),
        }
    else:
        matched_names = [QUESTION_MAP[qid]["title"] for qid in all_matched if qid in QUESTION_MAP]
        msg = (
            f"Checked {len(recent_subs)} recent submission{'s' if len(recent_subs) != 1 else ''} "
            f"from LeetCode (@{target_username}). "
        )
        if all_matched:
            msg += f"All {len(all_matched)} matching pattern question(s) were already checked off!"
        else:
            msg += "None of your recent submissions matched the 71 compulsory patterns. You can also use Quick Import to paste older questions!"

        return {
            "success": True,
            "username": target_username,
            "synced_count": 0,
            "matched_questions": matched_names,
            "total_recent_fetched": len(recent_subs),
            "metrics": current_progress["metrics"],
            "message": msg,
        }


async def import_solved_from_text(user_id: str, raw_text: str) -> Dict[str, Any]:
    """
    Parse problem names, slugs, or URLs from text and mark them as solved in the DSA checklist.
    """
    matched_ids = extract_matching_question_ids(raw_text)
    current_progress = get_user_dsa_progress(user_id)
    if not matched_ids:
        return {
            "success": False,
            "imported_count": 0,
            "matched_questions": [],
            "metrics": current_progress["metrics"],
            "message": "No matching questions from the 71 compulsory patterns found in the provided text. Try pasting LeetCode URLs or problem titles.",
        }

    current_solved: Set[str] = set(current_progress.get("solved_ids", []))
    newly_imported = matched_ids - current_solved
    combined_solved = current_solved | matched_ids

    save_result = await save_user_dsa_progress(user_id, list(combined_solved))
    matched_names = [QUESTION_MAP[qid]["title"] for qid in matched_ids if qid in QUESTION_MAP]

    return {
        "success": True,
        "imported_count": len(newly_imported),
        "matched_questions": matched_names,
        "metrics": save_result["metrics"],
        "message": (
            f"Matched {len(matched_ids)} compulsory question{'s' if len(matched_ids) != 1 else ''} "
            f"({len(newly_imported)} newly added)! Your DSA progress has been updated."
        ),
    }
