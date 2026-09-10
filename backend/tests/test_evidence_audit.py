import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from app.services.evidence.base import (
    EvidenceDepth,
    VerificationStatus,
    ExtractedSignal,
    VerificationResult,
)
from app.services.evidence.github import GitHubProvider
from app.services.evidence.kaggle import KaggleProvider
from app.services.evidence.codeforces import CodeforcesProvider
from app.services.evidence.linkedin import LinkedInProvider
from app.services import signal_extractor as se
from app.services import skill_engine


# ===========================================================================
# 1. GITHUB AUDIT VERIFICATION TESTS
# ===========================================================================

def test_github_fork_repository_discount():
    provider = GitHubProvider()
    inspection = {
        "is_fork": True,
        "languages": {"TypeScript": 20000, "JavaScript": 5000},
        "dependencies": ["react", "express"],
        "top_files": ["src/index.ts", "package.json"],
        "commit_count": 45,
    }
    res = provider._build_result_from_inspection("testuser", "forked-repo", inspection, datetime.now(timezone.utc))
    assert res.status == VerificationStatus.VERIFIED
    assert any("fork" in w.lower() for w in res.warnings)

    for sig in res.signals:
        # Forked repos must be capped at Level 2 and discounted strength
        assert sig.depth in (EvidenceDepth.LEVEL_1_MENTION, EvidenceDepth.LEVEL_2_CONFIG)
        assert sig.signal_strength <= 0.55
        assert "[Forked Repository]" in sig.reason


def test_github_test_framework_precision():
    provider = GitHubProvider()

    # Case A: False positive substrings like 'fastest-validator' or 'contest'
    fake_deps_inspection = {
        "is_fork": False,
        "dependencies": ["fastest-validator", "contest-runner", "detox-pills"],
        "languages": {"JavaScript": 5000},
    }
    res_fake = provider._build_result_from_inspection("testuser", "no-tests-repo", fake_deps_inspection, datetime.now(timezone.utc))
    test_signals_fake = [s for s in res_fake.signals if "test" in s.skill.lower()]
    assert len(test_signals_fake) == 0, f"False positive test signal detected: {test_signals_fake}"

    # Case B: Real test frameworks like pytest, jest, vitest
    real_deps_inspection = {
        "is_fork": False,
        "dependencies": ["jest", "supertest", "pytest"],
        "languages": {"Python": 15000, "JavaScript": 10000},
    }
    res_real = provider._build_result_from_inspection("testuser", "real-tests-repo", real_deps_inspection, datetime.now(timezone.utc))
    test_signals_real = [s for s in res_real.signals if s.skill in ("Testing", "Unit Testing & TDD")]
    assert len(test_signals_real) == 1
    assert test_signals_real[0].depth == EvidenceDepth.LEVEL_3_IMPLEMENTATION


def test_github_auth_and_database_detection():
    provider = GitHubProvider()
    inspection = {
        "is_fork": False,
        "dependencies": ["jsonwebtoken", "bcrypt", "prisma", "pg"],
        "languages": {"TypeScript": 30000},
    }
    res = provider._build_result_from_inspection("testuser", "backend-api", inspection, datetime.now(timezone.utc))
    skills = {s.skill: s for s in res.signals}
    assert "Authentication & Authorization" in skills
    assert "Database Design" in skills
    assert skills["Authentication & Authorization"].depth == EvidenceDepth.LEVEL_3_IMPLEMENTATION


def test_github_fullstack_architecture_detection():
    provider = GitHubProvider()
    inspection = {
        "is_fork": False,
        "dependencies": ["react", "express"],
        "languages": {"TypeScript": 40000},
        "top_files": ["frontend/src/App.tsx", "backend/src/server.ts", "package.json"],
    }
    res = provider._build_result_from_inspection("testuser", "fullstack-app", inspection, datetime.now(timezone.utc))
    skills = {s.skill: s for s in res.signals}
    assert "System Design" in skills


def test_github_staleness_warning():
    provider = GitHubProvider()
    four_years_ago = (datetime.now(timezone.utc) - timedelta(days=365 * 4)).isoformat()
    inspection = {
        "is_fork": False,
        "languages": {"Python": 10000},
        "pushed_at": four_years_ago,
    }
    res = provider._build_result_from_inspection("testuser", "stale-repo", inspection, datetime.now(timezone.utc))
    assert any("years ago" in w.lower() for w in res.warnings)


# ===========================================================================
# 2. KAGGLE AUDIT VERIFICATION TESTS
# ===========================================================================

