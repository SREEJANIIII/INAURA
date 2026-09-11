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
    assert "Application Security" in skills  # canonical name (was non-canonical "Authentication & Authorization")
    assert "DBMS" in skills  # canonical name (was non-canonical "Database Design")
    assert skills["Application Security"].depth == EvidenceDepth.LEVEL_3_IMPLEMENTATION


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


# ===========================================================================
# 7. JAVA GITHUB REGRESSION TESTS (Java 0% root-cause coverage)
# ===========================================================================

def _java_repo_inspection(**overrides):
    base = {
        "name": "spring-petclinic-clone",
        "description": "Spring Boot Java backend with REST APIs",
        "topics": ["java", "spring-boot"],
        "languages": {"Java": 45000, "HTML": 2000},
        "root_files": ["pom.xml", "README.md", "Dockerfile"],
        "top_files": ["Dockerfile"],
        "tree_scanned": True,
        "java_file_count": 14,
        "java_test_file_count": 3,
        "has_java_build_manifest": True,
        "build_system": "maven",
        "java_frameworks": ["spring_boot"],
        "java_build_deps": ["junit"],
        "has_workflows": False,
        "is_fork": False,
    }
    base.update(overrides)
    return base


def test_github_java_meaningful_implementation_produces_java_evidence():
    """Real Java repo (sources + manifest + Spring) must yield Java evidence, not 0%."""
    provider = GitHubProvider()
    res = provider._build_result_from_inspection(
        "student", "java-backend", _java_repo_inspection(), datetime.now(timezone.utc)
    )
    assert res.status == VerificationStatus.VERIFIED
    skills = {s.skill: s for s in res.signals}
    assert "Java" in skills
    assert skills["Java"].depth == EvidenceDepth.LEVEL_4_SUBSTANTIAL
    assert skills["Java"].signal_strength == pytest.approx(0.85)
    assert skills["Java"].source_reliability == pytest.approx(0.40)  # GitHub SUPPORTING tier
    assert "Spring Boot" in skills  # canonical framework signal

    # End-to-end through the shared extractor: single GitHub source proficiency
    evidence = [{
        "id": "ev-java",
        "evidence_type": "github",
        "source_url": "https://github.com/student/java-backend",
        "mock_inspection": _java_repo_inspection(),
    }]
    signals = se.extract_signals(evidence, [], [])
    java_sigs = [s for s in signals if s["canonical_name"] == "Java"]
    assert len(java_sigs) == 1
    # Raw weighted average of the GitHub signal alone.
    prof, _, cnt, _ = skill_engine.proficiency(java_sigs)
    assert cnt == 1
    assert prof == pytest.approx(0.85)

    # What the pipeline reports: while nothing has validated the skill, the
    # unvalidated-evidence prior shrinks the artifact-only estimate
    # (0.85*0.40 + 0.35*0.60) / (0.40 + 0.60) = 0.55.
    shrunk, _, _, _, prior_applied = skill_engine.proficiency_with_prior(java_sigs)
    assert shrunk == pytest.approx(0.55)
    assert prior_applied is True
    assert shrunk < prof
    assert java_sigs[0]["source_reliability"] == pytest.approx(0.40)  # GitHub SUPPORTING tier


def test_github_java_weak_footprint_does_not_overaward():
    """Trace Java bytes with no sources/manifest must NOT reach implementation strength."""
    provider = GitHubProvider()
    inspection = _java_repo_inspection(
        name="js-frontend",
        description="JS app",
        topics=[],
        languages={"JavaScript": 30000, "Java": 400},
        root_files=["package.json", "README.md"],
        top_files=[],
        tree_scanned=True,
        java_file_count=0,
        java_test_file_count=0,
        has_java_build_manifest=False,
        build_system=None,
        java_frameworks=[],
        java_build_deps=[],
    )
    res = provider._build_result_from_inspection("student", "js-frontend", inspection, datetime.now(timezone.utc))
    java_sigs = [s for s in res.signals if s.skill == "Java"]
    assert len(java_sigs) <= 1
    if java_sigs:
        assert java_sigs[0].depth <= EvidenceDepth.LEVEL_2_CONFIG
        assert java_sigs[0].signal_strength <= 0.60
        prof, _, _, _ = skill_engine.proficiency([java_sigs[0].to_dict()])
        assert prof <= 0.60


