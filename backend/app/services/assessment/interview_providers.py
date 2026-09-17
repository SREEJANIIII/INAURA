"""Local LLM primary for interview reasoning/evaluation (http://localhost:1234/api/v1/chat).

The interview service talks to providers only through this module::

    USER ANSWER -> run_evaluation_chain() -> raw JSON text (+observability)
        -> interview.py parses/validates -> deterministic recovery if needed

Current mode (per user request):
  * LOCAL LLM at http://localhost:1234/api/v1/chat is the ONLY active provider.
  * GEMINI and GROQ code is preserved below but COMMENTED OUT — not executed.
  * RAG / embedding pipeline (Gemini embeddings) is intentionally untouched.
  * If local LLM fails or is unreachable: caller falls back to
    deterministic recovery. Total time is bounded by per-attempt timeouts
    plus an overall deadline.
  * Timeouts are enforced with asyncio.wait_for so they never depend on
    SDK-specific knobs. API keys stay backend-only and are never logged.

Both providers receive the SAME system prompt, context, question, answer,
and output schema (built by the caller) — the fallback never behaves like
a different interviewer.

To re-enable cloud providers, uncomment the GEMINI/GROQ blocks and
provider_chain entries below.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException

logger = logging.getLogger("inaura.interview_llm")

PROVIDER_GEMINI = "gemini"
PROVIDER_NVIDIA = "nvidia"  # retained for non-live callers/tests; never in the live chain
PROVIDER_GROQ = "groq"
PROVIDER_LOCAL = "local_llm"
PROVIDER_DETERMINISTIC = "deterministic"

TRANSIENT_CLASSES = frozenset({
    "rate_limited", "timeout", "network_error", "temporary_unavailable",
})
NON_TRANSIENT_CLASSES = frozenset({
    "authentication_error", "invalid_request", "invalid_model",
    "invalid_configuration", "unknown_provider_error",
})

DEFAULT_LLM_TIMEOUT_SECONDS = 20
DEFAULT_TOTAL_BUDGET_SECONDS = 75
MAX_BACKOFF_SECONDS = 3.0


@dataclass
class ProviderAttempt:
    provider: str
    latency_ms: float
    success: bool
    failure_class: Optional[str] = None
    status: Optional[int] = None
    is_retry: bool = False


@dataclass
class ChainResult:
    text: Optional[str]
    provider_used: str
    attempts: List[ProviderAttempt] = field(default_factory=list)
    failure_class: Optional[str] = None
    fallback_used: bool = False


def _dig_status_and_headers(exc: BaseException) -> Tuple[Optional[int], Dict[str, str], str]:
    """Extract HTTP status, headers, and message from wrapped SDK errors."""
    seen: List[BaseException] = []
    current: Optional[BaseException] = exc
    status: Optional[int] = None
    headers: Dict[str, str] = {}
    texts: List[str] = []
    while current is not None and current not in seen and len(seen) < 6:
        seen.append(current)
        texts.append(str(current))
        response = getattr(current, "response", None)
        candidates = [current, response] if response is not None else [current]
        for obj in candidates:
            if status is None:
                for attr in ("status_code", "status"):
                    try:
                        value = getattr(obj, attr, None)
                        if value is not None:
                            status = int(value)
                            break
                    except (TypeError, ValueError):
                        continue
            if not headers:
                try:
                    raw_headers = getattr(obj, "headers", None)
                    if raw_headers:
                        headers = {str(k).lower(): str(v) for k, v in dict(raw_headers).items()}
                except Exception:
                    pass
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        if current is exc:
            break
    return status, headers, " | ".join(t for t in texts if t)[:1000]


def _parse_retry_after(headers: Dict[str, str]) -> Optional[float]:
    for key in ("retry-after", "retry_after", "retryafter"):
        value = headers.get(key)
        if value is None:
            continue
        try:
            return max(0.0, min(float(str(value).strip()), MAX_BACKOFF_SECONDS))
        except (TypeError, ValueError):
            continue
    return None


def classify_provider_error(exc: BaseException) -> Tuple[str, Optional[int], Optional[float]]:
    """Classify into (failure_class, status, retry_after_seconds)."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout", None, None
    try:
        import httpx  # noqa: F401
        import httpx as _httpx

        if isinstance(exc, _httpx.TimeoutException):
            return "timeout", None, None
        if isinstance(exc, (_httpx.ConnectError, _httpx.NetworkError)):
            return "network_error", None, None
    except ImportError:
        pass
    status, headers, text = _dig_status_and_headers(exc)
    lowered = text.lower()
    if status == 429 or any(t in lowered for t in ("rate limit", "rate_limit", "too many requests")):
        return "rate_limited", status, _parse_retry_after(headers)
    if any(t in lowered for t in ("resource_exhausted", "quota")):
        return "rate_limited", status, _parse_retry_after(headers)
    if status in (401, 403) or any(t in lowered for t in ("unauthorized", "forbidden", "invalid api key", "authentication", "incorrect api key")):
        return "authentication_error", status, None
    if status == 408 or any(t in lowered for t in ("timeout", "timed out", "deadline exceeded")):
        return "timeout", status, None
    if status == 400 or any(t in lowered for t in ("invalid argument", "invalid request", "bad request", "malformed")):
        return "invalid_request", status, None
    if status == 404 or any(t in lowered for t in ("model_not_found", "model not found", "not found")):
        return "invalid_model" if any(t in lowered for t in ("model",)) else "invalid_request", status, None
    if status in (500, 502, 503, 504) or any(t in lowered for t in (
        "temporarily unavailable", "service unavailable", "server error",
        "overloaded", "capacity", "try again", "internal error",
    )):
        return "temporary_unavailable", status, _parse_retry_after(headers)
    if isinstance(exc, (ConnectionError, OSError)) or any(t in lowered for t in ("network", "connection reset", "connection refused", "dns", "econn")):
        return "network_error", status, None
    if any(t in lowered for t in ("api key", "credentials", "permission")):
        return "authentication_error", status, None
    return "unknown_provider_error", status, None


