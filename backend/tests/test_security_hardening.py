"""Ownership checks on writes by row id, upload sniffing, and the Notion callback's redirect.

The backend talks to Supabase with the service-role key, which skips row-level security, so
every read or write addressed by a row id has to prove the row is the caller's itself.
"""
import pytest
from fastapi import HTTPException


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.patch = None
        self.single_row = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _n):
        return self

    def single(self):
        self.single_row = True
        return self

    def update(self, patch):
        self.patch = patch
        return self

    def execute(self):
        hits = [r for r in self.rows if all(r.get(c) == v for c, v in self.filters)]
        if self.patch is not None:
            for r in hits:
                r.update(self.patch)
        if self.single_row:
            return _Result(hits[0] if hits else None)
        return _Result(hits)


class _Client:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Query(self.tables.setdefault(name, []))


@pytest.fixture
def roadmap_db(monkeypatch):
    from app.services import roadmap_service as rs

    tables = {
        "roadmaps": [{"id": "rm-a", "user_id": "alice"}],
        "roadmap_weeks": [{"id": "wk-a", "roadmap_id": "rm-a", "week_number": 1}],
        # No embedded join comes back from this fake, like a PostgREST response without it
        "roadmap_tasks": [
            {"id": "t-a", "roadmap_week_id": "wk-a", "status": "not_started", "completion_percentage": 0},
            {"id": "t-orphan", "roadmap_week_id": None, "status": "not_started", "completion_percentage": 0},
        ],
        "roadmap_items": [{"id": "i-a", "roadmap_id": "rm-a", "status": "not_started", "completion_percentage": 0}],
    }
    monkeypatch.setattr(rs, "_client", lambda: _Client(tables))
    return rs, tables


def test_owner_can_update_their_task(roadmap_db):
    rs, tables = roadmap_db
    rs.update_roadmap_task("alice", "t-a", {"status": "completed"})
    assert tables["roadmap_tasks"][0]["status"] == "completed"


def test_someone_else_cannot_update_a_task(roadmap_db):
    rs, tables = roadmap_db
    with pytest.raises(HTTPException) as exc:
        rs.update_roadmap_task("mallory", "t-a", {"status": "completed"})
    assert exc.value.status_code == 403
    assert tables["roadmap_tasks"][0]["status"] == "not_started"


def test_a_task_with_no_provable_owner_is_refused(roadmap_db):
    rs, tables = roadmap_db
    with pytest.raises(HTTPException) as exc:
        rs.update_roadmap_task("alice", "t-orphan", {"status": "completed"})
    assert exc.value.status_code == 403
    assert tables["roadmap_tasks"][1]["status"] == "not_started"


def test_someone_else_cannot_update_an_item(roadmap_db):
    rs, tables = roadmap_db
    with pytest.raises(HTTPException) as exc:
        rs.update_roadmap_item("mallory", "i-a", {"completion_percentage": 100})
    assert exc.value.status_code == 403
    assert tables["roadmap_items"][0]["completion_percentage"] == 0


def test_someone_elses_week_reads_as_not_found(roadmap_db):
    rs, _ = roadmap_db
    assert rs.get_roadmap_week("alice", "wk-a")["id"] == "wk-a"
    with pytest.raises(HTTPException) as exc:
        rs.get_roadmap_week("mallory", "wk-a")
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "content, expected",
    [
        (b"%PDF-1.7\n...", ".pdf"),
        (b"\n\n%PDF-1.4 with a stray preamble", ".pdf"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, ".doc"),
        (b"PK\x03\x04" + b"\x00" * 26 + b"[Content_Types].xml ... word/document.xml", ".docx"),
        (b"PK\x03\x04 just some other zip", None),
        (b"<html><script>alert(1)</script></html>", None),
        (b"MZ\x90\x00 an executable", None),
    ],
)
def test_uploads_are_judged_by_their_bytes(content, expected):
    from app.services.evidence_service import sniff_document_type

    assert sniff_document_type(content) == expected


def test_notion_callback_never_reflects_raw_error_text(monkeypatch):
    import asyncio
    from app.api.v1.endpoints import notion

    response = asyncio.run(notion.notion_callback(code=None, state=None, error="access_denied&next=https://evil.example/#x"))
    location = response.headers["location"]
    assert "/analysis?notion_error=access_denied" in location
    assert "evil.example" not in location
    assert "&next=" not in location
