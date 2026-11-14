"""AI-08: the student's feedback becomes `ConstraintSet` changes and a new schedule.

Recorded Claude conversations are replayed through the real turn loop, so the tools
and the solver run for real. Record them by hand (live):

    set -a; source .env; set +a
    pytest -m live backend/tests/test_chat_record.py -k loop
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from tests.chat_harness import (
    FEEDBACK_DIFFERENT,
    FEEDBACK_FEWER_CREDITS,
    FEEDBACK_LATER,
    FEEDBACK_NO_FRIDAY,
    FEEDBACK_ONLINE_TO_CAMPUS,
    FEEDBACK_PROFESSOR,
    FEEDBACK_SCENARIOS,
    LOOP_NO_FIT,
    LOOP_SCENARIOS,
    LOOP_VAGUE,
    Scenario,
    build_calls,
    builds,
    replay,
    section_ids,
    turn_text,
)

from app.llm.chat import APPLY_RELAXATION
from app.llm.intake import CHOICES_OPEN

ASK = "Does this schedule work for you?"

Json = dict[str, Any]
# (constraints before, constraints after, rejected schedule, new schedule)
Check = Callable[[Json, Json, Json, Json], None]


def _section(schedule: Json, course: str) -> Json:
    (found,) = [c["section"] for c in schedule["classes"] if c["section"]["course_code"] == course]
    return dict(found)


def _days(schedule: Json) -> set[str]:
    return {
        d for c in schedule["classes"] for m in c["section"]["meetings"] for d in m["days"]
    }


def _no_friday(before: Json, after: Json, old: Json, new: Json) -> None:
    assert "F" in _days(old)
    assert after["days_off"] == ["F"]
    assert "F" not in _days(new)


def _not_that_professor(before: Json, after: Json, old: Json, new: Json) -> None:
    rejected = _section(old, "CIT 225")
    assert rejected["id"] in after["exclude_section_ids"]
    for c in new["classes"]:
        if c["section"]["course_code"] == "CIT 225":
            assert not set(c["section"]["instructor_ids"]) & set(rejected["instructor_ids"])


def _later(before: Json, after: Json, old: Json, new: Json) -> None:
    rejected = _section(old, "MATH 221A")
    assert rejected["id"] in after["exclude_section_ids"]
    # Only that class moves: the rule for every class is not changed.
    assert after["earliest_start"] == before["earliest_start"]
    moved = _section(new, "MATH 221A")
    assert moved["meetings"][0]["start_time"] > rejected["meetings"][0]["start_time"]


def _fewer_credits(before: Json, after: Json, old: Json, new: Json) -> None:
    assert after["credit_max"] < old["total_credits"]
    assert new["total_credits"] < old["total_credits"]


def _online_to_campus(before: Json, after: Json, old: Json, new: Json) -> None:
    rejected = _section(old, "MATH 113")
    assert rejected["delivery_method"] == "online"
    assert rejected["id"] in after["exclude_section_ids"] or after["delivery_methods"] == ["campus"]
    assert _section(new, "MATH 113")["delivery_method"] == "campus"


def _different(before: Json, after: Json, old: Json, new: Json) -> None:
    assert after == before  # the same rules, another schedule


CHECKS: dict[str, Check] = {
    FEEDBACK_NO_FRIDAY.id: _no_friday,
    FEEDBACK_PROFESSOR.id: _not_that_professor,
    FEEDBACK_LATER.id: _later,
    FEEDBACK_FEWER_CREDITS.id: _fewer_credits,
    FEEDBACK_ONLINE_TO_CAMPUS.id: _online_to_campus,
    FEEDBACK_DIFFERENT.id: _different,
}

# What a change must leave alone, per phrase: every rule the student did not mention.
UNTOUCHED = {
    FEEDBACK_NO_FRIDAY.id: {"days_off"},
    FEEDBACK_PROFESSOR.id: {"exclude_section_ids"},
    FEEDBACK_LATER.id: {"exclude_section_ids"},
    FEEDBACK_FEWER_CREDITS.id: {"credit_min", "credit_max"},
    FEEDBACK_ONLINE_TO_CAMPUS.id: {"exclude_section_ids", "delivery_methods"},
    FEEDBACK_DIFFERENT.id: set(),
}


@pytest.mark.parametrize("scenario", FEEDBACK_SCENARIOS, ids=[s.id for s in FEEDBACK_SCENARIOS])
def test_feedback_changes_the_constraints_and_avoids_the_rejected_schedule(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, transcript = replay(scenario, monkeypatch)
    (first,) = builds(transcript.turns[1])
    (second,) = builds(transcript.turns[2])
    old, new = first["schedules"][0], second["schedules"][0]
    before, after = first["constraints"], second["constraints"]

    CHECKS[scenario.id](before, after, old, new)
    for name in set(before) - UNTOUCHED[scenario.id]:
        assert after[name] == before[name], f"{name} changed, but the student did not ask"

    # The rejected schedule goes into avoid_schedules, and the new one differs from it.
    (call,) = build_calls(transcript.turns[2])
    assert sorted(section_ids(old)) in [sorted(ids) for ids in call["avoid_schedules"]]
    assert sorted(section_ids(old)) in session.ctx.plan.avoid_lists()
    assert section_ids(new) != section_ids(old)
    assert (first["option"], second["option"]) == (1, 2)
    assert ASK in turn_text(transcript.turns[2])


@pytest.mark.parametrize("scenario", LOOP_SCENARIOS, ids=[s.id for s in LOOP_SCENARIOS])
def test_rules_that_hold_in_every_loop(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, transcript = replay(scenario, monkeypatch)
    shown: list[set[str]] = []
    for turn in transcript.turns:
        assert "error" not in [e.type for e in turn]
        assert turn[-1].type == "done"
        assert CHOICES_OPEN not in turn_text(turn)
        results = builds(turn)
        assert len(results) <= 1, "more than one schedule in one message"
        for result in results:
            assert len(result["schedules"]) <= 1
            for schedule in result["schedules"]:
                assert section_ids(schedule) not in shown, "a rejected schedule came back"
                shown.append(section_ids(schedule))
                assert ASK in turn_text(turn)
                assert "Option 2:" not in turn_text(turn)  # no list of options in text


def test_vague_feedback_gets_one_question_then_another_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, transcript = replay(LOOP_VAGUE, monkeypatch)
    (first,) = builds(transcript.turns[1])
    vague, another = transcript.turns[2], transcript.turns[3]
    assert not build_calls(vague)
    assert turn_text(vague).count("?") == 1
    (second,) = builds(another)
    assert second["constraints"] == first["constraints"]
    assert section_ids(second["schedules"][0]) != section_ids(first["schedules"][0])


def test_no_fit_shows_the_hint_and_applying_it_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    _, transcript = replay(LOOP_NO_FIT, monkeypatch)
    no_fit, applied = transcript.turns[1], transcript.turns[2]
    (empty,) = builds(no_fit)
    assert empty["schedules"] == []
    hint = empty["relaxation"]
    assert hint is not None
    assert (no_fit[-1].data or {}).get("quick_replies") == [APPLY_RELAXATION]
    assert ASK not in turn_text(no_fit)

    (rebuilt,) = builds(applied)
    assert rebuilt["constraints"] == hint["patch"]
    assert len(rebuilt["schedules"]) == 1
    assert ASK in turn_text(applied)
