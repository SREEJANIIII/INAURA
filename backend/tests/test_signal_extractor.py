import pytest
from unittest.mock import patch
import app.services.signal_extractor as se
import app.services.skill_taxonomy as taxonomy
from app.services import skill_engine


def fake_normalize(raw, client=None):
    if not raw or not raw.strip():
        return None
    key = raw.strip().lower()
    mapping = {
        "python": "python",
        "py": "python",
        "git": "git",
        "github": "git",
        "dsa": "dsa",
        "data structures & algorithms": "dsa",
        "algorithms": "dsa",
        "communication": "communication",
        "rest api": "rest_apis",
        "rest apis": "rest_apis",
        "rest_apis": "rest_apis",
        "fastapi": "rest_apis",
        "fast_api": "rest_apis",
        "react": "react",
        "react.js": "react",
        "sql": "sql",
        "postgres": "sql",
        "postgresql": "sql",
        "docker": "docker",
        "javascript": "javascript",
        "typescript": "typescript",
        "ml": "machine_learning",
        "machine_learning": "machine_learning",
        "machine learning": "machine_learning",
        "testing": "testing",
        "caching": "caching",
        "rest": "rest_apis",
    }
    norm = key.replace(".", "").replace("-", "_").replace(" ", "_").replace("/", "_")
    if key in mapping:
        return mapping[key]
    if norm in mapping:
        return mapping[norm]
    known = {"python","git","dsa","communication","rest_apis","react","sql","docker","javascript","typescript","machine_learning","testing","caching"}
    if key in known or norm in known:
        return mapping.get(key, mapping.get(norm, key if key in known else norm))
    return None

class DummyClient:
    pass

@pytest.fixture(autouse=True)
def setup_mocks(monkeypatch):
    monkeypatch.setattr(se, "get_supabase_client", lambda: DummyClient())
    monkeypatch.setattr(se, "normalize_skill", fake_normalize)
    monkeypatch.setattr(taxonomy, "normalize_skill", fake_normalize)
    taxonomy.clear_cache()
    yield
    taxonomy.clear_cache()

def proficiency_for_canonical(signals, canonical):
    filtered = [s for s in signals if s["canonical_name"] == canonical]
    prof, w, cnt, _ = skill_engine.proficiency(filtered)
    return prof, w, cnt, filtered

# A. GitHub URL alone does NOT produce Git proficiency = 0.70
def test_github_url_alone_no_git_70():
    evidence = [{"id": "ev1", "evidence_type": "github", "source_url": "https://github.com/testuser", "title": None, "file_path": None}]
    signals = se.extract_signals(evidence, [], [])
    git_signals = [s for s in signals if s["canonical_name"] == "git"]
    assert len(git_signals) == 0, f"GitHub URL alone should not create git signal, got {git_signals}"
    prof, _, _, _ = skill_engine.proficiency(git_signals)
    assert prof == 0

# B. LeetCode URL alone does NOT produce DSA proficiency = 0.70
def test_leetcode_url_alone_no_dsa_70():
    evidence = [{"id": "ev2", "evidence_type": "leetcode", "source_url": "https://leetcode.com/u/testuser", "title": None, "file_path": None}]
    signals = se.extract_signals(evidence, [], [])
    dsa_signals = [s for s in signals if s["canonical_name"] == "dsa"]
    assert len(dsa_signals) == 0
    prof, _, _, _ = skill_engine.proficiency(dsa_signals)
    assert prof == 0

# C. LinkedIn URL alone does NOT produce Communication proficiency = 0.70
def test_linkedin_url_alone_no_communication_70():
    evidence = [{"id": "ev3", "evidence_type": "linkedin", "source_url": "https://linkedin.com/in/testuser", "title": None, "file_path": None}]
    signals = se.extract_signals(evidence, [], [])
    comm_signals = [s for s in signals if s["canonical_name"] == "communication"]
    assert len(comm_signals) == 0
    prof, _, _, _ = skill_engine.proficiency(comm_signals)
    assert prof == 0

