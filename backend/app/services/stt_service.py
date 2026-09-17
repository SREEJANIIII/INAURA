"""Speech-to-text boundary for interview audio.

STT is intentionally separate from interview reasoning. Groq Whisper is an
optional transcription provider; browser SpeechRecognition remains the safe
fallback when the provider is unavailable.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import HTTPException

from ..core.config import get_settings


TECHNICAL_TERMS = (
    (r"\bfast\s*api\b", "FastAPI"),
    (r"\bpost\s*gres(?:ql)?\b", "PostgreSQL"),
    (r"\bpg\s*vector\b", "pgvector"),
    (r"\bsupabase\b", "Supabase"),
    (r"\bgithub\b|\bgit\s*hub\b", "GitHub"),
    (r"\bgit\b", "Git"),
    (r"\btype\s*script\b", "TypeScript"),
    (r"\bjava\s*script\b", "JavaScript"),
    (r"\bnode\s*\.??\s*js\b", "Node.js"),
    (r"\bspring\s*boot\b", "Spring Boot"),
    (r"\bmongo\s*db\b", "MongoDB"),
    (r"\brest\s*api\b", "REST API"),
    (r"\bci\s*/?\s*cd\b", "CI/CD"),
    (r"\bo\s*auth\b", "OAuth"),
    (r"\bj\s*w\s*t\b", "JWT"),
    (r"\breact\b", "React"),
    (r"\bpython\b", "Python"),
    (r"\bjava\b", "Java"),
    (r"\bsql\b", "SQL"),
    (r"\brag\b", "RAG"),
    (r"\blang\s*chain\b", "LangChain"),
    (r"\bgemini\b", "Gemini"),
    (r"\bgroq\b", "Groq"),
    (r"\bnvidia\b", "NVIDIA"),
    (r"\bdocker\b", "Docker"),
    (r"\bkubernetes\b|\bk\s*8\s*s\b", "Kubernetes"),
    (r"\bredis\b", "Redis"),
)


def normalize_technical_transcript(text: str) -> str:
    """Correct only high-confidence technical variants."""
    normalized = str(text or "")
    for pattern, replacement in TECHNICAL_TERMS:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", normalized).strip()


async def transcribe(audio: bytes, filename: str = "answer.webm", content_type: str = "audio/webm") -> dict[str, Any]:
    settings = get_settings()
    key = (settings.groq_api_key or "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="STT provider is not configured")
    if not audio or len(audio) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Audio payload is empty or too large")

    model = (getattr(settings, "groq_stt_model", None) or "whisper-large-v3-turbo").strip()
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                files={"file": (filename, audio, content_type)},
                data={"model": model, "language": "en", "response_format": "json"},
            )
        response.raise_for_status()
        data = response.json()
        raw = str(data.get("text") or "").strip()
        if not raw:
            raise HTTPException(status_code=502, detail="STT provider returned an empty transcript")
        return {"text": normalize_technical_transcript(raw), "provider": "groq", "model": model}
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="STT provider timed out") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        category = "rate_limited" if status == 429 else "provider_error"
        raise HTTPException(status_code=503 if status >= 500 else status, detail={
            "message": "STT provider request failed", "category": category, "status": status,
        }) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="STT provider unavailable") from exc
