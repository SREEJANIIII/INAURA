from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict


class NotionConnectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    authorization_url: str


class SyncedPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    page_id: str
    page_title: str
    page_url: str
    last_edited_time: Optional[str] = None
    content_summary: Optional[str] = None
    skills: List[str] = []
    headings: List[str] = []
    code_languages: List[str] = []
    word_count: int = 0
    extracted_evidence: List[Dict[str, Any]] = []
    is_excluded: bool = False


class NotionStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    connected: bool
    status: str = "disconnected"
    workspace_name: Optional[str] = None
    workspace_icon: Optional[str] = None
    workspace_id: Optional[str] = None
    bot_id: Optional[str] = None
    last_synced_at: Optional[str] = None
    synced_pages_count: int = 0
    evidence_count: int = 0
    synced_pages: List[SyncedPageResponse] = []


class NotionSyncResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: str
    pages_scanned: int = 0
    pages_with_evidence: int = 0
    evidence_count: int = 0
    skills_detected: List[str] = []
    last_synced_at: Optional[str] = None
    details: List[Dict[str, Any]] = []
    synced_pages: List[SyncedPageResponse] = []


class NotionDisconnectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status: str = "disconnected"
    message: str


class NotionPageExclusionRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    is_excluded: bool
