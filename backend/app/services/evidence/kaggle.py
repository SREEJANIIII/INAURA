import re
import httpx
from typing import List, Dict, Tuple, Optional, Any, Set
from datetime import datetime, timezone

from .base import EvidenceProvider, VerificationResult, ExtractedSignal, EvidenceDepth, VerificationStatus
from .url_utils import validate_platform_url, extract_username_from_path, KAGGLE_HOSTS
from ..evidence_weights import reliability as source_reliability
from ..skill_taxonomy import normalize_skill

KAGGLE_RELIABILITY = source_reliability("kaggle")

# Calibrated multipliers for Kaggle tiers
TIER_STRENGTH_MAP: Dict[str, float] = {
    "novice": 0.40,
    "contributor": 0.55,
    "expert": 0.72,
    "master": 0.84,
    "grandmaster": 0.90,
}


class KaggleProvider(EvidenceProvider):
    """
    Evidence Intelligence Provider for Kaggle.
    Extracts verifiable data science and ML facts:
    - User tier (Novice, Contributor, Expert, Master, Grandmaster)
    - Public notebook implementations & used libraries (Pandas, NumPy, Scikit-Learn, PyTorch, etc.)
    - Competition entries and medals
    - Public datasets
    Scopes evidence to:
    - Machine Learning
    - Data Analysis
    - Python and Data Science stack (Pandas, NumPy, Scikit-Learn, PyTorch, TensorFlow)
    """

    @property
    def provider_name(self) -> str:
        return "kaggle"

    def can_handle(self, evidence: dict) -> bool:
        etype = (evidence.get("evidence_type") or "").lower()
        url = (evidence.get("source_url") or "").strip()

        if etype == "kaggle":
            if url:
                valid, _, _ = validate_platform_url(url, KAGGLE_HOSTS)
                return valid
            return True

        if url:
            valid, _, _ = validate_platform_url(url, KAGGLE_HOSTS)
            return valid

        return False

    def validate(self, evidence: dict) -> Tuple[bool, Optional[str]]:
        url = (evidence.get("source_url") or "").strip()
        if not url:
            return False, "Kaggle URL or username required"
        valid, path, err = validate_platform_url(url, KAGGLE_HOSTS)
        if not valid:
            return False, err
        username = extract_username_from_path(path or "", "kaggle")
        if not username:
            return False, "Could not extract Kaggle username from URL"
        return True, None

    async def verify(self, evidence: dict) -> VerificationResult:
        now = datetime.now(timezone.utc)
        url = (evidence.get("source_url") or "").strip()

        # 1. Deterministic offline mock inspection support
        if "mock_inspection" in evidence:
            return self._build_result_from_inspection(evidence["mock_inspection"], now)

        # 2. Validate input and extract username
        valid, path, err = validate_platform_url(url, KAGGLE_HOSTS)
        if not valid:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Invalid Kaggle URL or handle: {err}",
                provider=self.provider_name,
                raw_metadata={"raw_url": url},
                verified_at=now,
            )

        username = extract_username_from_path(path or "", "kaggle")
        if not username:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message="Could not extract Kaggle username from provided URL.",
                provider=self.provider_name,
                raw_metadata={"raw_url": url},
                verified_at=now,
            )

        # 3. Check public Kaggle profile availability
        profile_url = f"https://www.kaggle.com/{username}"
        headers = {
            "User-Agent": "INAURA-Evidence-Intelligence/1.0",
        }

        try:
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
                resp = await client.get(profile_url, headers=headers)

                if resp.status_code == 404:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        message=f"Kaggle profile '{username}' does not exist or has been removed.",
                        provider=self.provider_name,
                        raw_metadata={"username": username, "http_status": 404},
                        verified_at=now,
                    )

                if resp.status_code != 200:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        message=f"Kaggle profile unreachable (HTTP status {resp.status_code}).",
                        provider=self.provider_name,
                        raw_metadata={"username": username, "http_status": resp.status_code},
                        verified_at=now,
                    )

                html = resp.text

                # Robust regex extraction of public stats rather than naive keyword search
                tier_match = re.search(r'"tier(?:Name)?"\s*:\s*"([a-zA-Z]+)"', html, re.IGNORECASE)
                tier = tier_match.group(1).lower() if tier_match else "novice"
                if tier not in TIER_STRENGTH_MAP:
                    tier = "novice"

                code_match = re.search(r'"(?:codeCount|totalNotebooks|scriptsCount)"\s*:\s*(\d+)', html)
                notebooks_count = int(code_match.group(1)) if code_match else 0

                comp_match = re.search(r'"(?:competitionsCount|totalCompetitions)"\s*:\s*(\d+)', html)
                competitions_count = int(comp_match.group(1)) if comp_match else 0

                dataset_match = re.search(r'"(?:datasetsCount|totalDatasets)"\s*:\s*(\d+)', html)
                datasets_count = int(dataset_match.group(1)) if dataset_match else 0

                inspection = {
                    "username": username,
                    "profile_reachable": True,
                    "tier": tier,
                    "notebooks_count": notebooks_count,
                    "competitions_count": competitions_count,
                    "datasets_count": datasets_count,
                }
                return self._build_result_from_inspection(inspection, now)

        except (httpx.RequestError, Exception) as e:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Network connection to Kaggle failed: {str(e)[:100]}",
                provider=self.provider_name,
                raw_metadata={"username": username, "error": str(e)},
                verified_at=now,
                warnings=["Network timeout or unreachable Kaggle endpoint"],
            )

    def _build_result_from_inspection(self, facts: dict, verified_at: datetime) -> VerificationResult:
        username = facts.get("username") or "user"
        tier = str(facts.get("tier", "novice")).lower()
        if tier not in TIER_STRENGTH_MAP:
            tier = "novice"

        # Structured notebooks extraction
        raw_notebooks = facts.get("notebooks")
        detected_libraries: Set[str] = set()
        if isinstance(raw_notebooks, list):
            notebooks = len(raw_notebooks)
            for nb in raw_notebooks:
                if isinstance(nb, dict):
                    libs = nb.get("libraries") or nb.get("technologies") or nb.get("imports") or []
                    for lib in libs:
                        c = normalize_skill(str(lib))
                        if c:
                            detected_libraries.add(c)
        else:
            notebooks = int(facts.get("notebooks_count", 0))

        # Structured competitions extraction
        raw_competitions = facts.get("competitions")
        if isinstance(raw_competitions, list):
            competitions = len(raw_competitions)
        else:
            competitions = int(facts.get("competitions_count", 0))

        datasets = int(facts.get("datasets_count", 0))
        medals = facts.get("notebooks_medals") or facts.get("competitions_medals") or {}

        facts_list = [
            f"Kaggle tier '{tier.capitalize()}'",
            f"Public activity: {notebooks} notebooks, {competitions} competitions, {datasets} datasets",
        ]

        # Check for zero activity
        if notebooks == 0 and competitions == 0 and datasets == 0 and tier == "novice":
            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                message=f"Verified Kaggle profile '{username}', but no public notebooks or competitions found.",
                provider=self.provider_name,
                signals=[],
                raw_metadata=facts,
                profile={"username": username, "tier": tier},
                facts=facts_list,
                warnings=["Profile shows no public data science artifacts or competition submissions"],
                verified_at=verified_at,
            )

        # Calibrate depth and strength
        base_strength = TIER_STRENGTH_MAP.get(tier, 0.50)

        # Bonus for actual public notebooks/competitions
        if notebooks >= 5 or competitions >= 3 or bool(medals):
            depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION if tier in ("contributor", "expert") else EvidenceDepth.LEVEL_4_SUBSTANTIAL
            strength = min(0.88, base_strength + 0.05)
        elif notebooks >= 1 or competitions >= 1:
            depth = EvidenceDepth.LEVEL_2_CONFIG
            strength = base_strength
        else:
            depth = EvidenceDepth.LEVEL_1_MENTION
            strength = 0.40

        strength = round(strength, 2)
        signals: List[ExtractedSignal] = []

        # 1. Machine Learning (requires at least 1 notebook, competition, or expert+ tier)
        if notebooks > 0 or competitions > 0 or tier in ("expert", "master", "grandmaster"):
            ml_canonical = normalize_skill("Machine Learning") or "Machine Learning"
            signals.append(
                ExtractedSignal(
                    skill=ml_canonical,
                    signal_strength=strength,
                    depth=depth,
                    reason=(
                        f"Kaggle profile '{username}' ({tier}) demonstrates verified ML practice "
                        f"across {notebooks} public notebooks and {competitions} competitions."
                    ),
                    source_reliability=KAGGLE_RELIABILITY,
                    metadata={"tier": tier, "notebooks": notebooks, "competitions": competitions},
                )
            )

        # 2. Data Analysis (notebooks or datasets)
        if notebooks > 0 or datasets > 0:
            da_canonical = normalize_skill("Data Analysis") or "Data Analysis"
            da_strength = round(min(0.85, strength * 0.95), 2)
            signals.append(
                ExtractedSignal(
                    skill=da_canonical,
                    signal_strength=da_strength,
                    depth=depth,
                    reason=f"Published {notebooks} data notebooks and {datasets} datasets on Kaggle.",
                    source_reliability=KAGGLE_RELIABILITY,
                    metadata={"notebooks": notebooks, "datasets": datasets},
                )
            )

        # 3. Python & Scientific Stack (if notebooks present)
        if notebooks > 0:
            py_canonical = normalize_skill("Python") or "Python"
            signals.append(
                ExtractedSignal(
                    skill=py_canonical,
                    signal_strength=round(min(0.80, strength * 0.90), 2),
                    depth=depth,
                    reason=f"Python code implementation verified across {notebooks} Kaggle notebooks.",
                    source_reliability=KAGGLE_RELIABILITY,
                    metadata={"notebooks": notebooks},
                )
            )

        # 4. Detected Libraries in Public Notebooks (Pandas, NumPy, Scikit-Learn, PyTorch, etc.)
        for lib in sorted(detected_libraries):
            lib_strength = round(min(0.85, strength * 0.92), 2)
            signals.append(
                ExtractedSignal(
                    skill=lib,
                    signal_strength=lib_strength,
                    depth=EvidenceDepth.LEVEL_3_IMPLEMENTATION,
                    reason=f"Verified data science implementation using {lib} in Kaggle public notebooks.",
                    source_reliability=KAGGLE_RELIABILITY,
                    metadata={"library": lib, "platform": "kaggle"},
                )
            )

        summary_msg = f"Verified Kaggle profile '{username}' ({tier}): {notebooks} notebooks, {competitions} competitions."

        return VerificationResult(
            status=VerificationStatus.VERIFIED,
            message=summary_msg,
            provider=self.provider_name,
            signals=signals,
            raw_metadata=facts,
            profile={"username": username, "tier": tier},
            facts=facts_list,
            verified_at=verified_at,
        )

    async def extract_signals(self, evidence: dict) -> List[ExtractedSignal]:
        res = await self.verify(evidence)
        return res.signals
