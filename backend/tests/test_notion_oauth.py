import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import get_settings
from app.core.encryption import encrypt_token, decrypt_token
from app.core.security import CurrentUser, get_current_user
from app.services import notion_service
from app.services.evidence_weights import reliability, directness, RELIABILITY_TIERS
from app.services.skill_engine import proficiency, confidence_from_signals


client = TestClient(app)

USER_A = "user-aaa-1111-2222"
USER_B = "user-bbb-3333-4444"


@pytest.fixture(autouse=True)
def setup_notion_env(monkeypatch):
    """Ensure Notion configuration is active for tests."""
    monkeypatch.setenv("NOTION_CLIENT_ID", "test-notion-client-id")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "test-notion-client-secret-xyz-12345")
    monkeypatch.setenv("NOTION_REDIRECT_URI", "http://localhost:8000/api/integrations/notion/callback")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 1. OAuth State Generation & Cryptographic Validation (CSRF Protection)
# ---------------------------------------------------------------------------

def test_oauth_state_generation_and_validation():
    """State must be signed, contain user_id, and validate successfully."""
    state = notion_service.generate_oauth_state(USER_A)
    assert "." in state
    assert len(state.split(".")) == 2

    # Validate state
    validated_user = notion_service.validate_oauth_state(state)
    assert validated_user == USER_A


def test_oauth_state_rejects_tampered_payload():
    """Tampering with the payload or signature must fail with 400."""
    state = notion_service.generate_oauth_state(USER_A)
    payload_b64, sig_b64 = state.split(".")

    # Tamper with payload (substitute another user_id)
    tampered_payload = base64.urlsafe_b64encode(
        json.dumps({"user_id": USER_B, "nonce": "hacked", "exp": int(time.time()) + 600}).encode()
    ).decode().rstrip("=")
    tampered_state = f"{tampered_payload}.{sig_b64}"

    with pytest.raises(HTTPException) as exc:
        notion_service.validate_oauth_state(tampered_state)
    assert exc.value.status_code == 400
    assert "Invalid OAuth state signature" in exc.value.detail


def test_oauth_state_rejects_expired_state(monkeypatch):
    """Expired state must fail with 400."""
    # Create expired state by faking time
    with patch("time.time", return_value=1000.0):
        state = notion_service.generate_oauth_state(USER_A)

    # Validate after expiry
    with patch("time.time", return_value=2000.0):
        with pytest.raises(HTTPException) as exc:
            notion_service.validate_oauth_state(state)
        assert exc.value.status_code == 400
        assert "expired" in exc.value.detail.lower()


def test_oauth_state_rejects_malformed_inputs():
    """Missing or non-split state strings must be rejected."""
    for bad in ["", "not-a-state", "foo.bar.baz", "null", ".empty"]:
        with pytest.raises(HTTPException) as exc:
            notion_service.validate_oauth_state(bad)
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 2. Token Encryption at Rest
# ---------------------------------------------------------------------------

def test_token_encryption_at_rest():
    """Access tokens must be encrypted at rest and never stored in plaintext."""
    token = "secret_notion_access_token_super_confidential_9999"
    ciphertext = encrypt_token(token)

    assert ciphertext != token
    assert "secret_notion_access_token" not in ciphertext

    decrypted = decrypt_token(ciphertext)
    assert decrypted == token


# ---------------------------------------------------------------------------
# 3. Authentication & Authorization Enforcement (User Isolation)
# ---------------------------------------------------------------------------

def test_unauthenticated_requests_rejected():
    """Endpoints requiring authentication must return 401 when no token is provided."""
    resp = client.get("/api/integrations/notion/connect")
    assert resp.status_code == 401

    resp = client.get("/api/integrations/notion/status")
    assert resp.status_code == 401

    resp = client.post("/api/integrations/notion/sync")
    assert resp.status_code == 401

    resp = client.delete("/api/integrations/notion/disconnect")
    assert resp.status_code == 401


def test_cross_user_isolation():
    """User B cannot access or disconnect User A's Notion integration."""
    # Save integration for User A
    notion_service.save_integration(
        user_id=USER_A,
        access_token="secret_token_user_a",
        workspace_id="ws-a-123",
        workspace_name="User A Workspace",
    )

    # Mock CurrentUser as User B
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=USER_B, email="b@example.com")
    try:
        # User B checks status -> must be disconnected
        status_resp = client.get("/api/integrations/notion/status")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["connected"] is False
        assert data["status"] == "disconnected"
        assert data.get("workspace_name") is None

        # User B attempts to sync -> must fail
        sync_resp = client.post("/api/integrations/notion/sync")
        assert sync_resp.status_code == 400
        assert "not connected" in sync_resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()
        notion_service.disconnect(USER_A)
        notion_service.disconnect(USER_B)


