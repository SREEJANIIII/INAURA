"""Gemini-first providers for interview reasoning/evaluation.

The interview service talks to providers only through this module::

    USER ANSWER -> run_evaluation_chain() -> raw JSON text (+observability)
        -> interview.py parses/validates -> deterministic recovery if needed

Current mode:
    * Gemini is the primary active provider for interview reasoning.
    * Groq is the existing reasoning fallback, then deterministic recovery.
  * RAG / embedding pipeline (Gemini embeddings) is intentionally untouched.
  * NVIDIA remains TTS-only and Groq Whisper remains STT-only outside this
    reasoning fallback.
  * If Gemini and Groq fail or are unreachable: caller falls back to
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
PROVIDER_LOCAL = "local_llm"  # retained for compatibility with older diagnostics
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
    model: Optional[str] = None,
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
        "model": model,
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
# LOCAL LLM PROVIDER (ACTIVE) — http://localhost:1234/v1/chat/completions (ling-3.0-tiny)
# Legacy http://localhost:1234/api/v1/chat also supported (auto-adapts).
# Uses plain httpx. Payload adapts messages->input for LM Studio Responses API
# (error "'input' is required" + invalid_union) and tolerates both shapes.
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
    model = raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else "ling-3.0-tiny"
    api_key = getattr(settings, "local_llm_api_key", None)
    api_key = api_key.strip() if isinstance(api_key, str) else ""

    def _needs_input_retry(text: str) -> bool:
        lowered = (text or "").lower()
        return ("'input' is required" in lowered or '"input" is required' in lowered
                or "invalid_union" in lowered and "input" in lowered)

    def _extract_content(data: Any) -> Optional[str]:
        """Extract assistant text from chat/completions OR responses API."""
        if isinstance(data, dict):
            # --- Responses API: {"output": [{"content":[{"type":"output_text","text":"..."}]}]} ---
            # Also: {"output_text": "..."} direct field
            if isinstance(data.get("output_text"), str) and data["output_text"].strip():
                return str(data["output_text"])
            output = data.get("output")
            if isinstance(output, list) and output:
                for item in output:
                    if isinstance(item, dict):
                        # Case: {"type":"message","content":[{"type":"output_text","text":"..."}]}
                        cont = item.get("content")
                        if isinstance(cont, list):
                            for c in cont:
                                if isinstance(c, dict) and c.get("text"):
                                    # output_text or text
                                    txt = c.get("text") or c.get("output_text") or ""
                                    if isinstance(txt, str) and txt.strip():
                                        return txt
                                if isinstance(c, str) and c.strip():
                                    return c
                        if isinstance(item.get("text"), str) and item["text"].strip():
                            return str(item["text"])
                        # Some servers: {"output": "raw string"}
                        if isinstance(item, str) and item.strip():
                            return item
            # Also handle {"response": {"output_text": "..."}}
            resp_field = data.get("response")
            if isinstance(resp_field, dict):
                maybe = _extract_content(resp_field)
                if maybe:
                    return maybe
            # --- Chat Completions: {"choices": [{"message": {"content": "..."}}]} ---
            # ling-3.0-tiny returns reasoning in reasoning_content + final JSON in content; fallback accordingly
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    msg = first.get("message")
                    if isinstance(msg, dict):
                        c = msg.get("content")
                        rc = msg.get("reasoning_content") or msg.get("reasoning") or msg.get("reasoning_text")
                        # Prefer content if it looks like JSON, else fallback to reasoning_content that contains JSON
                        if isinstance(c, str) and c.strip():
                            if "{" in c and "}" in c:
                                return str(c)
                            # content exists but no JSON — check reasoning for JSON
                            if isinstance(rc, str) and rc.strip() and "{" in rc and "technical_correctness" in rc:
                                return str(rc)
                            return str(c)
                        if isinstance(rc, str) and rc.strip():
                            return str(rc)
                    if first.get("text"):
                        return str(first["text"])
                    if first.get("content"):
                        return str(first["content"])
                    if first.get("delta") and isinstance(first["delta"], dict) and first["delta"].get("content"):
                        return str(first["delta"]["content"])
            for key in ("content", "response", "message", "text", "answer", "completion"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val
                if isinstance(val, dict) and val.get("content"):
                    maybe = str(val["content"])
                    if maybe.strip():
                        return maybe
                # handle {"output": "string"} single
                if key == "output" and isinstance(val, str) and val.strip():
                    return val
            # Some servers wrap in {"data": {"content": "..."}}
            data_inner = data.get("data")
            if isinstance(data_inner, dict):
                for key in ("content", "response", "message", "text"):
                    val = data_inner.get(key)
                    if isinstance(val, str) and val.strip():
                        return val
            if len(data) == 1:
                sole = next(iter(data.values()))
                if isinstance(sole, str) and sole.strip():
                    return sole
        if isinstance(data, str) and data.strip():
            return data
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                for key in ("content", "response", "message", "text"):
                    if first.get(key):
                        return str(first[key])
            if isinstance(first, str):
                return first
        return None

    def _candidate_urls(primary: str) -> List[str]:
        urls: List[str] = []
        seen = set()
        for cand in [primary,
                     primary.replace("/api/v1/chat", "/v1/chat/completions"),
                     primary.replace("/api/v1/chat", "/v1/responses"),
                     "http://localhost:1234/v1/chat/completions",
                     "http://localhost:1234/v1/responses"]:
            if cand and cand not in seen:
                seen.add(cand)
                urls.append(cand)
        return urls

    async def invoke(messages: List[Dict[str, str]]) -> str:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Payload variants
        payload_messages = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 4096,
            "stream": False,
        }
        # For Responses API (/v1/responses or /api/v1/chat) LM Studio expects "input"
        # Convert messages to a single string (system + user) and also as array form
        input_as_string = "\n\n".join(f"{m.get('role','user')}: {m.get('content','')}" for m in messages)
        payload_input_string = {
            "model": model,
            "input": input_as_string,
            "temperature": 0.2,
            "max_tokens": 4096,
            "stream": False,
        }
        payload_input_array = {
            "model": model,
            "input": messages,
            "temperature": 0.2,
            "stream": False,
        }

        last_exc: Optional[Exception] = None
        for attempt_url in _candidate_urls(url):
            for payload in (payload_messages, payload_input_string, payload_input_array):
                try:
                    async with httpx.AsyncClient(timeout=30) as client:
                        resp = await client.post(attempt_url, json=payload, headers=headers)
                    if resp.status_code != 200:
                        body = resp.text or ""
                        # If server says 'input' is required, immediately try input payload on same URL
                        if resp.status_code == 400 and _needs_input_retry(body) and payload is payload_messages:
                            # retry with input payload on same URL — continue to next payload
                            last_exc = RuntimeError(f"Local LLM error {resp.status_code}: {body[:500]}")
                            # Also try alternative URL with messages in next outer loop
                            if attempt_url == url:
                                logger.warning("local_llm: %s expects 'input', retrying with input payload at %s", model, attempt_url)
                            continue
                        # 404 -> try next URL (wrong path)
                        if resp.status_code == 404 and attempt_url == url:
                            last_exc = RuntimeError(f"Local LLM error 404 at {attempt_url}: {body[:300]}")
                            break  # break payload loop, go to next URL
                        raise RuntimeError(f"Local LLM error {resp.status_code}: {body[:500]}")
                    try:
                        data = resp.json()
                    except Exception:
                        text = resp.text or ""
                        if text.strip():
                            return text
                        raise RuntimeError("Local LLM returned non-JSON empty response")
                    content = _extract_content(data)
                    if content is not None:
                        if attempt_url != url:
                            logger.info("local_llm: succeeded via fallback URL %s (primary %s failed)", attempt_url, url)
                        return content
                    # Fallback to stringified JSON — caller will try to extract JSON object
                    return json.dumps(data) if isinstance(data, (dict, list)) else str(data)
                except RuntimeError as e:
                    last_exc = e
                    # If input-required error, keep trying input variants
                    if _needs_input_retry(str(e)):
                        continue
                    # For other 400/404, try next payload/URL
                    if "404" in str(e) or "input" in str(e).lower():
                        break
                    raise
                except Exception as e:
                    last_exc = e
                    raise
            # if we got 404, continue to next URL
            if last_exc and "404" in str(last_exc):
                continue
            # if last error was input-required and we exhausted payloads, try next URL
            if last_exc and _needs_input_retry(str(last_exc)):
                continue
            if last_exc is None:
                continue
        # Exhausted all candidates
        if last_exc:
            raise last_exc
        raise RuntimeError("Local LLM: all endpoint/payload variants failed")

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
# GEMINI / GROQ — ACTIVE IMPLEMENTATIONS
# Gemini is called first by provider_chain; Groq is called only as its fallback.
# RAG embeddings are unaffected.
# ---------------------------------------------------------------------------

def make_gemini_invoker(settings: Any) -> Tuple[str, InvokeFn]:
    """Build the Gemini invoker used first by live interview reasoning."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Gemini provider not installed: {e}")

    api_key = _require_key(getattr(settings, "google_api_key", None), "GOOGLE_API_KEY", PROVIDER_GEMINI)
    raw_model = (getattr(settings, "gemini_model", None) or "gemini-2.5-flash").strip()
    if raw_model in ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.0-pro"):
        model = "gemini-2.5-flash"
    else:
        model = raw_model

    async def invoke(messages: List[Dict[str, str]]) -> str:
        llm = ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0.2, max_retries=0)
        raw = await llm.ainvoke(messages)
        return str(getattr(raw, "content", raw) or "")

    invoke.__name__ = "gemini_invoke"
    return PROVIDER_GEMINI, invoke


