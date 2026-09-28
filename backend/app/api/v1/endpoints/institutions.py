"""P0 #2: institution / training-supply endpoints (thin routes -> institution_service)."""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from ....core.security import get_current_user, CurrentUser
from ....schemas.institutions import (
    InstitutionCreate,
    InstitutionUpdate,
    InstitutionResponse,
    CourseCreate,
    CourseUpdate,
    CourseResponse,
    CourseModuleCreate,
    CourseModuleUpdate,
    CourseModuleResponse,
    CourseSkillCreate,
    CourseSkillResponse,
    TrainerCreate,
    TrainerResponse,
    TrainerSkillCreate,
    TrainerSkillResponse,
    CourseCoverageResponse,
)
from ....services import institution_service as svc

router = APIRouter(prefix="/institutions", tags=["institutions"])

# ---------------------------------------------------------------------------
# Institutions
# ---------------------------------------------------------------------------


@router.post("", response_model=InstitutionResponse, status_code=201)
def create_institution(payload: InstitutionCreate, current_user: CurrentUser = Depends(get_current_user)):
    return svc.create_institution(payload.model_dump())


@router.get("", response_model=list[InstitutionResponse])
def list_institutions(
    district: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    institution_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.list_institutions(district, state, institution_type, status)


@router.get("/{institution_id}", response_model=InstitutionResponse)
def get_institution(institution_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.get_institution(institution_id)


@router.patch("/{institution_id}", response_model=InstitutionResponse)
def update_institution(
    institution_id: str, payload: InstitutionUpdate, current_user: CurrentUser = Depends(get_current_user)
):
    clean = {k: v for k, v in payload.model_dump().items() if v is not None}
    return svc.update_institution(institution_id, clean)


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------


@router.post("/{institution_id}/courses", response_model=CourseResponse, status_code=201)
def create_course(
    institution_id: str, payload: CourseCreate, current_user: CurrentUser = Depends(get_current_user)
):
    return svc.create_course(institution_id, payload.model_dump())


@router.get("/{institution_id}/courses", response_model=list[CourseResponse])
def list_courses(
    institution_id: str,
    status: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.list_courses(institution_id, status)


# ---------------------------------------------------------------------------
# Trainers
# ---------------------------------------------------------------------------


@router.post("/{institution_id}/trainers", response_model=TrainerResponse, status_code=201)
def create_trainer(
    institution_id: str, payload: TrainerCreate, current_user: CurrentUser = Depends(get_current_user)
):
    return svc.create_trainer(institution_id, payload.model_dump())


@router.get("/{institution_id}/trainers", response_model=list[TrainerResponse])
def list_trainers(
    institution_id: str,
    status: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.list_trainers(institution_id, status)


course_router = APIRouter(prefix="/courses", tags=["courses"])
trainer_router = APIRouter(prefix="/trainers", tags=["trainers"])


@course_router.get("/{course_id}", response_model=CourseResponse)
def get_course(course_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.get_course(course_id)


@course_router.patch("/{course_id}", response_model=CourseResponse)
def update_course(course_id: str, payload: CourseUpdate, current_user: CurrentUser = Depends(get_current_user)):
    clean = {k: v for k, v in payload.model_dump().items() if v is not None}
    return svc.update_course(course_id, clean)


@course_router.post("/{course_id}/modules", response_model=CourseModuleResponse, status_code=201)
def create_module(course_id: str, payload: CourseModuleCreate, current_user: CurrentUser = Depends(get_current_user)):
    return svc.create_module(course_id, payload.model_dump())


@course_router.get("/{course_id}/modules", response_model=list[CourseModuleResponse])
def list_modules(course_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.list_modules(course_id)


@course_router.post("/{course_id}/skills", response_model=CourseSkillResponse, status_code=201)
def attach_course_skill(
    course_id: str, payload: CourseSkillCreate, current_user: CurrentUser = Depends(get_current_user)
):
    data = payload.model_dump()
    if data.get("module_id") is not None:
        data["module_id"] = str(data["module_id"])
    return svc.attach_course_skill(course_id, data)


@course_router.get("/{course_id}/skills", response_model=list[CourseSkillResponse])
def list_course_skills(
    course_id: str,
    mapping_status: Optional[str] = Query(None, pattern="^(mapped|unmapped)$"),
    current_user: CurrentUser = Depends(get_current_user),
):
    return svc.list_course_skills(course_id, mapping_status)


@course_router.get("/{course_id}/coverage", response_model=CourseCoverageResponse)
def get_course_coverage(course_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.get_course_coverage(course_id)


@course_router.delete("/{course_id}/skills/{skill_row_id}", status_code=204)
def remove_course_skill(course_id: str, skill_row_id: str, current_user: CurrentUser = Depends(get_current_user)):
    svc.remove_course_skill(course_id, skill_row_id)
    return None


@trainer_router.post("/{trainer_id}/skills", response_model=TrainerSkillResponse, status_code=201)
def attach_trainer_skill(
    trainer_id: str, payload: TrainerSkillCreate, current_user: CurrentUser = Depends(get_current_user)
):
    return svc.attach_trainer_skill(trainer_id, payload.model_dump())


@trainer_router.get("/{trainer_id}/skills", response_model=list[TrainerSkillResponse])
def list_trainer_skills(trainer_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return svc.list_trainer_skills(trainer_id)


@trainer_router.delete("/{trainer_id}/skills/{skill_row_id}", status_code=204)
def remove_trainer_skill(trainer_id: str, skill_row_id: str, current_user: CurrentUser = Depends(get_current_user)):
    svc.remove_trainer_skill(trainer_id, skill_row_id)
    return None
