from app.services.resume_builder import (
    MAX_RESUME_SKILL_GROUPS,
    MAX_SKILLS_PER_GROUP,
    _likely_same_project,
    _parse_doc_projects,
    _sanitize_doc_text,
    _split_experience_achievements,
    classify_bullet,
    deterministic_content,
    filter_project_bullets,
    humanize_repo_name,
    latex_escape,
    select_resume_skills,
    to_latex,
    verify_content,
)


def test_latex_is_standalone_and_escapes_user_content():
    tex = to_latex({"content": {"header": {"name": "A&B"}, "summary": "Uses 100% of data", "education": [{"school": "RIT", "degree": "B.E."}], "skills": ["Python"]}})
    assert r"\documentclass" in tex
    assert r"\begin{document}" in tex and r"\end{document}" in tex
    assert r"A\&B" in tex
    assert "100\\%" in tex
    assert "INAURA" not in tex


def test_resume_verifier_flags_unsupported_metrics_and_technology():
    result = verify_content({"summary": "Built a Python service serving 10,000 users"}, [], {"skills": [], "projects": []})
    assert result["status"] == "needs_verification"
    assert any("Metric" in item["reason"] for item in result["findings"])
    assert any("Technology" in item["reason"] for item in result["findings"])


def test_latex_escape_handles_tilde_and_caret():
    assert latex_escape("a~b^c") == r"a\textasciitilde{}b\textasciicircum{}c"


# Synthetic fixture reproducing the wrapped-PDF shape (no personal data).
WRAPPED_PROJECTS_SECTION = (
    "Sample Quest — Java Console App\n"
    "● Built a console-based quest game in Java with win detection, blocking,\n"
    "and fork detection\n"
    "● Designed move-priority logic winning every defensive line\n"
    "MirrorVibes — Live Project\n"
    "● Built and deployed a mood-based recommender using Node.js and Express\n"
    "● Implemented a 10-mood mapping engine returning curated data\n"
)


def test_wrapped_bullet_lines_do_not_become_titles():
    projects = _parse_doc_projects(WRAPPED_PROJECTS_SECTION)
    titles = [p["title"] for p in projects]
    assert titles == ["Sample Quest — Java Console App", "MirrorVibes — Live Project"]
    assert not any("fork detection" in t for t in titles)
    first_bullets = projects[0]["bullets"]
    assert any("blocking, and fork detection" in b for b in first_bullets)


def test_short_continuation_fragments_stay_in_bullets():
    projects = _parse_doc_projects(WRAPPED_PROJECTS_SECTION)
    titles = [p["title"] for p in projects]
    assert "Designed move-priority logic winning every defensive line" not in titles
    assert "Implemented a 10-mood mapping engine returning curated data" not in titles


def test_expected_titles_survive_parsing():
    projects = _parse_doc_projects(
        "MirrorVibes\n"
        "● Built a recommender with Node.js\n"
        "AI-Based Tic-Tac-Toe\n"
        "● Built a Java game\n"
        "Tic-Tac-Toe\n"
        "● Played on the console\n"
    )
    titles = [p["title"] for p in projects]
    assert titles == ["MirrorVibes", "AI-Based Tic-Tac-Toe", "Tic-Tac-Toe"]


def test_punctuation_ending_lines_are_not_titles():
    projects = _parse_doc_projects(
        "Sample App\n"
        "Shipped the first release.\n"
        "● Built the core module\n"
    )
    titles = [p["title"] for p in projects]
    assert "Shipped the first release." not in titles


def test_replacement_character_cleanup():
    assert "�" not in _sanitize_doc_text("AI-Based Tic-Tac-Toe � Java App")
    projects = _parse_doc_projects("Tic-Tac-Toe � Console Game\n● Built it\n")
    assert all("�" not in p["title"] for p in projects)


def test_github_slug_humanization():
    assert humanize_repo_name("TIC-TAC-TOE") == "Tic Tac Toe"
    assert humanize_repo_name("Rock-Paper-Scissors-with-difficulty-level") == (
        "Rock Paper Scissors with Difficulty Level")
    assert humanize_repo_name("PatternGenerator") == "Pattern Generator"
    assert humanize_repo_name("MirrorVibes-AI") == "Mirror Vibes AI"


def test_document_github_duplicate_detection():
    assert _likely_same_project("TIC-TAC-TOE", "AI-Based Tic-Tac-Toe")
    assert _likely_same_project("MirrorVibes", "MirrorVibes — Live Project")
    assert not _likely_same_project("WeatherApp", "MirrorVibes")
    assert not _likely_same_project("MirrorVibes-AI", "SoulFuel Kitchen")