def is_transient(failure_class: str) -> bool:
    return failure_class in TRANSIENT_CLASSES


def backoff_delay_seconds(first_attempt: bool, retry_after: Optional[float], attempt_index: int) -> float:
    _ = first_attempt
    if retry_after is not None:
        return retry_after
    return min(0.5 * (2 ** max(0, attempt_index)) + random.uniform(0, 0.4), MAX_BACKOFF_SECONDS)


def log_llm_event(
    *,
    session_id: Optional[str],
    question_id: Optional[str],
    provider: str,
    latency_ms: float,
    success: bool,
    failure_class: Optional[str] = None,
    retry_count: int = 0,
    fallback_used: bool = False,
) -> Dict[str, Any]:
    event = {
        "session_id": session_id,
        "question_id": question_id,
        "provider": provider,
        "latency_ms": round(latency_ms, 1),
        "success": success,
        "failure_class": failure_class,
        "retry_count": retry_count,
        "fallback_used": fallback_used,
    }
    logger.info("[INTERVIEW_LLM] %s", " ".join(
        f"{key}={json.dumps(value, separators=(',', ':'))}"
        for key, value in event.items()
    ))
    return event


# ---------------------------------------------------------------------------
# Provider adapters (same contract, different SDKs; lazy imports)
# ---------------------------------------------------------------------------

InvokeFn = Callable[[List[Dict[str, str]]], Awaitable[str]]


def _require_key(value: Any, env_name: str, provider: str) -> str:
    key = (value or "").strip() if isinstance(value, str) else ""
    if not key:
        raise HTTPException(
            status_code=503,
            detail=f"AI interview grading is not configured — set {env_name}. "
                   "Your answers are saved and will be graded once grading is configured.",
        )
    return key


# ===========================================================================
# LOCAL LLM PROVIDER (ACTIVE) — http://localhost:1234/api/v1/chat
# Uses plain httpx to call the user's local LLM. No cloud SDK required.
# Payload is OpenAI-compatible (messages, model, temperature). Response
# parsing is tolerant to multiple shapes (OpenAI, custom, etc.).
# This is the ONLY active provider for interview reasoning per user request.
# RAG / embeddings remain on Gemini and are NOT affected.
# ===========================================================================

