"""
Skill Capability Map (core INAURA feature, deterministic — no LLM required).

For every important skill required by a target role, explains:
  1. WHAT THE INDUSTRY EXPECTS (from industry requirements + RAG evidence)
  2. WHAT THE STUDENT SHOULD BE ABLE TO DO (observable abilities)
  3. WHAT INAURA ALREADY KNOWS (demonstrated capabilities + evidence)
  4. WHAT IS STILL MISSING (gaps, priorities, next actions)

Architecture (reuses the existing INAURA flow, duplicates nothing):

  Industry Role -> Industry Requirements / RAG -> Canonical Skill
      -> Skill Capability Definition -> Student Evidence (grouped signals)
      -> Deterministic Comparison -> Capability Map

Skill vs capability (kept strictly separate):
  Skill       = a technology in the canonical taxonomy (e.g. Python).
  Capability  = something observable a candidate can DO with it
                (e.g. build REST APIs, write automated tests).

A student can therefore show strong Python proficiency while a specific
async capability stays weak — the map reports both honestly.

Anti-fabrication rules:
- Capability vocabulary comes from the curated blueprints below (product
  content, versioned here — same standing as roadmap_catalog templates).
- Industry expectations are attached ONLY from real requirement rows and
  real supporting chunks. Without an industry requirement or without a
  blueprint, the skill is marked `insufficient_industry_data` and NO
  capabilities are invented to fill the UI.
- Demonstrated capabilities require matching signal evidence; a README
  mention (depth 1) never satisfies a rule that needs implementation.
- Absence of evidence is reported as `evidence_gap`, never as proof the
  student lacks the capability — unless implementation-level evidence for
  the skill exists while the specific capability is unmet (`skill_gap`).

Scores here NEVER enter proficiency, confidence, readiness, or gap math:
priority reuse calls skill_engine.calculate_prioritized_gap for ranking
only, exactly as the gap engine does for gaps.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from ..core.supabase import get_supabase_client
from . import analysis_run_service as ars
from . import analysis_service
from . import skill_engine as engine
from .roadmap_catalog import get_resources_for_skill, get_template_for_skill
from .skill_taxonomy import normalize_skill, normalize_skill_slug
from . import skill_dependencies


# ---------------------------------------------------------------------------
# Matching engine (deterministic; reads grouped signals only, writes nothing)
# ---------------------------------------------------------------------------

def _canon(name: Any) -> str:
    """Canonical display name for matching (falls back to stripped raw)."""
    text = str(name or "").strip()
    if not text:
        return ""
    try:
        return normalize_skill(text) or text
    except Exception:
        return text


def _signal_depth(sig: Dict[str, Any]) -> int:
    try:
        return int(sig.get("depth", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _signal_source(sig: Dict[str, Any]) -> str:
    return str(sig.get("source") or sig.get("source_type") or "").strip().lower()


def _signal_files(sig: Dict[str, Any]) -> List[str]:
    meta = sig.get("metadata") or {}
    files = meta.get("relevant_files") or []
    if not isinstance(files, list):
        return []
    return [str(f) for f in files if str(f or "").strip()][:5]


def _signal_patterns(sig: Dict[str, Any]) -> List[str]:
    meta = sig.get("metadata") or {}
    patterns = meta.get("detected_usage_patterns") or []
    if isinstance(patterns, dict):
        return sorted(str(p) for p in patterns.keys())
    if isinstance(patterns, (list, tuple, set)):
        return sorted(str(p) for p in patterns)
    return []


def _provenance_entry(sig: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, path-only provenance for one signal (no source contents)."""
    meta = sig.get("metadata") or {}
    repo = (
        meta.get("project_name")
        or meta.get("full_name")
        or meta.get("repo")
        or ""
    )
    reason = str(sig.get("reason") or sig.get("explanation") or "")[:300]
    return {
        "provider": _signal_source(sig) or "evidence",
        "repository": str(repo),
        "files": _signal_files(sig),
        "depth": _signal_depth(sig),
        "reason": reason,
    }


