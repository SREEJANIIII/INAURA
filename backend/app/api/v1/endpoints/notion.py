import logging
import re
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from ....core.config import get_settings
from ....core.security import get_current_user, CurrentUser
from ....schemas.notion import (
    NotionConnectResponse,
    NotionStatusResponse,
    NotionSyncResponse,
    NotionDisconnectResponse,
    NotionPageExclusionRequest,
    SyncedPageResponse,
)
from ....services import notion_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["notion-integration"])


@router.get("/connect", response_model=NotionConnectResponse)
def connect_notion(current_user: CurrentUser = Depends(get_current_user)):
    """
    Generate a secure Notion OAuth 2.0 authorization URL for the authenticated INAURA user.
    Uses cryptographically signed state for CSRF protection.
    """
    auth_url = notion_service.get_notion_authorization_url(current_user.id)
    return NotionConnectResponse(authorization_url=auth_url)


@router.get("/callback")
async def notion_callback(
    code: Optional[str] = Query(None, description="Notion OAuth authorization code"),
    state: Optional[str] = Query(None, description="Cryptographic CSRF OAuth state"),
    error: Optional[str] = Query(None, description="Error reported by Notion OAuth"),
):
    """
    Handle Notion OAuth callback redirect.
    Validates state parameter, exchanges code for access token, encrypts token at rest,
    and returns user to INAURA frontend.
    """
    settings = get_settings()
    frontend_base = settings.frontend_url.rstrip("/")

    # Check if user denied permission or Notion reported an error
    if error:
        logger.warning("Notion OAuth authorization error: %r", error[:200])
        # Only a short code goes back into the address, never text someone else chose
        code_name = re.sub(r"[^a-z0-9_]", "", error.lower())[:40] or "unknown"
        return RedirectResponse(
            url=f"{frontend_base}/analysis?notion_error={code_name}#notion",
            status_code=303,
        )

    if not code or not state:
        logger.warning("Notion callback missing code or state parameter")
        return RedirectResponse(
            url=f"{frontend_base}/analysis?notion_error=missing_code_or_state#notion",
            status_code=303,
        )

    # Validate state and retrieve authenticated user_id
    try:
        user_id = notion_service.validate_oauth_state(state)
    except HTTPException as e:
        logger.warning(f"Invalid OAuth state during callback: {e.detail}")
        return RedirectResponse(
            url=f"{frontend_base}/analysis?notion_error=invalid_state#notion",
            status_code=303,
        )

    # Exchange code for access token
    try:
        token_data = await notion_service.exchange_code_for_token(code)
    except HTTPException as e:
        logger.error(f"Failed to exchange Notion code for token: {e.detail}")
        return RedirectResponse(
            url=f"{frontend_base}/analysis?notion_error=token_exchange_failed#notion",
            status_code=303,
        )

    access_token = token_data.get("access_token")
    if not access_token:
        return RedirectResponse(
            url=f"{frontend_base}/analysis?notion_error=missing_access_token#notion",
            status_code=303,
        )

    # Store encrypted integration record
    notion_service.save_integration(
        user_id=user_id,
        access_token=access_token,
        workspace_id=token_data.get("workspace_id"),
        workspace_name=token_data.get("workspace_name"),
        workspace_icon=token_data.get("workspace_icon"),
        bot_id=token_data.get("bot_id"),
        owner=token_data.get("owner"),
    )

    # Redirect user back to INAURA
    return RedirectResponse(
        url=f"{frontend_base}/analysis?notion=connected#notion",
        status_code=303,
    )


@router.get("/status", response_model=NotionStatusResponse)
def get_notion_status(current_user: CurrentUser = Depends(get_current_user)):
    """
    Get current Notion integration status for the authenticated user.
    Returns workspace info and sync metadata; never returns secrets or tokens.
    """
    return notion_service.get_status(current_user.id)


@router.get("/pages", response_model=List[SyncedPageResponse])
def get_notion_pages(current_user: CurrentUser = Depends(get_current_user)):
    """
    Get all synchronized Notion pages and their extracted skill evidence for the authenticated user.
    """
    return notion_service.get_synced_pages(current_user.id)


@router.post("/sync", response_model=NotionSyncResponse)
async def sync_notion(current_user: CurrentUser = Depends(get_current_user)):
    """
    Synchronize authorized Notion pages and databases, extracting technical
    skill evidence into INAURA's unified evidence layer.
    """
    result = await notion_service.sync_notion_content(current_user.id)
    return NotionSyncResponse(**result)


@router.patch("/pages/{page_id}/exclusion", response_model=SyncedPageResponse)
def set_notion_page_exclusion(
    page_id: str,
    payload: NotionPageExclusionRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Include/exclude a single Notion page from career-readiness scoring.
    Excluded pages stay visible as study links; their signals stop contributing
    to analysis. Raw page data is preserved.
    """
    updated = notion_service.set_page_excluded(current_user.id, page_id, payload.is_excluded)
    # Re-run analysis so readiness reflects the change immediately
    try:
        from ....services import analysis_service as _as
        from ....services.analysis_run_service import run_analysis
        state = _as.get_state(current_user.id)
        if state and state.get("target_role"):
            import asyncio
            asyncio.create_task(run_analysis(current_user.id, state["target_role"]))
    except Exception:
        pass
    return SyncedPageResponse(**updated)


@router.delete("/disconnect", response_model=NotionDisconnectResponse)
def disconnect_notion(current_user: CurrentUser = Depends(get_current_user)):
    """
    Disconnect Notion integration: removes stored token and Notion-derived evidence.
    Existing evidence from other sources (GitHub, projects, resume, etc.) remains untouched.
    """
    result = notion_service.disconnect(current_user.id)
    # Trigger re-analysis if user has an active target role
    try:
        from ....services import analysis_service as _as
        from ....services.analysis_run_service import run_analysis
        state = _as.get_state(current_user.id)
        if state and state.get("target_role"):
            import asyncio
            asyncio.create_task(run_analysis(current_user.id, state["target_role"]))
    except Exception:
        pass

    return NotionDisconnectResponse(**result)
