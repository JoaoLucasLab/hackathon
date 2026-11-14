"""AI-02: the eight example phrases and the ConstraintSet each must produce.

Part 1 (here now): the phrase table itself is valid and covers every field.
Part 2 (with llm/tools.py): replay recorded Claude responses for each phrase and
compare the ConstraintSet the chat builds against `expected`.
"""

from __future__ import annotations

import json
from datetime import time
from pathlib import Path
from typing import Any

import pytest
from tests.chat_harness import EXPECTED, PHRASE_SCENARIOS, Scenario, replay

from app.contracts import ConstraintSet

PHRASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "data" / "chat_phrases.json").read_text(encoding="utf-8")
)


def test_there_are_eight_phrases() -> None:
    assert len(PHRASES) == 8
    assert len({p["id"] for p in PHRASES}) == 8


@pytest.mark.parametrize("phrase", PHRASES, ids=[p["id"] for p in PHRASES])
def test_expected_is_a_valid_constraint_set(phrase: dict[str, Any]) -> None:
    ConstraintSet.model_validate(phrase["expected"])


def test_phrases_cover_every_constraint_field() -> None:
    used = {field for p in PHRASES for field in p["expected"]}
    assert used == set(ConstraintSet.model_fields) - {"exclude_section_ids"}


def test_no_morning_classes_means_1130() -> None:
    first = ConstraintSet.model_validate(PHRASES[0]["expected"])
    assert first.earliest_start == time(11, 30)


# --- Part 2: replay recorded Claude conversations through the real loop ----------

@pytest.mark.parametrize("scenario", PHRASE_SCENARIOS, ids=[s.id for s in PHRASE_SCENARIOS])
def test_phrase_maps_to_expected_constraints(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What Claude understood = the constraints in its first build_schedules call.

    Later calls may add exclude_section_ids: with the ENG-01 stub scheduler (which
    ignores constraints) Claude notices rule-breaking results and retries, and then
    tells the student instead of showing them. That is correct grounding.
    """
    _, transcript = replay(scenario, monkeypatch)
    builds = [e for e in transcript.events if e.type == "tool_call" and e.tool == "build_schedules"]
    assert builds, "Claude never called build_schedules"
    first = ConstraintSet.model_validate((builds[0].data or {})["constraints"])
    assert first == ConstraintSet.model_validate(EXPECTED[scenario.id])
    assert transcript.events[-1].type == "done"
    assert not [e for e in transcript.events if e.type == "error"]


def test_first_phrase_shows_three_schedules(monkeypatch: pytest.MonkeyPatch) -> None:
    _, transcript = replay(PHRASE_SCENARIOS[0], monkeypatch)
    results = [
        e for e in transcript.events if e.type == "tool_result" and e.tool == "build_schedules"
    ]
    assert results and len((results[-1].data or {})["schedules"]) == 3
