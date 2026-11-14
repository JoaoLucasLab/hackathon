"""AI-08: "what changed" is written only from the two `build_schedules` results.

Every course code and every time in the assistant's text of a rebuild appears in
the previous schedule or the new one (or in the rules both were built from).
Recorded conversations, replayed: see test_feedback_to_constraints.py.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from tests.chat_harness import (
    FEEDBACK_SCENARIOS,
    LOOP_CONFIRM_THEN_CHANGE,
    Scenario,
    builds,
    replay,
    turn_text,
)

COURSE = re.compile(r"\b[A-Z]{2,4} \d{3}[A-Z]?\b")
TIME = re.compile(r"\b(\d{1,2}):(\d{2})\b")

SCENARIOS = [*FEEDBACK_SCENARIOS, LOOP_CONFIRM_THEN_CHANGE]


def _clock(value: str) -> set[str]:
    """ "14:00:00" -> {"14:00", "2:00"}: the ways the text may write that time."""
    hour, minute = int(value[:2]), value[3:5]
    return {f"{hour}:{minute}", f"{(hour - 1) % 12 + 1}:{minute}"}


def _facts(result: dict[str, Any]) -> tuple[set[str], set[str]]:
    courses: set[str] = set()
    times: set[str] = set()
    for schedule in result["schedules"]:
        for item in schedule["classes"]:
            sections = [item["section"], *item["backups"]]
            courses.add(item["section"]["course_code"])
            for section in sections:
                for meeting in section["meetings"]:
                    for key in ("start_time", "end_time"):
                        if meeting.get(key):
                            times |= _clock(meeting[key])
        # Warnings are part of the schedule: "CSE 310 needs CSE 210 (pending grade)".
        for warning in [
            *schedule["warnings"],
            *(w for c in schedule["classes"] for w in c["warnings"]),
        ]:
            courses |= set(COURSE.findall(warning["message"]))
            if warning.get("course_code"):
                courses.add(warning["course_code"])
    for key in ("earliest_start", "latest_end"):
        if result["constraints"].get(key):
            times |= _clock(result["constraints"][key])
    return courses, times


def _rebuilds(transcript_turns: list[Any]) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
    """(previous result, new result, the assistant's text) for every rebuild."""
    found = []
    previous: dict[str, Any] | None = None
    for turn in transcript_turns:
        for result in builds(turn):
            if not result["schedules"]:
                continue
            if previous is not None:
                found.append((previous, result, turn_text(turn)))
            previous = result
    return found


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_change_summary_only_names_facts_from_the_two_schedules(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, transcript = replay(scenario, monkeypatch)
    rebuilds = _rebuilds(transcript.turns)
    assert rebuilds, "no schedule was rebuilt"
    for previous, new, text in rebuilds:
        assert new["changed_from_previous"] is not None
        courses_a, times_a = _facts(previous)
        courses_b, times_b = _facts(new)
        # Rooms ("RKS 103") look like course codes: they are facts of the schedules too.
        rooms = set(COURSE.findall(json.dumps([previous, new])))
        named = set(COURSE.findall(text))
        assert named, "the text does not say what changed"
        assert named <= courses_a | courses_b | rooms, f"invented course in {text!r}"
        said = {f"{int(h)}:{m}" for h, m in TIME.findall(text)}
        # "Why a section was left out" is in the results too: `excluded` details such
        # as "ends at 16:45, after 14:00".
        left_out: set[str] = set()
        for result in (previous, new):
            for value in re.findall(r"\b\d{2}:\d{2}\b", json.dumps(result["excluded"])):
                left_out |= _clock(value)
        assert said <= times_a | times_b | left_out, f"invented time in {text!r}"


@pytest.mark.parametrize("scenario", FEEDBACK_SCENARIOS, ids=[s.id for s in FEEDBACK_SCENARIOS])
def test_change_summary_comes_before_the_question(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, transcript = replay(scenario, monkeypatch)
    for _, _, text in _rebuilds(transcript.turns):
        summary = text.split("Does this schedule work for you?")[0]
        assert COURSE.search(summary), "nothing said about the change before the question"