def test_merged_project_keeps_github_url_and_provenance():
    snapshot = {
        "profile": {"full_name": "Test User"},
        "projects": [],
        "doc_projects": [{
            "title": "AI-Based Tic-Tac-Toe — Java Console App",
            "bullets": ["Built a Java game with win detection."],
            "technologies": ["Java"], "matched_skills": ["Java"], "score": 5,
            "source_evidence_id": "doc-1"}],
        "github_repos": [{
            "repo": {"name": "TIC-TAC-TOE", "full_name": "tester/TIC-TAC-TOE",
                     "description": "A tic-tac-toe game.",
                     "html_url": "https://github.com/tester/TIC-TAC-TOE",
                     "languages": {"Java": 100}},
            "score": 3, "matched_skills": ["Java"], "technologies": ["Java"]}],
        "github_owner": "tester", "github_evidence_id": "gh-1",
        "github_url": "https://github.com/tester",
        "certifications": [], "evidence": [], "skills": [], "assessed_skills": [],
        "github_skills": [], "leetcode": {}, "experience": [], "achievements": [],
        "doc_evidence_id": "doc-1", "requirements": [], "target_role": "Software Engineer",
        "diagnostics": {},
    }
    content, claims = deterministic_content(snapshot)
    assert len(content["projects"]) == 1
    merged = content["projects"][0]
    assert merged["name"] == "AI-Based Tic-Tac-Toe — Java Console App"
    assert "https://github.com/tester/TIC-TAC-TOE" in merged["links"]
    assert merged["repository"] == "tester/TIC-TAC-TOE"
    anchor_types = {a["type"] for c in claims for a in c["evidence"]}
    assert {"resume", "github"} <= anchor_types


def test_experience_achievements_split():
    experience, achievements = _split_experience_achievements(
        "● Ranked 11th at a hackathon with teammates\n"
        "● GitHub Student Pack member\n"
    )
    assert achievements and not any("hackathon" in e.lower() for e in experience)
    assert any("member" in e.lower() for e in experience)


def test_all_caps_subsection_headings_skipped():
    experience, achievements = _split_experience_achievements(
        "OPEN SOURCE\n"
        "● GitHub Student Pack member\n"
    )
    assert not any("OPEN SOURCE" in e for e in experience + achievements)
    assert any("member" in e.lower() for e in experience)


def test_no_replacement_chars_in_parsed_content():
    projects = _parse_doc_projects("Sample Quest � Console App\n● Built a game\n")
    blob = " ".join([p["title"] for p in projects] + [b for p in projects for b in p["bullets"]])
    assert "�" not in blob


def test_real_profile_compact_groups_and_untouched_profile():
    """Live-data regression: compact groups, key skills kept, profile intact."""
    pytest = __import__("pytest")
    from app.core.supabase import get_supabase_client
    from app.services import resume_builder as rb_module
    client = get_supabase_client()
    if client is None:
        pytest.skip("Supabase not configured")
    try:
        profiles = (client.table("profiles").select("user_id").execute().data or [])
    except Exception:
        pytest.skip("profiles table unavailable")
    user_id = None
    for row in profiles:
        try:
            has = client.table("skill_assessments").select("id").eq(
                "user_id", row["user_id"]).limit(1).execute().data
        except Exception:
            continue
        if has:
            user_id = row["user_id"]
            break
    if not user_id:
        pytest.skip("no assessed profile available")
    before_profile = client.table("profiles").select("*").eq("user_id", user_id).execute().data
    before_count = len(client.table("skill_assessments").select("id").eq(
        "user_id", user_id).execute().data or [])
    snapshot = rb_module.build_evidence_snapshot(user_id, "Software Engineer")
    assert len(snapshot["skills"]) > 10  # genuinely rich profile
    content, _ = rb_module.deterministic_content(snapshot)
    groups = content["skill_groups"]
    assert 1 <= len(groups) <= MAX_RESUME_SKILL_GROUPS
    assert all(len(v) <= MAX_SKILLS_PER_GROUP for v in groups.values())
    assert len(groups) < len({s.get("category") for s in snapshot["skills"] if s.get("category")})
    flat = [n for g in groups.values() for n in g]
    assert len(flat) == len({n.lower() for n in flat})
    assert not any(k.lower() in ("database", "devops") and k != "Databases" and "DevOps" not in k
                   for k in groups)
    for key in ("React", "Python"):
        assert key in flat
    after_profile = client.table("profiles").select("*").eq("user_id", user_id).execute().data
    after_count = len(client.table("skill_assessments").select("id").eq(
        "user_id", user_id).execute().data or [])
    assert after_profile == before_profile
    assert after_count == before_count


# ---- Resume skill selector (presentation curation, profile untouched) ----

def _sel_skill(name, category="Programming", proficiency=0.5, confidence=0.5,
               evidence_count=1, source="skill_assessment"):
    return {"name": name, "category": category, "proficiency": proficiency,
            "confidence": confidence, "evidence_count": evidence_count, "source": source}

