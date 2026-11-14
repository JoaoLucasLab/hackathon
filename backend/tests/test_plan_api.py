"""AI-08: `GET/PUT/DELETE /api/plan`, the chat history and `DELETE /api/me`."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import audit_store
from app.api import chat as chat_api
from app.api import schedules as schedules_api
from app.contracts import ChatHistory, ChatTurn, Schedule
from app.llm import tools
from app.llm.chat import ChatSession, TurnResult, run_turn
from app.main import app

client = TestClient(app)
SID = "local"  # the session id when the request has no `sid` cookie

CONSTRAINTS: dict[str, Any] = {
    "credit_min": 12,
    "credit_max": 15,
    "earliest_start": None,
    "latest_end": None,
    "days_off": [],
    "include_courses": [],
    "exclude_courses": [],
    "exclude_section_ids": [],
    "delivery_methods": [],
    "only_required": False,
    "allow_waitlist": False,
    "only_favorite_professors": False,
}
BUILD = {
    "constraints": CONSTRAINTS,
    "avoid_schedules": [],
    "intake": {"track": None, "use_default_credits": False, "student_agreed": True},
}


@pytest.fixture(autouse=True)
def clean_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(config, "FEATURE_CONVERSATIONAL_PLANNER", True)
    chat_api.forget(SID)
    schedules_api.forget_plan(SID)
    yield
    chat_api.forget(SID)
    schedules_api.forget_plan(SID)


def _show_a_schedule() -> str:
    """Build one schedule through the chat tool, in the endpoint's own session."""
    ctx = chat_api._sessions.setdefault(
        SID,
        ChatSession(
            ctx=tools.ToolContext(
                audit=audit_store.get(SID), plan=schedules_api.plan_for(SID)
            )
        ),
    ).ctx
    ctx.intake.student_turns = 2  # past the first-message gate
    result = tools.run_tool(ctx, "build_schedules", BUILD)
    return str(result["schedules"][0]["id"])


def test_no_plan_is_404() -> None:
    assert client.get("/api/plan").status_code == 404


def test_put_before_any_schedule_is_409() -> None:
    response = client.put("/api/plan", json={"schedule_id": "sch-nothing"})
    assert response.status_code == 409
    assert client.get("/api/plan").status_code == 404


def test_put_confirms_only_the_schedule_shown_last() -> None:
    first = _show_a_schedule()
    second = _show_a_schedule()
    assert first != second

    assert client.put("/api/plan", json={"schedule_id": first}).status_code == 409
    assert client.put("/api/plan", json={"schedule_id": "sch-made-up"}).status_code == 409
    assert client.get("/api/plan").status_code == 404

    response = client.put("/api/plan", json={"schedule_id": second})
    assert response.status_code == 200
    plan = Schedule.model_validate(response.json())
    assert plan.id == second
    assert plan.advising_note == "Confirm with BYU-Idaho Academic Advising."
    assert Schedule.model_validate(client.get("/api/plan").json()) == plan


def test_tool_and_endpoint_share_the_plan() -> None:
    shown = _show_a_schedule()
    ctx = chat_api._sessions[SID].ctx
    tools.run_tool(ctx, "confirm_schedule", {"schedule_id": shown})
    assert client.get("/api/plan").json()["id"] == shown


def test_delete_plan_clears_it_and_keeps_the_conversation() -> None:
    shown = _show_a_schedule()
    client.put("/api/plan", json={"schedule_id": shown})
    assert client.delete("/api/plan").status_code == 204
    assert client.get("/api/plan").status_code == 404
    # The schedule is still the one shown last, so it can be confirmed again.
    assert client.put("/api/plan", json={"schedule_id": shown}).status_code == 200


def test_delete_me_clears_the_plan_and_the_chat() -> None:
    shown = _show_a_schedule()
    client.put("/api/plan", json={"schedule_id": shown})
    chat_api._sessions[SID].transcript.append(
        ChatTurn(role="student", text="12 to 15 credits")
    )
    assert client.delete("/api/me").status_code == 204
    assert client.get("/api/plan").status_code == 404
    assert client.get("/api/chat/history").json() == {"turns": []}
    assert client.put("/api/plan", json={"schedule_id": shown}).status_code == 409


def test_clearing_the_chat_starts_over_and_keeps_the_plan() -> None:
    shown = _show_a_schedule()
    client.put("/api/plan", json={"schedule_id": shown})
    session = chat_api._sessions[SID]
    session.transcript.append(ChatTurn(role="student", text="12 to 15 credits"))
    session.history.append({"role": "user", "content": "12 to 15 credits"})

    assert client.delete("/api/chat/history").status_code == 204
    assert client.get("/api/chat/history").json() == {"turns": []}
    assert chat_api._sessions[SID].history == []  # Claude starts fresh too
    # The confirmed plan is not part of the conversation: it stays until a new one.
    assert client.get("/api/plan").json()["id"] == shown


def _scripted(*responses: list[dict[str, Any]]) -> Any:
    calls = iter(responses)

    def caller(params: dict[str, Any]) -> Iterator[str | TurnResult]:
        content = next(calls)
        for block in content:
            if block["type"] == "text":
                yield block["text"]
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        yield TurnResult(content=content, stop_reason=stop)

    return caller


def test_history_keeps_the_conversation_and_the_card_for_a_reload() -> None:
    session = chat_api._sessions.setdefault(
        SID,
        ChatSession(
            ctx=tools.ToolContext(
                audit=audit_store.get(SID), plan=schedules_api.plan_for(SID)
            )
        ),
    )
    list(
        run_turn(
            session,
            "12 to 15 credits",
            _scripted(
                [
                    {
                        "type": "text",
                        "text": "Should I build a schedule with these?\n"
                        "<<choices: Build it | Change something>>",
                    }
                ]
            ),
        )
    )
    list(
        run_turn(
            session,
            "Build it",
            _scripted(
                [
                    {"type": "text", "text": "Building."},
                    {"type": "tool_use", "id": "t1", "name": "build_schedules", "input": BUILD},
                ],
                [{"type": "text", "text": "Does this schedule work for you?"}],
            ),
        )
    )

    history = ChatHistory.model_validate(client.get("/api/chat/history").json())
    assert [t.role for t in history.turns] == ["student", "assistant", "student", "assistant"]
    question, answer = history.turns[1], history.turns[3]
    assert question.text == "Should I build a schedule with these?"
    assert question.quick_replies == ["Build it", "Change something"]
    assert question.schedule is None
    assert history.turns[2].text == "Build it"
    assert answer.text == "Building.\n\nDoes this schedule work for you?"
    assert answer.schedule is not None and answer.option == 1
    assert answer.quick_replies == []  # the card has its own two replies
    assert answer.schedule.id == schedules_api.plan_for(SID).shown[-1].id
