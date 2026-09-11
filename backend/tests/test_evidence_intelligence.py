import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

from app.services.evidence.base import (
    EvidenceDepth,
    VerificationStatus,
    ExtractedSignal,
    VerificationResult,
)
from app.services.evidence.url_utils import (
    validate_platform_url,
    extract_username_from_path,
    is_private_ip,
    GITHUB_HOSTS,
    LEETCODE_HOSTS,
    CODEFORCES_HOSTS,
    KAGGLE_HOSTS,
    LINKEDIN_HOSTS,
)
from app.services.evidence.github import GitHubProvider, parse_github_url
from app.services.evidence.leetcode import LeetCodeProvider
from app.services.evidence.codeforces import CodeforcesProvider
from app.services.evidence.kaggle import KaggleProvider
from app.services.evidence.linkedin import LinkedInProvider
from app.services.evidence.manager import (
    EvidenceManager,
    evidence_manager,
    get_evidence_dedup_key,
    is_cache_valid,
)
from app.services import evidence_service
from app.services import signal_extractor as se
from app.services import skill_engine


# ===========================================================================
# 1. PROVIDER SELECTION & DOMAIN VALIDATION TESTS
# ===========================================================================

def test_provider_selection_all_platforms():
    mgr = EvidenceManager()

    # GitHub
    gh = {"evidence_type": "github", "source_url": "https://github.com/octocat/Hello-World"}
    assert isinstance(mgr.get_provider_or_raise(gh), GitHubProvider)

    # LeetCode
    lc = {"evidence_type": "leetcode", "source_url": "https://leetcode.com/u/algorithms_master"}
    assert isinstance(mgr.get_provider_or_raise(lc), LeetCodeProvider)

    # Codeforces
    cf = {"evidence_type": "codeforces", "source_url": "https://codeforces.com/profile/tourist"}
    assert isinstance(mgr.get_provider_or_raise(cf), CodeforcesProvider)

    # Kaggle
    kg = {"evidence_type": "kaggle", "source_url": "https://kaggle.com/grandmaster"}
    assert isinstance(mgr.get_provider_or_raise(kg), KaggleProvider)

    # LinkedIn
    li = {"evidence_type": "linkedin", "source_url": "https://linkedin.com/in/swe-candidate"}
    assert isinstance(mgr.get_provider_or_raise(li), LinkedInProvider)


def test_reject_lookalike_and_malicious_domains():
    mgr = EvidenceManager()

    malicious_urls = [
        "https://leetcode.fake.com/u/hacker",
        "https://codeforces.attacker.org/profile/fake",
        "https://kaggle.phishing.io/user",
        "https://linkedin.example.com/in/scam",
        "https://github.evil.com/owner/repo",
    ]

    for bad_url in malicious_urls:
        ev = {"source_url": bad_url}
        assert mgr.get_provider(ev) is None
        with pytest.raises(ValueError):
            mgr.get_provider_or_raise(ev)


def test_ssrf_and_private_network_rejection():
    mgr = EvidenceManager()

    ssrf_targets = [
        "http://localhost:8000/api",
        "http://127.0.0.1/admin",
        "http://192.168.1.100/internal",
        "http://10.0.0.1/secret",
        "http://172.16.0.5/private",
        "file:///etc/passwd",
        "gopher://127.0.0.1:25",
    ]

    for target in ssrf_targets:
        valid, _, err = validate_platform_url(target, LEETCODE_HOSTS)
        assert valid is False
        assert err is not None


# ===========================================================================
# 2. LEETCODE PROVIDER TESTS
# ===========================================================================

