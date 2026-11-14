"""ENG-03: hand-built cases with a known best answer, the fixture acceptance
criteria, the time limit and the structured `why`."""

from __future__ import annotations

import time as clock
from datetime import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ortools.sat.python import cp_model
from tests.engine_helpers import audit, requirement, section

from app import config
from app.api import fixture_data
from app.contracts import (
    BuildSchedulesResponse,
    ConstraintSet,
    CourseRecordStatus,
    Schedule,
    Section,
)
from app.engine.solver import build_schedules, schedules_differ
from app.main import app

CREDITS = (12.0, 15.0)


def _codes(s: Schedule) -> set[str]:
    return {c.section.course_code for c in s.classes}


def _ids(s: Schedule) -> set[str]:
    return {c.section.id for c in s.classes}


# --- Hand-built cases with a known best answer ---------------------------------


def test_case_two_required_courses_only_meet_at_the_same_time() -> None:
    """A and B are both required but only meet MWF 10:15. The best schedule takes
    one of them plus C and D; it never takes both."""
    a = audit(
        requirement("ra", "AAA 101"),
        requirement("rb", "BBB 101"),
        requirement("rc", "CCC 101"),
        requirement("rd", "DDD 101"),
        requirement("re", "EEE 101"),
    )
    secs = [
        section("AAA 101", when="MWF 10:15-11:15"),
        section("BBB 101", when="MWF 10:15-11:15"),
        section("CCC 101", when="TR 10:15-11:15"),
        section("DDD 101", when="TR 12:45-13:45"),
        section("EEE 101", when="MWF 12:45-13:45"),
    ]
    res = build_schedules(a, secs, ConstraintSet(), max_results=3, credit_range=(9, 12))
    assert res.schedules
    for s in res.schedules:
        assert not {"AAA 101", "BBB 101"} <= _codes(s)
    best = res.schedules[0]
    assert best.total_credits == 12
    assert {"CCC 101", "DDD 101", "EEE 101"} <= _codes(best)
    assert len(_codes(best) & {"AAA 101", "BBB 101"}) == 1
    # The two best answers are the A and B variants.
    assert {frozenset(_codes(s)) for s in res.schedules[:2]} == {
        frozenset({"AAA 101", "CCC 101", "DDD 101", "EEE 101"}),
        frozenset({"BBB 101", "CCC 101", "DDD 101", "EEE 101"}),
    }


def test_case_prefers_required_courses_over_electives() -> None:
    """Five 3-credit courses fit; only four fill requirements and the range is 12."""
    a = audit(*(requirement(f"r{i}", f"RRR {100 + i}") for i in range(4)))
    secs = [
        section(f"RRR {100 + i}", when=w)
        for i, w in enumerate(
            ["MWF 10:15-11:15", "MWF 11:30-12:30", "TR 10:15-11:15", "TR 11:30-12:30"]
        )
    ] + [section("XXX 999", when="MWF 14:00-15:00")]
    res = build_schedules(a, secs, ConstraintSet(), max_results=1, credit_range=(12, 12))
    [best] = res.schedules
    assert _codes(best) == {"RRR 100", "RRR 101", "RRR 102", "RRR 103"}
    assert best.optimal


def test_case_block_sections_share_a_time_slot() -> None:
    """First Block and Second Block sections at the same time both fit."""
    from app.contracts import BlockKind

    a = audit(requirement("r1", "AAA 101", needed=2), requirement("r2", "BBB 101", needed=2))
    secs = [
        section("AAA 101", when="MW 12:45-13:45", credits=2, block=BlockKind.first),
        section("BBB 101", when="MW 12:45-13:45", credits=2, block=BlockKind.second),
    ]
    res = build_schedules(a, secs, ConstraintSet(), max_results=1, credit_range=(4, 4))
    [best] = res.schedules
    assert _codes(best) == {"AAA 101", "BBB 101"}


def test_impossible_request_returns_no_schedules() -> None:
    a = audit(requirement("r", "AAA 101"))
    res = build_schedules(
        a, [section("AAA 101")], ConstraintSet(), max_results=3, credit_range=CREDITS
    )
    assert res.schedules == []
    assert res.relaxation is None  # ENG-05


# --- Fixture acceptance criteria ------------------------------------------------


def _fixture_build(constraints: ConstraintSet, n: int = 3) -> BuildSchedulesResponse:
    return build_schedules(
        fixture_data.audit(),
        fixture_data.sections(),
        constraints,
        max_results=n,
        credit_range=CREDITS,
    )


