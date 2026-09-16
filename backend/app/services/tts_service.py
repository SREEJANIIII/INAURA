"""NVIDIA-hosted interview TTS (voice only — never reasoning).

Architecture::

    Gemini next-question text -> TTSService.generate(text) -> NVIDIA TTS API
        -> audio bytes -> /interview/tts -> browser Audio playback

Responsibility split (non-negotiable):
  * Gemini (``gemini-2.5-flash``) does ANSWER -> ANALYSIS -> FOLLOW-UP
    DECISION -> NEXT QUESTION. This module never evaluates, never generates
    questions, and is only called AFTER the next question already exists.
  * NVIDIA does TEXT -> SPEECH and nothing else.

Provider: NVIDIA API catalog TTS (default ``magpie-tts-multilingual``,
voice ``Magpie-Multilingual.EN-US.Aria``) invoked over HTTP with a
backend-only ``NVIDIA_API_KEY``. Endpoint, model, voice, and function id
are configurable because NVIDIA versions catalog functions over time —
see the function's API schema on build.nvidia.com if the catalog changes.

Retry policy (voice is an enhancement — never amplify):
  * 429 / rate limit ............ fail fast, never retried
  * 401 / 403 (auth/config) ..... fail fast, never retried
  * invalid request / malformed .. fail fast, never retried
  * 5xx transient / timeout ..... exactly ONE controlled retry
"""

import asyncio
import base64
import hashlib
import logging
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from ..core.config import get_settings
from .tts_diagnostics import log_tts_event

logger = logging.getLogger("inaura.tts")

TTS_TIMEOUT_SECONDS_DEFAULT = 30
TTS_MAX_CHARS = 4000
TTS_MAX_ATTEMPTS = 2  # initial attempt + exactly one controlled retry
TTS_RETRY_DELAY_SECONDS = 0.5
MIN_AUDIO_BYTES = 44
MAX_AUDIO_BYTES = 10 * 1024 * 1024

# Only transient provider/network failures qualify for the single retry.
RETRYABLE_CATEGORIES = frozenset({"temporary_unavailable", "timeout", "network_error"})

# NVIDIA Magpie TTS HTTP API (current official transport): multipart audio
# synthesis on the function's invocation endpoint. The TTS function id below
# is the catalog id for magpie-tts-multilingual; override via env when it
# changes. Voice/language come from settings; encoding and sample rate follow
# the documented Magpie HTTP fields.
DEFAULT_FUNCTION_ID = "877104f7-e885-42b9-8de8-f6e4c6303969"
DEFAULT_MODEL = "magpie-tts-multilingual"
DEFAULT_VOICE = "Magpie-Multilingual.EN-US.Aria"
DEFAULT_LANGUAGE = "en-US"
TTS_ENCODING = "LINEAR_PCM"
TTS_SAMPLE_RATE_HZ = 44100


def default_invocation_url(function_id: str) -> str:
    return f"https://{function_id}.invocation.api.nvcf.nvidia.com/v1/audio/synthesize"


@dataclass
class TTSResult:
    audio: bytes
    media_type: str
    provider: str
    voice: str


def is_valid_wav(data: bytes) -> bool:
    if not isinstance(data, bytes):
        return False
    if len(data) < MIN_AUDIO_BYTES or len(data) > MAX_AUDIO_BYTES:
        return False
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return False
    if data[12:16] != b"fmt " or data[36:40] != b"data":
        return False
    declared = int.from_bytes(data[40:44], "little")
    return declared == len(data) - MIN_AUDIO_BYTES


def is_valid_mp3(data: bytes) -> bool:
    if not isinstance(data, bytes):
        return False
    if len(data) < MIN_AUDIO_BYTES or len(data) > MAX_AUDIO_BYTES:
        return False
    if data[:3] == b"ID3":
        return True
    return len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def sniff_media_type(data: bytes) -> Optional[str]:
    if is_valid_wav(data):
        return "audio/wav"
    if is_valid_mp3(data):
        return "audio/mpeg"
    return None