def test_leetcode_facts_and_signals_substantial_activity():
    async def _test():
        provider = LeetCodeProvider()
        ev = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/dsa_expert",
            "mock_inspection": {
                "username": "dsa_expert",
                "total_solved": 320,
                "easy_solved": 50,
                "medium_solved": 210,
                "hard_solved": 60,
                "contest_rating": 1850.0,
                "contest_ranking": 1240,
                "top_percentage": 6.5,
                "contests_attended": 18,
                "topics": {
                    "Arrays & Strings": 50,
                    "Linked Lists": 25,
                    "Stacks & Queues": 25,
                    "Trees": 45,
                    "Graphs": 45,
                    "Searching & Sorting": 35,
                    "Dynamic Programming": 50,
                    "Greedy": 25,
                    "Backtracking": 20,
                },
            }
        }
        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED
        assert "320 problems" in res.message
        assert len(res.facts) >= 2

        skills = {s.skill: s for s in res.signals}
        # Scoped strictly to algorithmic skills
        assert "Data Structures & Algorithms" in skills
        assert "Problem Solving" in skills
        assert "Competitive Programming" in skills
        assert skills["Data Structures & Algorithms"].signal_strength >= 0.78
        assert skills["Data Structures & Algorithms"].depth == EvidenceDepth.LEVEL_4_SUBSTANTIAL

        # Crucial negative assertion: LeetCode MUST NOT generate unrelated SWE skills
        assert "React" not in skills
        assert "Docker" not in skills
        assert "AWS" not in skills
        assert "Backend Development" not in skills

    asyncio.run(_test())


def test_leetcode_empty_activity_produces_zero_signals():
    async def _test():
        provider = LeetCodeProvider()
        ev = {
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/empty_user",
            "mock_inspection": {
                "username": "empty_user",
                "total_solved": 0,
                "easy_solved": 0,
                "medium_solved": 0,
                "hard_solved": 0,
                "contest_rating": 0.0,
                "contests_attended": 0,
            }
        }
        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED
        assert len(res.signals) == 0

    asyncio.run(_test())


def test_leetcode_network_failure_handling():
    async def _test():
        provider = LeetCodeProvider()
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = Exception("Connection refused")
            ev = {"evidence_type": "leetcode", "source_url": "https://leetcode.com/u/alice"}
            res = await provider.verify(ev)
            assert res.status == VerificationStatus.FAILED
            assert "failed" in res.message.lower()
            assert len(res.signals) == 0

    asyncio.run(_test())


# ===========================================================================
# 3. CODEFORCES PROVIDER TESTS
# ===========================================================================

def test_codeforces_expert_rating_and_signals():
    async def _test():
        provider = CodeforcesProvider()
        ev = {
            "evidence_type": "codeforces",
            "source_url": "https://codeforces.com/profile/tourist_lite",
            "mock_inspection": {
                "handle": "tourist_lite",
                "rating": 1720,
                "max_rating": 1780,
                "rank": "expert",
                "max_rank": "expert",
                "contest_count": 45,
            }
        }
        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED
        assert "1720" in res.message

        skills = {s.skill: s for s in res.signals}
        assert "Competitive Programming" in skills
        assert "Data Structures & Algorithms" in skills
        assert "Problem Solving" in skills
        assert skills["Competitive Programming"].signal_strength >= 0.75
        assert skills["Competitive Programming"].depth in (EvidenceDepth.LEVEL_3_IMPLEMENTATION, EvidenceDepth.LEVEL_4_SUBSTANTIAL)

        # Negative scoping
        assert "React" not in skills
        assert "Docker" not in skills

    asyncio.run(_test())


def test_codeforces_unrated_user_produces_zero_signals():
    async def _test():
        provider = CodeforcesProvider()
        ev = {
            "evidence_type": "codeforces",
            "source_url": "https://codeforces.com/profile/inactive",
            "mock_inspection": {
                "handle": "inactive",
                "rating": 0,
                "max_rating": 0,
                "rank": "unrated",
                "contest_count": 0,
            }
        }
        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED
        assert len(res.signals) == 0

    asyncio.run(_test())


# ===========================================================================
# 4. KAGGLE PROVIDER TESTS
# ===========================================================================

def test_kaggle_expert_with_notebooks_and_competitions():
    async def _test():
        provider = KaggleProvider()
        ev = {
            "evidence_type": "kaggle",
            "source_url": "https://kaggle.com/ml_wizard",
            "mock_inspection": {
                "username": "ml_wizard",
                "tier": "expert",
                "notebooks_count": 12,
                "competitions_count": 5,
                "datasets_count": 3,
                "notebooks_medals": {"silver": 2, "bronze": 4},
            }
        }
        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED

        skills = {s.skill: s for s in res.signals}
        assert "Machine Learning" in skills
        assert "Data Analysis" in skills
        assert "Python" in skills
        assert skills["Machine Learning"].signal_strength >= 0.72
        assert skills["Machine Learning"].depth in (EvidenceDepth.LEVEL_3_IMPLEMENTATION, EvidenceDepth.LEVEL_4_SUBSTANTIAL)

    asyncio.run(_test())