def _sel_reqs(*names, importance=0.9):
    return [{"skill": n, "importance": importance, "interview_relevance": 0.8, "demand": 0.7}
            for n in names]


def test_selector_returns_compact_groups_within_budget():
    skills = [
        _sel_skill("Python"), _sel_skill("Java"), _sel_skill("C++"), _sel_skill("JavaScript"),
        _sel_skill("TypeScript"), _sel_skill("Go"), _sel_skill("Rust"),
        _sel_skill("React", "Frontend"), _sel_skill("Next.js", "Frontend"),
        _sel_skill("Node.js", "Backend"), _sel_skill("REST APIs", "Backend"),
        _sel_skill("PostgreSQL", "Databases"), _sel_skill("MongoDB", "Databases"), _sel_skill("SQL", "Databases"),
        _sel_skill("Git", "Tools"), _sel_skill("Docker", "DevOps/Cloud"),
        _sel_skill("Pandas", "AI/ML"), _sel_skill("Machine Learning", "AI/ML"),
        _sel_skill("Data Structures & Algorithms", "Computer Science"),
        _sel_skill("Testing", "Quality"), _sel_skill("DBMS", "Computer Science"),
        _sel_skill("System Design", "Computer Science"),
    ]
    selected, available, stats = select_resume_skills(
        skills, _sel_reqs("Python", "React", "Node.js", "PostgreSQL", "Git", "Pandas",
                           "Data Structures & Algorithms"))
    assert len(selected) <= MAX_RESUME_SKILL_GROUPS
    assert all(len(v) <= MAX_SKILLS_PER_GROUP for v in selected.values())
    assert stats["skills_selected"] + stats["skills_available"] == len(skills)


def test_role_relevance_beats_alphabetical_order():
    skills = [_sel_skill("ZebraLang", proficiency=0.9, confidence=0.9),
              _sel_skill("Python", proficiency=0.5, confidence=0.5)]
    selected, _, _ = select_resume_skills(skills, _sel_reqs("Python"))
    assert selected["Languages"][0] == "Python"


def test_selector_never_mutates_or_deletes_canonical_profile():
    skills = [_sel_skill("Python"), _sel_skill("Cobol", "Programming", proficiency=0.1)]
    before = [dict(s) for s in skills]
    selected, available, _ = select_resume_skills(skills, _sel_reqs("Python"), max_groups=1)
    assert skills == before
    all_names = [n for g in list(selected.values()) + list(available.values()) for n in g]
    assert "Cobol" in all_names  # still present, only unselected


def test_duplicate_categories_and_names_consolidated():
    skills = [_sel_skill("SQL", "Database"), _sel_skill("PostgreSQL", "Databases"),
              _sel_skill("MongoDB", "Databases"), _sel_skill("SQL", "Databases")]
    selected, _, _ = select_resume_skills(skills, [])
    assert "Database" not in selected
    assert sorted(selected["Databases"]) == ["MongoDB", "PostgreSQL", "SQL"]


def test_no_self_referential_group_and_no_invented_skills():
    skills = [_sel_skill("Machine Learning", "AI/ML")]
    selected, _, _ = select_resume_skills(skills, [])
    assert "Machine Learning" not in selected
    assert selected["Data & ML"] == ["Machine Learning"]
    flat = [n for g in selected.values() for n in g]
    assert set(flat) <= {"Machine Learning"}


def test_soft_skills_and_leftovers_stay_available():
    skills = [_sel_skill("Communication", "Soft Skills"), _sel_skill("Python")]
    selected, available, _ = select_resume_skills(skills, _sel_reqs("Python"))
    assert "Communication" not in [n for g in selected.values() for n in g]
    assert "Communication" in [n for g in available.values() for n in g]


def test_selected_groups_land_in_resume_data_and_latex():
    snapshot = {
        "profile": {"full_name": "Test User", "college": "C", "degree": "B.Tech",
                    "branch": "CS", "current_year": "2nd Year", "graduation_year": 2029},
        "projects": [], "doc_projects": [], "github_repos": [], "github_owner": "",
        "github_evidence_id": None, "github_url": "",
        "certifications": [], "evidence": [],
        "skills": [_sel_skill("Python"), _sel_skill("SQL", "Database"),
                   _sel_skill("Communication", "Soft Skills")],
        "assessed_skills": [], "github_skills": [], "leetcode": {}, "experience": [],
        "achievements": [], "doc_evidence_id": None,
        "requirements": _sel_reqs("Python"), "target_role": "Software Engineer",
        "diagnostics": {},
    }
    content, _ = deterministic_content(snapshot)
    assert set(content["skill_groups"]) == {"Languages", "Databases"}
    assert "Communication" in [n for g in content["available_skills"].values() for n in g]
    tex = to_latex({"content": content})
    assert "Languages" in tex and "Python" in tex
    assert "Communication" not in tex


