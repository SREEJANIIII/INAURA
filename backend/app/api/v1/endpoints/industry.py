from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from ....schemas.industry import IndustryRequirementResponse, RetrieveRequest, RetrieveResponse
from ....services import industry_service, retrieval_service
from ....core.security import get_current_user, CurrentUser

router = APIRouter(prefix="/industry", tags=["industry"])


@router.get("/roles", response_model=List[str])
async def get_roles(current_user: CurrentUser = Depends(get_current_user)):
    # Industry roles are readable by any authenticated user
    return industry_service.list_roles()


@router.get("/requirements", response_model=List[IndustryRequirementResponse])
async def get_requirements(
    role: str = Query(..., description="Role name e.g., AI/ML Engineer"),
    current_user: CurrentUser = Depends(get_current_user),
):
    data = industry_service.list_by_role(role)
    return data


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_requirements(
    payload: RetrieveRequest, current_user: CurrentUser = Depends(get_current_user)
):
    result = await retrieval_service.retrieve(payload.role, payload.query, payload.top_k)
    # Map to response model
    items = [
        {
            "id": r["id"],
            "role": r["role"],
            "skill": r["skill"],
            "skill_category": r["skill_category"],
            "importance": r["importance"],
            "demand": r["demand"],
            "interview_relevance": r["interview_relevance"],
            "source": r["source"],
            "source_url": r.get("source_url"),
            "description": r.get("description"),
            "version": r.get("version", "v1-prototype"),
            "similarity": r.get("similarity", 0),
        }
        for r in result["items"]
    ]
    return {
        "role": result["role"],
        "query": result["query"],
        "count": result["count"],
        "items": items,
        "note": result.get("note", ""),
    }
