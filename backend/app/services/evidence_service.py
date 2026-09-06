from fastapi import HTTPException, UploadFile
from supabase import Client
from typing import List, Optional
from datetime import datetime, timezone
import uuid
import re
from ..core.supabase import get_supabase_client

BUCKET = "user-evidence"
EVIDENCE_TABLE = "evidence"
PROJECTS_TABLE = "projects"
CERTS_TABLE = "certifications"

ALLOWED_FILE_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
ALLOWED_EXTS = {".pdf", ".doc", ".docx"}
MAX_SIZE = 10 * 1024 * 1024  # 10 MB


def _client() -> Client:
    c = get_supabase_client()
    if c is None:
        raise HTTPException(status_code=503, detail="Supabase not configured — set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
    return c


# Evidence
def list_evidence(user_id: str) -> List[dict]:
    c = _client()
    try:
        r = c.table(EVIDENCE_TABLE).select("*").eq("user_id", user_id).order("created_at").execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "permission denied" in m or "does not exist" in m or "relation" in m or "could not find the table" in m or "pgrst205" in m or "schema cache" in m:
            raise HTTPException(status_code=503, detail="Evidence tables not found or permission denied — run backend/supabase/002_create_evidence.sql in Supabase SQL Editor")
        raise HTTPException(status_code=500, detail="Failed to list evidence")


def get_evidence(user_id: str, evidence_id: str) -> dict:
    c = _client()
    try:
        r = c.table(EVIDENCE_TABLE).select("*").eq("user_id", user_id).eq("id", evidence_id).single().execute()
        if r.data:
            return r.data
        raise HTTPException(status_code=404, detail="Evidence not found")
    except HTTPException:
        raise
    except Exception as e:
        m = str(e).lower()
        if "no rows" in m or "not found" in m:
            raise HTTPException(status_code=404, detail="Evidence not found")
        if "permission denied" in m:
            raise HTTPException(status_code=503, detail="Database permission denied")
        raise HTTPException(status_code=500, detail="Failed to fetch evidence")


def create_evidence(user_id: str, payload: dict) -> dict:
    c = _client()
    data = {
        "user_id": user_id,
        "evidence_type": payload["evidence_type"],
        "source_url": payload.get("source_url"),
        "file_path": payload.get("file_path"),
        "title": payload.get("title"),
        "metadata": payload.get("metadata") or {},
    }
    # For URL types, require source_url; for file types, file_path will be set after upload but allow creation with just type
    try:
        r = c.table(EVIDENCE_TABLE).insert(data).execute()
        if r.data and len(r.data) > 0:
            return r.data[0]
        return data
    except Exception as e:
        if "permission denied" in str(e).lower():
            raise HTTPException(status_code=503, detail="Database permission denied — run GRANTs")
        raise HTTPException(status_code=500, detail=f"Failed to create evidence: {str(e)[:200]}")


def update_evidence(user_id: str, evidence_id: str, payload: dict) -> dict:
    existing = get_evidence(user_id, evidence_id)
    merged = {**existing, **{k: v for k, v in payload.items() if v is not None}}
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    c = _client()
    try:
        r = c.table(EVIDENCE_TABLE).update(merged).eq("user_id", user_id).eq("id", evidence_id).execute()
        if r.data and len(r.data) > 0:
            return r.data[0]
        return merged
    except Exception as e:
        if "permission denied" in str(e).lower():
            raise HTTPException(status_code=503, detail="Database permission denied")
        raise HTTPException(status_code=500, detail="Failed to update evidence")


def delete_evidence(user_id: str, evidence_id: str):
    # Also delete file from storage if exists
    ev = get_evidence(user_id, evidence_id)
    c = _client()
    # Delete file from storage if file_path exists
    if ev.get("file_path"):
        try:
            c.storage.from_(BUCKET).remove([ev["file_path"].replace(f"{BUCKET}/", "") if ev["file_path"].startswith(f"{BUCKET}/") else ev["file_path"]])
            # Try alternative path format: user_id/... without bucket prefix
            # Supabase storage remove expects path without bucket
            # Our file_path is stored as "user_id/type/uuid.pdf" — use as is
            pass
        except Exception:
            pass  # don't fail delete if storage remove fails
        # Attempt correct removal
        try:
            # file_path stored as "user_id/type/filename" — remove that
            path = ev["file_path"]
            # If it starts with bucket prefix, strip
            if path.startswith(f"{BUCKET}/"):
                path = path[len(f"{BUCKET}/"):]
            c.storage.from_(BUCKET).remove([path])
        except Exception:
            pass

    try:
        c.table(EVIDENCE_TABLE).delete().eq("user_id", user_id).eq("id", evidence_id).execute()
    except Exception as e:
        if "permission denied" in str(e).lower():
            raise HTTPException(status_code=503, detail="Database permission denied")
        raise HTTPException(status_code=500, detail="Failed to delete evidence")


# File upload helper
async def upload_file(user_id: str, evidence_type: str, file: UploadFile) -> str:
    if file.content_type not in ALLOWED_FILE_TYPES:
        # also check extension
        ext = "." + (file.filename or "").split(".")[-1].lower() if file.filename and "." in file.filename else ""
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=400, detail="Invalid file type. Allowed: PDF, DOC, DOCX")
    # Check size by reading
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Max 10 MB")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Determine extension
    ext = ALLOWED_FILE_TYPES.get(file.content_type or "", "")
    if not ext and file.filename and "." in file.filename:
        ext = "." + file.filename.split(".")[-1].lower()
        if ext not in ALLOWED_EXTS:
            ext = ".pdf"
    if not ext:
        ext = ".pdf"

    filename = f"{uuid.uuid4().hex}{ext}"
    # Path: user_id/evidence_type/filename — RLS expects foldername = user_id
    storage_path = f"{user_id}/{evidence_type}/{filename}"

    c = _client()
    try:
        # Supabase storage upload expects bytes
        # Use storage.from_(BUCKET).upload(path, content)
        c.storage.from_(BUCKET).upload(storage_path, content, {"content-type": file.content_type or "application/pdf"})
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg or "duplicate" in msg:
            # Overwrite
            try:
                c.storage.from_(BUCKET).update(storage_path, content, {"content-type": file.content_type or "application/pdf"})
            except Exception as e2:
                raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e2)[:200]}")
        elif "bucket not found" in msg or "not found" in msg:
            raise HTTPException(status_code=503, detail="Storage bucket 'user-evidence' not found — run backend/supabase/002_create_evidence.sql")
        else:
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)[:200]}")

    return storage_path