def test_endpoint_no_class_before_ten_twelve_to_fifteen_credits_under_five_seconds() -> None:
    client = TestClient(app)
    body = {
        "constraints": {"earliest_start": "10:00:00", "credit_min": 12, "credit_max": 15},
        "max_results": 3,
    }
    started = clock.perf_counter()
    resp = client.post("/api/schedules/build", json=body)
    elapsed = clock.perf_counter() - started
    assert resp.status_code == 200
    assert elapsed < 5
    res = BuildSchedulesResponse.model_validate(resp.json())
    assert len(res.schedules) == 3
    for s in res.schedules:
        assert 12 <= s.total_credits <= 15
        assert s.total_credits == sum(c.section.credits for c in s.classes)
        for c in s.classes:
            for m in c.section.meetings:
                assert m.start_time is None or m.start_time >= time(10, 0)
        assert s.advising_note == "Confirm with BYU-Idaho Academic Advising."
    assert [s.rank for s in res.schedules] == [1, 2, 3]


def test_only_required_fills_unmet_requirements_and_skips_done_courses() -> None:
    a = fixture_data.audit()
    unmet = {r.id: set(r.options) for r in a.requirements if r.status == "not_met"}
    done = {
        c.course_code
        for c in a.courses
        if c.status in (CourseRecordStatus.complete, CourseRecordStatus.in_progress)
    }
    res = _fixture_build(ConstraintSet(only_required=True, earliest_start=time(10, 0)))
    assert len(res.schedules) == 3
    for s in res.schedules:
        assert not _codes(s) & done
        for c in s.classes:
            assert c.requirement_ids, c.section.id
            for rid in c.requirement_ids:
                assert c.section.course_code in unmet[rid]


def test_returned_schedules_are_different() -> None:
    res = _fixture_build(ConstraintSet(earliest_start=time(10, 0)), n=5)
    assert len(res.schedules) == 5
    for i, a in enumerate(res.schedules):
        for b in res.schedules[i + 1 :]:
            assert schedules_differ(a, b)


def test_schedules_differ_definition() -> None:
    x = [section("AAA 101", "01"), section("BBB 101", "01"), section("CCC 101", "01")]

    def sched(*secs: Section) -> Schedule:
        from app.contracts import ScheduledClass, ScheduleWhy

        return Schedule(
            id="s",
            rank=1,
            score=0,
            total_credits=0,
            optimal=True,
            classes=[ScheduledClass(section=s) for s in secs],
            why=ScheduleWhy(),
        )

    base = sched(*x)
    one_swap = sched(section("AAA 101", "02"), x[1], x[2])
    two_swaps = sched(section("AAA 101", "02"), section("BBB 101", "02"), x[2])
    other_course = sched(x[0], x[1], section("DDD 101"))
    assert not schedules_differ(base, base)
    assert not schedules_differ(base, one_swap)
    assert schedules_differ(base, two_swaps)
    assert schedules_differ(base, other_course)


def test_each_solve_uses_the_time_limit_and_reports_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fixture solves to optimal in milliseconds, so a real timeout cannot be
    forced reliably. A solver that reports FEASIBLE (CP-SAT's status when it stops
    at the time limit) must give `optimal: false`, and every solve gets the limit."""
    limits: list[float] = []

    class TimedOutSolver(cp_model.CpSolver):
        def solve(self, *args: Any, **kwargs: Any) -> Any:
            limits.append(self.parameters.max_time_in_seconds)
            status = super().solve(*args, **kwargs)
            return cp_model.FEASIBLE if status == cp_model.OPTIMAL else status

    monkeypatch.setattr(cp_model, "CpSolver", TimedOutSolver)
    res = _fixture_build(ConstraintSet(earliest_start=time(10, 0)))
    assert len(res.schedules) == 3
    assert all(s.optimal is False for s in res.schedules)
    assert limits and all(lim == 3 for lim in limits)


def test_default_time_limit_is_three_seconds() -> None:
    assert config.SOLVER_TIME_LIMIT_S == 3


def test_fixture_schedules_are_optimal_without_a_timeout() -> None:
    res = _fixture_build(ConstraintSet(earliest_start=time(10, 0)))
    assert res.schedules and all(s.optimal for s in res.schedules)


# --- Structured why -------------------------------------------------------------


def test_why_is_structured() -> None:
    from app.contracts import Day

    res = _fixture_build(
        ConstraintSet(
            earliest_start=time(10, 0), days_off=[Day.F], include_courses=["CSE 212", "NOPE 999"]
        )
    )
    s = res.schedules[0]
    assert "earliest_start" in s.why.preferences_met
    assert "days_off:F" in s.why.preferences_met
    assert "credit_range" in s.why.preferences_met
    assert "include_courses:CSE 212" in s.why.preferences_met
    assert "include_courses:NOPE 999" in s.why.preferences_missed
    for pref in s.why.preferences_met + s.why.preferences_missed:
        assert " " not in pref.split(":")[0]  # keys, not sentences
    assert any(c.requirement_ids for c in s.classes)


def test_favorite_professors_listed_in_why() -> None:
    res = build_schedules(
        audit(requirement("r", "AAA 101")),
        [section("AAA 101", instructor="p-fav")],
        ConstraintSet(),
        max_results=1,
        credit_range=(3, 3),
        favorite_professor_ids={"p-fav"},
    )
    assert res.schedules[0].why.favorite_professor_ids == ["p-fav"]
