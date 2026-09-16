"""Safe diagnostics for Gemini-backed interview requests.

This module deliberately records only provider metadata and bounded error text.
Secrets, authorization headers, prompts, transcripts, and response bodies are
never logged.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional


logger = logging.getLogger("inaura.gemini")


def _safe_message(value: Any) -> str:
    text = re.sub(r"(?i)(api[_-]?key|authorization|token)=?[^\s,;&]+", r"\1=<redacted>", str(value or ""))
    text = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "<redacted-key>", text)
    return re.sub(r"\s+", " ", text)[:240]


def _status_from(error: BaseException) -> Optional[int]:
    for obj in (error, getattr(error, "response", None)):
        value = getattr(obj, "status_code", None) or getattr(obj, "status", None)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def classify_error(error: BaseException, status: Optional[int] = None) -> str:
    """Map provider/network failures to a stable, non-sensitive category."""
    code = status or _status_from(error)
    text = str(error).lower()
    if code == 429 or any(token in text for token in ("resource_exhausted", "rate limit", "quota")):
        return "quota_exhausted" if "quota" in text or "resource_exhausted" in text else "rate_limited"
    if code in (401, 403) or any(token in text for token in ("unauthorized", "forbidden", "api key", "permission")):
        return "authentication_error"
    if code == 408 or any(token in text for token in ("timeout", "timed out")):
        return "timeout"
    if code in (400, 422) or any(token in text for token in ("invalid argument", "invalid request", "malformed")):
        return "invalid_request"
    if code in (500, 502, 503, 504) or any(token in text for token in ("temporarily unavailable", "service unavailable")):
        return "temporary_unavailable"
    if isinstance(error, (ConnectionError, OSError)) or any(token in text for token in ("network", "connection reset", "dns")):
        return "network_error"
    return "unknown_provider_error"


def provider_details(error: BaseException, status: Optional[int] = None) -> dict[str, Any]:
    """Extract safe, bounded provider metadata without logging secrets."""
    response = getattr(error, "response", None)
    payload: Any = getattr(error, "body", None)
    if payload is None and response is not None:
        try:
            payload = getattr(response, "json", lambda: None)()
        except Exception:
            payload = None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            payload = None
    detail = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(detail, dict):
        detail = payload if isinstance(payload, dict) else {}
    retry_after = None
    headers = getattr(response, "headers", None) or getattr(error, "headers", None) or {}
    for key in ("retry-after", "Retry-After"):
        if headers.get(key) is not None:
            retry_after = str(headers[key])[:80]
            break
    return {
        "status": status or _status_from(error),
        "provider_code": str(detail.get("status") or detail.get("code") or "")[:80] or None,
        "provider_category": str(detail.get("reason") or detail.get("type") or "")[:80] or None,
        "retry_after": retry_after,
        "message": _safe_message(detail.get("message") or str(error)),
    }


def log_gemini_event(*, request_type: str, model: str, success: bool, elapsed_ms: float,
                     error: Optional[BaseException] = None, session_id: Optional[str] = None,
                     question_id: Optional[str] = None) -> dict[str, Any]:
    details = provider_details(error) if error else {"status": None, "provider_code": None, "provider_category": None, "retry_after": None, "message": None}
    event = {
        "request_type": request_type,
        "model": model,
        "success": success,
        "elapsed_ms": round(elapsed_ms, 1),
        "session_id": session_id,
        "question_id": question_id,
        "error_category": classify_error(error) if error else None,
        **details,
    }
    logger.info("gemini_interview_event %s", json.dumps(event, separators=(",", ":")))
    return event
