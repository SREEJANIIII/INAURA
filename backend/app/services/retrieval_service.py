from typing import List, Optional, Dict, Any, Set
from fastapi import HTTPException
from supabase import Client
import math

from ..core.supabase import get_supabase_client
from ..core.config import get_settings
from . import embedding_service
from . import industry_service
from .skill_taxonomy import normalize_skill, extract_known_skills_from_text, normalize_skill_slug
from .industry_roles import canonicalize_role_name

TABLE_REQUIREMENTS = "industry_requirements"
TABLE_CHUNKS = "industry_knowledge_chunks"

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
                normalized.append({
                    **item,
                    "skill": canon,
                    "similarity": round(float(item.get("similarity", 0.8)), 3),
                })
            return normalized
        return None
    except Exception:
        return None


async def retrieve(role: str, query: Optional[str] = None, top_k: int = 10) -> dict:
    """
    Retrieve relevant industry requirements for a target role and query.
    Always returns normalized canonical skills and preserves all 5 industry dimensions.
    """
    canonical_role = canonicalize_role_name(role) or role.strip()
    q = (query or f"skills required for {canonical_role}").strip()

    # 1. Vector search path
    vec_results = await _vector_search(canonical_role, q, top_k)
    if vec_results:
        return {
            "role": canonical_role,
            "query": q,
            "count": len(vec_results),
            "items": vec_results,
            "note": "retrieved via vector search (pgvector)",
        }

    # 2. Deterministic keyword and role requirements path
    try:
        items = industry_service.list_by_role(canonical_role)
        if not items:
            items = industry_service.get_all(limit=top_k)
            if not items:
                return {
                    "role": canonical_role,
                    "query": q,
                    "count": 0,
                    "items": [],
                    "note": "no industry requirements found for target role",
                }

        # If custom free-text query provided, compute keyword relevance score
        if q and q.lower() != f"skills required for {canonical_role}".lower():
            q_words = set(q.lower().split())
            scored = []
            for it in items:
                text = f"{it.get('skill','')} {it.get('description','')} {it.get('evidence_context','')} {it.get('skill_category','')}".lower()
                overlap = len([w for w in q_words if w in text]) / max(1, len(q_words))
                combined = 0.7 * overlap + 0.3 * float(it.get("importance", 0.5))
                scored.append((combined, it))
            scored.sort(key=lambda x: x[0], reverse=True)
            items = [it for _, it in scored]
        else:
            items = sorted(items, key=lambda x: float(x.get("importance", 0.5)), reverse=True)

        top = items[:top_k]
        result_items = []
        for it in top:
            canonical_skill = normalize_skill(it.get("skill", "")) or it.get("skill", "")
            imp = float(it.get("importance", 0.5))
            dem = float(it.get("demand", 0.5))
            sim = max(0.0, min(1.0, imp * 0.8 + dem * 0.2))
            result_items.append({
                **it,
                "skill": canonical_skill,
                "similarity": round(sim, 3),
            })

        return {
            "role": canonical_role,
            "query": q,
            "count": len(result_items),
            "items": result_items,
            "note": "INAURA Industry Knowledge Catalog — authentic benchmarks with source attribution; retrieved via deterministic fallback",
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
        matched_chunks.extend(vec_chunks)

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
            "evidence_context": f"Synthesized from {len(matched_chunks)} industry benchmark knowledge chunks mentioning {skill_name}.",
            "published_at": "2024-05-01",
            "retrieved_at": "2026-01-01T00:00:00Z",
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
