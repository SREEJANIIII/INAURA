"""Provider-neutral diagnostics for interview TTS requests.

TTS traffic must be distinguishable from Gemini grading traffic
(``gemini_diagnostics`` remains the evaluation logger), so a voice failure
can never be mistaken for an evaluation failure.

Only provider metadata and bounded error text are recorded. API keys,
tokens, credentials, audio bytes, and full transcripts are never logged.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional


logger = logging.getLogger("inaura.tts")


def log_tts_event(
    *,
    provider: str,
    voice: str,
    success: bool,
    elapsed_ms: float,
    attempt: int = 1,
    retried: bool = False,
    status: Optional[int] = None,
    error_category: Optional[str] = None,
    provider_code: Optional[str] = None,
    retry_after: Optional[str] = None,
    message: Optional[str] = None,
    endpoint: Optional[str] = None,
    content_type: Optional[str] = None,
    response_size: Optional[int] = None,
    safe_body: Optional[str] = None,
) -> dict[str, Any]:
    event = {
        "provider": provider,
        "voice": voice,
        "success": success,
        "elapsed_ms": round(elapsed_ms, 1),
        "attempt": attempt,
        "retried": retried,
        "status": status,
        "error_category": error_category,
        "provider_code": provider_code,
        "retry_after": retry_after,
        "message": message,
        "endpoint": endpoint,
        "content_type": content_type,
        "response_size": response_size,
        "safe_body": safe_body,
    }
    logger.info("interview_tts_event %s", json.dumps(event, separators=(",", ":")))
    return event