def test_kaggle_empty_account_zero_signals():
    provider = KaggleProvider()
    inspection = {
        "username": "brand_new_student",
        "tier": "novice",
        "notebooks_count": 0,
        "competitions_count": 0,
        "datasets_count": 0,
    }
    res = provider._build_result_from_inspection(inspection, datetime.now(timezone.utc))
    assert res.status == VerificationStatus.VERIFIED
    assert len(res.signals) == 0
    assert any("no public data science" in w.lower() for w in res.warnings)


def test_kaggle_structured_notebook_library_detection():
    provider = KaggleProvider()
    inspection = {
        "username": "data_explorer",
        "tier": "contributor",
        "notebooks": [
            {
                "title": "Customer Churn Prediction",
                "libraries": ["pandas", "numpy", "scikit-learn", "torch"],
            },
            {
                "title": "Image Classifier",
                "libraries": ["tensorflow", "matplotlib"],
            }
        ],
        "competitions_count": 1,
    }
    res = provider._build_result_from_inspection(inspection, datetime.now(timezone.utc))
    assert res.status == VerificationStatus.VERIFIED
    skills = {s.skill: s for s in res.signals}

    # Core data science skills
    assert "Machine Learning" in skills
    assert "Data Analysis" in skills
    assert "Python" in skills

    # Specific detected libraries from public notebook code
    assert "Pandas" in skills
    assert "NumPy" in skills
    assert "Scikit-learn" in skills
    assert "Deep Learning" in skills
    assert "Data Visualization" in skills
    assert skills["Pandas"].depth == EvidenceDepth.LEVEL_3_IMPLEMENTATION


# ===========================================================================
# 3. CODEFORCES AUDIT VERIFICATION TESTS
# ===========================================================================

def test_codeforces_problem_tag_topic_breadth():
    provider = CodeforcesProvider()
    inspection = {
        "handle": "algo_contestant",
        "rating": 1650,
        "max_rating": 1680,
        "rank": "specialist",
        "contest_count": 22,
        "solved_count": 65,
        "problem_tags": {
            "dp": 20,
            "graphs": 15,
            "greedy": 18,
            "trees": 12,
            "math": 10,
            "binary search": 8,
        },
    }
    res = provider._build_result_from_inspection(inspection, datetime.now(timezone.utc))
    assert res.status == VerificationStatus.VERIFIED

    # Check that useless contribution field is stripped
    assert "contribution" not in res.raw_metadata

    # Check DSA signal carries topic breadth
    dsa_sig = [s for s in res.signals if s.skill == "Data Structures & Algorithms"][0]
    assert "dp" in dsa_sig.reason
    assert "graphs" in dsa_sig.reason
    assert dsa_sig.metadata["solved_count"] == 65
    assert len(dsa_sig.metadata["problem_tags"]) == 6


def test_codeforces_unrated_zero_problems_zero_signals():
    provider = CodeforcesProvider()
    inspection = {
        "handle": "inactive_account",
        "rating": 0,
        "max_rating": 0,
        "rank": "unrated",
        "contest_count": 0,
        "solved_count": 0,
        "problem_tags": {},
    }
    res = provider._build_result_from_inspection(inspection, datetime.now(timezone.utc))
    assert res.status == VerificationStatus.VERIFIED
    assert len(res.signals) == 0
    assert any("not participated" in w.lower() for w in res.warnings)


# ===========================================================================
# 4. RESUME & FILE EVIDENCE AUDIT TESTS
# ===========================================================================

def test_resume_aspirational_phrase_filtering():
    """Ensure phrases like 'interested in learning Docker' do NOT award Docker."""
    evidence = [{
        "id": "doc1",
        "evidence_type": "resume",
        "title": "Software_Engineer_Resume.pdf",
        "metadata": {
            "parsed_text": (
                "Passionate developer. Interested in learning Docker and Kubernetes. "
                "Seeking to learn Go. "
                "Engineered scalable microservices using Python, FastAPI, and PostgreSQL. "
                "Implemented responsive frontend interfaces with React."
            )
        }
    }]
    signals = se.extract_signals(evidence, [], [])
    detected_skills = {s["canonical_name"]: s for s in signals}

    # Aspirational skills must be filtered out
    assert "Docker" not in detected_skills, "Aspirational skill Docker should have been suppressed"
    assert "Kubernetes" not in detected_skills, "Aspirational skill Kubernetes should have been suppressed"
    assert "Go" not in detected_skills, "Aspirational skill Go should have been suppressed"

    # Concrete action skills must be credited
    assert "Python" in detected_skills
    assert "React" in detected_skills
    assert "PostgreSQL" in detected_skills
    # Concrete action claims receive 0.50 value with 0.50 reliability
    assert detected_skills["Python"]["signal_value"] == 0.50
    assert detected_skills["Python"]["source_reliability"] == 0.50


