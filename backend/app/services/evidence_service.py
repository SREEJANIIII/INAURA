from fastapi import HTTPException, UploadFile
from supabase import Client
from typing import List, Optional
from datetime import datetime, timezone
import uuid
import re

from ..core.supabase import get_supabase_client
from .evidence.manager import evidence_manager
from . import document_parser

BUCKET = "user-evidence"
EVIDENCE_TABLE = "evidence"
PROJECTS_TABLE = "projects"
CERTS_TABLE = "certifications"
FILE_TYPES = {"resume", "syllabus", "certification_file", "project_doc"}

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


def _enrich_evidence_row(row: dict) -> dict:
    """Ensure verification fields are cleanly populated, checking metadata fallback if table not yet migrated."""
    if not row:
        return row
    meta = row.get("metadata") or {}
    status = row.get("verification_status") or meta.get("verification_status", "unverified")
    msg = row.get("verification_message") or meta.get("verification_message")
    prov = row.get("provider") or meta.get("provider")
    v_at = row.get("verified_at") or meta.get("verified_at")
    return {
        **row,
        "verification_status": status,
        "verification_message": msg,
        "provider": prov,
        "verified_at": v_at,
    }


# Evidence
def list_evidence(user_id: str) -> List[dict]:
    c = _client()
    try:
        r = c.table(EVIDENCE_TABLE).select("*").eq("user_id", user_id).order("created_at").execute()
        return [_enrich_evidence_row(row) for row in (r.data or [])]
    except Exception as e:
        m = str(e).lower()
        if "permission denied" in m or "does not exist" in m or "relation" in m or "could not find the table" in m or "pgrst205" in m or "schema cache" in m:
            raise HTTPException(status_code=503, detail="Evidence tables not found or permission denied — run backend/supabase/002_create_evidence.sql")
        raise HTTPException(status_code=500, detail="Failed to list evidence")


def get_evidence(user_id: str, evidence_id: str) -> dict:
    c = _client()
    try:
        r = c.table(EVIDENCE_TABLE).select("*").eq("user_id", user_id).eq("id", evidence_id).single().execute()
        if r.data:
            return _enrich_evidence_row(r.data)
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
    meta = payload.get("metadata") or {}
    status = payload.get("verification_status", "unverified")
    data = {
        "user_id": user_id,
        "evidence_type": payload["evidence_type"],
        "source_url": payload.get("source_url"),
        "file_path": payload.get("file_path"),
        "title": payload.get("title"),
        "metadata": {
            **meta,
            "verification_status": status,
        },
    }
    # If columns exist in schema
    if "verification_status" in payload:
        data["verification_status"] = payload["verification_status"]
    if "verification_message" in payload:
        data["verification_message"] = payload["verification_message"]
    if "provider" in payload:
        data["provider"] = payload["provider"]

    try:
        r = c.table(EVIDENCE_TABLE).insert(data).execute()
        if r.data and len(r.data) > 0:
            return _enrich_evidence_row(r.data[0])
        return _enrich_evidence_row(data)
    except Exception as e:
        if "permission denied" in str(e).lower():
            raise HTTPException(status_code=503, detail="Database permission denied — run GRANTs")
        # Retry without direct verification columns if DB columns not yet added
        if "column" in str(e).lower() and ("verification" in str(e).lower() or "provider" in str(e).lower()):
            data.pop("verification_status", None)
            data.pop("verification_message", None)
            data.pop("provider", None)
            try:
                r2 = c.table(EVIDENCE_TABLE).insert(data).execute()
                if r2.data and len(r2.data) > 0:
                    return _enrich_evidence_row(r2.data[0])
                return _enrich_evidence_row(data)
            except Exception as e2:
                raise HTTPException(status_code=500, detail=f"Failed to create evidence: {str(e2)[:200]}")
        raise HTTPException(status_code=500, detail=f"Failed to create evidence: {str(e)[:200]}")


