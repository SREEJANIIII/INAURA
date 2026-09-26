from typing import List, Optional, Dict, Any, Set, Tuple
from fastapi import HTTPException
from supabase import Client
import math
import re

from ..core.supabase import get_supabase_client
from ..core.config import get_settings
from . import embedding_service
from . import industry_service
from .skill_taxonomy import normalize_skill, extract_known_skills_from_text, normalize_skill_slug
from .industry_roles import canonicalize_role_name

TABLE_REQUIREMENTS = "industry_requirements"
TABLE_CHUNKS = "industry_knowledge_chunks"

# ---------------------------------------------------------------------------
# Phase 6: multi-signal deterministic ranking (fusion-v1).
#
# Relevant industry evidence is selected with more than one signal:
#   similarity         - semantic cosine similarity (pgvector) or deterministic
#                        keyword-overlap proxy when vectors are unavailable.
#   role_relevance     - canonical role match blended with the row's
#                        role_relevance tier (CORE / IMPORTANT / RELEVANT).
#   skill_relevance    - canonical skill/topic mention in the query.
#   source_quality     - source_quality field; low-quality sources can never
#                        dominate on similarity alone (explicit cap below).
#   importance_demand  - importance / demand signal from the benchmark row.
#   recency (freshness)- small multiplicative factor from published_at
#                        (neutral when unknown). Bounded so it can never
#                        dominate the ranking.
#
# Explicit fusion formula (deterministic, no LLM anywhere in retrieval):
#   fused = (0.40*similarity + 0.20*role_relevance + 0.15*skill_relevance
#            + 0.15*source_quality + 0.10*importance_demand) * freshness
#   if source_quality < 0.50: fused = min(fused, 0.49)   # quality gate
# Ties resolve by (fused desc, importance desc, skill asc): total order.
# ---------------------------------------------------------------------------
RANKING_VERSION = "fusion-v1"

FUSION_WEIGHTS = {
    "similarity": 0.40,
    "role_relevance": 0.20,
    "skill_relevance": 0.15,
    "source_quality": 0.15,
    "importance_demand": 0.10,
}

# Sources below this quality can never outrank solid sources on similarity.
MIN_QUALITY_FOR_RANK = 0.50
QUALITY_CAPPED_FUSED_MAX = 0.49

ROLE_TIER_SCORES = {
    "CORE": 1.0,
    "IMPORTANT": 0.75,
    "RELEVANT": 0.5,
}
DEFAULT_TIER_SCORE = 0.5

# Freshness multiplier bounds: recency nudges, never dominates.
FRESHNESS_MAX = 1.0
FRESHNESS_MIN = 0.95
FRESHNESS_FULL_YEARS = 2.0
FRESHNESS_FLOOR_YEARS = 8.0

# Deterministic stopwords for keyword signals (shared by similarity,
# skill-relevance, and role-token matching below).
_RANK_STOP_WORDS = frozenset({
    "role", "roles", "requirements", "requirement", "required", "requiring",
    "skills", "skill", "for", "the", "in", "of", "to", "a", "an", "is",
    "with", "on", "as", "and", "or", "what", "which", "that", "are",
})

