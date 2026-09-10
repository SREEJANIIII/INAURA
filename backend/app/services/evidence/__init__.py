from .base import EvidenceProvider, VerificationStatus, VerificationResult, ExtractedSignal, EvidenceDepth
from .github import GitHubProvider
from .leetcode import LeetCodeProvider
from .codeforces import CodeforcesProvider
from .kaggle import KaggleProvider
from .linkedin import LinkedInProvider
from .manager import EvidenceManager, evidence_manager
from .url_utils import validate_platform_url

__all__ = [
    "EvidenceProvider",
    "VerificationStatus",
    "VerificationResult",
    "ExtractedSignal",
    "EvidenceDepth",
    "GitHubProvider",
    "LeetCodeProvider",
    "CodeforcesProvider",
    "KaggleProvider",
    "LinkedInProvider",
    "EvidenceManager",
    "evidence_manager",
    "validate_platform_url",
]
