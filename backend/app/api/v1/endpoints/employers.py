"""Person 2: employer endpoints (thin routes -> employer_service)."""

from fastapi import APIRouter, Depends

from ....core.security import get_current_user, CurrentUser
from ....schemas.employers import (
    EmployerCreate,
    EmployerUpdate,
    EmployerOut,
    MemberAdd,
    MemberOut,
    RequirementCreate,
    RequirementUpdate,
    RequirementOut,
    RequirementSkillsBulk,
    RequirementSkillOut,
)
from ....services import employer_service as svc

router = APIRouter(prefix="/employers", tags=["employers"])


@router.post("", response_model=EmployerOut, status_code=201)
def create_employer(payload: EmployerCreate, current_user: CurrentUser = Depends(get_current_user)):
    return svc.create_employer(current_user.id, payload.model_dump())


@router.get("", response_model=list[EmployerOut])
def list_employers(current_user: CurrentUser = Depends(get_current_user)):
    return svc.list_employers(current_user.id)


@router.get("/{employer_id}", response_model=EmployerOut)
def get_employer(employer_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.get_employer(current_user.id, employer_id)


@router.patch("/{employer_id}", response_model=EmployerOut)
def update_employer(employer_id: str, payload: EmployerUpdate, current_user: CurrentUser = Depends(get_current_user)):
    clean = {k: v for k, v in payload.model_dump().items() if v is not None}
    return svc.update_employer(current_user.id, employer_id, clean)


@router.delete("/{employer_id}", status_code=204)
def delete_employer(employer_id: str, current_user: CurrentUser = Depends(get_current_user)):
    svc.delete_employer(current_user.id, employer_id)
    return None


@router.get("/{employer_id}/members", response_model=list[MemberOut])
def list_members(employer_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.list_members(current_user.id, employer_id)


@router.post("/{employer_id}/members", response_model=MemberOut, status_code=201)
def add_member(employer_id: str, payload: MemberAdd, current_user: CurrentUser = Depends(get_current_user)):
    return svc.add_member(current_user.id, employer_id, payload.user_id, payload.role)


@router.delete("/{employer_id}/members/{target_user_id}", status_code=204)
def remove_member(employer_id: str, target_user_id: str, current_user: CurrentUser = Depends(get_current_user)):
    svc.remove_member(current_user.id, employer_id, target_user_id)
    return None


@router.post("/{employer_id}/requirements", response_model=RequirementOut, status_code=201)
def create_requirement(employer_id: str, payload: RequirementCreate, current_user: CurrentUser = Depends(get_current_user)):
    return svc.create_requirement(current_user.id, employer_id, payload.model_dump())


@router.get("/{employer_id}/requirements", response_model=list[RequirementOut])
def list_requirements(employer_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.list_requirements(current_user.id, employer_id)
