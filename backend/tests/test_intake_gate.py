"""AI-07: `build_schedules` does not run before the readiness checklist is complete.

Hand-scripted Claude responses go through the real turn loop and the real tools,
so these tests show what the backend does when the model tries to skip ahead.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app import config
from app.api import fixture_data
from app.contracts import ConstraintSet, Track
from app.llm import tools
from app.llm.chat import ChatSession, TurnResult, build_params, run_turn
from app.llm.intake import OFFER_DEFAULTS_NOTE, ChoiceFilter, IntakeState, parse_choices
from app.llm.tools import ToolContext

CONSTRAINTS: dict[str, Any] = {
    "credit_min": None,
    "credit_max": None,
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
WITH_CREDITS = {**CONSTRAINTS, "credit_min": 12, "credit_max": 15}


@pytest.fixture(autouse=True)
def flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "FEATURE_CONVERSATIONAL_PLANNER", True)


def _session(track: bool = True) -> ChatSession:
    audit = fixture_data.audit()
    if not track:
        audit = audit.model_copy(update={"track": None})
    return ChatSession(ctx=ToolContext(audit=audit))


def _build(
    i: int,
    constraints: dict[str, Any] = WITH_CREDITS,
    *,
    track: str | None = None,
    use_default_credits: bool = False,
    agreed: bool = True,
) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": f"toolu_{i}",
        "name": "build_schedules",
        "input": {
            "constraints": constraints,
            "max_results": 1,
            "intake": {
                "track": track,
                "use_default_credits": use_default_credits,
                "student_agreed": agreed,
            },
        },
    }


def _text(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


class Script:
    def __init__(self, *turns: TurnResult) -> None:
        self.turns = list(turns)
        self.params: list[dict[str, Any]] = []

    def __call__(self, params: dict[str, Any]) -> Iterator[str | TurnResult]:
        self.params.append(params)
        turn = self.turns.pop(0)
        for block in turn.content:
            if block["type"] == "text":
                yield block["text"]
        yield turn


def _say(session: ChatSession, message: str, *turns: TurnResult) -> tuple[list[Any], Script]:
    script = Script(*turns)
    return list(run_turn(session, message, script)), script


def _question(text: str = "How many credits do you want?") -> TurnResult:
    return TurnResult([_text(text)], "end_turn")


def _gate_error(script: Script) -> str:
    """The tool_result the model got back for its build_schedules call."""
    block = script.params[1]["messages"][-1]["content"][0]
    assert block["is_error"] is True
    return str(block["content"])


def _built(events: list[Any]) -> bool:
    return any(e.type == "tool_result" and e.tool == "build_schedules" for e in events)


def test_build_on_turn_1_gives_a_question_not_a_schedule() -> None:
    """A model that calls build_schedules on turn 1 still produces a question."""
    session = _session()
    events, script = _say(
        session,
        "12 to 15 credits, no Fridays",
        TurnResult([_build(1)], "tool_use"),
        _question("Should I build a schedule with these?"),
    )
    assert not _built(events)
    assert _gate_error(script).startswith("not ready: this is the student's first message")
    assert "".join(e.text or "" for e in events if e.type == "text").endswith("?")
    assert "error" not in [e.type for e in events]  # the student sees a question
    assert session.ctx.constraints == ConstraintSet()  # nothing was saved


@pytest.mark.parametrize(
    ("has_track", "kwargs", "constraints", "missing"),
    [
        (False, {}, WITH_CREDITS, "track"),
        (True, {}, CONSTRAINTS, "credit load"),
        (False, {}, CONSTRAINTS, "track and credit load"),
    ],
    ids=["no-track", "no-credit-load", "neither"],
)
def test_each_missing_required_item_is_named(
    has_track: bool, kwargs: dict[str, Any], constraints: dict[str, Any], missing: str
) -> None:
    session = _session(track=has_track)
    _say(session, "help me plan my semester", _question())
    events, script = _say(
        session,
        "yes, build it",
        TurnResult([_build(1, constraints, **kwargs)], "tool_use"),
        _question(),
    )
    assert not _built(events)
    assert _gate_error(script) == f"not ready: ask the student for {missing}"


def test_not_agreed_is_blocked() -> None:
    session = _session()
    _say(session, "12 to 15 credits", _question())
    events, script = _say(
        session, "and no Fridays", TurnResult([_build(1, agreed=False)], "tool_use"), _question()
    )
    assert not _built(events)
    assert "has not agreed to build" in _gate_error(script)


@pytest.mark.parametrize(
    ("has_track", "kwargs", "constraints"),
    [
        (True, {}, WITH_CREDITS),
        (True, {"use_default_credits": True}, CONSTRAINTS),
        (False, {"track": "winter_spring"}, WITH_CREDITS),
        # The student may choose any number of credits, also outside the default range.
        (True, {}, {**CONSTRAINTS, "credit_min": 7, "credit_max": 7}),
        (True, {}, {**CONSTRAINTS, "credit_min": 19, "credit_max": 21}),
        (True, {}, {**CONSTRAINTS, "credit_max": 6}),
    ],
    ids=[
        "credit-range",
        "default-credits",
        "student-stated-track",
        "exactly-7-credits",
        "19-to-21-credits",
        "at-most-6-credits",
    ],
)
def test_complete_checklist_builds(
    has_track: bool, kwargs: dict[str, Any], constraints: dict[str, Any]
) -> None:
    session = _session(track=has_track)
    _say(session, "12 to 15 credits, no Fridays", _question("Should I build?"))
    events, _ = _say(
        session,
        "yes",
        TurnResult([_build(1, constraints, **kwargs)], "tool_use"),
        TurnResult([_text("Here is a schedule.")], "end_turn"),
    )
    assert _built(events)
    assert session.ctx.intake.built and session.ctx.intake.agreed_to_build
    # The student's own numbers reach the solver unchanged.
    assert session.ctx.constraints == ConstraintSet.model_validate(constraints)
    if not has_track:
        assert session.ctx.audit.track == Track.winter_spring


def test_track_from_the_audit_cannot_be_changed() -> None:
    session = _session()
    audit_track = session.ctx.audit.track
    assert audit_track is not None
    other = next(t.value for t in Track if t != audit_track)
    _say(session, "12 credits", _question())
    events, script = _say(
        session, "yes", TurnResult([_build(1, track=other)], "tool_use"), _question()
    )
    assert not _built(events)
    assert f"the degree audit says the track is {audit_track.value}" in _gate_error(script)
    assert session.ctx.audit.track == audit_track


def test_answers_are_kept_between_calls() -> None:
    """The track given in a blocked call still counts in the next one."""
    session = _session(track=False)
    _say(session, "I'm on Winter & Spring", _question())
    _say(
        session,
        "build",
        TurnResult([_build(1, CONSTRAINTS, track="winter_spring")], "tool_use"),
        _question(),
    )
    events, _ = _say(
        session,
        "the default is fine, build it",
        TurnResult([_build(2, CONSTRAINTS, use_default_credits=True)], "tool_use"),
        TurnResult([_text("Here is a schedule.")], "end_turn"),
    )
    assert _built(events)


def test_rebuild_after_the_first_schedule_needs_no_new_agreement() -> None:
    session = _session()
    _say(session, "12 to 15 credits", _question())
    _say(session, "yes", TurnResult([_build(1)], "tool_use"), _question("Does this work?"))
    events, _ = _say(
        session,
        "no Fridays please",
        TurnResult([_build(2, {**WITH_CREDITS, "days_off": ["F"]}, agreed=False)], "tool_use"),
        _question("Does this work?"),
    )
    assert _built(events)


def test_intake_argument_is_required_when_the_flag_is_on() -> None:
    session = _session()
    session.ctx.intake.student_turns = 2
    with pytest.raises(tools.ToolInputError, match="intake"):
        tools.run_tool(
            session.ctx, "build_schedules", {"constraints": CONSTRAINTS, "max_results": 1}
        )


def test_tool_schema_has_intake_only_with_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    def build_props() -> dict[str, Any]:
        tool = next(t for t in tools.tool_definitions() if t["name"] == "build_schedules")
        schema: dict[str, Any] = dict(tool["input_schema"])
        return dict(schema["properties"])

    on = build_props()
    assert set(on["intake"]["properties"]) == {"track", "use_default_credits", "student_agreed"}
    assert on["intake"]["additionalProperties"] is False
    assert build_params([])["system"][0]["text"].count("Should I build a schedule with these?")

    monkeypatch.setattr(config, "FEATURE_CONVERSATIONAL_PLANNER", False)
    assert "intake" not in build_props()
    assert "call `build_schedules` right away" in build_params([])["system"][0]["text"]


def test_flag_off_builds_on_turn_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "FEATURE_CONVERSATIONAL_PLANNER", False)
    args = {"constraints": CONSTRAINTS, "max_results": 3}
    block = {"type": "tool_use", "id": "toolu_1", "name": "build_schedules", "input": args}
    events, _ = _say(
        _session(),
        "no Fridays",
        TurnResult([block], "tool_use"),
        TurnResult([_text("Here are three schedules.")], "end_turn"),
    )
    assert _built(events)


def test_after_4_rounds_the_app_tells_the_model_to_offer_defaults() -> None:
    session = _session()
    for n in range(4):
        _, script = _say(session, f"answer {n}", _question())
        assert isinstance(script.params[0]["messages"][-1]["content"], str)
    _, script = _say(session, "hmm", _question("I can build one now. Want me to?"))
    content = script.params[0]["messages"][-1]["content"]
    assert content == [
        {"type": "text", "text": "hmm"},
        {"type": "text", "text": OFFER_DEFAULTS_NOTE},
    ]


def test_question_rounds_stop_counting_after_the_first_schedule() -> None:
    state = IntakeState()
    state.end_turn(built_this_turn=False)
    state.end_turn(built_this_turn=True)
    state.built = True
    state.end_turn(built_this_turn=False)
    assert state.question_rounds == 1 and not state.should_offer_defaults()


# --- Quick replies ---------------------------------------------------------------------


def test_choices_line_becomes_quick_replies_and_is_not_shown() -> None:
    reply = "Which track are you on?\n<<choices: Fall & Winter | Winter & Spring | Online student>>"
    events, _ = _say(_session(track=False), "help me plan", _question(reply))
    assert "".join(e.text or "" for e in events if e.type == "text") == "Which track are you on?"
    assert events[-1].type == "done"
    assert events[-1].data == {
        "quick_replies": ["Fall & Winter", "Winter & Spring", "Online student"]
    }


def test_no_choices_line_means_a_plain_done() -> None:
    events, _ = _say(_session(), "help me plan", _question("What courses do you want?"))
    assert events[-1].type == "done" and events[-1].data is None


@pytest.mark.parametrize("size", [1, 2, 3, 7, 50])
def test_choice_filter_works_however_the_text_is_chunked(size: int) -> None:
    full = "Any days off? A < B is fine.\n\n<<choices: No preference | Fridays off>>\n"
    f = ChoiceFilter()
    shown = "".join(f.feed(full[i : i + size]) for i in range(0, len(full), size)) + f.finish()
    assert shown == "Any days off? A < B is fine."
    assert f.choices == ["No preference", "Fridays off"]


def test_choice_filter_keeps_text_that_only_looks_like_a_marker() -> None:
    f = ChoiceFilter()
    shown = f.feed("Use << to shift") + f.feed(" bits. <<cho") + f.finish()
    assert shown == "Use << to shift bits. <<cho"
    assert f.choices == []


def test_parse_choices_is_bounded() -> None:
    assert parse_choices(" A |  B | A | " + "x" * 41 + " | C | D | E") == ["A", "B", "C", "D"]
