"""
Tests for DSA Pattern Checklist Service and Industry Question Bank.
"""

from app.services.dsa_checklist_service import (
    COMPULSORY_DSA_QUESTIONS,
    get_all_topics,
    calculate_checklist_metrics,
    QUESTION_MAP,
)


def test_question_bank_completeness():
    assert len(COMPULSORY_DSA_QUESTIONS) >= 70
    topics = get_all_topics()
    assert len(topics) >= 14
    assert "Arrays & Hashing" in topics
    assert "Two Pointers" in topics
    assert "Sliding Window" in topics
    assert "Binary Search" in topics
    assert "Trees" in topics
    assert "Graphs" in topics
    assert "1-D Dynamic Programming" in topics


def test_every_question_has_valid_fields_and_links():
    for q in COMPULSORY_DSA_QUESTIONS:
        assert q["id"], "Question must have an id"
        assert q["title"], "Question must have a title"
        assert q["topic"], f"Question {q['id']} must have a topic"
        assert q["pattern"], f"Question {q['id']} must have a pattern"
        assert q["difficulty"] in ("Easy", "Medium", "Hard"), f"Invalid difficulty in {q['id']}"
        assert q["neetcode_url"].startswith("https://neetcode.io/problems/"), f"Invalid NeetCode url in {q['id']}"
        assert q["leetcode_url"].startswith("https://leetcode.com/problems/"), f"Invalid LeetCode url in {q['id']}"
        assert len(q["why_it_matters"]) > 10, f"Missing why_it_matters in {q['id']}"


def test_checklist_metrics_calculation():
    # 0 solved
    m0 = calculate_checklist_metrics(set())
    assert m0["solved_count"] == 0
    assert m0["solved_percentage"] == 0.0
    assert m0["score"] == 0.0

    # Solved some questions
    sample_solved = {"two-sum", "valid-anagram", "three-sum", "trapping-rain-water"}
    m1 = calculate_checklist_metrics(sample_solved)
    assert m1["solved_count"] == 4
    assert m1["score"] > 0.0
    assert m1["score"] <= 1.0
    assert m1["difficulty"]["easy"]["solved"] == 2  # two-sum, valid-anagram
    assert m1["difficulty"]["medium"]["solved"] == 1  # three-sum
    assert m1["difficulty"]["hard"]["solved"] == 1  # trapping-rain-water
    assert m1["topics"]["Arrays & Hashing"]["solved"] == 2
    assert m1["topics"]["Two Pointers"]["solved"] == 2


def test_all_solved_yields_full_score():
    all_ids = set(QUESTION_MAP.keys())
    m_all = calculate_checklist_metrics(all_ids)
    assert m_all["solved_count"] == len(COMPULSORY_DSA_QUESTIONS)
    assert m_all["solved_percentage"] == 100.0
    assert m_all["score"] == 1.0


def test_slug_and_title_mappings_coverage():
    from app.services.dsa_checklist_service import (
        LEETCODE_SLUG_TO_QUESTION_ID,
        TITLE_TO_QUESTION_ID,
    )
    # Check that canonical LeetCode slugs exist
    assert "two-sum" in LEETCODE_SLUG_TO_QUESTION_ID
    assert "3sum" in LEETCODE_SLUG_TO_QUESTION_ID
    assert "trapping-rain-water" in LEETCODE_SLUG_TO_QUESTION_ID
    assert "two-sum-ii-input-array-is-sorted" in LEETCODE_SLUG_TO_QUESTION_ID
    assert "course-schedule" in LEETCODE_SLUG_TO_QUESTION_ID

    # Check that titles map cleanly
    assert TITLE_TO_QUESTION_ID["two sum"] == "two-sum"
    assert TITLE_TO_QUESTION_ID["3sum"] == "three-sum"
    assert TITLE_TO_QUESTION_ID["trapping rain water"] == "trapping-rain-water"


def test_extract_matching_question_ids_from_urls_and_text():
    from app.services.dsa_checklist_service import extract_matching_question_ids

    # 1. LeetCode URLs
    text_urls = """
    I solved https://leetcode.com/problems/two-sum/
    and also https://leetcode.com/problems/3sum/ and https://leetcode.com/problems/trapping-rain-water/
    """
    matched = extract_matching_question_ids(text_urls)
    assert "two-sum" in matched
    assert "three-sum" in matched
    assert "trapping-rain-water" in matched

    # 2. NeetCode URLs
    text_nc = "Checked https://neetcode.io/problems/duplicate-integer and https://neetcode.io/problems/max-water-container"
    matched_nc = extract_matching_question_ids(text_nc)
    assert "contains-duplicate" in matched_nc
    assert "container-with-most-water" in matched_nc

    # 3. Comma-separated problem names or slugs
    text_mixed = "valid-anagram, Invert Binary Tree, course-schedule, Coin Change"
    matched_mixed = extract_matching_question_ids(text_mixed)
    assert "valid-anagram" in matched_mixed
    assert "invert-binary-tree" in matched_mixed
    assert "course-schedule" in matched_mixed
    assert "coin-change" in matched_mixed