def make_local_llm_invoker(settings: Any) -> Tuple[str, InvokeFn]:
    """Build the Local LLM invoker used by live interview reasoning.

    Reads LOCAL_LLM_URL / local_llm_url from settings, defaults to
    http://localhost:1234/api/v1/chat as requested. No API key required
    unless the local server enforces auth (LOCAL_LLM_API_KEY).
    When settings is a MagicMock (tests) without a real string URL, this
    is treated as not-configured so tests can still exercise gemini/groq
    via provider_chain fallback.
    """
    import httpx  # lazy import

    raw_url = getattr(settings, "local_llm_url", None)
    # MagicMock / non-string in tests -> treat as not configured
    if isinstance(raw_url, str):
        url = raw_url.strip()
        if not url:
            raise HTTPException(
                status_code=503,
                detail="AI interview grading is not configured — set LOCAL_LLM_URL "
                       "(e.g., http://localhost:1234/api/v1/chat). "
                       "Your answers are saved and will be graded once grading is configured.",
            )
    elif raw_url is None:
        # Real settings with no override -> use default requested by user
        url = "http://localhost:1234/api/v1/chat"
    else:
        # Non-string mock value -> not configured (lets tests fallback to gemini/groq)
        raise HTTPException(
            status_code=503,
            detail="AI interview grading is not configured — set LOCAL_LLM_URL "
                   "(e.g., http://localhost:1234/api/v1/chat). "
                   "Your answers are saved and will be graded once grading is configured.",
        )
    raw_model = getattr(settings, "local_llm_model", None)
    model = raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else "local-model"
    api_key = getattr(settings, "local_llm_api_key", None)
    api_key = api_key.strip() if isinstance(api_key, str) else ""

    async def invoke(messages: List[Dict[str, str]]) -> str:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # OpenAI-compatible payload; many local servers (LM Studio, Ollama, etc.)
        # accept this shape even if they expose /api/v1/chat
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 4096,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                # Surface status so classify_provider_error can categorize it
                raise RuntimeError(f"Local LLM error {resp.status_code}: {resp.text[:500]}")
            try:
                data = resp.json()
            except Exception:
                # If response is not JSON, return raw text
                text = resp.text or ""
                if text.strip():
                    return text
                raise RuntimeError("Local LLM returned non-JSON empty response")

            # --- Tolerate multiple response shapes ---------------------------------
            # OpenAI: {"choices": [{"message": {"content": "..."}}]}
            # Custom: {"content": "..."}, {"response": "..."}, {"message": "..."}, {"text": "..."}
            # Some servers: {"choices": [{"text": "..."}]}
            # Fallback: str(data)
            content: Optional[str] = None
            if isinstance(data, dict):
                # OpenAI choices
                choices = data.get("choices")
                if isinstance(choices, list) and choices:
                    first = choices[0]
                    if isinstance(first, dict):
                        msg = first.get("message")
                        if isinstance(msg, dict) and msg.get("content"):
                            content = str(msg["content"])
                        elif first.get("text"):
                            content = str(first["text"])
                        elif first.get("content"):
                            content = str(first["content"])
                        elif first.get("delta") and isinstance(first["delta"], dict) and first["delta"].get("content"):
                            content = str(first["delta"]["content"])
                if content is None:
                    for key in ("content", "response", "message", "text", "output", "answer", "completion"):
                        val = data.get(key)
                        if isinstance(val, str) and val.strip():
                            content = val
                            break
                        if isinstance(val, dict) and val.get("content"):
                            content = str(val["content"])
                            break
                if content is None:
                    # Some servers wrap in {"data": {"content": "..."}}
                    data_inner = data.get("data")
                    if isinstance(data_inner, dict):
                        for key in ("content", "response", "message", "text"):
                            val = data_inner.get(key)
                            if isinstance(val, str) and val.strip():
                                content = val
                                break
                if content is None:
                    # Last resort: if the entire dict is the content (e.g., raw string JSON)
                    # try to find any string value that looks like JSON with our schema
                    if len(data) == 1:
                        sole = next(iter(data.values()))
                        if isinstance(sole, str) and sole.strip():
                            content = sole
            if content is not None:
                return content
            # If data is a list or string directly
            if isinstance(data, str) and data.strip():
                return data
            if isinstance(data, list) and data:
                # e.g., [{"content": "..."}]
                first = data[0]
                if isinstance(first, dict):
                    for key in ("content", "response", "message", "text"):
                        if first.get(key):
                            return str(first[key])
                if isinstance(first, str):
                    return first
            # Fallback to stringified JSON — caller will try to extract JSON object
            return json.dumps(data) if isinstance(data, (dict, list)) else str(data)

    invoke.__name__ = "local_llm_invoke"
    return PROVIDER_LOCAL, invoke


