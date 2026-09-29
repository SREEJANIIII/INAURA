"""INAURA Labour Market Intelligence (P0 #1).

Provider-neutral persistent ingestion + aggregation layer UNDERNEATH
industry_intelligence.py (which is never modified here).

Pipeline:
  raw posting dicts
    -> sanitize_description()          (PII scrub, Part 15)
    -> normalize_posting()             (role/location/time normalization)
    -> map_posting_skills()            (canonical taxonomy mapping, unmapped preserved)
    -> aggregate_demand()              (monthly buckets, counts, shares)
    -> calculate_demand() / calculate_trend()  (explainable derived dimensions)
    -> get_demand_signals() / refresh_demand_signals()

All pure computation is deterministic: no network, no LLM, no wall-clock
dependence except injectable `now` / explicit period bounds.

Reused (never duplicated):
  - skill_taxonomy.get_canonical_skill / extract_known_skills_from_text
  - industry_roles.canonicalize_role_name
  - industry_intelligence.normalize_location + data-origin constants

demand / required_level / importance / trend / confidence are DERIVED
measurements and are always stored/returned beside the raw counts they were
computed from. They must never be presented as ground truth.
"""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .industry_roles import canonicalize_role_name
from .skill_taxonomy import extract_known_skills_from_text, get_canonical_skill

# ---------------------------------------------------------------------------
# Provenance constants (mirror industry_intelligence tiers; imported lazily
# where a hard import would risk a cycle — values duplicated as literals).
# ---------------------------------------------------------------------------
ORIGIN_SOURCE = "source_data"
ORIGIN_DERIVED = "inaura_derived"
ORIGIN_DEMO = "demo_seeded"
VALID_ORIGINS = frozenset({ORIGIN_SOURCE, ORIGIN_DERIVED, ORIGIN_DEMO})

# Trend states. TREND_INSUFFICIENT is the only honest answer on thin evidence.
TREND_STABLE = "stable"
TREND_RISING = "rising"
TREND_DECLINING = "declining"
TREND_EMERGING = "emerging"
TREND_INSUFFICIENT = "insufficient_data"
VALID_TRENDS = frozenset({TREND_STABLE, TREND_RISING, TREND_DECLINING, TREND_EMERGING, TREND_INSUFFICIENT})

# ---------------------------------------------------------------------------
# Small-sample policy (Part 9). Explicit, documented, configurable.
# A signal is *suppressed* (no strong interpretation) unless ALL hold:
#   role postings in the cell's period      >= MIN_ROLE_POSTINGS
#   postings mentioning the skill           >= MIN_SKILL_MENTIONS
#   distinct companies in the role cell     >= MIN_DISTINCT_COMPANIES
# Trend comparison additionally requires each compared period to hold at
# least TREND_MIN_POSTINGS_PER_PERIOD role postings and the skill to have at
# least TREND_MIN_SKILL_MENTIONS mentions in at least one of the two periods.
# Trend deltas below TREND_DELTA in absolute skill-share are noise -> stable.
# ---------------------------------------------------------------------------
MIN_ROLE_POSTINGS = 10
MIN_SKILL_MENTIONS = 3
MIN_DISTINCT_COMPANIES = 2

TREND_MIN_POSTINGS_PER_PERIOD = 10
TREND_MIN_SKILL_MENTIONS = 3
TREND_RISE_DELTA = 0.10
TREND_DECLINE_DELTA = -0.10

SOURCE_VERSION = "labour-market-v1"

# PII patterns that must never persist (Part 15: postings, not candidates).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class LabourMarketPosting:
    provider_id: str
    title: str
    description: Optional[str] = None
    role_key: Optional[str] = None
    role_mapping_status: str = "unresolved"
    company_name: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    employment_type: Optional[str] = None
    published_at: Optional[str] = None
    collected_at: Optional[str] = None
    source_url: Optional[str] = None
    source_version: str = SOURCE_VERSION
    external_posting_id: Optional[str] = None
    content_hash: str = ""
    data_origin: str = ORIGIN_SOURCE

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class LabourMarketSkillObservation:
    source_concept: str
    canonical_skill_slug: Optional[str] = None
    skill_id: Optional[str] = None
    mapping_status: str = "unmapped"
    mapping_rationale: str = ""
    extraction_method: str = "taxonomy_match"
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class LabourMarketDemandSignal:
    role_key: str
    skill_slug: Optional[str] = None
    source_concept: Optional[str] = None
    mapping_status: str = "mapped"
    location_scope: str = "global"
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    period_start: str = ""
    period_end: str = ""
    posting_count: int = 0
    skill_posting_count: int = 0
    distinct_company_count: int = 0
    skill_share: float = 0.0
    demand: float = 0.0
    required_level: Optional[float] = None
    importance: Optional[float] = None
    trend: str = TREND_INSUFFICIENT
    confidence: float = 0.0
    evidence_suppressed: bool = True
    provider_id: str = ""
    data_origin: str = ORIGIN_SOURCE
    source_version: str = SOURCE_VERSION
    evidence_context: str = ""
    computed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


# ---------------------------------------------------------------------------
# In-memory store (used by tests / when Supabase is unavailable).
# Supabase persistence is attempted opportunistically; pure functions never
# depend on it, so unit tests stay deterministic without credentials.
# ---------------------------------------------------------------------------
_MEMORY_POSTINGS: List[Dict[str, Any]] = []
_MEMORY_SKILLS: List[Dict[str, Any]] = []
_MEMORY_SIGNALS: List[Dict[str, Any]] = []


def clear_memory_store() -> None:
    """Reset the in-memory store. Tests only; never touches Supabase."""
    _MEMORY_POSTINGS.clear()
    _MEMORY_SKILLS.clear()
    _MEMORY_SIGNALS.clear()