def test_kaggle_novice_zero_artifacts_produces_zero_signals():
    async def _test():
        provider = KaggleProvider()
        ev = {
            "evidence_type": "kaggle",
            "source_url": "https://kaggle.com/empty_learner",
            "mock_inspection": {
                "username": "empty_learner",
                "tier": "novice",
                "notebooks_count": 0,
                "competitions_count": 0,
                "datasets_count": 0,
            }
        }
        res = await provider.verify(ev)
        assert res.status == VerificationStatus.VERIFIED
        assert len(res.signals) == 0

    asyncio.run(_test())


# ===========================================================================
# 5. LINKEDIN PROVIDER TESTS
# ===========================================================================

def test_linkedin_remains_unverified_supporting_evidence():
    async def _test():
        provider = LinkedInProvider()
        ev = {
            "evidence_type": "linkedin",
            "source_url": "https://linkedin.com/in/student-candidate",
        }
        res = await provider.verify(ev)
        # LinkedIn does not fake full verification
        assert res.status == VerificationStatus.UNVERIFIED
        assert "self-reported" in res.message.lower()
        assert len(res.signals) == 0

    asyncio.run(_test())


def test_linkedin_claims_have_low_reliability_and_cannot_outweigh_implementation():
    async def _test():
        provider = LinkedInProvider()
        ev = {
            "evidence_type": "linkedin",
            "source_url": "https://linkedin.com/in/student-candidate",
            "metadata": {
                "claimed_skills": ["Docker", "React", "AWS"]
            }
        }
        res = await provider.verify(ev)
        assert res.status == VerificationStatus.PARTIALLY_VERIFIED
        
        for sig in res.signals:
            # Self-reported claims must have low reliability (0.40) and low strength (0.30)
            assert sig.source_reliability == 0.40
            assert sig.signal_strength <= 0.35
            assert sig.depth == EvidenceDepth.LEVEL_1_MENTION

    asyncio.run(_test())


# ===========================================================================
# 6. CROSS-PLATFORM AGGREGATION & CONFIDENCE TESTS
# ===========================================================================

def test_cross_platform_dsa_confidence_increase():
    # Student with LeetCode + Codeforces + GitHub Algorithm Repo
    evidence = [
        {
            "id": "ev-lc",
            "evidence_type": "leetcode",
            "source_url": "https://leetcode.com/u/candidate",
            "mock_inspection": {
                "username": "candidate",
                "total_solved": 250,
                "medium_solved": 180,
                "hard_solved": 30,
                "contest_rating": 1720,
            }
        },
        {
            "id": "ev-cf",
            "evidence_type": "codeforces",
            "source_url": "https://codeforces.com/profile/candidate",
            "mock_inspection": {
                "handle": "candidate",
                "rating": 1550,
                "max_rating": 1600,
                "rank": "specialist",
                "contest_count": 25,
            }
        },
    ]

    signals = se.extract_signals(evidence, [], [])
    dsa_signals = [s for s in signals if s["canonical_name"] == "Data Structures & Algorithms"]
    assert len(dsa_signals) == 2

    # Verify Skill Engine aggregation
    prof, ev_weight, ev_count, _ = skill_engine.proficiency(dsa_signals)
    sources = len(set(s.get("source", s.get("source_type")) for s in dsa_signals))
    conf, _, _ = skill_engine.confidence(ev_weight, sources)

    # 1. Proficiency stays bounded in [0.0, 1.0]
    assert 0.0 <= prof <= 1.0
    # 2. Confidence is boosted by having multiple verified platform sources
    assert sources == 2
    assert conf > 0.55


