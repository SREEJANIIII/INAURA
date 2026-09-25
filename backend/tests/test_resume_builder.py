from app.services.resume_builder import latex_escape, to_latex, verify_content


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
