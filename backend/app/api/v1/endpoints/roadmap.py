from fastapi import APIRouter, Depends, HTTPException
from ....schemas.roadmap import RoadmapGenerateRequest, RoadmapItemUpdateRequest
from ....services import roadmap_service
from ....core.security import get_current_user, CurrentUser

router = APIRouter(prefix="/roadmap", tags=["roadmap"])

@router.post("/generate")
async def generate_roadmap(
    payload: RoadmapGenerateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    # Use target_role if provided, else None -> service will fallback to latest analysis role
    result = await roadmap_service.generate_roadmap(current_user.id, payload.target_role)
    return result

@router.get("/latest")
async def get_latest_roadmap(current_user: CurrentUser = Depends(get_current_user)):
    data = roadmap_service.get_latest_roadmap(current_user.id)
    return data

@router.get("/items")
async def get_roadmap_items(current_user: CurrentUser = Depends(get_current_user)):
    data = roadmap_service.get_all_items_for_user(current_user.id)
    return data

@router.get("/milestones")
async def get_roadmap_milestones(current_user: CurrentUser = Depends(get_current_user)):
    data = roadmap_service.get_all_milestones_for_user(current_user.id)
    return data

@router.patch("/items/{item_id}")
async def patch_roadmap_item(
    item_id: str,
    payload: RoadmapItemUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    # Only allow status and completion_percentage, forbid other fields via schema extra=forbid
    update = {}
    if payload.status is not None:
        update["status"] = payload.status
    if payload.completion_percentage is not None:
        update["completion_percentage"] = payload.completion_percentage
    if not update:
        raise HTTPException(status_code=400, detail="No valid fields to update. Allowed: status, completion_percentage")
    updated = roadmap_service.update_roadmap_item(current_user.id, item_id, update)
    return updated
