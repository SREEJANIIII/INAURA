from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from typing import Optional, List
import io

from ....schemas.ats import AtsTestResponse, AtsRoleOption
from ....services import ats_service
from ....services import evidence_service
from ....core.security import get_current_user, CurrentUser

router = APIRouter(prefix="/resume", tags=["resume"])


@router.get("/roles", response_model=List[AtsRoleOption])
def get_ats_roles(current_user: CurrentUser = Depends(get_current_user)):
    """Return all catalog roles with structured benchmark skills for ATS matching."""
    return ats_service.get_supported_ats_roles()


@router.get("/existing")
def list_user_existing_resumes(current_user: CurrentUser = Depends(get_current_user)):
    """Return list of previously uploaded .docx resume files from the user's evidence records."""
    all_evidence = evidence_service.list_evidence(current_user.id)
    resumes = []
    for ev in all_evidence:
        if (ev.get("evidence_type") or "").lower() == "resume":
            meta = ev.get("metadata") or {}
            orig_name = meta.get("original_filename") or ev.get("title") or ""
            if orig_name.lower().endswith(".docx"):
                resumes.append({
                    "id": ev.get("id"),
                    "title": ev.get("title") or orig_name or "Resume.docx",
                    "filename": orig_name or "resume.docx",
                    "created_at": ev.get("created_at"),
                    "file_path": ev.get("file_path"),
                    "has_parsed_text": bool(meta.get("parsed_text")),
                    "word_count": meta.get("word_count", 0),
                })
    return resumes


@router.post("/ats-test", response_model=AtsTestResponse)
async def test_resume_ats_endpoint(
    target_role: str = Form(..., description="Target job role (e.g. Software Engineer, Frontend Developer)"),
    job_description: Optional[str] = Form(None, description="Optional job description text to match against"),
    evidence_id: Optional[str] = Form(None, description="Optional existing evidence ID to test against"),
    file: Optional[UploadFile] = File(None, description="Resume file (Microsoft Word .docx only)"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Evaluate a resume against target job role requirements and return comprehensive ATS scores,
    keyword matches, structural analysis, action verb density, and optimization recommendations.
    Restricted to Microsoft Word (.docx) format only.
    """
    file_bytes: bytes = b""
    filename: str = "resume.docx"
    content_type: Optional[str] = None

    if file is not None and file.filename:
        filename = file.filename
        content_type = file.content_type
        if not filename.lower().endswith(".docx"):
            raise HTTPException(
                status_code=400,
                detail="Only Microsoft Word (.docx) files are supported for ATS testing. Please upload a .docx document."
            )
        file_bytes = await file.read()
    elif evidence_id:
        # Load from existing evidence
        all_evidence = evidence_service.list_evidence(current_user.id)
        ev = next((e for e in all_evidence if str(e.get("id")) == str(evidence_id)), None)
        if not ev:
            raise HTTPException(status_code=404, detail="Selected evidence record not found")
        
        meta = ev.get("metadata") or {}
        filename = meta.get("original_filename") or ev.get("title") or "resume.docx"
        content_type = meta.get("content_type")

        if not filename.lower().endswith(".docx"):
            raise HTTPException(
                status_code=400,
                detail="The selected resume is not a .docx file. Only Microsoft Word (.docx) documents are supported for ATS testing."
            )

        if ev.get("file_path"):
            # Download file from Supabase storage
            try:
                from ....core.supabase import get_supabase_client
                client = get_supabase_client()
                if client:
                    data = client.storage.from_("user-evidence").download(ev["file_path"])
                    if data:
                        file_bytes = data
            except Exception as ex:
                raise HTTPException(status_code=500, detail=f"Failed to retrieve stored resume file: {str(ex)}")

        if not file_bytes and meta.get("parsed_text"):
            file_bytes = meta["parsed_text"].encode("utf-8")

    if not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="Please provide a .docx resume file or select an existing uploaded .docx resume to test.",
        )

    return await ats_service.test_resume_ats(
        file_bytes=file_bytes,
        filename=filename,
        target_role=target_role,
        job_description=job_description,
        content_type=content_type,
    )
