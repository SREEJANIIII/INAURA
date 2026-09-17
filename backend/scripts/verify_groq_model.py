"""Verify the configured GROQ_MODEL is currently supported by the Groq API.

Manual use (never pytest): run once after setting GROQ_API_KEY/GROQ_MODEL.

    python scripts/verify_groq_model.py

Prints ONLY the configured model, whether it is listed, and a bounded
sample of available model ids. Never prints the API key.

Exit codes: 0 supported, 1 not listed/unreachable, 2 missing API key.
"""

import os
import sys


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def main() -> int:
    api_key = _env("GROQ_API_KEY")
    if not api_key:
        print("GROQ_API_KEY is not set — cannot verify the Groq model.")
        return 2
    model = _env("GROQ_MODEL", "llama-3.3-70b-versatile")
    try:
        from groq import Groq
    except ImportError:
        print("groq SDK not installed — add it to backend/requirements.txt first.")
        return 1
    try:
        client = Groq(api_key=api_key)
        available = sorted(m.id for m in client.models.list().data)
    except Exception as exc:
        print(f"Groq models endpoint unreachable: {type(exc).__name__}")
        return 1
    print(f"configured_model={model}")
    print(f"supported={str(model in available).lower()}")
    print(f"sample_models={', '.join(available[:12]) or 'none'}")
    return 0 if model in available else 1


if __name__ == "__main__":
    raise SystemExit(main())
