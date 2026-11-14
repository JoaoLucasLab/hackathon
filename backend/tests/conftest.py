"""Importing the app registers the school (BYU-Idaho rules), as at startup.

Tests that call API functions directly (without a TestClient) need it too.
"""

import os

import pytest

# Tests run on the fixtures, never on a real database (CI has no Postgres), even
# when a developer's shell has DATABASE_URL set. See app/api/catalog_data.py.
os.environ.pop("DATABASE_URL", None)

import app.main  # noqa: E402, F401
from app.llm import client as llm_client  # noqa: E402
from app.llm import mentor_text  # noqa: E402


@pytest.fixture(autouse=True)
def _no_live_mentor_text(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mentor text endpoints fall back to their no-Claude text in tests, even when a
    developer has ANTHROPIC_API_KEY set. Tests marked `live` are left alone."""
    if request.node.get_closest_marker("live"):
        return

    def _blocked() -> None:
        raise llm_client.ClaudeNotConfiguredError("No live Claude calls in tests.")

    monkeypatch.setattr(mentor_text, "_api", _blocked)
    mentor_text._cache.clear()
