from typing import List, Optional
import httpx
from ..core.config import get_settings

# Embedding abstraction — Phase 4B
# Supports: openai (text-embedding-3-small), fallback none
# If not configured, app still starts; retrieval falls back to keyword

DIMENSION = 1536  # text-embedding-3-small


def is_configured() -> bool:
    s = get_settings()
    return bool(s.embedding_provider and s.embedding_api_key)


def get_provider() -> Optional[str]:
    s = get_settings()
    return s.embedding_provider


async def _embed_openai(texts: List[str]) -> List[List[float]]:
    s = get_settings()
    if not s.embedding_api_key:
        raise RuntimeError("EMBEDDING_API_KEY not configured")
    model = s.embedding_model or "text-embedding-3-small"
    # OpenAI embeddings API
    # Use httpx async
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {s.embedding_api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "input": texts},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Embedding API error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        # data['data'] is list of {embedding: [...], index: ...}
        embeddings = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
        return embeddings


async def embed_text(text: str) -> Optional[List[float]]:
    if not is_configured():
        return None
    provider = get_provider()
    if provider == "openai":
        embs = await _embed_openai([text])
        return embs[0] if embs else None
    # Future providers: e.g., cohere, local
    return None


async def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    if not is_configured():
        return None
    provider = get_provider()
    if provider == "openai":
        return await _embed_openai(texts)
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
