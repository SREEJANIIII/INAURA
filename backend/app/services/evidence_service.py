from fastapi import HTTPException, UploadFile
from supabase import Client
from typing import List, Optional, Dict
from datetime import datetime, timezone
import uuid
import re

from ..core.supabase import get_supabase_client
from .evidence.base import EVIDENCE_PIPELINE_VERSION, VerificationStatus
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
    is_excluded = row.get("is_excluded") if "is_excluded" in row else meta.get("is_excluded", False)
    is_ai = row.get("is_ai_assisted") if "is_ai_assisted" in row else meta.get("is_ai_assisted", False)
    # Normalize booleans
    is_excluded = bool(is_excluded) if is_excluded is not None else False
    is_ai = bool(is_ai) if is_ai is not None else False
    return {
        **row,
        "verification_status": status,
        "verification_message": msg,
        "provider": prov,
        "verified_at": v_at,
        "is_excluded": is_excluded,
        "is_ai_assisted": is_ai,
    }


def _enrich_project_row(row: dict) -> dict:
    if not row:
        return row
    meta = row.get("metadata") or {}
    is_ex = row.get("is_excluded") if "is_excluded" in row else meta.get("is_excluded", False)
    is_ai = row.get("is_ai_assisted") if "is_ai_assisted" in row else meta.get("is_ai_assisted", False)
    return {**row, "is_excluded": bool(is_ex) if is_ex is not None else False, "is_ai_assisted": bool(is_ai) if is_ai is not None else False}


def _enrich_cert_row(row: dict) -> dict:
    if not row:
        return row
    meta = row.get("metadata") or {}
    is_ex = row.get("is_excluded") if "is_excluded" in row else meta.get("is_excluded", False)
    return {**row, "is_excluded": bool(is_ex) if is_ex is not None else False}


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


def set_evidence_excluded(user_id: str, evidence_id: str, is_excluded: bool) -> dict:
    ev = get_evidence(user_id, evidence_id)
    meta = ev.get("metadata") or {}
    # Try direct column, fallback to metadata
    c = _client()
    payload_col = {"is_excluded": bool(is_excluded), "metadata": {**meta, "is_excluded": bool(is_excluded)}}
    # Attempt column update
    try:
        r = c.table(EVIDENCE_TABLE).update(payload_col).eq("user_id", user_id).eq("id", evidence_id).execute()
        if r.data and len(r.data) > 0:
            return _enrich_evidence_row(r.data[0])
    except Exception as e:
        m = str(e).lower()
        if "column" in m and "is_excluded" in m:
            # Fallback to metadata only
            try:
                r2 = c.table(EVIDENCE_TABLE).update({"metadata": {**meta, "is_excluded": bool(is_excluded)}}).eq("user_id", user_id).eq("id", evidence_id).execute()
                if r2.data and len(r2.data) > 0:
                    return _enrich_evidence_row(r2.data[0])
            except Exception:
                pass
        else:
            # Try metadata fallback anyway
            try:
                r2 = c.table(EVIDENCE_TABLE).update({"metadata": {**meta, "is_excluded": bool(is_excluded)}}).eq("user_id", user_id).eq("id", evidence_id).execute()
                if r2.data and len(r2.data) > 0:
                    return _enrich_evidence_row(r2.data[0])
            except Exception:
                pass
    # Fallback: return enriched with flag
    return _enrich_evidence_row({**ev, "is_excluded": bool(is_excluded), "metadata": {**meta, "is_excluded": bool(is_excluded)}})