def _now_iso(now: Any = None) -> str:
    if isinstance(now, datetime):
        dt = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(now, str) and now.strip():
        return now.strip()
    return datetime.now(timezone.utc).isoformat()


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
        try:
            return datetime.strptime(str(value).strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Sanitization + hashing (Part 15)
# ---------------------------------------------------------------------------
def sanitize_description(text: Any) -> str:
    """Scrub emails/phone-like strings from posting descriptions.

    Keeps skill-relevant prose; drops candidate-PII-shaped tokens.
    Deterministic pure function.
    """
    cleaned = str(text or "")
    cleaned = _EMAIL_RE.sub("[redacted-email]", cleaned)
    cleaned = _PHONE_RE.sub("[redacted-phone]", cleaned)
    return cleaned.strip()


def compute_content_hash(title: Any, description: Any, company: Any, location: Any = "",
                         published_at: Any = None) -> str:
    """Stable sha256 over normalized posting identity fields.

    Includes the published calendar day: an identical repost on a different
    day is a distinct labour-market observation, while a byte-identical
    re-import (same published day) still deduplicates safely.
    """
    day = ""
    try:
        dt = _parse_dt(published_at)
        day = dt.date().isoformat() if dt else str(published_at or "").strip()[:10]
    except Exception:
        day = ""
    basis = "|".join([
        str(title or "").strip().lower(),
        str(description or "").strip().lower(),
        str(company or "").strip().lower(),
        str(location or "").strip().lower(),
        day,
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def normalize_source_concept(raw: Any) -> str:
    """Normalize an extracted skill label: trim, collapse whitespace."""
    return re.sub(r"\s+", " ", str(raw or "").strip())


# ---------------------------------------------------------------------------
# Posting normalization (Parts 2/5/6)
# ---------------------------------------------------------------------------
def normalize_posting(raw: Dict[str, Any], now: Any = None) -> LabourMarketPosting:
    """Normalize one raw posting dict into a canonical LabourMarketPosting.

    - role: canonicalize_role_name(); unresolvable -> role_key None,
      role_mapping_status 'unresolved', raw title preserved in `title`.
    - location: from the posting source fields only; never inferred.
    - published_at: parsed defensively; invalid -> None.
    - content_hash: always computed (dedup key).
    - data_origin: validated against known tiers, default source_data.
    Pure + deterministic.
    """
    from . import industry_intelligence as _intel

    raw = dict(raw or {})
    provider_id = str(raw.get("provider_id") or "unknown").strip()
    title = str(raw.get("title") or "").strip()
    description = sanitize_description(raw.get("description") or "")

    canonical_role = canonicalize_role_name(title) or canonicalize_role_name(
        str(raw.get("role") or raw.get("role_key") or ""))
    role_mapping_status = "mapped" if canonical_role else "unresolved"

    loc = _intel.normalize_location({
        "country": raw.get("location_country") or (raw.get("location") or {}).get("country")
        if isinstance(raw.get("location"), dict) else raw.get("location_country"),
        "region": raw.get("location_region") or (raw.get("location") or {}).get("region")
        if isinstance(raw.get("location"), dict) else raw.get("location_region"),
        "city": raw.get("location_city") or (raw.get("location") or {}).get("city")
        if isinstance(raw.get("location"), dict) else raw.get("location_city"),
    }) if not isinstance(raw.get("location"), str) else _intel.normalize_location(raw.get("location"))

    published = _parse_dt(raw.get("published_at"))
    origin = str(raw.get("data_origin") or ORIGIN_SOURCE).strip().lower()
    if origin not in VALID_ORIGINS:
        origin = ORIGIN_SOURCE

    content_hash = compute_content_hash(
        title, description, raw.get("company_name"),
        f"{loc.get('country') or ''}|{loc.get('region') or ''}|{loc.get('city') or ''}",
        raw.get("published_at"))

    return LabourMarketPosting(
        provider_id=provider_id,
        title=title,
        description=description or None,
        role_key=canonical_role,
        role_mapping_status=role_mapping_status,
        company_name=str(raw.get("company_name") or "").strip() or None,
        country=loc.get("country"),
        region=loc.get("region"),
        city=loc.get("city"),
        employment_type=str(raw.get("employment_type") or "").strip() or None,
        published_at=published.isoformat() if published else None,
        collected_at=_now_iso(raw.get("collected_at") or now),
        source_url=str(raw.get("source_url") or "").strip() or None,
        source_version=str(raw.get("source_version") or SOURCE_VERSION),
        external_posting_id=str(raw.get("external_posting_id") or "").strip() or None,
        content_hash=str(raw.get("content_hash") or "").strip() or content_hash,
        data_origin=origin,
    )


# ---------------------------------------------------------------------------
# Skill mapping (Part 4): taxonomy reuse, unmapped preserved
# ---------------------------------------------------------------------------
def map_posting_skills(
    posting: LabourMarketPosting,
    explicit_skills: Optional[List[str]] = None,
) -> List[LabourMarketSkillObservation]:
    """Extract + map skills for one normalized posting.

    Sources: explicit provider skill tags first, then deterministic taxonomy
    phrase extraction over title + description. Every distinct normalized
    concept yields exactly one observation; confidently mapped concepts carry
    the canonical slug, everything else is preserved with
    mapping_status='unmapped' and never forced onto an unrelated skill.
    Pure + deterministic.
    """
    concepts: List[Tuple[str, str]] = []  # (concept, method)
    seen: set = set()

    def _add(label: Any, method: str) -> None:
        concept = normalize_source_concept(label)
        if not concept or concept.lower() in seen:
            return
        seen.add(concept.lower())
        concepts.append((concept, method))

    for tag in explicit_skills or []:
        _add(tag, "provider_tag")
    text = f"{posting.title or ''}\n{posting.description or ''}"
    for skill_def in extract_known_skills_from_text(text):
        _add(skill_def.display_name, "taxonomy_match")

    observations: List[LabourMarketSkillObservation] = []
    for concept, method in concepts:
        canon = get_canonical_skill(concept)
        if canon is not None:
            observations.append(LabourMarketSkillObservation(
                source_concept=concept,
                canonical_skill_slug=canon.id,
                skill_id=canon.id,
                mapping_status="mapped",
                mapping_rationale="Canonical mapping via INAURA skill taxonomy",
                extraction_method=method,
                confidence=1.0 if method == "provider_tag" else 0.9,
            ))
        else:
            observations.append(LabourMarketSkillObservation(
                source_concept=concept,
                canonical_skill_slug=None,
                skill_id=None,
                mapping_status="unmapped",
                mapping_rationale="No clean canonical mapping; source concept preserved without forcing",
                extraction_method=method,
                confidence=0.5,
            ))
    return observations


# ---------------------------------------------------------------------------
# Ingestion with duplicate protection (Part 1A/1B)
# ---------------------------------------------------------------------------
def ingest_postings(
    raw_postings: List[Dict[str, Any]],
    provider: Optional["LabourMarketPostingProvider"] = None,
    now: Any = None,
    persist: bool = False,
) -> Dict[str, Any]:
    """Normalize + deduplicate + store raw postings and skill observations.

    Dedup keys (in order): (provider_id, external_posting_id) then
    content_hash. Repeated imports are safe: duplicates are counted and
    skipped, never stored twice. Returns summary counts. When `persist` is
    True AND Supabase is configured, rows are also upserted server-side
    (best-effort; memory store is always updated so tests stay hermetic).
    """
    provider_id = provider.provider_id if provider else None
    collected_now = _now_iso(now)
    ingested = 0
    dup_external = 0
    dup_content = 0

    existing_external = {(p.get("provider_id"), p.get("external_posting_id"))
                         for p in _MEMORY_POSTINGS if p.get("external_posting_id")}
    existing_hashes = {p.get("content_hash") for p in _MEMORY_POSTINGS if p.get("content_hash")}

    new_postings: List[Dict[str, Any]] = []
    new_skills: List[Dict[str, Any]] = []

    for raw in raw_postings or []:
        payload = dict(raw or {})
        if provider_id and not payload.get("provider_id"):
            payload["provider_id"] = provider_id
        if provider is not None and not payload.get("data_origin"):
            payload["data_origin"] = provider.data_origin
        posting = normalize_posting(payload, now=collected_now)
        if not posting.title:
            continue
        ext_key = (posting.provider_id, posting.external_posting_id)
        if posting.external_posting_id and ext_key in existing_external:
            dup_external += 1
            continue
        if posting.content_hash in existing_hashes:
            dup_content += 1
            continue
        record = posting.to_dict()
        explicit = payload.get("skills") or payload.get("source_skills") or []
        if isinstance(explicit, str):
            explicit = [explicit]
        obs = map_posting_skills(posting, [str(s) for s in (explicit or [])])
        record_id = f"mem-{len(_MEMORY_POSTINGS) + len(new_postings) + 1}"
        record["id"] = record_id
        new_postings.append(record)
        existing_external.add(ext_key)
        existing_hashes.add(posting.content_hash)
        for o in obs:
            row = o.to_dict()
            row["posting_id"] = record_id
            new_skills.append(row)
        ingested += 1

    _MEMORY_POSTINGS.extend(new_postings)
    _MEMORY_SKILLS.extend(new_skills)

    if persist:
        _persist_to_supabase(new_postings, new_skills)

    return {"ingested": ingested, "duplicate_external_id": dup_external,
            "duplicate_content_hash": dup_content, "total_postings": len(_MEMORY_POSTINGS)}


def _persist_to_supabase(postings: List[Dict[str, Any]], skills: List[Dict[str, Any]]) -> None:
    """Best-effort Supabase upsert. Never raises (import path stays usable offline)."""
    if not postings:
        return
    try:
        from ..core.supabase import get_supabase_client
        client = get_supabase_client()
        if client is None:
            return
        for p in postings:
            payload = {k: v for k, v in p.items() if k != "id"}
            try:
                client.table("labour_market_postings").upsert(
                    payload, on_conflict="provider_id,external_posting_id").execute()
            except Exception:
                try:
                    client.table("labour_market_postings").insert(payload).execute()
                except Exception:
                    continue
    except Exception:
        return


# ---------------------------------------------------------------------------
# Time buckets + demand + trend (Parts 7/8)
# ---------------------------------------------------------------------------
def month_bucket(value: Any) -> Tuple[date, date]:
    """Map a timestamp to its (period_start, period_end) month bucket."""
    dt = _parse_dt(value)
    if dt is None:
        raise ValueError(f"Cannot bucket unparseable date: {value!r}")
    start = date(dt.year, dt.month, 1)
    end = date(dt.year, dt.month, monthrange(dt.year, dt.month)[1])
    return start, end


def calculate_demand(posting_count: int, skill_posting_count: int) -> Dict[str, float]:
    """Explainable demand dimensions from observed posting frequency.

    skill_share = skill_posting_count / role_posting_count (0 when empty).
    demand = skill_share rounded to 3dp — i.e. the 0..1 NORMALIZED form of the
    observed mention share, documented here and always returned beside the raw
    counts. No hidden rescaling: 45 mentions in 100 postings -> share 0.45 ->
    demand 0.45. Pure function.
    """
    posting_count = max(0, int(posting_count or 0))
    skill_posting_count = max(0, int(skill_posting_count or 0))
    share = (skill_posting_count / posting_count) if posting_count > 0 else 0.0
    share = max(0.0, min(1.0, share))
    return {"skill_share": round(share, 4), "demand": round(share, 3)}


def calculate_trend(previous_share: Optional[float], current_share: Optional[float],
                    previous_n: int = 0, current_n: int = 0,
                    previous_skill_n: int = 0, current_skill_n: int = 0) -> str:
    """Compare recent vs previous comparable period skill-shares.

    Returns rising/declining/stable, or TREND_INSUFFICIENT when either period
    is below TREND_MIN_POSTINGS_PER_PERIOD role postings or the skill has
    fewer than TREND_MIN_SKILL_MENTIONS mentions in BOTH periods. Deltas
    smaller than TREND_RISE_DELTA in magnitude are noise -> stable.
    Deterministic; no LLM.
    """
    if previous_share is None or current_share is None:
        return TREND_INSUFFICIENT
    if min(int(previous_n or 0), int(current_n or 0)) < TREND_MIN_POSTINGS_PER_PERIOD:
        return TREND_INSUFFICIENT
    if max(int(previous_skill_n or 0), int(current_skill_n or 0)) < TREND_MIN_SKILL_MENTIONS:
        return TREND_INSUFFICIENT
    delta = float(current_share) - float(previous_share)
    if delta >= TREND_RISE_DELTA:
        return TREND_RISING
    if delta <= TREND_DECLINE_DELTA:
        return TREND_DECLINING
    return TREND_STABLE


def _confidence(posting_count: int, skill_posting_count: int, distinct_companies: int,
                suppressed: bool) -> float:
    """Explainable confidence from sample breadth. Suppressed cells cap at 0.40."""
    pc = min(max(0, int(posting_count or 0)), 50) / 50.0
    sc = min(max(0, int(skill_posting_count or 0)), 20) / 20.0
    cc = min(max(0, int(distinct_companies or 0)), 5) / 5.0
    value = 0.30 + 0.30 * pc + 0.20 * sc + 0.20 * cc
    if suppressed:
        value = min(value, 0.40)
    return round(max(0.0, min(0.95, value)), 3)


def aggregate_demand(
    postings: Optional[List[Dict[str, Any]]] = None,
    skills: Optional[List[Dict[str, Any]]] = None,
    provider_id: Optional[str] = None,
    now: Any = None,
) -> List[LabourMarketDemandSignal]:
    """Monthly aggregation over normalized postings + skill observations.

    Groups by (provider, role_key, skill-or-concept, location, month).
    Unmapped concepts aggregate under their source_concept and are flagged
    mapping_status='unmapped' (never counted as canonical demand). Cells
    below the small-sample minimums are preserved with evidence_suppressed=True,
    trend=insufficient_data, and capped confidence. Pure + deterministic.
    """
    postings = postings if postings is not None else list(_MEMORY_POSTINGS)
    skills = skills if skills is not None else list(_MEMORY_SKILLS)

    by_posting: Dict[str, List[Dict[str, Any]]] = {}
    for s in skills or []:
        by_posting.setdefault(str(s.get("posting_id")), []).append(s)

    # role cell stats per (provider, role, location, month)
    role_cells: Dict[Tuple, Dict[str, Any]] = {}
    # skill cells per (provider, role, skill-key, location, month)
    skill_cells: Dict[Tuple, Dict[str, Any]] = {}

    def _loc_tuple(p: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
        from . import industry_intelligence as _intel
        loc = _intel.normalize_location({
            "country": p.get("country") or p.get("location_country"),
            "region": p.get("region") or p.get("location_region"),
            "city": p.get("city") or p.get("location_city"),
        })
        return (loc["scope"], loc["country"], loc["region"], loc["city"])

    for p in postings or []:
        if provider_id and str(p.get("provider_id")) != provider_id:
            continue
        role = p.get("role_key") or p.get("role")
        if not role:
            continue  # unresolved roles stay as raw observations, never aggregated
        try:
            start, end = month_bucket(p.get("published_at") or p.get("collected_at"))
        except ValueError:
            continue
        scope, country, region, city = _loc_tuple(p)
        prov = str(p.get("provider_id") or "")
        rkey = (prov, str(role), scope, country, region, city, start)
        cell = role_cells.setdefault(rkey, {
            "posting_ids": set(), "companies": set(), "start": start, "end": end,
            "scope": scope, "country": country, "region": region, "city": city,
            "provider": prov, "role": str(role),
            "origins": set(), "version": str(p.get("source_version") or SOURCE_VERSION),
        })
        cell["posting_ids"].add(str(p.get("id") or p.get("content_hash")))
        if p.get("company_name"):
            cell["companies"].add(str(p.get("company_name")).strip().lower())
        if p.get("data_origin"):
            cell["origins"].add(str(p.get("data_origin")))

        for obs in by_posting.get(str(p.get("id")), []):
            slug = obs.get("canonical_skill_slug")
            concept = normalize_source_concept(obs.get("source_concept"))
            status = obs.get("mapping_status") or ("mapped" if slug else "unmapped")
            skill_key = f"slug:{str(slug).lower()}" if slug else f"raw:{concept.lower()}"
            skey = (prov, str(role), skill_key, scope, country, region, city, start)
            scell = skill_cells.setdefault(skey, {
                "posting_ids": set(), "slug": slug, "concept": concept,
                "status": status, "role_cell": rkey,
            })
            scell["posting_ids"].add(str(p.get("id") or p.get("content_hash")))

    computed_at = _now_iso(now)
    signals: List[LabourMarketDemandSignal] = []
    for skey, scell in sorted(skill_cells.items(), key=lambda kv: str(kv[0])):
        rcell = role_cells[scell["role_cell"]]
        posting_count = len(rcell["posting_ids"])
        skill_n = len(scell["posting_ids"])
        companies = len(rcell["companies"])
        dims = calculate_demand(posting_count, skill_n)
        suppressed = (
            posting_count < MIN_ROLE_POSTINGS
            or skill_n < MIN_SKILL_MENTIONS
            or companies < MIN_DISTINCT_COMPANIES
        )
        origin = ORIGIN_DERIVED
        if len(rcell["origins"]) == 1:
            only = next(iter(rcell["origins"]))
            origin = only if only in VALID_ORIGINS else ORIGIN_DERIVED
        start, end = rcell["start"], rcell["end"]
        signals.append(LabourMarketDemandSignal(
            role_key=rcell["role"],
            skill_slug=scell["slug"],
            source_concept=scell["concept"],
            mapping_status=scell["status"],
            location_scope=rcell["scope"],
            country=rcell["country"], region=rcell["region"], city=rcell["city"],
            period_start=start.isoformat(), period_end=end.isoformat(),
            posting_count=posting_count, skill_posting_count=skill_n,
            distinct_company_count=companies,
            skill_share=dims["skill_share"], demand=dims["demand"],
            required_level=None, importance=None,
            trend=TREND_INSUFFICIENT,  # resolved across periods by attach_trends()
            confidence=_confidence(posting_count, skill_n, companies, suppressed),
            evidence_suppressed=suppressed,
            provider_id=rcell["provider"],
            data_origin=origin,
            source_version=rcell["version"],
            evidence_context=(
                f"Derived from {skill_n} of {posting_count} observed postings "
                f"mentioning '{scell['concept']}' during {start.isoformat()} → {end.isoformat()} "
                f"({companies} distinct companies). demand equals observed skill share; "
                f"not ground truth."
            ),
            computed_at=computed_at,
        ))

    attach_trends(signals)
    return signals


def attach_trends(signals: List[LabourMarketDemandSignal]) -> None:
    """Resolve each signal's trend by comparing its month to the previous one.

    Same (provider, role, skill, location) series; previous month only.
    Suppressed cells stay TREND_INSUFFICIENT. Mutates in place.
    """
    def _series_key(s: LabourMarketDemandSignal) -> Tuple:
        skill_part = f"slug:{(s.skill_slug or '').lower()}" if s.skill_slug \
            else f"raw:{(s.source_concept or '').lower()}"
        return (s.provider_id, s.role_key.lower(), skill_part,
                s.location_scope, (s.country or "").lower(),
                (s.region or "").lower(), (s.city or "").lower())

    by_series: Dict[Tuple, Dict[str, LabourMarketDemandSignal]] = {}
    for s in signals:
        by_series.setdefault(_series_key(s), {})[s.period_start] = s

    for series in by_series.values():
        for s in series.values():
            if s.evidence_suppressed:
                s.trend = TREND_INSUFFICIENT
                continue
            try:
                y, m, _ = (int(x) for x in s.period_start.split("-"))
            except Exception:
                s.trend = TREND_INSUFFICIENT
                continue
            pm_y, pm_m = (y, m - 1) if m > 1 else (y - 1, 12)
            prev_key = f"{pm_y:04d}-{pm_m:02d}-01"
            prev = series.get(prev_key)
            if prev is None or prev.evidence_suppressed:
                # Single-period or suppressed-previous: insufficient unless the
                # cell itself is strong enough to call stable.
                if (s.posting_count >= TREND_MIN_POSTINGS_PER_PERIOD
                        and s.skill_posting_count >= TREND_MIN_SKILL_MENTIONS):
                    s.trend = TREND_STABLE
                else:
                    s.trend = TREND_INSUFFICIENT
                continue
            s.trend = calculate_trend(
                prev.skill_share, s.skill_share,
                previous_n=prev.posting_count, current_n=s.posting_count,
                previous_skill_n=prev.skill_posting_count,
                current_skill_n=s.skill_posting_count)


# ---------------------------------------------------------------------------
# Read API over the store (+ Supabase when configured)
# ---------------------------------------------------------------------------
def _signal_matches(s: Dict[str, Any], role: Optional[str], skill: Optional[str],
                    country: Optional[str], region: Optional[str], city: Optional[str],
                    start: Optional[date], end: Optional[date],
                    include_raw_concepts: bool) -> bool:
    if role:
        canon = canonicalize_role_name(role) or role.strip()
        if str(s.get("role_key") or "").lower() != canon.lower():
            return False
    if skill:
        canon = get_canonical_skill(skill)
        if canon is not None:
            if (s.get("skill_slug") or "").lower() != canon.id.lower():
                return False
        elif not include_raw_concepts:
            return False
        elif str(s.get("source_concept") or "").lower() != skill.strip().lower():
            return False
    elif not include_raw_concepts and (s.get("mapping_status") == "unmapped"):
        return False
    for key, val in (("country", country), ("region", region), ("city", city)):
        if val and str(s.get(key) or "").lower() != str(val).strip().lower():
            return False
    try:
        if start and str(s.get("period_start") or "") < start.isoformat():
            return False
        if end and str(s.get("period_start") or "") > end.isoformat():
            return False
    except Exception:
        pass
    return True


def get_demand_signals(
    role: Optional[str] = None,
    skill: Optional[str] = None,
    country: Optional[str] = None,
    region: Optional[str] = None,
    city: Optional[str] = None,
    start_date: Any = None,
    end_date: Any = None,
    provider_id: Optional[str] = None,
    include_raw_concepts: bool = False,
) -> List[Dict[str, Any]]:
    """Return aggregated demand signals with full provenance.

    Unmapped raw concepts are EXCLUDED unless include_raw_concepts=True, so
    canonical skill demand statistics never silently mix in raw concepts.
    Falls back to Supabase rows when the memory store is empty.
    """
    start = _parse_dt(start_date).date() if _parse_dt(start_date) else None
    end = _parse_dt(end_date).date() if _parse_dt(end_date) else None

    rows = list(_MEMORY_SIGNALS)
    if not rows:
        rows = _fetch_signals_from_supabase()
    out: List[Dict[str, Any]] = []
    for s in rows:
        if provider_id and str(s.get("provider_id")) != provider_id:
            continue
        if _signal_matches(s, role, skill, country, region, city, start, end, include_raw_concepts):
            out.append(dict(s))
    out.sort(key=lambda r: (str(r.get("role_key") or ""), str(r.get("period_start") or ""),
                            str(r.get("skill_slug") or r.get("source_concept") or "")))
    return out


def _fetch_signals_from_supabase() -> List[Dict[str, Any]]:
    try:
        from ..core.supabase import get_supabase_client
        client = get_supabase_client()
        if client is None:
            return []
        res = client.table("labour_market_demand_signals").select("*").limit(500).execute()
        rows = list(res.data or [])
        # The signals table stores canonical_skill_slug; in-memory signals
        # carry skill_slug. Normalise here so Supabase-backed reads present
        # the same shape every consumer (e.g. course alignment) expects.
        for r in rows:
            if not r.get("skill_slug"):
                r["skill_slug"] = r.get("canonical_skill_slug")
        return rows
    except Exception:
        return []


def refresh_demand_signals(
    provider: Optional["LabourMarketPostingProvider"] = None,
    postings: Optional[List[Dict[str, Any]]] = None,
    now: Any = None,
    persist: bool = False,
) -> Dict[str, Any]:
    """Deterministic idempotent refresh: ingest -> aggregate -> store signals.

    Either `postings` or a `provider` (fetch_postings) supplies observations.
    Re-running with identical input yields identical signals (upsert by logical
    cell key in memory; Supabase upsert when persist=True and configured).
    """
    global _MEMORY_SIGNALS
    raw = list(postings or [])
    if provider is not None and not raw:
        try:
            raw = provider.fetch_postings(role=None, location=None,
                                          start_date=None, end_date=None) or []
        except Exception:
            raw = []
    ingest_summary = ingest_postings(raw, provider=provider, now=now, persist=persist)
    signals = aggregate_demand(now=now,
                               provider_id=provider.provider_id if provider else None)

    # Upsert into the memory signal store by logical cell key.
    def _cell_key(s: Any) -> Tuple:
        d = s.to_dict() if isinstance(s, LabourMarketDemandSignal) else dict(s)
        skill_part = f"slug:{(d.get('skill_slug') or '').lower()}" if d.get("skill_slug") \
            else f"raw:{(d.get('source_concept') or '').lower()}"
        return (d.get("provider_id"), (d.get("role_key") or "").lower(), skill_part,
                d.get("location_scope"), (d.get("country") or "").lower(),
                (d.get("region") or "").lower(), (d.get("city") or "").lower(),
                d.get("period_start"))

    if provider is not None:
        _MEMORY_SIGNALS = [s for s in _MEMORY_SIGNALS
                           if str(s.get("provider_id")) != provider.provider_id]
    index = {_cell_key(s): i for i, s in enumerate(_MEMORY_SIGNALS)}
    for sig in signals:
        payload = sig.to_dict()
        key = _cell_key(payload)
        if key in index:
            _MEMORY_SIGNALS[index[key]] = payload
        else:
            index[key] = len(_MEMORY_SIGNALS)
            _MEMORY_SIGNALS.append(payload)

    if persist:
        _persist_signals_to_supabase([s.to_dict() for s in signals])

    return {"ingested": ingest_summary, "signals": len(signals),
            "provider_id": provider.provider_id if provider else None}


def _persist_signals_to_supabase(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    try:
        from ..core.supabase import get_supabase_client
        client = get_supabase_client()
        if client is None:
            return
        for r in rows:
            try:
                client.table("labour_market_demand_signals").upsert(r).execute()
            except Exception:
                continue
    except Exception:
        return


# ---------------------------------------------------------------------------
# Provider interface for posting ingestion (Part 3)
# ---------------------------------------------------------------------------
class LabourMarketPostingProvider(ABC):
    """Posting-level provider: fetch raw posting dicts for later normalization.

    Future external providers (job boards, aggregators) implement this without
    any architectural rewrite: ingest_postings() + aggregate_demand() consume
    the same normalized shape regardless of source.
    """

    provider_id: str = "base"
    display_name: str = "Base posting provider"
    data_origin: str = ORIGIN_DERIVED
    is_live: bool = False
    description: str = "Abstract posting provider interface."

    @abstractmethod
    def fetch_postings(self, role: str | None, location: dict | None,
                       start_date: Any, end_date: Any) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def to_dict(self) -> Dict[str, Any]:
        return {"provider_id": self.provider_id, "display_name": self.display_name,
                "data_origin": self.data_origin, "is_live": self.is_live,
                "description": self.description}


_POSTING_PROVIDERS: Dict[str, LabourMarketPostingProvider] = {}


def register_posting_provider(provider: LabourMarketPostingProvider) -> None:
    _POSTING_PROVIDERS[provider.provider_id] = provider


def list_posting_providers() -> List[Dict[str, Any]]:
    if not _POSTING_PROVIDERS:
        register_posting_provider(DemoPostingProvider())
    return [p.to_dict() for p in _POSTING_PROVIDERS.values()]


def get_posting_provider(provider_id: str) -> Optional[LabourMarketPostingProvider]:
    if not _POSTING_PROVIDERS:
        register_posting_provider(DemoPostingProvider())
    return _POSTING_PROVIDERS.get(provider_id)


class DemoPostingProvider(LabourMarketPostingProvider):
    """Deterministic synthetic posting source for tests/plumbing.

    SYNTHETIC — NOT live labour-market data. Every posting carries
    data_origin='demo_seeded' and API/UI layers must never label it live.
    Covers Software Engineer, Frontend Developer, Backend Developer, and
    Mobile Developer across several months so trend math is exercisable.
    """

    provider_id = "demo_postings_v1"
    display_name = "INAURA Demo Postings (synthetic, not live)"
    data_origin = ORIGIN_DEMO
    is_live = False
    description = ("Deterministic synthetic postings for import-pipeline tests. "
                   "Explicitly NOT live job-market data.")

    def fetch_postings(self, role: str | None, location: dict | None,
                       start_date: Any, end_date: Any) -> List[Dict[str, Any]]:
        postings = list(_DEMO_POSTINGS)
        if role:
            canon = canonicalize_role_name(role) or role.strip()
            postings = [p for p in postings
                        if (canonicalize_role_name(p.get("title", "")) or "") == canon]
        # Location filter matches exactly; never fabricates city demand.
        if isinstance(location, dict) and any(location.get(k) for k in ("country", "region", "city")):
            def _match(p: Dict[str, Any]) -> bool:
                for k in ("country", "region", "city"):
                    want = str(location.get(k) or "").strip().lower()
                    if want and str(p.get(f"location_{k}") or "").strip().lower() != want:
                        return False
                return True
            postings = [p for p in postings if _match(p)]
        start = _parse_dt(start_date)
        end = _parse_dt(end_date)
        if start or end:
            kept = []
            for p in postings:
                dt = _parse_dt(p.get("published_at"))
                if dt is None:
                    continue
                if start and dt < start:
                    continue
                if end and dt > end:
                    continue
                kept.append(p)
            postings = kept
        return [dict(p, provider_id=self.provider_id, data_origin=self.data_origin,
                     source_version=SOURCE_VERSION) for p in postings]


def _demo_posting(pid: str, title: str, skills: List[str], month: str, day: int,
                  company: str, country: str = "India",
                  region: str = "Karnataka", city: str = "Bengaluru") -> Dict[str, Any]:
    skill_lines = ", ".join(skills)
    return {
        "external_posting_id": pid,
        "title": title,
        "description": (
            f"We are hiring a {title} ({company}). Required skills include "
            f"{skill_lines}. Apply with relevant project experience."
        ),
        "skills": list(skills),
        "company_name": company,
        "location_country": country,
        "location_region": region,
        "location_city": city,
        "employment_type": "full_time",
        "published_at": f"{month}-{day:02d}T09:00:00Z",
        "source_url": f"https://example.invalid/demo-postings/{pid}",
    }


_DEMO_COMPANIES = ["DemoCorp", "ExampleSoft", "SampleLabs", "TestWorks", "MockSystems"]

# Skill-share design (Software Engineer x Docker): June 2026 low (~0.25),
# August 2026 high (~0.5+) -> rising trend under the 0.10 delta rule.
# Each month carries >= MIN_ROLE_POSTINGS SWE postings so trend math engages.
_DEMO_POSTINGS: List[Dict[str, Any]] = [
    # ---- June 2026: Software Engineer x10 (Docker in 2) ----
    _demo_posting("demo-swe-jun-01", "Software Engineer", ["Python", "SQL", "Git"], "2026-06", 3, "DemoCorp"),
    _demo_posting("demo-swe-jun-02", "Software Engineer", ["Java", "SQL", "Git"], "2026-06", 4, "ExampleSoft"),
    _demo_posting("demo-swe-jun-03", "Software Engineer", ["Python", "REST APIs", "Git"], "2026-06", 5, "SampleLabs"),
    _demo_posting("demo-swe-jun-04", "Software Engineer", ["Java", "REST APIs", "Docker"], "2026-06", 6, "TestWorks"),
    _demo_posting("demo-swe-jun-05", "Software Engineer", ["Python", "SQL", "REST APIs"], "2026-06", 9, "MockSystems"),
    _demo_posting("demo-swe-jun-06", "Software Engineer", ["Java", "Git", "SQL"], "2026-06", 11, "DemoCorp"),
    _demo_posting("demo-swe-jun-07", "Software Engineer", ["Python", "Git", "Docker"], "2026-06", 14, "ExampleSoft"),
    _demo_posting("demo-swe-jun-08", "Software Engineer", ["Java", "SQL", "REST APIs"], "2026-06", 17, "SampleLabs"),
    _demo_posting("demo-swe-jun-09", "Software Engineer", ["Python", "Java", "Git"], "2026-06", 21, "TestWorks"),
    _demo_posting("demo-swe-jun-10", "Software Engineer", ["SQL", "REST APIs", "Git"], "2026-06", 24, "MockSystems"),
    # ---- July 2026: Software Engineer x12 (Docker in 4) ----
    _demo_posting("demo-swe-jul-01", "Software Engineer", ["Python", "Docker", "Git"], "2026-07", 2, "DemoCorp"),
    _demo_posting("demo-swe-jul-02", "Software Engineer", ["Java", "SQL", "Git"], "2026-07", 3, "ExampleSoft"),
    _demo_posting("demo-swe-jul-03", "Software Engineer", ["Python", "SQL", "REST APIs"], "2026-07", 5, "SampleLabs"),
    _demo_posting("demo-swe-jul-04", "Software Engineer", ["Java", "Docker", "AWS"], "2026-07", 7, "TestWorks"),
    _demo_posting("demo-swe-jul-05", "Software Engineer", ["Python", "Git", "SQL"], "2026-07", 9, "MockSystems"),
    _demo_posting("demo-swe-jul-06", "Software Engineer", ["Java", "REST APIs", "Git"], "2026-07", 11, "DemoCorp"),
    _demo_posting("demo-swe-jul-07", "Software Engineer", ["Python", "AWS", "Docker"], "2026-07", 13, "ExampleSoft"),
    _demo_posting("demo-swe-jul-08", "Software Engineer", ["Java", "SQL", "Git"], "2026-07", 15, "SampleLabs"),
    _demo_posting("demo-swe-jul-09", "Software Engineer", ["Python", "REST APIs", "Git"], "2026-07", 18, "TestWorks"),
    _demo_posting("demo-swe-jul-10", "Software Engineer", ["SQL", "Docker", "Git"], "2026-07", 21, "MockSystems"),
    _demo_posting("demo-swe-jul-11", "Software Engineer", ["Java", "Python", "SQL"], "2026-07", 24, "DemoCorp"),
    _demo_posting("demo-swe-jul-12", "Software Engineer", ["REST APIs", "Git", "SQL"], "2026-07", 27, "ExampleSoft"),
    # ---- August 2026: Software Engineer x12 (Docker in 7 -> share ~0.58) ----
    _demo_posting("demo-swe-aug-01", "Software Engineer", ["Python", "Docker", "AWS"], "2026-08", 1, "DemoCorp"),
    _demo_posting("demo-swe-aug-02", "Software Engineer", ["Java", "Docker", "Git"], "2026-08", 2, "ExampleSoft"),
    _demo_posting("demo-swe-aug-03", "Software Engineer", ["Python", "SQL", "Docker"], "2026-08", 4, "SampleLabs"),
    _demo_posting("demo-swe-aug-04", "Software Engineer", ["Java", "SQL", "REST APIs"], "2026-08", 6, "TestWorks"),
    _demo_posting("demo-swe-aug-05", "Software Engineer", ["Python", "Docker", "Git"], "2026-08", 8, "MockSystems"),
    _demo_posting("demo-swe-aug-06", "Software Engineer", ["Java", "AWS", "Docker"], "2026-08", 10, "DemoCorp"),
    _demo_posting("demo-swe-aug-07", "Software Engineer", ["Python", "REST APIs", "SQL"], "2026-08", 12, "ExampleSoft"),
    _demo_posting("demo-swe-aug-08", "Software Engineer", ["Docker", "Git", "SQL"], "2026-08", 14, "SampleLabs"),
    _demo_posting("demo-swe-aug-09", "Software Engineer", ["Java", "REST APIs", "Git"], "2026-08", 16, "TestWorks"),
    _demo_posting("demo-swe-aug-10", "Software Engineer", ["Python", "Docker", "REST APIs"], "2026-08", 19, "MockSystems"),
    _demo_posting("demo-swe-aug-11", "Software Engineer", ["SQL", "Git", "Java"], "2026-08", 22, "DemoCorp"),
    _demo_posting("demo-swe-aug-12", "Software Engineer", ["Python", "Git", "SQL"], "2026-08", 25, "ExampleSoft"),
    # ---- Frontend Developer (July + August, >=10 total; TypeScript/React heavy) ----
    _demo_posting("demo-fe-jul-01", "Frontend Developer", ["React", "TypeScript", "Git"], "2026-07", 3, "DemoCorp"),
    _demo_posting("demo-fe-jul-02", "Frontend Developer", ["React", "JavaScript", "REST APIs"], "2026-07", 8, "ExampleSoft"),
    _demo_posting("demo-fe-jul-03", "Frontend Developer", ["TypeScript", "React", "Node.js"], "2026-07", 15, "SampleLabs"),
    _demo_posting("demo-fe-jul-04", "Frontend Developer", ["React", "Git", "REST APIs"], "2026-07", 22, "TestWorks"),
    _demo_posting("demo-fe-aug-01", "Frontend Developer", ["React", "TypeScript", "REST APIs"], "2026-08", 2, "DemoCorp"),
    _demo_posting("demo-fe-aug-02", "Frontend Developer", ["TypeScript", "React", "Git"], "2026-08", 6, "ExampleSoft"),
    _demo_posting("demo-fe-aug-03", "Frontend Developer", ["React", "Node.js", "Git"], "2026-08", 10, "SampleLabs"),
    _demo_posting("demo-fe-aug-04", "Frontend Developer", ["TypeScript", "REST APIs", "Git"], "2026-08", 14, "TestWorks"),
    _demo_posting("demo-fe-aug-05", "Frontend Developer", ["React", "TypeScript", "Git"], "2026-08", 18, "MockSystems"),
    _demo_posting("demo-fe-aug-06", "Frontend Developer", ["React", "REST APIs", "Node.js"], "2026-08", 22, "DemoCorp"),
    # ---- Backend Developer (July + August; Python/FastAPI->REST APIs, Node.js, SQL) ----
    _demo_posting("demo-be-jul-01", "Backend Developer", ["Python", "FastAPI", "SQL"], "2026-07", 4, "DemoCorp"),
    _demo_posting("demo-be-jul-02", "Backend Developer", ["Node.js", "SQL", "Docker"], "2026-07", 11, "ExampleSoft"),
    _demo_posting("demo-be-jul-03", "Backend Developer", ["Java", "SQL", "REST APIs"], "2026-07", 18, "SampleLabs"),
    _demo_posting("demo-be-jul-04", "Backend Developer", ["Python", "SQL", "Git"], "2026-07", 25, "TestWorks"),
    _demo_posting("demo-be-aug-01", "Backend Developer", ["Python", "FastAPI", "Docker"], "2026-08", 3, "DemoCorp"),
    _demo_posting("demo-be-aug-02", "Backend Developer", ["Node.js", "REST APIs", "SQL"], "2026-08", 7, "ExampleSoft"),
    _demo_posting("demo-be-aug-03", "Backend Developer", ["Python", "SQL", "AWS"], "2026-08", 11, "SampleLabs"),
    _demo_posting("demo-be-aug-04", "Backend Developer", ["Java", "Docker", "Git"], "2026-08", 15, "TestWorks"),
    _demo_posting("demo-be-aug-05", "Backend Developer", ["Node.js", "SQL", "Git"], "2026-08", 19, "MockSystems"),
    _demo_posting("demo-be-aug-06", "Backend Developer", ["Python", "REST APIs", "SQL"], "2026-08", 23, "DemoCorp"),
    # ---- Mobile Developer (July + August; Flutter / REST APIs heavy) ----
    _demo_posting("demo-mob-jul-01", "Mobile Developer", ["Flutter", "REST APIs", "Git"], "2026-07", 5, "DemoCorp"),
    _demo_posting("demo-mob-jul-02", "Mobile Developer", ["Flutter", "Git", "SQL"], "2026-07", 12, "ExampleSoft"),
    _demo_posting("demo-mob-jul-03", "Mobile Developer", ["React Native", "REST APIs", "Git"], "2026-07", 19, "SampleLabs"),
    _demo_posting("demo-mob-jul-04", "Mobile Developer", ["Flutter", "REST APIs", "AWS"], "2026-07", 26, "TestWorks"),
    _demo_posting("demo-mob-aug-01", "Mobile Developer", ["Flutter", "REST APIs", "Git"], "2026-08", 4, "DemoCorp"),
    _demo_posting("demo-mob-aug-02", "Mobile Developer", ["Flutter", "AWS", "Git"], "2026-08", 9, "ExampleSoft"),
    _demo_posting("demo-mob-aug-03", "Mobile Developer", ["React Native", "Git", "REST APIs"], "2026-08", 13, "SampleLabs"),
    _demo_posting("demo-mob-aug-04", "Mobile Developer", ["Flutter", "SQL", "REST APIs"], "2026-08", 17, "TestWorks"),
    _demo_posting("demo-mob-aug-05", "Mobile Developer", ["Flutter", "Git", "REST APIs"], "2026-08", 21, "MockSystems"),
    _demo_posting("demo-mob-aug-06", "Mobile Developer", ["Flutter", "REST APIs", "AWS"], "2026-08", 25, "DemoCorp"),
]


# ---------------------------------------------------------------------------
# Adapter: labour-market signals -> IndustryDemandProvider shape (Part 11)
# ---------------------------------------------------------------------------
def to_industry_demand_signals(
    signals: Optional[List[Dict[str, Any]]] = None,
    role: Optional[str] = None,
    include_raw_concepts: bool = False,
) -> List[Dict[str, Any]]:
    """Project derived demand signals to normalize_provider_signal() input shape.

    Lets the existing industry-intelligence layer consume imported labour-market
    signals with zero contract changes. Canonical skills map by slug; unmapped
    concepts ride `source_concept` and are excluded unless explicitly requested.
    """
    from .skill_taxonomy import RAW_TAXONOMY
    rows = signals if signals is not None else get_demand_signals(
        role=role, include_raw_concepts=True)
    by_slug = {s.id: s for s in RAW_TAXONOMY}
    out: List[Dict[str, Any]] = []
    for s in rows:
        if role:
            canon_role = canonicalize_role_name(role) or role.strip()
            if str(s.get("role_key") or "").lower() != canon_role.lower():
                continue
        if (s.get("mapping_status") == "unmapped") and not include_raw_concepts:
            continue
        slug = s.get("skill_slug")
        display = (by_slug[slug].display_name if slug and slug in by_slug
                   else s.get("source_concept") or slug or "Unknown signal")
        loc = {"scope": s.get("location_scope") or "global",
               "country": s.get("country"), "region": s.get("region"), "city": s.get("city"),
               "label": s.get("city") or s.get("region") or s.get("country") or "Global",
               "is_global": (s.get("location_scope") or "global") == "global"}
        out.append({
            "role": s.get("role_key") or "",
            "skill": display,
            "source_concept": s.get("source_concept") or display,
            "required_level": s.get("required_level") if s.get("required_level") is not None else 0.70,
            "importance": s.get("importance") if s.get("importance") is not None else 0.70,
            "demand": s.get("demand") if s.get("demand") is not None else 0.0,
            "interview_relevance": 0.60,
            "industry_confidence": s.get("confidence") if s.get("confidence") is not None else 0.50,
            "trend": s.get("trend") or TREND_INSUFFICIENT,
            "source": f"Labour-market observations ({s.get('provider_id')})",
            "source_version": s.get("source_version") or SOURCE_VERSION,
            "evidence_context": s.get("evidence_context") or "",
            "collected_at": s.get("computed_at"),
            "last_updated": s.get("computed_at"),
            "published_at": s.get("period_start") or "2024-01-01",
            "location": loc,
            "data_origin": s.get("data_origin") or ORIGIN_DERIVED,
            "provider_id": s.get("provider_id") or "",
            "mapping_rationale": (
                f"Aggregated from {s.get('skill_posting_count')} of {s.get('posting_count')} "
                f"postings ({s.get('period_start')} → {s.get('period_end')}); "
                f"skill_share={s.get('skill_share')}, suppressed={s.get('evidence_suppressed')}."),
        })
    return out


class LabourMarketDemandProvider:
    """IndustryDemandProvider-compatible reader over derived demand signals.

    Registered into industry_intelligence WITHOUT modifying
    build_role_intelligence(): dynamic labour-market observations surface as
    ordinary normalized signals. DemoSeedDemandProvider stays registered as
    fallback/demo infrastructure — never silently replaced.
    """

    provider_id = "labour_market_v1"
    display_name = "INAURA Labour Market Observations (imported postings)"
    data_origin = ORIGIN_DERIVED
    is_live = False
    description = ("Aggregated imported job-posting observations with provenance. "
                   "Derived measurements, not ground truth; never live data.")

    def fetch_signals(self, role: str, location: Dict[str, Any]) -> List[Dict[str, Any]]:
        from . import industry_intelligence as _intel
        loc = location if isinstance(location, dict) else _intel.normalize_location(location)
        rows = get_demand_signals(role=role, include_raw_concepts=False)
        applicable: List[Dict[str, Any]] = []
        for raw in to_industry_demand_signals(rows, role=role):
            raw_loc = raw.get("location") or {}
            if raw_loc.get("is_global") or _intel._loc_key(raw_loc) == _intel._loc_key(loc):
                applicable.append(raw)
        return applicable

    def to_dict(self) -> Dict[str, Any]:
        return {"provider_id": self.provider_id, "display_name": self.display_name,
                "data_origin": self.data_origin, "is_live": self.is_live,
                "description": self.description}


def register_labour_market_provider() -> LabourMarketDemandProvider:
    """Register the adapter on the existing provider registry (idempotent).

    The DemoSeedDemandProvider fallback is ensured first so demo infrastructure
    is never silently replaced — both providers coexist.
    """
    from . import industry_intelligence as _intel
    try:
        if not any(p.get("provider_id") == "inaura_demo_seed_v1"
                   for p in _intel.list_providers()):
            _intel.register_provider(_intel.DemoSeedDemandProvider())
    except Exception:
        pass
    provider = LabourMarketDemandProvider()
    try:
        _intel.register_provider(provider)  # type: ignore[attr-defined]
    except Exception:
        pass
    return provider