def test_resume_self_reported_reliability_boundary():
    """Self-reported resume claims cannot outweigh concrete implementations."""
    evidence = [{
        "id": "doc2",
        "evidence_type": "resume",
        "title": "Resume.pdf",
        "metadata": {
            "parsed_text": "Built web backend using Node.js and PostgreSQL."
        }
    }]
    signals = se.extract_signals(evidence, [], [])
    node_sigs = [s for s in signals if s["canonical_name"] == "Node.js"]
    assert len(node_sigs) == 1
    prof, _, _, _ = skill_engine.proficiency(node_sigs)
    # Self-reported resume claim produces low-confidence moderate proficiency (0.50)
    assert prof == pytest.approx(0.50, abs=0.05)


# ===========================================================================
# 5. PROJECTS & CROSS-SOURCE DEDUPLICATION AUDIT TESTS
# ===========================================================================

def test_project_github_cross_deduplication():
    """
    If a student submits a GitHub repo AND a Project pointing to that exact same repo,
    signals must NOT be double-counted.
    """
    repo_url = "https://github.com/student/e-commerce-api"
    evidence = [{
        "id": "ev-gh-1",
        "evidence_type": "github",
        "source_url": repo_url,
        "mock_inspection": {
            "languages": {"TypeScript": 25000},
            "dependencies": ["react", "express", "prisma"],
            "commit_count": 40,
        }
    }]
    projects = [{
        "id": "proj-1",
        "name": "E-Commerce API",
        "description": "Implemented online store backend with TypeScript and React.",
        "technologies": ["TypeScript", "React"],
        "github_url": repo_url,
        "student_contribution": "Architected the product ordering pipeline",
    }]

    signals = se.extract_signals(evidence, projects, [])

    # The GitHub provider inspected the real repo; duplicate project signals must be suppressed
    ts_sigs = [s for s in signals if s["canonical_name"] == "TypeScript"]
    assert len(ts_sigs) == 1, f"Expected 1 TypeScript signal, got duplicates: {ts_sigs}"
    assert ts_sigs[0]["source_type"] == "github"


def test_project_student_contribution_incorporation():
    """Project with specific student contribution correctly incorporates depth."""
    projects = [{
        "id": "proj-2",
        "name": "Team Analytics Tool",
        "description": "Full team project for data visualization.",
        "technologies": ["Python", "FastAPI"],
        "student_contribution": "Personally engineered and implemented JWT authentication and Redis caching",
    }]
    signals = se.extract_signals([], projects, [])
    skills = {s["canonical_name"]: s for s in signals}
    assert "Python" in skills
    # Student contribution has strong implementation keywords ('jwt', 'redis', 'caching')
    assert skills["Python"]["signal_value"] >= 0.65
    assert skills["Python"]["metadata"].get("student_contribution") is not None


# ===========================================================================
# 6. CERTIFICATIONS SCOPING AUDIT TESTS
# ===========================================================================

def test_certification_vendor_mapping_and_no_word_tokenization():
    """Amazon Web Services should map to AWS, NOT extract 'Web Services'."""
    certs = [{
        "id": "cert-1",
        "name": "AWS Certified Solutions Architect",
        "issuing_org": "Amazon Web Services",
        "completion_year": datetime.now(timezone.utc).year - 1,
    }]
    signals = se.extract_signals([], [], certs)
    skill_names = [s["canonical_name"] for s in signals]
    assert "AWS" in skill_names
    assert "Web Services" not in skill_names


def test_certification_outdated_discount():
    """Certifications completed > 5 years ago must be discounted and marked outdated."""
    certs = [{
        "id": "cert-2",
        "name": "Oracle Certified Professional Java Programmer",
        "issuing_org": "Oracle",
        "completion_year": 2017,  # > 5 years ago
    }]
    signals = se.extract_signals([], [], certs)
    java_sigs = [s for s in signals if s["canonical_name"] == "Java"]
    assert len(java_sigs) >= 1
    sig = java_sigs[0]
    assert sig["signal_value"] == pytest.approx(0.35, abs=0.01)  # 0.50 * 0.70 = 0.35
    assert sig["metadata"]["is_outdated"] is True
    assert "outdated" in sig["explanation"].lower()