# Curated knowledge chunks for offline / fallback RAG
PROTOTYPE_KNOWLEDGE_CHUNKS: List[dict] = [
    {
        "id": "chunk-swe-1",
        "role": "Software Engineer",
        "topic": "Core Fundamentals",
        "content": "Modern software engineering requires rigorous Data Structures & Algorithms problem solving, Git version control, and relational database querying with SQL. Production stability relies on automated Testing and Object-Oriented Programming (OOP) design patterns.",
        "skills_mentioned": ["Data Structures & Algorithms", "Git", "SQL", "Testing", "OOP"],
        "source": "ACM/IEEE CS2023 Curriculum Guidelines",
        "source_url": "https://csed.acm.org/",
        "source_quality": 0.90,
    },
    {
        "id": "chunk-backend-1",
        "role": "Backend Developer",
        "topic": "Server-side Architecture",
        "content": "Backend engineering emphasizes REST APIs contract design, PostgreSQL databases, Docker containerization, in-memory Caching with Redis, and System Design scalability.",
        "skills_mentioned": ["REST APIs", "PostgreSQL", "Docker", "Caching", "System Design"],
        "source": "Stack Overflow Developer Survey 2024",
        "source_url": "https://survey.stackoverflow.co/2024/",
        "source_quality": 0.90,
    },
    {
        "id": "chunk-frontend-1",
        "role": "Frontend Developer",
        "topic": "Client Web Engineering",
        "content": "Frontend development centers on modern JavaScript, TypeScript, React components, HTML/CSS layout systems, and Responsive Design mobile accessibility.",
        "skills_mentioned": ["JavaScript", "TypeScript", "React", "HTML/CSS", "Responsive Design"],
        "source": "W3C Web Standards & Guidelines",
        "source_url": "https://www.w3.org/standards/",
        "source_quality": 0.90,
    },
    {
        "id": "chunk-ai-engineer-1",
        "role": "AI Engineer",
        "topic": "Applied AI and Foundation Models",
        "content": "The emerging AI Engineer role integrates generative models and machine learning pipelines into production software. Essential competencies include Python programming, REST APIs, Deep Learning, Docker containerization, and Model Evaluation metrics.",
        "skills_mentioned": ["Python", "REST APIs", "Deep Learning", "Docker", "Model Evaluation"],
        "source": "State of AI Engineering Report 2024",
        "source_url": "https://stateof.ai/",
        "source_quality": 0.85,
    },
    {
        "id": "chunk-sre-1",
        "role": "Site Reliability Engineer",
        "topic": "Systems Reliability and Infrastructure",
        "content": "Site Reliability Engineering demands Linux systems administration, Kubernetes orchestration, CI/CD automated deployment, and Monitoring observability with Prometheus.",
        "skills_mentioned": ["Linux", "Kubernetes", "CI/CD", "Monitoring"],
        "source": "Google SRE Handbook & CNCF Survey",
        "source_url": "https://sre.google/sre-book/",
        "source_quality": 0.90,
    },
    {
        "id": "chunk-sec-1",
        "role": "Cybersecurity Engineer",
        "topic": "Threat Mitigation and AppSec",
        "content": "Cybersecurity requires in-depth Computer Networks, Network Security firewalls, Linux server administration, Application Security vulnerability mitigation, and Cryptography.",
        "skills_mentioned": ["Computer Networks", "Network Security", "Linux", "Application Security", "Cryptography"],
        "source": "CompTIA State of Cybersecurity Report",
        "source_url": "https://www.comptia.org/content/research/state-of-cybersecurity",
        "source_quality": 0.90,
    },
]


def _content_tokens(text: Any) -> List[str]:
    """Deterministic lowercase word tokens with stopwords removed."""
    words = re.findall(r"[a-z0-9+#]+", str(text or "").lower())
    return [w for w in words if w not in _RANK_STOP_WORDS and len(w) > 1]


def _text_similarity(query: str, item_text: str) -> float:
    """
    Deterministic keyword-overlap proxy for semantic similarity, used when
    no vector score exists: fraction of distinct query tokens found as
    substrings in the item text. Returns 0.0 for empty queries.
    """
    q_tokens = set(_content_tokens(query))
    if not q_tokens:
        return 0.0
    hay = str(item_text or "").lower()
    hits = sum(1 for w in q_tokens if w in hay)
    return round(hits / len(q_tokens), 3)


def _role_match_score(role: str, item_role: Any) -> float:
    """1.0 for exact canonical role match, else role-name token overlap."""
    if not role:
        return 0.0
    if str(item_role or "").strip().lower() == str(role).strip().lower():
        return 1.0
    role_tokens = set(_content_tokens(role))
    if not role_tokens:
        return 0.0
    hay = str(item_role or "").lower()
    return round(sum(1 for w in role_tokens if w in hay) / len(role_tokens), 3)


def _relevance_tier_score(role_relevance: Any) -> float:
    """Map the row's role_relevance tier (CORE/IMPORTANT/RELEVANT) to [0,1]."""
    return ROLE_TIER_SCORES.get(str(role_relevance or "").strip().upper(), DEFAULT_TIER_SCORE)


def _role_relevance_signal(role: str, item: Dict[str, Any]) -> float:
    """Blend canonical role match (0.6) with relevance tier (0.4)."""
    return round(
        0.6 * _role_match_score(role, item.get("role"))
        + 0.4 * _relevance_tier_score(item.get("role_relevance")),
        3,
    )


def _skill_relevance_signal(query: str, skill: Any) -> float:
    """
    Fraction of the canonical skill's tokens mentioned in the query.
    Uses taxonomy-normalized skill names so aliases resolve identically.
    """
    canonical = normalize_skill(str(skill or "")) or str(skill or "")
    skill_tokens = set(_content_tokens(canonical))
    if not skill_tokens:
        return 0.0
    q_tokens = set(_content_tokens(query))
    if not q_tokens:
        return 0.0
    return round(len(skill_tokens & q_tokens) / len(skill_tokens), 3)


