"""P1.5: human review / approval workflow for P1.2 curriculum proposals.

Append-only human decision ledger (transition graph mirrors the outcome
service TRANSITIONS convention):

    PENDING_REVIEW -> APPROVED | REJECTED | DEFERRED
    DEFERRED       -> APPROVED | REJECTED | DEFERRED
    APPROVED       -> (terminal)
    REJECTED       -> (terminal)

Rules enforced here, deterministically:
  - proposal must exist in the live P1.2 projection for the given context
    (404 otherwise — reviews attach to real proposals, never phantoms);
  - REJECTED and DEFERRED require a reason; APPROVED reasons are optional;
  - reviewer is the authenticated caller (recorded, never spoofable via
    payload). Authorization limitation, documented: the repository has no
    institution-scoped admin role (employer owner/member is employer-scoped
    and does not cover institutions), so any authenticated user may record a
    decision; fine-grained institutional RBAC is deferred, not invented here.
  - APPROVAL NEVER IMPLEMENTS: this module writes only review rows. Nothing
    here touches course_skills, course_modules, or any curriculum table
    (statically asserted in tests).

Current status of a proposal = latest decision row, or PENDING_REVIEW when
no rows exist. Concurrent decisions append rows; latest timestamp wins, and
both rows remain visible in history (no silent overwrites).
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from supabase import Client

from ..core.supabase import get_supabase_client
from . import curriculum_proposal_service as prop_svc

ENGINE_VERSION = "proposal-review-v1"

STATUS_PENDING = "PENDING_REVIEW"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_DEFERRED = "DEFERRED"

TABLE = "curriculum_proposal_reviews"
TABLES_MIGRATION_HINT = "Proposal review tables missing — run backend/supabase/033_curriculum_proposal_reviews.sql"

# Explicit transition graph. Terminal states have no outbound edges; there is
# deliberately no path back to PENDING_REVIEW and no REJECTED -> IMPLEMENTED
# (no IMPLEMENTED state exists: approval is not implementation).
TRANSITIONS: Dict[str, Dict[str, None]] = {
    STATUS_PENDING: {STATUS_APPROVED: None, STATUS_REJECTED: None, STATUS_DEFERRED: None},
    STATUS_DEFERRED: {STATUS_APPROVED: None, STATUS_REJECTED: None, STATUS_DEFERRED: None},
    STATUS_APPROVED: {},
    STATUS_REJECTED: {},
}
TERMINAL = {STATUS_APPROVED, STATUS_REJECTED}


def _ensure_client() -> Client:
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured — set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env",
        )
    return client


def _table_missing_msg(e: Exception) -> bool:
    m = str(e).lower()
    return "could not find table" in m or "pgrst205" in m


def _missing_table() -> HTTPException:
    return HTTPException(status_code=503, detail=TABLES_MIGRATION_HINT)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_proposal(proposal_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a proposal against the live P1.2 projection (404 on phantom)."""
    try:
        full = prop_svc.get_curriculum_proposals(**context)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail=f"No proposal {proposal_id!r} in this context")
        raise
    for p in full.get("proposals") or []:
        if p.get("proposal_id") == proposal_id:
            return p
    raise HTTPException(status_code=404, detail=f"No proposal {proposal_id!r} in this context")


def _history(client: Client, proposal_id: str) -> List[Dict[str, Any]]:
    try:
        resp = (client.table(TABLE).select("*").eq("proposal_id", proposal_id)
                .order("created_at").execute())
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to load review history")
    rows = resp.data or []
    rows.sort(key=lambda r: str(r.get("created_at") or ""))
    return rows


def current_status(history: List[Dict[str, Any]]) -> str:
    """Latest decision wins; no rows means PENDING_REVIEW."""
    if not history:
        return STATUS_PENDING
    return str(history[-1].get("to_status") or STATUS_PENDING)


def create_review(user_id: str, proposal_id: str, district: str, role: str,
                  decision: str, reason: Optional[str] = None, **context) -> Dict[str, Any]:
    """Record one human decision. Appends a row; never updates history."""
    if not user_id or not str(user_id).strip():
        raise HTTPException(status_code=401, detail="Not authenticated")
    decision = str(decision or "").strip().upper()
    if decision not in (STATUS_APPROVED, STATUS_REJECTED, STATUS_DEFERRED):
        raise HTTPException(status_code=400, detail=f"Invalid decision: {decision!r}")
    if decision in (STATUS_REJECTED, STATUS_DEFERRED) and not (reason or "").strip():
        raise HTTPException(status_code=400, detail=f"A reason is required for {decision}")
    full_context = {"district": district, "role": role, **(context or {})}
    proposal = _find_proposal(str(proposal_id), full_context)

    client = _ensure_client()
    history = _history(client, str(proposal_id))
    current = current_status(history)
    if decision not in TRANSITIONS.get(current, {}):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid transition {current} -> {decision}")
    row = {
        "proposal_id": str(proposal_id),
        "district": str(proposal.get("district") or district),
        "role": str(proposal.get("role") or role),
        "course_id": proposal.get("course_id"),
        "institution_id": proposal.get("institution_id"),
        "skill_slug": (proposal.get("skill") or {}).get("id"),
        "action_type": (proposal.get("action") or {}).get("type"),
        "reviewer_id": str(user_id),
        "from_status": None if current == STATUS_PENDING else current,
        "to_status": decision,
        "reason": (reason or "").strip() or None,
        "created_at": _now(),
    }
    try:
        resp = client.table(TABLE).insert(row).execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail=f"Failed to record review: {str(e)[:200]}")
    created = (resp.data or [None])[0]
    if not created:
        raise HTTPException(status_code=500, detail="Failed to record review")
    created["current_status"] = decision
    return created


def list_reviews(proposal_id: Optional[str] = None, course_id: Optional[str] = None,
                 district: Optional[str] = None,
                 decision: Optional[str] = None) -> List[Dict[str, Any]]:
    """Review history reads (newest last in storage order; callers sort)."""
    if decision is not None and str(decision).upper() not in (
            STATUS_APPROVED, STATUS_REJECTED, STATUS_DEFERRED):
        raise HTTPException(status_code=400, detail=f"Invalid decision filter: {decision!r}")
    client = _ensure_client()
    try:
        query = client.table(TABLE).select("*")
        if proposal_id:
            query = query.eq("proposal_id", str(proposal_id))
        if course_id:
            query = query.eq("course_id", str(course_id))
        if district:
            query = query.eq("district", str(district))
        if decision:
            query = query.eq("to_status", str(decision).upper())
        resp = query.order("created_at").execute()
    except Exception as e:
        if _table_missing_msg(e):
            raise _missing_table()
        raise HTTPException(status_code=500, detail="Failed to list reviews")
    return resp.data or []


def get_proposal_status(proposal_id: str, district: str, role: str, **context) -> Dict[str, Any]:
    """Current review status + full append-only history for one proposal."""
    full_context = {"district": district, "role": role, **(context or {})}
    proposal = _find_proposal(str(proposal_id), full_context)
    client = _ensure_client()
    history = _history(client, str(proposal_id))
    return {"proposal_id": str(proposal_id),
            "course_id": proposal.get("course_id"),
            "current_status": current_status(history),
            "decisions": len(history),
            "history": history,
            "proposal": {"title": proposal.get("title"),
                         "action_type": (proposal.get("action") or {}).get("type"),
                         "skill": proposal.get("skill")}}