def set_evidence_ai_assisted(user_id: str, evidence_id: str, is_ai_assisted: bool) -> dict:
    ev = get_evidence(user_id, evidence_id)
    meta = ev.get("metadata") or {}
    c = _client()
    payload_col = {"is_ai_assisted": bool(is_ai_assisted), "metadata": {**meta, "is_ai_assisted": bool(is_ai_assisted)}}
    try:
        r = c.table(EVIDENCE_TABLE).update(payload_col).eq("user_id", user_id).eq("id", evidence_id).execute()
        if r.data and len(r.data) > 0:
            return _enrich_evidence_row(r.data[0])
    except Exception as e:
        m = str(e).lower()
        if "column" in m and "is_ai" in m:
            try:
                r2 = c.table(EVIDENCE_TABLE).update({"metadata": {**meta, "is_ai_assisted": bool(is_ai_assisted)}}).eq("user_id", user_id).eq("id", evidence_id).execute()
                if r2.data and len(r2.data) > 0:
                    return _enrich_evidence_row(r2.data[0])
            except Exception:
                pass
        else:
            try:
                r2 = c.table(EVIDENCE_TABLE).update({"metadata": {**meta, "is_ai_assisted": bool(is_ai_assisted)}}).eq("user_id", user_id).eq("id", evidence_id).execute()
                if r2.data and len(r2.data) > 0:
                    return _enrich_evidence_row(r2.data[0])
            except Exception:
                pass
    return _enrich_evidence_row({**ev, "is_ai_assisted": bool(is_ai_assisted), "metadata": {**meta, "is_ai_assisted": bool(is_ai_assisted)}})


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


async def verify_evidence_item(user_id: str, evidence_id: str, force_refresh: bool = False) -> dict:
    """
    Independently inspect an evidence item using its provider.
    Updates verification status, message, verified_at, and saves verified signals in metadata.
    Enforces user ownership.

    `force_refresh` bypasses the freshness cache — used when stored signals were
    produced by an older evidence pipeline version.
    """
    ev = get_evidence(user_id, evidence_id)
    result = await evidence_manager.verify_evidence(ev, force_refresh=force_refresh)

    now_iso = (result.verified_at or datetime.now(timezone.utc)).isoformat()
    meta = ev.get("metadata") or {}
    prior_signals = meta.get("verified_signals")
    had_prior_success = bool(prior_signals) and (
        meta.get("verification_status") in (VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_VERIFIED)
        or ev.get("verification_status") in (VerificationStatus.VERIFIED, VerificationStatus.PARTIALLY_VERIFIED)
    )

    if result.status == VerificationStatus.FAILED and had_prior_success:
        # A transient failure (rate limit, outage, network error) must not wipe
        # evidence that was successfully inspected before. Keep the previous
        # verification and record the failed attempt alongside it.
        updated_meta = {
            **meta,
            "last_verification_error": result.message,
            "last_verification_attempt_at": now_iso,
        }
        update_payload = {"metadata": updated_meta}
        updated = update_evidence(user_id, evidence_id, update_payload)
        return {
            **updated,
            "detected_skills": [
                s.get("skill") or s.get("canonical_name", "") for s in prior_signals
            ],
            "facts": meta.get("facts") or [],
            "warnings": (meta.get("warnings") or []) + [
                f"Re-verification failed; retained the previous successful inspection. {result.message}"
            ],
        }

    updated_meta = {
        **meta,
        "verification_status": result.status,
        "verification_message": result.message,
        "verified_at": now_iso,
        "provider": result.provider,
        "verified_signals": [s.to_dict() for s in result.signals],
        "evidence_pipeline_version": EVIDENCE_PIPELINE_VERSION,
        "inspection": result.raw_metadata,
        "profile": result.profile,
        "facts": result.facts,
        "warnings": result.warnings,
    }
    updated_meta.pop("last_verification_error", None)
    updated_meta.pop("last_verification_attempt_at", None)

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
        return [_enrich_project_row(row) for row in (r.data or [])]
    except Exception as e:
        m = str(e).lower()
        if "permission denied" in m or "does not exist" in m or "relation" in m or "could not find the table" in m or "pgrst205" in m or "schema cache" in m:
            raise HTTPException(status_code=503, detail="Projects table not found or permission denied — run 002_create_evidence.sql")
        raise HTTPException(status_code=500, detail="Failed to list projects")