def update_evidence(user_id: str, evidence_id: str, payload: dict) -> dict:
    existing = get_evidence(user_id, evidence_id)
    merged = {**existing, **{k: v for k, v in payload.items() if v is not None}}
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    c = _client()
    try:
        r = c.table(EVIDENCE_TABLE).update(merged).eq("user_id", user_id).eq("id", evidence_id).execute()
        if r.data and len(r.data) > 0:
            return _enrich_evidence_row(r.data[0])
        return _enrich_evidence_row(merged)
    except Exception as e:
        if "permission denied" in str(e).lower():
            raise HTTPException(status_code=503, detail="Database permission denied")
        # Fallback if DB columns not present
        if "column" in str(e).lower() and ("verification" in str(e).lower() or "provider" in str(e).lower()):
            clean = {k: v for k, v in merged.items() if k not in ("verification_status", "verification_message", "provider", "verified_at")}
            try:
                r2 = c.table(EVIDENCE_TABLE).update(clean).eq("user_id", user_id).eq("id", evidence_id).execute()
                if r2.data and len(r2.data) > 0:
                    return _enrich_evidence_row(r2.data[0])
                return _enrich_evidence_row(merged)
            except Exception as e2:
                raise HTTPException(status_code=500, detail=f"Failed to update evidence: {str(e2)[:200]}")
        raise HTTPException(status_code=500, detail="Failed to update evidence")


async def verify_evidence_item(user_id: str, evidence_id: str) -> dict:
    """
    Independently inspect an evidence item using its provider.
    Updates verification status, message, verified_at, and saves verified signals in metadata.
    Enforces user ownership.
    """
    ev = get_evidence(user_id, evidence_id)
    result = await evidence_manager.verify_evidence(ev)

    now_iso = (result.verified_at or datetime.now(timezone.utc)).isoformat()
    meta = ev.get("metadata") or {}
    updated_meta = {
        **meta,
        "verification_status": result.status,
        "verification_message": result.message,
        "verified_at": now_iso,
        "provider": result.provider,
        "verified_signals": [s.to_dict() for s in result.signals],
        "inspection": result.raw_metadata,
        "profile": result.profile,
        "facts": result.facts,
        "warnings": result.warnings,
    }

    update_payload = {
        "metadata": updated_meta,
        "verification_status": result.status,
        "verification_message": result.message,
        "verified_at": now_iso,
        "provider": result.provider,
    }

    updated = update_evidence(user_id, evidence_id, update_payload)
    return {
        **updated,
        "detected_skills": [s.skill for s in result.signals],
        "facts": result.facts,
        "warnings": result.warnings,
    }


def delete_evidence(user_id: str, evidence_id: str):
    ev = get_evidence(user_id, evidence_id)
    c = _client()
    if ev.get("file_path"):
        try:
            path = ev["file_path"]
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
async def upload_file(user_id: str, evidence_type: str, file: UploadFile) -> tuple:
    """Upload file bytes to storage and extract document text.

    Returns (storage_path, doc_meta) where doc_meta is the
    signal_extractor-ready parsed document dict from document_parser.
    Never fails the upload because of a parse error — parse failures
    are reported via doc_meta["parse_status"] instead.
    """
    if file.content_type not in ALLOWED_FILE_TYPES:
        ext = "." + (file.filename or "").split(".")[-1].lower() if file.filename and "." in file.filename else ""
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=400, detail="Invalid file type. Allowed: PDF, DOC, DOCX")
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Max 10 MB")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    ext = ALLOWED_FILE_TYPES.get(file.content_type or "", "")
    if not ext and file.filename and "." in file.filename:
        ext = "." + file.filename.split(".")[-1].lower()
        if ext not in ALLOWED_EXTS:
            ext = ".pdf"
    if not ext:
        ext = ".pdf"

    filename = f"{uuid.uuid4().hex}{ext}"
    storage_path = f"{user_id}/{evidence_type}/{filename}"

    c = _client()
    try:
        c.storage.from_(BUCKET).upload(storage_path, content, {"content-type": file.content_type or "application/pdf"})
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg or "duplicate" in msg:
            try:
                c.storage.from_(BUCKET).update(storage_path, content, {"content-type": file.content_type or "application/pdf"})
            except Exception as e2:
                raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e2)[:200]}")
        elif "bucket not found" in msg or "not found" in msg:
            raise HTTPException(status_code=503, detail="Storage bucket 'user-evidence' not found — run 002_create_evidence.sql")
        else:
            raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)[:200]}")

    # Parse document text now (while bytes are in hand) so resume/
    # syllabus content is immediately usable by signal_extractor.
    try:
        doc_meta = document_parser.parse_document_bytes(
            content, filename=file.filename or filename, content_type=file.content_type
        )
    except Exception:
        doc_meta = {
            "parsed_text": "",
            "sections": {},
            "text_char_count": 0,
            "word_count": 0,
            "parser": "none",
            "parse_status": "failed",
            "parse_warning": "Parser crashed unexpectedly",
        }

    return storage_path, doc_meta


