from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime, timezone

from .base import EvidenceProvider, VerificationResult, ExtractedSignal, EvidenceDepth, VerificationStatus
from .url_utils import validate_platform_url, extract_username_from_path, LINKEDIN_HOSTS
from ..skill_taxonomy import normalize_skill

# LinkedIn claims are self-reported with low technical verification reliability
LINKEDIN_RELIABILITY = 0.40
CLAIM_SIGNAL_STRENGTH = 0.30


class LinkedInProvider(EvidenceProvider):
    """
    Evidence Provider for LinkedIn.
    Philosophical and Technical Grounding:
    - LinkedIn data consists of self-reported claims and professional profiles.
    - Does NOT bypass authentication walls or perform brittle unauthorized scraping.
    - Preserves profile URLs with 'unverified' or 'partially_verified' status.
    - Strictly limits signal reliability to 0.40 (self-reported) and depth to Level 1 (0.30).
    - Cannot outweigh verified code implementations or competitive contest facts.
    """

    @property
    def provider_name(self) -> str:
        return "linkedin"

    def can_handle(self, evidence: dict) -> bool:
        etype = (evidence.get("evidence_type") or "").lower()
        url = (evidence.get("source_url") or "").strip()

        if etype == "linkedin":
            if url:
                valid, _, _ = validate_platform_url(url, LINKEDIN_HOSTS)
                return valid
            return True

        if url:
            valid, _, _ = validate_platform_url(url, LINKEDIN_HOSTS)
            return valid

        return False

    def validate(self, evidence: dict) -> Tuple[bool, Optional[str]]:
        url = (evidence.get("source_url") or "").strip()
        if not url:
            return False, "LinkedIn profile URL required"
        valid, path, err = validate_platform_url(url, LINKEDIN_HOSTS)
        if not valid:
            return False, err
        username = extract_username_from_path(path or "", "linkedin")
        if not username:
            return False, "Could not extract LinkedIn handle from URL"
        return True, None

    async def verify(self, evidence: dict) -> VerificationResult:
        now = datetime.now(timezone.utc)
        url = (evidence.get("source_url") or "").strip()

        # 1. Deterministic mock fixture support
        if "mock_inspection" in evidence:
            return self._build_result_from_inspection(evidence["mock_inspection"], now)

        # 2. Host and format validation (reject lookalikes like linkedin.example.com)
        valid, path, err = validate_platform_url(url, LINKEDIN_HOSTS)
        if not valid:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Invalid LinkedIn URL or handle: {err}",
                provider=self.provider_name,
                raw_metadata={"raw_url": url},
                verified_at=now,
            )

        username = extract_username_from_path(path or "", "linkedin")
        if not username:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message="Could not extract LinkedIn profile identifier from provided URL.",
                provider=self.provider_name,
                raw_metadata={"raw_url": url},
                verified_at=now,
            )

        # 3. Handle claims in evidence metadata if provided (e.g. self-reported skills)
        meta = evidence.get("metadata") or {}
        claimed_skills = meta.get("skills") or meta.get("claimed_skills") or []
        if isinstance(claimed_skills, str):
            claimed_skills = [s.strip() for s in claimed_skills.split(",") if s.strip()]

        inspection = {
            "username": username,
            "profile_url": f"https://www.linkedin.com/in/{username}",
            "claimed_skills": claimed_skills,
        }

        return self._build_result_from_inspection(inspection, now)

    def _build_result_from_inspection(self, facts: dict, verified_at: datetime) -> VerificationResult:
        username = facts.get("username") or "profile"
        claimed_skills = facts.get("claimed_skills") or []

        facts_list = [
            f"LinkedIn profile link recorded: linkedin.com/in/{username}",
            "Source classified as self-reported professional claims (unverified technical implementation)",
        ]

        signals: List[ExtractedSignal] = []

        # Self-reported skill claims produce low-strength Level 1 signals with 0.40 reliability
        for raw_s in claimed_skills:
            canonical = normalize_skill(str(raw_s))
            if canonical:
                signals.append(
                    ExtractedSignal(
                        skill=canonical,
                        signal_strength=CLAIM_SIGNAL_STRENGTH,
                        depth=EvidenceDepth.LEVEL_1_MENTION,
                        reason=f"Skill '{canonical}' listed as self-reported claim on LinkedIn profile '{username}'.",
                        source_reliability=LINKEDIN_RELIABILITY,
                        metadata={"self_reported": True, "platform": "linkedin"},
                    )
                )

        status = VerificationStatus.PARTIALLY_VERIFIED if signals else VerificationStatus.UNVERIFIED
        msg = (
            f"LinkedIn profile 'in/{username}' recorded as self-reported supporting evidence. "
            f"Technical claims are unverified without third-party work artifacts."
        )

        return VerificationResult(
            status=status,
            message=msg,
            provider=self.provider_name,
            signals=signals,
            raw_metadata=facts,
            profile={"username": username},
            facts=facts_list,
            warnings=["LinkedIn profile is self-reported and not independently verified against source code"],
            verified_at=verified_at,
        )

    async def extract_signals(self, evidence: dict) -> List[ExtractedSignal]:
        res = await self.verify(evidence)
        return res.signals