# ---------------------------------------------------------------------------
# 4. Connect, Callback, Status & Disconnect Lifecycle
# ---------------------------------------------------------------------------

def test_connect_endpoint_generates_official_oauth_url():
    """GET /connect generates a valid Notion OAuth 2.0 URL."""
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=USER_A, email="a@example.com")
    try:
        resp = client.get("/api/integrations/notion/connect")
        assert resp.status_code == 200
        data = resp.json()
        url = data["authorization_url"]
        assert "https://api.notion.com/v1/oauth/authorize" in url
        assert "client_id=test-notion-client-id" in url
        assert "response_type=code" in url
        assert "owner=user" in url
        assert "state=" in url
    finally:
        app.dependency_overrides.clear()


def test_callback_handles_user_denial():
    """Callback redirects to frontend with error message if user denies access."""
    resp = client.get("/api/integrations/notion/callback?error=access_denied", follow_redirects=False)
    assert resp.status_code in (302, 303, 307)
    location = resp.headers["location"]
    assert "notion_error=access_denied" in location


def test_callback_validates_state_and_exchanges_token(monkeypatch):
    """Callback validates state and exchanges authorization code for token."""
    state = notion_service.generate_oauth_state(USER_A)
    mock_token_data = {
        "access_token": "secret_mock_oauth_access_token_12345",
        "workspace_id": "ws-notion-456",
        "workspace_name": "Engineering Knowledge Base",
        "workspace_icon": "📚",
        "bot_id": "bot-inaura-789",
        "owner": {"user": {"id": "usr-1", "name": "Alice", "person": {"email": "alice@example.com"}}},
    }

    async def _mock_exchange(code):
        return mock_token_data

    with patch("app.services.notion_service.exchange_code_for_token", side_effect=_mock_exchange):
        resp = client.get(f"/api/integrations/notion/callback?code=mock_auth_code&state={state}", follow_redirects=False)
        assert resp.status_code in (302, 303, 307)
        assert "notion=connected" in resp.headers["location"]

    # Verify integration saved securely
    integration = notion_service.get_integration(USER_A)
    assert integration is not None
    assert integration["status"] == "connected"
    assert integration["workspace_name"] == "Engineering Knowledge Base"
    assert integration["workspace_id"] == "ws-notion-456"
    # Never stored in plaintext
    assert integration["access_token_encrypted"] != "secret_mock_oauth_access_token_12345"
    assert decrypt_token(integration["access_token_encrypted"]) == "secret_mock_oauth_access_token_12345"


def test_status_endpoint_never_exposes_secrets():
    """GET /status must never leak access tokens or client secrets."""
    notion_service.save_integration(
        user_id=USER_A,
        access_token="secret_super_secret_notion_key",
        workspace_id="ws-123",
        workspace_name="Alice's Workspace",
    )

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=USER_A, email="a@example.com")
    try:
        resp = client.get("/api/integrations/notion/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["workspace_name"] == "Alice's Workspace"
        # Secrets MUST NOT appear anywhere in the response JSON
        raw_json = resp.text
        assert "secret_super_secret" not in raw_json
        assert "access_token" not in data
        assert "access_token_encrypted" not in data
    finally:
        app.dependency_overrides.clear()
        notion_service.disconnect(USER_A)


def test_disconnect_removes_token_and_notion_evidence_only():
    """Disconnect removes Notion tokens and Notion evidence while keeping other sources intact."""
    notion_service.save_integration(
        user_id=USER_A,
        access_token="secret_to_delete",
        workspace_name="Alice Notes",
    )

    # Simulate memory evidence for both github and notion
    notion_service._memory_evidence[USER_A] = [
        {"evidence_type": "github", "source_url": "https://github.com/alice/repo1", "title": "Repo 1"},
        {"evidence_type": "notion", "source_url": "https://notion.so/page1", "title": "Notion React Notes"},
    ]

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=USER_A, email="a@example.com")
    try:
        del_resp = client.delete("/api/integrations/notion/disconnect")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "disconnected"

        # Check integration is gone
        int_after = notion_service.get_integration(USER_A)
        assert int_after is None

        # Check status is disconnected
        stat_resp = client.get("/api/integrations/notion/status")
        assert stat_resp.json()["connected"] is False

        # Verify other evidence (GitHub) was NOT deleted
        ev_remaining = notion_service._memory_evidence.get(USER_A, [])
        assert any(e.get("evidence_type") == "github" for e in ev_remaining)
        assert not any(e.get("evidence_type") == "notion" for e in ev_remaining)
    finally:
        app.dependency_overrides.clear()
        notion_service.disconnect(USER_A)


