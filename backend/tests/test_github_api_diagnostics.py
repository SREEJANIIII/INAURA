import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.services.evidence.github import (
    _github_get,
    _get_github_headers,
    _response_diagnostics,
    _safe_failure_message,
)


def test_github_error_categories_preserve_rate_headers_without_token_data():
    response = httpx.Response(
        403,
        json={"message": "Forbidden"},
        headers={"x-ratelimit-limit": "5000", "x-ratelimit-remaining": "4999", "x-ratelimit-reset": "1773000000"},
    )
    diagnostics = _response_diagnostics(response)
    assert diagnostics["category"] == "forbidden"
    assert diagnostics["remaining"] == 4999
    assert "Authorization" not in _safe_failure_message("owner", "repo", diagnostics)


def test_github_get_retries_transient_5xx_but_is_bounded():
    class Client:
        def __init__(self):
            self.calls = 0

        async def get(self, *_args, **_kwargs):
            self.calls += 1
            return httpx.Response(500, json={"message": "server error"})

    client = Client()
    response = asyncio.run(_github_get(client, "https://api.github.com/test"))
    assert response.status_code == 500
    assert client.calls == 3


def test_github_token_is_added_only_to_server_side_request_headers():
    with patch("app.services.evidence.github.get_settings", return_value=SimpleNamespace(github_token="secret-token")):
        headers = _get_github_headers()
    assert headers["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in _safe_failure_message("owner", "repo", {"category": "forbidden", "status_code": 403})


def test_missing_github_token_keeps_requests_unauthenticated():
    with patch("app.services.evidence.github.get_settings", return_value=SimpleNamespace(github_token=None)):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "", "GH_TOKEN": ""}, clear=False):
            headers = _get_github_headers()
    assert "Authorization" not in headers


def test_response_categories_distinguish_auth_and_exhausted_quota():
    auth = _response_diagnostics(httpx.Response(401, json={"message": "Bad credentials"}))
    limited = _response_diagnostics(httpx.Response(403, json={"message": "rate limit"}, headers={"x-ratelimit-remaining": "0"}))
    forbidden = _response_diagnostics(httpx.Response(403, json={"message": "forbidden"}, headers={"x-ratelimit-remaining": "10"}))
    assert auth["category"] == "authentication"
    assert limited["category"] == "rate_limited"
    assert forbidden["category"] == "forbidden"
