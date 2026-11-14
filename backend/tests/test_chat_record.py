"""Re-record the Claude conversations the AI-02 tests replay. Live, by hand only:

    set -a; source .env; set +a
    pytest -m live backend/tests/test_chat_record.py

Run it again after changing the system prompt or a tool, then re-run pytest.
"""

from __future__ import annotations

import json

import pytest
from tests.chat_harness import (
    ALL_SCENARIOS,
    RECORDINGS,
    RecordingCaller,
    Scenario,
    make_session,
    recording_path,
    run,
)

from app.llm import client

pytestmark = pytest.mark.live


@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=[s.id for s in ALL_SCENARIOS])
def test_record(scenario: Scenario, monkeypatch: pytest.MonkeyPatch) -> None:
    if not client.is_configured():
        pytest.skip("ANTHROPIC_API_KEY not set")
    caller = RecordingCaller()
    transcript = run(make_session(scenario, monkeypatch), scenario, caller)
    assert transcript.events[-1].type == "done"
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    recording_path(scenario.id).write_text(
        json.dumps(
            {"id": scenario.id, "messages": scenario.messages, "calls": caller.calls},
            indent=2,
        )
        + "\n"
    )