def _status_from(error: BaseException) -> Optional[int]:
    for obj in (error, getattr(error, "response", None)):
        value = getattr(obj, "status_code", None) or getattr(obj, "status", None)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def classify_tts_error(error: BaseException) -> str:
    """Map provider/network failures to a stable category (fail-fast first).

    httpx transport errors are distinguished explicitly so they never
    collapse into ``unknown_provider_error``.
    """
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    if isinstance(error, (httpx.ConnectError, httpx.NetworkError)):
        return "network_error"
    code = _status_from(error)
    text = str(error).lower()
    if code == 429 or any(t in text for t in ("rate limit", "rate_limit", "too many requests")):
        return "rate_limited"
    if any(t in text for t in ("resource_exhausted", "quota")):
        return "quota_exhausted"
    if code in (401, 403) or any(t in text for t in ("unauthorized", "forbidden", "invalid api key", "authentication")):
        return "authentication_error"
    if code == 408 or any(t in text for t in ("timeout", "timed out")):
        return "timeout"
    if code in (400, 404, 422) or any(t in text for t in ("invalid argument", "invalid request", "malformed", "bad request", "not found")):
        return "invalid_request"
    if code in (500, 502, 503, 504) or any(t in text for t in ("temporarily unavailable", "service unavailable", "server error")):
        return "temporary_unavailable"
    if isinstance(error, (ConnectionError, OSError)) or any(t in text for t in ("network", "connection reset", "dns")):
        return "network_error"
    return "unknown_provider_error"


def _scrub_secrets(text: str) -> str:
    """Redact credential-shaped material; bound the length."""
    out = re.sub(r"nvapi-[A-Za-z0-9_\-]+", "<redacted-nvidia-key>", text or "")
    out = re.sub(r"(?i)bearer\s+[A-Za-z0-9_\-\.~+/=]+", "Bearer <redacted>", out)
    out = re.sub(r"(?i)(api[_-]?key|authorization|token)\s*[:=]\s*[^\s,;\"}]+", r"\1=<redacted>", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:500]


def _endpoint_label(url: str) -> str:
    """Hostname + path only — never query strings or credentials."""
    try:
        parts = urlsplit(url or "")
        host = parts.hostname or ""
        return f"{host}{parts.path or ''}"[:160]
    except Exception:
        return ""


def _provider_response_envelope(exc: BaseException) -> Dict[str, Any]:
    """Safe, bounded provider response facts (never secrets)."""
    envelope: Dict[str, Any] = {
        "content_type": None, "response_size": None, "safe_body": None,
    }
    response = getattr(exc, "response", None)
    if response is None:
        return envelope
    try:
        content_type = (response.headers.get("content-type") or "").lower() if getattr(response, "headers", None) else ""
        envelope["content_type"] = (content_type.split(";")[0].strip() or None)
    except Exception:
        pass
    try:
        raw = bytes(getattr(response, "content", b"") or b"")[:2000]
        envelope["response_size"] = len(bytes(getattr(response, "content", b"") or b""))
        envelope["safe_body"] = _scrub_secrets(raw.decode("utf-8", "replace")) or None
    except Exception:
        pass
    return envelope


def should_retry_tts(error_category: str, attempt: int) -> bool:
    return attempt < TTS_MAX_ATTEMPTS and error_category in RETRYABLE_CATEGORIES


def _decode_audio_blob(encoded: Any) -> bytes:
    if not encoded or not isinstance(encoded, str):
        raise ValueError("malformed TTS response: empty audio payload")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        raise ValueError("malformed TTS response: audio payload is not valid base64")
    if not raw:
        raise ValueError("malformed TTS response: decoded audio is empty")
    if len(raw) > MAX_AUDIO_BYTES:
        raise ValueError("malformed TTS response: audio payload exceeds size budget")
    return raw


