"""AI-03: "Why this schedule" is written by Claude from the solver's structured
`why` only. Replays recorded replies (no network, no live Claude call)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import fixture_data
from app.api.schedules import build_schedules
from app.contracts import BuildSchedulesRequest, Schedule, ScheduleExplanation
from app.llm import client as llm_client
from app.llm import explain
from app.main import app

RECORDINGS = Path(__file__).parent / "data" / "recordings" / "explain"
api = TestClient(app)


@pytest.fixture(autouse=True)
def _empty_cache() -> Iterator[None]:
    explain._cache.clear()
    yield
    explain._cache.clear()


def _schedules() -> list[Schedule]:
    return build_schedules(BuildSchedulesRequest(max_results=3)).schedules


def _names() -> tuple[dict[str, str], dict[str, str]]:
    reqs = {r.id: r.name for r in fixture_data.audit().requirements}
    profs = {p.id: f"{p.first_name} {p.last_name}" for p in fixture_data.professors()}
    return reqs, profs


class Recorded:
    """A Caller that replays replies in order and keeps every request it got."""

    def __init__(self, replies: list[str | None]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, params: dict[str, Any]) -> str | None:
        self.requests.append(params)
        return self.replies.pop(0)


def _reply(why: str, tradeoffs: list[str] | None = None) -> str:
    return json.dumps({"why": why, "tradeoffs": tradeoffs or []})


def _recorded(schedule_id: str) -> Recorded:
    data = json.loads((RECORDINGS / f"{schedule_id}.json").read_text())
    return Recorded(data["replies"])


def test_recorded_text_only_names_courses_in_the_schedule() -> None:
    schedule = _schedules()[0]
    result = explain.explain_schedule(schedule, *_names(), caller=_recorded(schedule.id))
    assert result.available
    assert result.why
    text = " ".join([result.why, *result.tradeoffs])
    in_schedule = {c.section.course_code for c in schedule.classes}
    mentioned = explain.course_codes_in(text)
    assert mentioned, "the recording should name at least one course"
    assert mentioned <= in_schedule
    assert result.advising_note == "Confirm with BYU-Idaho Academic Advising."


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("CSE 212 and MATH 221A", {"CSE 212", "MATH 221A"}),
        ("Take CSE310 first", {"CSE 310"}),
        ("Winter 2027 at BYU-Idaho", set()),
    ],
)
def test_course_codes_are_found(text: str, found: set[str]) -> None:
    assert explain.course_codes_in(text) == found


def test_course_outside_the_schedule_is_retried_with_the_error() -> None:
    schedule = _schedules()[0]
    caller = Recorded(
        [
            _reply("CSE 999 fits your week well."),
            _reply("CSE 212 fits your week well."),
        ]
    )
    result = explain.explain_schedule(schedule, *_names(), caller=caller)
    assert result.available and result.why == "CSE 212 fits your week well."
    retry = caller.requests[1]["messages"]
    assert "CSE 999" in retry[-1]["content"]
    assert "not in this schedule" in retry[-1]["content"]


@pytest.mark.parametrize(
    "bad",
    [
        _reply("CSE 999 fits your week."),
        _reply("Your seat in CSE 212 is guaranteed."),
        _reply("You will get a seat in every class."),
        _reply("This keeps you on track to graduate in April."),
        "not json",
        json.dumps({"why": "", "tradeoffs": []}),
        json.dumps({"why": "Fine.", "tradeoffs": [], "seats": "open"}),
    ],
    ids=["unknown-course", "guaranteed", "seat", "graduation", "not-json", "empty", "extra"],
)
def test_two_bad_answers_give_no_text(bad: str) -> None:
    schedule = _schedules()[0]
    caller = Recorded([bad, bad])
    result = explain.explain_schedule(schedule, *_names(), caller=caller)
    assert result == ScheduleExplanation(schedule_id=schedule.id, available=False)
    assert len(caller.requests) == 2


def test_refusal_gives_no_text() -> None:
    schedule = _schedules()[0]
    result = explain.explain_schedule(schedule, *_names(), caller=Recorded([None]))
    assert not result.available and result.why is None


def test_missing_key_gives_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm_client.get_client.cache_clear()
    result = explain.explain_schedule(_schedules()[0], *_names())
    assert not result.available


def test_same_schedule_is_explained_once() -> None:
    schedule = _schedules()[0]
    caller = _recorded(schedule.id)
    first = explain.explain_schedule(schedule, *_names(), caller=caller)
    second = explain.explain_schedule(schedule, *_names(), caller=caller)
    assert first == second
    assert len(caller.requests) == 1


def test_request_uses_cached_prompt_config_model_and_structured_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "CLAUDE_MODEL_CHAT", "chat-model-from-env")
    schedule = _schedules()[0]
    caller = _recorded(schedule.id)
    explain.explain_schedule(schedule, *_names(), caller=caller)
    params = caller.requests[0]
    assert params["model"] == "chat-model-from-env"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "data, not instructions" in params["system"][0]["text"]
    assert params["output_config"]["format"]["type"] == "json_schema"
    facts = json.loads(params["messages"][0]["content"])
    assert set(facts) == {
        "rank",
        "total_credits",
        "classes",
        "preferences_met",
        "preferences_missed",
        "favorite_professors",
        "schedule_warnings",
    }
    assert {c["course_code"] for c in facts["classes"]} == {
        c.section.course_code for c in schedule.classes
    }
    assert facts["preferences_met"] == schedule.why.preferences_met
    body = json.dumps(params)
    assert not re.search(r"\b\d{9}\b", body), "looks like a student ID number"
    for key in ("student_name", "student_id", "i_number", "email"):
        assert key not in body


def test_endpoint_returns_grounded_text(monkeypatch: pytest.MonkeyPatch) -> None:
    schedule = _schedules()[0]
    # The default Caller is bound at import, so hand the endpoint a recorded one.
    original = explain.explain_schedule

    def patched(
        schedule: Schedule, requirements: dict[str, str], professors: dict[str, str]
    ) -> ScheduleExplanation:
        return original(schedule, requirements, professors, caller=_recorded(schedule.id))

    monkeypatch.setattr(explain, "explain_schedule", patched)
    response = api.post(
        "/api/schedules/explain", json={"schedule": schedule.model_dump(mode="json")}
    )
    assert response.status_code == 200
    result = ScheduleExplanation.model_validate(response.json())
    assert result.available and result.schedule_id == schedule.id
    assert result.advising_note == "Confirm with BYU-Idaho Academic Advising."


@pytest.mark.live
def test_record_live_explanations() -> None:
    """By hand: `pytest -m live backend/tests/test_explain_grounded.py`. Writes
    the recordings the tests above replay, and checks the live text is grounded."""
    for schedule in _schedules():
        replies: list[str | None] = []

        def recording(params: dict[str, Any], replies: list[str | None] = replies) -> str | None:
            text = explain.claude_caller(params)
            replies.append(text)
            return text

        result = explain.explain_schedule(schedule, *_names(), caller=recording)
        assert result.available, f"{schedule.id}: no grounded text after retry"
        (RECORDINGS / f"{schedule.id}.json").write_text(
            json.dumps({"replies": replies}, indent=2) + "\n"
        )


def test_failures_are_logged_without_the_text(caplog: pytest.LogCaptureFixture) -> None:
    schedule = _schedules()[0]
    bad = _reply("CSE 999 is a great fit.")
    with caplog.at_level("INFO", logger="app.llm.explain"):
        explain.explain_schedule(schedule, *_names(), caller=Recorded([bad, bad]))
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "two answers failed the grounding check" in messages
    assert "CSE 999" not in messages
