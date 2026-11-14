"""ENG-05: BYU-Idaho rules behind `SchoolRules` (track, exclusion reasons,
religion limit, waitlist cap)."""

from __future__ import annotations

from datetime import time

import pytest
from tests.engine_helpers import audit, requirement, section
from tests.test_prereq_evaluator import course

from app.api import fixture_data
from app.api.schedules import build_schedules as build_api
from app.contracts import (
    BuildSchedulesRequest,
    ConstraintSet,
    DeliveryMethod,
    ExclusionReason,
    SeatStatus,
    Section,
    Student,
    Term,
    Track,
)
from app.engine.prereqs.evaluator import PrereqChecker
from app.engine.solver import build_schedules
from app.schools.base import default_school
from app.schools.byui.rules import ByuiRules

RULES = ByuiRules()


def _hybrid(code: str) -> Section:
    return section(code, "03").model_copy(
        update={"id": f"2027;WI|{code}-03", "delivery_method": DeliveryMethod.hybrid}
    )


def _mixed() -> list[Section]:
    """Campus, online and hybrid sections for three courses."""
    return [
        section("AAA 101", "01", "MWF 10:15-11:15"),
        section("AAA 101", "02", None, online=True),
        section("BBB 101", "01", "TR 10:15-11:15"),
        section("BBB 101", "02", None, online=True),
        _hybrid("CCC 101"),
        section("CCC 101", "02", None, online=True),
    ]


def _build(track: Track | None) -> set[DeliveryMethod]:
    a = audit(
        requirement("ra", "AAA 101"), requirement("rb", "BBB 101"), requirement("rc", "CCC 101")
    )
    a = a.model_copy(update={"track": track})
    res = build_schedules(
        a, _mixed(), ConstraintSet(), max_results=3, credit_range=(9, 9), rules=RULES
    )
    assert res.schedules, res
    return {c.section.delivery_method for s in res.schedules for c in s.classes}


def test_track_without_winter_gets_only_online() -> None:
    delivered = _build(Track.spring_fall)
    assert delivered == {DeliveryMethod.online}


def test_off_track_exclusions_carry_reason_track() -> None:
    a = audit(requirement("ra", "AAA 101")).model_copy(update={"track": Track.spring_fall})
    res = build_schedules(a, _mixed(), ConstraintSet(), credit_range=(3, 3), rules=RULES)
    track_out = {e.section_id for e in res.excluded if e.reason == ExclusionReason.track}
    assert track_out == {"2027;WI|AAA 101-01", "2027;WI|BBB 101-01", "2027;WI|CCC 101-03"}


@pytest.mark.parametrize("track", [Track.fall_winter, Track.winter_spring])
def test_winter_track_gets_campus_and_online(track: Track) -> None:
    a = audit(requirement("ra", "AAA 101"), requirement("rb", "BBB 101"))
    a = a.model_copy(update={"track": track})
    res = build_schedules(a, _mixed(), ConstraintSet(), credit_range=(3, 9), rules=RULES)
    assert not [e for e in res.excluded if e.reason == ExclusionReason.track]
    term = fixture_data.terms()[0]
    assert RULES.allowed_delivery(Student(id="s", track=track), term) == set(DeliveryMethod)


def test_online_student_gets_online_sections() -> None:
    assert _build(Track.online) == {DeliveryMethod.online}
    term: Term = fixture_data.terms()[0]
    assert RULES.allowed_delivery(Student(id="s", track=Track.online), term) == {
        DeliveryMethod.online
    }


def test_unknown_track_filters_nothing() -> None:
    """The chat asks for the track; the rules do not guess one."""
    assert RULES.exclusion(_mixed()[0], Student(id="s", track=None), ConstraintSet()) is None


def test_block_term_codes_map_to_winter() -> None:
    assert RULES.season("2027;WI") == RULES.season("2027;WI;W1") == "winter"


# --- every exclusion carries a reason ------------------------------------------------


def test_each_exclusion_reason() -> None:
    a = audit(
        requirement("ra", "AAA 101"),
        requirement("rb", "BBB 101"),
        requirement("rc", "CCC 101"),
        requirement("rd", "DDD 101"),
        requirement("re", "EEE 101"),
        requirement("rf", "FFF 101"),
    ).model_copy(update={"track": Track.spring_fall})
    secs = [
        section("AAA 101", "01", "MWF 10:15-11:15"),  # campus while off-track -> track
        section("BBB 101", "01", None, online=True),  # prereq not met
        section("CCC 101", "01", None, online=True, status=SeatStatus.closed),  # closed
        section("DDD 101", "01", None, online=True),  # excluded by you
        section("EEE 101", "01", "TR 09:00-10:00", online=True),  # must-take, one section
        section("FFF 101", "01", "TR 09:30-10:30", online=True),  # clashes with EEE -> conflict
    ]
    checker = PrereqChecker([course("BBB 101", "MATH 112")], [])
    res = build_schedules(
        a,
        secs,
        ConstraintSet(exclude_courses=["DDD 101"], include_courses=["EEE 101"]),
        credit_range=(3, 3),
        prereqs=checker,
        rules=RULES,
    )
    reasons = {e.section_id.split("|")[1]: e.reason for e in res.excluded}
    assert reasons == {
        "AAA 101-01": ExclusionReason.track,
        "BBB 101-01": ExclusionReason.prerequisite,
        "CCC 101-01": ExclusionReason.closed,
        "DDD 101-01": ExclusionReason.excluded_by_you,
        "FFF 101-01": ExclusionReason.conflict,
    }
    assert all(e.detail for e in res.excluded)
    conflict = next(e for e in res.excluded if e.reason == ExclusionReason.conflict)
    assert conflict.detail == "conflicts with EEE 101-01 (must-take EEE 101)"