def _extract_audio(data: Any) -> bytes:
    """Pull audio bytes out of an NVIDIA TTS JSON response.

    Accepts the common audio-carrying shapes (audioContent / audio / data,
    or a single-element output list) so minor catalog schema revisions do
    not break voice. Raises ValueError (never retried) when unusable.
    """
    if isinstance(data, dict):
        for field in ("audioContent", "audio", "data"):
            value = data.get(field)
            if isinstance(value, str) and value.strip():
                return _decode_audio_blob(value)
        output = data.get("output")
        candidates = output if isinstance(output, list) else [output]
        for item in candidates:
            if isinstance(item, str) and item.strip():
                return _decode_audio_blob(item)
            if isinstance(item, dict):
                for field in ("audio", "audioContent", "data", "content"):
                    value = item.get(field)
                    if isinstance(value, str) and value.strip():
                        return _decode_audio_blob(value)
    raise ValueError("malformed TTS response: no audio payload found")


def _debug_enabled(settings: Any) -> bool:
    """Local-development diagnostics flag (TTS_DEBUG=true). Never default on."""
    return getattr(settings, "tts_debug", False) is True


_tts_config_logged = False


def log_tts_config_once(settings: Any, endpoint: str) -> None:
    """One-line safe config summary (never the key). Diagnostics only."""
    global _tts_config_logged
    if _tts_config_logged:
        return
    _tts_config_logged = True
    logger.info(
        "interview_tts_config provider=%s endpoint=%s model=%s voice=%s language=%s function_id=%s api_key_configured=%s",
        (getattr(settings, "tts_provider", None) or "nvidia"),
        _endpoint_label(endpoint),
        (getattr(settings, "nvidia_tts_model", None) or DEFAULT_MODEL),
        (getattr(settings, "nvidia_tts_voice", None) or DEFAULT_VOICE),
        (getattr(settings, "nvidia_tts_language", None) or DEFAULT_LANGUAGE),
        (getattr(settings, "nvidia_tts_function_id", None) or DEFAULT_FUNCTION_ID),
        bool((getattr(settings, "nvidia_api_key", None) or "").strip()),
    )