def make_groq_invoker(settings: Any) -> Tuple[str, InvokeFn]:
    """Build the Groq reasoning fallback invoker."""
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


PROVIDER_OPENROUTER = "openrouter"


def make_nvidia_invoker(settings: Any) -> Tuple[str, InvokeFn]:
    """Build the server-side NVIDIA NIM interview invoker."""
    try:
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"NVIDIA provider not installed: {e}")

    api_key = _require_key(getattr(settings, "nvidia_api_key", None), "NVIDIA_API_KEY", PROVIDER_NVIDIA)
    model = (getattr(settings, "nvidia_model", None) or "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning").strip()

    async def invoke(messages: List[Dict[str, str]]) -> str:
        llm = ChatNVIDIA(
            model=model,
            api_key=api_key,
            temperature=0.2,
            max_completion_tokens=4096,
        )
        raw = await llm.ainvoke(messages)
        return str(getattr(raw, "content", raw) or "")

    invoke.__name__ = "nvidia_invoke"
    return PROVIDER_NVIDIA, invoke


def make_openrouter_invoker(settings: Any) -> Tuple[str, InvokeFn]:
    """Build one OpenRouter request with server-side ordered model fallback."""
    import httpx

    api_key = _require_key(
        getattr(settings, "openrouter_api_key", None),
        "OPENROUTER_API_KEY", PROVIDER_OPENROUTER,
    )
    primary = (getattr(settings, "openrouter_primary_model", None)
               or "deepseek/deepseek-v3.2").strip()
    raw_fallbacks = getattr(settings, "openrouter_fallback_models", "") or ""
    fallbacks = [model.strip() for model in str(raw_fallbacks).split(",") if model.strip()]
    fallbacks = [model for model in fallbacks if model != primary]

    async def invoke(messages: List[Dict[str, str]]) -> str:
        payload = {
            "model": primary,
            "models": fallbacks,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 4096,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        if response.status_code != 200:
            raise RuntimeError(f"OpenRouter error {response.status_code}: {response.text[:500]}")
        data = response.json()
        invoke.last_model = str(data.get("model") or primary) if isinstance(data, dict) else primary
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenRouter returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenRouter returned empty content")
        return content

    invoke.__name__ = "openrouter_invoke"
    invoke.last_model = primary
    invoke.fallback_models = tuple(fallbacks)
    return PROVIDER_OPENROUTER, invoke


def provider_chain(settings: Any) -> List[Tuple[str, InvokeFn]]:
    """Live reasoning order: Gemini, Groq fallback, deterministic recovery."""
    chain: List[Tuple[str, InvokeFn]] = []
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
# Orchestration: Gemini -> Groq -> deterministic marker. Each provider is
# attempted at most once so one answer cannot trigger a correction/retry call.
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
                 detail="AI interview grading is not configured — set NVIDIA_API_KEY "
                     "and configure NVIDIA_MODEL. "
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
                                  model=getattr(invoke, "last_model", None),
                                  latency_ms=latency, success=False,
                                  failure_class="malformed_output", retry_count=0,
                                  fallback_used=position > 0)
                    last_failure = "malformed_output"
                    break
                attempts.append(ProviderAttempt(name, latency, True, None, None, retries_used > 0))
                log_llm_event(session_id=session_id, question_id=question_id, provider=name,
                              model=getattr(invoke, "last_model", None),
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
                              model=getattr(invoke, "last_model", None),
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
