from typing import List, Dict, Optional, Any, Set
from datetime import datetime, timezone

from .base import EvidenceProvider, VerificationResult, ExtractedSignal, VerificationStatus
from ..evidence_weights import reliability as source_reliability
from .github import GitHubProvider, parse_github_url
from .leetcode import LeetCodeProvider
from .codeforces import CodeforcesProvider
from .kaggle import KaggleProvider
from .linkedin import LinkedInProvider
from .url_utils import (
    validate_platform_url,
    extract_username_from_path,
    GITHUB_HOSTS,
    LEETCODE_HOSTS,
    CODEFORCES_HOSTS,
    KAGGLE_HOSTS,
    LINKEDIN_HOSTS,
)

CACHE_DURATION_HOURS = 24.0


def is_cache_valid(verified_at_str: Optional[str]) -> bool:
    """Check if previous verification is within the freshness cache window."""
    if not verified_at_str:
        return False
    try:
        verified_dt = datetime.fromisoformat(verified_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_hours = (now - verified_dt).total_seconds() / 3600.0
        return 0 <= age_hours < CACHE_DURATION_HOURS
    except Exception:
        return False


def get_evidence_dedup_key(ev: dict) -> str:
    """
    Generate normalized deduplication key for an evidence item
    to prevent double counting identical repositories or profiles across platforms.
    """
    etype = (ev.get("evidence_type") or "").lower()
    url = (ev.get("source_url") or "").strip()

    if etype == "github" or "github.com" in url.lower():
        owner, repo, is_prof = parse_github_url(url)
        if owner and repo and not is_prof:
            return f"github:{owner.lower()}/{repo.lower()}"
        elif owner:
            return f"github:{owner.lower()}"

    for plat, hosts in [
        ("leetcode", LEETCODE_HOSTS),
        ("codeforces", CODEFORCES_HOSTS),
        ("kaggle", KAGGLE_HOSTS),
        ("linkedin", LINKEDIN_HOSTS),
    ]:
        if etype == plat or any(h in url.lower() for h in hosts):
            valid, path, _ = validate_platform_url(url, hosts)
            if valid and path:
                user = extract_username_from_path(path, plat)
                if user:
                    return f"{plat}:{user.lower()}"

    return url.lower().strip() if url else (ev.get("id") or "unknown")


class EvidenceManager:
    """
    Centralized Registry and Orchestrator for Evidence Intelligence providers.
    Provides:
    - Provider discovery and routing with domain/SSRF validation
    - Deduplication across all evidence sources
    - Simple database-backed metadata caching for external API freshness
    - Safe batch signal extraction
    """

    def __init__(self):
        self.providers: List[EvidenceProvider] = [
            GitHubProvider(),
            LeetCodeProvider(),
            CodeforcesProvider(),
            KaggleProvider(),
            LinkedInProvider(),
        ]

    def get_provider(self, evidence: dict) -> Optional[EvidenceProvider]:
        """Find the matching provider for an evidence item."""
        for p in self.providers:
            if p.can_handle(evidence):
                return p
        return None

    def get_provider_or_raise(self, evidence: dict) -> EvidenceProvider:
        """Find matching provider or raise ValueError if unsupported or malicious."""
        provider = self.get_provider(evidence)
        if not provider:
            src = evidence.get("source_url") or evidence.get("evidence_type") or "unknown"
            raise ValueError(f"No provider registered for evidence source or type: '{src}'")
        return provider

    async def verify_evidence(self, evidence: dict, force_refresh: bool = False) -> VerificationResult:
        """
        Verify an evidence item using its appropriate provider.
        Reuses cached result if verified within the freshness threshold,
        unless force_refresh is requested.
        """
        meta = evidence.get("metadata") or {}
        v_status = evidence.get("verification_status") or meta.get("verification_status")
        verified_at = evidence.get("verified_at") or meta.get("verified_at")

        # Reuse cache if valid and not testing offline mocks
        if not force_refresh and "mock_inspection" not in evidence:
            if v_status in (VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_VERIFIED):
                if is_cache_valid(verified_at):
                    cached_signals = meta.get("verified_signals") or []
                    # Source reliability is re-derived from the central weight
                    # config, never read back from the cached copy: a stored
                    # signal must not keep a pre-recalibration weight alive.
                    cached_provider = (
                        evidence.get("provider")
                        or meta.get("provider")
                        or (evidence.get("evidence_type") or "")
                    )
                    cached_reliability = source_reliability(cached_provider)
                    signals_objs = [
                        ExtractedSignal(
                            skill=s.get("skill") or s.get("canonical_name", ""),
                            signal_strength=float(s.get("signal_strength", s.get("signal_value", 0.5))),
                            depth=int(s.get("depth", 2)),
                            reason=s.get("reason") or s.get("explanation", ""),
                            source_reliability=cached_reliability,
                            metadata=s.get("metadata") or {},
                        )
                        for s in cached_signals
                    ]
                    return VerificationResult(
                        status=v_status,
                        message=evidence.get("verification_message") or meta.get("verification_message") or "Verified (cached)",
                        provider=evidence.get("provider") or meta.get("provider") or "cached",
                        signals=signals_objs,
                        raw_metadata=meta.get("inspection") or {},
                        profile=meta.get("profile") or {},
                        facts=meta.get("facts") or [],
                        warnings=meta.get("warnings") or [],
                        verified_at=datetime.fromisoformat(verified_at.replace("Z", "+00:00")) if verified_at else None,
                    )

        provider = self.get_provider(evidence)
        if not provider:
            return VerificationResult(
                status=VerificationStatus.UNVERIFIED,
                message=f"No automated inspector configured for evidence type '{evidence.get('evidence_type')}'.",
                provider="generic",
                signals=[],
                raw_metadata={},
            )

        return await provider.verify(evidence)

    async def extract_signals_from_evidence_list(self, evidence_list: List[dict]) -> List[dict]:
        """
        Extract verified technical signals across all student evidence items.
        Deduplication rule: If the same repository or profile is submitted multiple times,
        it is only processed once to prevent artificial confidence inflation.
        """
        seen_keys: Set[str] = set()
        all_signals: List[dict] = []

        for ev in evidence_list:
            dedup_key = get_evidence_dedup_key(ev)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            # If evidence has pre-verified signals in metadata, use them
            meta = ev.get("metadata") or {}
            verified_signals = meta.get("verified_signals")
            status = ev.get("verification_status") or meta.get("verification_status")

            # Verified and partially_verified evidence generates substantive signals
            if status in (VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_VERIFIED) and isinstance(verified_signals, list):
                for sig in verified_signals:
                    all_signals.append({
                        **sig,
                        "evidence_id": ev.get("id"),
                    })
                continue

            # Otherwise verify and extract dynamically
            provider = self.get_provider(ev)
            if provider:
                res = await provider.verify(ev)
                if res.status in (VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_VERIFIED):
                    for sig in res.signals:
                        all_signals.append({
                            **sig.to_dict(),
                            "evidence_id": ev.get("id"),
                        })

        return all_signals


# Singleton instance
evidence_manager = EvidenceManager()
