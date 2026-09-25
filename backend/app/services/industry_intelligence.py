"""INAURA Dynamic Industry Intelligence (Person 1).

Extension layer on top of the existing O*NET + ESCO foundation.

What already exists (do NOT rebuild):
  - skill_taxonomy.py: canonical taxonomy SSOT (RAW_TAXONOMY, get_canonical_skill)
  - industry_roles.py: 11-role catalog + canonicalize_role_name
  - industry_service.py: PROTOTYPE_INDUSTRY_REQUIREMENTS, _normalize_requirement_row,
    aggregate_requirements, list_by_role, trust tiers
  - retrieval_service.py: fusion-v1 ranking (similarity/role/skill/quality/importance-demand x freshness)
  - skill_engine.py + analysis_run_service.py: gap = max(0, required - current), priority logic

What this module adds (additive only):
  - IndustryDemandProvider abstraction (pluggable future job-market providers)
  - Deterministic DemoSeedDemandProvider (global scope only, explicitly demo_seeded, never live)
  - Location normalization (global/country/region/city) with graceful fallback
  - Freshness classification reusing retrieval_service bounds (2y full, 8y floor)
  - Skill trend states (stable/rising/emerging/declining/insufficient_data) with evidence gating
  - Role+location intelligence view feeding the EXISTING gap engine + retrieval shapes
  - Strict provenance: source_data vs inaura_derived vs demo_seeded; unmapped concepts preserved

Determinism: no network, no LLM, no wall-clock dependence except injectable `now`.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .industry_roles import canonicalize_role_name
from .skill_taxonomy import get_canonical_skill, normalize_skill, normalize_skill_slug

# ---------------------------------------------------------------------------
# Trend states (Part 2). Only set rising/emerging/declining when a dynamic
# signal carries them with provenance; baseline catalog defaults to stable.
# ---------------------------------------------------------------------------
TREND_STABLE = "stable"
TREND_RISING = "rising"
TREND_EMERGING = "emerging"
TREND_DECLINING = "declining"
TREND_INSUFFICIENT = "insufficient_data"
VALID_TRENDS = frozenset({TREND_STABLE, TREND_RISING, TREND_EMERGING, TREND_DECLINING, TREND_INSUFFICIENT})
# Priority for merging multiple trends for one skill (highest wins).
_TREND_PRIORITY = {
    TREND_INSUFFICIENT: 0,
    TREND_STABLE: 1,
    TREND_DECLINING: 2,
    TREND_RISING: 3,
    TREND_EMERGING: 4,
}

# ---------------------------------------------------------------------------
# Freshness states (Part 4). Thresholds mirror retrieval_service fusion bounds
# (FRESHNESS_FULL_YEARS=2.0, FRESHNESS_FLOOR_YEARS=8.0) instead of inventing
# new constants: current <=2y, aging 2-8y, stale >8y, unknown when no date.
# ---------------------------------------------------------------------------
FRESHNESS_CURRENT = "current"
FRESHNESS_AGING = "aging"
FRESHNESS_STALE = "stale"
FRESHNESS_UNKNOWN = "unknown"
VALID_FRESHNESS = frozenset({FRESHNESS_CURRENT, FRESHNESS_AGING, FRESHNESS_STALE, FRESHNESS_UNKNOWN})
FRESHNESS_FULL_YEARS = 2.0
FRESHNESS_FLOOR_YEARS = 8.0

# ---------------------------------------------------------------------------
# Data origin (Part 10). Every dynamic signal must declare one.
# ---------------------------------------------------------------------------
ORIGIN_SOURCE = "source_data"       # authentic external benchmark (O*NET/ESCO/SO/CNCF/...)
ORIGIN_DERIVED = "inaura_derived"   # INAURA aggregation/mapping heuristic
ORIGIN_DEMO = "demo_seeded"         # deterministic demo seed, NOT live market data
VALID_ORIGINS = frozenset({ORIGIN_SOURCE, ORIGIN_DERIVED, ORIGIN_DEMO})

GLOBAL_LABEL = "Global"


# ---------------------------------------------------------------------------
# Location (Part 3): optional, graceful degradation.
# ---------------------------------------------------------------------------
def normalize_location(
    location: Any = None,
    country: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize any location input to {scope, country, region, city, label, is_global}.

    Accepts None (global), a string ("Bengaluru", "Bengaluru, India", "Global"),
    or a dict {country, region/state, city}. String parsing is a deterministic
    heuristic for matching only, never an authoritative geocode.
    """
    c = (country or "").strip() or None
    r = (region or "").strip() or None
    ct = (city or "").strip() or None

    if isinstance(location, dict):
        c = str(location.get("country") or c or "").strip() or None
        r = str(location.get("region") or location.get("state") or r or "").strip() or None
        ct = str(location.get("city") or location.get("metro") or ct or "").strip() or None
        scope_hint = str(location.get("scope") or "").strip().lower() or None
    elif isinstance(location, str) and location.strip():
        text = location.strip()
        if text.lower() in ("global", "default", "all", "worldwide"):
            return {"scope": "global", "country": None, "region": None, "city": None,
                    "label": GLOBAL_LABEL, "is_global": True}
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if len(parts) == 1:
            ct = ct or parts[0]
        elif len(parts) == 2:
            ct = ct or parts[0]
            c = c or parts[1]
        elif len(parts) >= 3:
            ct = ct or parts[0]
            r = r or parts[1]
            c = c or parts[2]
        scope_hint = None
    else:
        scope_hint = None

    if ct:
        scope = "city"
        label = ct if not c else f"{ct}, {c}"
    elif r:
        scope = "region"
        label = r if not c else f"{r}, {c}"
    elif c:
        scope = "country"
        label = c
    else:
        scope = "global"
        label = GLOBAL_LABEL
    if isinstance(location, dict) and scope_hint in ("global", "country", "region", "city"):
        # Explicit scope wins only when consistent with fields; global requires no fields.
        if scope_hint == "global" and scope == "global":
            scope = "global"
    return {"scope": scope, "country": c, "region": r, "city": ct,
            "label": label, "is_global": scope == "global"}


