"""Helpers for the DATA-06 tests: a client with a signed session (so its data is
stored in the in-memory database), a chat turn with no Claude call, and raw reads
of the stored columns."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.contracts import ChatEvent, ChatTurn
from app.db import engine
from app.llm import chat as llm_chat
from app.main import app

REPLY = "CSE 210 fits your Tuesday and Thursday mornings."


def session_client() -> tuple[TestClient, uuid.UUID]:
    """A client with a new signed `sid` cookie, and its student id. https: the cookie
    is Secure, so the test client only sends it back over https."""
    client = TestClient(app, base_url="https://testserver")
    res = client.post("/api/session", json={"consent": True})
    assert res.status_code == 200
    return client, uuid.UUID(res.json()["student"]["id"])


def script_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every chat turn answers REPLY without calling Claude."""

    def run_turn(
        session: llm_chat.ChatSession, message: str, _caller: object
    ) -> Iterator[ChatEvent]:
        session.transcript += [
            ChatTurn(role="student", text=message),
            ChatTurn(role="assistant", text=REPLY),
        ]
        yield ChatEvent(type="text", text=REPLY)
        yield ChatEvent(type="done")

    monkeypatch.setattr(llm_chat, "run_turn", run_turn)


def raw_column(table: str, column: str, student_id: uuid.UUID) -> list[bytes]:
    """The stored bytes, read with plain SQL as from a copy of the database."""
    with engine.engine().connect() as conn:
        rows = conn.execute(
            text(f"SELECT {column} FROM {table} WHERE student_id = :s ORDER BY id"),
            {"s": student_id.hex},  # SQLite stores a Uuid as 32 hex digits
        ).all()
    return [bytes(r[0]) for r in rows]


def row_count(table: str, student_id: uuid.UUID) -> int:
    column = "id" if table == "students" else "student_id"
    with engine.engine().connect() as conn:
        return int(
            conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :s"), {"s": student_id.hex}
            ).scalar_one()
        )
