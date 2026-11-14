"""AI-08: the `confirm_schedule` tool, and when the assistant uses it.

The first half runs the tool directly. The second half replays recorded Claude
conversations through the real turn loop (record them by hand, live:
`pytest -m live backend/tests/test_chat_record.py -k loop`).
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.chat_harness import (
    LOOP_CONFIRM,
    LOOP_CONFIRM_THEN_CHANGE,
    LOOP_NOT_A_YES,
    builds,
    replay,
    tool_results,
    turn_text,
)

from app import config
from app.api import fixture_data
from app.llm import tools

SAVED = (
    "Saved as your Winter 2027 plan. This does not register you for classes. "
    "Confirm with BYU-Idaho Academic Advising."
)
ASK = "Does this schedule work for you?"

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
NINE = [
    "get_remaining_requirements",
    "search_sections",
    "check_prerequisites",
    "build_schedules",
    "get_professor_profile",
    "toggle_favorite_professor",
    "find_mentors",
    "draft_outreach_email",
    "confirm_schedule",
]


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> tools.ToolContext:
    monkeypatch.setattr(config, "FEATURE_CONVERSATIONAL_PLANNER", True)
    ctx = tools.ToolContext(audit=fixture_data.audit())
    ctx.intake.student_turns = 2  # past the first-message gate
    return ctx


def _build(ctx: tools.ToolContext) -> dict[str, Any]:
    return tools.run_tool(ctx, "build_schedules", BUILD)


# --- The tool ----------------------------------------------------------------------


def test_ninth_tool_only_with_the_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "FEATURE_CONVERSATIONAL_PLANNER", True)
    assert [d["name"] for d in tools.tool_definitions()] == NINE
    monkeypatch.setattr(config, "FEATURE_CONVERSATIONAL_PLANNER", False)
    assert [d["name"] for d in tools.tool_definitions()] == NINE[:-1]
    with pytest.raises(tools.ToolInputError, match="Unknown tool"):
        tools.run_tool(
            tools.ToolContext(audit=fixture_data.audit()),
            "confirm_schedule",
            {"schedule_id": "sch-x"},
        )


def test_schema_is_strict() -> None:
    definition = tools.CONFIRM_SCHEDULE.definition()
    schema = tools.CONFIRM_SCHEDULE.input_schema
    assert definition["strict"] is True
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["schedule_id"] == list(schema["properties"])


def test_confirms_the_schedule_shown_last(ctx: tools.ToolContext) -> None:
    shown = _build(ctx)["schedules"][0]
    result = tools.run_tool(ctx, "confirm_schedule", {"schedule_id": shown["id"]})
    assert result["confirmed"] is True
    assert result["registered"] is False
    assert result["advising_note"] == "Confirm with BYU-Idaho Academic Advising."
    assert ctx.plan.confirmed is not None and ctx.plan.confirmed.id == shown["id"]


@pytest.mark.parametrize("bad_id", ["sch-made-up", "OLDER"])
def test_any_other_id_is_an_error(ctx: tools.ToolContext, bad_id: str) -> None:
    older = _build(ctx)["schedules"][0]["id"]
    latest = _build(ctx)["schedules"][0]["id"]
    assert older != latest
    with pytest.raises(tools.ToolExecutionError, match="shown last"):
        tools.run_tool(
            ctx, "confirm_schedule", {"schedule_id": older if bad_id == "OLDER" else bad_id}
        )
    assert ctx.plan.confirmed is None


def test_nothing_shown_yet_is_an_error(ctx: tools.ToolContext) -> None:
    with pytest.raises(tools.ToolExecutionError, match="No schedule has been shown"):
        tools.run_tool(ctx, "confirm_schedule", {"schedule_id": "sch-x"})


def test_extra_field_rejected(ctx: tools.ToolContext) -> None:
    with pytest.raises(tools.ToolInputError, match="student_name"):
        tools.run_tool(ctx, "confirm_schedule", {"schedule_id": "sch-x", "student_name": "x"})


def test_plan_stays_until_a_new_one_is_confirmed(ctx: tools.ToolContext) -> None:
    first = _build(ctx)["schedules"][0]["id"]
    tools.run_tool(ctx, "confirm_schedule", {"schedule_id": first})
    second = _build(ctx)["schedules"][0]["id"]
    assert ctx.plan.confirmed is not None and ctx.plan.confirmed.id == first
    tools.run_tool(ctx, "confirm_schedule", {"schedule_id": second})
    assert ctx.plan.confirmed.id == second


def test_a_shown_schedule_never_comes_back_even_if_the_model_lists_none(
    ctx: tools.ToolContext,
) -> None:
    seen: list[frozenset[str]] = []
    for option in range(1, 5):
        result = _build(ctx)  # avoid_schedules is empty every time
        schedule = result["schedules"][0]
        ids = frozenset(c["section"]["id"] for c in schedule["classes"])
        assert ids not in seen
        assert result["option"] == option
        seen.append(ids)
    changes = result["changed_from_previous"]
    assert changes["added_section_ids"] or changes["removed_section_ids"]


def test_first_schedule_has_nothing_to_compare(ctx: tools.ToolContext) -> None:
    assert _build(ctx)["changed_from_previous"] is None


# --- When the assistant confirms (recorded conversations) ----------------------------


def test_a_clear_yes_confirms_and_says_it_does_not_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transcript = replay(LOOP_CONFIRM, monkeypatch)
    shown = builds(transcript.turns[1])[0]["schedules"][0]
    last = transcript.turns[2]
    (confirmed,) = tool_results(last, "confirm_schedule")
    assert confirmed["schedule_id"] == shown["id"]
    assert SAVED in turn_text(last)
    assert not builds(last)
    assert session.ctx.plan.confirmed is not None
    assert session.ctx.plan.confirmed.id == shown["id"]


def test_after_every_schedule_the_assistant_asks_whether_it_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, transcript = replay(LOOP_CONFIRM, monkeypatch)
    first_schedule = transcript.turns[1]
    assert builds(first_schedule)[0]["schedules"]
    text = turn_text(first_schedule)
    assert ASK in text
    assert text.count("?") == 1
    assert "Confirm with BYU-Idaho Academic Advising." in text
    # The card has its own two replies: the turn sends none.
    assert not (first_schedule[-1].data or {}).get("quick_replies")


def test_maybe_or_a_question_does_not_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    session, transcript = replay(LOOP_NOT_A_YES, monkeypatch)
    for turn in transcript.turns[2:]:
        assert not tool_results(turn, "confirm_schedule")
        assert not [e for e in turn if e.type == "tool_call" and e.tool == "confirm_schedule"]
        assert ASK in turn_text(turn)
    assert session.ctx.plan.confirmed is None


def test_after_confirming_a_change_reopens_the_loop_and_the_plan_stays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transcript = replay(LOOP_CONFIRM_THEN_CHANGE, monkeypatch)
    first = builds(transcript.turns[1])[0]["schedules"][0]
    assert tool_results(transcript.turns[2], "confirm_schedule")
    reopened = transcript.turns[3]
    (rebuilt,) = builds(reopened)
    assert rebuilt["schedules"][0]["id"] != first["id"]
    assert not tool_results(reopened, "confirm_schedule")
    assert ASK in turn_text(reopened)
    # The confirmed plan stays until a new one is confirmed, and the assistant says so.
    assert session.ctx.plan.confirmed is not None
    assert session.ctx.plan.confirmed.id == first["id"]
    assert any(word in turn_text(reopened).lower() for word in ("stays", "still", "saved"))