def set_project_excluded(user_id: str, project_id: str, is_excluded: bool) -> dict:
    c = _client()
    # Fetch existing
    try:
        r0 = c.table(PROJECTS_TABLE).select("*").eq("user_id", user_id).eq("id", project_id).single().execute()
        existing = r0.data or {}
    except Exception:
        raise HTTPException(status_code=404, detail="Project not found")
    meta = existing.get("metadata") or {}
    payload = {"is_excluded": bool(is_excluded)}
    # Try column
    try:
        r = c.table(PROJECTS_TABLE).update(payload).eq("user_id", user_id).eq("id", project_id).execute()
        if r.data and len(r.data) > 0:
            return _enrich_project_row(r.data[0])
    except Exception as e:
        if "column" in str(e).lower() and "is_excluded" in str(e).lower():
            # fallback to metadata
            try:
                r2 = c.table(PROJECTS_TABLE).update({"metadata": {**meta, "is_excluded": bool(is_excluded)}}).eq("user_id", user_id).eq("id", project_id).execute()
                if r2.data and len(r2.data) > 0:
                    return _enrich_project_row(r2.data[0])
            except Exception:
                pass
        else:
            try:
                r2 = c.table(PROJECTS_TABLE).update({"metadata": {**meta, "is_excluded": bool(is_excluded)}}).eq("user_id", user_id).eq("id", project_id).execute()
                if r2.data and len(r2.data) > 0:
                    return _enrich_project_row(r2.data[0])
            except Exception:
                pass
    return _enrich_project_row({**existing, "is_excluded": bool(is_excluded)})


def set_project_ai_assisted(user_id: str, project_id: str, is_ai_assisted: bool) -> dict:
    c = _client()
    try:
        r0 = c.table(PROJECTS_TABLE).select("*").eq("user_id", user_id).eq("id", project_id).single().execute()
        existing = r0.data or {}
    except Exception:
        raise HTTPException(status_code=404, detail="Project not found")
    meta = existing.get("metadata") or {}
    payload = {"is_ai_assisted": bool(is_ai_assisted)}
    try:
        r = c.table(PROJECTS_TABLE).update(payload).eq("user_id", user_id).eq("id", project_id).execute()
        if r.data and len(r.data) > 0:
            return _enrich_project_row(r.data[0])
    except Exception as e:
        if "column" in str(e).lower():
            try:
                r2 = c.table(PROJECTS_TABLE).update({"metadata": {**meta, "is_ai_assisted": bool(is_ai_assisted)}}).eq("user_id", user_id).eq("id", project_id).execute()
                if r2.data and len(r2.data) > 0:
                    return _enrich_project_row(r2.data[0])
            except Exception:
                pass
        else:
            try:
                r2 = c.table(PROJECTS_TABLE).update({"metadata": {**meta, "is_ai_assisted": bool(is_ai_assisted)}}).eq("user_id", user_id).eq("id", project_id).execute()
                if r2.data and len(r2.data) > 0:
                    return _enrich_project_row(r2.data[0])
            except Exception:
                pass
    return _enrich_project_row({**existing, "is_ai_assisted": bool(is_ai_assisted)})


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
        return [_enrich_cert_row(row) for row in (r.data or [])]
    except Exception as e:
        m = str(e).lower()
        if "permission denied" in m or "does not exist" in m or "relation" in m or "could not find the table" in m or "pgrst205" in m or "schema cache" in m:
            raise HTTPException(status_code=503, detail="Certifications table not found or permission denied — run 002_create_evidence.sql")
        raise HTTPException(status_code=500, detail="Failed to list certifications")