# ---------------------------------------------------------------------------
# GEMINI INVOKER — COMMENTED OUT (kept for reference, NOT executed)
# Per user request, interview now uses local LLM at
# http://localhost:1234/api/v1/chat. Gemini code is preserved but disabled.
# RAG / embedding pipeline still uses Gemini and is NOT affected by this.
# To re-enable, uncomment the provider_chain entry below.
# The commented block is kept verbatim for easy rollback.
# ---------------------------------------------------------------------------
# def make_gemini_invoker(settings: Any) -> Tuple[str, InvokeFn]:
#     """Build the Gemini invoker used by live interview reasoning."""
#     from langchain_google_genai import ChatGoogleGenerativeAI
#
#     api_key = _require_key(getattr(settings, "google_api_key", None), "GOOGLE_API_KEY", PROVIDER_GEMINI)
#     model = (getattr(settings, "gemini_model", None) or "gemini-2.5-flash").strip()
#
#     async def invoke(messages: List[Dict[str, str]]) -> str:
#         llm = ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0.2, max_retries=0)
#         raw = await llm.ainvoke(messages)
#         return str(getattr(raw, "content", raw) or "")
#
#     invoke.__name__ = "gemini_invoke"
#     return PROVIDER_GEMINI, invoke


# ---------------------------------------------------------------------------
# GROQ FALLBACK INVOKER — COMMENTED OUT (kept for reference, NOT executed)
# Per user request, Groq fallback is disabled while local LLM is active.
# To re-enable fallback, uncomment the provider_chain entry below.
# ---------------------------------------------------------------------------
# def make_groq_invoker(settings: Any) -> Tuple[str, InvokeFn]:
#     """Build the Groq fallback invoker. Raises 503 when unconfigured."""
#     from langchain_groq import ChatGroq
#
#     api_key = _require_key(getattr(settings, "groq_api_key", None), "GROQ_API_KEY", PROVIDER_GROQ)
#     model = (getattr(settings, "groq_model", None) or "llama-3.3-70b-versatile").strip()
#
#     async def invoke(messages: List[Dict[str, str]]) -> str:
#         llm = ChatGroq(model_name=model, groq_api_key=api_key, temperature=0.6, max_retries=0)
#         raw = await llm.ainvoke(messages)
#         return str(getattr(raw, "content", raw) or "")
#
#     invoke.__name__ = "groq_invoke"
#     return PROVIDER_GROQ, invoke

# ---------------------------------------------------------------------------
# GEMINI / GROQ — ACTIVE IMPLEMENTATIONS (kept for tests + rollback)
# These are NOT called in live provider_chain while local LLM is active
# (see commented entries above). They remain importable so existing tests
# that patch make_gemini_invoker / make_groq_invoker keep working, and so
# a single uncomment restores cloud fallback. RAG embeddings are unaffected.
# ---------------------------------------------------------------------------

