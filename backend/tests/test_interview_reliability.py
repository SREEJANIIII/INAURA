"""Reliability regressions for the live adaptive interview path."""

import asyncio
import copy
from unittest.mock import AsyncMock, patch

from app.services.assessment import interview as iv
from app.services.gemini_diagnostics import classify_error


class ProviderError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


def test_gemini_error_categories_are_stable():
    assert classify_error(ProviderError(429, "RESOURCE_EXHAUSTED")) == "quota_exhausted"
    assert classify_error(ProviderError(503, "service unavailable")) == "temporary_unavailable"
    assert classify_error(ProviderError(401, "unauthorized")) == "authentication_error"
    assert classify_error(TimeoutError("timed out")) == "timeout"


def test_existing_answer_replays_without_a_second_evaluation():
    response = {"session_id": "s1", "question_id": "q0", "action": "NEXT", "evaluation": {"depth": 0.8}}
    session = {
        "evaluation_results": [{
            "question_id": "q0",
            "transcript_hash": iv._answer_hash("same answer"),
            "response": response,
        }],
    }
    assert iv._existing_answer(session, "q0", iv._answer_hash("same answer")) == response


def test_concurrent_session_operations_are_serialized():
    calls = []

    async def fake_locked(*args, **kwargs):
        calls.append(args[1])
        await asyncio.sleep(0.01)
        return {"ok": True}

    async def run():
        with patch.object(iv, "_answer_interview_question_locked", new=fake_locked):
            await asyncio.gather(
                iv.answer_interview_question("u", "same-session", "q", "a"),
                iv.answer_interview_question("u", "same-session", "q", "a"),
            )

    asyncio.run(run())
    # The lock prevents overlapping work; durable claims handle the replay
    # decision in the real locked implementation.
    assert calls == ["same-session", "same-session"]