# ---- Deterministic bullet-quality filter (no LLM) ----

GOOD_IMPL_BULLET = (
    "Built a console-based Tic-Tac-Toe game in Java with a rule-based AI "
    "opponent implementing win detection, blocking, and fork detection."
)
GOOD_PRIORITY_BULLET = "Designed move-priority logic (without minimax) ensuring the AI never loses."
MARKETING_BULLET = (
    "Step into the ultimate battle of wits! This isn't just another task game — "
    "it's a super-smart challenge designed to outsmart you at every move. Can you beat it?"
)


def test_concrete_implementation_bullet_survives():
    assert classify_bullet(GOOD_IMPL_BULLET, ["Java"]) == (True, "keep")


def test_move_priority_bullet_survives():
    assert classify_bullet(GOOD_PRIORITY_BULLET, ["Java"]) == (True, "keep")


def test_marketing_paragraph_rejected():
    keep, reason = classify_bullet(MARKETING_BULLET, ["Java"])
    assert keep is False and reason == "marketing_prose"


def test_redundant_tech_statement_rejected_when_tech_listed():
    keep, reason = classify_bullet("Implemented using Java.", ["Java"])
    assert keep is False and reason == "redundant_tech_statement"


def test_tech_statement_kept_when_tech_not_listed():
    assert classify_bullet("Implemented using Docker.", ["Java"]) == (True, "keep")


def test_generic_and_duplicate_bullets_rejected():
    assert classify_bullet("Built a software project.", ["Java"])[0] is False
    kept, dropped = filter_project_bullets(
        [GOOD_IMPL_BULLET, GOOD_IMPL_BULLET, "Implemented using Java."],
        ["Java"],
    )
    assert kept == [GOOD_IMPL_BULLET]
    assert {d["reason"] for d in dropped} == {"duplicate_claim", "redundant_tech_statement"}


def test_bullet_filter_preserves_other_projects_and_provenance():
    snapshot = {
        "profile": {"full_name": "Test User", "college": "Test College", "degree": "B.Tech",
                    "branch": "Computer Science", "current_year": "2nd Year", "graduation_year": 2029},
        "projects": [],
        "doc_projects": [{
            "title": "AI-Based Tic-Tac-Toe — Java Console App",
            "bullets": [GOOD_IMPL_BULLET, GOOD_PRIORITY_BULLET, MARKETING_BULLET,
                        "Implemented using Java."],
            "technologies": ["Java"], "matched_skills": ["Java"], "score": 9,
            "source_evidence_id": "doc-1"},
            {"title": "MirrorVibes — Live Project",
             "bullets": ["Built and deployed a mood-based recommender using Node.js and Express."],
             "technologies": ["Node.js", "Express"], "matched_skills": ["Node.js"],
             "score": 8, "source_evidence_id": "doc-1"}],
        "github_repos": [], "github_owner": "", "github_evidence_id": None, "github_url": "",
        "certifications": [], "evidence": [], "skills": [], "assessed_skills": [],
        "github_skills": [], "leetcode": {}, "experience": [], "achievements": [],
        "doc_evidence_id": "doc-1", "requirements": [], "target_role": "Software Engineer",
        "diagnostics": {},
    }
    content, claims = deterministic_content(snapshot)
    by_name = {p["name"]: p for p in content["projects"]}
    # No title regression.
    assert set(by_name) == {"AI-Based Tic-Tac-Toe — Java Console App", "MirrorVibes — Live Project"}
    # Tic-Tac-Toe keeps exactly the two concrete bullets.
    assert by_name["AI-Based Tic-Tac-Toe — Java Console App"]["bullets"] == [
        GOOD_IMPL_BULLET, GOOD_PRIORITY_BULLET]
    # Other projects untouched.
    assert by_name["MirrorVibes — Live Project"]["bullets"] == [
        "Built and deployed a mood-based recommender using Node.js and Express."]
    # Filtered items remain traceable with provenance + reasons.
    filtered = content["_diagnostics"]["filtered_bullets"]
    assert {f["reason"] for f in filtered} == {"marketing_prose", "redundant_tech_statement"}
    assert all(f["evidence"] for f in filtered)
    # Claims stay 1:1 with visible bullets; provenance intact.
    assert [c["text"] for c in claims if "Tic-Tac-Toe" in c["claim_id"] or "tic" in c["claim_id"]] != []
    assert all(c["evidence"] for c in claims)
    # LaTeX receives filtered bullets only.
    tex = to_latex({"content": content})
    assert GOOD_IMPL_BULLET[:40] in tex and GOOD_PRIORITY_BULLET[:40] in tex
    assert "ultimate battle" not in tex and "Implemented using Java." not in tex
