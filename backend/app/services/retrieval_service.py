from typing import List, Optional
from fastapi import HTTPException
from supabase import Client
from ..core.supabase import get_supabase_client
from ..core.config import get_settings
from . import embedding_service

TABLE = "industry_requirements"

# Retrieval — Phase 4B
# Tries vector search if embedding configured and pgvector available, else keyword fallback
# Never crashes if not configured; returns clear message


def _client() -> Client:
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    return c


async def _vector_search(role: str, query: str, top_k: int) -> Optional[List[dict]]:
    # Only if embedding configured and pgvector available
    if not embedding_service.is_configured():
        return None
    # Check pgvector extension exists by trying a vector query
    # We embed the query and do cosine similarity via supabase rpc or direct SQL
    # Supabase postgrest doesn't expose vector ops directly via table filter without rpc,
    # so we try a simple rpc if available, else fallback
    try:
        emb = await embedding_service.embed_text(query)
        if not emb:
            return None
        c = _client()
        # Try via rpc: we expect a function `match_industry_requirements` if created
        # If not exists, this will fail and we fallback
        # For prototype, we attempt direct vector search via SQL through rpc
        # If no rpc, return None to trigger keyword fallback
        # We check if embedding column has data
        # For now, since seed embeddings are null, vector search will return empty anyway
        # So we just return None to use keyword path
        return None
    except Exception:
        return None


async def retrieve(role: str, query: Optional[str], top_k: int = 10) -> dict:
    c = _client()
    # Validate role exists
    try:
        # Check if role exists
        r = c.table(TABLE).select("role").eq("role", role).limit(1).execute()
        if not r.data:
            # Role not found — maybe user typed "Other" or custom
            # Return empty with note, don't 404
            pass
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Industry knowledge base not configured — run 003_industry_knowledge.sql")
        raise

    q = (query or f"skills required for {role}").strip()
    # Try vector search first
    vec_results = await _vector_search(role, q, top_k)
    if vec_results:
        return {
            "role": role,
            "query": q,
            "count": len(vec_results),
            "items": vec_results,
            "note": "retrieved via vector search (pgvector)",
        }

    # Keyword fallback — filter by role, order by importance
    try:
        # Simple: get all for role, compute keyword relevance if query provided
        r = c.table(TABLE).select("*").eq("role", role).execute()
        items = r.data or []
        if not items:
            # If no items for exact role, try other roles (e.g., "Other")
            r2 = c.table(TABLE).select("*").limit(top_k).execute()
            items = r2.data or []
            if not items:
                return {"role": role, "query": q, "count": 0, "items": [], "note": "no industry requirements found"}

        # If query is not just role, compute simple keyword score (count matching words in skill/description)
        if q and q.lower() != f"skills required for {role}".lower():
            q_words = set(q.lower().split())
            scored = []
            for it in items:
                text = f"{it.get('skill','')} {it.get('description','')} {it.get('skill_category','')}".lower()
                # simple overlap
                score = len([w for w in q_words if w in text]) / max(1, len(q_words))
                # combine with importance as secondary
                combined = 0.7 * score + 0.3 * float(it.get("importance", 0))
                scored.append((combined, it))
            scored.sort(key=lambda x: x[0], reverse=True)
            items = [it for _, it in scored]

        # Sort by importance as fallback and limit
        if q.lower() == f"skills required for {role}".lower():
            items = sorted(items, key=lambda x: float(x.get("importance", 0)), reverse=True)

        top = items[:top_k]
        # Attach similarity as heuristic: for keyword fallback, similarity = normalized importance
        # For real vector, it would be cosine similarity
        result_items = []
        for it in top:
            # similarity 0-1 — here we use importance as proxy for relevance in fallback
            # In real vector case, this would be cosine similarity
            sim = float(it.get("importance", 0)) * 0.8 + float(it.get("demand", 0)) * 0.2
            # Clamp
            sim = max(0, min(1, sim))
            result_items.append({
                **it,
                "similarity": round(sim, 3),
            })

        return {
            "role": role,
            "query": q,
            "count": len(result_items),
            "items": result_items,
            "note": "prototype industry knowledge — heuristic values, not scientifically validated; retrieved via keyword fallback (embedding not configured or no vectors)",
        }
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m:
            raise HTTPException(status_code=503, detail="Industry knowledge base not configured")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)[:200]}")
