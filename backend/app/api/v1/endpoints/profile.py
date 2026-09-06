from fastapi import APIRouter, Depends, HTTPException
from ....schemas.profile import ProfileCreate, ProfileUpdate, ProfileResponse
from ....services import profile_service
from ....core.security import get_current_user, CurrentUser

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
async def get_my_profile(current_user: CurrentUser = Depends(get_current_user)):
    data = profile_service.get_profile(current_user.id)
    if not data:
        raise HTTPException(status_code=404, detail="Profile not found")
    return data


@router.post("", response_model=ProfileResponse, status_code=201)
async def create_profile(
    payload: ProfileCreate, current_user: CurrentUser = Depends(get_current_user)
):
    # payload already validated
    data = profile_service.upsert_profile(current_user.id, payload.model_dump())
    return data


@router.put("", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdate, current_user: CurrentUser = Depends(get_current_user)
):
    # filter None values but allow partial
    clean = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update")
    data = profile_service.update_profile_partial(current_user.id, clean)
    return data
