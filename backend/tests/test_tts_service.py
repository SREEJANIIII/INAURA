"""NVIDIA TTS: provider selection, validation, retry, coalescing, independence.

NVIDIA HTTP calls are always mocked — the suite never needs an API key,
network access, or a catalog function.
"""

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.services import tts_service
from app.services.tts_service import (
    TTSService,
    is_valid_mp3,
    is_valid_wav,
)


def _settings(provider="nvidia", key="test-nvidia-key", timeout=30):
    s = MagicMock()
    s.tts_provider = provider
    s.nvidia_api_key = key
    s.nvidia_tts_model = "magpie-tts-multilingual"
    s.nvidia_tts_voice = "Magpie-Multilingual.EN-US.Aria"
    s.nvidia_tts_language = "en-US"
    s.nvidia_tts_function_id = "func-123"
    s.nvidia_tts_endpoint = ""
    s.nvidia_tts_timeout_seconds = timeout
    s.google_api_key = "gemini-key-unused-by-tts"
    return s


def _wav_bytes() -> bytes:
    pcm = b"\x00\x01" * 100
    return (
        b"RIFF" + (36 + len(pcm)).to_bytes(4, "little") + b"WAVEfmt "
        + (16).to_bytes(4, "little") + b"\x01\x00\x01\x00"
        + (24000).to_bytes(4, "little") + (48000).to_bytes(4, "little")
        + b"\x02\x00\x10\x00" + b"data" + len(pcm).to_bytes(4, "little") + pcm
    )


def _mp3_bytes() -> bytes:
    return b"ID3" + b"\x00\x01" * 100


def _json_ok_response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    resp.headers = {"content-type": "application/json"}
    return resp


def _audio_ok_response(audio: bytes, media_type: str):
    resp = MagicMock()
    resp.content = audio
    resp.raise_for_status.return_value = None
    resp.headers = {"content-type": media_type}
    return resp


class _FakeClient:
    """Minimal async-CM stand-in for httpx.AsyncClient; records requests."""

    def __init__(self, effects):
        self._effects = list(effects)
        self.posts = 0
        self.urls: list[str] = []
        self.headers: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *args, **kwargs):
        self.posts += 1
        self.urls.append(str(url))
        self.headers.append(dict(kwargs.get("headers") or {}))
        effect = self._effects[min(self.posts - 1, len(self._effects) - 1)]
        if callable(effect) and not isinstance(effect, MagicMock):
            return await effect(url, *args, **kwargs)
        if isinstance(effect, Exception):
            raise effect
        return effect