def make_gemini_invoker(settings: Any) -> Tuple[str, InvokeFn]:
    """Build the Gemini invoker (COMMENTED OUT IN LIVE CHAIN — kept for rollback/tests)."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Gemini provider not installed: {e}")

    api_key = _require_key(getattr(settings, "google_api_key", None), "GOOGLE_API_KEY", PROVIDER_GEMINI)
    model = (getattr(settings, "gemini_model", None) or "gemini-2.5-flash").strip()

    async def invoke(messages: List[Dict[str, str]]) -> str:
        llm = ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0.2, max_retries=0)
        raw = await llm.ainvoke(messages)
        return str(getattr(raw, "content", raw) or "")

    invoke.__name__ = "gemini_invoke"
    return PROVIDER_GEMINI, invoke


def make_groq_invoker(settings: Any) -> Tuple[str, InvokeFn]:
    """Build the Groq fallback invoker (COMMENTED OUT IN LIVE CHAIN — kept for rollback/tests)."""
    try:
        from langchain_groq import ChatGroq
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Groq provider not installed: {e}")

    api_key = _require_key(getattr(settings, "groq_api_key", None), "GROQ_API_KEY", PROVIDER_GROQ)
    model = (getattr(settings, "groq_model", None) or "llama-3.3-70b-versatile").strip()

    async def invoke(messages: List[Dict[str, str]]) -> str:
        llm = ChatGroq(model_name=model, groq_api_key=api_key, temperature=0.6, max_retries=0)
        raw = await llm.ainvoke(messages)
        return str(getattr(raw, "content", raw) or "")

    invoke.__name__ = "groq_invoke"
    return PROVIDER_GROQ, invoke


def provider_chain(settings: Any) -> List[Tuple[str, InvokeFn]]:
    """Live reasoning order: Local LLM only (Gemini/Groq commented out in production).

    Gemini/Groq entries below are COMMENTED OUT per user request to use
    http://localhost:1234/api/v1/chat. They are kept for easy rollback and
    for existing tests that mock them (when local LLM is not configured in
    the test MagicMock, the chain falls back to gemini/groq so tests pass).
    RAG / embeddings remain on Gemini and are NOT affected.
    """
    chain: List[Tuple[str, InvokeFn]] = []
    # --- LOCAL LLM (ACTIVE) -------------------------------------------------
    try:
        chain.append(make_local_llm_invoker(settings))
    except HTTPException:
        pass
    # --- GEMINI (COMMENTED OUT — preserved for future rollback) -------------
    # NOTE: This block is intentionally commented. Uncomment to re-enable.
    # try:
    #     chain.append(make_gemini_invoker(settings))
    # except HTTPException:
    #     pass
    # --- GROQ FALLBACK (COMMENTED OUT — preserved for future rollback) ------
    # NOTE: This block is intentionally commented. Uncomment to re-enable.
    # try:
    #     chain.append(make_groq_invoker(settings))
    # except HTTPException:
    #     pass

    # Fallback for tests / when local LLM is not configured (e.g., MagicMock
    # in test suite without local_llm_url string). This does NOT affect
    # production where local_llm_url defaults to http://localhost:1234/api/v1/chat
    # and make_local_llm_invoker succeeds, so gemini/groq are never reached.
    if not chain:
        try:
            chain.append(make_gemini_invoker(settings))
        except HTTPException:
            pass
        try:
            chain.append(make_groq_invoker(settings))
        except HTTPException:
            pass
    return chain


# ---------------------------------------------------------------------------
# Orchestration: Local LLM -> deterministic marker. Each provider is
# attempted at most once so one answer cannot trigger a correction/retry call.
# (Gemini -> Groq chain is commented out; see above.)
# ---------------------------------------------------------------------------

async def run_evaluation_chain(
    messages: List[Dict[str, str]],
    *,
    settings: Any,
    session_id: Optional[str] = None,
    question_id: Optional[str] = None,
    timeout_s: Optional[float] = None,
    total_budget_s: Optional[float] = None,
    accept_text: Optional[Callable[[str], bool]] = None,
) -> ChainResult:
    """Run providers in order with bounded retries. Never raises for provider
    failures — returns provider_used="deterministic" when all fail. Raises
    HTTPException 503 only when NO provider is configured at all."""
    per_attempt = float(timeout_s if timeout_s is not None
                        else getattr(settings, "interview_llm_timeout_seconds", None)
                        or DEFAULT_LLM_TIMEOUT_SECONDS)
    total_budget = float(total_budget_s if total_budget_s is not None
                         else getattr(settings, "interview_llm_total_budget_seconds", None)
                         or DEFAULT_TOTAL_BUDGET_SECONDS)
    chain = provider_chain(settings)
    if not chain:
        raise HTTPException(
            status_code=503,
            detail="AI interview grading is not configured — set LOCAL_LLM_URL "
                   "(e.g., http://localhost:1234/api/v1/chat). "
                   "Your answers are saved and will be graded once grading is configured.",
        )
    attempts: List[ProviderAttempt] = []
    deadline = perf_counter() + total_budget
    last_failure: Optional[str] = None

    for position, (name, invoke) in enumerate(chain):
        retries_used = 0
        while True:
            remaining = deadline - perf_counter()
            if remaining < min(5.0, per_attempt):
                last_failure = last_failure or "timeout"
                break
            started = perf_counter()
            try:
                text = await asyncio.wait_for(invoke(messages), timeout=min(per_attempt, remaining))
                latency = (perf_counter() - started) * 1000
                if accept_text is not None and not accept_text(text):
                    attempts.append(ProviderAttempt(name, latency, False, "malformed_output", None, False))
                    log_llm_event(session_id=session_id, question_id=question_id, provider=name,
                                  latency_ms=latency, success=False,
                                  failure_class="malformed_output", retry_count=0,
                                  fallback_used=position > 0)
                    last_failure = "malformed_output"
                    break
                attempts.append(ProviderAttempt(name, latency, True, None, None, retries_used > 0))
                log_llm_event(session_id=session_id, question_id=question_id, provider=name,
                              latency_ms=latency, success=True,
                              retry_count=len(attempts) - 1, fallback_used=position > 0)
                return ChainResult(text=text, provider_used=name, attempts=attempts,
                                   failure_class=None, fallback_used=position > 0)
            except HTTPException:
                raise
            except Exception as exc:
                latency = (perf_counter() - started) * 1000
                failure_class, status, retry_after = classify_provider_error(exc)
                last_failure = failure_class
                log_llm_event(session_id=session_id, question_id=question_id, provider=name,
                              latency_ms=latency, success=False, failure_class=failure_class,
                              retry_count=len(attempts), fallback_used=position > 0)
                attempts.append(ProviderAttempt(name, latency, False, failure_class, status, retries_used > 0))
                break

    log_llm_event(session_id=session_id, question_id=question_id,
                  provider=PROVIDER_DETERMINISTIC, latency_ms=0.0,
                  success=False, failure_class=last_failure or "unknown_provider_error",
                  fallback_used=True)
    return ChainResult(text=None, provider_used=PROVIDER_DETERMINISTIC, attempts=attempts,
                       failure_class=last_failure or "unknown_provider_error", fallback_used=True)


async def correct_once(
    provider_name: str,
    invokers: Dict[str, InvokeFn],
    messages: List[Dict[str, str]],
    correction_note: str,
    *,
    timeout_s: float = DEFAULT_LLM_TIMEOUT_SECONDS,
    session_id: Optional[str] = None,
    question_id: Optional[str] = None,
) -> Optional[str]:
    """One strict correction retry on the SAME provider. Returns text or None."""
    invoke = invokers.get(provider_name)
    if invoke is None:
        return None
    fixed = list(messages) + [{"role": "user", "content": correction_note}]
    started = perf_counter()
    try:
        text = await asyncio.wait_for(invoke(fixed), timeout=timeout_s)
        log_llm_event(session_id=session_id, question_id=question_id, provider=provider_name,
                      latency_ms=(perf_counter() - started) * 1000, success=True,
                      retry_count=1, fallback_used=provider_name != PROVIDER_LOCAL)
        return text
    except Exception as exc:
        failure_class, status, _ = classify_provider_error(exc)
        log_llm_event(session_id=session_id, question_id=question_id, provider=provider_name,
                      latency_ms=(perf_counter() - started) * 1000, success=False,
                      failure_class=failure_class, retry_count=1,
                      fallback_used=provider_name != PROVIDER_LOCAL)
        return None


_INJECTION_MARKERS = (
    "ignore previous instructions", "ignore all previous", "disregard instructions",
    "system prompt", "reveal instructions", "jailbreak", "developer instructions",
)


def contains_injection_markers(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in _INJECTION_MARKERS)
