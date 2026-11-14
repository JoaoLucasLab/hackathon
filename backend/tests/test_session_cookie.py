"""DATA-01: the first request gets a signed, HttpOnly `sid` cookie; the second request
with it reaches the same `students` row. No name, email or password is asked.

Runs on the in-memory database (no DATABASE_URL in tests). test_migrations.py runs the
same two requests on Postgres.
"""

from __future__ import annotations

import uuid
from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from app.api import session as session_api
from app.contracts import SessionRequest
from app.db import engine
from app.db.models import Student
from app.main import app

FORBIDDEN = ("name", "email", "password", "byui_id", "student_number", "inumber")


def _client() -> TestClient:
    # https: the cookie is Secure, so the test client only sends it back over https.
    return TestClient(app, base_url="https://testserver")


def _student_count() -> int:
    with engine.session() as db:
        return db.scalar(select(func.count()).select_from(Student)) or 0


def _sid_cookie(set_cookie: str) -> SimpleCookie:
    cookie = SimpleCookie()
    cookie.load(set_cookie)
    assert "sid" in cookie
    return cookie


def test_first_request_gets_a_signed_httponly_cookie() -> None:
    res = _client().post("/api/session", json={"consent": True})
    assert res.status_code == 200
    header = res.headers["set-cookie"]
    morsel = _sid_cookie(header)["sid"]
    assert morsel["httponly"] is True
    assert morsel["secure"] is True
    assert morsel["samesite"].lower() == "lax"
    assert morsel["path"] == "/"
    student_id = res.json()["student"]["id"]
    assert morsel.value != student_id  # signed, not the bare id
    assert session_api.unsign(morsel.value) == uuid.UUID(student_id)


def test_second_request_reaches_the_same_student_row() -> None:
    client = _client()
    first = client.post("/api/session", json={"consent": True}).json()["student"]
    before = _student_count()
    second = client.post("/api/session", json={"consent": True})
    assert second.json()["student"]["id"] == first["id"]
    assert "set-cookie" not in second.headers  # the cookie is kept, not replaced
    assert _student_count() == before
    with engine.session() as db:
        row = db.get(Student, uuid.UUID(first["id"]))
    assert row is not None
    assert row.consented_at is not None


def test_consent_time_is_stored_once() -> None:
    client = _client()
    first = client.post("/api/session", json={"consent": True}).json()["student"]
    again = client.post("/api/session", json={"consent": True}).json()["student"]
    assert first["consented_at"] is not None
    assert again["consented_at"] == first["consented_at"]


def test_no_consent_leaves_it_empty() -> None:
    student = _client().post("/api/session", json={"consent": False}).json()["student"]
    assert student["consented_at"] is None


@pytest.mark.parametrize(
    "cookie",
    [
        "not-a-session",
        f"{uuid.uuid4()}.forged-signature",
        # Well signed, but its row does not exist (deleted, or another database).
        session_api.sign(str(uuid.uuid4())),
    ],
)
def test_a_bad_or_unknown_cookie_gets_a_new_session(cookie: str) -> None:
    client = _client()
    client.cookies.set("sid", cookie, domain="testserver")
    res = client.post("/api/session", json={"consent": True})
    assert res.status_code == 200
    new = _sid_cookie(res.headers["set-cookie"])["sid"].value
    assert new != cookie
    assert session_api.unsign(new) == uuid.UUID(res.json()["student"]["id"])


def test_cookie_is_not_sent_over_plain_http() -> None:
    """Secure: a browser (and the test client) keeps it to https."""
    client = TestClient(app, base_url="http://testserver")
    first = client.post("/api/session", json={"consent": True}).json()["student"]
    second = client.post("/api/session", json={"consent": True}).json()["student"]
    assert first["id"] != second["id"]


def test_samesite_follows_cookie_samesite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_api, "_samesite", "none")
    res = _client().post("/api/session", json={"consent": True})
    assert _sid_cookie(res.headers["set-cookie"])["sid"]["samesite"].lower() == "none"


def test_nothing_personal_is_asked_or_stored() -> None:
    assert set(SessionRequest.model_fields) == {"consent"}
    columns = {c["name"] for c in inspect(engine.engine()).get_columns("students")}
    assert not [c for c in columns if any(word in c for word in FORBIDDEN)], columns