def _expand_role_query(role: str, query: str) -> str:
    """Add domain intent only when the resolved role supports that intent."""
    role_name = canonicalize_role_name(role) or role
    q = str(query or "").strip()
    q_low = q.lower()
    mobile_terms = ("mobile", "app development", "app developer", "flutter", "react native", "android", "ios")
    if role_name == "Mobile Developer" and any(term in q_low for term in mobile_terms):
        # This is a ranking vocabulary expansion, not a claim that every mobile
        # developer must use every framework. Role requirements still carry the
        # benchmark importance and provenance for each technology.
        return f"{q} mobile Android iOS Flutter React Native REST APIs Git Responsive Design"
    return q


def _quality_signal(item: Dict[str, Any]) -> float:
    """Source quality clamped to [0,1]; missing quality is neutral 0.5."""
    try:
        q = float(item.get("source_quality", 0.5))
    except (TypeError, ValueError):
        q = 0.5
    return max(0.0, min(1.0, q))


def _importance_demand_signal(item: Dict[str, Any]) -> float:
    """Benchmark weight signal: 0.6*importance + 0.4*demand."""
    try:
        imp = float(item.get("importance", 0.5))
    except (TypeError, ValueError):
        imp = 0.5
    try:
        dem = float(item.get("demand", 0.5))
    except (TypeError, ValueError):
        dem = 0.5
    return round(max(0.0, min(1.0, 0.6 * imp + 0.4 * dem)), 3)


def _parse_retrieval_date(value: Any) -> Optional[Any]:
    """Parse published_at/retrieved_at defensively; None when unknown."""
    if not value:
        return None
    try:
        from datetime import datetime as _dt

        text = str(value).strip().replace("Z", "+00:00")
        parsed = _dt.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_dt.now().astimezone().tzinfo)
        return parsed
    except Exception:
        return None


def _freshness_factor(
    published_at: Any,
    retrieved_at: Any = None,
    now: Any = None,
) -> float:
    """
    Small recency multiplier in [0.95, 1.0]: full weight within 2 years,
    linear decay to a 0.95 floor at 8+ years, neutral 1.0 when unknown.
    `now` is injectable so tests stay deterministic.
    """
    try:
        from datetime import datetime as _dt, timezone as _tz

        ref = _parse_retrieval_date(published_at) or _parse_retrieval_date(retrieved_at)
        if ref is None:
            return FRESHNESS_MAX
        current = now or _dt.now(_tz.utc)
        try:
            age_days = (current - ref).days
        except Exception:
            return FRESHNESS_MAX
        if age_days < 0:
            return FRESHNESS_MAX
        age_years = age_days / 365.25
        if age_years <= FRESHNESS_FULL_YEARS:
            return FRESHNESS_MAX
        if age_years >= FRESHNESS_FLOOR_YEARS:
            return FRESHNESS_MIN
        span = FRESHNESS_FLOOR_YEARS - FRESHNESS_FULL_YEARS
        decayed = FRESHNESS_MAX - (FRESHNESS_MAX - FRESHNESS_MIN) * (
            (age_years - FRESHNESS_FULL_YEARS) / span
        )
        return round(max(FRESHNESS_MIN, min(FRESHNESS_MAX, decayed)), 3)
    except Exception:
        return FRESHNESS_MAX


