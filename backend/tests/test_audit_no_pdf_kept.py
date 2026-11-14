"""AI-04: the audit PDF is sent to Claude once and never written to disk, the store
or a log. Upload endpoint behavior on recorded Claude replies (no network)."""

from __future__ import annotations

import base64
import builtins
import json
import logging
import tempfile
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import audit as audit_api
from app.api import audit_store, fixture_data
from app.main import app
from app.schools.base import get_school
from app.schools.byui.audit_parser import ByuiAuditParser

SID = "test-no-pdf"
MARKER = b"UNIQUE-PDF-MARKER-7f3a"
# Above Starlette's default 1 MB spool size, so a default parser would use a temp file.
PDF = b"%PDF-1.7\n" + MARKER + b"\n" + b"0" * (2 * 1024 * 1024)


class Recorded:
    def __init__(self, replies: list[str | None]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, params: dict[str, Any]) -> str | None:
        self.requests.append(params)
        return self.replies.pop(0)


def _reply() -> str:
    raw = fixture_data.audit().model_dump(mode="json")
    raw.pop("validation_flags")
    raw["audit_date"] = date.today().isoformat()
    return json.dumps({"readable": True, "audit": raw})


@pytest.fixture
def api() -> Iterator[TestClient]:
    client = TestClient(app)
    client.cookies.set("sid", SID)
    yield client
    audit_store.forget(SID)


@pytest.fixture
def upload_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_api, "FEATURE_AUDIT_UPLOAD", True)


def _use_caller(monkeypatch: pytest.MonkeyPatch, caller: Recorded) -> None:
    monkeypatch.setattr(get_school("byui"), "audit_parser", ByuiAuditParser(caller=caller))


@pytest.fixture
def no_disk_writes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fails any attempt to write a file or create a temporary file."""
    attempts: list[str] = []
    real_open = builtins.open

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(m in mode for m in "wax+"):
            attempts.append(f"open({file!r}, {mode!r})")
            raise AssertionError(f"file write attempted: {file!r}")
        return real_open(file, mode, *args, **kwargs)

    def refuse(name: str) -> Any:
        def _refuse(*_a: Any, **_k: Any) -> Any:
            attempts.append(name)
            raise AssertionError(f"{name} called")

        return _refuse

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", refuse("rollover"))
    for name in ("mkstemp", "NamedTemporaryFile", "TemporaryFile", "mkdtemp"):
        monkeypatch.setattr(tempfile, name, refuse(name))
    return attempts


def _post(api: TestClient, data: bytes = PDF, name: str = "audit.pdf") -> Any:
    return api.post("/api/audit", files={"file": (name, data, "application/pdf")})


def test_upload_parses_without_touching_disk_and_sends_pdf_once(
    api: TestClient,
    upload_on: None,
    no_disk_writes: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caller = Recorded([_reply()])
    _use_caller(monkeypatch, caller)
    caplog.set_level(logging.DEBUG)

    res = _post(api)

    assert res.status_code == 200, res.text
    assert no_disk_writes == []
    assert len(caller.requests) == 1
    encoded = base64.standard_b64encode(PDF).decode("ascii")
    sent = caller.requests[0]["messages"][0]["content"][0]["source"]["data"]
    assert sent == encoded
    assert MARKER.decode() not in res.text
    assert MARKER.decode() not in caplog.text
    assert encoded[:200] not in caplog.text


def test_upload_does_not_store_until_confirmed(
    api: TestClient, upload_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_caller(monkeypatch, Recorded([_reply()]))
    parsed = _post(api).json()
    parsed["major"] = "Confirmed Major (BS)"
    assert audit_store.get(SID).major == fixture_data.audit().major

    assert api.put("/api/audit", json=parsed).status_code == 200
    stored = audit_store.get(SID).model_dump_json()
    assert "Confirmed Major (BS)" in stored
    assert MARKER.decode() not in stored
    assert base64.standard_b64encode(PDF).decode("ascii")[:200] not in stored


def test_upload_is_off_by_default(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_api, "FEATURE_AUDIT_UPLOAD", False)
    assert _post(api).status_code == 404


def test_not_a_pdf_is_refused_before_claude(
    api: TestClient, upload_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller = Recorded([])
    _use_caller(monkeypatch, caller)
    res = _post(api, data=b"just text", name="audit.txt")
    assert res.status_code == 415
    assert caller.requests == []


def test_file_over_10_mb_is_refused_before_claude(
    api: TestClient, upload_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller = Recorded([])
    _use_caller(monkeypatch, caller)
    res = _post(api, data=b"%PDF-1.7\n" + b"0" * (audit_api.AUDIT_MAX_BYTES + 1))
    assert res.status_code == 413
    assert caller.requests == []


def test_two_failed_parses_answer_422_with_a_clear_message(
    api: TestClient, upload_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = json.dumps({"readable": True, "audit": {"major": "x"}})
    caller = Recorded([bad, bad])
    _use_caller(monkeypatch, caller)
    res = _post(api)
    assert res.status_code == 422
    assert res.json()["detail"] == "We couldn't read this audit."
    assert len(caller.requests) == 2
    # The retry carries only the rejected JSON, never the PDF.
    assert "document" not in json.dumps(caller.requests[1]["messages"])