def download_file_bytes(user_id: str, storage_path: str) -> bytes:
    """Download raw file bytes from Supabase storage (enforces user isolation)."""
    if not storage_path or ".." in storage_path or storage_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")
    # Enforce user folder isolation unless path already scoped
    if not storage_path.startswith(f"{user_id}/"):
        raise HTTPException(status_code=404, detail="File not found")
    c = _client()
    try:
        data = c.storage.from_(BUCKET).download(storage_path)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not found in storage: {str(e)[:150]}")
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    # storage3 may return dict/response wrappers in some versions
    for attr in ("data", "content"):
        val = getattr(data, attr, None)
        if isinstance(val, (bytes, bytearray)):
            return bytes(val)
    if isinstance(data, dict) and isinstance(data.get("data"), (bytes, bytearray)):
        return bytes(data["data"])
    raise HTTPException(status_code=500, detail="Unexpected storage download format")


def reparse_evidence(user_id: str, evidence_id: str) -> dict:
    """Re-download a stored file and refresh its parsed_text/sections metadata.

    Used for resumes uploaded before text extraction existed, and as a
    manual retry when the first parse failed (e.g. scanned PDF).
    """
    ev = get_evidence(user_id, evidence_id)
    if (ev.get("evidence_type") or "") not in FILE_TYPES:
        raise HTTPException(status_code=400, detail="Only file evidence (resume, syllabus, ...) can be reparsed")
    file_path = ev.get("file_path")
    if not file_path:
        raise HTTPException(status_code=400, detail="Evidence has no stored file to reparse")
    # Strip bucket prefix if present
    path = file_path
    if path.startswith(f"{BUCKET}/"):
        path = path[len(f"{BUCKET}/"):]

    content = download_file_bytes(user_id, path)
    meta = ev.get("metadata") or {}
    filename = meta.get("original_filename") or ev.get("title") or path.split("/")[-1]
    doc_meta = document_parser.parse_document_bytes(
        content, filename=filename, content_type=meta.get("content_type")
    )
    updated_meta = {**meta, **doc_meta}
    return update_evidence(user_id, evidence_id, {"metadata": updated_meta})


def ensure_file_evidence_parsed(user_id: str, evidence_list: list) -> list:
    """Best-effort backfill: parse any file evidence missing parsed_text.

    Called by the analysis pipeline so old uploads still contribute skills.
    Never raises — parse/download failures are skipped silently.
    Mutates evidence_list items in place and returns it.
    """
    for ev in evidence_list or []:
        try:
            if (ev.get("evidence_type") or "") not in FILE_TYPES:
                continue
            meta = ev.get("metadata") or {}
            if (meta.get("parsed_text") or "").strip():
                continue
            if not ev.get("file_path") or not ev.get("id"):
                continue
            refreshed = reparse_evidence(user_id, ev["id"])
            ev["metadata"] = refreshed.get("metadata") or ev.get("metadata")
        except Exception:
            continue
    return evidence_list


# Projects
def list_projects(user_id: str) -> List[dict]:
    c = _client()
    try:
        r = c.table(PROJECTS_TABLE).select("*").eq("user_id", user_id).order("created_at").execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "permission denied" in m or "does not exist" in m or "relation" in m or "could not find the table" in m or "pgrst205" in m or "schema cache" in m:
            raise HTTPException(status_code=503, detail="Projects table not found or permission denied — run 002_create_evidence.sql")
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
        if "column" in str(e).lower() and "student_contribution" in str(e).lower():
            data_no_contrib = {k: v for k, v in data.items() if k != "student_contribution"}
            try:
                r2 = c.table(PROJECTS_TABLE).insert(data_no_contrib).execute()
                if r2.data and len(r2.data) > 0:
                    res = r2.data[0]
                    res["student_contribution"] = data.get("student_contribution")
                    return res
                return data
            except Exception as e2:
                raise HTTPException(status_code=500, detail=f"Failed to create project: {str(e2)[:200]}")
        raise HTTPException(status_code=500, detail=f"Failed to create project: {str(e)[:200]}")


def delete_project(user_id: str, project_id: str):
    c = _client()
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
            raise HTTPException(status_code=503, detail="Certifications table not found or permission denied — run 002_create_evidence.sql")
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