def test_github_java_readme_mention_only_stays_documentation_level():
    """
    README/description/topics saying 'Java' with zero implementation evidence
    must never reach implementation depth.

    Behaviour update (deep GitHub evidence pipeline): documentation is now an
    explicit, weakest evidence tier (LEVEL_1_MENTION, 0.40) instead of being
    dropped entirely, so the provider can distinguish documentation-only from
    configuration and implementation evidence. The original guarantee — a
    README mention must not be treated as demonstrated Java implementation —
    is asserted below and unchanged.
    """
    provider = GitHubProvider()
    inspection = _java_repo_inspection(
        name="java-notes",
        description="My Java tutorial notes and interview prep",
        topics=["java"],
        languages={},
        root_files=["README.md"],
        top_files=[],
        tree_scanned=True,
        java_file_count=0,
        java_test_file_count=0,
        has_java_build_manifest=False,
        build_system=None,
        java_frameworks=[],
        java_build_deps=[],
    )
    res = provider._build_result_from_inspection("student", "java-notes", inspection, datetime.now(timezone.utc))
    java_sigs = [s for s in res.signals if s.skill == "Java"]
    assert len(java_sigs) <= 1
    if java_sigs:
        sig = java_sigs[0]
        assert sig.depth == EvidenceDepth.LEVEL_1_MENTION
        assert sig.signal_strength == pytest.approx(0.40)
        assert sig.metadata.get("documentation_only") is True
        prof, _, _, _ = skill_engine.proficiency([sig.to_dict()])
        assert prof == pytest.approx(0.40)
        assert prof < 0.75  # strictly below implementation-level evidence


def test_github_java_manifest_without_sources_is_weak():
    """pom.xml alone (no .java files, no bytes) is config-level, not implementation."""
    provider = GitHubProvider()
    inspection = _java_repo_inspection(
        name="empty-archetype",
        description="",
        topics=[],
        languages={},
        root_files=["pom.xml"],
        top_files=[],
        tree_scanned=True,
        java_file_count=0,
        java_test_file_count=0,
        has_java_build_manifest=True,
        build_system="maven",
        java_frameworks=[],
        java_build_deps=[],
    )
    res = provider._build_result_from_inspection("student", "empty-archetype", inspection, datetime.now(timezone.utc))
    java_sigs = [s for s in res.signals if s.skill == "Java"]
    assert len(java_sigs) == 1
    assert java_sigs[0].depth == EvidenceDepth.LEVEL_2_CONFIG
    assert java_sigs[0].signal_strength == pytest.approx(0.60)


def test_evidence_hierarchy_github_below_performance_sources():
    """
    GitHub SUPPORTING (0.40) < LeetCode/Codeforces/Kaggle HIGH (0.85) <
    INAURA assessment VERY HIGH (0.95).

    Recalibration history: GitHub 0.70 -> 0.60 (2026-09) -> 0.40 (2026-09-11).
    Repository evidence shows technology exposure rather than demonstrated
    ability, so it is weighted as supporting evidence and cannot carry a skill
    on its own. All weights come from the central evidence_weights module.
    """
    from app.services.evidence.github import GITHUB_RELIABILITY
    from app.services.evidence.leetcode import LEETCODE_RELIABILITY
    from app.services.evidence.codeforces import CODEFORCES_RELIABILITY
    from app.services.evidence.kaggle import KAGGLE_RELIABILITY

    assert GITHUB_RELIABILITY == pytest.approx(0.40)
    assert LEETCODE_RELIABILITY == pytest.approx(0.85)
    assert CODEFORCES_RELIABILITY == pytest.approx(0.85)
    assert KAGGLE_RELIABILITY == pytest.approx(0.85)
    assert GITHUB_RELIABILITY < LEETCODE_RELIABILITY

    assert se.SOURCE_RELIABILITY["leetcode"] > se.SOURCE_RELIABILITY["github"]
    assert se.SOURCE_RELIABILITY["codeforces"] > se.SOURCE_RELIABILITY["github"]
    assert se.SOURCE_RELIABILITY["kaggle"] > se.SOURCE_RELIABILITY["github"]
    # GitHub is now supporting evidence: it ranks below credentials and
    # coursework as well as below the performance platforms.
    assert se.SOURCE_RELIABILITY["github"] < se.SOURCE_RELIABILITY["certification"]
    assert se.SOURCE_RELIABILITY["syllabus"] > se.SOURCE_RELIABILITY["github"]

    assert skill_engine.SOURCE_RELIABILITY["github"] == pytest.approx(se.SOURCE_RELIABILITY["github"])
    assert skill_engine.SOURCE_RELIABILITY["leetcode"] == pytest.approx(se.SOURCE_RELIABILITY["leetcode"])

    # VERY HIGH tier: INAURA's own assessment outranks every artifact source.
    assert se.SOURCE_RELIABILITY["assessment"] > se.SOURCE_RELIABILITY["leetcode"]
    assert se.SOURCE_RELIABILITY["assessment"] > se.SOURCE_RELIABILITY["github"]
    assert se.SOURCE_RELIABILITY["project"] < se.SOURCE_RELIABILITY["leetcode"]
    assert se.SOURCE_RELIABILITY["project"] == pytest.approx(0.40)


