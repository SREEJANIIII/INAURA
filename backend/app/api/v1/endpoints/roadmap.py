from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from ....schemas.roadmap import (
    RoadmapGenerateRequest,
    RoadmapItemUpdateRequest,
    RoadmapTaskUpdateRequest,
    RoadmapReassessRequest,
)
from ....services import roadmap_service
from ....core.security import get_current_user, CurrentUser

router = APIRouter(prefix="/roadmap", tags=["roadmap"])


@router.post("/generate")
async def generate_roadmap(
    payload: RoadmapGenerateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    result = await roadmap_service.generate_roadmap(
        current_user.id,
        payload.target_role,
        payload.hours_per_week,
    )
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
    update = {}
    if payload.status is not None:
        update["status"] = payload.status
    if payload.completion_percentage is not None:
        update["completion_percentage"] = payload.completion_percentage
    if not update:
        raise HTTPException(status_code=400, detail="No valid fields to update. Allowed: status, completion_percentage")
    updated = roadmap_service.update_roadmap_item(current_user.id, item_id, update)
    return updated


# --- Weekly Adaptive Endpoints ---

@router.get("/weeks")
async def get_roadmap_weeks(
    roadmap_id: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return roadmap_service.get_roadmap_weeks(current_user.id, roadmap_id)


@router.get("/weeks/{week_id}")
async def get_roadmap_week(
    week_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    return roadmap_service.get_roadmap_week(current_user.id, week_id)


@router.get("/tasks")
async def get_roadmap_tasks(
    week_id: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return roadmap_service.get_roadmap_tasks(current_user.id, week_id)


@router.patch("/tasks/{task_id}")
async def patch_roadmap_task(
    task_id: str,
    payload: RoadmapTaskUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    update = payload.model_dump(exclude_unset=True)
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided to update task")
    return roadmap_service.update_roadmap_task(current_user.id, task_id, update)


@router.post("/reassess")
async def reassess_roadmap(
    payload: RoadmapReassessRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    return await roadmap_service.reassess_and_adapt(
        current_user.id,
        target_role=payload.target_role,
        adjust_hours_per_week=payload.adjust_hours_per_week,
        mode=payload.mode or "compress",
    )
