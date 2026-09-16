"""Developer-only NVIDIA TTS connectivity probe (manual use, never pytest).

Uses the SAME endpoint, voice, language, and multipart fields as the real
provider (imported from app.services.tts_service), with NVIDIA_API_KEY read
from the environment.

Prints ONLY: HTTP status, Content-Type, response size, elapsed time, and a
safe (secret-scrubbed, bounded) response body on failure. Saves the audio to
backend/tmp/nvidia_tts_test.wav on success (gitignored, never commit).

Usage (backend/.env must define NVIDIA_API_KEY, or export it ambiently):
    python scripts/nvidia_tts_probe.py ["custom text..."]

Exit codes: 0 success, 1 provider failure, 2 missing API key.
"""

import os
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.tts_service import (  # noqa: E402
    TTS_SAMPLE_RATE_HZ,
    TTS_ENCODING,
    DEFAULT_FUNCTION_ID,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    _endpoint_label,
    _scrub_secrets,
    default_invocation_url,
    sniff_media_type,
)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def main() -> int:
    api_key = _env("NVIDIA_API_KEY")
    if not api_key:
        print("NVIDIA_API_KEY is not set — refusing to probe without credentials.")
        return 2
    function_id = _env("NVIDIA_TTS_FUNCTION_ID", DEFAULT_FUNCTION_ID)
    endpoint = _env("NVIDIA_TTS_ENDPOINT") or default_invocation_url(function_id)
    voice = _env("NVIDIA_TTS_VOICE", DEFAULT_VOICE)
    language = _env("NVIDIA_TTS_LANGUAGE", DEFAULT_LANGUAGE)
    model = _env("NVIDIA_TTS_MODEL", DEFAULT_MODEL)
    text = " ".join(sys.argv[1:]).strip() or "Hello, this is a test of the INAURA interviewer voice."

    print(f"provider=nvidia endpoint={_endpoint_label(endpoint)} model={model} "
          f"voice={voice} language={language} api_key_configured=true")
    multipart = {
        "text": (None, text),
        "language": (None, language),
        "voice": (None, voice),
        "encoding": (None, TTS_ENCODING),
        "sample_rate_hz": (None, str(TTS_SAMPLE_RATE_HZ)),
    }
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                files=multipart,
            )
    except Exception as exc:
        print(f"transport_error category={type(exc).__name__} "
              f"message={_scrub_secrets(str(exc))[:300]}")
        return 1
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    content_type = (response.headers.get("content-type") or "").lower()
    size = len(response.content or b"")
    print(f"status={response.status_code} content_type={content_type or 'none'} "
          f"size={size}B elapsed_ms={elapsed_ms}")
    if response.status_code == 200 and (sniff_media_type(bytes(response.content or b"")) or "audio/" in content_type):
        out = Path(__file__).resolve().parent.parent / "tmp" / "nvidia_tts_test.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(bytes(response.content))
        print(f"saved={out} (gitignored, do not commit)")
        return 0
    safe = _scrub_secrets((response.content or b"")[:2000].decode("utf-8", "replace"))
    print(f"safe_body={safe[:500] or 'empty'}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
