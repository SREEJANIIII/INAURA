import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException
from supabase import Client

from ..core.config import get_settings
from ..core.encryption import encrypt_token, decrypt_token
from ..core.supabase import get_supabase_client
from .evidence.base import EVIDENCE_PIPELINE_VERSION, EvidenceDepth, VerificationStatus
from .evidence_weights import reliability as get_reliability
from .skill_taxonomy import normalize_skill, extract_known_skills_from_text

logger = logging.getLogger(__name__)

USER_INTEGRATIONS_TABLE = "user_integrations"
NOTION_SYNCED_PAGES_TABLE = "notion_synced_pages"
EVIDENCE_TABLE = "evidence"

NOTION_OAUTH_AUTHORIZE_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_OAUTH_TOKEN_URL = "https://api.notion.com/v1/oauth/token"
NOTION_API_BASE_URL = "https://api.notion.com/v1"
NOTION_API_VERSION = "2022-06-28"

# In-memory storage fallback for local development or unit testing without live Supabase
_memory_integrations: Dict[str, dict] = {}
_memory_synced_pages: Dict[str, List[dict]] = {}
_memory_evidence: Dict[str, List[dict]] = {}


def _client() -> Optional[Client]:
    return get_supabase_client()


def _get_signing_secret() -> bytes:
    settings = get_settings()
    raw = (
        settings.notion_client_secret
        or settings.supabase_jwt_secret
        or settings.notion_token_encryption_key
        or "inaura-notion-state-signing-secret"
    )
    return raw.encode("utf-8")


# ---------------------------------------------------------------------------
# Cryptographically Secure OAuth State Management (CSRF Protection)
# ---------------------------------------------------------------------------