# ---------------------------------------------------------------------------
# 5. Notion API Pagination
# ---------------------------------------------------------------------------

def test_notion_search_pagination(monkeypatch):
    """fetch_authorized_pages must follow start_cursor across multiple pages."""
    import asyncio
    call_count = 0

    async def mock_post(url, json=None, headers=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MagicMock(
                status_code=200,
                json=lambda: {
                    "results": [{"id": "page-1", "title": [{"plain_text": "Page 1"}]}],
                    "has_more": True,
                    "next_cursor": "cursor-2",
                },
            )
        else:
            return MagicMock(
                status_code=200,
                json=lambda: {
                    "results": [{"id": "page-2", "title": [{"plain_text": "Page 2"}]}],
                    "has_more": False,
                    "next_cursor": None,
                },
            )

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        pages = asyncio.run(notion_service.fetch_authorized_pages("fake-token", max_pages=10))
        assert len(pages) == 2
        assert pages[0]["id"] == "page-1"
        assert pages[1]["id"] == "page-2"
        assert call_count == 2


# ---------------------------------------------------------------------------
# 6. Evidence Extraction & 5-Tier Classification
# ---------------------------------------------------------------------------

def test_learning_evidence_differentiation():
    """
    Evidence extraction must differentiate between:
    - Demonstrated
    - Implemented
    - Practiced
    - Studied
    - Mentioned
    """
    # 1. Demonstrated: Code + passing unit tests
    demo_blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "React Custom Hooks"}]}},
        {"type": "code", "code": {"language": "typescript", "rich_text": [{"plain_text": "export function useFetch(url: string) { const [data, setData] = useState(null); return data; }"}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Unit test suite passed all test cases with 100% benchmark score."}]}},
    ]
    ev_demo = notion_service.extract_learning_evidence_from_page(
        page_id="p-demo",
        page_title="React Custom Hooks",
        page_url="https://notion.so/p-demo",
        blocks=demo_blocks,
    )
    assert len(ev_demo) >= 1
    react_ev = next(e for e in ev_demo if e["skill"] == "React")
    assert react_ev["evidenceType"] == "demonstrated"
    assert react_ev["confidence"] >= 0.85
    assert react_ev["source"] == "notion"
    assert react_ev["sourcePageId"] == "p-demo"
    assert "useState" in react_ev["topics"]

    # 2. Implemented: Code blocks with implementation
    impl_blocks = [
        {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "REST APIs Dependency Injection"}]}},
        {"type": "code", "code": {"language": "python", "rich_text": [{"plain_text": "@app.get('/items')\ndef get_items(db: Session = Depends(get_db)): return db.query(Item).all()"}]}},
    ]
    ev_impl = notion_service.extract_learning_evidence_from_page(
        page_id="p-impl",
        page_title="REST APIs Architecture",
        page_url="https://notion.so/p-impl",
        blocks=impl_blocks,
    )
    api_ev = next(e for e in ev_impl if e["skill"] in ("REST APIs", "FastAPI", "Python"))
    assert api_ev["evidenceType"] == "implemented"
    assert api_ev["confidence"] >= 0.78

    # 3. Practiced: Checklists / completed exercises
    practice_blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "DSA Practice"}]}},
        {"type": "to_do", "to_do": {"checked": True, "rich_text": [{"plain_text": "Solved LeetCode 206 Reverse Linked List"}]}},
        {"type": "to_do", "to_do": {"checked": True, "rich_text": [{"plain_text": "Binary search trees exercises completed"}]}},
    ]
    ev_practice = notion_service.extract_learning_evidence_from_page(
        page_id="p-prac",
        page_title="Data Structures & Algorithms Problem Solving",
        page_url="https://notion.so/p-prac",
        blocks=practice_blocks,
    )
    dsa_ev = next(e for e in ev_practice if "Data Structures" in e["skill"])
    assert dsa_ev["evidenceType"] == "practiced"
    assert dsa_ev["confidence"] >= 0.70

    # 4. Studied: Conceptual study notes
    study_blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Docker Architecture Study Notes"}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Detailed overview and study of containerization, image layers, daemon architecture, and multi-stage build concepts."}]}},
    ]
    ev_study = notion_service.extract_learning_evidence_from_page(
        page_id="p-study",
        page_title="Docker Notes",
        page_url="https://notion.so/p-study",
        blocks=study_blocks,
    )
    docker_ev = next(e for e in ev_study if e["skill"] == "Docker")
    assert docker_ev["evidenceType"] == "studied"
    assert docker_ev["confidence"] >= 0.65

    # 5. Mentioned: Wishlist / Backlog / Aspirational
    mention_blocks = [
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Kubernetes wishlist: hoping to learn in the future."}]}},
    ]
    ev_mention = notion_service.extract_learning_evidence_from_page(
        page_id="p-wish",
        page_title="Reading Wishlist",
        page_url="https://notion.so/p-wish",
        blocks=mention_blocks,
    )
    k8s_ev = next(e for e in ev_mention if e["skill"] == "Kubernetes")
    assert k8s_ev["evidenceType"] == "mentioned"
    assert k8s_ev["confidence"] <= 0.45


