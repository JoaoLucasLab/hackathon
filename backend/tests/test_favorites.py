"""AI-03: starring a professor persists for the session, and the chat tool and
the API see the same stars."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.api import professors as professors_api
from app.llm import tools
from app.main import app


@pytest.fixture(autouse=True)
def _fresh_sessions() -> Iterator[None]:
    professors_api._favorites.clear()
    chat_api._sessions.clear()
    yield
    professors_api._favorites.clear()
    chat_api._sessions.clear()


def _starred(api: TestClient) -> set[str]:
    return {p["id"] for p in api.get("/api/professors").json() if p["is_favorite"]}


def test_star_persists_across_requests() -> None:
    api = TestClient(app)
    assert api.put("/api/professors/p-hale/favorite", json={"favorite": True}).status_code == 200
    # A reload is a fresh request with the same session cookie.
    assert _starred(TestClient(app)) == {"p-hale"}
    assert TestClient(app).get("/api/professors/p-hale").json()["is_favorite"] is True
    api.put("/api/professors/p-hale/favorite", json={"favorite": False})
    assert _starred(api) == set()


def test_unknown_professor_is_404() -> None:
    api = TestClient(app)
    assert api.put("/api/professors/nobody/favorite", json={"favorite": True}).status_code == 404


def test_sessions_keep_their_own_stars() -> None:
    a, b = TestClient(app, cookies={"sid": "a"}), TestClient(app, cookies={"sid": "b"})
    a.put("/api/professors/p-okafor/favorite", json={"favorite": True})
    assert _starred(a) == {"p-okafor"}
    assert _starred(b) == set()


def test_chat_tool_and_api_share_stars() -> None:
    api = TestClient(app)
    api.put("/api/professors/p-reyes/favorite", json={"favorite": True})
    api.get("/api/constraints")  # opens the chat session for this cookie
    session = chat_api._sessions["local"]
    assert "p-reyes" in session.ctx.favorite_professor_ids
    tools.run_tool(
        session.ctx, "toggle_favorite_professor", {"professor_id": "p-hale", "favorite": True}
    )
    assert _starred(api) == {"p-reyes", "p-hale"}