def _http_error(status: int, message: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test/api")
    response = httpx.Response(status, request=request, text=message)
    return httpx.HTTPStatusError(message, request=request, response=response)


async def _run(text, client, provider="nvidia", key="test-nvidia-key",
               session_id="", question_id=""):
    with (
        patch("app.services.tts_service.get_settings",
              return_value=_settings(provider, key)),
        patch("app.services.tts_service.httpx.AsyncClient", return_value=client),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        return await TTSService.generate(text, session_id, question_id)


def _run_sync(text, client, provider="nvidia", key="test-nvidia-key",
              session_id="", question_id=""):
    return asyncio.run(_run(text, client, provider, key, session_id, question_id))


def _b64(audio: bytes) -> str:
    return base64.b64encode(audio).decode()


def test_success_returns_correct_audio_bytes_and_mime():
    audio = _mp3_bytes()
    client = _FakeClient([_json_ok_response({"audioContent": _b64(audio)})])
    result = _run_sync("What breaks at 10x load?", client)
    assert result.audio == audio
    assert result.media_type == "audio/mpeg"
    assert result.provider == "nvidia"
    assert result.voice == "Magpie-Multilingual.EN-US.Aria"
    assert client.posts == 1


def test_raw_audio_body_is_accepted_with_its_content_type():
    audio = _wav_bytes()
    assert is_valid_wav(audio) is True
    client = _FakeClient([_audio_ok_response(audio, "audio/wav")])
    result = _run_sync("Hello.", client)
    assert result.audio == audio
    assert result.media_type == "audio/wav"


def test_bearer_key_is_sent_and_text_reaches_nvidia():
    seen: dict = {}
    inner = _json_ok_response({"audio": _b64(_mp3_bytes())})

    async def spy(url, *args, **kwargs):
        seen["url"] = str(url)
        seen["headers"] = dict(kwargs.get("headers") or {})
        seen["files"] = dict(kwargs.get("files") or {})
        return inner

    client = _FakeClient([spy])
    _run_sync("Exact Gemini follow-up?", client)
    assert "invocation.api.nvcf.nvidia.com/v1/audio/synthesize" in seen["url"]
    assert seen["headers"]["Authorization"] == "Bearer test-nvidia-key"
    assert "NVIDIA_API_KEY" not in seen["headers"]["Authorization"]
    assert "Content-Type" not in seen["headers"]  # httpx sets multipart boundary itself
    fields = {k: v[1] for k, v in seen["files"].items()}
    assert fields["text"] == "Exact Gemini follow-up?"
    assert fields["language"] == "en-US"
    assert fields["voice"] == "Magpie-Multilingual.EN-US.Aria"
    assert fields["encoding"] == "LINEAR_PCM"
    assert fields["sample_rate_hz"] == "44100"


def test_raw_pcm_body_without_audio_content_type_is_accepted_as_wav():
    audio = _wav_bytes()
    resp = MagicMock()
    resp.content = audio
    resp.raise_for_status.return_value = None
    resp.headers = {"content-type": "application/octet-stream"}
    resp.json.side_effect = ValueError("no json")
    client = _FakeClient([resp])
    result = _run_sync("Hello.", client)
    assert result.audio == audio
    assert result.media_type == "application/octet-stream"


def test_401_auth_failure_fails_fast():
    client = _FakeClient([_http_error(401, "unauthorized: invalid api key")])
    with pytest.raises(HTTPException) as exc_info:
        _run_sync("Hello.", client)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error_category"] == "authentication_error"
    assert client.posts == 1


def test_429_rate_limit_fails_fast():
    client = _FakeClient([_http_error(429, "Too Many Requests: rate limit exceeded")])
    with pytest.raises(HTTPException) as exc_info:
        _run_sync("Hello.", client)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error_category"] == "rate_limited"
    assert client.posts == 1


def test_5xx_retries_once_then_succeeds():
    client = _FakeClient([
        _http_error(503, "Service Unavailable"),
        _json_ok_response({"audioContent": _b64(_mp3_bytes())}),
    ])
    result = _run_sync("Hello.", client)
    assert is_valid_mp3(result.audio) is True
    assert client.posts == 2


def test_5xx_twice_fails_after_exactly_one_retry():
    client = _FakeClient([
        _http_error(503, "Service Unavailable"),
        _http_error(503, "Service Unavailable"),
    ])
    with pytest.raises(HTTPException) as exc_info:
        _run_sync("Hello.", client)
    assert exc_info.value.detail["error_category"] == "temporary_unavailable"
    assert client.posts == 2


def test_timeout_retries_once_then_succeeds():
    request = httpx.Request("POST", "https://example.test/api")
    client = _FakeClient([
        httpx.TimeoutException("timed out", request=request),
        _json_ok_response({"data": _b64(_mp3_bytes())}),
    ])
    result = _run_sync("Hello.", client)
    assert is_valid_mp3(result.audio) is True
    assert client.posts == 2


def test_malformed_response_raises_without_retry():
    client = _FakeClient([_json_ok_response({"nope": "nothing here"})])
    with pytest.raises(HTTPException) as exc_info:
        _run_sync("Hello.", client)
    assert exc_info.value.status_code == 502
    assert client.posts == 1


def test_empty_text_rejected_before_network():
    client = _FakeClient([_json_ok_response({"audio": _b64(_mp3_bytes())})])
    with pytest.raises(HTTPException) as exc_info:
        _run_sync("   ", client)
    assert exc_info.value.status_code == 400
    assert client.posts == 0


def test_missing_api_key_is_a_clear_503_without_network():
    client = _FakeClient([_json_ok_response({"audio": _b64(_mp3_bytes())})])
    with pytest.raises(HTTPException) as exc_info:
        _run_sync("Hello.", client, key=None)
    assert exc_info.value.status_code == 503
    assert "NVIDIA_API_KEY" in str(exc_info.value.detail.get("message"))
    assert client.posts == 0


def test_concurrent_duplicate_requests_are_coalesced():
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def gated(url, *args, **kwargs):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return _json_ok_response({"audioContent": _b64(_mp3_bytes())})

    client = _FakeClient([gated])
    with (
        patch("app.services.tts_service.get_settings", return_value=_settings()),
        patch("app.services.tts_service.httpx.AsyncClient", return_value=client),
    ):
        async def run():
            first = asyncio.ensure_future(
                TTSService.generate("Same question?", "s1", "q1"))
            await started.wait()
            second = asyncio.ensure_future(
                TTSService.generate("Same question?", "s1", "q1"))
            await asyncio.sleep(0)
            release.set()
            return await asyncio.gather(first, second)

        a, b = asyncio.run(run())
    assert calls == 1
    assert a.audio == b.audio


def test_tts_failure_does_not_touch_interview_evaluation():
    import pathlib

    src = pathlib.Path(tts_service.__file__).read_text()
    assert "evaluate_answer" not in src
    assert "assessment" not in src
    assert "generativelanguage" not in src


def test_gemini_evaluation_model_is_unchanged():
    from app.core.config import Settings

    assert Settings().gemini_model == "gemini-2.5-flash"
    import pathlib

    interview_src = (
        pathlib.Path(tts_service.__file__).parent / "assessment" / "interview.py"
    ).read_text()
    assert "gemini-2.5-flash" in interview_src
    assert "gemini-2.5-flash-preview-tts" not in interview_src


def test_tts_endpoint_returns_provider_audio_with_correct_mime():
    from app.api.v1.endpoints.assessment import interview_tts
    from app.schemas.assessment import InterviewTTSRequest
    from app.services.tts_service import TTSResult

    expected = TTSResult(audio=_mp3_bytes(), media_type="audio/mpeg",
                         provider="nvidia", voice="v")
    with patch.object(tts_service, "synthesize", new=AsyncMock(return_value=expected)):
        response = asyncio.run(
            interview_tts(InterviewTTSRequest(text="Q?", session_id="s", question_id="q"), object())
        )
    assert response.media_type == "audio/mpeg"
    assert response.body == expected.audio
    assert response.headers["Cache-Control"] == "no-store"