# Projects
def list_projects(user_id: str) -> List[dict]:
    c = _client()
    try:
        r = c.table(PROJECTS_TABLE).select("*").eq("user_id", user_id).order("created_at").execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "permission denied" in m or "does not exist" in m or "relation" in m or "could not find the table" in m or "pgrst205" in m or "schema cache" in m:
            raise HTTPException(status_code=503, detail="Projects table not found or permission denied — run backend/supabase/002_create_evidence.sql")
        raise HTTPException(status_code=500, detail="Failed to list projects")


def create_project(user_id: str, payload: dict) -> dict:
    c = _client()
    data = {"user_id": user_id, **payload}
    try:
        r = c.table(PROJECTS_TABLE).insert(data).execute()
        if r.data and len(r.data) > 0:
            return r.data[0]
        return data
    except Exception as e:
        if "permission denied" in str(e).lower():
            raise HTTPException(status_code=503, detail="Database permission denied")
        raise HTTPException(status_code=500, detail=f"Failed to create project: {str(e)[:200]}")


def delete_project(user_id: str, project_id: str):
    c = _client()
    # verify exists
    try:
        r = c.table(PROJECTS_TABLE).select("*").eq("user_id", user_id).eq("id", project_id).single().execute()
        if not r.data:
            raise HTTPException(status_code=404, detail="Project not found")
    except HTTPException:
        raise
    except Exception as e:
        if "no rows" in str(e).lower():
            raise HTTPException(status_code=404, detail="Project not found")
        raise HTTPException(status_code=500, detail="Failed to fetch project")
    try:
        c.table(PROJECTS_TABLE).delete().eq("user_id", user_id).eq("id", project_id).execute()
    except Exception as e:
        if "permission denied" in str(e).lower():
            raise HTTPException(status_code=503, detail="Database permission denied")
        raise HTTPException(status_code=500, detail="Failed to delete project")


# Certifications
def list_certs(user_id: str) -> List[dict]:
    c = _client()
    try:
        r = c.table(CERTS_TABLE).select("*").eq("user_id", user_id).order("created_at").execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "permission denied" in m or "does not exist" in m or "relation" in m or "could not find the table" in m or "pgrst205" in m or "schema cache" in m:
            raise HTTPException(status_code=503, detail="Certifications table not found or permission denied — run backend/supabase/002_create_evidence.sql")
        raise HTTPException(status_code=500, detail="Failed to list certifications")


def create_cert(user_id: str, payload: dict) -> dict:
    c = _client()
    data = {"user_id": user_id, **payload}
    try:
        r = c.table(CERTS_TABLE).insert(data).execute()
        if r.data and len(r.data) > 0:
            return r.data[0]
        return data
    except Exception as e:
        if "permission denied" in str(e).lower():
            raise HTTPException(status_code=503, detail="Database permission denied")
        raise HTTPException(status_code=500, detail=f"Failed to create certification: {str(e)[:200]}")


def delete_cert(user_id: str, cert_id: str):
    c = _client()
    try:
        r = c.table(CERTS_TABLE).select("*").eq("user_id", user_id).eq("id", cert_id).single().execute()
        if not r.data:
            raise HTTPException(status_code=404, detail="Certification not found")
    except HTTPException:
        raise
    except Exception as e:
        if "no rows" in str(e).lower():
            raise HTTPException(status_code=404, detail="Certification not found")
        raise HTTPException(status_code=500, detail="Failed to fetch certification")
    try:
        c.table(CERTS_TABLE).delete().eq("user_id", user_id).eq("id", cert_id).execute()
    except Exception as e:
        if "permission denied" in str(e).lower():
            raise HTTPException(status_code=503, detail="Database permission denied")
        raise HTTPException(status_code=500, detail="Failed to delete certification")