def test_canonical_skill_normalization_required_set():
    """Common variations must collapse to the canonical names used by industry requirements."""
    from app.services.skill_taxonomy import normalize_skill

    cases = {
        "Java": "Java",
        "java": "Java",
        "core java": "Java",
        "Python": "Python",
        "python3": "Python",
        "C++": "C++",
        "cpp": "C++",
        "JavaScript": "JavaScript",
        "js": "JavaScript",
        "TypeScript": "TypeScript",
        "ts": "TypeScript",
        "React": "React",
        "ReactJS": "React",
        "react.js": "React",
        "SQL": "SQL",
        "Git": "Git",
        "github": "Git",
        "DSA": "Data Structures & Algorithms",
        "data structures and algorithms": "Data Structures & Algorithms",
        "REST API": "REST APIs",
        "rest": "REST APIs",
        "Testing": "Testing",
        "pytest": "Testing",
        "System Design": "System Design",
        "software architecture": "System Design",
        "Spring Boot": "Spring Boot",
        "springboot": "Spring Boot",
    }
    for raw, expected in cases.items():
        assert normalize_skill(raw) == expected, f"{raw!r} should normalize to {expected!r}"


def test_required_java_skill_assessed_when_missing():
    """Industry-required Java with no evidence stays assessed at 0% as an evidence gap."""
    from app.services import analysis_run_service as ars

    req_map = ars.build_requirements_map(
        [{"skill": "Java", "skill_category": "Programming", "required_level": 0.75,
          "importance": 0.9, "demand": 0.8, "interview_relevance": 0.85}],
        None,
    )
    assessments = ars.calculate_assessments({}, req_map, None)
    java = next(a for a in assessments if a["canonical_name"] == "Java")
    assert java["proficiency"] == 0.0
    assert java["confidence"] == 0.0
    assert java["evidence_count"] == 0
    assert java["gap"] == pytest.approx(0.75)
    assert java["gap_type"] == "evidence_gap"
    assert java["is_missing_evidence"] is True


