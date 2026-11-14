"""AI-07: the two worked examples (and two edge cases) as recorded conversations.

Recorded Claude responses are replayed through the real turn loop with the flag
on, so the gate and the tools run for real. Record them by hand (live, a few cents):

    set -a; source .env; set +a
    pytest -m live backend/tests/test_chat_record.py -k intake
"""

from __future__ import annotations

import re

import pytest
from tests.chat_harness import (
    INTAKE_ANY_CREDITS,
    INTAKE_EVERYTHING,
    INTAKE_HELP_ME_PLAN,
    INTAKE_SCENARIOS,
    INTAKE_UNKNOWN_COURSE,
    Scenario,
    Transcript,
    replay,
)

from app.contracts import ChatEvent, ConstraintSet, Day, Track
from app.llm.intake import CHOICES_OPEN

CONFIRM = "Should I build a schedule with these?"


def _text(turn: list[ChatEvent]) -> str:
    return "".join(e.text or "" for e in turn if e.type == "text")


def _built(turn: list[ChatEvent]) -> bool:
    return any(e.type == "tool_result" and e.tool == "build_schedules" for e in turn)


def _built_constraints(transcript: Transcript) -> ConstraintSet:
    results = [
        e for e in transcript.events if e.type == "tool_result" and e.tool == "build_schedules"
    ]
    assert results, "no schedule was built"
    return ConstraintSet.model_validate((results[0].data or {})["constraints"])


@pytest.mark.parametrize("scenario", INTAKE_SCENARIOS, ids=[s.id for s in INTAKE_SCENARIOS])
def test_rules_that_hold_in_every_intake(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, transcript = replay(scenario, monkeypatch)
    assert not _built(transcript.turns[0]), "a schedule was built on the first message"
    for turn in transcript.turns:
        text = _text(turn)
        assert "error" not in [e.type for e in turn]
        assert turn[-1].type == "done"
        assert CHOICES_OPEN not in text  # the choices line is never shown as text
        if not _built(turn):
            assert 1 <= text.count("?") <= 2, f"not 1 or 2 questions: {text!r}"


def test_everything_in_one_message_gets_one_confirmation_then_a_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transcript = replay(INTAKE_EVERYTHING, monkeypatch)
    first, second = transcript.turns
    assert CONFIRM in _text(first)
    assert _text(first).count("?") == 1  # no extra questions
    assert (first[-1].data or {}).get("quick_replies"), "no quick replies on the confirmation"
    assert _built(second)

    built = _built_constraints(transcript)
    assert (built.credit_min, built.credit_max) == (12, 15)
    assert built.earliest_start is not None and built.earliest_start.hour == 10
    assert built.days_off == [Day.F]
    assert built.include_courses == ["CSE 210"]
    assert "Confirm with BYU-Idaho Academic Advising." in _text(second)
    assert session.ctx.intake.agreed_to_build


def test_help_me_plan_asks_over_several_turns_then_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, transcript = replay(INTAKE_HELP_ME_PLAN, monkeypatch)
    built_at = [i for i, turn in enumerate(transcript.turns) if _built(turn)]
    assert built_at, "no schedule was built"
    assert built_at[0] >= 2, "built before the questions were asked"
    # The turn before the first schedule is the confirmation question.
    assert CONFIRM in _text(transcript.turns[built_at[0] - 1])
    # The track question comes with fixed choices.
    assert (transcript.turns[0][-1].data or {}).get("quick_replies")

    built = _built_constraints(transcript)
    assert (built.credit_min, built.credit_max) == (None, None)  # the school default
    assert built.days_off == [Day.F]
    assert session.ctx.audit.track == Track.winter_spring
    # The default range is said out loud, from the tool result.
    assert re.search(r"12 (to|-|–) ?15", " ".join(_text(t) for t in transcript.turns))


def test_unknown_course_stops_the_intake(monkeypatch: pytest.MonkeyPatch) -> None:
    session, transcript = replay(INTAKE_UNKNOWN_COURSE, monkeypatch)
    (turn,) = transcript.turns
    assert "search_sections" in transcript.tools_called()
    assert "CSE 999" in _text(turn)
    assert CONFIRM not in _text(turn)  # it does not move on as if the course were valid
    assert not _built(turn)
    assert session.ctx.constraints.include_courses == []


def test_student_can_choose_any_number_of_credits(monkeypatch: pytest.MonkeyPatch) -> None:
    _, transcript = replay(INTAKE_ANY_CREDITS, monkeypatch)
    built = _built_constraints(transcript)
    assert (built.credit_min, built.credit_max) == (7, 7)
