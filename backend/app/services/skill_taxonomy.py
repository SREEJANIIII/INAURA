from typing import Dict, List, Optional
from supabase import Client
from fastapi import HTTPException
from ..core.supabase import get_supabase_client

# Cache for skills taxonomy
_cache: Optional[Dict[str, dict]] = None  # canonical_name -> row


def _load_cache(client: Client) -> Dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        r = client.table("skills").select("*").execute()
        data = r.data or []
        _cache = {row["canonical_name"]: row for row in data}
        return _cache
    except Exception:
        return {}


def get_all_skills(client: Client) -> List[dict]:
    return list(_load_cache(client).values())


def normalize_skill(raw: str, client: Client) -> Optional[str]:
    """
    Map raw skill string to canonical_name via aliases and canonical list.
    Returns canonical_name or None if no match.
    Deterministic, case-insensitive, handles variations like "React.js" -> "react".
    """
    if not raw or not raw.strip():
        return None
    key = raw.strip().lower()
    # Direct canonical match
    cache = _load_cache(client)
    if key in cache:
        return key
    # Alias match
    for canonical, row in cache.items():
        aliases = [a.lower() for a in (row.get("aliases") or [])]
        if key in aliases:
            return canonical
        # Also handle normalized alias without punctuation
        norm_key = key.replace(".", "").replace("-", "_").replace(" ", "_")
        for alias in aliases:
            norm_alias = alias.lower().replace(".", "").replace("-", "_").replace(" ", "_")
            if norm_key == norm_alias:
                return canonical
    # Fallback heuristic: normalize and check canonical with same normalization
    norm_key = key.replace(".", "").replace("-", "_").replace(" ", "_").replace("/", "_")
    for canonical in cache:
        norm_canonical = canonical.replace(".", "").replace("-", "_")
        if norm_key == norm_canonical:
            return canonical
    # Also check display_name
    for canonical, row in cache.items():
        display = row.get("display_name", "").lower()
        if key == display.lower():
            return canonical
    return None


def clear_cache():
    global _cache
    _cache = None
