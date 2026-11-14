"""DATA-06: `DELETE /api/me` removes the audit, chats, constraints, favorites and the
student row. The same cookie then gets 404 from GET /api/requirements/remaining."""

from __future__ import annotations

import json

import pytest
from tests.student_helpers import row_count, script_chat, session_client

from app.api import session as session_api
from app.config import FIXTURES_DIR

STUDENT_TABLES = ("audits", "chats", "constraints", "favorites", "students")


def _fill(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """A session with a row in every student table."""
    script_chat(monkeypatch)
    client, student_id = session_client()
    audit = json.loads((FIXTURES_DIR / "audit.json").read_text())
    assert client.put("/api/audit", json=audit).status_code == 200
    assert client.post("/api/chat", json={"message": "Mornings only"}).status_code == 200
    constraints = client.get("/api/constraints").json()
    assert client.put("/api/constraints", json=constraints).status_code == 200
    professor_id = client.get("/api/professors").json()[0]["id"]
    res = client.put(f"/api/professors/{professor_id}/favorite", json={"favorite": True})
    assert res.status_code == 200
    for table in STUDENT_TABLES:
        assert row_count(table, student_id) >= 1, table
    return client, student_id


def test_delete_removes_every_student_table_row(monkeypatch: pytest.MonkeyPatch) -> None:
    client, student_id = _fill(monkeypatch)
    res = client.delete("/api/me")
    assert res.status_code == 204
    for table in STUDENT_TABLES:
        assert row_count(table, student_id) == 0, table


def test_the_same_cookie_then_gets_404(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _fill(monkeypatch)
    cookie = client.cookies["sid"]
    assert client.get("/api/requirements/remaining").status_code == 200
    assert client.delete("/api/me").status_code == 204
    client.cookies.set("sid", cookie)  # the browser was told to drop it; send it anyway
    res = client.get("/api/requirements/remaining")
    assert res.status_code == 404
    assert res.json()["detail"] == session_api.SESSION_GONE
    # Nor does the deleted session come back through another endpoint.
    assert client.get("/api/chat/history").status_code == 404
    assert client.get("/api/professors").status_code == 404


def test_delete_asks_the_browser_to_drop_the_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _fill(monkeypatch)
    header = client.delete("/api/me").headers["set-cookie"]
    assert header.startswith('sid=""') and "Max-Age=0" in header


def test_delete_is_idempotent_and_a_new_session_starts_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, old_id = _fill(monkeypatch)
    cookie = client.cookies["sid"]
    assert client.delete("/api/me").status_code == 204
    client.cookies.set("sid", cookie)
    assert client.delete("/api/me").status_code == 204
    new = client.post("/api/session", json={"consent": True}).json()["student"]["id"]
    assert new != str(old_id)
    assert client.get("/api/requirements/remaining").status_code == 200
    assert client.get("/api/chat/history").json() == {"turns": []}


def test_the_store_survives_a_restart_until_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The memory copies are gone after a restart; the stored data brings them back."""
    from app.api import audit_store, chat, professors

    client, _ = _fill(monkeypatch)
    sid = client.cookies["sid"]
    for forget in (audit_store.forget, chat.forget, professors.forget):
        forget(sid)
    history = client.get("/api/chat/history").json()["turns"]
    assert [t["role"] for t in history] == ["student", "assistant"]
    assert any(p["is_favorite"] for p in client.get("/api/professors").json())


def test_clearing_the_chat_also_clears_what_is_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    """DELETE /api/chat/history (AI-08) on a stored session: the messages and rules are
    deleted, not only forgotten in memory, so they do not come back after a restart."""
    from app.api import chat

    client, student_id = _fill(monkeypatch)
    assert client.delete("/api/chat/history").status_code == 204
    assert row_count("chats", student_id) == 0
    assert row_count("constraints", student_id) == 0
    assert row_count("audits", student_id) == 1  # the audit and favorites stay
    assert row_count("favorites", student_id) == 1
    chat.forget(client.cookies["sid"])  # as after a restart
    assert client.get("/api/chat/history").json() == {"turns": []}