def test_verified_github_java_flows_into_assessment():
    """Persisted GitHub verification (verified_signals path used by run_analysis) feeds Java proficiency."""
    from app.services import analysis_run_service as ars

    evidence = [{
        "id": "ev-java",
        "evidence_type": "github",
        "source_url": "https://github.com/student/java-backend",
        "verification_status": "verified",
        "metadata": {
            "verification_status": "verified",
            "verified_signals": [{
                "skill": "Java",
                "canonical_name": "Java",
                "signal_strength": 0.85,
                "signal_value": 0.85,
                "source_reliability": 0.70,
                "reason": "Repository 'java-backend' 14 Java source files with build manifest (maven).",
                "explanation": "Repository 'java-backend' 14 Java source files with build manifest (maven).",
                "metadata": {"java_file_count": 14},
            }],
        },
    }]
    raw = ars.extract_skill_signals(evidence, [], [])
    assert any(s["canonical_name"] == "Java" for s in raw)
    signals = ars.normalize_signals(raw, None)
    grouped = ars.aggregate_skills(signals)
    req_map = ars.build_requirements_map(
        [{"skill": "Java", "skill_category": "Programming", "required_level": 0.75,
          "importance": 0.9, "demand": 0.8, "interview_relevance": 0.85}],
        None,
    )
    assessments = ars.calculate_assessments(grouped, req_map, None)
    java = next(a for a in assessments if a["canonical_name"] == "Java")
    # GitHub-only: the raw 0.85 signal is shrunk to 0.55 by the
    # unvalidated-evidence prior, so an artifact estimate no longer meets a
    # 0.75 role requirement on its own.
    assert java["proficiency"] == pytest.approx(0.55)
    assert java["unvalidated_prior_applied"] is True
    assert java["evidence_state"] == "evidence_estimate"
    assert java["evidence_count"] == 1
    assert java["gap"] == pytest.approx(0.20)
    # Single GitHub source: supporting evidence, not proof — low confidence.
    assert java["confidence"] < 0.50
    assert java["quadrant"] == "exploratory"


# ===========================================================================
# 8. EVERY-FILE ECOSYSTEM COVERAGE TESTS
# ===========================================================================

def _eco_inspection(**overrides):
    base = {
        "name": "repo",
        "description": "",
        "topics": [],
        "languages": {},
        "root_files": [],
        "top_files": [],
        "tree_scanned": True,
        "ext_file_counts": {},
        "is_fork": False,
    }
    base.update(overrides)
    return base


def _eco_signals(inspection, url="https://github.com/student/repo"):
    evidence = [{
        "id": "ev-eco",
        "evidence_type": "github",
        "source_url": url,
        "mock_inspection": inspection,
    }]
    return se.extract_signals(evidence, [], [])


def test_github_go_repo_with_gin_and_tests():
    """Go sources + go.mod (gin, testify) yield Go, REST APIs and Testing evidence."""
    from app.services.evidence.github import parse_manifest_deps

    assert "gin" in parse_manifest_deps(
        "gomod", "module example.com/api\n\ngo 1.21\nrequire github.com/gin-gonic/gin v1.9.1"
    )
    signals = _eco_signals(_eco_inspection(
        name="go-api",
        languages={"Go": 30000},
        root_files=["go.mod", "go.sum", "README.md"],
        ext_file_counts={".go": 8},
        top_files=["main.go", "handler.go", "handler_test.go", "go.mod"],
        eco_manifest_deps=["gin", "testify"],
    ))
    by_skill = {s["canonical_name"]: s for s in signals}
    assert "Go" in by_skill
    assert by_skill["Go"]["signal_value"] >= 0.75
    assert "REST APIs" in by_skill  # gin web framework
    assert "Testing" in by_skill  # handler_test.go
    prof, _, _, _ = skill_engine.proficiency([by_skill["Go"]])
    assert prof > 0
    assert by_skill["Go"]["source_reliability"] == pytest.approx(0.40)  # GitHub SUPPORTING tier


def test_github_rust_repo_with_cargo():
    """Rust sources + Cargo.toml yield substantial Rust evidence."""
    from app.services.evidence.github import parse_manifest_deps

    deps = parse_manifest_deps("cargo", '[dependencies]\ntokio = "1"\nserde = "1"\n')
    assert "tokio" in deps and "serde" in deps
    signals = _eco_signals(_eco_inspection(
        name="rust-svc",
        languages={"Rust": 50000},
        root_files=["Cargo.toml", "Cargo.lock"],
        ext_file_counts={".rs": 12},
        eco_manifest_deps=deps,
    ))
    by_skill = {s["canonical_name"]: s for s in signals}
    assert "Rust" in by_skill
    assert by_skill["Rust"]["signal_value"] == pytest.approx(0.85)


