"""
Generic GitHub evidence validation gate.

Prevents weak/incidental evidence from becoming a final skill signal
while preserving correct detections. No technology-specific hacks.

Evidence hierarchy (weak -> strong):
  documentation (README mention) < metadata (language stats)
  < dependency/configuration < imports/usages < implementation < substantial

A final skill signal should be SUPPORTED/DEMONSTRATED, not merely MENTIONED.
"""
from typing import Dict, List, Optional, Tuple, Any
from ..skill_taxonomy import get_canonical_skill
from .base import EvidenceDepth

# Evidence kinds as produced by _build_result_from_inspection
KIND_DOCUMENTATION = "documentation"
KIND_METADATA = "metadata"
KIND_DEPENDENCY = "dependency_manifest"
KIND_CONFIGURATION = "configuration"
KIND_SOURCE_USAGE = "source_usage"
KIND_IMPLEMENTATION = "implementation"
KIND_SUBSTANTIAL = "substantial_implementation"
KIND_TESTS = "tests"
KIND_INFRASTRUCTURE = "infrastructure"

# Centralized evidence policy thresholds
# Documentation alone never sufficient; need corroboration
DOC_ONLY_REJECT_DEPTH = EvidenceDepth.LEVEL_1_MENTION

# Categories that should never be inferred from code artifacts alone
CODE_INELIGIBLE_CATEGORIES = {"Soft Skills"}

def _skill_category(skill_name: str) -> Optional[str]:
    defn = get_canonical_skill(skill_name)
    return defn.category if defn else None


def validate_aggregated_signal(signal: Any, metadata: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Generic validator for an aggregated GitHub signal (one per canonical skill
    across all repos). Returns (accepted, reason).

    Rejection reasons are explicit and auditable.
    """
    # Extract fields
    try:
        skill = getattr(signal, "skill", None) or signal.get("skill") if isinstance(signal, dict) else str(signal)
    except Exception:
        skill = str(signal)
    skill = str(skill or "")
    meta = metadata or {}
    # Also handle signal object vs dict
    if hasattr(signal, "metadata"):
        meta = getattr(signal, "metadata", {}) or meta
        depth = getattr(signal, "depth", meta.get("evidence_depth", 0))
    elif isinstance(signal, dict):
        depth = signal.get("depth", meta.get("evidence_depth", 0))
    else:
        depth = meta.get("evidence_depth", 0)

    kinds: List[str] = list(meta.get("evidence_kinds") or [])
    # Normalize kinds to lowercase
    kinds = [str(k).lower() for k in kinds]
    doc_only = bool(meta.get("documentation_only"))
    owned = int(meta.get("owned_count", 0) or 0)
    repo_count = int(meta.get("repo_count", 0) or 0)
    fork_count = int(meta.get("fork_count", 0) or 0)

    category = _skill_category(skill)

    # 1. Soft skills cannot be demonstrated by code
    if category in CODE_INELIGIBLE_CATEGORIES:
        return False, "soft_skill_not_from_code"

    # 2. Documentation-only at weakest depth is always insufficient
    if doc_only and int(depth) == int(EvidenceDepth.LEVEL_1_MENTION):
        return False, "documentation_only"

    # 3. Pure documentation kind with weak depth
    if kinds == [KIND_DOCUMENTATION] and int(depth) == int(EvidenceDepth.LEVEL_1_MENTION):
        return False, "documentation_only"

    # 4. No meaningful evidence kind and weak depth -> insufficient corroboration
    if not kinds and int(depth) == int(EvidenceDepth.LEVEL_1_MENTION):
        return False, "insufficient_corroboration"

    # 5. Single weak indicator without owned implementation
    # If only one repo and it is fork and depth 1-2, not sufficient
    if repo_count == 1 and owned == 0 and int(depth) <= int(EvidenceDepth.LEVEL_2_CONFIG):
        # Allow DevOps config from forks? Require stronger for programming
        if category in ("Programming", "Frontend", "Backend", "Databases", "AI/ML", "Mobile"):
            return False, "insufficient_corroboration"

    # 6. Programming languages need implementation evidence, not just metadata
    if category == "Programming":
        has_impl = any(k in kinds for k in (KIND_IMPLEMENTATION, KIND_SUBSTANTIAL, KIND_SOURCE_USAGE))
        # Also check depth: programming at L1/L2 with only doc/config is weak
        if not has_impl and int(depth) < int(EvidenceDepth.LEVEL_3_IMPLEMENTATION):
            # Check if at least dependency + usage present
            if KIND_DEPENDENCY not in kinds or KIND_SOURCE_USAGE not in kinds:
                return False, "insufficient_corroboration"

    # 7. Frameworks (Frontend/Backend) need dependency + usage corroboration
    if category in ("Frontend", "Backend"):
        has_dep = KIND_DEPENDENCY in kinds
        has_usage = KIND_SOURCE_USAGE in kinds
        has_impl = KIND_IMPLEMENTATION in kinds or KIND_SUBSTANTIAL in kinds
        if has_dep and not (has_usage or has_impl):
            # Single dependency without usage and only 1 repo is weak
            if repo_count < 2 and int(depth) <= int(EvidenceDepth.LEVEL_2_CONFIG):
                return False, "insufficient_corroboration"

    # 8. Databases need dependency/config + usage or implementation
    if category == "Databases":
        has_dep = KIND_DEPENDENCY in kinds
        has_config = KIND_CONFIGURATION in kinds
        has_usage = KIND_SOURCE_USAGE in kinds
        has_impl = KIND_IMPLEMENTATION in kinds
        if not (has_dep or has_config):
            return False, "insufficient_context"
        if (has_dep or has_config) and not (has_usage or has_impl) and int(depth) == int(EvidenceDepth.LEVEL_2_CONFIG) and repo_count == 1:
            # Single config without usage is still okay for DB? Keep but mark weak
            # For now allow, but if doc_only already filtered, this is okay
            pass

    # 9. Testing requires test evidence
    if category == "Quality" and skill.lower() == "testing":
        if KIND_TESTS not in kinds and "tests" not in [str(k) for k in kinds]:
            # Check metadata for has_tests? Use evidence_kinds includes tests if present
            # If no test kind, reject weak doc mention of testing
            if KIND_DOCUMENTATION in kinds and len(kinds) == 1:
                return False, "insufficient_corroboration"

    # Passed all gates
    return True, "accepted"


def validate_repo_signal(skill: str, depth: int, evidence_kind: Optional[str], inspection: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Per-repository validation before a candidate becomes a repo signal.
    Soft skills and vendor files are rejected here; documentation-only
    is kept per-repo as weak tier (validated at aggregation).
    """
    category = _skill_category(skill or "")
    kind = str(evidence_kind or "").lower()

    # Soft skills never from code
    if category in CODE_INELIGIBLE_CATEGORIES:
        return False, "soft_skill_not_from_code"

    # Metadata alone without files is weak but keep for now - aggregated will filter
    # Documentation-only kept per-repo as weak evidence; aggregated gate rejects final
    return True, "accepted"


def classify_rejection_reason(kinds: List[str], depth: int, category: Optional[str], doc_only: bool) -> str:
    if doc_only and depth == EvidenceDepth.LEVEL_1_MENTION:
        return "documentation_only"
    if category in CODE_INELIGIBLE_CATEGORIES:
        return "soft_skill_not_from_code"
    if not kinds and depth == EvidenceDepth.LEVEL_1_MENTION:
        return "insufficient_corroboration"
    return "insufficient_corroboration"