# --- religion --------------------------------------------------------------------------


def test_at_most_one_religion_course_with_note() -> None:
    a = audit(
        requirement("rel1", "REL 250"),
        requirement("rel2", "REL 275"),
        requirement("ra", "AAA 101"),
        requirement("rb", "BBB 101"),
    )
    secs = [
        section("REL 250", when="MWF 08:00-09:00", credits=2),
        section("REL 275", when="TR 08:00-09:00", credits=2),
        section("AAA 101", when="MWF 10:15-11:15"),
        section("BBB 101", when="TR 10:15-11:15"),
    ]
    res = build_schedules(
        a, secs, ConstraintSet(), max_results=3, credit_range=(1, 12), rules=RULES
    )
    assert res.schedules
    for s in res.schedules:
        rel = [c for c in s.classes if c.section.course_code.startswith("REL")]
        assert len(rel) <= 1
        notes = [w for w in s.warnings if w.kind == "religion_limit"]
        if rel:
            assert [w.message for w in notes] == [
                "You can add a second religion course after the first day of the semester."
            ]
        else:
            assert notes == []


def test_catalog_religion_flag_counts() -> None:
    rules = ByuiRules(courses=fixture_data.courses())
    assert rules.is_religion_course("REL 275")
    assert not rules.is_religion_course("CSE 212")


def test_fixture_schedules_hold_at_most_one_religion_course() -> None:
    rules = default_school().rules
    assert rules is not None
    res = build_api(BuildSchedulesRequest(max_results=5))
    assert res.schedules
    for s in res.schedules:
        assert sum(rules.is_religion_course(c.section.course_code) for c in s.classes) <= 1


# --- waitlist --------------------------------------------------------------------------


def _closed_courses() -> list[Section]:
    days = ["M", "T", "W", "R", "F"]
    return [
        section(f"W{c}A 101", when=f"{d} 10:00-11:00", credits=4, status=SeatStatus.closed)
        for c, d in zip("ABCDE", days, strict=True)
    ]


def test_closed_sections_left_out_without_waitlisting() -> None:
    a = audit(*(requirement(f"r{c}", f"W{c}A 101", needed=4) for c in "ABCDE"))
    res = build_schedules(a, _closed_courses(), ConstraintSet(), credit_range=(4, 20), rules=RULES)
    assert res.schedules == [] or all(not c.waitlisted for s in res.schedules for c in s.classes)
    assert {e.reason for e in res.excluded} == {ExclusionReason.closed}


def test_waitlisted_credits_capped_at_12() -> None:
    a = audit(*(requirement(f"r{c}", f"W{c}A 101", needed=4) for c in "ABCDE"))
    res = build_schedules(
        a,
        _closed_courses(),
        ConstraintSet(allow_waitlist=True),
        max_results=3,
        credit_range=(4, 20),
        rules=RULES,
    )
    assert res.schedules
    for s in res.schedules:
        waitlisted = sum(c.section.credits for c in s.classes if c.waitlisted)
        assert 0 < waitlisted <= RULES.max_waitlisted_credits() == 12


def test_never_two_waitlisted_sections_of_one_class() -> None:
    a = audit(requirement("r", "AAA 101"))
    secs = [
        section("AAA 101", "01", "MWF 08:00-09:00", status=SeatStatus.closed),
        section("AAA 101", "02", "TR 08:00-09:00", status=SeatStatus.waitlist),
    ]
    res = build_schedules(
        a, secs, ConstraintSet(allow_waitlist=True), max_results=3, credit_range=(3, 6), rules=RULES
    )
    assert res.schedules
    for s in res.schedules:
        assert len(s.classes) == 1


def test_morning_rule_still_applies_with_rules() -> None:
    a = audit(requirement("r", "AAA 101"))
    res = build_schedules(
        a,
        [section("AAA 101", when="MWF 08:00-09:00")],
        ConstraintSet(earliest_start=time(10, 0)),
        credit_range=(3, 3),
        rules=RULES,
    )
    assert res.schedules == []