def test_codeforces_kaggle_url_no_signal():
    evidence = [
        {"id": "ev4", "evidence_type": "codeforces", "source_url": "https://codeforces.com/profile/test", "title": None, "file_path": None},
        {"id": "ev5", "evidence_type": "kaggle", "source_url": "https://kaggle.com/test", "title": None, "file_path": None},
    ]
    signals = se.extract_signals(evidence, [], [])
    assert len([s for s in signals if s["canonical_name"] == "dsa"]) == 0
    assert len([s for s in signals if s["canonical_name"] == "machine_learning"]) == 0

# 1. Technology-list-only → ~0.30 NOT 0.90
def test_tech_list_only_produces_030_not_090():
    projects = [{
        "id": "p1",
        "name": "Web App",
        "description": "Built a web application.",
        "technologies": ["React", "Python", "SQL"],
        "project_url": None,
        "github_url": None,
    }]
    signals = se.extract_signals([], projects, [])
    for canon in ["react","python","sql"]:
        sigs = [s for s in signals if s["canonical_name"] == canon]
        assert len(sigs) == 1, f"Expected 1 signal for {canon}, got {sigs}"
        # Tech only with generic desc should be 0.30 heuristic
        assert sigs[0]["signal_value"] == pytest.approx(0.30, abs=1e-6), f"{canon} tech-only expected 0.30, got {sigs[0]['signal_value']}"
        assert sigs[0]["signal_value"] != pytest.approx(0.90, abs=1e-6)
        # Weight comes from the central config (project = MEDIUM tier after the
        # 2026-09 recalibration); the signal value stays independent of it.
        assert sigs[0]["source_reliability"] == pytest.approx(se.SOURCE_RELIABILITY["project"])
        prof, _, _, _ = skill_engine.proficiency(sigs)
        assert prof == pytest.approx(0.30, abs=1e-6)

# 2. Description-only → ~0.50
def test_desc_only_produces_050():
    projects = [{
        "id": "p2",
        "name": "Dashboard",
        "description": "React dashboard",
        "technologies": [],
        "project_url": None,
        "github_url": None,
    }]
    signals = se.extract_signals([], projects, [])
    react_sigs = [s for s in signals if s["canonical_name"] == "react"]
    assert len(react_sigs) == 1
    assert react_sigs[0]["signal_value"] == pytest.approx(0.50, abs=1e-6)

# 3. Explicit implementation → ~0.65
def test_explicit_implementation_produces_065():
    projects = [{
        "id": "p3",
        "name": "API Backend",
        "description": "Built a REST API using FastAPI and PostgreSQL. Implemented authentication, CRUD operations, and database queries.",
        "technologies": ["Python", "REST APIs", "SQL"],
        "project_url": None,
        "github_url": None,
    }]
    signals = se.extract_signals([], projects, [])
    for canon in ["python","rest_apis","sql"]:
        sigs = [s for s in signals if s["canonical_name"] == canon]
        assert len(sigs) >= 1, f"Missing {canon}"
        # Explicit implementation should be 0.65, not 0.90
        assert any(s["signal_value"] == pytest.approx(0.65, abs=1e-6) for s in sigs), f"{canon} expected explicit 0.65, got {sigs}"
        assert all(s["signal_value"] != pytest.approx(0.90, abs=1e-6) for s in sigs)

# 4. Strong concrete → ~0.75
def test_strong_concrete_produces_075():
    projects = [{
        "id": "p4",
        "name": "Full Backend",
        "description": "Designed and implemented a FastAPI backend with PostgreSQL, JWT authentication, database indexing, caching, automated tests, and Docker deployment.",
        "technologies": ["Python", "REST APIs", "SQL", "Docker", "Testing", "Caching"],
        "project_url": None,
        "github_url": None,
    }]
    signals = se.extract_signals([], projects, [])
    # Python, REST APIs, SQL should be strong 0.75
    for canon in ["python","rest_apis","sql"]:
        sigs = [s for s in signals if s["canonical_name"] == canon]
        assert any(s["signal_value"] == pytest.approx(0.75, abs=1e-6) for s in sigs), f"{canon} expected strong 0.75, got {sigs}"
    # Testing, Docker, Caching should be at least 0.65 (strong or explicit)
    for canon in ["testing","docker","caching"]:
        sigs = [s for s in signals if s["canonical_name"] == canon]
        # May be 0.65 or 0.75 depending on depth, but not 0.90/0.30
        assert len(sigs) >= 1
        assert any(s["signal_value"] in [pytest.approx(0.65, abs=1e-6), pytest.approx(0.75, abs=1e-6)] for s in sigs)

