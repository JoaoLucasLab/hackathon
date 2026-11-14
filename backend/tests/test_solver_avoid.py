"""ENG-07: one schedule at a time, and a schedule the student rejected never comes back."""

from __future__ import annotations

import time as clock
from datetime import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.engine_helpers import audit, requirement, section

from app import config
from app.api import schedules as schedules_api
from app.contracts import (
    BuildSchedulesRequest,
    BuildSchedulesResponse,
    ConstraintSet,
    Schedule,
    Section,
)
from app.engine.solver import build_schedules
from app.llm import intake as intake_rules
from app.llm import tools
from app.llm.tools import ToolContext
from app.main import app
from app.schools.base import default_school

# Four required courses, two sections each, no conflicts, room for three: 32
# possible schedules of 9 credits, finite so the rejections can run out.
A = audit(
    requirement("ra", "AAA 101"),
    requirement("rb", "BBB 101"),
    requirement("rc", "CCC 101"),
    requirement("rd", "DDD 101"),
)
SECTIONS: list[Section] = [
    section("AAA 101", "01", "MWF 08:00-09:00"),
    section("AAA 101", "02", "MWF 13:00-14:00"),
    section("BBB 101", "01", "TR 08:00-09:15"),
    section("BBB 101", "02", "TR 13:00-14:15"),
    section("CCC 101", "01", "MWF 10:15-11:15"),
    section("CCC 101", "02", "MWF 15:00-16:00"),
    section("DDD 101", "01", "TR 10:00-11:15"),
    section("DDD 101", "02", "TR 15:00-16:15"),
]
CREDITS = (9.0, 9.0)


def _ids(s: Schedule) -> frozenset[str]:
    return frozenset(c.section.id for c in s.classes)


def _build(
    avoid: list[frozenset[str]], constraints: ConstraintSet | None = None
) -> BuildSchedulesResponse:
    return build_schedules(
        A,
        SECTIONS,
        constraints or ConstraintSet(),
        max_results=1,
        credit_range=CREDITS,
        avoid_schedules=[sorted(ids) for ids in avoid],
    )


def _same_or_too_close(a: frozenset[str], b: frozenset[str]) -> bool:
    """The solver's diversity rule: same courses with fewer than 2 sections changed."""

    def by_course(ids: frozenset[str]) -> dict[str, str]:
        return {sid.split("|")[1].rsplit("-", 1)[0]: sid for sid in ids}

    ca, cb = by_course(a), by_course(b)
    return ca.keys() == cb.keys() and sum(ca[k] != cb[k] for k in ca) < 2


def _reject_in_a_row(n: int) -> tuple[list[frozenset[str]], BuildSchedulesResponse]:
    rejected: list[frozenset[str]] = []
    for _ in range(n):
        res = _build(rejected)
        assert len(res.schedules) == 1
        rejected.append(_ids(res.schedules[0]))
    return rejected, _build(rejected)


@pytest.mark.parametrize("n_avoided", [0, 1, 3])
def test_result_differs_from_every_rejected_schedule(n_avoided: int) -> None:
    rejected, res = _reject_in_a_row(n_avoided)
    assert len(res.schedules) == 1
    got = _ids(res.schedules[0])
    for r in rejected:
        assert got != r
        assert not _same_or_too_close(got, r)
    assert res.exhausted is False


def test_zero_avoided_is_the_same_as_before() -> None:
    plain = build_schedules(A, SECTIONS, ConstraintSet(), max_results=1, credit_range=CREDITS)
    assert [_ids(s) for s in _build([]).schedules] == [_ids(s) for s in plain.schedules]


def test_no_schedule_left_says_exhausted_and_never_repeats() -> None:
    rejected: list[frozenset[str]] = []
    for _ in range(40):
        res = _build(rejected)
        if not res.schedules:
            break
        got = _ids(res.schedules[0])
        assert got not in rejected
        rejected.append(got)
    else:
        pytest.fail("the solver never ran out of schedules")
    assert res.schedules == []
    assert res.exhausted is True
    assert res.relaxation is None  # no school rules here, so no relaxation to try


def test_no_schedule_left_with_school_rules_gives_relaxation_or_exhausted() -> None:
    rules = default_school().rules
    rejected: list[frozenset[str]] = []
    res: BuildSchedulesResponse | None = None
    for _ in range(40):
        res = build_schedules(
            A,
            SECTIONS,
            ConstraintSet(credit_min=9, credit_max=9),
            max_results=1,
            rules=rules,
            avoid_schedules=[sorted(r) for r in rejected],
        )
        if not res.schedules:
            break
        rejected.append(_ids(res.schedules[0]))
    assert res is not None and res.schedules == []
    assert res.exhausted or res.relaxation is not None
    if res.relaxation is not None:
        patched = build_schedules(
            A,
            SECTIONS,
            res.relaxation.patch,
            max_results=1,
            rules=rules,
            avoid_schedules=[sorted(r) for r in rejected],
        )
        assert patched.schedules and _ids(patched.schedules[0]) not in rejected


def test_impossible_constraints_are_not_exhausted() -> None:
    """Nothing fits even without the rejected list: that is not `exhausted`."""
    rejected, _ = _reject_in_a_row(1)
    res = _build(rejected, ConstraintSet(earliest_start=time(18, 0)))
    assert res.schedules == []
    assert res.exhausted is False


