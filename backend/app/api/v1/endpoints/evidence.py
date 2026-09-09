from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional
import json
from ....schemas.evidence import (
    EvidenceCreate,
    EvidenceUpdate,
    EvidenceResponse,
    ProjectCreate,
    ProjectResponse,
    CertCreate,
    CertResponse,
)
from ....services import evidence_service
from ....core.security import get_current_user, CurrentUser

router = APIRouter(prefix="/evidence", tags=["evidence"])

# Generic evidence
@router.get("", response_model=list[EvidenceResponse])
async def list_evidence(current_user: CurrentUser = Depends(get_current_user)):
    return evidence_service.list_evidence(current_user.id)


@router.post("", response_model=EvidenceResponse, status_code=201)
async def create_evidence(
    payload: EvidenceCreate, current_user: CurrentUser = Depends(get_current_user)
):
    return evidence_service.create_evidence(current_user.id, payload.model_dump())


@router.put("/{evidence_id}", response_model=EvidenceResponse)
async def update_evidence(
    evidence_id: str,
    payload: EvidenceUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    clean = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not clean:
        raise HTTPException(status_code=400, detail="No fields to update")
    return evidence_service.update_evidence(current_user.id, evidence_id, clean)


@router.delete("/{evidence_id}", status_code=204)
async def delete_evidence(
    evidence_id: str, current_user: CurrentUser = Depends(get_current_user)
):
    evidence_service.delete_evidence(current_user.id, evidence_id)
    return None


@router.post("/{evidence_id}/verify")
async def verify_evidence(
    evidence_id: str, current_user: CurrentUser = Depends(get_current_user)
):
    """
    Independently inspect and verify an evidence item (e.g., GitHub repository).
    Enforces user isolation and returns verified technical facts and detected skills.
    """
    return await evidence_service.verify_evidence_item(current_user.id, evidence_id)



# File upload -> storage + evidence record
@router.post("/upload", response_model=EvidenceResponse, status_code=201)
async def upload_evidence_file(
    evidence_type: str = Form(..., description="resume|syllabus|certification_file|project_doc"),
    title: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
):
    allowed = {"resume", "syllabus", "certification_file", "project_doc"}
    if evidence_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid evidence_type for upload. Allowed: {', '.join(allowed)}")
    # Upload to storage
    storage_path = await evidence_service.upload_file(current_user.id, evidence_type, file)
    # Create evidence record
    payload = {
        "evidence_type": evidence_type,
        "source_url": None,
        "file_path": storage_path,
        "title": title or file.filename,
        "metadata": {"original_filename": file.filename, "content_type": file.content_type},
    }
    return evidence_service.create_evidence(current_user.id, payload)


# Projects
@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(current_user: CurrentUser = Depends(get_current_user)):
    return evidence_service.list_projects(current_user.id)


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    payload: ProjectCreate, current_user: CurrentUser = Depends(get_current_user)
):
    return evidence_service.create_project(current_user.id, payload.model_dump())


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str, current_user: CurrentUser = Depends(get_current_user)
):
    evidence_service.delete_project(current_user.id, project_id)
    return None


# Certifications
@router.get("/certifications", response_model=list[CertResponse])
async def list_certs(current_user: CurrentUser = Depends(get_current_user)):
    return evidence_service.list_certs(current_user.id)


@router.post("/certifications", response_model=CertResponse, status_code=201)
async def create_cert(
    payload: CertCreate, current_user: CurrentUser = Depends(get_current_user)
):
    return evidence_service.create_cert(current_user.id, payload.model_dump())


@router.delete("/certifications/{cert_id}", status_code=204)
async def delete_cert(
    cert_id: str, current_user: CurrentUser = Depends(get_current_user)
):
    evidence_service.delete_cert(current_user.id, cert_id)
    return None


# Summary — convenience for frontend
@router.get("/summary")
async def evidence_summary(current_user: CurrentUser = Depends(get_current_user)):
    evidence = evidence_service.list_evidence(current_user.id)
    projects = evidence_service.list_projects(current_user.id)
    certs = evidence_service.list_certs(current_user.id)

    # 9 sources as per spec
    all_types = ["github", "leetcode", "codeforces", "kaggle", "linkedin", "resume", "syllabus", "certification_file", "project_doc"]
    # For count, we consider distinct evidence_type present + projects count? Spec says 9 sources: 5 URLs + resume, syllabus, projects, certifications
    # We'll count: URL types + file types + projects (if any) + certs (if any) as separate? Simpler: count distinct evidence_type + projects>0 + certs>0
    present = set(e["evidence_type"] for e in evidence)
    # Add project/cert file types already in present, but also count projects/certs as separate sources
    # Actually spec's 9: github, leetcode, codeforces, kaggle, linkedin, resume, projects, certifications, syllabus
    # So map: evidence types for URLs + resume/syllabus, plus projects presence, plus certs presence
    count = len(present)
    # If projects exist, ensure counted (if not already via project_doc)
    has_project_doc = "project_doc" in present
    has_cert_file = "certification_file" in present
    # Count projects/certifications as distinct if they exist even without file evidence? Spec lists projects/certifications as manual, so count them
    if projects and not has_project_doc:
        count += 1
        present.add("projects")
    if certs and not has_cert_file:
        # certifications counted separately from cert file? But spec says certifications as source
        # We'll count certs as one if not already
        if "certification_file" not in present:
            count += 1
            present.add("certifications")
    # Ensure max 9
    count = min(count, 9)

    return {
        "total_sources": 9,
        "provided": count,
        "evidence": evidence,
        "projects": projects,
        "certifications": certs,
    }
