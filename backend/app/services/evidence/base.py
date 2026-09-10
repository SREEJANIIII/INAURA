from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Bumped whenever evidence extraction changes in a way that makes previously
# stored `verified_signals` stale. The analysis pipeline re-verifies evidence
# recorded under an older version so live runs never serve outdated signals.
# 2: deep GitHub repository-content evidence (full pagination + content stage).
EVIDENCE_PIPELINE_VERSION = 2


class VerificationStatus:
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    FAILED = "failed"


class EvidenceDepth:
    """
    Evidence Depth Levels:
    - LEVEL_0 (0.0): Raw URL only — no inspected repository or verified content.
    - LEVEL_1 (0.40): Textual mention in README or metadata description.
    - LEVEL_2 (0.60): Configuration or dependency files detected (package.json, Dockerfile, requirements.txt).
    - LEVEL_3 (0.75): Actual code implementation files detected (components, routes, modules).
    - LEVEL_4 (0.85): Substantial implementation (dependencies + multiple files + tests/workflows).
    """
    LEVEL_0_URL_ONLY = 0
    LEVEL_1_METADATA = 1
    LEVEL_1_MENTION = 1
    LEVEL_2_CONFIG = 2
    LEVEL_3_IMPLEMENTATION = 3
    LEVEL_4_SUBSTANTIAL = 4

    DEPTH_STRENGTH_MAP: Dict[int, float] = {
        LEVEL_0_URL_ONLY: 0.0,
        LEVEL_1_METADATA: 0.40,
        LEVEL_2_CONFIG: 0.60,
        LEVEL_3_IMPLEMENTATION: 0.75,
        LEVEL_4_SUBSTANTIAL: 0.85,
    }

    @classmethod
    def get_strength_for_depth(cls, depth: int) -> float:
        return cls.DEPTH_STRENGTH_MAP.get(depth, 0.40)


@dataclass
class ExtractedSignal:
    skill: str  # Canonical skill name
    signal_strength: float  # [0.0, 1.0]
    depth: int  # EvidenceDepth level [0-4]
    reason: str  # Traceable evidence-based explanation
    source_reliability: float = 0.90
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "canonical_name": self.skill,
            "signal_strength": self.signal_strength,
            "signal_value": self.signal_strength,
            "depth": self.depth,
            "reason": self.reason,
            "explanation": self.reason,
            "source_reliability": self.source_reliability,
            "metadata": self.metadata,
        }


@dataclass
class VerificationResult:
    status: str
    message: str
    provider: str
    signals: List[ExtractedSignal] = field(default_factory=list)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
    verified_at: Optional[datetime] = None
    profile: Dict[str, Any] = field(default_factory=dict)
    facts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    observed_at: Optional[datetime] = None
    source_updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "verification_status": self.status,
            "verification_message": self.message,
            "provider": self.provider,
            "signals": [s.to_dict() for s in self.signals],
            "profile": self.profile,
            "facts": self.facts,
            "warnings": self.warnings,
            "metadata": self.raw_metadata,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "source_updated_at": self.source_updated_at,
        }


class EvidenceProvider(ABC):
    """Abstract Base Class for Evidence Intelligence Providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of provider: e.g., 'github', 'leetcode', 'codeforces', 'kaggle', 'linkedin'."""
        pass

    @abstractmethod
    def can_handle(self, evidence: dict) -> bool:
        """Return True if this provider can inspect and verify the given evidence item."""
        pass

    def validate(self, evidence: dict) -> Tuple[bool, Optional[str]]:
        """Validate evidence format, platform domain, or handle structure."""
        return True, None

    @abstractmethod
    async def verify(self, evidence: dict) -> VerificationResult:
        """
        Inspect the evidence source asynchronously and return VerificationResult
        containing verification status, message, raw metadata, and extracted signals.
        """
        pass

    @abstractmethod
    async def extract_signals(self, evidence: dict) -> List[ExtractedSignal]:
        """Extract structured skill signals from verified evidence."""
        pass