def test_github_python_pyproject_with_fastapi_and_pytest():
    """pyproject.toml deps feed the Python/REST/Testing detection (not just requirements.txt)."""
    from app.services.evidence.github import parse_manifest_deps

    deps = parse_manifest_deps("pyproject", '[project]\ndependencies = ["fastapi>=0.100", "pytest", "sqlalchemy"]\n')
    assert set(deps) == {"fastapi", "pytest", "sqlalchemy"}
    signals = _eco_signals(_eco_inspection(
        name="py-api",
        languages={"Python": 20000},
        root_files=["pyproject.toml"],
        ext_file_counts={".py": 6},
        eco_manifest_deps=deps,
        eco_python_deps=deps,
    ))
    by_skill = {s["canonical_name"]: s for s in signals}
    assert "Python" in by_skill
    assert "REST APIs" in by_skill  # fastapi
    assert "Testing" in by_skill  # pytest
    assert "DBMS" in by_skill  # sqlalchemy


def test_github_cpp_repo_with_cmake():
    """C++ sources + CMakeLists yield C++ implementation evidence."""
    signals = _eco_signals(_eco_inspection(
        name="engine",
        languages={"C++": 40000},
        root_files=["CMakeLists.txt", "README.md"],
        ext_file_counts={".cpp": 5, ".h": 4},
    ))
    by_skill = {s["canonical_name"]: s for s in signals}
    assert "C++" in by_skill
    assert by_skill["C++"]["signal_value"] >= 0.75


def test_github_csharp_csproj_with_xunit():
    """C# sources + csproj (xunit) yield C# and Testing evidence."""
    signals = _eco_signals(_eco_inspection(
        name="dotnet-app",
        languages={"C#": 25000},
        root_files=["app.sln"],
        ext_file_counts={".cs": 7},
        top_files=["Program.cs", "CalcTests.cs", "app.csproj"],
        eco_manifest_deps=["xunit", "microsoft.net.test.sdk"],
    ))
    by_skill = {s["canonical_name"]: s for s in signals}
    assert "C#" in by_skill
    assert by_skill["C#"]["signal_value"] >= 0.75
    assert "Testing" in by_skill


def test_github_rails_gemfile_maps_to_rest_apis():
    """Ruby web framework deps map to canonical REST APIs (no invented Ruby skill)."""
    from app.services.evidence.github import parse_manifest_deps

    deps = parse_manifest_deps("gemfile", 'source "https://rubygems.org"\ngem "rails"\ngem "pg"\n')
    assert "rails" in deps
    signals = _eco_signals(_eco_inspection(
        name="rails-app",
        root_files=["Gemfile"],
        ext_file_counts={".rb": 9},
        eco_manifest_deps=deps,
    ))
    by_skill = {s["canonical_name"]: s for s in signals}
    assert "REST APIs" in by_skill  # rails
    assert "PostgreSQL" in by_skill  # pg
    # Ruby itself has no canonical skill: must not invent one
    assert "Ruby" not in by_skill


def test_github_sql_terraform_k8s_and_jenkins_detected():
    """SQL files, .tf files, k8s manifests and Jenkinsfile each yield their canonical skill."""
    signals = _eco_signals(_eco_inspection(
        name="infra",
        ext_file_counts={".sql": 4, ".tf": 2},
        top_files=["schema.sql", "main.tf", "deployment.yaml", "Jenkinsfile"],
        has_k8s_manifests=True,
        k8s_manifest_count=1,
        has_ci_config=True,
    ))
    by_skill = {s["canonical_name"]: s for s in signals}
    assert "SQL" in by_skill
    assert "Terraform" in by_skill
    assert "Kubernetes" in by_skill
    assert by_skill["Kubernetes"]["signal_value"] == pytest.approx(0.60)  # config-level only
    assert "CI/CD" in by_skill
    assert "GitHub Actions" not in by_skill  # Jenkins is not GitHub Actions


def test_github_weak_go_footprint_capped():
    """One stray .go file with tiny bytes and no manifest stays weak (<=0.60)."""
    signals = _eco_signals(_eco_inspection(
        name="docs",
        languages={"Go": 300},
        root_files=["README.md"],
        ext_file_counts={".go": 1},
    ))
    by_skill = {s["canonical_name"]: s for s in signals}
    assert "Go" not in by_skill or by_skill["Go"]["signal_value"] <= 0.60
    if "Go" in by_skill:
        prof, _, _, _ = skill_engine.proficiency([by_skill["Go"]])
        assert prof <= 0.60
