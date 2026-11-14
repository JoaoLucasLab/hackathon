"""DATA-06: the audit upload rejects a non-PDF (by file signature, not by name) with
415 and a file over 10 MB with 413, and leaves no file on disk. Chat is limited to 20
messages per 5 minutes per session and upload to 5 per hour: then 429 with a message
the student can read. No Claude call: the parser is never reached, or is replaced."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from tests.student_helpers import script_chat, session_client

from app.api import audit as audit_api
from app.api import limits
from app.contracts import DegreeAudit
from app.main import app
from app.schools.base import get_school

MB = 1024 * 1024


class _Parser:
    """Stands in for the Claude audit parser."""

    def __init__(self) -> None:
        self.calls = 0

    def parse(self, pdf: bytes) -> DegreeAudit:
        from app.api import fixture_data

        self.calls += 1
        return fixture_data.audit()


@pytest.fixture
def parser(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Parser]:
    fake = _Parser()
    monkeypatch.setattr(audit_api, "FEATURE_AUDIT_UPLOAD", True)
    monkeypatch.setattr(get_school("byui"), "audit_parser", fake)
    yield fake


def _upload(client: TestClient, data: bytes, name: str = "audit.pdf") -> int:
    files = {"file": (name, data, "application/pdf")}
    return client.post("/api/audit", files=files).status_code


def _temp_files() -> set[str]:
    return set(os.listdir(tempfile.gettempdir()))


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("audit.pdf", b"PK\x03\x04 a zip file named .pdf"),
        ("audit.pdf", b"<html>not a pdf</html>"),
        ("audit.pdf", b""),
        ("audit.png", b"\x89PNG\r\n\x1a\n"),
    ],
)
def test_a_non_pdf_gets_415(parser: _Parser, name: str, data: bytes) -> None:
    assert _upload(TestClient(app), data, name) == 415
    assert parser.calls == 0


def test_the_signature_decides_not_the_name(parser: _Parser) -> None:
    assert _upload(TestClient(app), b"%PDF-1.7\nsmall audit", "audit.txt") == 200
    assert parser.calls == 1


def test_a_file_over_10_mb_gets_413(parser: _Parser) -> None:
    before = _temp_files()
    assert _upload(TestClient(app), b"%PDF-1.7\n" + b"0" * (10 * MB + 1)) == 413
    assert parser.calls == 0
    assert _temp_files() - before == set()


def test_a_file_just_under_10_mb_is_read_in_memory(parser: _Parser) -> None:
    before = _temp_files()
    assert _upload(TestClient(app), b"%PDF-1.7\n" + b"0" * (10 * MB - 100)) == 200
    assert _temp_files() - before == set()


def test_upload_is_limited_to_5_per_hour(parser: _Parser) -> None:
    client, _ = session_client()
    for _ in range(5):
        assert _upload(client, b"%PDF-1.7\nsmall") == 200
    res = client.post("/api/audit", files={"file": ("a.pdf", b"%PDF-1.7\n", "application/pdf")})
    assert res.status_code == 429
    assert res.json()["detail"] == limits.UPLOAD.message
    assert int(res.headers["retry-after"]) > 0
    assert parser.calls == 5
    # Another session has its own count.
    other, _ = session_client()
    assert _upload(other, b"%PDF-1.7\nsmall") == 200


def test_chat_is_limited_to_20_messages_per_5_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    script_chat(monkeypatch)
    client, _ = session_client()
    for _ in range(20):
        assert client.post("/api/chat", json={"message": "hi"}).status_code == 200
    res = client.post("/api/chat", json={"message": "hi"})
    assert res.status_code == 429
    assert "20 messages" in res.json()["detail"]


def test_the_window_slides(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr("app.api.limits.time.monotonic", lambda: now[0])
    script_chat(monkeypatch)
    client, _ = session_client()
    for _ in range(20):
        assert client.post("/api/chat", json={"message": "hi"}).status_code == 200
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 429
    now[0] += 5 * 60
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 200


def test_made_up_cookies_do_not_reset_the_count(monkeypatch: pytest.MonkeyPatch) -> None:
    script_chat(monkeypatch)
    client = TestClient(app)
    for i in range(20):
        client.cookies.set("sid", f"made-up-{i}")
        assert client.post("/api/chat", json={"message": "hi"}).status_code == 200
    client.cookies.set("sid", "made-up-again")
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 429
