from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
import re

from .base import EvidenceProvider, VerificationResult, ExtractedSignal, VerificationStatus, EvidenceDepth
from ..evidence_weights import reliability as get_reliability


class NotionProvider(EvidenceProvider):
    """
    Evidence Intelligence Provider for authorized Notion content.
    Extracts structured skill signals from user-authorized Notion pages and databases.
    Maintains full provenance: sourcePageId, sourcePageTitle, sourceUrl, evidenceType, confidence.
    """

    @property
    def provider_name(self) -> str:
        return "notion"

    def can_handle(self, evidence: dict) -> bool:
        etype = str(evidence.get("evidence_type") or "").strip().lower()
        if etype == "notion":
            return True
        url = str(evidence.get("source_url") or "").strip().lower()
        return "notion.so" in url or "notion.site" in url

    def validate(self, evidence: dict) -> Tuple[bool, Optional[str]]:
        url = str(evidence.get("source_url") or "").strip()
        meta = evidence.get("metadata") or {}
        page_id = meta.get("sourcePageId") or meta.get("page_id")
        if not url and not page_id:
            return False, "Notion evidence must specify a page URL or page ID"
        return True, None

    async def verify(self, evidence: dict) -> VerificationResult:
        meta = evidence.get("metadata") or {}
        verified_signals = meta.get("verified_signals") or []
        verified_at = evidence.get("verified_at") or meta.get("verified_at")
        page_title = meta.get("sourcePageTitle") or evidence.get("title") or "Notion Workspace Page"

        # If already parsed and pre-verified during sync, re-hydrate signals
        if verified_signals and isinstance(verified_signals, list):
            signals: List[ExtractedSignal] = []
            rel = get_reliability(self.provider_name)
            for s in verified_signals:
                signals.append(
                    ExtractedSignal(
                        skill=s.get("skill") or s.get("canonical_name", ""),
                        signal_strength=float(s.get("signal_strength", s.get("signal_value", 0.60))),
                        depth=int(s.get("depth", EvidenceDepth.LEVEL_2_CONFIG)),
                        reason=s.get("reason") or s.get("explanation") or f"Notion notes on '{page_title}'",
                        source_reliability=rel,
                        metadata=s.get("metadata") or meta,
                    )
                )

            return VerificationResult(
                status=VerificationStatus.VERIFIED,
                message=f"Verified {len(signals)} technical skill signal(s) from Notion page '{page_title}'",
                provider=self.provider_name,
                signals=signals,
                raw_metadata=meta,
                verified_at=datetime.fromisoformat(verified_at.replace("Z", "+00:00")) if verified_at else datetime.now(timezone.utc),
                facts=[f"Notion page: {page_title}", f"{len(signals)} skill signals verified"],
            )

        # Fallback dynamic signal extraction
        signals = await self.extract_signals(evidence)
        return VerificationResult(
            status=VerificationStatus.VERIFIED if signals else VerificationStatus.PARTIALLY_VERIFIED,
            message=f"Extracted {len(signals)} skill signals from Notion evidence",
            provider=self.provider_name,
            signals=signals,
            raw_metadata=meta,
            verified_at=datetime.now(timezone.utc),
        )

    async def extract_signals(self, evidence: dict) -> List[ExtractedSignal]:
        meta = evidence.get("metadata") or {}
        verified_signals = meta.get("verified_signals") or []
        page_title = meta.get("sourcePageTitle") or evidence.get("title") or "Notion Page"
        rel = get_reliability(self.provider_name)
        signals: List[ExtractedSignal] = []

        if isinstance(verified_signals, list) and verified_signals:
            for s in verified_signals:
                signals.append(
                    ExtractedSignal(
                        skill=s.get("skill") or s.get("canonical_name", ""),
                        signal_strength=float(s.get("signal_strength", s.get("signal_value", 0.60))),
                        depth=int(s.get("depth", EvidenceDepth.LEVEL_2_CONFIG)),
                        reason=s.get("reason") or s.get("explanation") or f"Notion notes on '{page_title}'",
                        source_reliability=rel,
                        metadata=s.get("metadata") or meta,
                    )
                )

        return signals
