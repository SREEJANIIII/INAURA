"""TTS diagnostics: provider errors are logged, classified, and mapped to a
safe 503 — without ever exposing secrets or touching interview logic.

NVIDIA is always mocked here. For a live check use the manual probe:
    python backend/scripts/nvidia_tts_probe.py
"""

import asyncio
import base64
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.services import tts_service
from app.services.tts_service import TTSService


def _settings(key="nvapi-TESTKEY123", debug=False):
    s = MagicMock()
    s.tts_provider = "nvidia"
    s.nvidia_api_key = key
    s.nvidia_tts_model = "magpie-tts-multilingual"
    s.nvidia_tts_voice = "Magpie-Multilingual.EN-US.Aria"
    s.nvidia_tts_language = "en-US"
    s.nvidia_tts_function_id = "func-123"
    s.nvidia_tts_endpoint = ""
    s.nvidia_tts_timeout_seconds = 30
    s.tts_debug = debug
    return s


class _FakeClient:
    def __init__(self, effects):
        self._effects = list(effects)
        self.posts = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *args, **kwargs):
        self.posts += 1
        effect = self._effects[min(self.posts - 1, len(self._effects) - 1)]
        if callable(effect) and not isinstance(effect, MagicMock):
            return await effect(url, *args, **kwargs)
        if isinstance(effect, Exception):
            raise effect
        return effect


def _http_error(status: int, body: str, content_type: str = "application/json"):
    request = httpx.Request("POST", "https://example.test/api")
    response = httpx.Response(status, request=request, content=body.encode(),
                              headers={"content-type": content_type})
    return httpx.HTTPStatusError(f"error {status}", request=request, response=response)


def _run_sync(text, client, key="nvapi-TESTKEY123", debug=False):
    async def _run():
        with (
            patch("app.services.tts_service.get_settings",
                  return_value=_settings(key, debug)),
            patch("app.services.tts_service.httpx.AsyncClient", return_value=client),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            return await TTSService.generate(text, "s1", "q1")

    return asyncio.run(_run())


def _tts_event_records(caplog):
    out = []
    for record in caplog.records:
        if record.name != "inaura.tts":
            continue
        message = record.getMessage()
        if "interview_tts_event" not in message:
            continue
        payload = message.split("interview_tts_event", 1)[1].strip()
        try:
            out.append(json.loads(payload))
        except ValueError:
            pass
    return out


@pytest.fixture(autouse=True)
def _clean_state():
    tts_service._tts_inflight.clear()
    tts_service._tts_config_logged = False
    yield
    tts_service._tts_inflight.clear()
    tts_service._tts_config_logged = True  # silence config log after tests


@pytest.mark.parametrize("status,category", [
    (401, "authentication_error"),
    (403, "authentication_error"),
    (404, "invalid_request"),
    (429, "rate_limited"),
    (500, "temporary_unavailable"),
])
def test_provider_statuses_are_classified(status, category):
    client = _FakeClient([
        _http_error(500, "boom"),
        _http_error(status, f"provider says {status}"),
    ] if status == 500 else [_http_error(status, f"provider says {status}")])
    with pytest.raises(HTTPException) as exc_info:
        _run_sync("Hello.", client)
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["error_category"] == category
    assert exc_info.value.detail["status"] == status
    # Fail-fast categories never retry; 5xx gets exactly one retry.
    assert client.posts == (2 if category == "temporary_unavailable" else 1)


def test_httpx_transport_errors_are_distinguished():
    request = httpx.Request("POST", "https://example.test/api")
    timeout_client = _FakeClient([httpx.TimeoutException("timed out", request=request)])
    with pytest.raises(HTTPException) as exc_info:
        _run_sync("Hello.", timeout_client)
    assert exc_info.value.detail["error_category"] == "timeout"

    connect_client = _FakeClient([httpx.ConnectError("connection refused", request=request)])
    with pytest.raises(HTTPException) as exc_info:
        _run_sync("Hello.", connect_client)
    assert exc_info.value.detail["error_category"] == "network_error"


def test_failure_log_contains_safe_provider_facts_and_no_secrets(caplog):
    body = '{"error": "invalid API key nvapi-TESTKEY123"}'
    client = _FakeClient([_http_error(401, body)])
    with caplog.at_level(logging.INFO, logger="inaura.tts"):
        with pytest.raises(HTTPException):
            _run_sync("Hello.", client)
    events = [e for e in _tts_event_records(caplog) if e.get("success") is False]
    assert events, "expected a failed interview_tts_event"
    event = events[-1]
    assert event["provider"] == "nvidia"
    assert event["status"] == 401
    assert event["error_category"] == "authentication_error"
    assert event["endpoint"] == "func-123.invocation.api.nvcf.nvidia.com/v1/audio/synthesize"
    assert event["content_type"] == "application/json"
    assert event["response_size"] == len(body.encode())
    assert "invalid API key" in (event["safe_body"] or "")
    blob = json.dumps(event)
    assert "nvapi-TESTKEY123" not in blob
    assert "Bearer" not in blob


def test_config_summary_logs_facts_without_key(caplog):
    client = _FakeClient([_http_error(503, "down")])
    with caplog.at_level(logging.INFO, logger="inaura.tts"):
        with pytest.raises(HTTPException):
            _run_sync("Hello.", client)
    config_lines = [
        r.getMessage() for r in caplog.records
        if r.name == "inaura.tts" and "interview_tts_config" in r.getMessage()
    ]
    assert config_lines, "expected one config summary line"
    line = config_lines[0]
    for token in ("provider=nvidia", "magpie-tts-multilingual",
                  "Magpie-Multilingual.EN-US.Aria", "api_key_configured=True"):
        assert token in line
    assert "nvapi-TESTKEY123" not in line


def _endpoint_503(detail_502, debug):
    from app.api.v1.endpoints.assessment import interview_tts
    from app.schemas.assessment import InterviewTTSRequest

    async def _call():
        with (
            patch.object(tts_service, "synthesize",
                         new=AsyncMock(side_effect=HTTPException(status_code=502, detail=detail_502))),
            patch("app.api.v1.endpoints.assessment.get_settings",
                  return_value=_settings(debug=debug)),
        ):
            return await interview_tts(
                InterviewTTSRequest(text="Q?", session_id="s", question_id="q"), object())

    return asyncio.run(_call())


def test_debug_503_contains_safe_provider_facts():
    with pytest.raises(HTTPException) as exc_info:
        _endpoint_503({"message": "x", "error_category": "authentication_error",
                       "status": 401, "reason": "attempt 1: HTTP 401"}, debug=True)
    assert exc_info.value.status_code == 503
    detail = exc_info.value.detail
    assert detail["message"] == "NVIDIA TTS request failed"
    assert detail["provider"] == "nvidia"
    assert detail["status"] == 401
    assert detail["category"] == "authentication_error"
    assert "HTTP 401" in detail["reason"]


def test_production_503_stays_generic():
    with pytest.raises(HTTPException) as exc_info:
        _endpoint_503({"message": "x", "error_category": "authentication_error",
                       "status": 401, "reason": "attempt 1: HTTP 401"}, debug=False)
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {
        "message": "NVIDIA TTS request failed",
        "provider": "nvidia",
    }
