from fastapi import APIRouter, Depends, Query
from ....schemas.capability import CapabilityMapResponse
from ....services import capability_map as capability_service
from ....core.security import get_current_user, CurrentUser
from typing import Optional

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/capability-map", response_model=CapabilityMapResponse)
def get_capability_map(
    target_role: Optional[str] = Query(default=None, description="Target role, e.g. Backend Developer"),
    skill: Optional[str] = Query(default=None, description="Optional single skill filter, e.g. Python"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Skill Capability Map: per required skill, what industry expects, what
    the student should be able to do, what INAURA found, and what is missing.
    Deterministic read-only view over existing analysis; changes nothing."""
    return capability_service.build_capability_map_for_user(
        current_user.id, target_role=target_role, skill=skill
    )
