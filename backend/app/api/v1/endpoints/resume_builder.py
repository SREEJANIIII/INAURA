from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from ....core.security import CurrentUser, get_current_user
from ....schemas.resume import ResumeCreate, ResumeResponse, ResumeUpdate
from ....services import resume_builder

router = APIRouter(prefix="/resumes", tags=["resume-builder"])

@router.get("", response_model=list[ResumeResponse])
def list_resumes(current_user: CurrentUser = Depends(get_current_user)):
    return resume_builder.list_resumes(current_user.id)

@router.post("", response_model=ResumeResponse, status_code=201)
def create_resume(payload: ResumeCreate, current_user: CurrentUser = Depends(get_current_user)):
    return resume_builder.create_resume(current_user.id, payload.target_role, payload.title, payload.template, current_user.email)

@router.get("/{resume_id}", response_model=ResumeResponse)
def get_resume(resume_id: str, current_user: CurrentUser = Depends(get_current_user)):
    return resume_builder.get_resume(current_user.id, resume_id)

@router.patch("/{resume_id}", response_model=ResumeResponse)
def update_resume(resume_id: str, payload: ResumeUpdate, current_user: CurrentUser = Depends(get_current_user)):
    return resume_builder.update_resume(current_user.id, resume_id, {k: v for k, v in payload.model_dump().items() if v is not None})

@router.delete("/{resume_id}", status_code=204)
def delete_resume(resume_id: str, current_user: CurrentUser = Depends(get_current_user)):
    resume_builder.get_resume(current_user.id, resume_id)
    resume_builder._client().table(resume_builder.TABLE).delete().eq("user_id", current_user.id).eq("id", resume_id).execute()

@router.post("/{resume_id}/verify")
def verify_resume(resume_id: str, current_user: CurrentUser = Depends(get_current_user)):
    resume = resume_builder.get_resume(current_user.id, resume_id)
    snapshot = resume_builder.build_evidence_snapshot(current_user.id, resume["target_role"])
    return resume_builder.verify_content(resume["content"], resume["claims"], snapshot)

@router.get("/{resume_id}/latex", response_class=PlainTextResponse)
def export_latex(resume_id: str, current_user: CurrentUser = Depends(get_current_user)):
    resume = resume_builder.get_resume(current_user.id, resume_id)
    snapshot = resume_builder.build_evidence_snapshot(current_user.id, resume["target_role"])
    resume_builder.validate_resume_content(resume.get("content"), snapshot)
    return PlainTextResponse(resume_builder.to_latex(resume), media_type="application/x-tex")