def test_verified_github_outweighs_linkedin_claim():
    # Student claims Docker on LinkedIn, and implements Docker on GitHub
    linkedin_ev = {
        "id": "ev-li",
        "evidence_type": "linkedin",
        "source_url": "https://linkedin.com/in/dev",
        "mock_inspection": {
            "username": "dev",
            "claimed_skills": ["Docker"],
        }
    }
    github_ev = {
        "id": "ev-gh",
        "evidence_type": "github",
        "source_url": "https://github.com/dev/microservices",
        "mock_inspection": {
            "name": "microservices",
            "root_files": ["Dockerfile", "docker-compose.yml"],
            "languages": {"Python": 5000},
        }
    }

    signals = se.extract_signals([linkedin_ev, github_ev], [], [])
    docker_signals = [s for s in signals if s["canonical_name"] == "Docker"]
    assert len(docker_signals) == 2

    gh_sig = next(s for s in docker_signals if s.get("source") == "github")
    li_sig = next(s for s in docker_signals if s.get("source") == "linkedin")

    # GitHub SUPPORTING (0.40 after the 2026-09-11 recalibration): far below
    # LeetCode/Codeforces/Kaggle (0.85) and INAURA assessment (0.95), and now
    # level with LinkedIn's weight — the implementation *signal strength*, not
    # the source weight, is what still separates them.
    assert gh_sig["source_reliability"] == 0.40
    assert gh_sig["signal_strength"] >= 0.70
    assert li_sig["source_reliability"] == 0.40
    assert li_sig["signal_strength"] <= 0.35

    # Implementation evidence still outweighs a LinkedIn claim: equal source
    # weights, but the GitHub signal strength is much higher.
    prof, _, _, _ = skill_engine.proficiency(docker_signals)
    assert prof > 0.50
    assert prof > li_sig["signal_strength"]


# ===========================================================================
# 7. PROVIDER FAILURE ISOLATION TESTS
# ===========================================================================

def test_failure_isolation_analysis_proceeds_with_available_evidence():
    # Even if Codeforces verification fails (e.g. timeout / network down),
    # GitHub and LeetCode evidence still verify and produce signals.
    evidence_items = [
        {
            "id": "ev-gh",
            "evidence_type": "github",
            "source_url": "https://github.com/dev/web",
            "mock_inspection": {
                "name": "web",
                "root_files": ["package.json"],
                "package_json_deps": ["react", "typescript"],
            }
        },
        {
            "id": "ev-cf-failed",
            "evidence_type": "codeforces",
            "source_url": "https://codeforces.com/profile/timeout_user",
            "verification_status": "failed",
            "verification_message": "Network connection to Codeforces failed: timeout",
        }
    ]

    signals = se.extract_signals(evidence_items, [], [])
    # GitHub signals extracted successfully
    react_signals = [s for s in signals if s["canonical_name"] == "React"]
    assert len(react_signals) == 1

    # Failed Codeforces produces 0 signals without crashing
    cf_signals = [s for s in signals if s.get("source") == "codeforces"]
    assert len(cf_signals) == 0


# ===========================================================================
# 8. CACHING AND FRESHNESS TESTS
# ===========================================================================

def test_evidence_freshness_cache_validity():
    now = datetime.now(timezone.utc)

    # 2 hours ago is fresh
    fresh_time = (now - timedelta(hours=2)).isoformat()
    assert is_cache_valid(fresh_time) is True

    # 48 hours ago is stale
    stale_time = (now - timedelta(hours=48)).isoformat()
    assert is_cache_valid(stale_time) is False

    # None is invalid
    assert is_cache_valid(None) is False


def test_evidence_deduplication_across_platforms():
    k1 = get_evidence_dedup_key({"evidence_type": "leetcode", "source_url": "https://leetcode.com/u/JOHN_DOE/"})
    k2 = get_evidence_dedup_key({"evidence_type": "leetcode", "source_url": "leetcode.com/john_doe"})
    assert k1 == k2 == "leetcode:john_doe"

    cf1 = get_evidence_dedup_key({"evidence_type": "codeforces", "source_url": "https://codeforces.com/profile/tourist"})
    cf2 = get_evidence_dedup_key({"evidence_type": "codeforces", "source_url": "tourist"})
    assert cf1 == cf2 == "codeforces:tourist"