def _loc_key(loc: Dict[str, Any]) -> str:
    return f"{(loc.get('scope') or 'global').lower()}|{(loc.get('country') or '').lower()}|{(loc.get('region') or '').lower()}|{(loc.get('city') or '').lower()}"


def location_matches(requirement_location: Any, requested: Dict[str, Any]) -> bool:
    """Global requirements match every request; specific rows match on exact key."""
    req = requirement_location if isinstance(requirement_location, dict) else normalize_location(requirement_location)
    if req.get("scope") == "global" or req.get("is_global"):
        return True
    return _loc_key(req) == _loc_key(requested)


def describe_location(loc: Dict[str, Any]) -> str:
    return str((loc or {}).get("label") or GLOBAL_LABEL)


# ---------------------------------------------------------------------------
# Freshness (Part 4)
# ---------------------------------------------------------------------------
def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def classify_freshness(
    published_at: Any = None,
    retrieved_at: Any = None,
    collected_at: Any = None,
    last_updated: Any = None,
    now: Any = None,
) -> Dict[str, Any]:
    """Classify freshness from the most recent available timestamp.

    Preference: collected_at/last_updated (dynamic) > retrieved_at > published_at.
    Returns {state, age_days, age_years, reference_date}.
    """
    ref = (
        _parse_dt(collected_at) or _parse_dt(last_updated)
        or _parse_dt(retrieved_at) or _parse_dt(published_at)
    )
    if ref is None:
        return {"state": FRESHNESS_UNKNOWN, "age_days": None, "age_years": None, "reference_date": None}
    current = now or datetime.now(timezone.utc)
    try:
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        age_days = (current - ref).days
    except Exception:
        return {"state": FRESHNESS_UNKNOWN, "age_days": None, "age_years": None, "reference_date": ref.isoformat()}
    if age_days < 0:
        age_days = 0
    age_years = age_days / 365.25
    if age_years <= FRESHNESS_FULL_YEARS:
        state = FRESHNESS_CURRENT
    elif age_years >= FRESHNESS_FLOOR_YEARS:
        state = FRESHNESS_STALE
    else:
        state = FRESHNESS_AGING
    return {"state": state, "age_days": age_days, "age_years": round(age_years, 2),
            "reference_date": ref.isoformat()}


