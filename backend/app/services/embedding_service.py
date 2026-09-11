from typing import List, Optional
import httpx
from ..core.config import get_settings

# Embedding abstraction — Phase 4B (migrated to Gemini)
# Supports: gemini (gemini-embedding-001, text-embedding-004), fallback none
# If not configured, app still starts; retrieval falls back to keyword

DIMENSION = 768  # gemini-embedding-001 with outputDimensionality=768 (MRL)
DEFAULT_GEMINI_MODEL = "gemini-embedding-001"
LEGACY_GEMINI_MODEL = "text-embedding-004"  # deprecated Jan 2026, kept for reference


def _resolve_api_key() -> Optional[str]:
    s = get_settings()
    # Prefer explicit embedding key, fallback to GOOGLE_API_KEY for Gemini
    key = s.embedding_api_key or s.google_api_key
    if key and key.strip():
        return key.strip()
    return None


def is_configured() -> bool:
    s = get_settings()
    provider = (s.embedding_provider or "").strip().lower()
    if provider in ("", "none", "disabled"):
        return False
    # Only gemini is supported now (openai removed)
    if provider not in ("gemini", "google"):
        return False
    return bool(_resolve_api_key())


def get_provider() -> Optional[str]:
    s = get_settings()
    provider = s.embedding_provider
    if provider:
        return provider.strip().lower()
    return None


def _get_model() -> str:
    s = get_settings()
    # EMBEDDING_MODEL takes precedence, else gemini_embedding_model, else default
    raw = s.embedding_model or getattr(s, "gemini_embedding_model", None) or DEFAULT_GEMINI_MODEL
    raw = raw.strip()
    # Normalize "models/gemini-embedding-001" -> "gemini-embedding-001"
    if raw.startswith("models/"):
        raw = raw[len("models/"):]
    if not raw:
        raw = DEFAULT_GEMINI_MODEL
    return raw


def _get_dimension() -> int:
    s = get_settings()
    if s.embedding_dimension and isinstance(s.embedding_dimension, int) and s.embedding_dimension > 0:
        return int(s.embedding_dimension)
    return DIMENSION


async def _embed_gemini(texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> List[List[float]]:
    """
    Call Google Gemini embeddings API.
    Uses batchEmbedContents for batch, embedContent for single.
    Supports outputDimensionality via MRL (768 recommended).
    """
    api_key = _resolve_api_key()
    if not api_key:
        raise RuntimeError("Embedding API key not configured (set EMBEDDING_API_KEY or GOOGLE_API_KEY)")

    model = _get_model()
    dimension = _get_dimension()

    # Use batch endpoint if multiple texts
    if len(texts) == 1:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
        params = {"key": api_key}
        payload = {
            "model": f"models/{model}",
            "content": {"parts": [{"text": texts[0]}]},
            "taskType": task_type,
            "outputDimensionality": dimension,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, params=params, json=payload, headers={"Content-Type": "application/json"})
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini embedding API error {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            # Response: {"embedding": {"values": [...]}}
            embedding = data.get("embedding", {}).get("values")
            if embedding is None:
                # Some versions return {"embedding": {"values": [...]}} or direct
                embedding = data.get("embedding")
                if isinstance(embedding, dict):
                    embedding = embedding.get("values")
            if not isinstance(embedding, list):
                raise RuntimeError(f"Unexpected Gemini embedding response: {str(data)[:500]}")
            return [embedding]
    else:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
        params = {"key": api_key}
        requests = []
        for t in texts:
            requests.append({
                "model": f"models/{model}",
                "content": {"parts": [{"text": t}]},
                "taskType": task_type,
                "outputDimensionality": dimension,
            })
        payload = {"requests": requests}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, params=params, json=payload, headers={"Content-Type": "application/json"})
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini embedding API error {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            # Response: {"embeddings": [{"values": [...]}, ...]}
            embeddings = data.get("embeddings")
            if not isinstance(embeddings, list):
                raise RuntimeError(f"Unexpected Gemini batch embedding response: {str(data)[:500]}")
            result: List[List[float]] = []
            for item in embeddings:
                vals = item.get("values") if isinstance(item, dict) else None
                if not isinstance(vals, list):
                    raise RuntimeError(f"Unexpected embedding item: {str(item)[:300]}")
                result.append(vals)
            return result


async def embed_text(text: str) -> Optional[List[float]]:
    if not is_configured():
        return None
    provider = get_provider()
    # Support gemini and generic (treated as gemini)
    if provider in ("gemini", "google", None):
        # Use RETRIEVAL_QUERY for single query embedding (better for search)
        # Retrieval service uses embed_text for query vector search
        embs = await _embed_gemini([text], task_type="RETRIEVAL_QUERY")
        return embs[0] if embs else None
    return None


async def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    if not is_configured():
        return None
    provider = get_provider()
    if provider in ("gemini", "google", None):
        # Use RETRIEVAL_DOCUMENT for batch document embedding
        return await _embed_gemini(texts, task_type="RETRIEVAL_DOCUMENT")
    return None


def dummy_embedding(text: str) -> List[float]:
    # Deterministic pseudo-embedding for prototype when provider not configured
    # Not used for real retrieval; retrieval falls back to keyword
    import hashlib
    import struct
    h = hashlib.sha256(text.encode()).digest()
    # Expand to DIMENSION via repeating hash
    vals = []
    for i in range(DIMENSION):
        # Use 4 bytes per float
        start = (i * 4) % len(h)
        chunk = h[start : start + 4]
        if len(chunk) < 4:
            chunk = chunk + b"\x00" * (4 - len(chunk))
        # Unpack as unsigned int and normalize to -1..1
        uint = struct.unpack("I", chunk)[0]
        vals.append((uint / 0xFFFFFFFF) * 2 - 1)
    return vals