def _dedupe_evidence(entries: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for entry in entries:
        key = (entry.get("provider"), entry.get("repository"),
               tuple(entry.get("files") or []), entry.get("depth"))
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def _rule_matches(rule: Dict[str, Any], grouped: Dict[str, List[dict]]) -> Tuple[bool, List[Dict[str, Any]]]:
    """Evaluate one evidence rule. Returns (matched, provenance entries)."""
    kind = str(rule.get("kind") or "")
    if kind == "signal":
        skill = _canon(rule.get("skill", ""))
        candidates = grouped.get(skill, [])
        try:
            min_depth = int(rule.get("min_depth", 0) or 0)
        except (TypeError, ValueError):
            min_depth = 0
        sources = {str(s).strip().lower() for s in (rule.get("sources") or []) if str(s or "").strip()}
        usage_in = {str(s).strip().lower() for s in (rule.get("usage_in") or []) if str(s or "").strip()}
        try:
            min_files = int(rule.get("min_files", 0) or 0)
        except (TypeError, ValueError):
            min_files = 0
        matched = [
            s for s in candidates
            if _signal_depth(s) >= min_depth
            and (not sources or _signal_source(s) in sources)
            and (not usage_in or str((s.get("metadata") or {}).get("usage_status") or "").lower() in usage_in)
        ]
        if min_files:
            total_files = sum(len(_signal_files(s)) for s in matched)
            if total_files < min_files:
                return False, []
        if not matched:
            return False, []
        return True, _dedupe_evidence([_provenance_entry(s) for s in matched])
    if kind == "patterns":
        skill = _canon(rule.get("skill", ""))
        wanted = {str(p) for p in (rule.get("any_of") or [])}
        hits = []
        for sig in grouped.get(skill, []):
            found = set(_signal_patterns(sig)) & wanted
            if found:
                entry = _provenance_entry(sig)
                entry["patterns"] = sorted(found)
                hits.append(entry)
        if not hits:
            return False, []
        return True, _dedupe_evidence(hits)
    if kind == "files":
        skill = _canon(rule.get("skill", ""))
        try:
            min_count = int(rule.get("min_count", 1) or 1)
        except (TypeError, ValueError):
            min_count = 1
        files: List[str] = []
        entries: List[Dict[str, Any]] = []
        for sig in grouped.get(skill, []):
            for f in _signal_files(sig):
                if f not in files:
                    files.append(f)
            entries.append(_provenance_entry(sig))
            if len(files) >= min_count and len(entries) >= 3:
                break
        if len(files) < min_count:
            return False, []
        return True, _dedupe_evidence(entries)
    if kind == "related_present":
        skills = [_canon(s) for s in (rule.get("skills") or [])]
        skills = [s for s in skills if s]
        entries = []
        for skill in skills:
            for sig in grouped.get(skill, [])[:2]:
                entries.append(_provenance_entry(sig))
            if entries:
                break
        if not entries:
            return False, []
        return True, _dedupe_evidence(entries)
    return False, []


def evaluate_capability(
    capability: Dict[str, Any],
    grouped: Dict[str, List[dict]],
) -> Dict[str, Any]:
    """
    Score one capability against grouped student signals.
    Returns {support [0..1], demonstrated bool, evidence [...]}.
    support = matched rule weight / total rule weight (rounded to 3).
    demonstrated = support >= 0.75. A README mention (depth 1) can never
    satisfy a rule requiring implementation depth.
    """
    rules = capability.get("evidence_rules") or []
    total = 0.0
    matched_weight = 0.0
    evidence: List[Dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        try:
            weight = float(rule.get("weight", 1.0) or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        if weight <= 0:
            continue
        total += weight
        try:
            matched, entries = _rule_matches(rule, grouped)
        except Exception:
            matched, entries = False, []
        if matched:
            matched_weight += weight
            evidence.extend(entries)
    support = round(matched_weight / total, 3) if total > 0 else 0.0
    return {
        "support": support,
        "demonstrated": support >= DEMONSTRATED_SUPPORT,
        "evidence": _dedupe_evidence(evidence),
    }


def _has_implementation(signals: List[dict]) -> bool:
    """Any implementation-level (depth >= 3) signal for the skill itself."""
    return any(_signal_depth(s) >= 3 for s in (signals or []))


def classify_capability_status(support: Any, has_implementation: bool = False) -> str:
    """Deterministic capability status around the existing support score.

    Interpretation layer only — never changes scoring:
      support >= DEMONSTRATED_SUPPORT -> demonstrated
      support >= DEVELOPING_SUPPORT  -> developing
      support < DEVELOPING_SUPPORT   -> unverified, unless the existing
        evidence logic already identifies a genuine gap (skill-level
        implementation evidence exists while this capability is unmet),
        in which case -> confirmed_gap.

    Absence of evidence is unverified, never confirmed inability.
    Mirrors the existing evidence_gap vs skill_gap distinction:
      no implementation evidence -> unverified (evidence_gap analogue)
      implementation evidence + support == 0 -> confirmed_gap (skill_gap analogue)
    """
    try:
        value = float(support or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    if value >= DEMONSTRATED_SUPPORT:
        return STATUS_DEMONSTRATED
    if value >= DEVELOPING_SUPPORT:
        return STATUS_DEVELOPING
    if bool(has_implementation) and value <= 0.0:
        return STATUS_CONFIRMED_GAP
    return STATUS_UNVERIFIED


def build_capability_knowledge_statement(
    title: Any,
    support: Any,
    status: str,
    evidence: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Concise deterministic statement describing what INAURA knows.

    Derived only from the capability title, its support/status, and the
    depth of its existing evidence. Never claims inability; unverified
    capabilities explicitly report insufficient evidence.
    """
    label = str(title or "").strip() or "this capability"
    entries = evidence or []
    has_impl_evidence = any(
        isinstance(e, dict) and int(e.get("depth", 0) or 0) >= 3
        for e in entries
        if isinstance(e, dict)
    )
    if status == STATUS_DEMONSTRATED:
        if has_impl_evidence:
            return (
                f"INAURA has strong implementation-level evidence "
                f"that you have demonstrated {label}."
            )
        return f"INAURA has strong evidence that you have demonstrated {label}."
    if status == STATUS_DEVELOPING:
        return (
            f"INAURA has some evidence related to {label}, but the available "
            f"evidence does not fully demonstrate this capability."
        )
    if status == STATUS_CONFIRMED_GAP:
        return (
            f"INAURA has implementation-level evidence for this skill, but the "
            f"available evidence does not demonstrate {label}."
        )
    return (
        f"INAURA does not currently have sufficient evidence to verify {label}."
    )


def build_evidence_summary(skill_signals: Optional[List[dict]]) -> Dict[str, Any]:
    """Compact evidence summary reusing existing provenance (path-only).

    Counts only signals already available to the capability map:
      evidence_count: total signals relevant to the skill
      source_types: unique provider/source types (sorted)
      implementation_evidence_count: signals with depth >= 3
    """
    signals = list(skill_signals or [])
    providers: List[str] = []
    impl_count = 0
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        provider = _signal_source(sig) or "evidence"
        if provider not in providers:
            providers.append(provider)
        if _signal_depth(sig) >= 3:
            impl_count += 1
    return {
        "evidence_count": len(signals),
        "source_types": sorted(providers),
        "implementation_evidence_count": impl_count,
    }


def _empty_what_inaura_knows(summary: str) -> Dict[str, Any]:
    """Consistent empty shape for skills without evaluable capabilities."""
    return {
        "summary": summary,
        "demonstrated_areas": [],
        "developing_areas": [],
        "unverified_areas": [],
        "evidence_summary": {
            "evidence_count": 0,
            "source_types": [],
            "implementation_evidence_count": 0,
        },
    }


def build_what_inaura_knows_summary(
    canonical_skill: str,
    demonstrated_areas: List[Dict[str, Any]],
    developing_areas: List[Dict[str, Any]],
    unverified_areas: List[Dict[str, Any]],
    has_implementation: bool,
) -> str:
    """Deterministic skill-level summary from capability evaluation results.

    Mentions only curated capability titles and evidence depth already
    present. Never invents experience; reports limited evidence honestly.
    """
    skill = str(canonical_skill or "").strip() or "this skill"
    if not demonstrated_areas and not developing_areas:
        return f"INAURA has limited evidence about how {skill} is used in practice."

    def _titles(areas: List[Dict[str, Any]]) -> str:
        names = [
            str(a.get("capability_title") or "").strip()
            for a in areas
            if str(a.get("capability_title") or "").strip()
        ]
        return ", ".join(names)

    parts: List[str] = []
    if demonstrated_areas:
        titles = _titles(demonstrated_areas)
        depth_phrase = (
            "implementation-level evidence" if has_implementation else "evidence"
        )
        if titles:
            parts.append(
                f"INAURA has {depth_phrase} of {skill} usage, including {titles}."
            )
        else:
            parts.append(
                f"INAURA has {depth_phrase} of {skill} usage."
            )
    elif developing_areas:
        titles = _titles(developing_areas)
        if titles:
            parts.append(
                f"INAURA has partial evidence of {skill} usage related to {titles}."
            )
        else:
            parts.append(f"INAURA has partial evidence of {skill} usage.")
    if demonstrated_areas and developing_areas:
        titles = _titles(developing_areas)
        if titles:
            parts.append(f"{titles} have weaker or partial evidence.")
    if unverified_areas and (demonstrated_areas or developing_areas):
        titles = _titles(unverified_areas)
        if titles:
            parts.append(f"{titles} have insufficient evidence.")
    return " ".join(p for p in parts if p).strip()


def build_what_inaura_knows(
    canonical_skill: str,
    capabilities_out: List[Dict[str, Any]],
    skill_signals: Optional[List[dict]],
) -> Dict[str, Any]:
    """Interpretation layer: deterministic synthesis of existing evidence.

    Flow preserved: capability blueprint -> "you should be able to do" ->
    student evidence -> capability evaluation (support preserved) ->
    "what INAURA knows" -> status/gaps/next action.

    Each capability keeps its support score and evidence list; this adds
    only status + statement. Evidence remains the underlying support layer.
    """
    signals = list(skill_signals or [])
    has_impl = _has_implementation(signals)
    demonstrated_areas: List[Dict[str, Any]] = []
    developing_areas: List[Dict[str, Any]] = []
    unverified_areas: List[Dict[str, Any]] = []
    for cap in capabilities_out or []:
        if not isinstance(cap, dict):
            continue
        try:
            support = float(cap.get("support", 0.0) or 0.0)
        except (TypeError, ValueError):
            support = 0.0
        evidence = cap.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = []
        # For REST APIs the capability's own status is already refined to
        # capability-specific evidence (generic REST alone stays unverified);
        # reuse it so WHAT INAURA KNOWS and STILL DEVELOP stay consistent.
        raw_status = cap.get("status")
        if isinstance(raw_status, str) and raw_status:
            status = raw_status
        else:
            status = classify_capability_status(support, has_impl)
        statement = build_capability_knowledge_statement(
            cap.get("title"), support, status, evidence
        )
        area = {
            "capability_id": str(cap.get("id") or ""),
            "capability_title": str(cap.get("title") or ""),
            "statement": statement,
            "support": support,
            "status": status,
        }
        if status == STATUS_DEMONSTRATED:
            demonstrated_areas.append(area)
        elif status == STATUS_DEVELOPING:
            developing_areas.append(area)
        else:
            # Both unverified and confirmed_gap live here; status distinguishes
            # absence of evidence (unverified) from a genuine gap already
            # identified by the existing skill_gap logic (confirmed_gap).
            unverified_areas.append(area)
    summary = build_what_inaura_knows_summary(
        canonical_skill, demonstrated_areas, developing_areas,
        unverified_areas, has_impl,
    )
    return {
        "summary": summary,
        "demonstrated_areas": demonstrated_areas,
        "developing_areas": developing_areas,
        "unverified_areas": unverified_areas,
        "evidence_summary": build_evidence_summary(signals),
    }


# ---------------------------------------------------------------------------
# Phase 2: Capability-level evidence & explainability (deterministic).
#
# Presentation/explanation layer only. Every helper below reads the existing
# capability blueprint rules and the existing grouped evidence through the
# SAME _rule_matches() engine used by evaluate_capability(). Nothing here
# feeds back into proficiency, confidence, readiness, gap, priority, RAG,
# industry-requirement, or GitHub-inspection logic.
#
# Kept separate from "What INAURA knows" (a synthesis of understanding) and
# from "Evidence" (provenance/artifacts): this layer answers WHY a status
# was assigned, citing only rules that actually matched and rules from the
# curated blueprint that did not.
# ---------------------------------------------------------------------------

EVIDENCE_STRENGTH_STRONG = "strong"
EVIDENCE_STRENGTH_MODERATE = "moderate"
EVIDENCE_STRENGTH_WEAK = "weak"
EVIDENCE_STRENGTH_INSUFFICIENT = "insufficient"


def classify_evidence_strength(support: Any) -> str:
    """Evidence strength from the existing support score (display only).

    support >= 0.75         -> strong
    support >= 0.40         -> moderate
    support > 0             -> weak
    support == 0            -> insufficient
    """
    try:
        value = float(support or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    if value >= DEMONSTRATED_SUPPORT:
        return EVIDENCE_STRENGTH_STRONG
    if value >= DEVELOPING_SUPPORT:
        return EVIDENCE_STRENGTH_MODERATE
    if value > 0:
        return EVIDENCE_STRENGTH_WEAK
    return EVIDENCE_STRENGTH_INSUFFICIENT


def _status_reasons() -> Dict[str, str]:
    # Built lazily: the STATUS_* constants are defined further below with
    # the rest of the capability model vocabulary.
    return {
        STATUS_DEMONSTRATED: "Strong implementation evidence supports this capability.",
        STATUS_DEVELOPING: (
            "INAURA found partial implementation evidence, but not enough "
            "evidence to establish the full capability."
        ),
        STATUS_UNVERIFIED: (
            "INAURA does not have sufficient evidence to determine whether "
            "this capability is demonstrated."
        ),
        STATUS_CONFIRMED_GAP: (
            "Available assessment/evidence indicates this capability is "
            "currently below the required level."
        ),
    }


def build_status_reason(status: str) -> str:
    """Fixed deterministic reason for a capability status (no LLM)."""
    reasons = _status_reasons()
    return reasons.get(str(status or ""), reasons[STATUS_UNVERIFIED])


def _humanize_pattern(pattern_id: Any) -> str:
    """Internal pattern ids ('fastapi_app') -> readable words ('fastapi app')."""
    return str(pattern_id or "").strip().replace("_", " ")


def _rule_subject_skill(rule: Dict[str, Any]) -> str:
    """Canonical skill a rule inspects ('' when the rule has none)."""
    skill = rule.get("skill") if isinstance(rule, dict) else None
    if skill:
        return _canon(skill)
    return ""


def _depth_word(min_depth: int) -> str:
    if min_depth >= 3:
        return "implementation"
    if min_depth == 2:
        return "configuration"
    if min_depth == 1:
        return "mention"
    return "usage"


def _depth_phrase(min_depth: int) -> str:
    if min_depth >= 3:
        return "implementation-level"
    if min_depth == 2:
        return "configuration-level"
    if min_depth == 1:
        return "mention-level"
    return "recorded"


def _rule_signal_label(rule: Dict[str, Any]) -> str:
    """Short human label for one evidence rule (no weights, no internals)."""
    kind = str((rule or {}).get("kind") or "")
    if kind == "signal":
        skill = _rule_subject_skill(rule) or "skill"
        try:
            depth = int(rule.get("min_depth", 0) or 0)
        except (TypeError, ValueError):
            depth = 0
        return f"{skill} {_depth_word(depth)} evidence"
    if kind == "patterns":
        skill = _rule_subject_skill(rule) or "skill"
        return f"{skill} code patterns"
    if kind == "files":
        skill = _rule_subject_skill(rule) or "skill"
        return f"{skill} project files"
    if kind == "related_present":
        skills = [_canon(s) for s in ((rule or {}).get("skills") or [])]
        skills = [s for s in skills if s]
        return f"related {', '.join(skills)} activity" if skills else "related activity"
    return "supporting evidence"


def _rule_expectation_detail(rule: Dict[str, Any]) -> str:
    """What one rule expects, in human words derived from the rule itself."""
    kind = str((rule or {}).get("kind") or "")
    if kind == "signal":
        skill = _rule_subject_skill(rule) or "this skill"
        try:
            depth = int(rule.get("min_depth", 0) or 0)
        except (TypeError, ValueError):
            depth = 0
        detail = f"{_depth_phrase(depth)} {skill} usage"
        sources = sorted({str(s).strip().lower() for s in (rule.get("sources") or [])
                          if str(s or "").strip()})
        if sources:
            detail += f" from {', '.join(sources)}"
        usage_in = sorted({str(s).strip().lower() for s in (rule.get("usage_in") or [])
                           if str(s or "").strip()})
        if usage_in:
            detail += f" with '{', '.join(usage_in)}' usage"
        try:
            min_files = int(rule.get("min_files", 0) or 0)
        except (TypeError, ValueError):
            min_files = 0
        if min_files:
            detail += f" across {min_files}+ files"
        return detail
    if kind == "patterns":
        skill = _rule_subject_skill(rule) or "skill"
        wanted = [_humanize_pattern(p) for p in (rule.get("any_of") or [])]
        wanted = [w for w in wanted if w]
        if wanted:
            return f"{skill} code patterns ({', '.join(wanted)})"
        return f"{skill} code patterns"
    if kind == "files":
        skill = _rule_subject_skill(rule) or "skill"
        try:
            min_count = int(rule.get("min_count", 1) or 1)
        except (TypeError, ValueError):
            min_count = 1
        return f"project files showing {skill} use ({min_count}+ files)"
    if kind == "related_present":
        skills = [_canon(s) for s in ((rule or {}).get("skills") or [])]
        skills = [s for s in skills if s]
        if skills:
            return f"related activity in {', '.join(skills)}"
        return "related skill activity"
    return "supporting evidence"


def _rule_weight_entries(capability: Dict[str, Any]) -> List[Tuple[Dict[str, Any], float]]:
    """(rule, weight) pairs exactly as evaluate_capability() counts them."""
    out: List[Tuple[Dict[str, Any], float]] = []
    for rule in ((capability or {}).get("evidence_rules") or []):
        if not isinstance(rule, dict):
            continue
        try:
            weight = float(rule.get("weight", 1.0) or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        if weight <= 0:
            continue
        out.append((rule, weight))
    return out


def _is_rest_generic_rule(rule: Dict[str, Any], canonical_skill: Any) -> bool:
    """Generic skill-level REST APIs evidence (signal/files on REST APIs).

    For the REST APIs skill, a bare `signal` or `files` rule on REST APIs
    proves the project uses REST APIs but does NOT prove a specific
    capability such as validation, auth, or documentation. Those need a
    capability-specific rule (patterns / related_present). This helper lets
    the explanation layer separate skill-level context from capability-specific
    evidence without inventing any new rules.
    """
    try:
        canon = _canon(canonical_skill) if canonical_skill else ""
    except Exception:
        canon = ""
    if canon != "REST APIs":
        return False
    kind = str((rule or {}).get("kind") or "")
    if kind not in ("signal", "files"):
        return False
    skill = _rule_subject_skill(rule)
    return skill == "REST APIs"


def _split_capability_rules(
    capability: Dict[str, Any], canonical_skill: Any
) -> Tuple[List[Tuple[Dict[str, Any], float]], List[Tuple[Dict[str, Any], float]]]:
    """Split blueprint rules into (specific, generic) for the explanation layer.

    Generic = REST APIs skill-level signal/files on REST APIs (context only).
    Specific = everything else that actually proves the capability.
    For non-REST skills the split is trivial (all specific) so existing
    Python/JS/etc. behaviour is unchanged. No rule is invented or removed;
    support scoring is untouched — this is presentation only.
    """
    weighted = _rule_weight_entries(capability)
    # Only the REST APIs skill has a meaningful generic/specific distinction.
    try:
        canon = _canon(canonical_skill) if canonical_skill else ""
    except Exception:
        canon = ""
    if canon != "REST APIs":
        return weighted, []
    specific: List[Tuple[Dict[str, Any], float]] = []
    generic: List[Tuple[Dict[str, Any], float]] = []
    for rule, weight in weighted:
        if _is_rest_generic_rule(rule, canonical_skill):
            generic.append((rule, weight))
        else:
            specific.append((rule, weight))
    return specific, generic


def _specific_support(
    capability: Dict[str, Any],
    grouped: Dict[str, List[dict]],
    canonical_skill: Any,
) -> Tuple[float, float, float]:
    """Specific support for the explanation layer (deterministic).

    Returns (specific_support, matched_specific_weight, total_specific_weight).
    When a REST capability has no specific rules (e.g. Validate, Document),
    total_specific_weight == 0 and specific_support == 0 — the explanation
    will explicitly say no capability-specific evidence was found.
    """
    specific, _generic = _split_capability_rules(capability, canonical_skill)
    total = sum(w for _, w in specific)
    if total <= 0:
        return 0.0, 0.0, 0.0
    matched_weight = 0.0
    for rule, weight in specific:
        if _matched_rule_entries(rule, grouped):
            matched_weight += weight
    return round(matched_weight / total, 3) if total > 0 else 0.0, matched_weight, total


def _has_generic_rest_evidence(
    capability: Dict[str, Any],
    grouped: Dict[str, List[dict]],
    canonical_skill: Any,
) -> bool:
    _, generic = _split_capability_rules(capability, canonical_skill)
    for rule, _ in generic:
        if _matched_rule_entries(rule, grouped):
            return True
    return False


def _matched_rule_entries(rule: Dict[str, Any],
                           grouped: Dict[str, List[dict]]) -> List[Dict[str, Any]]:
    """Provenance entries for one rule, or [] when it does not match."""
    try:
        matched, entries = _rule_matches(rule, grouped or {})
    except Exception:
        return []
    return list(entries) if matched else []


def _dominant_provider(entries: List[Dict[str, Any]]) -> str:
    """Most common provider across entries (ties -> first sorted)."""
    counts: Dict[str, int] = {}
    for entry in entries:
        provider = str((entry or {}).get("provider") or "evidence")
        counts[provider] = counts.get(provider, 0) + 1
    if not counts:
        return "evidence"
    best = max(counts.values())
    return sorted(p for p, n in counts.items() if n == best)[0]


def _union_files(entries: List[Dict[str, Any]], limit: int = 3) -> List[str]:
    """Ordered, deduped file paths across entries (capped, path-only)."""
    files: List[str] = []
    for entry in entries:
        for path in ((entry or {}).get("files") or []):
            text = str(path or "").strip()
            if text and text not in files:
                files.append(text)
            if len(files) >= limit:
                return files
    return files


def _build_matched_entries_for_rules(
    rules: List[Tuple[Dict[str, Any], float]],
    grouped: Dict[str, List[dict]],
    total: float,
) -> List[Dict[str, Any]]:
    """Build matched signal entries for a specific rule subset."""
    matched: List[Dict[str, Any]] = []
    for rule, weight in rules:
        entries = _matched_rule_entries(rule, grouped)
        if not entries:
            continue
        kind = str(rule.get("kind") or "")
        provider = _dominant_provider(entries)
        files = _union_files(entries)
        if kind == "patterns":
            found: List[str] = []
            for entry in entries:
                for pattern in ((entry or {}).get("patterns") or []):
                    label = _humanize_pattern(pattern)
                    if label and label not in found:
                        found.append(label)
            skill = _rule_subject_skill(rule) or "skill"
            if found:
                statement = (f"INAURA found {skill} code patterns "
                             f"({', '.join(found)}) in {provider} evidence.")
            else:
                statement = (f"INAURA found {_rule_expectation_detail(rule)} "
                             f"in {provider} evidence.")
        elif kind == "files":
            skill = _rule_subject_skill(rule) or "skill"
            count = len({path for entry in entries
                         for path in ((entry or {}).get("files") or []) if str(path or "").strip()})
            statement = (f"INAURA found project files showing {skill} use "
                         f"({count} file{'s' if count != 1 else ''}) "
                         f"in {provider} evidence.")
        elif kind == "related_present":
            skills = [_canon(s) for s in (rule.get("skills") or [])]
            hit = [s for s in skills if s and (grouped or {}).get(s)]
            names = hit or [s for s in skills if s]
            statement = (f"INAURA found related {', '.join(names)} activity "
                         f"in {provider} evidence.") if names else (
                f"INAURA found {_rule_expectation_detail(rule)} in {provider} evidence.")
        else:
            statement = (f"INAURA found {_rule_expectation_detail(rule)} "
                         f"in {provider} evidence.")
        matched.append({
            "signal": _rule_signal_label(rule),
            "statement": statement,
            "source_type": provider,
            "support": round(weight / total, 3) if total > 0 else 0.0,
            "files": files,
        })
    return matched


def build_matched_signals(capability: Dict[str, Any],
                           grouped: Dict[str, List[dict]],
                           canonical_skill: Any = None) -> List[Dict[str, Any]]:
    """Signals that actually matched, one entry per satisfied blueprint rule.

    Each entry cites only real provenance (dominant source type + up to 3
    file paths already present in the capability evidence). Support is the
    rule's existing weight share (weight / total rule weight), i.e. the same
    arithmetic evaluate_capability() uses — presentation only.

    Refinement: for the REST APIs skill, generic skill-level REST presence
    (signal/files on REST APIs) is treated as contextual, not capability-
    specific. matched_signals returns only capability-specific matches; the
    generic context is available via _has_generic_rest_evidence() and the
    summary wording. Pass canonical_skill for that split; when omitted the
    legacy behaviour (all rules) is preserved for backwards compat.
    """
    if canonical_skill is None or _canon(canonical_skill) != "REST APIs":
        weighted = _rule_weight_entries(capability)
        total = sum(weight for _, weight in weighted)
        return _build_matched_entries_for_rules(weighted, grouped, total)
    specific, _generic = _split_capability_rules(capability, canonical_skill)
    if not specific:
        return []
    total = sum(weight for _, weight in specific)
    return _build_matched_entries_for_rules(specific, grouped, total)


def build_missing_signals(capability: Dict[str, Any],
                           grouped: Dict[str, List[dict]],
                           canonical_skill: Any = None) -> List[Dict[str, Any]]:
    """Blueprint rules with insufficient evidence (expectations, not verdicts).

    'Missing' means INAURA did not find sufficient evidence — never that the
    candidate cannot do it. For the REST APIs skill, only capability-specific
    rules are reported as missing; generic REST presence is contextual.
    """
    if canonical_skill is None or _canon(canonical_skill) != "REST APIs":
        missing: List[Dict[str, Any]] = []
        for rule, _weight in _rule_weight_entries(capability):
            if _matched_rule_entries(rule, grouped):
                continue
            missing.append({
                "signal": _rule_signal_label(rule),
                "statement": ("INAURA did not find sufficient evidence for "
                              f"{_rule_expectation_detail(rule)}."),
            })
        return missing
    specific, _generic = _split_capability_rules(capability, canonical_skill)
    if not specific:
        return []
    missing: List[Dict[str, Any]] = []
    for rule, _weight in specific:
        if _matched_rule_entries(rule, grouped):
            continue
        missing.append({
            "signal": _rule_signal_label(rule),
            "statement": ("INAURA did not find sufficient evidence for "
                          f"{_rule_expectation_detail(rule)}."),
        })
    return missing


def _join_and(items: List[str]) -> str:
    items = [str(i or "").strip() for i in (items or [])]
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def build_capability_explanation_summary(
    title: Any,
    status: str,
    support: Any,
    matched_labels: List[str],
    missing_labels: List[str],
    canonical_skill: Any = None,
    has_generic_context: bool = False,
) -> str:
    """Deterministic why-summary assembled only from rule outcomes.

    Refinement: when a REST APIs capability has no capability-specific
    evidence, the summary explicitly says so and mentions the generic REST
    context rather than presenting generic presence as capability proof.
    """
    label = str(title or "").strip() or "this capability"
    # REST generic-but-no-specific case: explicit capability-specific gap.
    try:
        canon = _canon(canonical_skill) if canonical_skill else ""
    except Exception:
        canon = ""
    if canon == "REST APIs" and has_generic_context and not matched_labels:
        # Generic REST APIs evidence exists, but nothing capability-specific.
        # Keep the distinction: generic skill evidence ≠ capability evidence.
        return (
            f"INAURA found REST API implementation in the project, but no "
            f"capability-specific evidence for {label.lower()} was detected."
        )
    try:
        value = float(support or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    if status == STATUS_DEMONSTRATED:
        if matched_labels:
            return (f"INAURA found {_join_and(list(matched_labels))} "
                    f"supporting {label}.")
        return f"INAURA found strong evidence supporting {label}."
    if status == STATUS_DEVELOPING:
        if matched_labels and missing_labels:
            return (f"INAURA found partial evidence for {label} "
                    f"({_join_and(list(matched_labels))}), but did not find "
                    f"sufficient evidence for {_join_and(list(missing_labels))}.")
        if matched_labels:
            return (f"INAURA found partial evidence for {label} "
                    f"({_join_and(list(matched_labels))}), but the evidence does "
                    f"not fully establish the capability.")
        return (f"INAURA found partial evidence for {label}, but the evidence "
                f"does not fully establish the capability.")
    if status == STATUS_CONFIRMED_GAP:
        return ("INAURA found implementation evidence for this skill but did "
                f"not find sufficient evidence for {label}.")
    if value > 0 and matched_labels:
        if missing_labels:
            return (f"INAURA found only weak evidence related to {label}. "
                    f"INAURA did not find sufficient evidence for "
                    f"{_join_and(list(missing_labels))}.")
        return (f"INAURA found only weak evidence related to {label}, which is "
                f"not enough to verify the capability.")
    return f"INAURA did not find sufficient evidence for {label}."


def build_capability_explanation(
    capability: Dict[str, Any],
    grouped: Dict[str, List[dict]],
    support: Any,
    status: str,
    canonical_skill: Any = None,
) -> Dict[str, Any]:
    """Explain WHY a capability got its status (deterministic, read-only).

    Inputs are the curated blueprint capability, the existing grouped
    evidence, and the already-computed support/status. Output adds no new
    scoring: strength mirrors support thresholds, matched/missing signals
    mirror per-rule _rule_matches() outcomes.

    Refinement: for the REST APIs skill, generic REST presence is kept as
    contextual and does not count as capability-specific support; the summary
    and strength use the capability-specific support instead. Pass
    canonical_skill for that split; when omitted the legacy behaviour is
    preserved for backwards compat.
    """
    capability = capability if isinstance(capability, dict) else {}
    grouped = grouped if isinstance(grouped, dict) else {}
    # Capability-specific strength/status for REST APIs; otherwise overall.
    try:
        canon = _canon(canonical_skill) if canonical_skill else ""
    except Exception:
        canon = ""
    if canon == "REST APIs":
        specific_support, _matched_w, _total_w = _specific_support(
            capability, grouped, canonical_skill
        )
        has_generic = _has_generic_rest_evidence(capability, grouped, canonical_skill)
        # Strength mirrors capability-specific support for REST; this is
        # presentation only — the capability's top-level `support` field keeps
        # the original overall support from evaluate_capability().
        strength_value = specific_support
        # Refine status for explanation (generic alone stays unverified).
        specific, _generic = _split_capability_rules(capability, canonical_skill)
        if not specific:
            # No capability-specific rules exist — generic alone never proves
            # validation / documentation etc. Report unverified even though
            # overall support may be 1.0.
            refined_status = STATUS_UNVERIFIED
        elif specific_support == 0:
            refined_status = STATUS_UNVERIFIED
        else:
            refined_status = build_status_reason(status)  # placeholder to keep import order
            refined_status = status  # will be overwritten below with specific-based
            try:
                v = float(specific_support or 0.0)
            except (TypeError, ValueError):
                v = 0.0
            if v >= DEMONSTRATED_SUPPORT:
                refined_status = STATUS_DEMONSTRATED
            elif v >= DEVELOPING_SUPPORT:
                refined_status = STATUS_DEVELOPING
            else:
                refined_status = STATUS_UNVERIFIED
        matched = build_matched_signals(capability, grouped, canonical_skill)
        missing = build_missing_signals(capability, grouped, canonical_skill)
        return {
            "summary": build_capability_explanation_summary(
                capability.get("title"), str(refined_status or ""),
                specific_support,
                [m.get("signal", "") for m in matched],
                [m.get("signal", "") for m in missing],
                canonical_skill,
                has_generic,
            ),
            "status_reason": build_status_reason(refined_status),
            "evidence_strength": classify_evidence_strength(specific_support),
            "matched_signals": matched,
            "missing_signals": missing,
        }
    try:
        value = float(support or 0.0)
    except (TypeError, ValueError):
        value = 0.0
    matched = build_matched_signals(capability, grouped, canonical_skill)
    missing = build_missing_signals(capability, grouped, canonical_skill)
    return {
        "summary": build_capability_explanation_summary(
            capability.get("title"), str(status or ""),
            value,
            [m.get("signal", "") for m in matched],
            [m.get("signal", "") for m in missing],
            canonical_skill,
            False,
        ),
        "status_reason": build_status_reason(status),
        "evidence_strength": classify_evidence_strength(value),
        "matched_signals": matched,
        "missing_signals": missing,
    }


def get_capability_blueprint(skill: Any) -> List[Dict[str, Any]]:
    """Curated capability definitions for a canonical skill (slug or name)."""
    text = str(skill or "").strip()
    if not text:
        return []
    try:
        slug = normalize_skill_slug(text) or ""
    except Exception:
        slug = ""
    if slug and slug in CAPABILITY_BLUEPRINTS:
        return CAPABILITY_BLUEPRINTS[slug]
    lowered = text.lower().replace(" ", "_")
    return CAPABILITY_BLUEPRINTS.get(lowered, [])


def validate_blueprints() -> List[str]:
    """
    Audit the curated catalog. Returns error strings (empty = valid):
    unique ids, non-empty titles/abilities, well-formed rules, and every
    referenced skill resolvable through the canonical taxonomy.
    """
    errors: List[str] = []
    seen_ids = set()
    for slug, capabilities in CAPABILITY_BLUEPRINTS.items():
        if normalize_skill(slug) is None and slug not in (
                (normalize_skill_slug(slug) or ""),):
            # slug keys must themselves be canonical slugs
            pass
        if not isinstance(capabilities, list) or not capabilities:
            errors.append(f"{slug}: no capabilities defined")
            continue
        for cap in capabilities:
            cap_id = str(cap.get("id") or "")
            if not cap_id:
                errors.append(f"{slug}: capability missing id")
                continue
            if cap_id in seen_ids:
                errors.append(f"{slug}: duplicate capability id '{cap_id}'")
            seen_ids.add(cap_id)
            if not str(cap.get("title") or "").strip():
                errors.append(f"{cap_id}: missing title")
            if not [a for a in (cap.get("observable_abilities") or []) if str(a).strip()]:
                errors.append(f"{cap_id}: no observable abilities")
            if not str(cap.get("action") or "").strip():
                errors.append(f"{cap_id}: missing next action")
            for rule in (cap.get("evidence_rules") or []):
                if not isinstance(rule, dict) or rule.get("kind") not in (
                        "signal", "patterns", "files", "related_present"):
                    errors.append(f"{cap_id}: malformed evidence rule {rule!r}")
                    continue
                for skill_ref in ([rule.get("skill")] if rule.get("skill")
                                  else list(rule.get("skills") or [])):
                    if skill_ref and normalize_skill(str(skill_ref)) is None:
                        errors.append(
                            f"{cap_id}: rule references unknown skill '{skill_ref}'")
    return errors


def _capability_relevance(capability: Dict[str, Any], requirement: Dict[str, Any],
                          role: str) -> List[str]:
    """Why this capability is expected for the role (deterministic)."""
    reasons: List[str] = []
    try:
        required_level = float(requirement.get("required_level", 0.0) or 0.0)
    except (TypeError, ValueError):
        required_level = 0.0
    try:
        interview = float(requirement.get("interview_relevance", 0.0) or 0.0)
    except (TypeError, ValueError):
        interview = 0.0
    if required_level >= 0.80:
        reasons.append(f"core requirement (level {required_level:.2f})")
    if interview >= 0.80:
        reasons.append("interview-critical")
    if str(requirement.get("role_relevance") or "").upper() == "CORE":
        reasons.append(f"core for {role}")
    return reasons[:3]


def _chunk_topics_for_skill(requirement: Dict[str, Any]) -> List[str]:
    """Chunk topics backing this requirement (references only, capped)."""
    topics: List[str] = []
    for chunk in (requirement.get("supporting_chunks") or []):
        if not isinstance(chunk, dict):
            continue
        topic = str(chunk.get("topic") or "").strip()
        if topic and topic not in topics:
            topics.append(topic)
        if len(topics) >= 2:
            break
    return topics


def _next_actions(capability: Dict[str, Any], canonical_skill: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """Deterministic next actions: curated action + roadmap catalog template
    steps + catalog resources. No separate roadmap engine is created."""
    actions: List[str] = []
    curated = str(capability.get("action") or "").strip()
    if curated:
        actions.append(curated)
    try:
        template = get_template_for_skill(canonical_skill) or {}
    except Exception:
        template = {}
    for slot in ("practice", "project"):
        try:
            step = str(template.get(slot) or "").strip()
        except AttributeError:
            step = ""
        if step and step not in actions:
            actions.append(f"{slot.capitalize()}: {step}")
    resources: List[Dict[str, str]] = []
    try:
        for res in (get_resources_for_skill(canonical_skill) or [])[:2]:
            if not isinstance(res, dict):
                continue
            title = str(res.get("title") or "").strip()
            url = str(res.get("url") or "").strip()
            if title and url:
                resources.append({
                    "title": title,
                    "url": url,
                    "provider": str(res.get("provider") or ""),
                })
    except Exception:
        pass
    return actions[:3], resources


def build_skill_capability(
    role: str,
    requirement: Optional[Dict[str, Any]],
    grouped: Dict[str, List[dict]],
    assessment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the capability map for one required skill. Pure function of
    (requirement, grouped signals, assessment): no I/O, no scoring changes.
    Assessment contributes proficiency/confidence context only.
    """
    assessment = assessment or {}
    skill = str((requirement or {}).get("skill") or assessment.get("canonical_name")
                or assessment.get("skill") or "").strip()
    canonical = _canon(skill) or skill
    try:
        slug = normalize_skill_slug(canonical) or canonical.lower().replace(" ", "_")
    except Exception:
        slug = canonical.lower().replace(" ", "_")

    try:
        proficiency = float(assessment.get("proficiency", 0.0) or 0.0)
    except (TypeError, ValueError):
        proficiency = 0.0
    try:
        confidence = float(assessment.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    base: Dict[str, Any] = {
        "skill": canonical or skill,
        "slug": slug,
        "role": role,
        # Additive context for the Career Track view: the requirement's category and
        # the canonical learning prerequisites from skill_dependencies (read-only).
        "category": str((requirement or {}).get("skill_category") or ""),
        "prerequisites": skill_dependencies.get_prerequisites(slug),
        "proficiency": proficiency,
        "confidence": confidence,
        "required_level": 0.0,
        "importance": 0.0,
        "status": STATUS_INSUFFICIENT_DATA,
        "priority": 0.0,
        "priority_category": "covered",
        "industry_expectations": [],
        "capabilities": [],
        "demonstrated_capabilities": [],
        "missing_capabilities": [],
        "evidence_gap": [],
        "skill_gap": [],
        "evidence_sources": [],
        "requirement": {},
        "explanation": "",
        "what_inaura_knows": _empty_what_inaura_knows(
            f"INAURA has limited evidence about how {canonical or skill} "
            "is used in practice."
        ),
    }

    if not requirement:
        base["explanation"] = (
            f"No industry requirement for {canonical or skill} under role '{role}': "
            "INAURA cannot define expected capabilities without industry evidence."
        )
        base["what_inaura_knows"] = _empty_what_inaura_knows(
            f"INAURA has limited evidence about how {canonical or skill} "
            "is used in practice."
        )
        return base
    blueprint = get_capability_blueprint(slug) or get_capability_blueprint(canonical)
    if not blueprint:
        base.update(_requirement_context(requirement, role))
        base["explanation"] = (
            f"INAURA has no capability definition for {canonical}: industry "
            "expectations are not invented to fill the UI."
        )
        base["what_inaura_knows"] = _empty_what_inaura_knows(
            f"INAURA has limited evidence about how {canonical} is used in practice."
        )
        return base

    base.update(_requirement_context(requirement, role))
    try:
        importance = float(requirement.get("importance", 0.5) or 0.5)
    except (TypeError, ValueError):
        importance = 0.5
    try:
        demand = float(requirement.get("demand", 0.5) or 0.5)
    except (TypeError, ValueError):
        demand = 0.5
    try:
        interview = float(requirement.get("interview_relevance", 0.5) or 0.5)
    except (TypeError, ValueError):
        interview = 0.5
    try:
        industry_confidence = float(requirement.get("industry_confidence", 0.85) or 0.85)
    except (TypeError, ValueError):
        industry_confidence = 0.85

    skill_signals = grouped.get(canonical, [])
    if not skill_signals:
        for key, sigs in grouped.items():
            if _canon(key) == canonical:
                skill_signals = sigs
                break
    has_impl = _has_implementation(skill_signals)

    # Industry expectations: every blueprint capability annotated with why
    # the role expects it, plus requirement + chunk provenance.
    chunk_topics = _chunk_topics_for_skill(requirement)
    expectations = []
    for cap in blueprint:
        relevance = _capability_relevance(cap, requirement, role)
        for topic in chunk_topics:
            marker = f"highlighted in {topic}"
            if marker not in relevance and len(relevance) < 3:
                relevance.append(marker)
        expectations.append({
            "capability_id": cap.get("id"),
            "title": cap.get("title"),
            "detail": cap.get("summary"),
            "relevance": relevance,
        })

    capabilities_out = []
    demonstrated_out = []
    missing_out = []
    evidence_gap_titles: List[str] = []
    skill_gap_titles: List[str] = []
    best_priority = 0.0
    best_category = "covered"

    for cap in blueprint:
        evaluated = evaluate_capability(cap, grouped)
        support = evaluated["support"]
        # Interpretation layer (adds status + statement only; support and
        # evidence preserved verbatim from evaluate_capability).
        # Refinement for REST APIs: generic skill-level REST presence is
        # contextual, not capability-specific. A capability with no
        # capability-specific evidence remains unverified even if generic
        # REST support is moderate. This is explanation/presentation only —
        # `support` and `demonstrated` keep the original overall scoring.
        is_rest = _canon(canonical) == "REST APIs"
        if is_rest:
            specific_support, _matched_w, _total_w = _specific_support(
                cap, grouped, canonical
            )
            specific_rules, _generic_rules = _split_capability_rules(cap, canonical)
            has_generic = _has_generic_rest_evidence(cap, grouped, canonical)
            if not specific_rules:
                # No capability-specific rule exists for this capability
                # (e.g. Validate, Document). Generic REST alone never proves it.
                knowledge_status = STATUS_UNVERIFIED
            elif specific_support == 0:
                knowledge_status = STATUS_UNVERIFIED
            elif specific_support >= DEMONSTRATED_SUPPORT:
                knowledge_status = STATUS_DEMONSTRATED
            elif specific_support >= DEVELOPING_SUPPORT:
                knowledge_status = STATUS_DEVELOPING
            else:
                knowledge_status = STATUS_UNVERIFIED
            # Keep specific values for the demonstrated check below.
            _rest_specific_support = specific_support
            _rest_specific_rules = specific_rules
        else:
            knowledge_status = classify_capability_status(support, has_impl)
            _rest_specific_support = None  # type: ignore
            _rest_specific_rules = []  # type: ignore
        knowledge_statement = build_capability_knowledge_statement(
            cap.get("title"), support, knowledge_status, evaluated["evidence"]
        )
        # Phase 2: explain WHY this status was assigned (read-only layer over
        # the same blueprint rules and grouped evidence; scoring untouched).
        explanation = build_capability_explanation(
            cap, grouped, support, knowledge_status, canonical
        )
        entry = {
            "id": cap.get("id"),
            "title": cap.get("title"),
            "summary": cap.get("summary"),
            "observable_abilities": list(cap.get("observable_abilities") or []),
            "related_skills": list(cap.get("related_skills") or []),
            "support": support,
            "evidence": evaluated["evidence"],
            "status": knowledge_status,
            "knowledge_statement": knowledge_statement,
            "capability_explanation": explanation,
        }
        capabilities_out.append(entry)
        # For REST APIs, demonstrated requires capability-specific support;
        # generic REST presence alone never demonstrates validation / docs etc.
        if is_rest:
            if _rest_specific_rules and _rest_specific_support >= DEMONSTRATED_SUPPORT:
                strengths = [float(s.get("signal_strength", s.get("signal_value", 0.0)) or 0.0)
                             for s in _signals_for_evidence(grouped, cap, evaluated["evidence"])]
                cap_conf = round(max(strengths) if strengths else support, 3)
                demonstrated_out.append({
                    "id": cap.get("id"),
                    "title": cap.get("title"),
                    "support": support,
                    "confidence": cap_conf,
                    "evidence": evaluated["evidence"],
                })
                continue
        elif evaluated["demonstrated"]:
            strengths = [float(s.get("signal_strength", s.get("signal_value", 0.0)) or 0.0)
                         for s in _signals_for_evidence(grouped, cap, evaluated["evidence"])]
            cap_conf = round(max(strengths) if strengths else support, 3)
            demonstrated_out.append({
                "id": cap.get("id"),
                "title": cap.get("title"),
                "support": support,
                "confidence": cap_conf,
                "evidence": evaluated["evidence"],
            })
            continue
        # Status-consistency fix: STILL DEVELOP derives from the same
        # deterministic knowledge status (single source of truth).
        # - developing: support >= DEVELOPING_SUPPORT with partial evidence
        # - unverified (support < threshold): reported as evidence_gap
        #   ("Evidence gap" / "Needs verification"), never "Developing"
        # - confirmed_gap: genuine gap already identified by existing logic
        #   (has_impl + support == 0), never from absence alone.
        if knowledge_status == STATUS_DEVELOPING:
            missing_status = STATUS_DEVELOPING
        elif knowledge_status == STATUS_CONFIRMED_GAP:
            missing_status = STATUS_CONFIRMED_GAP
        else:
            missing_status = STATUS_EVIDENCE_GAP
        # Priority calculation unchanged: same engine, same inputs, same
        # gap_kind mapping (skill_gap if has_impl else evidence_gap).
        gap_kind = STATUS_SKILL_GAP if has_impl else STATUS_EVIDENCE_GAP
        priority, category, _breakdown = engine.calculate_prioritized_gap(
            gap_val=round(1.0 - support, 3),
            importance=importance,
            demand=demand,
            student_confidence=confidence,
            interview_relevance=interview,
            industry_confidence=industry_confidence,
            gap_type=gap_kind,
        )
        actions, resources = _next_actions(cap, canonical)
        missing_out.append({
            "id": cap.get("id"),
            "title": cap.get("title"),
            "support": support,
            "status": missing_status,
            "priority": priority,
            "priority_category": category,
            "next_actions": actions,
            "resources": resources,
            "evidence": evaluated["evidence"],
        })
        if missing_status == STATUS_CONFIRMED_GAP:
            # Backwards compat: confirmed gaps still populate the legacy
            # skill_gap title list (same membership as before: support == 0
            # with skill-level implementation evidence).
            skill_gap_titles.append(str(cap.get("title")))
        elif missing_status == STATUS_EVIDENCE_GAP:
            evidence_gap_titles.append(str(cap.get("title")))
        # developing capabilities are partial (support >= DEVELOPING_SUPPORT),
        # not gaps: listed in missing_capabilities, in neither gap list.
        if priority > best_priority:
            best_priority = priority
            best_category = category

    # Skill-level evidence provenance across the skill's own signals.
    evidence_sources = _dedupe_evidence(
        [_provenance_entry(s) for s in skill_signals]
    )[:10]

    if str(requirement.get("evidence_strength") or "").lower() == "insufficient":
        status = STATUS_INDUSTRY_GAP
        explanation = (
            f"Industry evidence for {canonical} under role '{role}' is too thin "
            "to set firm expectations; shown capabilities use cautious baselines."
        )
    elif len(demonstrated_out) == len(blueprint):
        status = STATUS_DEMONSTRATED
        explanation = (
            f"All {len(blueprint)} expected {canonical} capabilities are demonstrated."
        )
    elif demonstrated_out or any(c["support"] > 0 for c in capabilities_out):
        status = STATUS_DEVELOPING
        explanation = (
            f"{len(demonstrated_out)} of {len(blueprint)} expected {canonical} "
            "capabilities demonstrated; the rest are developing or missing."
        )
    elif skill_gap_titles:
        status = STATUS_SKILL_GAP
        explanation = (
            f"INAURA sees {canonical} implementation evidence but not the expected "
            "capabilities listed below."
        )
    else:
        status = STATUS_EVIDENCE_GAP
        explanation = (
            f"No evidence found for the expected {canonical} capabilities. Note: "
            "this indicates absence of submitted evidence, not confirmed inability."
        )

    what_knows = build_what_inaura_knows(canonical, capabilities_out, skill_signals)

    base.update({
        "industry_expectations": expectations,
        "capabilities": capabilities_out,
        "demonstrated_capabilities": demonstrated_out,
        "missing_capabilities": missing_out,
        "evidence_gap": evidence_gap_titles,
        "skill_gap": skill_gap_titles,
        "evidence_sources": evidence_sources,
        "status": status,
        "priority": best_priority,
        "priority_category": best_category,
        "explanation": explanation,
        "what_inaura_knows": what_knows,
    })
    return base


def _requirement_context(requirement: Dict[str, Any], role: str) -> Dict[str, Any]:
    """Shared requirement-derived fields (provenance for 'why required')."""
    try:
        required_level = float(requirement.get("required_level", 0.0) or 0.0)
    except (TypeError, ValueError):
        required_level = 0.0
    try:
        importance = float(requirement.get("importance", 0.0) or 0.0)
    except (TypeError, ValueError):
        importance = 0.0
    chunks = requirement.get("supporting_chunks") or []
    chunk_refs = []
    if isinstance(chunks, list):
        for chunk in chunks[:3]:
            if not isinstance(chunk, dict):
                continue
            chunk_refs.append({
                "chunk_id": chunk.get("chunk_id", chunk.get("id")),
                "role": chunk.get("role"),
                "topic": chunk.get("topic"),
                "source": chunk.get("source"),
                "source_url": chunk.get("source_url"),
            })
    return {
        "required_level": required_level,
        "importance": importance,
        "requirement": {
            "source": requirement.get("source", ""),
            "source_url": requirement.get("source_url"),
            "source_quality": requirement.get("source_quality"),
            "evidence_strength": requirement.get("evidence_strength", ""),
            "required_level": required_level,
            "importance": importance,
            "role_relevance": requirement.get("role_relevance", ""),
            "evidence_context": requirement.get("evidence_context", ""),
            "supporting_chunks": chunk_refs,
        },
    }


def _signals_for_evidence(grouped: Dict[str, List[dict]], capability: Dict[str, Any],
                           evidence: List[Dict[str, Any]]) -> List[dict]:
    """Signals backing one capability's evidence (for confidence context)."""
    skills = set()
    for rule in (capability.get("evidence_rules") or []):
        if not isinstance(rule, dict):
            continue
        if rule.get("skill"):
            skills.add(_canon(rule.get("skill")))
        for extra in (rule.get("skills") or []):
            skills.add(_canon(extra))
    out: List[dict] = []
    for skill in skills:
        out.extend(grouped.get(skill, []))
    return out


def build_capability_map_for_user(
    user_id: str,
    target_role: Optional[str] = None,
    client: Any = None,
    skill: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the full Skill Capability Map for a user + role.

    Reuses the existing pipeline pieces (profile/evidence loading, signal
    extraction, normalization, aggregation, requirements, assessments) and
    performs NO persistence and NO scoring changes: proficiency/confidence
    are read from assessments, never recomputed here.
    """
    profile = ars.load_profile(user_id)
    del profile  # validated for existence only; profile fields unused here.

    if client is None:
        try:
            client = get_supabase_client()
        except Exception:
            client = None

    role = str(target_role or "").strip()
    if not role:
        try:
            state = analysis_service.get_state(user_id)
        except Exception:
            state = None
        if isinstance(state, dict) and state.get("target_role"):
            role = str(state["target_role"]).strip()
    if not role:
        raise HTTPException(status_code=400, detail="Target role required")

    evidence, projects, certifications = ars.load_evidence(user_id)
    requirements = ars.load_industry_requirements(role)
    if not requirements:
        raise HTTPException(
            status_code=400,
            detail=f"No industry requirements found for role '{role}'",
        )
    signals = ars.extract_skill_signals(evidence, projects, certifications)
    grouped = ars.aggregate_skills(ars.normalize_signals(signals, client))
    req_map = ars.build_requirements_map(requirements, client)
    try:
        overrides = ars.load_user_overrides(user_id, client)
    except Exception:
        overrides = {}
    assessments = ars.calculate_assessments(grouped, req_map, client, overrides)
    assessments_by_skill = {
        str(a.get("canonical_name") or a.get("skill") or ""): a for a in assessments
    }

    wanted: Optional[str] = None
    if skill and str(skill).strip():
        wanted = _canon(skill)
        if not wanted:
            raise HTTPException(status_code=400, detail="Unknown skill filter")

    skills_out = []
    for req in requirements:
        canonical = _canon(req.get("skill", ""))
        if not canonical:
            continue
        if wanted and canonical != wanted:
            continue
        assessment = assessments_by_skill.get(canonical)
        if assessment is None:
            for key, candidate in assessments_by_skill.items():
                if _canon(key) == canonical:
                    assessment = candidate
                    break
        skills_out.append(build_skill_capability(role, req, grouped, assessment))

    counts = {status: 0 for status in _SKILL_STATUSES}
    for entry in skills_out:
        counts[entry.get("status", STATUS_INSUFFICIENT_DATA)] = \
            counts.get(entry.get("status", STATUS_INSUFFICIENT_DATA), 0) + 1

    return {
        "role": role,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "capability_model_version": CAPABILITY_MODEL_VERSION,
        "engine_version": engine.ENGINE_VERSION,
        "skills": skills_out,
        "summary": {
            "total_skills": len(skills_out),
            "by_status": counts,
        },
    }


CAPABILITY_MODEL_VERSION = "capability-v2"

# Support thresholds (documented, deterministic).
DEMONSTRATED_SUPPORT = 0.75  # >= this fraction of rule weight -> demonstrated
DEVELOPING_SUPPORT = 0.40  # >= this and < demonstrated -> developing
# Support in (0, 0.75) -> developing (legacy gap ladder); support == 0 ->
# missing (gap kind below). The "What INAURA knows" interpretation layer
# below uses DEMONSTRATED_SUPPORT / DEVELOPING_SUPPORT; the legacy
# missing_capabilities ladder is intentionally untouched.

# Skill statuses. Reuses engine gap vocabulary where it exists.
STATUS_DEMONSTRATED = "demonstrated"
STATUS_DEVELOPING = "developing"
STATUS_UNVERIFIED = "unverified"
STATUS_CONFIRMED_GAP = "confirmed_gap"
STATUS_EVIDENCE_GAP = "evidence_gap"
STATUS_SKILL_GAP = "skill_gap"
STATUS_INDUSTRY_GAP = "industry_gap"
STATUS_INSUFFICIENT_DATA = "insufficient_industry_data"

_SKILL_STATUSES = (
    STATUS_DEMONSTRATED,
    STATUS_DEVELOPING,
    STATUS_EVIDENCE_GAP,
    STATUS_SKILL_GAP,
    STATUS_INDUSTRY_GAP,
    STATUS_INSUFFICIENT_DATA,
)


# ---------------------------------------------------------------------------
# Curated capability blueprints, keyed by canonical skill slug.
#
# Same standing as roadmap_catalog templates: hand-written product content,
# not runtime invention. Each capability carries evidence rules evaluated
# against grouped student signals (see _rule_matches).
#
# Rule kinds (all fields optional unless noted):
#   {"kind": "signal", "skill": canonical, "min_depth": int,
#    "sources": [source_type...], "usage_in": [usage_status...],
#    "min_files": int}
#     - any signal for `skill` meeting every stated constraint.
#   {"kind": "patterns", "skill": canonical, "any_of": [pattern ids]}
#     - detected_usage_patterns for `skill` contains any listed id.
#   {"kind": "files", "skill": canonical, "min_count": int}
#     - total relevant_files across `skill` signals >= min_count.
#   {"kind": "related_present", "skills": [canonical...]}
#     - any signal exists for any listed skill (breadth only).
# Rule weight defaults to 1.0; support = matched_weight / total_weight.
# ---------------------------------------------------------------------------

def _sig_rule(skill: str, min_depth: int = 0, **kw: Any) -> Dict[str, Any]:
    rule: Dict[str, Any] = {"kind": "signal", "skill": skill, "min_depth": min_depth}
    rule.update(kw)
    return rule


def _pat_rule(skill: str, *pattern_ids: str, weight: float = 1.0) -> Dict[str, Any]:
    return {"kind": "patterns", "skill": skill, "any_of": list(pattern_ids),
            "weight": weight}


def _files_rule(skill: str, min_count: int, weight: float = 1.0) -> Dict[str, Any]:
    return {"kind": "files", "skill": skill, "min_count": min_count,
            "weight": weight}


def _rel_rule(*skills: str, weight: float = 0.5) -> Dict[str, Any]:
    return {"kind": "related_present", "skills": list(skills), "weight": weight}


CAPABILITY_BLUEPRINTS: Dict[str, List[Dict[str, Any]]] = {
    "python": [
        {
            "id": "python-fundamentals",
            "title": "Python fundamentals",
            "summary": "Write correct Python using functions, modules, and standard data structures.",
            "observable_abilities": [
                "Write functions and modules with clear structure",
                "Use lists, dicts, sets, and comprehensions appropriately",
                "Manage dependencies with requirements files or pyproject",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Python", min_depth=3),
                _files_rule("Python", 1),
            ],
            "action": "Complete a Python fundamentals course track, then refactor a script into tested modules.",
        },
        {
            "id": "python-oop",
            "title": "OOP in Python",
            "summary": "Model problems with classes, encapsulation, and composition.",
            "observable_abilities": [
                "Design classes with clear responsibilities",
                "Apply encapsulation, inheritance, and composition",
            ],
            "related_skills": ["OOP"],
            "evidence_rules": [
                _sig_rule("Python", min_depth=3),
                _sig_rule("OOP", min_depth=1, weight=0.5),
            ],
            "action": "Refactor a procedural script into classes with unit tests for each class.",
        },
        {
            "id": "python-rest-apis",
            "title": "Build REST APIs",
            "summary": "Build maintainable backend services exposing validated HTTP APIs.",
            "observable_abilities": [
                "Build maintainable backend services",
                "Build REST APIs",
                "Implement validation and error handling",
            ],
            "related_skills": ["REST APIs", "SQL"],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=3),
                _pat_rule("REST APIs", "fastapi_app", "flask_app", "route_decorator", "api_router"),
            ],
            "action": "Build a production-style asynchronous API with tests.",
        },
        {
            "id": "python-testing",
            "title": "Write automated tests",
            "summary": "Verify Python code with automated unit and integration tests.",
            "observable_abilities": [
                "Write automated tests",
                "Structure testable code and fixtures",
            ],
            "related_skills": ["Testing"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=2),
                _pat_rule("Testing", "test_def", "test_import"),
            ],
            "action": "Add pytest coverage to an existing module until edge cases are tested.",
        },
        {
            "id": "python-async",
            "title": "Build asynchronous services",
            "summary": "Use async programming for I/O-heavy backend workloads.",
            "observable_abilities": [
                "Build asynchronous services",
                "Use async/await for I/O-bound work correctly",
            ],
            "related_skills": ["REST APIs"],
            "evidence_rules": [
                _sig_rule("Python", min_depth=3),
                _pat_rule("REST APIs", "fastapi_app", "api_router"),
                _files_rule("Python", 3, weight=0.5),
            ],
            "action": "Build an async FastAPI service with PostgreSQL, Docker and automated tests.",
        },
        {
            "id": "python-data",
            "title": "Work with databases",
            "summary": "Persist and query data from Python using SQL and drivers.",
            "observable_abilities": [
                "Work with databases",
                "Write parameterized queries and manage connections",
            ],
            "related_skills": ["SQL", "PostgreSQL", "DBMS"],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=2),
                _pat_rule("PostgreSQL", "sql_query", "pg_import"),
            ],
            "action": "Add a PostgreSQL-backed persistence layer with migrations to a project.",
        },
        {
            "id": "python-packaging",
            "title": "Package management",
            "summary": "Declare, pin, and isolate project dependencies reproducibly.",
            "observable_abilities": [
                "Declare dependencies in manifests",
                "Pin versions with lockfiles or constraints",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Python", min_depth=2),
                _rel_rule("Testing", weight=0.5),
            ],
            "action": "Convert a project to pyproject with pinned dependencies and a clean install.",
        },
    ],
    "javascript": [
        {
            "id": "js-fundamentals",
            "title": "JavaScript fundamentals",
            "summary": "Write correct modern JavaScript for browser and server runtimes.",
            "observable_abilities": [
                "Use ES6+ syntax, modules, and array methods",
                "Handle asynchronous code with promises and async/await",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("JavaScript", min_depth=3),
                _files_rule("JavaScript", 1),
            ],
            "action": "Complete 20 JavaScript exercises covering arrays, async, and modules.",
        },
        {
            "id": "js-async",
            "title": "Asynchronous JavaScript",
            "summary": "Coordinate async work without race conditions or callback pyramids.",
            "observable_abilities": [
                "Use async/await and promise composition correctly",
                "Handle async errors and loading states",
            ],
            "related_skills": ["REST APIs"],
            "evidence_rules": [
                _sig_rule("JavaScript", min_depth=3),
                _pat_rule("REST APIs", "http_client"),
            ],
            "action": "Build a UI that fetches, caches, and gracefully fails on API errors.",
        },
        {
            "id": "js-dom",
            "title": "DOM interaction",
            "summary": "Build interactive pages that respond to user input.",
            "observable_abilities": [
                "Manipulate the DOM in response to events",
                "Manage client-side state consistently",
            ],
            "related_skills": ["HTML", "CSS"],
            "evidence_rules": [
                _sig_rule("JavaScript", min_depth=3),
                _rel_rule("HTML", "CSS", weight=0.5),
            ],
            "action": "Build an interactive page with form validation and state handling.",
        },
        {
            "id": "js-testing",
            "title": "Test JavaScript code",
            "summary": "Verify behavior with unit tests and assertions.",
            "observable_abilities": [
                "Write unit tests with assertions",
                "Test async code paths",
            ],
            "related_skills": ["Testing"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=2),
                _pat_rule("Testing", "test_def", "test_import"),
            ],
            "action": "Add Jest/Vitest coverage to an existing module.",
        },
        {
            "id": "js-tooling",
            "title": "Node.js tooling basics",
            "summary": "Run scripts and manage packages with Node.js tooling.",
            "observable_abilities": [
                "Run Node.js scripts and manage npm dependencies",
            ],
            "related_skills": ["Node.js"],
            "evidence_rules": [
                _sig_rule("Node.js", min_depth=2),
            ],
            "action": "Script a small Node.js CLI with npm scripts.",
        },
    ],
    "typescript": [
        {
            "id": "ts-types",
            "title": "Static typing",
            "summary": "Model data with types, interfaces, and generics.",
            "observable_abilities": [
                "Annotate functions and data with types",
                "Define interfaces and type aliases",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("TypeScript", min_depth=3),
                _pat_rule("TypeScript", "type_annotation", "interface_def", "type_alias"),
            ],
            "action": "Migrate a JavaScript module to strict TypeScript.",
        },
        {
            "id": "ts-config",
            "title": "TypeScript project configuration",
            "summary": "Configure strict, maintainable TypeScript projects.",
            "observable_abilities": [
                "Configure tsconfig for strictness",
                "Keep typed boundaries between modules",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("TypeScript", min_depth=2),
            ],
            "action": "Enable strict mode on a project and fix the resulting errors.",
        },
        {
            "id": "ts-react",
            "title": "Typed React components",
            "summary": "Build type-safe React components and hooks.",
            "observable_abilities": [
                "Type component props and hook state",
            ],
            "related_skills": ["React"],
            "evidence_rules": [
                _sig_rule("TypeScript", min_depth=3),
                _sig_rule("React", min_depth=3),
            ],
            "action": "Convert two React components to fully typed props and state.",
        },
        {
            "id": "ts-node",
            "title": "Type-safe backend code",
            "summary": "Write typed server-side TypeScript services.",
            "observable_abilities": [
                "Type API boundaries and service layers",
            ],
            "related_skills": ["Node.js", "Express", "REST APIs"],
            "evidence_rules": [
                _sig_rule("TypeScript", min_depth=3),
                _rel_rule("Node.js", "Express", "REST APIs", weight=0.5),
            ],
            "action": "Add typed request/response models to an Express API.",
        },
    ],
    "react": [
        {
            "id": "react-components",
            "title": "Build components",
            "summary": "Compose user interfaces from reusable components.",
            "observable_abilities": [
                "Build reusable function and class components",
                "Structure component trees sensibly",
            ],
            "related_skills": ["JavaScript"],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _pat_rule("React", "component_func", "component_class", "jsx_component"),
            ],
            "action": "Build three reusable components with documented props.",
        },
        {
            "id": "react-hooks",
            "title": "Manage state with hooks",
            "summary": "Handle local and shared state with hooks and effects.",
            "observable_abilities": [
                "Manage state with hooks",
                "Handle side effects correctly",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _pat_rule("React", "hook_useState", "hook_useEffect", "hook_generic"),
            ],
            "action": "Refactor class components to hooks with effect cleanup.",
        },
        {
            "id": "react-routing",
            "title": "Client-side routing",
            "summary": "Navigate between views with routes and parameters.",
            "observable_abilities": [
                "Configure routes, links, and URL parameters",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _pat_rule("React", "router"),
            ],
            "action": "Add routed views with parameterized URLs to an app.",
        },
        {
            "id": "react-state",
            "title": "Shared state management",
            "summary": "Share state across components predictably.",
            "observable_abilities": [
                "Lift state or adopt a store where justified",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _pat_rule("React", "state_mgmt"),
                _files_rule("React", 3, weight=0.5),
            ],
            "action": "Introduce a store for cross-component state with selectors.",
        },
        {
            "id": "react-data",
            "title": "Consume REST APIs",
            "summary": "Fetch, cache, and render remote data with loading and error states.",
            "observable_abilities": [
                "Fetch REST data with loading and error states",
            ],
            "related_skills": ["REST APIs"],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _sig_rule("REST APIs", min_depth=2, weight=0.5),
            ],
            "action": "Build a dashboard that consumes a REST API with error states.",
        },
        {
            "id": "react-quality",
            "title": "Test and polish UI",
            "summary": "Verify responsive, accessible interfaces and their states.",
            "observable_abilities": [
                "Test responsiveness, accessibility, and error states",
            ],
            "related_skills": ["Testing", "Responsive Design"],
            "evidence_rules": [
                _sig_rule("React", min_depth=3),
                _sig_rule("Testing", min_depth=2, weight=0.5),
            ],
            "action": "Add component tests covering loading, error, and empty states.",
        },
    ],
    "nodejs": [
        {
            "id": "node-runtime",
            "title": "Node.js runtime basics",
            "summary": "Run JavaScript services on Node.js with core modules.",
            "observable_abilities": [
                "Use core modules (fs, path, http) appropriately",
                "Manage processes and environment configuration",
            ],
            "related_skills": ["JavaScript"],
            "evidence_rules": [
                _sig_rule("Node.js", min_depth=3),
                _pat_rule("Node.js", "node_require", "node_import", "process_api"),
            ],
            "action": "Build a Node.js CLI using core modules and env config.",
        },
        {
            "id": "node-servers",
            "title": "Run HTTP servers",
            "summary": "Serve HTTP traffic and manage server lifecycle.",
            "observable_abilities": [
                "Start, configure, and gracefully stop servers",
            ],
            "related_skills": ["Express", "REST APIs"],
            "evidence_rules": [
                _sig_rule("Node.js", min_depth=3),
                _pat_rule("Node.js", "server_listen"),
            ],
            "action": "Serve an API with graceful shutdown and health checks.",
        },
        {
            "id": "node-packages",
            "title": "Manage Node.js dependencies",
            "summary": "Declare and lock Node.js dependencies reproducibly.",
            "observable_abilities": [
                "Maintain package.json with locked dependencies",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Node.js", min_depth=2),
            ],
            "action": "Audit and pin dependencies, then reproduce installs cleanly.",
        },
        {
            "id": "node-async",
            "title": "Async server patterns",
            "summary": "Handle concurrent I/O without blocking the event loop.",
            "observable_abilities": [
                "Structure non-blocking I/O flows",
            ],
            "related_skills": ["Express"],
            "evidence_rules": [
                _sig_rule("Node.js", min_depth=3),
                _rel_rule("Express", weight=0.5),
            ],
            "action": "Refactor blocking I/O paths to async with load testing.",
        },
    ],
    "express": [
        {
            "id": "express-routes",
            "title": "Define Express routes",
            "summary": "Expose HTTP endpoints with Express routing.",
            "observable_abilities": [
                "Define routes with parameters and handlers",
            ],
            "related_skills": ["Node.js", "REST APIs"],
            "evidence_rules": [
                _sig_rule("Express", min_depth=3),
                _pat_rule("Express", "route_handler", "express_init"),
            ],
            "action": "Build CRUD routes with parameter validation.",
        },
        {
            "id": "express-middleware",
            "title": "Use middleware",
            "summary": "Compose cross-cutting behavior with middleware chains.",
            "observable_abilities": [
                "Write and order middleware (auth, logging, errors)",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Express", min_depth=3),
                _pat_rule("Express", "middleware"),
            ],
            "action": "Add auth, logging, and error middleware to an API.",
        },
        {
            "id": "express-routers",
            "title": "Modular routers",
            "summary": "Split large APIs into maintainable router modules.",
            "observable_abilities": [
                "Organize endpoints into mounted routers",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Express", min_depth=3),
                _pat_rule("Express", "router"),
                _files_rule("Express", 2, weight=0.5),
            ],
            "action": "Split a monolithic route file into mounted routers.",
        },
        {
            "id": "express-testing",
            "title": "Test Express APIs",
            "summary": "Verify endpoints with automated request tests.",
            "observable_abilities": [
                "Write endpoint tests covering success and failure paths",
            ],
            "related_skills": ["Testing"],
            "evidence_rules": [
                _sig_rule("Express", min_depth=3),
                _sig_rule("Testing", min_depth=2, weight=0.5),
            ],
            "action": "Add supertest coverage for all routes including errors.",
        },
    ],
    "rest_apis": [
        {
            "id": "rest-design",
            "title": "Design REST APIs",
            "summary": "Model resources with correct methods, status codes, and pagination.",
            "observable_abilities": [
                "Design resource-oriented endpoints",
                "Use HTTP methods and status codes correctly",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=3),
                _pat_rule("REST APIs", "route_decorator", "api_router", "express_route"),
            ],
            "action": "Design a versioned CRUD API with pagination and filtering.",
        },
        {
            "id": "rest-framework",
            "title": "Implement with a framework",
            "summary": "Ship working APIs with FastAPI, Flask, Express, or Django.",
            "observable_abilities": [
                "Build REST APIs",
                "Wire frameworks to services and data layers",
            ],
            "related_skills": ["Python", "Node.js"],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=3),
                _pat_rule("REST APIs", "fastapi_app", "flask_app", "django_view", "express_route"),
            ],
            "action": "Build a production-style REST API with FastAPI/Express (CRUD, auth, tests).",
        },
        {
            "id": "rest-validation",
            "title": "Validate input and handle errors",
            "summary": "Reject bad input clearly and fail predictably.",
            "observable_abilities": [
                "Implement validation and error handling",
                "Return consistent error responses",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=3),
                _files_rule("REST APIs", 2, weight=0.5),
            ],
            "action": "Add schema validation and uniform error responses to every endpoint.",
        },
        {
            "id": "rest-auth",
            "title": "Secure APIs",
            "summary": "Protect endpoints with authentication and authorization.",
            "observable_abilities": [
                "Add auth to endpoints appropriately",
            ],
            "related_skills": ["Application Security"],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=3),
                _rel_rule("Application Security", weight=0.5),
            ],
            "action": "Protect endpoints with token auth and role checks.",
        },
        {
            "id": "rest-docs",
            "title": "Document APIs",
            "summary": "Publish contracts consumers can implement against.",
            "observable_abilities": [
                "Write OpenAPI docs and test edge cases",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("REST APIs", min_depth=2),
            ],
            "action": "Write OpenAPI docs and test with edge cases.",
        },
        {
            "id": "rest-clients",
            "title": "Consume APIs",
            "summary": "Integrate third-party and internal APIs robustly.",
            "observable_abilities": [
                "Call APIs with retries, timeouts, and error handling",
            ],
            "related_skills": ["JavaScript", "Python"],
            "evidence_rules": [
                _pat_rule("REST APIs", "http_client"),
            ],
            "action": "Integrate two public APIs with retries and caching.",
        },
    ],
    "sql": [
        {
            "id": "sql-select",
            "title": "Query relational data",
            "summary": "Retrieve exactly the data needed with SELECT, filters, and JOINs.",
            "observable_abilities": [
                "Write SELECT queries with JOINs and filters",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=3),
                _pat_rule("SQL", "sql_select", "sql_query"),
            ],
            "action": "Complete 50 query exercises on realistic datasets.",
        },
        {
            "id": "sql-write",
            "title": "Modify relational data safely",
            "summary": "Insert, update, and delete rows with transactions in mind.",
            "observable_abilities": [
                "Write INSERT, UPDATE, and DELETE statements safely",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=3),
                _pat_rule("SQL", "sql_insert", "sql_update", "sql_delete"),
            ],
            "action": "Script a safe data migration with rollback steps.",
        },
        {
            "id": "sql-schema",
            "title": "Design schemas",
            "summary": "Model entities with tables, keys, and normalization.",
            "observable_abilities": [
                "Design and query a relational schema",
            ],
            "related_skills": ["DBMS"],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=3),
                _pat_rule("SQL", "sql_ddl"),
            ],
            "action": "Design and query a relational schema for an e-commerce app.",
        },
        {
            "id": "sql-perf",
            "title": "Optimize queries",
            "summary": "Diagnose slow queries with plans and indexes.",
            "observable_abilities": [
                "Explain query plans and optimize slow queries",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=3),
                _files_rule("SQL", 3, weight=0.5),
            ],
            "action": "Optimize a slow query using EXPLAIN and indexes.",
        },
        {
            "id": "sql-app",
            "title": "Use SQL from applications",
            "summary": "Integrate queries into services with safe parameterization.",
            "observable_abilities": [
                "Call parameterized queries from application code",
            ],
            "related_skills": ["Python", "DBMS"],
            "evidence_rules": [
                _sig_rule("SQL", min_depth=2),
                _pat_rule("SQL", "sql_cursor"),
            ],
            "action": "Replace string-built queries with parameterized calls.",
        },
    ],
    "postgresql": [
        {
            "id": "pg-queries",
            "title": "Query PostgreSQL",
            "summary": "Use PostgreSQL SQL fluently, including its extensions.",
            "observable_abilities": [
                "Write PostgreSQL queries and manage schemas",
            ],
            "related_skills": ["SQL"],
            "evidence_rules": [
                _sig_rule("PostgreSQL", min_depth=3),
                _pat_rule("PostgreSQL", "sql_query", "pg_import"),
            ],
            "action": "Port an app's queries to PostgreSQL-specific features.",
        },
        {
            "id": "pg-drivers",
            "title": "Connect from applications",
            "summary": "Wire services to PostgreSQL with drivers and pooling.",
            "observable_abilities": [
                "Configure drivers, pools, and transactions",
            ],
            "related_skills": ["Python", "Node.js"],
            "evidence_rules": [
                _sig_rule("PostgreSQL", min_depth=2),
                _pat_rule("PostgreSQL", "pg_import", "pg_config"),
            ],
            "action": "Add pooled connections and transactions to a service.",
        },
        {
            "id": "pg-modeling",
            "title": "Model PostgreSQL data",
            "summary": "Design tables, constraints, and indexes for Postgres.",
            "observable_abilities": [
                "Design tables with constraints and indexes",
            ],
            "related_skills": ["SQL", "DBMS"],
            "evidence_rules": [
                _sig_rule("PostgreSQL", min_depth=3),
                _pat_rule("PostgreSQL", "sql_ddl"),
            ],
            "action": "Design a schema with constraints, then load and index it.",
        },
        {
            "id": "pg-ops",
            "title": "Operate PostgreSQL locally",
            "summary": "Run Postgres reproducibly with configuration and backups in mind.",
            "observable_abilities": [
                "Run PostgreSQL via Compose with seeded data",
            ],
            "related_skills": ["Docker"],
            "evidence_rules": [
                _sig_rule("PostgreSQL", min_depth=2),
                _rel_rule("Docker", weight=0.5),
            ],
            "action": "Compose Postgres with seed data and backup scripts.",
        },
        {
            "id": "pg-perf",
            "title": "Tune PostgreSQL performance",
            "summary": "Find and fix slow Postgres queries.",
            "observable_abilities": [
                "Use EXPLAIN and indexes to tune queries",
            ],
            "related_skills": ["SQL"],
            "evidence_rules": [
                _sig_rule("PostgreSQL", min_depth=3),
                _files_rule("PostgreSQL", 2, weight=0.5),
            ],
            "action": "Tune three slow queries and document the plans.",
        },
    ],
    "docker": [
        {
            "id": "docker-images",
            "title": "Build container images",
            "summary": "Package applications into reproducible images.",
            "observable_abilities": [
                "Write Dockerfiles for applications",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=2),
                _pat_rule("Docker", "docker_from", "docker_run"),
            ],
            "action": "Containerize an existing frontend/backend service.",
        },
        {
            "id": "docker-compose",
            "title": "Orchestrate multi-service apps",
            "summary": "Run cooperating services with Compose networking and volumes.",
            "observable_abilities": [
                "Deploy a multi-service app (api + db) with docker-compose",
                "Configure service-to-service networking",
            ],
            "related_skills": ["PostgreSQL"],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=3),
                _pat_rule("Docker", "docker_from"),
                _files_rule("Docker", 2, weight=0.5),
            ],
            "action": "Containerize a backend and PostgreSQL service using Docker Compose and configure service-to-service networking.",
        },
        {
            "id": "docker-networking",
            "title": "Docker networking",
            "summary": "Connect containers securely across networks.",
            "observable_abilities": [
                "Configure container networks and published ports deliberately",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=3),
                _files_rule("Docker", 2, weight=0.5),
            ],
            "action": "Isolate frontend, API, and database networks in Compose.",
        },
        {
            "id": "docker-volumes",
            "title": "Persist container data",
            "summary": "Keep state across restarts with volumes and mounts.",
            "observable_abilities": [
                "Configure volumes for databases and uploads",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=2),
            ],
            "action": "Add named volumes and a backup routine to a Compose app.",
        },
        {
            "id": "docker-repro",
            "title": "Reproduce deployments",
            "summary": "Rebuild environments from scratch reliably.",
            "observable_abilities": [
                "Reproduce the deployment from scratch on a clean machine",
            ],
            "related_skills": ["CI/CD"],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=3),
                _rel_rule("CI/CD", weight=0.5),
            ],
            "action": "Reproduce the deployment from scratch on a clean machine.",
        },
        {
            "id": "docker-optimize",
            "title": "Optimize images",
            "summary": "Keep images small, cached, and secure.",
            "observable_abilities": [
                "Use multi-stage builds and minimal base images",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Docker", min_depth=3),
                _files_rule("Docker", 2, weight=0.5),
            ],
            "action": "Convert a Dockerfile to multi-stage and halve its size.",
        },
    ],
    "testing": [
        {
            "id": "testing-unit",
            "title": "Write unit tests",
            "summary": "Verify units in isolation with assertions and mocks.",
            "observable_abilities": [
                "Write unit tests with assertions and mocks",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=2),
                _pat_rule("Testing", "test_def", "test_import"),
            ],
            "action": "Write tests for an existing module to reach 80% coverage.",
        },
        {
            "id": "testing-integration",
            "title": "Write integration tests",
            "summary": "Verify components working together, including APIs and data.",
            "observable_abilities": [
                "Write integration tests for APIs and data flows",
            ],
            "related_skills": ["REST APIs", "SQL"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=3),
                _files_rule("Testing", 2, weight=0.5),
            ],
            "action": "Add integration tests covering API-to-database flows.",
        },
        {
            "id": "testing-pipeline",
            "title": "Run tests in CI",
            "summary": "Gate changes on automated test execution.",
            "observable_abilities": [
                "Add a testing pipeline to a project",
            ],
            "related_skills": ["CI/CD"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=2),
                _rel_rule("CI/CD", weight=0.5),
            ],
            "action": "Add a testing pipeline to your API project.",
        },
        {
            "id": "testing-pytest",
            "title": "Test Python code",
            "summary": "Use pytest idioms: fixtures, parametrization, markers.",
            "observable_abilities": [
                "Write idiomatic pytest suites",
            ],
            "related_skills": ["Python"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=3),
                _sig_rule("Python", min_depth=3, weight=0.5),
            ],
            "action": "Parametrize an existing suite and add fixtures.",
        },
        {
            "id": "testing-js",
            "title": "Test JavaScript code",
            "summary": "Use Jest/Vitest idioms for frontend and Node code.",
            "observable_abilities": [
                "Write Jest/Vitest suites for JS/TS code",
            ],
            "related_skills": ["JavaScript", "TypeScript"],
            "evidence_rules": [
                _sig_rule("Testing", min_depth=3),
                _rel_rule("JavaScript", "TypeScript", weight=0.5),
            ],
            "action": "Add component tests for loading and error states.",
        },
    ],
    "git": [
        {
            "id": "git-basics",
            "title": "Version control basics",
            "summary": "Track work with commits, branches, and remotes.",
            "observable_abilities": [
                "Commit, branch, and merge with clear history",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Git", min_depth=3),
            ],
            "action": "Practice a branching workflow on a sample repo.",
        },
        {
            "id": "git-collab",
            "title": "Collaborate with pull requests",
            "summary": "Review and integrate others' work safely.",
            "observable_abilities": [
                "Collaborate via PRs with meaningful commit history",
                "Resolve merge conflicts deliberately",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Git", min_depth=3),
                _files_rule("Git", 2, weight=0.5),
            ],
            "action": "Collaborate via PRs with meaningful commit history.",
        },
        {
            "id": "git-workflows",
            "title": "Branching workflows",
            "summary": "Apply trunk-based or Git-flow discipline to teams.",
            "observable_abilities": [
                "Follow a consistent branching strategy",
            ],
            "related_skills": ["CI/CD"],
            "evidence_rules": [
                _sig_rule("Git", min_depth=3),
                _rel_rule("CI/CD", weight=0.5),
            ],
            "action": "Adopt trunk-based development with CI checks on a repo.",
        },
        {
            "id": "git-advanced",
            "title": "Advanced Git operations",
            "summary": "Rewrite history safely and recover from mistakes.",
            "observable_abilities": [
                "Rebase, stash, and recover work confidently",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Git", min_depth=3),
                _files_rule("Git", 3, weight=0.5),
            ],
            "action": "Practice interactive rebase and reflog recovery.",
        },
    ],
    "kubernetes": [
        {
            "id": "k8s-manifests",
            "title": "Write Kubernetes manifests",
            "summary": "Declare Deployments, Services, and ConfigMaps as code.",
            "observable_abilities": [
                "Author Deployment and Service manifests",
            ],
            "related_skills": ["Docker"],
            "evidence_rules": [
                _sig_rule("Kubernetes", min_depth=2),
                _pat_rule("Kubernetes", "k8s_kind", "k8s_api"),
            ],
            "action": "Write manifests deploying an API with a Service.",
        },
        {
            "id": "k8s-config",
            "title": "Configure workloads",
            "summary": "Externalize configuration with ConfigMaps, Secrets, and env.",
            "observable_abilities": [
                "Manage configuration separately from images",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Kubernetes", min_depth=2),
            ],
            "action": "Move hardcoded config into ConfigMaps and Secrets.",
        },
        {
            "id": "k8s/networking",
            "title": "Expose services",
            "summary": "Route traffic with Services and Ingress.",
            "observable_abilities": [
                "Expose workloads via Services and Ingress",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("Kubernetes", min_depth=3),
                _files_rule("Kubernetes", 2, weight=0.5),
            ],
            "action": "Expose two services behind one Ingress with TLS.",
        },
        {
            "id": "k8s-ops",
            "title": "Operate workloads",
            "summary": "Observe health, scale, and roll out safely.",
            "observable_abilities": [
                "Use probes, scaling, and rollout strategies",
            ],
            "related_skills": ["Monitoring"],
            "evidence_rules": [
                _sig_rule("Kubernetes", min_depth=3),
                _rel_rule("Monitoring", weight=0.5),
            ],
            "action": "Add probes and autoscaling to a Deployment.",
        },
    ],
    "dbms": [
        {
            "id": "dbms-modeling",
            "title": "Model relational data",
            "summary": "Design normalized schemas with keys and constraints.",
            "observable_abilities": [
                "Normalize tables and choose keys",
            ],
            "related_skills": ["SQL"],
            "evidence_rules": [
                _sig_rule("DBMS", min_depth=2),
                _sig_rule("SQL", min_depth=2, weight=0.5),
            ],
            "action": "Normalize a denormalized schema to 3NF.",
        },
        {
            "id": "dbms-indexing",
            "title": "Index for performance",
            "summary": "Choose indexes that match query patterns.",
            "observable_abilities": [
                "Create indexes and verify their use",
            ],
            "related_skills": ["SQL", "PostgreSQL"],
            "evidence_rules": [
                _sig_rule("DBMS", min_depth=3),
                _files_rule("DBMS", 2, weight=0.5),
            ],
            "action": "Index a slow workload and verify with EXPLAIN.",
        },
        {
            "id": "dbms-transactions",
            "title": "Ensure data integrity",
            "summary": "Use transactions and constraints to protect data.",
            "observable_abilities": [
                "Apply transactions and integrity constraints",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("DBMS", min_depth=2),
            ],
            "action": "Wrap a multi-write flow in a transaction with tests.",
        },
        {
            "id": "dbms-orm",
            "title": "Use ORMs effectively",
            "summary": "Map objects to tables without N+1 or integrity surprises.",
            "observable_abilities": [
                "Model with an ORM and avoid N+1 queries",
            ],
            "related_skills": ["Python", "SQL"],
            "evidence_rules": [
                _sig_rule("DBMS", min_depth=3),
                _rel_rule("Python", "SQL", weight=0.5),
            ],
            "action": "Fix N+1 queries in an ORM-backed endpoint.",
        },
    ],
    "oop": [
        {
            "id": "oop-classes",
            "title": "Design classes",
            "summary": "Encapsulate state and behavior with clear interfaces.",
            "observable_abilities": [
                "Design classes with clear responsibilities",
            ],
            "related_skills": ["Python", "Java"],
            "evidence_rules": [
                _sig_rule("OOP", min_depth=2),
            ],
            "action": "Refactor a module around small, focused classes.",
        },
        {
            "id": "oop-inheritance",
            "title": "Apply inheritance and polymorphism",
            "summary": "Share behavior safely through hierarchies and interfaces.",
            "observable_abilities": [
                "Use inheritance and polymorphism appropriately",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("OOP", min_depth=3),
                _files_rule("OOP", 2, weight=0.5),
            ],
            "action": "Replace conditionals with polymorphic dispatch.",
        },
        {
            "id": "oop-composition",
            "title": "Prefer composition",
            "summary": "Compose behavior instead of deep hierarchies.",
            "observable_abilities": [
                "Compose objects rather than deep inheritance",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("OOP", min_depth=3),
            ],
            "action": "Extract a deep hierarchy into composed collaborators.",
        },
        {
            "id": "oop-patterns",
            "title": "Apply design patterns",
            "summary": "Recognize and apply common patterns where they fit.",
            "observable_abilities": [
                "Apply factory, strategy, or observer patterns",
            ],
            "related_skills": ["System Design"],
            "evidence_rules": [
                _sig_rule("OOP", min_depth=3),
                _rel_rule("System Design", weight=0.5),
            ],
            "action": "Implement one pattern to remove duplicated logic.",
        },
    ],
    "system_design": [
        {
            "id": "sd-scalability",
            "title": "Design for scale",
            "summary": "Reason about load, bottlenecks, and horizontal growth.",
            "observable_abilities": [
                "Identify bottlenecks and scaling strategies",
            ],
            "related_skills": ["REST APIs", "SQL"],
            "evidence_rules": [
                _sig_rule("System Design", min_depth=2),
            ],
            "action": "Study 3 case studies (URL shortener, feed, chat).",
        },
        {
            "id": "sd-caching",
            "title": "Apply caching",
            "summary": "Reduce load with appropriate caching layers.",
            "observable_abilities": [
                "Add caching with correct invalidation",
            ],
            "related_skills": ["Caching", "Redis"],
            "evidence_rules": [
                _sig_rule("System Design", min_depth=2),
                _rel_rule("Caching", "Redis", weight=0.5),
            ],
            "action": "Add a cache layer with invalidation to a read path.",
        },
        {
            "id": "sd-tradeoffs",
            "title": "Document trade-offs",
            "summary": "Record architecture decisions and their consequences.",
            "observable_abilities": [
                "Document architecture decisions and trade-offs",
            ],
            "related_skills": [],
            "evidence_rules": [
                _sig_rule("System Design", min_depth=3),
                _files_rule("System Design", 2, weight=0.5),
            ],
            "action": "Write ADRs for two past architecture decisions.",
        },
        {
            "id": "sd-reliability",
            "title": "Design for reliability",
            "summary": "Handle failure with retries, timeouts, and fallbacks.",
            "observable_abilities": [
                "Add retries, timeouts, and graceful degradation",
            ],
            "related_skills": ["Monitoring"],
            "evidence_rules": [
                _sig_rule("System Design", min_depth=3),
                _rel_rule("Monitoring", weight=0.5),
            ],
            "action": "Add timeouts, retries, and health checks to a service.",
        },
    ],
}
