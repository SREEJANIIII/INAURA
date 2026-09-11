from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from pydantic import BaseModel
from typing import Optional
import json

class GithubRepoExcludeRequest(BaseModel):
    repo_full_name: str
    is_excluded: bool

class GithubRepoAiRequest(BaseModel):
    repo_full_name: str
    is_ai_assisted: bool
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

# ---------------------------------------------------------------------------
# Per-repository GitHub personalization (each repo independent)
# MUST be before dynamic /{evidence_id} routes — otherwise
# /github-repos/exclude is captured as evidence_id="github-repos" and
# raises 500 "Failed to fetch evidence" (invalid UUID).
# ---------------------------------------------------------------------------
@router.get("/github-repos")
async def list_github_repos(current_user: CurrentUser = Depends(get_current_user)):
    """
    List all discovered GitHub repositories for the current user with their personalization state.
    Each repo has independent included/excluded and AI-assisted flags. Defaults: included, not AI.
    Safe: skips malformed repository entries; never fails whole request for one bad repo.
    """
    evidence = evidence_service.list_evidence(current_user.id)
    repo_settings = evidence_service.get_github_repo_settings_map(current_user.id)
    repos_out = []
    for ev in evidence:
        try:
            if (ev.get("evidence_type") or "").lower() != "github":
                continue
            meta = ev.get("metadata") or {}
            if not isinstance(meta, dict):
                meta = {}
            raw = meta.get("inspection") or meta.get("raw_metadata") or {}
            if not isinstance(raw, dict):
                raw = {}
            # Try multiple possible locations for repositories list
            repos = raw.get("repositories") or meta.get("repositories") or []
            if not isinstance(repos, list):
                repos = []
            # Fallback: if evidence is single repo, synthesize
            if not repos and ev.get("source_url"):
                try:
                    from ...services.evidence.github import parse_github_url
                    owner, repo, is_profile = parse_github_url(ev.get("source_url") or "")
                    if repo and not is_profile:
                        repos = [{"name": repo, "full_name": f"{owner}/{repo}", "url": ev.get("source_url"), "html_url": ev.get("source_url")}]
                except Exception:
                    repos = []
            for r in repos or []:
                try:
                    if not isinstance(r, dict):
                        continue
                    full = str(r.get("full_name") or r.get("name") or "").strip().lower()
                    if not full:
                        continue
                    settings = repo_settings.get(full, {}) if isinstance(repo_settings, dict) else {}
                    # Safe defaults: is_excluded=false, is_ai_assisted=false when no settings row
                    is_excluded = bool(settings.get("is_excluded", False)) if isinstance(settings, dict) else False
                    is_ai_assisted = bool(settings.get("is_ai_assisted", False)) if isinstance(settings, dict) else False
                    repos_out.append({
                        "full_name": r.get("full_name") or r.get("name"),
                        "name": r.get("name"),
                        "url": r.get("url") or r.get("html_url"),
                        "html_url": r.get("html_url") or r.get("url"),
                        "is_excluded": is_excluded,
                        "is_ai_assisted": is_ai_assisted,
                        "classification": r.get("classification"),
                        "fork": bool(r.get("fork")) if r.get("fork") is not None else False,
                        "archived": bool(r.get("archived")) if r.get("archived") is not None else False,
                        "pushed_at": r.get("pushed_at"),
                        "evidence_id": ev.get("id"),
                    })
                except Exception:
                    continue
        except Exception:
            continue
    # Deduplicate by full_name (keep first)
    seen = {}
    for r in repos_out:
        try:
            key = str(r.get("full_name") or "").lower()
            if key and key not in seen:
                seen[key] = r
        except Exception:
            continue
    return list(seen.values())


