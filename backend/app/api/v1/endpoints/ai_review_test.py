"""EXPERIMENTAL endpoint: one-call Gemini career review (isolated).

POST /api/v1/ai-review-test — thin wrapper over ai_review_test_service.
Deleting this file + the router line removes the endpoint; nothing else
references it.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ....core.security import get_current_user, CurrentUser
from ....services import ai_review_test_service as review_service

router = APIRouter(prefix="/ai-review-test", tags=["ai-review-test"])


class AIReviewTestRequest(BaseModel):
    target_role: Optional[str] = None


@router.post("")
async def run_ai_review_test(
    payload: AIReviewTestRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        return await review_service.run_ai_review(current_user.id, payload.target_role)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="AI review failed unexpectedly.")
