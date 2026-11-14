"""ENG-05: an impossible request returns no schedules plus the one constraint to
loosen, tried in the fixed order from the school config."""

from __future__ import annotations

from datetime import time

from fastapi.testclient import TestClient
from tests.engine_helpers import audit, requirement, section

from app.contracts import BuildSchedulesResponse, ConstraintSet, Day, Section
from app.engine.solver import build_schedules
from app.main import app
from app.schools.byui.rules import ByuiRules, load_config

RULES = ByuiRules()
A = audit(requirement("ra", "AAA 101"), requirement("rb", "BBB 101"))


def _early() -> list[Section]:
    """Both courses only meet early; one of them also only meets on Friday."""
    return [
        section("AAA 101", "01", "MW 08:00-09:00"),
        section("AAA 101", "02", "MW 09:00-10:00"),
        section("BBB 101", "01", "F 09:00-10:00"),
    ]


def _build(c: ConstraintSet) -> BuildSchedulesResponse:
    return build_schedules(A, _early(), c, max_results=3, credit_range=(6, 6), rules=RULES)


def test_impossible_request_names_one_constraint_to_loosen() -> None:
    res = _build(ConstraintSet(earliest_start=time(10, 0)))
    assert res.schedules == []
    r = res.relaxation
    assert r is not None
    assert r.constraint == "earliest_start"
    # The smallest change first: 09:00, not 08:00.
    assert r.change == "allow classes from 09:00 instead of 10:00"
    assert r.patch.earliest_start == time(9, 0)
    assert r.schedules_available >= 1


def test_applying_the_patch_gives_that_many_schedules() -> None:
    res = _build(ConstraintSet(earliest_start=time(10, 0)))
    assert res.relaxation is not None
    again = _build(res.relaxation.patch)
    assert len(again.schedules) == res.relaxation.schedules_available
    assert again.relaxation is None


def _either() -> list[Section]:
    """AAA 101 meets either early (08:00) or on Friday; either loosening alone works."""
    return [
        section("AAA 101", "01", "F 10:00-11:00"),
        section("AAA 101", "02", "MW 08:00-09:00"),
        section("BBB 101", "01", "TR 10:00-11:00"),
    ]


BLOCKED = ConstraintSet(earliest_start=time(10, 0), days_off=[Day.F])


def _either_build(rules: ByuiRules) -> BuildSchedulesResponse:
    return build_schedules(A, _either(), BLOCKED, max_results=3, credit_range=(6, 6), rules=rules)


def test_order_comes_from_config() -> None:
    order = RULES.relaxation_order()
    assert order.index("earliest_start") < order.index("days_off")
    res = _either_build(RULES)
    assert res.schedules == []
    assert res.relaxation is not None
    assert res.relaxation.constraint == "earliest_start"
    assert res.relaxation.change == "allow classes from 08:00 instead of 10:00"
    assert res.relaxation.patch.days_off == [Day.F]  # only one constraint changes


def test_custom_order_is_followed() -> None:
    data = load_config()
    data["relaxation_order"] = ["days_off", "earliest_start"]
    res = _either_build(ByuiRules(data))
    assert res.relaxation is not None
    assert res.relaxation.constraint == "days_off"
    assert res.relaxation.change == "allow classes on F"
    assert res.relaxation.patch.earliest_start == time(10, 0)


def test_two_blocking_constraints_give_no_single_relaxation() -> None:
    """BBB 101 meets only Friday 09:00: loosening one constraint is not enough."""
    res = _build(BLOCKED)
    assert res.schedules == []
    assert res.relaxation is None


def test_relaxation_order_lists_only_known_constraints() -> None:
    known = {
        "only_favorite_professors",
        "earliest_start",
        "latest_end",
        "days_off",
        "delivery_methods",
        "allow_waitlist",
        "only_required",
        "credit_min",
        "credit_max",
        "include_courses",
    }
    assert set(RULES.relaxation_order()) <= known
    assert "exclude_courses" not in RULES.relaxation_order()


def test_excluded_courses_are_never_loosened() -> None:
    """Without BBB 101 only 3 of the 6 credits fit. The suggestion lowers the
    minimum; it never brings back the course the student excluded."""
    res = _build(ConstraintSet(exclude_courses=["BBB 101"]))
    assert res.schedules == []
    assert res.relaxation is not None
    assert res.relaxation.constraint == "credit_min"
    assert res.relaxation.change == "lower the minimum to 3 credits"
    assert res.relaxation.patch.exclude_courses == ["BBB 101"]


def test_feasible_request_has_no_relaxation() -> None:
    res = _build(ConstraintSet())
    assert res.schedules
    assert res.relaxation is None


def test_nothing_helps_gives_no_relaxation() -> None:
    res = build_schedules(A, [], ConstraintSet(), credit_range=(6, 6), rules=RULES)
    assert res.schedules == []
    assert res.relaxation is None


def test_only_favorites_with_no_favorite_is_loosened_first() -> None:
    res = _build(ConstraintSet(only_favorite_professors=True))
    assert res.relaxation is not None
    assert res.relaxation.constraint == "only_favorite_professors"
    assert res.relaxation.patch.only_favorite_professors is False


def test_endpoint_returns_relaxation_on_fixtures() -> None:
    api = TestClient(app)
    body = {"constraints": {"earliest_start": "17:00:00"}, "max_results": 3}
    res = api.post("/api/schedules/build", json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["schedules"] == []
    relax = data["relaxation"]
    assert relax["constraint"] == "earliest_start"
    assert relax["schedules_available"] >= 1
    applied = api.post(
        "/api/schedules/build", json={"constraints": relax["patch"], "max_results": 3}
    ).json()
    assert len(applied["schedules"]) == relax["schedules_available"]