def generate_oauth_state(user_id: str) -> str:
    """
    Generate a tamper-proof, time-bounded, cryptographically signed OAuth state
    associated with the authenticated INAURA user.
    """
    if not user_id or not str(user_id).strip():
        raise HTTPException(status_code=400, detail="Authenticated user_id required for OAuth state")

    nonce = secrets.token_urlsafe(16)
    exp = int(time.time()) + 600  # 10 minutes expiry
    payload_dict = {
        "user_id": str(user_id).strip(),
        "nonce": nonce,
        "exp": exp,
    }
    payload_json = json.dumps(payload_dict, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")

    secret = _get_signing_secret()
    sig = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")

    return f"{payload_b64}.{sig_b64}"


def validate_oauth_state(state: str) -> str:
    """
    Validate the OAuth state parameter against CSRF and tampering.
    Returns the verified user_id if valid, or raises HTTPException(400).
    Never trusts user input; verifies HMAC signature and expiration.
    """
    if not state or "." not in state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state parameter")

    parts = state.split(".", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Malformed OAuth state format")

    payload_b64, sig_b64 = parts
    secret = _get_signing_secret()

    # Verify signature
    expected_sig = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode("utf-8").rstrip("=")

    if not hmac.compare_digest(sig_b64, expected_sig_b64):
        raise HTTPException(status_code=400, detail="Invalid OAuth state signature")

    # Decode and check payload
    try:
        padded_payload = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(padded_payload.encode("utf-8")).decode("utf-8")
        payload = json.loads(payload_json)
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to decode OAuth state payload")

    exp = payload.get("exp")
    if not exp or not isinstance(exp, (int, float)):
        raise HTTPException(status_code=400, detail="Invalid OAuth state expiration")

    if time.time() > float(exp):
        raise HTTPException(status_code=400, detail="OAuth state has expired. Please try connecting again.")

    user_id = payload.get("user_id")
    if not user_id or not isinstance(user_id, str):
        raise HTTPException(status_code=400, detail="Invalid user_id in OAuth state")

    return user_id


# ---------------------------------------------------------------------------
# Notion OAuth URL & Token Exchange
# ---------------------------------------------------------------------------

def get_notion_authorization_url(user_id: str) -> str:
    """Construct Notion OAuth 2.0 authorization URL for the user."""
    settings = get_settings()
    client_id = settings.notion_client_id
    if not client_id:
        raise HTTPException(
            status_code=503,
            detail="Notion integration is not configured. Set NOTION_CLIENT_ID and NOTION_CLIENT_SECRET on the server.",
        )

    redirect_uri = settings.notion_redirect_uri
    state = generate_oauth_state(user_id)

    params = {
        "client_id": client_id,
        "response_type": "code",
        "owner": "user",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    encoded_params = httpx.QueryParams(params)
    return f"{NOTION_OAUTH_AUTHORIZE_URL}?{encoded_params}"


async def exchange_code_for_token(code: str) -> dict:
    """Exchange Notion OAuth authorization code for access token."""
    settings = get_settings()
    client_id = settings.notion_client_id
    client_secret = settings.notion_client_secret
    redirect_uri = settings.notion_redirect_uri

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail="Notion OAuth credentials not configured on the backend.",
        )

    auth_str = f"{client_id}:{client_secret}"
    basic_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

    headers = {
        "Authorization": f"Basic {basic_auth}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_API_VERSION,
    }
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(NOTION_OAUTH_TOKEN_URL, json=payload, headers=headers)
    except Exception as e:
        logger.error(f"Network error during Notion OAuth token exchange: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to Notion OAuth service: {str(e)}",
        )

    if resp.status_code != 200:
        err_body = resp.text
        logger.error(f"Notion token exchange failed ({resp.status_code}): {err_body}")
        raise HTTPException(
            status_code=400,
            detail=f"Notion authorization exchange failed: {resp.status_code} {err_body[:200]}",
        )

    return resp.json()


# ---------------------------------------------------------------------------
# Server-Side Storage with Encryption at Rest
# ---------------------------------------------------------------------------

def save_integration(
    user_id: str,
    access_token: str,
    workspace_id: Optional[str] = None,
    workspace_name: Optional[str] = None,
    workspace_icon: Optional[str] = None,
    bot_id: Optional[str] = None,
    owner: Optional[dict] = None,
) -> dict:
    """Encrypt Notion access token and store integration record server-side."""
    c = _client()
    now_iso = datetime.now(timezone.utc).isoformat()
    encrypted_token = encrypt_token(access_token)

    owner_user_id = None
    owner_user_name = None
    owner_user_email = None
    if isinstance(owner, dict):
        user_info = owner.get("user") or {}
        owner_user_id = user_info.get("id")
        owner_user_name = user_info.get("name")
        owner_user_email = (user_info.get("person") or {}).get("email")

    record = {
        "user_id": user_id,
        "provider": "notion",
        "access_token_encrypted": encrypted_token,
        "workspace_id": workspace_id,
        "workspace_name": workspace_name or "Notion Workspace",
        "workspace_icon": workspace_icon,
        "bot_id": bot_id,
        "owner_user_id": owner_user_id,
        "owner_user_name": owner_user_name,
        "owner_user_email": owner_user_email,
        "status": "connected",
        "updated_at": now_iso,
    }

    if c is not None:
        try:
            # Check existing
            r0 = (
                c.table(USER_INTEGRATIONS_TABLE)
                .select("id")
                .eq("user_id", user_id)
                .eq("provider", "notion")
                .execute()
            )
            if r0.data and len(r0.data) > 0:
                int_id = r0.data[0]["id"]
                r = (
                    c.table(USER_INTEGRATIONS_TABLE)
                    .update(record)
                    .eq("id", int_id)
                    .execute()
                )
                if r.data:
                    return r.data[0]
            else:
                record["created_at"] = now_iso
                r = c.table(USER_INTEGRATIONS_TABLE).insert(record).execute()
                if r.data:
                    return r.data[0]
        except Exception as e:
            logger.warning(f"Could not persist integration to Supabase (using memory fallback): {e}")

    # Memory fallback
    record["created_at"] = _memory_integrations.get(user_id, {}).get("created_at", now_iso)
    _memory_integrations[user_id] = record
    return record


def get_integration(user_id: str) -> Optional[dict]:
    """Retrieve integration record for user."""
    c = _client()
    if c is not None:
        try:
            r = (
                c.table(USER_INTEGRATIONS_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .eq("provider", "notion")
                .execute()
            )
            if r.data and len(r.data) > 0:
                return r.data[0]
        except Exception as e:
            logger.debug(f"Error querying user_integrations: {e}")

    return _memory_integrations.get(user_id)


def get_synced_pages(user_id: str) -> List[dict]:
    """
    Retrieve all synchronized Notion pages and their extracted skill evidence for a user.
    """
    c = _client()
    pages: List[dict] = []
    if c is not None:
        try:
            r = (
                c.table(NOTION_SYNCED_PAGES_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .order("last_edited_time", desc=True)
                .execute()
            )
            pages = r.data or []
        except Exception as e:
            logger.warning(f"Error reading notion_synced_pages: {e}")
            pages = _memory_synced_pages.get(user_id, [])
    else:
        pages = _memory_synced_pages.get(user_id, [])

    formatted = []
    for p in pages:
        ev_items = p.get("extracted_evidence") or []
        skills = list(dict.fromkeys(item.get("skill") for item in ev_items if isinstance(item, dict) and item.get("skill")))
        headings = p.get("headings") or []
        code_langs = p.get("code_languages") or []
        word_count = p.get("word_count") or 0

        formatted.append({
            "page_id": p.get("page_id", ""),
            "page_title": p.get("page_title", "Untitled Notion Page"),
            "page_url": p.get("page_url", ""),
            "last_edited_time": p.get("last_edited_time"),
            "content_summary": p.get("content_summary") or f"Detected {len(skills)} skills",
            "skills": skills,
            "headings": headings,
            "code_languages": code_langs,
            "word_count": word_count,
            "extracted_evidence": ev_items,
        })
    return formatted


def get_status(user_id: str) -> dict:
    """
    Get user-facing Notion integration status.
    NEVER leaks access tokens or internal encryption details.
    """
    integration = get_integration(user_id)
    if not integration or integration.get("status") != "connected":
        return {
            "connected": False,
            "status": "disconnected",
            "synced_pages": [],
        }

    c = _client()
    synced_pages = get_synced_pages(user_id)
    synced_pages_count = len(synced_pages)
    evidence_count = sum(len(p.get("extracted_evidence") or []) for p in synced_pages)

    if c is not None and evidence_count == 0:
        try:
            r_ev = (
                c.table(EVIDENCE_TABLE)
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("evidence_type", "notion")
                .execute()
            )
            count_val = getattr(r_ev, "count", None) or len(r_ev.data or [])
            if count_val > 0:
                evidence_count = count_val
        except Exception:
            pass

    return {
        "connected": True,
        "status": integration.get("status", "connected"),
        "workspace_name": integration.get("workspace_name"),
        "workspace_icon": integration.get("workspace_icon"),
        "workspace_id": integration.get("workspace_id"),
        "bot_id": integration.get("bot_id"),
        "last_synced_at": integration.get("last_synced_at"),
        "synced_pages_count": synced_pages_count,
        "evidence_count": evidence_count,
        "synced_pages": synced_pages,
    }


def disconnect(user_id: str) -> dict:
    """
    Disconnect Notion integration:
    1. Permanently remove integration record & encrypted token server-side.
    2. Remove synced Notion pages.
    3. Remove Notion-derived evidence from canonical evidence table.
    4. Leave all GitHub, resume, project, cert, and interview evidence 100% intact.
    """
    c = _client()

    if c is not None:
        try:
            # 1. Remove integration row
            c.table(USER_INTEGRATIONS_TABLE).delete().eq("user_id", user_id).eq("provider", "notion").execute()
        except Exception as e:
            logger.warning(f"Error deleting user_integrations: {e}")

        try:
            # 2. Remove synced pages
            c.table(NOTION_SYNCED_PAGES_TABLE).delete().eq("user_id", user_id).execute()
        except Exception as e:
            logger.warning(f"Error deleting notion_synced_pages: {e}")

        try:
            # 3. Remove Notion evidence items only
            c.table(EVIDENCE_TABLE).delete().eq("user_id", user_id).eq("evidence_type", "notion").execute()
        except Exception as e:
            logger.warning(f"Error deleting notion evidence: {e}")

    # Clear memory fallback
    _memory_integrations.pop(user_id, None)
    _memory_synced_pages.pop(user_id, None)
    if user_id in _memory_evidence:
        _memory_evidence[user_id] = [e for e in _memory_evidence[user_id] if e.get("evidence_type") != "notion"]

    return {
        "status": "disconnected",
        "message": "Notion integration disconnected and stored Notion evidence removed.",
    }


# ---------------------------------------------------------------------------
# Notion API Client (Pagination & Permissions Awareness)
# ---------------------------------------------------------------------------

async def fetch_authorized_pages(access_token: str, max_pages: int = 100) -> List[dict]:
    """
    Retrieve only pages and databases that Notion makes available to the authorized integration.
    Handles Notion API pagination (start_cursor / has_more) cleanly.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }

    pages: List[dict] = []
    has_more = True
    start_cursor = None

    async with httpx.AsyncClient(timeout=20.0) as client:
        while has_more and len(pages) < max_pages:
            body: Dict[str, Any] = {
                "sort": {
                    "direction": "descending",
                    "timestamp": "last_edited_time",
                },
                "page_size": min(100, max_pages - len(pages)),
            }
            if start_cursor:
                body["start_cursor"] = start_cursor

            try:
                resp = await client.post(f"{NOTION_API_BASE_URL}/search", json=body, headers=headers)
            except Exception as e:
                logger.error(f"Network error querying Notion search: {e}")
                raise HTTPException(status_code=502, detail=f"Failed to query Notion API: {str(e)}")

            if resp.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="Notion access token has expired or was revoked. Please reconnect Notion.",
                )
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After", "2")
                logger.warning(f"Notion rate limit hit. Retry-After: {retry_after}")
                raise HTTPException(status_code=429, detail="Notion API rate limit exceeded. Please wait a moment.")
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Notion API returned error: {resp.text[:200]}",
                )

            data = resp.json()
            results = data.get("results") or []
            pages.extend(results)

            has_more = bool(data.get("has_more", False))
            start_cursor = data.get("next_cursor")
            if not start_cursor:
                break

    return pages


def extract_page_title(page: dict) -> str:
    """Extract page title safely across various Notion property schemas."""
    # Check properties
    props = page.get("properties") or {}
    for p_name, p_val in props.items():
        if isinstance(p_val, dict) and p_val.get("type") == "title":
            title_list = p_val.get("title") or []
            title_str = "".join(t.get("plain_text", "") for t in title_list if isinstance(t, dict)).strip()
            if title_str:
                return title_str

    # Database title
    title_list = page.get("title") or []
    if isinstance(title_list, list) and title_list:
        title_str = "".join(t.get("plain_text", "") for t in title_list if isinstance(t, dict)).strip()
        if title_str:
            return title_str

    return "Untitled Notion Page"


async def fetch_page_blocks(access_token: str, page_id: str, max_depth: int = 2) -> List[dict]:
    """
    Fetch block children of a Notion page, handling pagination and nested blocks.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": NOTION_API_VERSION,
    }

    blocks: List[dict] = []
    has_more = True
    start_cursor = None

    async with httpx.AsyncClient(timeout=15.0) as client:
        while has_more and len(blocks) < 150:
            params = {"page_size": 100}
            if start_cursor:
                params["start_cursor"] = start_cursor

            try:
                resp = await client.get(
                    f"{NOTION_API_BASE_URL}/blocks/{page_id}/children",
                    params=params,
                    headers=headers,
                )
            except Exception as e:
                logger.warning(f"Error fetching blocks for page {page_id}: {e}")
                break

            if resp.status_code != 200:
                break

            data = resp.json()
            results = data.get("results") or []
            blocks.extend(results)

            has_more = bool(data.get("has_more", False))
            start_cursor = data.get("next_cursor")
            if not start_cursor:
                break

    return blocks


def parse_block_content(blocks: List[dict]) -> Tuple[str, List[dict], List[dict], List[str]]:
    """
    Parse text, code snippets, completed tasks, and headings from Notion blocks.
    Returns: (full_text, code_blocks, tasks, headings)
    """
    text_chunks: List[str] = []
    code_blocks: List[dict] = []
    tasks: List[dict] = []
    headings: List[str] = []

    for b in blocks:
        if not isinstance(b, dict):
            continue
        b_type = b.get("type", "")
        b_data = b.get(b_type) or {}
        if not isinstance(b_data, dict):
            continue

        rich_texts = b_data.get("rich_text") or []
        plain = "".join(r.get("plain_text", "") for r in rich_texts if isinstance(r, dict)).strip()

        if b_type.startswith("heading_"):
            if plain:
                headings.append(plain)
                text_chunks.append(plain)
        elif b_type == "code":
            lang = b_data.get("language", "text")
            code_text = plain
            code_blocks.append({"language": lang, "code": code_text})
            text_chunks.append(code_text)
        elif b_type == "to_do":
            checked = bool(b_data.get("checked", False))
            tasks.append({"task": plain, "completed": checked})
            if plain:
                text_chunks.append(plain)
        elif plain:
            text_chunks.append(plain)

    return " ".join(text_chunks), code_blocks, tasks, headings


# ---------------------------------------------------------------------------
# Learning Evidence Extraction & Provenance Model
# ---------------------------------------------------------------------------

ASPIRATIONAL_PATTERNS = [
    re.compile(r'\b(?:interested in|looking to|eager to|hoping to|seeking to|want to|plan to)\s+learn\b', re.I),
    re.compile(r'\b(?:interested in|exploring|future interest(?:\s+in)?|wishlist|backlog|to read|to learn)\b', re.I),
    re.compile(r'\b(?:beginner in|basic knowledge of|familiarity with|introductory knowledge of)\b', re.I),
]

STUDY_KEYWORDS = [
    "notes", "concept", "concepts", "overview", "summary", "how it works",
    "architecture", "lifecycle", "cheatsheet", "guide", "tutorial", "lecture",
    "study", "key takeaways", "fundamentals", "explanation", "deep dive"
]

PRACTICE_KEYWORDS = [
    "exercise", "exercises", "problem", "problems", "solved", "leetcode",
    "hackerrank", "lab", "assignment", "practice", "drill", "task", "checklist"
]

IMPLEMENTATION_KEYWORDS = [
    "implemented", "built", "engineered", "developed", "configured", "deployed",
    "refactored", "migration", "service", "endpoint", "pipeline", "schema",
    "dockerfile", "component", "middleware", "api"
]

DEMONSTRATED_KEYWORDS = [
    "tested", "test cases", "unit test", "integration test", "benchmark",
    "passed", "score", "grade", "verified", "demo", "production", "live"
]

KNOWN_SKILL_TOPICS: Dict[str, List[str]] = {
    "React": ["useState", "useEffect", "useRef", "useMemo", "useCallback", "custom hooks", "context api", "jsx", "virtual dom", "props"],
    "Python": ["decorators", "generators", "asyncio", "multiprocessing", "pydantic", "fastapi", "list comprehension", "typing"],
    "Docker": ["Dockerfile", "docker-compose", "container", "image", "multi-stage build", "volumes", "port mapping"],
    "Kubernetes": ["pods", "deployments", "services", "ingress", "configmaps", "secrets", "helm", "namespaces"],
    "PostgreSQL": ["indexing", "joins", "transactions", "acid", "views", "triggers", "foreign keys", "constraints"],
    "FastAPI": ["dependency injection", "routers", "pydantic", "async endpoints", "status codes", "middleware"],
    "Data Structures & Algorithms": ["binary search", "graphs", "trees", "dynamic programming", "two pointers", "sliding window", "sorting"],
    "TypeScript": ["interfaces", "types", "generics", "unions", "utility types", "type guards", "tsconfig"],
    "Git": ["branches", "rebase", "cherry-pick", "merge", "commit", "stash"],
}


def extract_skill_excerpt(text: str, skill: str, max_length: int = 140) -> Optional[str]:
    """Find a readable excerpt around where the skill or its topics appear."""
    if not text or not skill:
        return None
    skill_lower = skill.lower()
    idx = text.lower().find(skill_lower)
    if idx == -1:
        clean_text = text.strip()
        if not clean_text:
            return None
        return clean_text[:max_length].strip() + ("…" if len(clean_text) > max_length else "")

    start = max(0, idx - 35)
    end = min(len(text), idx + len(skill) + 90)

    # Adjust to word boundaries
    if start > 0:
        prev_space = text.rfind(" ", 0, start)
        if prev_space != -1 and prev_space >= start - 15:
            start = prev_space + 1
    if end < len(text):
        next_space = text.find(" ", end)
        if next_space != -1 and next_space <= end + 15:
            end = next_space

    snippet = text[start:end].strip().replace("\n", " ")
    if start > 0 and not snippet.startswith("…"):
        snippet = "…" + snippet
    if end < len(text) and not snippet.endswith("…"):
        snippet = snippet + "…"
    return snippet


def extract_learning_evidence_from_page(
    page_id: str,
    page_title: str,
    page_url: str,
    blocks: List[dict],
    last_edited_time: Optional[str] = None,
    client: Optional[Client] = None,
) -> List[dict]:
    """
    Extract structured learning/skill evidence from authorized Notion page content.
    Differentiates between:
    - Demonstrated (code + tests/benchmarks/high quiz score)
    - Implemented (substantive code blocks, concrete code implementations)
    - Practiced (completed tasks, exercise logs, problem solutions)
    - Studied (conceptual notes, explanations, structured summaries)
    - Mentioned (isolated mention, wishlist/backlog, aspirational)
    """
    full_text, code_blocks, tasks, headings = parse_block_content(blocks)
    combined_text = f"{page_title} {full_text}"
    text_lower = combined_text.lower()

    if not combined_text.strip():
        return []

    # Detect skills via taxonomy
    detected_skills: Dict[str, dict] = {}

    # 1. From title
    for token in page_title.replace("-", " ").replace("/", " ").replace("_", " ").split():
        if len(token) >= 2:
            c = normalize_skill(token, client)
            if c:
                detected_skills[c] = {"in_title": True, "count": 1}

    # 2. From taxonomy scan
    for sk in extract_known_skills_from_text(combined_text, client):
        canonical = sk.display_name
        if canonical not in detected_skills:
            detected_skills[canonical] = {"in_title": False, "count": 1}
        else:
            detected_skills[canonical]["count"] += 1

    # 3. Check language of code blocks
    lang_to_skill = {
        "python": "Python",
        "javascript": "JavaScript",
        "typescript": "TypeScript",
        "sql": "SQL",
        "dockerfile": "Docker",
        "shell": "Linux",
        "bash": "Linux",
        "html": "HTML",
        "css": "CSS",
        "go": "Go",
        "rust": "Rust",
        "java": "Java",
        "c++": "C++",
    }
    for cb in code_blocks:
        l = cb.get("language", "").lower()
        if l in lang_to_skill:
            c = lang_to_skill[l]
            if c not in detected_skills:
                detected_skills[c] = {"in_title": False, "count": 2, "has_code": True}
            else:
                detected_skills[c]["has_code"] = True

    evidence_items: List[dict] = []
    timestamp = last_edited_time or datetime.now(timezone.utc).isoformat()

    for skill, info in detected_skills.items():
        skill_lower = skill.lower()
        has_code = bool(info.get("has_code")) or any(skill_lower in (cb.get("code") or "").lower() for cb in code_blocks)

        # Topic detection for this skill
        known_topics = KNOWN_SKILL_TOPICS.get(skill, [])
        found_topics: List[str] = []
        for t in known_topics:
            if t.lower() in text_lower:
                found_topics.append(t)

        # Also search headings for topic clues
        for h in headings:
            if h.lower() != page_title.lower() and len(h.split()) <= 4:
                if any(w in h.lower() for w in [skill_lower, "hook", "pattern", "component", "config", "method", "query"]):
                    if h not in found_topics:
                        found_topics.append(h)

        # Check aspirational / backlog context
        is_aspirational = any(p.search(combined_text) for p in ASPIRATIONAL_PATTERNS)
        if "to learn" in text_lower or "wishlist" in text_lower or "backlog" in text_lower:
            is_aspirational = True

        # Check completed practice tasks
        completed_tasks = [t for t in tasks if t.get("completed")]
        has_practice = any(any(kw in t["task"].lower() for kw in PRACTICE_KEYWORDS) for t in completed_tasks) or any(kw in text_lower for kw in PRACTICE_KEYWORDS)
        has_implementation = has_code or any(kw in text_lower for kw in IMPLEMENTATION_KEYWORDS)
        has_demonstrated = (has_code and any(kw in text_lower for kw in DEMONSTRATED_KEYWORDS)) or "passed" in text_lower or "score" in text_lower

        # Classify evidenceType
        if is_aspirational and not has_code and not has_practice:
            evidence_type = "mentioned"
            confidence = 0.35
            signal_strength = 0.25
            depth = EvidenceDepth.LEVEL_1_MENTION
        elif has_demonstrated:
            evidence_type = "demonstrated"
            confidence = 0.88 + min(0.07, len(found_topics) * 0.02)
            signal_strength = 0.85
            depth = EvidenceDepth.LEVEL_4_SUBSTANTIAL
        elif has_implementation:
            evidence_type = "implemented"
            confidence = 0.80 + min(0.08, len(found_topics) * 0.02)
            signal_strength = 0.75
            depth = EvidenceDepth.LEVEL_3_IMPLEMENTATION
        elif has_practice:
            evidence_type = "practiced"
            confidence = 0.75 + min(0.08, len(found_topics) * 0.02)
            signal_strength = 0.65
            depth = EvidenceDepth.LEVEL_2_CONFIG
        elif any(kw in text_lower for kw in STUDY_KEYWORDS) or len(combined_text) > 80:
            evidence_type = "studied"
            confidence = 0.70 + min(0.08, len(found_topics) * 0.02)
            signal_strength = 0.60
            depth = EvidenceDepth.LEVEL_2_CONFIG
        else:
            evidence_type = "mentioned"
            confidence = 0.40
            signal_strength = 0.30
            depth = EvidenceDepth.LEVEL_1_MENTION

        confidence = round(min(0.95, max(0.20, confidence)), 2)
        signal_strength = round(signal_strength, 2)

        excerpt = extract_skill_excerpt(full_text or combined_text, skill)

        evidence_items.append({
            "skill": skill,
            "canonical_name": skill,
            "evidenceType": evidence_type,
            "source": "notion",
            "sourcePageId": page_id,
            "sourcePageTitle": page_title,
            "sourceUrl": page_url,
            "confidence": confidence,
            "signal_strength": signal_strength,
            "depth": depth,
            "topics": found_topics[:6],
            "excerpt": excerpt,
            "timestamp": timestamp,
        })

    return evidence_items


# ---------------------------------------------------------------------------
# Content Synchronization Orchestrator
# ---------------------------------------------------------------------------

async def sync_notion_content(user_id: str) -> dict:
    """
    Synchronize authorized Notion content for the authenticated user.
    1. Retrieves encrypted access token and decrypts it server-side.
    2. Fetches authorized pages via Notion API with pagination.
    3. Fetches page content blocks.
    4. Extracts learning/skill evidence with full provenance.
    5. Saves raw synced pages to notion_synced_pages.
    6. Updates canonical evidence layer (public.evidence) with verified signals.
    7. Optionally triggers re-analysis if target_role is active.
    """
    integration = get_integration(user_id)
    if not integration or integration.get("status") != "connected":
        raise HTTPException(
            status_code=400,
            detail="Notion is not connected. Please authorize Notion first.",
        )

    encrypted_token = integration.get("access_token_encrypted")
    if not encrypted_token:
        raise HTTPException(status_code=400, detail="Notion authorization token missing.")

    try:
        access_token = decrypt_token(encrypted_token)
    except Exception as e:
        logger.error(f"Failed to decrypt Notion token for user {user_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to decrypt integration token. Please reconnect Notion.",
        )

    # Fetch authorized pages
    try:
        pages = await fetch_authorized_pages(access_token)
    except HTTPException as he:
        if he.status_code == 401:
            # Mark integration as expired/reconnect_required
            c = _client()
            if c is not None:
                try:
                    c.table(USER_INTEGRATIONS_TABLE).update({"status": "reconnect_required"}).eq("user_id", user_id).eq("provider", "notion").execute()
                except Exception:
                    pass
            if user_id in _memory_integrations:
                _memory_integrations[user_id]["status"] = "reconnect_required"
        raise

    c = _client()
    now_iso = datetime.now(timezone.utc).isoformat()
    evidence_items_created = 0
    pages_with_evidence = 0
    all_detected_skills: set[str] = set()
    sync_details: List[dict] = []

    for page in pages:
        p_id = page.get("id")
        if not p_id:
            continue
        p_title = extract_page_title(page)
        p_url = page.get("url") or f"https://www.notion.so/{p_id.replace('-', '')}"
        last_edited = page.get("last_edited_time") or now_iso

        # Fetch child blocks for text & code
        blocks = await fetch_page_blocks(access_token, p_id)
        evidence_items = extract_learning_evidence_from_page(
            page_id=p_id,
            page_title=p_title,
            page_url=p_url,
            blocks=blocks,
            last_edited_time=last_edited,
            client=c,
        )

        if not evidence_items:
            continue

        pages_with_evidence += 1
        page_skills = [item["skill"] for item in evidence_items]
        all_detected_skills.update(page_skills)

        # Compute rich metadata for user clarity
        full_text, code_blocks, tasks, headings = parse_block_content(blocks)
        page_code_langs = sorted(list(set(cb.get("language") for cb in code_blocks if cb.get("language") and cb.get("language") != "plain text")))
        word_count = len(full_text.split())
        content_summary = (
            f"Extracted {len(evidence_items)} skill evidence items: {', '.join(page_skills[:4])}"
            + (f" · {len(code_blocks)} code block{'s' if len(code_blocks) != 1 else ''}" if code_blocks else "")
            + (f" · {len(headings)} section{'s' if len(headings) != 1 else ''}" if headings else "")
        )

        # 1. Save to notion_synced_pages
        synced_page_record = {
            "user_id": user_id,
            "page_id": p_id,
            "page_title": p_title,
            "page_url": p_url,
            "last_edited_time": last_edited,
            "content_summary": content_summary,
            "extracted_evidence": evidence_items,
            "headings": headings[:6],
            "code_languages": page_code_langs,
            "word_count": word_count,
            "skills": page_skills,
            "updated_at": now_iso,
        }

        if c is not None:
            try:
                # Upsert into notion_synced_pages
                c.table(NOTION_SYNCED_PAGES_TABLE).upsert(
                    {**synced_page_record, "created_at": now_iso},
                    on_conflict="user_id,page_id",
                ).execute()
            except Exception as e:
                logger.debug(f"Could not persist to notion_synced_pages: {e}")

        # In-memory fallback
        user_pages = _memory_synced_pages.setdefault(user_id, [])
        user_pages = [p for p in user_pages if p.get("page_id") != p_id]
        user_pages.append(synced_page_record)
        _memory_synced_pages[user_id] = user_pages

        # 2. Build verified technical signals for this Notion evidence
        rel = get_reliability("notion")
        verified_signals = []
        for it in evidence_items:
            verified_signals.append({
                "skill": it["skill"],
                "canonical_name": it["skill"],
                "signal_strength": it["signal_strength"],
                "signal_value": it["signal_strength"],
                "depth": it["depth"],
                "reason": f"Notion notes on '{p_title}': {it['evidenceType']} {it['skill']}" + (f" ({', '.join(it['topics'])})" if it.get("topics") else ""),
                "explanation": f"Notion notes on '{p_title}'",
                "source_reliability": rel,
                "metadata": {
                    "source": "notion",
                    "sourcePageId": p_id,
                    "sourcePageTitle": p_title,
                    "sourceUrl": p_url,
                    "evidenceType": it["evidenceType"],
                    "confidence": it["confidence"],
                    "topics": it.get("topics", []),
                    "timestamp": it.get("timestamp"),
                },
            })

        evidence_payload = {
            "user_id": user_id,
            "evidence_type": "notion",
            "source_url": p_url,
            "title": f"Notion · {p_title}",
            "verification_status": VerificationStatus.VERIFIED,
            "provider": "notion",
            "verified_at": now_iso,
            "metadata": {
                "source": "notion",
                "sourcePageId": p_id,
                "sourcePageTitle": p_title,
                "sourceUrl": p_url,
                "last_edited_time": last_edited,
                "evidence_pipeline_version": EVIDENCE_PIPELINE_VERSION,
                "verified_signals": verified_signals,
                "extracted_items": evidence_items,
                "facts": [
                    f"Notion page: {p_title}",
                    f"Skills detected: {', '.join(page_skills)}",
                ],
            },
            "updated_at": now_iso,
        }

        # Save to canonical evidence table
        if c is not None:
            try:
                # Check if evidence record already exists for this page
                r_existing = (
                    c.table(EVIDENCE_TABLE)
                    .select("id")
                    .eq("user_id", user_id)
                    .eq("evidence_type", "notion")
                    .eq("source_url", p_url)
                    .execute()
                )
                if r_existing.data and len(r_existing.data) > 0:
                    ev_id = r_existing.data[0]["id"]
                    c.table(EVIDENCE_TABLE).update(evidence_payload).eq("id", ev_id).execute()
                else:
                    evidence_payload["created_at"] = now_iso
                    c.table(EVIDENCE_TABLE).insert(evidence_payload).execute()
            except Exception as e:
                logger.warning(f"Could not persist Notion evidence to canonical evidence table: {e}")

        # Memory fallback
        user_ev_list = _memory_evidence.setdefault(user_id, [])
        user_ev_list = [e for e in user_ev_list if e.get("source_url") != p_url]
        user_ev_list.append(evidence_payload)
        _memory_evidence[user_id] = user_ev_list

        evidence_items_created += len(evidence_items)
        sync_details.append({
            "page_id": p_id,
            "page_title": p_title,
            "page_url": p_url,
            "last_edited_time": last_edited,
            "content_summary": content_summary,
            "skills": page_skills,
            "headings": headings[:6],
            "code_languages": page_code_langs,
            "word_count": word_count,
            "evidence_count": len(evidence_items),
            "extracted_evidence": evidence_items,
        })

    # Update last_synced_at on user_integrations
    if c is not None:
        try:
            c.table(USER_INTEGRATIONS_TABLE).update({"last_synced_at": now_iso}).eq("user_id", user_id).eq("provider", "notion").execute()
        except Exception:
            pass
    if user_id in _memory_integrations:
        _memory_integrations[user_id]["last_synced_at"] = now_iso

    # Automatically re-run analysis if target role is set, so roadmap updates immediately
    try:
        from . import analysis_service as _as
        from .analysis_run_service import run_analysis
        state = _as.get_state(user_id)
        if state and state.get("target_role"):
            await run_analysis(user_id, state["target_role"])
    except Exception as e:
        logger.debug(f"Optional re-analysis after sync skipped: {e}")

    return {
        "status": "ok",
        "pages_scanned": len(pages),
        "pages_with_evidence": pages_with_evidence,
        "evidence_count": evidence_items_created,
        "skills_detected": sorted(list(all_detected_skills)),
        "last_synced_at": now_iso,
        "details": sync_details,
        "synced_pages": get_synced_pages(user_id),
    }