# ---------------------------------------------------------------------------
# 7. Evidence Provenance & Aggregation Non-Destructive Invariance
# ---------------------------------------------------------------------------

def test_notion_evidence_aggregates_cleanly_with_other_sources():
    """
    Notion evidence must aggregate with GitHub, project, and assessment evidence
    in the unified skill engine without overwriting or destroying other sources.
    """
    github_signal = {
        "skill": "React",
        "source": "github",
        "signal_strength": 0.75,
        "source_reliability": reliability("github"),
    }
    notion_signal = {
        "skill": "React",
        "source": "notion",
        "signal_strength": 0.60,
        "source_reliability": reliability("notion"),
        "metadata": {
            "source": "notion",
            "sourcePageId": "p-123",
            "sourcePageTitle": "React Hooks Notes",
            "sourceUrl": "https://notion.so/p-123",
            "evidenceType": "studied",
            "confidence": 0.78,
        },
    }

    # Combined signals
    combined = [github_signal, notion_signal]
    prof_val, weight, count, avg_sig = proficiency(combined)

    assert count == 2
    # Both sources contributed to weight
    assert weight == pytest.approx(reliability("github") + reliability("notion"))
    assert 0.0 < prof_val <= 1.0

    # Test confidence with multiple source types
    conf, ev_weight, diversity, _ = confidence_from_signals(combined)
    assert diversity == 2.0  # github + notion
    assert conf > 0.0


# ---------------------------------------------------------------------------
# 8. Content Synchronization & Error Handling
# ---------------------------------------------------------------------------

def test_sync_content_flow_and_provenance(monkeypatch):
    """POST /sync must fetch pages, extract evidence, and update status."""
    notion_service.save_integration(
        user_id=USER_A,
        access_token="secret_valid_token",
        workspace_name="Engineering Notes",
    )

    mock_pages = [
        {
            "id": "page-react-101",
            "url": "https://notion.so/page-react-101",
            "properties": {
                "title": {"type": "title", "title": [{"plain_text": "React Custom Hooks Notes"}]}
            },
            "last_edited_time": "2026-09-20T12:00:00Z",
        }
    ]
    mock_blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "React Custom Hooks"}]}},
        {"type": "code", "code": {"language": "typescript", "rich_text": [{"plain_text": "export const useAuth = () => { const [user] = useState(null); return user; };"}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Detailed overview and study of useState and custom hooks."}]}},
    ]

    async def _mock_fetch_pages(token, max_pages=100):
        return mock_pages

    async def _mock_fetch_blocks(token, page_id):
        return mock_blocks

    monkeypatch.setattr(notion_service, "fetch_authorized_pages", _mock_fetch_pages)
    monkeypatch.setattr(notion_service, "fetch_page_blocks", _mock_fetch_blocks)

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=USER_A, email="a@example.com")
    try:
        resp = client.post("/api/integrations/notion/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["pages_scanned"] == 1
        assert data["pages_with_evidence"] == 1
        assert "React" in data["skills_detected"]

        # Check evidence was created with provenance
        ev_list = notion_service._memory_evidence.get(USER_A, [])
        assert len(ev_list) >= 1
        notion_ev = next(e for e in ev_list if e.get("evidence_type") == "notion")
        assert notion_ev["evidence_type"] == "notion"
        assert notion_ev["source_url"] == "https://notion.so/page-react-101"
        assert notion_ev["metadata"]["source"] == "notion"
        assert notion_ev["metadata"]["sourcePageId"] == "page-react-101"
        assert len(notion_ev["metadata"]["verified_signals"]) >= 1
    finally:
        app.dependency_overrides.clear()
        notion_service.disconnect(USER_A)


def test_sync_handles_expired_or_revoked_token(monkeypatch):
    """POST /sync marks integration as reconnect_required when Notion returns 401."""
    notion_service.save_integration(
        user_id=USER_A,
        access_token="secret_expired_token",
        workspace_name="Alice Notes",
    )

    async def _mock_fetch_pages_401(token, max_pages=100):
        raise HTTPException(status_code=401, detail="Notion access token has expired or was revoked.")

    monkeypatch.setattr(notion_service, "fetch_authorized_pages", _mock_fetch_pages_401)

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=USER_A, email="a@example.com")
    try:
        resp = client.post("/api/integrations/notion/sync")
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

        # Status must be updated to reconnect_required
        integration = notion_service.get_integration(USER_A)
        assert integration["status"] == "reconnect_required"
    finally:
        app.dependency_overrides.clear()
        notion_service.disconnect(USER_A)


def test_sync_handles_rate_limiting(monkeypatch):
    """POST /sync returns 429 when Notion API rate limit is exceeded."""
    notion_service.save_integration(
        user_id=USER_A,
        access_token="secret_valid_token",
    )

    async def _mock_fetch_pages_429(token, max_pages=100):
        raise HTTPException(status_code=429, detail="Notion API rate limit exceeded.")

    monkeypatch.setattr(notion_service, "fetch_authorized_pages", _mock_fetch_pages_429)

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=USER_A, email="a@example.com")
    try:
        resp = client.post("/api/integrations/notion/sync")
        assert resp.status_code == 429
        assert "rate limit" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()
        notion_service.disconnect(USER_A)