def set_cert_excluded(user_id: str, cert_id: str, is_excluded: bool) -> dict:
    c = _client()
    try:
        r0 = c.table(CERTS_TABLE).select("*").eq("user_id", user_id).eq("id", cert_id).single().execute()
        existing = r0.data or {}
    except Exception:
        raise HTTPException(status_code=404, detail="Certification not found")
    meta = existing.get("metadata") or {}
    payload = {"is_excluded": bool(is_excluded)}
    try:
        r = c.table(CERTS_TABLE).update(payload).eq("user_id", user_id).eq("id", cert_id).execute()
        if r.data and len(r.data) > 0:
            return _enrich_cert_row(r.data[0])
    except Exception:
        try:
            r2 = c.table(CERTS_TABLE).update({"metadata": {**meta, "is_excluded": bool(is_excluded)}}).eq("user_id", user_id).eq("id", cert_id).execute()
            if r2.data and len(r2.data) > 0:
                return _enrich_cert_row(r2.data[0])
        except Exception:
            pass
    return _enrich_cert_row({**existing, "is_excluded": bool(is_excluded)})


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


# ---------------------------------------------------------------------------
# Skill overrides (downward personalization)
# ---------------------------------------------------------------------------
OVERRIDES_TABLE = "user_skill_overrides"


def list_skill_overrides(user_id: str) -> List[dict]:
    c = _client()
    try:
        r = c.table(OVERRIDES_TABLE).select("*").eq("user_id", user_id).execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m or "does not exist" in m:
            return []
        raise HTTPException(status_code=500, detail="Failed to list skill overrides")


def set_skill_override(user_id: str, skill: str, is_zero_override: bool = True) -> dict:
    from .skill_taxonomy import normalize_skill, normalize_skill_slug
    if not skill or not str(skill).strip():
        raise HTTPException(status_code=400, detail="Skill required")
    # Normalize to canonical
    canonical = normalize_skill(str(skill).strip()) or str(skill).strip()
    slug = normalize_skill_slug(str(skill).strip()) or canonical.lower().replace(" ", "_")
    if not is_zero_override:
        raise HTTPException(status_code=400, detail="Only downward override to 0% is allowed. Manual increase requires new evidence or assessment.")
    c = _client()
    now = datetime.now(timezone.utc).isoformat()
    # Upsert
    try:
        # Try insert, on conflict update
        existing = None
        try:
            r0 = c.table(OVERRIDES_TABLE).select("*").eq("user_id", user_id).eq("skill_key", slug).single().execute()
            existing = r0.data
        except Exception:
            existing = None
        if existing:
            r = c.table(OVERRIDES_TABLE).update({"is_zero_override": True, "skill_name": canonical, "updated_at": now}).eq("user_id", user_id).eq("skill_key", slug).execute()
            if r.data and len(r.data) > 0:
                return r.data[0]
            return {**existing, "is_zero_override": True}
        else:
            payload = {
                "user_id": user_id,
                "skill_name": canonical,
                "skill_key": slug,
                "is_zero_override": True,
                "created_at": now,
                "updated_at": now,
            }
            r = c.table(OVERRIDES_TABLE).insert(payload).execute()
            if r.data and len(r.data) > 0:
                return r.data[0]
            return payload
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Skill overrides table not found — run backend/supabase/013_evidence_provenance_and_personalization.sql")
        if "permission denied" in m:
            raise HTTPException(status_code=503, detail="Database permission denied for skill overrides")
        raise HTTPException(status_code=500, detail=f"Failed to set skill override: {str(e)[:200]}")


def delete_skill_override(user_id: str, skill: str) -> None:
    from .skill_taxonomy import normalize_skill_slug
    slug = normalize_skill_slug(str(skill).strip()) or str(skill).strip().lower().replace(" ", "_")
    c = _client()
    try:
        c.table(OVERRIDES_TABLE).delete().eq("user_id", user_id).eq("skill_key", slug).execute()
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            return
        raise HTTPException(status_code=500, detail="Failed to delete skill override")