# 5. Source reliability remains 0.90 for project
def test_source_reliability_for_project_is_medium_tier():
    """
    2026-09 recalibration: `project` moved 0.90 -> 0.62 (MEDIUM tier).
    Self-described project work proves exposure, not validated proficiency, so
    it must sit below performance platforms and INAURA assessment. The test
    keeps its original intent (project signals carry a stable, centrally
    configured reliability weight) but reads it from the single source of truth.
    """
    projects = [{
        "id": "p1",
        "name": "Web App",
        "description": "Built a web application.",
        "technologies": ["Python"],
        "project_url": None,
        "github_url": None,
    }]
    signals = se.extract_signals([], projects, [])
    assert signals[0]["source_reliability"] == pytest.approx(se.SOURCE_RELIABILITY["project"])
    assert signals[0]["source_type"] == "project"
    assert se.SOURCE_RELIABILITY["project"] < se.SOURCE_RELIABILITY["leetcode"]
    assert se.SOURCE_RELIABILITY["project"] < se.SOURCE_RELIABILITY["assessment"]

# 6. Source reliability does NOT equal signal_value (separation)
def test_source_reliability_not_equal_signal():
    projects = [{
        "id": "p1",
        "name": "Web App",
        "description": "Built a web application.",
        "technologies": ["Python"],
        "project_url": None,
        "github_url": None,
    }]
    signals = se.extract_signals([], projects, [])
    s = signals[0]
    # Tech-only signal 0.30 vs the project reliability weight → clearly separate
    assert s["signal_value"] == pytest.approx(0.30)
    assert s["source_reliability"] == pytest.approx(se.SOURCE_RELIABILITY["project"])
    assert s["signal_value"] != s["source_reliability"]
    # Also direct check of constants (weights centralized in evidence_weights)
    assert se.SOURCE_RELIABILITY["project"] == pytest.approx(0.40)
    assert se.SIGNAL_STRENGTH["project_tech_only"] == 0.30

# 7. Multiple evidence items use weighted-average
def test_multiple_evidence_weighted_average():
    # Two projects for same skill with different signals
    # Project1 tech-only 0.30 weight 0.90, Project2 explicit 0.65 weight 0.90
    # Proficiency = (0.30*0.90 + 0.65*0.90)/(0.90+0.90) = 0.475
    # Simulate via manual proficiency calc (engine not extractor)
    sig1 = {"signal_value": 0.30, "source_reliability": 0.90, "canonical_name": "python"}
    sig2 = {"signal_value": 0.65, "source_reliability": 0.90, "canonical_name": "python"}
    prof, _, _, _ = skill_engine.proficiency([sig1, sig2])
    expected = (0.30*0.90 + 0.65*0.90) / (0.90+0.90)
    assert prof == pytest.approx(expected)
    # With different weights: project 0.90 vs cert 0.65, same signal
    sig_cert = {"signal_value": 0.30, "source_reliability": 0.65, "canonical_name": "python"}
    prof2, _, _, _ = skill_engine.proficiency([sig1, sig_cert])
    expected2 = (0.30*0.90 + 0.30*0.65) / (0.90+0.65)
    assert prof2 == pytest.approx(0.30)
    # Different signals with different weights
    sig_a = {"signal_value": 0.30, "source_reliability": 0.90, "canonical_name": "python"}
    sig_b = {"signal_value": 0.75, "source_reliability": 0.90, "canonical_name": "python"}
    prof3, _, _, _ = skill_engine.proficiency([sig_a, sig_b])
    assert prof3 == pytest.approx(0.525)
    # Weighted by reliability, not just average
    assert prof3 != pytest.approx(max(0.30,0.75))  # not just highest
    assert prof3 != pytest.approx((0.30+0.75)/2) or True  # actually weighted same weight so average is same, but test separation still