class NvidiaTTSProvider:
    """NVIDIA API-catalog TTS over HTTP. Backend-only credentials."""

    name = "nvidia"

    @staticmethod
    async def synthesize(
        text: str,
        api_key: str,
        endpoint: str,
        model: str,
        voice: str,
        language: str,
        timeout: int,
    ) -> TTSResult:
        # Documented Magpie TTS HTTP fields (multipart form).
        multipart = {
            "text": (None, text),
            "language": (None, language),
            "voice": (None, voice),
            "encoding": (None, TTS_ENCODING),
            "sample_rate_hz": (None, str(TTS_SAMPLE_RATE_HZ)),
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        for attempt in range(1, TTS_MAX_ATTEMPTS + 1):
            started = perf_counter()
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(endpoint, headers=headers, files=multipart)
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").lower()
                if "audio/" in content_type or "octet-stream" in content_type:
                    audio = bytes(response.content)
                    media_type = content_type.split(";")[0].strip() or "audio/wav"
                else:
                    # Tolerate a JSON-wrapped payload; otherwise treat the body
                    # as the expected WAV/linear PCM bytes.
                    try:
                        audio = _extract_audio(response.json())
                    except ValueError:
                        audio = bytes(response.content)
                    media_type = sniff_media_type(audio) or "audio/wav"
                if sniff_media_type(audio) is None:
                    raise ValueError("malformed TTS response: payload is not playable audio")
                log_tts_event(
                    provider=NvidiaTTSProvider.name, voice=voice, success=True,
                    elapsed_ms=(perf_counter() - started) * 1000,
                    attempt=attempt, retried=attempt > 1,
                )
                return TTSResult(audio=audio, media_type=media_type,
                                 provider=NvidiaTTSProvider.name, voice=voice)
            except HTTPException:
                raise
            except Exception as exc:
                category = classify_tts_error(exc)
                status = _status_from(exc)
                envelope = _provider_response_envelope(exc)
                log_tts_event(
                    provider=NvidiaTTSProvider.name, voice=voice, success=False,
                    elapsed_ms=(perf_counter() - started) * 1000,
                    attempt=attempt, retried=attempt > 1 and should_retry_tts(category, attempt),
                    status=status, error_category=category,
                    endpoint=_endpoint_label(endpoint),
                    content_type=envelope["content_type"],
                    response_size=envelope["response_size"],
                    safe_body=envelope["safe_body"],
                )
                if should_retry_tts(category, attempt):
                    await asyncio.sleep(TTS_RETRY_DELAY_SECONDS)
                    continue
                # Scrubbed, bounded provider facts for the local-debug 503
                # mapping in the endpoint. Never credentials; the endpoint
                # only forwards them when TTS_DEBUG=true.
                body_note = envelope["safe_body"] or "no response body"
                size_note = envelope["response_size"]
                size_text = f"{size_note}B" if size_note is not None else "unknown size"
                ctype = envelope["content_type"] or "unknown content-type"
                reason = f"attempt {attempt}: HTTP {status} ({ctype}, {size_text}): {body_note}"[:600]
                raise HTTPException(status_code=502, detail={
                    "message": "AI voice generation failed",
                    "error_category": category,
                    "status": status,
                    "reason": reason,
                }) from exc
        raise HTTPException(status_code=502, detail="AI voice generation failed")


# ---------------------------------------------------------------------------
# Service boundary (what the rest of INAURA talks to)
# ---------------------------------------------------------------------------

_tts_inflight: Dict[str, "asyncio.Task[TTSResult]"] = {}


def _dedupe_key(text: str, voice: str, session_id: str = "", question_id: str = "") -> str:
    stable = question_id or text
    return hashlib.sha256(f"nvidia|{voice}|{session_id}|{stable}".encode("utf-8")).hexdigest()


class TTSService:
    """Clean TTS boundary. The evaluator must never depend on this."""

    @staticmethod
    async def generate(
        text: str, session_id: str = "", question_id: str = "",
    ) -> TTSResult:
        settings = get_settings()
        provider = (getattr(settings, "tts_provider", None) or "nvidia").strip().lower()
        if provider != "nvidia":
            raise HTTPException(
                status_code=503,
                detail=f"Unknown TTS_PROVIDER '{provider}' — this build supports NVIDIA TTS only ('nvidia').",
            )
        api_key = (getattr(settings, "nvidia_api_key", None) or "").strip()
        if not api_key:
            raise HTTPException(status_code=503, detail={
                "message": "NVIDIA TTS is not configured — set NVIDIA_API_KEY on the backend. "
                           "The interview continues with on-screen question text.",
                "error_category": "authentication_error",
                "status": None,
            })
        cleaned = (text or "").strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Cannot synthesize empty text.")
        cleaned = cleaned[:TTS_MAX_CHARS]
        model = (getattr(settings, "nvidia_tts_model", None) or DEFAULT_MODEL).strip()
        voice = (getattr(settings, "nvidia_tts_voice", None) or DEFAULT_VOICE).strip()
        language = (getattr(settings, "nvidia_tts_language", None) or DEFAULT_LANGUAGE).strip()
        function_id = (getattr(settings, "nvidia_tts_function_id", None) or DEFAULT_FUNCTION_ID).strip()
        endpoint = (getattr(settings, "nvidia_tts_endpoint", None) or "").strip()
        if not endpoint:
            endpoint = default_invocation_url(function_id)
        log_tts_config_once(settings, endpoint)
        try:
            timeout = int(getattr(settings, "nvidia_tts_timeout_seconds", None) or TTS_TIMEOUT_SECONDS_DEFAULT)
        except (TypeError, ValueError):
            timeout = TTS_TIMEOUT_SECONDS_DEFAULT
        timeout = max(5, min(120, timeout))

        key = _dedupe_key(cleaned, voice, session_id, question_id)
        existing = _tts_inflight.get(key)
        if existing is not None:
            return await asyncio.shield(existing)
        task: "asyncio.Task[TTSResult]" = asyncio.ensure_future(
            NvidiaTTSProvider.synthesize(cleaned, api_key, endpoint, model, voice, language, timeout)
        )
        _tts_inflight[key] = task
        try:
            return await asyncio.shield(task)
        finally:
            if _tts_inflight.get(key) is task:
                _tts_inflight.pop(key, None)


async def synthesize(
    text: str, session_id: str = "", question_id: str = "",
) -> TTSResult:
    """Entry point used by the ``/interview/tts`` route."""
    return await TTSService.generate(text, session_id, question_id)