def test_avoided_schedule_plus_changed_constraints() -> None:
    rejected, _ = _reject_in_a_row(1)
    # Changed constraints that still allow the rejected schedule: it stays out.
    res = _build(rejected, ConstraintSet(latest_end=time(17, 0)))
    assert res.schedules and _ids(res.schedules[0]) != rejected[0]
    # Constraints that rule out a section of it: the rejected list adds nothing.
    first_out = sorted(rejected[0])[0]
    changed = ConstraintSet(exclude_section_ids=[first_out])
    with_avoid = _build(rejected, changed)
    without = _build([], changed)
    assert [_ids(s) for s in with_avoid.schedules] == [_ids(s) for s in without.schedules]
    assert all(first_out not in _ids(s) for s in with_avoid.schedules)


# --- Fixtures: same session constraints, 3 rejections in a row -----------------------

FIXTURE_CONSTRAINTS = ConstraintSet(earliest_start=time(10, 0), credit_min=12, credit_max=15)


def test_fixtures_fourth_schedule_differs_from_three_rejected() -> None:
    rejected: list[list[str]] = []
    for _ in range(4):
        res = schedules_api.build_schedules(
            BuildSchedulesRequest(
                constraints=FIXTURE_CONSTRAINTS, max_results=1, avoid_schedules=rejected
            )
        )
        assert len(res.schedules) == 1
        got = _ids(res.schedules[0])
        assert all(got != frozenset(r) for r in rejected)
        rejected.append(sorted(got))
    assert len({frozenset(r) for r in rejected}) == 4


def test_one_result_stays_inside_the_time_limit() -> None:
    started = clock.perf_counter()
    schedules_api.build_schedules(
        BuildSchedulesRequest(constraints=FIXTURE_CONSTRAINTS, max_results=1)
    )
    # One solve, capped at SOLVER_TIME_LIMIT_S; a little slack for candidates and scoring.
    assert clock.perf_counter() - started <= config.SOLVER_TIME_LIMIT_S + 1.0


# --- API and chat tool ---------------------------------------------------------------


def test_endpoint_still_accepts_1_to_5_and_avoid_schedules() -> None:
    client = TestClient(app)
    body: dict[str, Any] = {"constraints": FIXTURE_CONSTRAINTS.model_dump(mode="json")}
    first = client.post("/api/schedules/build", json={**body, "max_results": 5})
    assert first.status_code == 200
    schedules = first.json()["schedules"]
    assert 1 <= len(schedules) <= 5
    rejected = [c["section"]["id"] for c in schedules[0]["classes"]]
    again = client.post(
        "/api/schedules/build",
        json={**body, "max_results": 1, "avoid_schedules": [rejected]},
    )
    assert again.status_code == 200
    got = {c["section"]["id"] for c in again.json()["schedules"][0]["classes"]}
    assert got != set(rejected)
    assert client.post("/api/schedules/build", json={**body, "max_results": 6}).status_code == 422


def _capture_build(monkeypatch: pytest.MonkeyPatch) -> list[BuildSchedulesRequest]:
    seen: list[BuildSchedulesRequest] = []

    def fake(body: BuildSchedulesRequest, _favorites: object = ()) -> BuildSchedulesResponse:
        seen.append(body)
        return BuildSchedulesResponse(schedules=[])

    monkeypatch.setattr(schedules_api, "build_schedules", fake)
    monkeypatch.setattr(tools, "_intake_gate", lambda _ctx, _args: None)
    monkeypatch.setattr(intake_rules, "mark_built", lambda _state: None)
    return seen


def _ctx() -> ToolContext:
    from app.api import fixture_data

    return ToolContext(audit=fixture_data.audit())


EMPTY = ConstraintSet().model_dump(mode="json")


@pytest.mark.parametrize("asked", [None, 1, 3, 5])
def test_chat_tool_builds_exactly_one_with_the_flag(
    monkeypatch: pytest.MonkeyPatch, asked: int | None
) -> None:
    monkeypatch.setattr(config, "FEATURE_CONVERSATIONAL_PLANNER", True)
    seen = _capture_build(monkeypatch)
    args: dict[str, Any] = {"constraints": EMPTY, "avoid_schedules": [["s1", "s2"]]}
    if asked is not None:
        args["max_results"] = asked
    tools.run_tool(_ctx(), "build_schedules", args)
    assert seen[0].max_results == 1
    assert seen[0].avoid_schedules == [["s1", "s2"]]


def test_chat_tool_with_flag_off_keeps_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "FEATURE_CONVERSATIONAL_PLANNER", False)
    seen = _capture_build(monkeypatch)
    tools.run_tool(_ctx(), "build_schedules", {"constraints": EMPTY, "max_results": 3})
    assert seen[0].max_results == 3
    assert seen[0].avoid_schedules == []


def _build_tool_props() -> dict[str, Any]:
    tool = next(t for t in tools.tool_definitions() if t["name"] == "build_schedules")
    schema: dict[str, Any] = dict(tool["input_schema"])
    return dict(schema["properties"])


def test_tool_schema_has_no_max_results_with_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "FEATURE_CONVERSATIONAL_PLANNER", True)
    on = _build_tool_props()
    assert "max_results" not in on
    assert on["avoid_schedules"]["items"] == {"type": "array", "items": {"type": "string"}}
    monkeypatch.setattr(config, "FEATURE_CONVERSATIONAL_PLANNER", False)
    off = _build_tool_props()
    assert "max_results" in off and "avoid_schedules" not in off