def normalize_trend(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_TRENDS else TREND_INSUFFICIENT


def merge_trends(trends: List[Any]) -> str:
    best = TREND_INSUFFICIENT
    best_rank = -1
    for t in trends or []:
        norm = normalize_trend(t)
        rank = _TREND_PRIORITY.get(norm, -1)
        if rank > best_rank:
            best_rank = rank
            best = norm
    return best


# ---------------------------------------------------------------------------
# Provider abstraction (Part 1). Future job-market providers plug in here.
# ---------------------------------------------------------------------------
class IndustryDemandProvider(ABC):
    """Conceptual provider: fetch demand signals -> normalize -> map to canonical
    skills -> preserve provenance. Never fabricate live data."""

    provider_id: str = "base"
    display_name: str = "Base demand provider"
    data_origin: str = ORIGIN_DERIVED
    is_live: bool = False
    description: str = "Abstract provider interface."

    @abstractmethod
    def fetch_signals(self, role: str, location: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return raw signal dicts (see normalize_provider_signal for schema)."""
        raise NotImplementedError

    def to_dict(self) -> Dict[str, Any]:
        return {"provider_id": self.provider_id, "display_name": self.display_name,
                "data_origin": self.data_origin, "is_live": self.is_live,
                "description": self.description}


def normalize_provider_signal(raw: Dict[str, Any], default_location: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalize one provider signal, preserving source concept when unmapped.

    Raw may contain: role, skill/source_concept, required_level, demand, importance,
    interview_relevance, industry_confidence, trend, source, source_url, source_version,
    evidence_context, collected_at/last_updated, location, data_origin.
    Unmapped concepts keep skill=source_concept, skill_slug=None, mapping_status=unmapped.
    """
    raw = dict(raw or {})
    role = str(raw.get("role") or "").strip()
    source_concept = str(raw.get("source_concept") or raw.get("skill") or raw.get("skill_raw") or "").strip()
    canon_def = get_canonical_skill(source_concept) if source_concept else None
    if canon_def:
        skill_display = canon_def.display_name
        skill_slug: Optional[str] = canon_def.id
        canonical_mapping: Optional[str] = canon_def.display_name
        mapping_status = "mapped"
        category = canon_def.category
    else:
        skill_display = source_concept or "Unknown signal"
        skill_slug = None
        canonical_mapping = None
        mapping_status = "unmapped"
        category = str(raw.get("skill_category") or "Unmapped Dynamic Signal")

    loc = raw.get("location")
    loc_norm = loc if isinstance(loc, dict) and loc.get("scope") else normalize_location(
        loc if loc is not None else (default_location or {"scope": "global", "label": GLOBAL_LABEL}))
    origin = str(raw.get("data_origin") or ORIGIN_DERIVED).strip().lower()
    if origin not in VALID_ORIGINS:
        origin = ORIGIN_DERIVED
    trend = normalize_trend(raw.get("trend") or raw.get("skill_trend"))

    def _f(key: str, default: float) -> float:
        try:
            v = raw.get(key)
            return max(0.0, min(1.0, float(v))) if v is not None else default
        except (TypeError, ValueError):
            return default

    collected = raw.get("collected_at") or raw.get("last_updated") or raw.get("retrieved_at")
    return {
        "role": role,
        "skill": skill_display,
        "skill_slug": skill_slug,
        "skill_category": category,
        "required_level": round(_f("required_level", 0.75), 3),
        "importance": round(_f("importance", 0.70), 3),
        "demand": round(_f("demand", 0.70), 3),
        "interview_relevance": round(_f("interview_relevance", 0.60), 3),
        "industry_confidence": round(_f("industry_confidence", 0.60), 3),
        "trend": trend,
        "source": str(raw.get("source") or "Unknown dynamic source"),
        "source_url": raw.get("source_url"),
        "source_version": raw.get("source_version") or "",
        "evidence_context": str(raw.get("evidence_context") or raw.get("description") or ""),
        "published_at": raw.get("published_at") or "2024-01-01",
        "retrieved_at": raw.get("retrieved_at") or collected or "2026-01-01T00:00:00Z",
        "collected_at": collected or "2026-01-01T00:00:00Z",
        "last_updated": raw.get("last_updated") or collected or "2026-01-01T00:00:00Z",
        "location": loc_norm,
        "data_origin": origin,
        "source_concept": source_concept,
        "canonical_mapping": canonical_mapping,
        "mapping_status": mapping_status,
        "mapping_rationale": str(raw.get("mapping_rationale") or (
            "Canonical mapping via INAURA taxonomy" if canon_def
            else "No clean canonical mapping; source concept preserved without forcing")),
        "source_quality": round(_f("source_quality", 0.70), 3),
        "provider_id": str(raw.get("provider_id") or ""),
    }


class DemoSeedDemandProvider(IndustryDemandProvider):
    """Deterministic demo seed. Global scope ONLY (never location-specific),
    explicitly demo_seeded, never presented as live market data."""

    provider_id = "inaura_demo_seed_v1"
    display_name = "INAURA Demo Demand Seed (deterministic, not live)"
    data_origin = ORIGIN_DEMO
    is_live = False
    description = ("Deterministic illustrative overlay for UI/plumbing. Global scope only; "
                   "location queries fall back to global baselines. Not live job-market data.")

    COLLECTED_AT = "2026-01-15T00:00:00Z"
    DEMO_SIGNALS: List[Dict[str, Any]] = [
        {"role": "Software Engineer", "skill": "React", "required_level": 0.80,
         "importance": 0.78, "demand": 0.82, "interview_relevance": 0.70,
         "industry_confidence": 0.60, "trend": TREND_RISING, "source_quality": 0.70,
         "source": "INAURA Demo Demand Seed (deterministic, not live)",
         "evidence_context": "Demo seed illustrating a rising dynamic overlay for React; not live market data."},
        {"role": "Software Engineer", "skill": "Docker", "required_level": 0.68,
         "importance": 0.66, "demand": 0.74, "interview_relevance": 0.55,
         "industry_confidence": 0.60, "trend": TREND_RISING, "source_quality": 0.70,
         "source": "INAURA Demo Demand Seed (deterministic, not live)",
         "evidence_context": "Demo seed illustrating container demand movement; not live market data."},
        {"role": "Frontend Developer", "skill": "TypeScript", "required_level": 0.80,
         "importance": 0.85, "demand": 0.84, "interview_relevance": 0.75,
         "industry_confidence": 0.60, "trend": TREND_RISING, "source_quality": 0.70,
         "source": "INAURA Demo Demand Seed (deterministic, not live)",
         "evidence_context": "Demo seed for type-safety demand illustration; not live market data."},
        # Unmapped example: preserved verbatim, never forced onto an unrelated skill.
        {"role": "Software Engineer", "skill": "Prompt Engineering for LLMs", "required_level": 0.65,
         "importance": 0.60, "demand": 0.65, "interview_relevance": 0.55,
         "industry_confidence": 0.50, "trend": TREND_EMERGING, "source_quality": 0.60,
         "source": "INAURA Demo Demand Seed (deterministic, not live)",
         "evidence_context": "Demo unmapped concept: no clean canonical skill; preserved as source concept."},
    ]

    def fetch_signals(self, role: str, location: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Demo seed is global-only: non-global requests get no location-specific
        # fabrication; the caller falls back to global baselines gracefully.
        if not location.get("is_global", True):
            return []
        canonical = canonicalize_role_name(role) or (role or "").strip()
        out: List[Dict[str, Any]] = []
        for sig in self.DEMO_SIGNALS:
            if sig.get("role", "").lower() != canonical.lower():
                continue
            raw = dict(sig, provider_id=self.provider_id, data_origin=self.data_origin,
                       collected_at=self.COLLECTED_AT, last_updated=self.COLLECTED_AT,
                       retrieved_at=self.COLLECTED_AT, published_at="2024-05-01",
                       location={"scope": "global", "country": None, "region": None,
                                 "city": None, "label": GLOBAL_LABEL, "is_global": True})
            out.append(raw)
        return out


_PROVIDERS: Dict[str, IndustryDemandProvider] = {}


def register_provider(provider: IndustryDemandProvider) -> None:
    _PROVIDERS[provider.provider_id] = provider


def list_providers() -> List[Dict[str, Any]]:
    if not _PROVIDERS:
        register_provider(DemoSeedDemandProvider())
    return [p.to_dict() for p in _PROVIDERS.values()]


def get_dynamic_signals(role: str, location: Any = None) -> List[Dict[str, Any]]:
    """Collect normalized dynamic signals for a role+location from all providers."""
    if not _PROVIDERS:
        register_provider(DemoSeedDemandProvider())
    loc = normalize_location(location)
    signals: List[Dict[str, Any]] = []
    for provider in _PROVIDERS.values():
        try:
            for raw in provider.fetch_signals(role, loc) or []:
                raw = dict(raw)
                raw.setdefault("provider_id", provider.provider_id)
                raw.setdefault("data_origin", provider.data_origin)
                signals.append(normalize_provider_signal(raw, default_location=loc))
        except Exception:
            continue
    return signals


# ---------------------------------------------------------------------------
# Aggregation + role+location view (Parts 5-6). Reuses industry_service
# aggregation math; never collapses demand/importance/level/confidence into
# one arbitrary score.
# ---------------------------------------------------------------------------
def _signal_key(role: str, skill_display: str, slug: Optional[str]) -> str:
    if slug:
        return f"{role.lower()}|{slug.lower()}"
    return f"{role.lower()}|__unmapped__{(skill_display or '').lower()}"


def build_role_intelligence(
    role: str,
    location: Any = None,
    include_dynamics: bool = True,
    now: Any = None,
) -> Dict[str, Any]:
    """Build explainable role+location intelligence over baseline + dynamics.

    Returns {role, canonical_role, location, location_match, last_updated,
    skills: [{skill, skill_slug, required_level, demand, importance,
    interview_relevance, industry_confidence, trend, freshness, source,
    source_url, evidence_context, data_origin, mapping_status, ...}],
    counts, data_origins, providers, note}.
    """
    from . import industry_service as _isvc  # lazy: industry_service never imports this module

    if not role or not str(role).strip():
        return {"role": role or "", "canonical_role": "", "location": normalize_location(location),
                "location_match": "global", "last_updated": None, "skills": [], "counts": {},
                "data_origins": [], "providers": list_providers(),
                "note": "No role provided."}
    canonical = canonicalize_role_name(role) or str(role).strip()
    loc = normalize_location(location)
    baseline: List[Dict[str, Any]] = _isvc.list_by_role(canonical) or []
    dynamics: List[Dict[str, Any]] = get_dynamic_signals(canonical, loc) if include_dynamics else []

    # Index baseline by signal key.
    base_by_key: Dict[str, Dict[str, Any]] = {}
    for b in baseline:
        slug = b.get("skill_slug") or normalize_skill_slug(str(b.get("skill") or "")) or None
        base_by_key[_signal_key(canonical, str(b.get("skill") or ""), slug)] = b

    # Location filtering for dynamics: demo seed returns globals only, but the
    # rule is general — exact city/region/country matches win, globals apply
    # everywhere, other locations never match (no fabrication).
    applicable: List[Dict[str, Any]] = []
    for d in dynamics:
        d_loc = d.get("location") if isinstance(d.get("location"), dict) else normalize_location(d.get("location"))
        if d_loc.get("is_global"):
            applicable.append(d)
        elif _loc_key(d_loc) == _loc_key(loc):
            applicable.append(d)

    dyn_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for d in applicable:
        dyn_by_key.setdefault(_signal_key(canonical, str(d.get("skill") or ""), d.get("skill_slug")), []).append(d)

    skills: List[Dict[str, Any]] = []
    origins: Dict[str, int] = {}
    last_updated: Optional[str] = None

    def _track_origin(o: str) -> None:
        origins[o] = origins.get(o, 0) + 1

    def _track_date(*vals: Any) -> None:
        nonlocal last_updated
        best = last_updated
        for v in vals:
            dt = _parse_dt(v)
            if dt is None:
                continue
            iso = dt.isoformat()
            if best is None or iso > best:
                best = iso
        last_updated = best

    all_keys = sorted(set(base_by_key) | set(dyn_by_key))
    for key in all_keys:
        base = base_by_key.get(key)
        dyns = dyn_by_key.get(key, [])
        if base is not None and dyns:
            # Quality-weighted merge reusing the documented aggregation formula
            # via industry_service.aggregate_requirements on raw-shaped rows.
            raws: List[Dict[str, Any]] = [dict(base)]
            for d in dyns:
                raws.append({
                    "role": canonical, "skill": d.get("source_concept") or d.get("skill"),
                    "skill_category": d.get("skill_category"),
                    "required_level": d.get("required_level"), "importance": d.get("importance"),
                    "demand": d.get("demand"), "interview_relevance": d.get("interview_relevance"),
                    "industry_confidence": d.get("industry_confidence"),
                    "source": d.get("source"), "source_url": d.get("source_url"),
                    "source_quality": d.get("source_quality"),
                    "evidence_context": d.get("evidence_context"),
                    "published_at": d.get("published_at"), "retrieved_at": d.get("retrieved_at"),
                    "collected_at": d.get("collected_at"), "last_updated": d.get("last_updated"),
                    "trend": d.get("trend"), "data_origin": d.get("data_origin"),
                    "location": d.get("location"), "source_concept": d.get("source_concept"),
                    "mapping_rationale": d.get("mapping_rationale"),
                })
            merged_list = _isvc.aggregate_requirements(raws)
            merged = dict(merged_list[0]) if merged_list else dict(base)
            merged_trend = merge_trends([base.get("trend") or TREND_STABLE] + [d.get("trend") for d in dyns])
            merged["trend"] = merged_trend
            merged["data_origin"] = ORIGIN_DEMO if any(d.get("data_origin") == ORIGIN_DEMO for d in dyns) else ORIGIN_DERIVED
            merged["data_origins"] = sorted({str(base.get("data_origin") or ORIGIN_SOURCE)} | {str(d.get("data_origin") or ORIGIN_DERIVED) for d in dyns})
            merged["supporting_dynamic_sources"] = [
                {"source": d.get("source"), "source_url": d.get("source_url"),
                 "trend": d.get("trend"), "data_origin": d.get("data_origin"),
                 "collected_at": d.get("collected_at")} for d in dyns]
            for d in dyns:
                _track_origin(str(d.get("data_origin") or ORIGIN_DERIVED))
            _track_origin(str(base.get("data_origin") or ORIGIN_SOURCE))
            entry = merged
            _track_date(base.get("retrieved_at"), base.get("published_at"),
                        *[d.get("collected_at") for d in dyns], *[d.get("last_updated") for d in dyns])
        elif base is not None:
            entry = dict(base)
            entry.setdefault("trend", TREND_STABLE)
            entry.setdefault("data_origin", ORIGIN_SOURCE)
            entry.setdefault("data_origins", [entry["data_origin"]])
            _track_origin(entry["data_origin"])
            _track_date(base.get("retrieved_at"), base.get("published_at"))
        else:
            # Dynamic-only skill (may be unmapped): surface honestly with provenance.
            combined = _isvc.aggregate_requirements([{
                "role": canonical, "skill": d.get("source_concept") or d.get("skill"),
                "skill_category": d.get("skill_category"),
                "required_level": d.get("required_level"), "importance": d.get("importance"),
                "demand": d.get("demand"), "interview_relevance": d.get("interview_relevance"),
                "industry_confidence": d.get("industry_confidence"),
                "source": d.get("source"), "source_url": d.get("source_url"),
                "source_quality": d.get("source_quality"),
                "evidence_context": d.get("evidence_context"),
                "published_at": d.get("published_at"), "retrieved_at": d.get("retrieved_at"),
                "collected_at": d.get("collected_at"), "last_updated": d.get("last_updated"),
                "trend": d.get("trend"), "data_origin": d.get("data_origin"),
                "location": d.get("location"), "source_concept": d.get("source_concept"),
                "mapping_rationale": d.get("mapping_rationale"),
            } for d in dyns])
            entry = dict(combined[0]) if combined else dict(dyns[0])
            entry["trend"] = merge_trends([d.get("trend") for d in dyns])
            entry["data_origin"] = dyns[0].get("data_origin", ORIGIN_DERIVED)
            entry["data_origins"] = sorted({str(d.get("data_origin") or ORIGIN_DERIVED) for d in dyns})
            for d in dyns:
                _track_origin(str(d.get("data_origin") or ORIGIN_DERIVED))
            _track_date(*[d.get("collected_at") for d in dyns])

        fresh = classify_freshness(entry.get("published_at"), entry.get("retrieved_at"),
                                   entry.get("collected_at"), entry.get("last_updated"), now)
        entry["freshness"] = fresh["state"]
        entry["freshness_detail"] = fresh
        entry["location"] = {"scope": loc["scope"], "country": loc["country"], "region": loc["region"],
                             "city": loc["city"], "label": loc["label"], "is_global": loc["is_global"]}
        entry["location_match"] = "global" if loc.get("is_global") else (
            "exact" if any(not (d.get("location") or {}).get("is_global", True) for d in dyns) else "fallback_global")
        # Keep requirement shape compatible with gap engine + retrieval.
        skills.append(entry)

    skills.sort(key=lambda x: (-float(x.get("importance", 0.0) or 0.0), str(x.get("skill") or "")))
    rising = [s for s in skills if s.get("trend") in (TREND_RISING, TREND_EMERGING)]
    loc_match = "global" if loc.get("is_global") else (
        "exact" if any(s.get("location_match") == "exact" for s in skills) else "fallback_global")
    return {
        "role": canonical,
        "canonical_role": canonical,
        "location": loc,
        "location_match": loc_match,
        "last_updated": last_updated,
        "skills": skills,
        "counts": {"total": len(skills), "rising_emerging": len(rising),
                   "baseline": len(base_by_key), "dynamic": len(dyn_by_key)},
        "data_origins": sorted(origins),
        "providers": list_providers(),
        "note": ("Baselines are O*NET/ESCO-grounded industry requirements; dynamic overlays are "
                 + ("demo-seeded illustrations, not live market data." if any(
                     (d.get("data_origin") == ORIGIN_DEMO) for d in applicable) else "provider signals with provenance.")),
    }


def get_top_skills(view: Dict[str, Any], n: int = 10) -> List[Dict[str, Any]]:
    return list((view or {}).get("skills") or [])[:max(1, int(n))]


def get_rising_emerging(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [s for s in ((view or {}).get("skills") or []) if s.get("trend") in (TREND_RISING, TREND_EMERGING)]


def to_gap_engine_requirements(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Project the intelligence view back to requirement-shaped rows the
    EXISTING gap engine consumes (no second gap algorithm)."""
    reqs: List[Dict[str, Any]] = []
    for s in ((view or {}).get("skills") or []):
        # Unmapped dynamic-only concepts have no canonical skill: surface them for
        # display but exclude from gap-engine requirements so the taxonomy never
        # drifts (caller may still show them as emerging context).
        if s.get("mapping_status") == "unmapped":
            continue
        reqs.append({
            "role": (view or {}).get("role", s.get("role", "")),
            "skill": s.get("skill", ""),
            "skill_category": s.get("skill_category", "General"),
            "required_level": s.get("required_level", 0.75),
            "importance": s.get("importance", 0.5),
            "demand": s.get("demand", 0.5),
            "interview_relevance": s.get("interview_relevance", 0.5),
            "industry_confidence": s.get("industry_confidence", 0.85),
            "source": s.get("source", ""),
            "source_url": s.get("source_url"),
            "source_quality": s.get("source_quality", 0.85),
            "evidence_context": s.get("evidence_context", ""),
            "published_at": s.get("published_at"),
            "retrieved_at": s.get("retrieved_at"),
            "collected_at": s.get("collected_at"),
            "last_updated": s.get("last_updated"),
            "trend": s.get("trend"),
            "freshness": s.get("freshness"),
            "data_origin": s.get("data_origin"),
            "location": s.get("location"),
            "source_concept": s.get("source_concept"),
            "canonical_mapping": s.get("canonical_mapping", s.get("skill")),
            "mapping_rationale": s.get("mapping_rationale"),
        })
    return reqs


def to_retrievable_items(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Project the view to retrieval-compatible items (existing fusion ranking)."""
    items: List[Dict[str, Any]] = []
    for s in ((view or {}).get("skills") or []):
        if s.get("mapping_status") == "unmapped":
            continue
        canon = s.get("skill", "")
        items.append({**s, "skill": canon})
    return items