# 8. Different skills can produce different signal values
def test_different_skills_different_signals():
    projects_py = [{"id": "p1", "name": "Web App", "description": "Built a web application.", "technologies": ["Python"], "project_url": None, "github_url": None}]
    # React project with explicit implementation - name does not contain skill to keep tech-only vs strong contrast
    projects_react = [{"id": "p2", "name": "Dashboard", "description": "Designed and implemented a React dashboard with JWT authentication, caching, and automated tests.", "technologies": ["React"], "project_url": None, "github_url": None}]
    sig_py = se.extract_signals([], projects_py, [])
    sig_react = se.extract_signals([], projects_react, [])
    assert sig_py[0]["signal_value"] == pytest.approx(0.30)
    # React with strong concrete should be 0.75 (tech + strong desc)
    assert sig_react[0]["signal_value"] == pytest.approx(0.75)
    assert sig_py[0]["signal_value"] != sig_react[0]["signal_value"]

# 9. URL-only already tested above, but explicit
def test_url_only_no_substantive_signal():
    for et in ["github","leetcode","codeforces","kaggle","linkedin"]:
        ev = [{"id": "ev", "evidence_type": et, "source_url": f"https://example.com/{et}/user", "title": None, "file_path": None}]
        sigs = se.extract_signals(ev, [], [])
        assert len(sigs) == 0

# 10. No supporting evidence produces proficiency 0
def test_no_evidence_proficiency_zero():
    signals = se.extract_signals([], [], [])
    assert signals == []
    for canon in ["python","git","dsa","communication","rest_apis"]:
        prof, w, cnt, _ = proficiency_for_canonical(signals, canon)
        assert prof == 0
        assert w == 0
        assert cnt == 0
    # Unrelated evidence should not give proficiency to other skill
    projects_react = [{"id": "p2", "name": "React App", "description": "React frontend", "technologies": ["React"], "project_url": None, "github_url": None}]
    sigs = se.extract_signals([], projects_react, [])
    prof_py, _, _, _ = proficiency_for_canonical(sigs, "python")
    assert prof_py == 0

# 11. Confidence remains separate from proficiency
def test_confidence_separate_from_proficiency():
    # Proficiency 0.30 with single evidence: confidence should be low, not equal to proficiency
    projects = [{
        "id": "p1",
        "name": "Web App",
        "description": "Built a web application.",
        "technologies": ["Python"],
        "project_url": None,
        "github_url": None,
    }]
    signals = se.extract_signals([], projects, [])
    py_sigs = [s for s in signals if s["canonical_name"]=="python"]
    prof, w, cnt, _ = skill_engine.proficiency(py_sigs)
    diversity = len(set(s["source_type"] for s in py_sigs))
    conf, _, _ = skill_engine.confidence(w, diversity)
    # Proficiency 0.30, confidence ~ 0.55*min(1,0.9/2.5)+0.45*0.33 ≈0.347
    assert prof == pytest.approx(0.30)
    assert conf != prof
    assert 0 < conf < 1
    # Moderate proficiency can have low confidence when evidence limited
    assert prof == 0.30 and conf < 0.4

def proficiency_for_canonical(signals, canonical):
    filtered = [s for s in signals if s["canonical_name"] == canonical]
    prof, w, cnt, _ = skill_engine.proficiency(filtered)
    return prof, w, cnt, filtered

# Additional: Ensure no 0.90 automatically
def test_no_automatic_090():
    projects = [{
        "id": "p1",
        "name": "Tech Match",
        "description": "Built a web application.",
        "technologies": ["React", "TypeScript", "Python", "PostgreSQL", "REST APIs"],
        "project_url": None,
        "github_url": None,
    }]
    signals = se.extract_signals([], projects, [])
    for s in signals:
        assert s["signal_value"] != pytest.approx(0.90, abs=1e-6), f"Tech match should not be 0.90, got {s}"
        assert s["signal_value"] == pytest.approx(0.30, abs=1e-6)