@router.post("/github-repos/exclude")
async def set_github_repo_excluded(
    payload: GithubRepoExcludeRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    result = evidence_service.set_github_repo_excluded(current_user.id, payload.repo_full_name, payload.is_excluded)
    try:
        from ...services import analysis_service as _as
        from ...services.analysis_run_service import run_analysis
        state = _as.get_state(current_user.id)
        if state and state.get("target_role"):
            await run_analysis(current_user.id, state["target_role"])
    except Exception:
        pass
    return result


@router.post("/github-repos/ai-assisted")
async def set_github_repo_ai_assisted(
    payload: GithubRepoAiRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    result = evidence_service.set_github_repo_ai_assisted(current_user.id, payload.repo_full_name, payload.is_ai_assisted)
    try:
        from ...services import analysis_service as _as
        from ...services.analysis_run_service import run_analysis
        state = _as.get_state(current_user.id)
        if state and state.get("target_role"):
            await run_analysis(current_user.id, state["target_role"])
    except Exception:
        pass
    return result


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
    # Upload to storage + extract document text (resume content is parsed here)
    storage_path, doc_meta = await evidence_service.upload_file(current_user.id, evidence_type, file)
    # Create evidence record
    payload = {
        "evidence_type": evidence_type,
        "source_url": None,
        "file_path": storage_path,
        "title": title or file.filename,
        "metadata": {
            "original_filename": file.filename,
            "content_type": file.content_type,
            **doc_meta,
        },
    }
    return evidence_service.create_evidence(current_user.id, payload)


@router.post("/{evidence_id}/reparse", response_model=EvidenceResponse)
async def reparse_evidence_file(
    evidence_id: str, current_user: CurrentUser = Depends(get_current_user)
):
    """Re-download the stored file and refresh parsed_text/sections.

    Use for resumes uploaded before text extraction existed, or to retry
    a failed parse after re-uploading a text-based PDF/DOCX.
    """
    return evidence_service.reparse_evidence(current_user.id, evidence_id)


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


# Evidence personalization: exclusion & AI-assisted flag
@router.post("/{evidence_id}/exclude")
async def set_evidence_excluded(
    evidence_id: str,
    is_excluded: bool = Body(..., embed=True),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Exclude or include an evidence item from scoring.
    Preserves raw evidence, only toggles active scoring contribution.
    """
    result = evidence_service.set_evidence_excluded(current_user.id, evidence_id, is_excluded)
    # Recalculate affected skills/readiness/roadmap via existing engine
    try:
        from ...services import analysis_service as _as
        from ...services.analysis_run_service import run_analysis
        state = _as.get_state(current_user.id)
        if state and state.get("target_role"):
            await run_analysis(current_user.id, state["target_role"])
    except Exception:
        pass
    return result


@router.post("/{evidence_id}/ai-assisted")
async def set_evidence_ai_assisted(
    evidence_id: str,
    is_ai_assisted: bool = Body(..., embed=True),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Mark evidence as AI-assisted: retained but scoring contribution reduced via reliability.
    """
    result = evidence_service.set_evidence_ai_assisted(current_user.id, evidence_id, is_ai_assisted)
    try:
        from ...services import analysis_service as _as
        from ...services.analysis_run_service import run_analysis
        state = _as.get_state(current_user.id)
        if state and state.get("target_role"):
            await run_analysis(current_user.id, state["target_role"])
    except Exception:
        pass
    return result


@router.post("/projects/{project_id}/exclude")
async def set_project_excluded(
    project_id: str,
    is_excluded: bool = Body(..., embed=True),
    current_user: CurrentUser = Depends(get_current_user),
):
    result = evidence_service.set_project_excluded(current_user.id, project_id, is_excluded)
    try:
        from ...services import analysis_service as _as
        from ...services.analysis_run_service import run_analysis
        state = _as.get_state(current_user.id)
        if state and state.get("target_role"):
            await run_analysis(current_user.id, state["target_role"])
    except Exception:
        pass
    return result


@router.post("/projects/{project_id}/ai-assisted")
async def set_project_ai_assisted(
    project_id: str,
    is_ai_assisted: bool = Body(..., embed=True),
    current_user: CurrentUser = Depends(get_current_user),
):
    result = evidence_service.set_project_ai_assisted(current_user.id, project_id, is_ai_assisted)
    try:
        from ...services import analysis_service as _as
        from ...services.analysis_run_service import run_analysis
        state = _as.get_state(current_user.id)
        if state and state.get("target_role"):
            await run_analysis(current_user.id, state["target_role"])
    except Exception:
        pass
    return result


@router.post("/certifications/{cert_id}/exclude")
async def set_cert_excluded(
    cert_id: str,
    is_excluded: bool = Body(..., embed=True),
    current_user: CurrentUser = Depends(get_current_user),
):
    result = evidence_service.set_cert_excluded(current_user.id, cert_id, is_excluded)
    try:
        from ...services import analysis_service as _as
        from ...services.analysis_run_service import run_analysis
        state = _as.get_state(current_user.id)
        if state and state.get("target_role"):
            await run_analysis(current_user.id, state["target_role"])
    except Exception:
        pass
    return result



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