# ---------------------------------------------------------------------------
# GitHub per-repository personalization
# ---------------------------------------------------------------------------
REPO_SETTINGS_TABLE = "user_github_repo_settings"


def list_github_repo_settings(user_id: str) -> List[dict]:
    c = _client()
    try:
        r = c.table(REPO_SETTINGS_TABLE).select("*").eq("user_id", user_id).execute()
        return r.data or []
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m or "does not exist" in m:
            return []
        raise HTTPException(status_code=500, detail="Failed to list repo settings")


def get_github_repo_settings_map(user_id: str) -> Dict[str, dict]:
    rows = list_github_repo_settings(user_id)
    out: Dict[str, dict] = {}
    for r in rows:
        key = str(r.get("repo_full_name") or "").lower()
        if key:
            out[key] = r
    return out


def set_github_repo_excluded(user_id: str, repo_full_name: str, is_excluded: bool) -> dict:
    if not repo_full_name or not str(repo_full_name).strip():
        raise HTTPException(status_code=400, detail="repo_full_name required")
    key = str(repo_full_name).strip().lower()
    c = _client()
    now = datetime.now(timezone.utc).isoformat()
    try:
        # Try fetch existing
        existing = None
        try:
            r0 = c.table(REPO_SETTINGS_TABLE).select("*").eq("user_id", user_id).eq("repo_full_name", key).single().execute()
            existing = r0.data
        except Exception:
            existing = None
        if existing:
            r = c.table(REPO_SETTINGS_TABLE).update({"is_excluded": bool(is_excluded), "updated_at": now}).eq("user_id", user_id).eq("repo_full_name", key).execute()
            if r.data and len(r.data) > 0:
                return r.data[0]
            return {**existing, "is_excluded": bool(is_excluded)}
        else:
            payload = {
                "user_id": user_id,
                "repo_full_name": key,
                "repo_url": f"https://github.com/{key}",
                "is_excluded": bool(is_excluded),
                "is_ai_assisted": False,
                "created_at": now,
                "updated_at": now,
            }
            r = c.table(REPO_SETTINGS_TABLE).insert(payload).execute()
            if r.data and len(r.data) > 0:
                return r.data[0]
            return payload
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Repo settings table not found — run 015_github_repo_personalization.sql")
        raise HTTPException(status_code=500, detail=f"Failed to set repo excluded: {str(e)[:200]}")


def set_github_repo_ai_assisted(user_id: str, repo_full_name: str, is_ai_assisted: bool) -> dict:
    if not repo_full_name or not str(repo_full_name).strip():
        raise HTTPException(status_code=400, detail="repo_full_name required")
    key = str(repo_full_name).strip().lower()
    c = _client()
    now = datetime.now(timezone.utc).isoformat()
    try:
        existing = None
        try:
            r0 = c.table(REPO_SETTINGS_TABLE).select("*").eq("user_id", user_id).eq("repo_full_name", key).single().execute()
            existing = r0.data
        except Exception:
            existing = None
        if existing:
            r = c.table(REPO_SETTINGS_TABLE).update({"is_ai_assisted": bool(is_ai_assisted), "updated_at": now}).eq("user_id", user_id).eq("repo_full_name", key).execute()
            if r.data and len(r.data) > 0:
                return r.data[0]
            return {**existing, "is_ai_assisted": bool(is_ai_assisted)}
        else:
            payload = {
                "user_id": user_id,
                "repo_full_name": key,
                "repo_url": f"https://github.com/{key}",
                "is_excluded": False,
                "is_ai_assisted": bool(is_ai_assisted),
                "created_at": now,
                "updated_at": now,
            }
            r = c.table(REPO_SETTINGS_TABLE).insert(payload).execute()
            if r.data and len(r.data) > 0:
                return r.data[0]
            return payload
    except Exception as e:
        m = str(e).lower()
        if "could not find the table" in m or "pgrst205" in m:
            raise HTTPException(status_code=503, detail="Repo settings table not found — run 015_github_repo_personalization.sql")
        raise HTTPException(status_code=500, detail=f"Failed to set repo AI: {str(e)[:200]}")


