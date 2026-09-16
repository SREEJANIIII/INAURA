import asyncio

from app.services import evidence_service


def test_concurrent_verification_for_same_evidence_is_coalesced():
    calls = 0

    async def fake_verify(_user_id, _evidence_id, _force_refresh=False):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return {"id": "e1", "verification_status": "verified"}

    async def run():
        evidence_service._IN_FLIGHT_VERIFICATIONS.clear()
        original = evidence_service._verify_evidence_item_once
        evidence_service._verify_evidence_item_once = fake_verify
        try:
            return await asyncio.gather(
                evidence_service.verify_evidence_item("u1", "e1"),
                evidence_service.verify_evidence_item("u1", "e1"),
            )
        finally:
            evidence_service._verify_evidence_item_once = original
            evidence_service._IN_FLIGHT_VERIFICATIONS.clear()

    results = asyncio.run(run())
    assert calls == 1
    assert results[0] == results[1]