def test_get_synced_pages_and_excerpt_transparency():
    """Verify that synced Notion pages and extracted skill excerpts are transparently exposed for clarity."""
    # 1. Test excerpt extraction
    sample_text = (
        "In our backend architecture we implemented custom middleware in FastAPI and deployed with Docker containers. "
        "The test suite verified high concurrency benchmarks."
    )
    fastapi_excerpt = notion_service.extract_skill_excerpt(sample_text, "FastAPI")
    assert fastapi_excerpt is not None
    assert "FastAPI" in fastapi_excerpt

    # 2. Simulate synced page in memory
    notion_service.save_integration(
        user_id=USER_A,
        access_token="secret_key_test",
        workspace_name="Engineering Knowledge",
    )
    notion_service._memory_synced_pages[USER_A] = [
        {
            "user_id": USER_A,
            "page_id": "p-docker-101",
            "page_title": "Docker Production Deployment",
            "page_url": "https://notion.so/p-docker-101",
            "last_edited_time": "2026-09-20T10:00:00Z",
            "content_summary": "Extracted 2 skill evidence items: Docker, Linux · 1 code block(s)",
            "skills": ["Docker", "Linux"],
            "headings": ["Production Setup", "Multi-stage Builds"],
            "code_languages": ["dockerfile"],
            "word_count": 320,
            "extracted_evidence": [
                {
                    "skill": "Docker",
                    "canonical_name": "Docker",
                    "evidenceType": "implemented",
                    "confidence": 0.85,
                    "signal_strength": 0.75,
                    "depth": 3,
                    "topics": ["multi-stage build", "docker-compose"],
                    "excerpt": "…configured multi-stage build in Dockerfile for minimal image size…",
                }
            ],
        }
    ]

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=USER_A, email="a@example.com")
    try:
        # Check GET /pages endpoint
        resp_pages = client.get("/api/integrations/notion/pages")
        assert resp_pages.status_code == 200
        pages_data = resp_pages.json()
        assert len(pages_data) == 1
        page = pages_data[0]
        assert page["page_id"] == "p-docker-101"
        assert page["page_title"] == "Docker Production Deployment"
        assert "Docker" in page["skills"]
        assert len(page["extracted_evidence"]) == 1
        ev = page["extracted_evidence"][0]
        assert ev["skill"] == "Docker"
        assert ev["evidenceType"] == "implemented"
        assert "multi-stage build" in ev["topics"]
        assert "multi-stage build in Dockerfile" in ev["excerpt"]

        # Check GET /status also includes synced_pages
        resp_status = client.get("/api/integrations/notion/status")
        assert resp_status.status_code == 200
        status_data = resp_status.json()
        assert status_data["connected"] is True
        assert len(status_data["synced_pages"]) == 1
        assert status_data["synced_pages"][0]["page_title"] == "Docker Production Deployment"
    finally:
        app.dependency_overrides.clear()
        notion_service.disconnect(USER_A)