def _fuse_signals(
    item: Dict[str, Any],
    role: str,
    query: str,
    similarity: float,
    now: Any = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Explicit deterministic fusion. Returns (fused_score, ranking_detail).
    ranking_detail records every component so any ordering is explainable.
    """
    try:
        sim = max(0.0, min(1.0, float(similarity)))
    except (TypeError, ValueError):
        sim = 0.0
    role_rel = _role_relevance_signal(role, item)
    skill_rel = _skill_relevance_signal(query, item.get("skill", ""))
    quality = _quality_signal(item)
    impdem = _importance_demand_signal(item)
    freshness = _freshness_factor(item.get("published_at"), item.get("retrieved_at"), now)

    fused = (
        FUSION_WEIGHTS["similarity"] * sim
        + FUSION_WEIGHTS["role_relevance"] * role_rel
        + FUSION_WEIGHTS["skill_relevance"] * skill_rel
        + FUSION_WEIGHTS["source_quality"] * quality
        + FUSION_WEIGHTS["importance_demand"] * impdem
    )
    quality_capped = False
    if quality < MIN_QUALITY_FOR_RANK and fused > QUALITY_CAPPED_FUSED_MAX:
        # Low-quality sources can never dominate on similarity alone.
        fused = QUALITY_CAPPED_FUSED_MAX
        quality_capped = True
    fused = round(max(0.0, min(1.0, fused)) * freshness, 3)
    detail = {
        "similarity": round(sim, 3),
        "role_relevance": role_rel,
        "skill_relevance": skill_rel,
        "source_quality": quality,
        "importance_demand": impdem,
        "freshness": freshness,
        "fused_score": fused,
        "quality_capped": quality_capped,
        "weights_version": RANKING_VERSION,
    }
    return fused, detail


def _catalog_index_for_role(role: str) -> Dict[Any, dict]:
    """Index catalog rows by (role.lower, skill-key) for metadata enrichment."""
    index: Dict[Any, dict] = {}
    try:
        for row in industry_service.list_by_role(role):
            canon = normalize_skill(str(row.get("skill", ""))) or str(row.get("skill", ""))
            index[(str(row.get("role", "")).lower(), canon.lower())] = row
            index[(str(row.get("role", "")).lower(), str(row.get("skill", "")).lower())] = row
    except Exception:
        pass
    return index


def _enrich_with_catalog(item: dict, catalog_index: Dict[Any, dict]) -> dict:
    """
    Fill source-metadata gaps on vector-path rows from the canonical catalog
    (source_quality, published_at, retrieved_at, evidence_context,
    role_relevance, dimensions). RPC values always win when present.
    """
    enriched = dict(item)
    try:
        canon = normalize_skill(str(item.get("skill", ""))) or str(item.get("skill", ""))
        row = catalog_index.get((str(item.get("role", "")).lower(), canon.lower()))
        if not row:
            return enriched
        for key in (
            "required_level", "importance", "demand", "interview_relevance",
            "industry_confidence", "source", "source_url", "source_quality",
            "evidence_context", "published_at", "retrieved_at", "description",
            "role_relevance", "source_version", "source_reference",
            "source_occupation", "mapping_version", "skill_category", "version",
            # Phase 3: contextual employer-outcome annotation rides the same
            # enrichment (both retrieval paths share this function). Never a
            # ranking input — _fuse_signals reads only its fixed signals.
            "outcome_overlay",
        ):
            if enriched.get(key) in (None, "") and row.get(key) not in (None, ""):
                enriched[key] = row.get(key)
    except Exception:
        pass
    return enriched


def _rank_items(
    items: List[dict],
    role: str,
    query: str,
    top_k: int,
    similarities: Optional[Dict[int, float]] = None,
    now: Any = None,
) -> Tuple[List[dict], int]:
    """
    Fuse, quality-gate, deduplicate, and deterministically order candidates.
    `similarities` optionally maps item index -> semantic similarity
    (vector cosine); otherwise the keyword-overlap proxy is used.
    Returns (ranked_items, duplicates_removed). Each item gains `similarity`
    (raw semantic component), `fused_score`, and an explainable `ranking`
    breakdown. Canonical skill extraction is enforced on every item.
    """
    scored: List["tuple[float, float, str, dict]"] = []
    for idx, raw in enumerate(items or []):
        item = dict(raw)
        if similarities is not None and idx in similarities:
            sim = similarities[idx]
        else:
            sim = _text_similarity(
                query,
                f"{item.get('skill', '')} {item.get('description', '')} "
                f"{item.get('evidence_context', '')} {item.get('skill_category', '')} "
                f"{item.get('topic', '')}",
            )
        canonical_skill = normalize_skill(str(item.get("skill", ""))) or str(item.get("skill", ""))
        item["skill"] = canonical_skill
        fused, detail = _fuse_signals(item, role, query, sim, now)
        item["similarity"] = detail["similarity"]
        item["fused_score"] = fused
        item["ranking"] = detail
        try:
            tiebreak_imp = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            tiebreak_imp = 0.5
        scored.append((fused, tiebreak_imp, canonical_skill, item))

    # Deduplicate by (role, canonical skill): keep the strongest fused item.
    # Same evidence counted once, never stacked.
    best_by_key: Dict[Any, "tuple[float, float, str, dict]"] = {}
    for entry in scored:
        fused, imp, skill, item = entry
        key = (str(item.get("role", role)).lower(), skill.lower())
        prev = best_by_key.get(key)
        if prev is None or (fused, imp, skill) > (prev[0], prev[1], prev[2]):
            best_by_key[key] = entry
    duplicates_removed = len(scored) - len(best_by_key)

    ordered = sorted(
        best_by_key.values(), key=lambda e: (-e[0], -e[1], e[2])
    )
    try:
        limit = max(1, int(top_k))
    except (TypeError, ValueError):
        limit = 10
    return [entry[3] for entry in ordered[:limit]], duplicates_removed


def _chunk_matches_role(chunk: dict, role: str) -> bool:
    """
    Role-relevance gate for knowledge chunks (shared rule): exact role match
    or at least one meaningful role-title token in the chunk text. Vector
    chunks must pass it too, so unrelated roles can never synthesize
    requirements from similarity alone.
    """
    role_tokens = [w for w in str(role or "").lower().split() if w not in _RANK_STOP_WORDS and len(w) > 1]
    text = f"{chunk.get('role', '')} {chunk.get('topic', '')} {chunk.get('content', '')}".lower()
    ch_role = str(chunk.get("role", "")).lower()
    cleaned = str(role or "").strip().lower()
    exact = bool(ch_role) and (ch_role in cleaned or cleaned in ch_role)
    return bool(exact or sum(1 for w in role_tokens if w in text) > 0)


def _client() -> Optional[Client]:
    return get_supabase_client()


async def _vector_search_chunks(query: str, top_k: int) -> Optional[List[dict]]:
    """Attempt vector similarity search across industry_knowledge_chunks table."""
    if not embedding_service.is_configured():
        return None

    try:
        emb = await embedding_service.embed_text(query)
        if not emb:
            return None
        c = _client()
        if c is None:
            return None

        rpc_res = c.rpc("match_industry_knowledge_chunks", {
            "query_embedding": emb,
            "match_count": top_k,
        }).execute()

        if rpc_res.data:
            return rpc_res.data
        return None
    except Exception:
        return None


async def _vector_search(role: str, query: str, top_k: int) -> Optional[List[dict]]:
    """
    Attempt vector similarity search across industry_requirements if configured.
    Returns list of items with cosine similarity scores, or None to trigger fallback.
    """
    if not embedding_service.is_configured():
        return None

    try:
        emb = await embedding_service.embed_text(query)
        if not emb:
            return None
        c = _client()
        if c is None:
            return None

        rpc_res = c.rpc("match_industry_requirements", {
            "query_embedding": emb,
            "filter_role": role,
            "match_count": top_k,
        }).execute()

        if rpc_res.data:
            normalized = []
            for item in rpc_res.data:
                canon = normalize_skill(item.get("skill", "")) or item.get("skill", "")
                try:
                    sim = round(float(item.get("similarity", 0.8)), 3)
                except (TypeError, ValueError):
                    sim = 0.8
                normalized.append({
                    **item,
                    "skill": canon,
                    "similarity": max(0.0, min(1.0, sim)),
                })
            return normalized
        return None
    except Exception:
        return None


def _attach_requirement_evidence(item: dict, role: str) -> dict:
    """
    Attach requirement trustworthiness metadata to one retrieval item:
    evidence_strength tier plus supporting knowledge-chunk references that
    mention the skill. Chunk bodies are never copied, references only.
    Missing data degrades to honest defaults; nothing is fabricated.
    """
    try:
        skill = str(item.get("skill", "") or "")
        if "evidence_strength" not in item or not item.get("evidence_strength"):
            try:
                quality = float(item.get("source_quality", 0.5))
            except (TypeError, ValueError):
                quality = 0.5
            try:
                confidence = float(item.get("industry_confidence", 0.85))
            except (TypeError, ValueError):
                confidence = 0.85
            item["evidence_strength"] = industry_service.classify_requirement_evidence(
                1, quality, confidence
            )
        if "supporting_chunks" not in item:
            try:
                item["supporting_chunks"] = industry_service.supporting_chunk_refs(
                    role, skill
                )
            except Exception:
                item["supporting_chunks"] = []
    except Exception:
        pass
    return item


def _requirements_for_retrieval(role: str, location: Any = None) -> List[dict]:
    """Merged baseline+dynamic requirements for retrieval (additive).

    Uses the intelligence view's gap-engine projection so unmapped dynamic
    concepts never enter ranking (taxonomy cannot drift). Falls back to the
    baseline catalog when intelligence is unavailable. Never raises.
    """
    try:
        from . import industry_intelligence as _intel

        view = _intel.build_role_intelligence(role, location=location, include_dynamics=True)
        reqs = _intel.to_gap_engine_requirements(view)
        if reqs:
            return reqs
    except Exception:
        pass
    try:
        return industry_service.list_by_role(role)
    except Exception:
        return []


def _attach_intelligence_metadata(items: List[dict], role: str, location: Any = None) -> None:
    """Enrich vector-path items with trend/freshness/location from the view.

    RPC values always win for core dimensions; only additive intelligence
    fields are filled. Never raises; degrades gracefully when unavailable.
    """
    try:
        from . import industry_intelligence as _intel

        view = _intel.build_role_intelligence(role, location=location, include_dynamics=True)
        by_skill = {str(s.get("skill", "")).lower(): s for s in (view.get("skills") or [])}
        for it in items or []:
            ref = by_skill.get(str(it.get("skill", "")).lower())
            if not ref:
                continue
            for key in ("trend", "freshness", "data_origin", "location",
                        "collected_at", "last_updated", "mapping_status"):
                if it.get(key) in (None, "") and ref.get(key) not in (None, ""):
                    it[key] = ref.get(key)
    except Exception:
        pass


def _append_missing_dynamic_requirements(
    items: List[dict], role: str, location: Any = None
) -> None:
    """Append dynamic-only mapped requirements absent from vector results.

    Vector RPCs only return persisted rows, so dynamic-only skills (e.g. a
    rising overlay with no DB row yet) would otherwise be invisible on the
    vector path. Only skills NOT already present are appended, so pgvector
    ranking for overlapping skills is untouched; unmapped concepts are never
    appended so the taxonomy cannot drift. Mutates `items`; never raises.
    """
    try:
        from . import industry_intelligence as _intel

        present = set()
        for it in items or []:
            canon = normalize_skill(str(it.get("skill", ""))) or str(it.get("skill", ""))
            present.add(canon.lower())
        view = _intel.build_role_intelligence(role, location=location, include_dynamics=True)
        for req in _intel.to_gap_engine_requirements(view):
            canon = normalize_skill(str(req.get("skill", ""))) or str(req.get("skill", ""))
            if canon.lower() in present:
                continue
            items.append(dict(req))
            present.add(canon.lower())
    except Exception:
        pass


async def retrieve(role: str, query: Optional[str] = None, top_k: int = 10, location: Any = None) -> dict:
    """
    Retrieve relevant industry requirements for a target role and query.
    Always returns normalized canonical skills and preserves all 5 industry
    dimensions plus full source metadata (source, source_url, source_quality,
    published_at, retrieved_at, similarity, role/topic).

    Both paths rank with the same explicit fusion formula (see FUSION_WEIGHTS):
    vector cosine similarity when pgvector is available, the deterministic
    keyword-overlap proxy otherwise. Low-quality sources are capped so they
    can never dominate on similarity alone; duplicates collapse to one item.

    Optional `location` enables Dynamic Industry Intelligence overlays
    (additive): the fallback path ranks merged baseline+dynamic requirements;
    the vector path keeps pgvector ranking, appends dynamic-only mapped skills
    missing from RPC coverage, then enriches items with trend/freshness/
    location metadata. Unmapped dynamic concepts never enter
    retrieval so the canonical taxonomy cannot drift.
    """
    canonical_role = canonicalize_role_name(role) or role.strip()
    q = (query or f"skills required for {canonical_role}").strip()
    ranking_query = _expand_role_query(canonical_role, q)

    # 1. Vector search path (pgvector kept; fusion + gating applied on top).
    # Source metadata gaps are filled from the canonical catalog (RPC values
    # win), so every vector-path item carries the same provenance contract.
    vec_results = await _vector_search(canonical_role, ranking_query, top_k)
    if vec_results:
        catalog_index = _catalog_index_for_role(canonical_role)
        vec_results = [_enrich_with_catalog(dict(it), catalog_index) for it in vec_results]
        _append_missing_dynamic_requirements(vec_results, canonical_role, location)
        for it in vec_results:
            _attach_requirement_evidence(it, canonical_role)
        _attach_intelligence_metadata(vec_results, canonical_role, location)
        similarities = {i: max(0.0, min(1.0, float(it.get("similarity", 0.8)))) for i, it in enumerate(vec_results)}
        ranked, duplicates_removed = _rank_items(vec_results, canonical_role, ranking_query, top_k, similarities)
        for it in ranked:
            # Retrieval relevance: the fused multi-signal score.
            it["similarity"] = it.pop("fused_score", it.get("similarity", 0.0))
        return {
            "role": canonical_role,
            "query": q,
            "count": len(ranked),
            "items": ranked,
            "ranking": RANKING_VERSION,
            "duplicates_removed": duplicates_removed,
            "note": "retrieved via vector search (pgvector) with multi-signal fusion ranking",
        }

    # 2. Deterministic fallback path (embeddings/RPC unavailable): same
    # fusion ranking over merged baseline+dynamic rows, keyword-overlap as the
    # similarity. Dynamic overlays feed the EXISTING ranking (no second RAG).
    try:
        items = _requirements_for_retrieval(canonical_role, location)
        if not items:
            items = industry_service.get_all(limit=top_k)
            if not items:
                return {
                    "role": canonical_role,
                    "query": q,
                    "count": 0,
                    "items": [],
                    "ranking": RANKING_VERSION,
                    "duplicates_removed": 0,
                    "note": "no industry requirements found for target role",
                }

        ranked, duplicates_removed = _rank_items(items, canonical_role, ranking_query, top_k)
        for it in ranked:
            _attach_requirement_evidence(it, canonical_role)
            it["similarity"] = it.pop("fused_score", it.get("similarity", 0.0))

        return {
            "role": canonical_role,
            "query": q,
            "count": len(ranked),
            "items": ranked,
            "ranking": RANKING_VERSION,
            "duplicates_removed": duplicates_removed,
            "note": "INAURA Industry Knowledge Catalog — authentic benchmarks with source attribution; retrieved via deterministic fallback with multi-signal fusion ranking",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)[:200]}")


async def synthesize_custom_role(custom_role: str, query: Optional[str] = None) -> dict:
    """
    RAG-driven dynamic requirement synthesis for custom / non-catalog roles (e.g., 'AI Engineer'):
    1. Check if role is an alias for a catalog role. If so, return catalog requirements.
    2. Search knowledge chunks via vector search or semantic keyword matching.
    3. Extract canonical skills mentioned using extract_known_skills_from_text.
    4. If fewer than 2 distinct canonical skills are identified, return honest failure notice.
    5. If >= 2 skills found, synthesize structured requirements with honest confidence (e.g. 0.60-0.70).
    """
    cleaned_role = custom_role.strip()

    # If it is an alias for a catalog role, resolve directly
    resolved = canonicalize_role_name(cleaned_role)
    if resolved:
        catalog_reqs = industry_service.list_by_role(resolved)
        return {
            "status": "catalog_match",
            "role": resolved,
            "is_custom": False,
            "requirements": catalog_reqs,
            "skills_count": len(catalog_reqs),
            "confidence": 0.90,
            "source_summary": "Resolved directly to catalog benchmark",
            "note": f"Input '{cleaned_role}' resolved to catalog role '{resolved}'.",
        }

    q = (query or f"role requirements and skills for {cleaned_role}").strip()

    # 1. Retrieve knowledge chunks (vector search if available, else prototype chunks)
    matched_chunks: List[dict] = []
    vec_chunks = await _vector_search_chunks(q, top_k=5)
    if vec_chunks:
        # Role-relevance gate applies to vector chunks too: similarity alone
        # must never pull unrelated roles into a custom synthesis.
        matched_chunks.extend([ch for ch in vec_chunks if _chunk_matches_role(ch, cleaned_role)])

    if not matched_chunks:
        # Fallback to prototype knowledge chunks
        STOP_WORDS = {
            "role", "requirements", "requirement", "and", "skills", "skill",
            "for", "the", "in", "of", "to", "a", "an", "is", "with", "on", "as"
        }
        role_tokens = [w for w in cleaned_role.lower().split() if w not in STOP_WORDS and len(w) > 1]
        query_tokens = [w for w in q.lower().split() if w not in STOP_WORDS and len(w) > 1]

        scored_chunks = []
        for ch in PROTOTYPE_KNOWLEDGE_CHUNKS:
            text = f"{ch.get('role','')} {ch.get('topic','')} {ch.get('content','')}".lower()
            ch_role = ch.get("role", "").lower()

            # Must match the role name or at least one meaningful domain token from role title
            role_token_matches = sum(1 for w in role_tokens if w in text)
            exact_role_match = ch_role in cleaned_role.lower() or cleaned_role.lower() in ch_role

            if exact_role_match or role_token_matches > 0:
                overlap = role_token_matches * 2 + sum(1 for w in query_tokens if w in text)
                scored_chunks.append((overlap, ch))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        matched_chunks = [ch for _, ch in scored_chunks]

    # Combine chunk texts
    combined_text = " ".join([ch.get("content", "") for ch in matched_chunks])

    # 2. Extract canonical skills mentioned
    extracted_skills = extract_known_skills_from_text(combined_text)
    distinct_skills = {s.canonical_name: s for s in extracted_skills}

    # 3. Honest rejection if insufficient data
    if len(distinct_skills) < 2:
        return {
            "status": "insufficient_data",
            "role": cleaned_role,
            "is_custom": True,
            "requirements": [],
            "skills_count": len(distinct_skills),
            "confidence": 0.0,
            "source_summary": "Insufficient benchmark data",
            "note": f"INAURA could not locate sufficient verifiable industry benchmark data for '{cleaned_role}' (found {len(distinct_skills)} skills, minimum 2 required). No requirements fabricated.",
        }

    # 4. Synthesize structured requirements from knowledge chunks
    synthesized_reqs: List[dict] = []
    chunk_sources = list({ch.get("source", "Industry Knowledge") for ch in matched_chunks if ch.get("source")})
    primary_source = f"RAG Synthesis ({len(chunk_sources)} sources: {', '.join(chunk_sources[:2])})" if chunk_sources else "Dynamic RAG Synthesis"
    primary_url = matched_chunks[0].get("source_url") if matched_chunks else None

    for skill_name, skill_def in distinct_skills.items():
        # Frequency of mention in chunks
        mention_count = combined_text.lower().count(skill_name.lower())
        mention_factor = min(1.0, 0.60 + 0.10 * mention_count)

        # Baseline dimensions for synthesized requirements
        req_level = round(0.70 * mention_factor, 2)
        importance = round(0.75 * mention_factor, 2)
        demand = round(0.70 * mention_factor, 2)
        interview = round(0.65 * mention_factor, 2)
        # Bounded honest confidence reflecting synthesis
        ind_conf = round(0.60 + 0.05 * min(2, len(matched_chunks)), 2)

        # Supporting chunks that actually mention this skill (references
        # only: chunk id, role, topic, source, url -- never chunk bodies).
        skill_chunk_refs: List[dict] = []
        try:
            for ch in matched_chunks:
                mentioned = ch.get("skills_mentioned") or []
                if isinstance(mentioned, str):
                    mentioned = [mentioned]
                names = set()
                for name in mentioned:
                    canon = normalize_skill(str(name)) or str(name)
                    names.add(canon)
                    names.add(str(name))
                if skill_name in names or skill_def.id in {str(n).lower() for n in mentioned}:
                    skill_chunk_refs.append({
                        "chunk_id": ch.get("id"),
                        "role": ch.get("role"),
                        "topic": ch.get("topic"),
                        "source": ch.get("source"),
                        "source_url": ch.get("source_url"),
                    })
        except Exception:
            skill_chunk_refs = []

        synthesized_reqs.append({
            "id": f"syn-{normalize_skill_slug(skill_name)}",
            "role": cleaned_role,
            "skill": skill_name,
            "skill_slug": skill_def.id,
            "skill_category": skill_def.category,
            "required_level": req_level,
            "importance": importance,
            "demand": demand,
            "interview_relevance": interview,
            "industry_confidence": ind_conf,
            "source": primary_source,
            "source_url": primary_url,
            "source_quality": 0.70,
            "evidence_strength": industry_service.classify_requirement_evidence(
                len(chunk_sources), 0.70, ind_conf
            ),
            "evidence_context": f"Synthesized from {len(matched_chunks)} industry benchmark knowledge chunks mentioning {skill_name}.",
            "published_at": "2024-05-01",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "supporting_chunks": skill_chunk_refs[:5],
            "description": skill_def.description,
            "version": "2026.1-rag-synth",
            "metadata": {"is_synthesized": True, "chunk_count": len(matched_chunks)},
        })

    synthesized_reqs.sort(key=lambda x: x["importance"], reverse=True)

    return {
        "status": "synthesized",
        "role": cleaned_role,
        "is_custom": True,
        "requirements": synthesized_reqs,
        "skills_count": len(synthesized_reqs),
        "confidence": 0.65,
        "source_summary": primary_source,
        "note": f"Synthesized requirement profile for '{cleaned_role}' across {len(matched_chunks)} industry benchmark knowledge chunks. Confidence calibrated conservatively for custom role.",
    }