def adjust_github_signals_for_repo_settings(signals: List[dict], repo_settings: Dict[str, dict]) -> List[dict]:
    """
    Apply per-repo included/excluded and AI-assisted settings to aggregated GitHub signals.
    Each GitHub signal's metadata.repositories lists contributing repos for that skill.
    If a repo is excluded, it is removed from that skill's provenance. If all repos for a skill are excluded, the signal is dropped.
    AI-assisted repos halve the signal's reliability contribution (centralized heuristic).
    Returns new list (does not mutate input).
    """
    if not repo_settings:
        return signals
    adjusted: List[dict] = []
    for sig in signals:
        src_type = str(sig.get("source") or sig.get("source_type") or "").lower()
        if src_type != "github":
            adjusted.append(sig)
            continue
        meta = dict(sig.get("metadata") or {})
        repos = meta.get("repositories") or []
        if not isinstance(repos, list) or not repos:
            # No per-repo breakdown available (single-repo evidence), check single repo key
            # Try to find single repo name from meta
            single_key = str(meta.get("full_name") or meta.get("project_name") or "").lower()
            if single_key and single_key in repo_settings and repo_settings[single_key].get("is_excluded"):
                continue  # drop
            # AI check
            if single_key and repo_settings.get(single_key, {}).get("is_ai_assisted"):
                # halve reliability
                new_sig = dict(sig)
                new_sig["source_reliability"] = max(0.05, float(sig.get("source_reliability", 0.40)) * 0.5)
                new_meta = dict(meta)
                new_meta["is_ai_assisted"] = True
                new_sig["metadata"] = new_meta
                new_sig["is_ai_assisted"] = True
                adjusted.append(new_sig)
            else:
                adjusted.append(sig)
            continue
        # Multiple repos for this skill
        remaining = []
        ai_count = 0
        excluded_count = 0
        for repo in repos:
            r_key = str(repo.get("full_name") or repo.get("name") or "").lower()
            # Also try owner/name
            if not r_key and repo.get("owner"):
                # not needed
                pass
            settings = repo_settings.get(r_key) or {}
            if settings.get("is_excluded"):
                excluded_count += 1
                continue
            if settings.get("is_ai_assisted"):
                ai_count += 1
            remaining.append(repo)
        total = len(repos)
        if not remaining:
            # All repos excluded for this skill -> drop signal
            continue
        # Update metadata
        new_meta = dict(meta)
        new_meta["repositories"] = remaining
        new_meta["repo_count"] = len(remaining)
        new_meta["owned_count"] = len([r for r in remaining if not r.get("fork")])
        # Preserve original total for audit
        new_meta["original_repo_count"] = total
        new_meta["excluded_repo_count"] = excluded_count
        if ai_count:
            new_meta["ai_assisted_repo_count"] = ai_count
            new_meta["is_ai_assisted"] = True
        new_sig = dict(sig)
        new_sig["metadata"] = new_meta
        # Adjust reliability for AI: centralized heuristic, halve if any AI repo contributes
        if ai_count:
            # If all remaining are AI, halve; if mixed, reduce proportionally
            # Simple: halve reliability if any AI, else proportional
            ai_ratio = ai_count / len(remaining) if remaining else 0
            # Halve proportionally: reliability * (1 - 0.5*ai_ratio)
            # For single AI repo among 3, reduction 1 - 0.5*(1/3)=0.833
            # For all AI, reduction 0.5
            factor = 1.0 - 0.5 * ai_ratio
            new_sig["source_reliability"] = max(0.05, float(sig.get("source_reliability", 0.40)) * factor)
            new_sig["is_ai_assisted"] = True
        # Also if repos reduced, keep signal strength same (depth unchanged) but provenance updated
        adjusted.append(new_sig)
    return adjusted
