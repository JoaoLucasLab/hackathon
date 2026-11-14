"""ENG-03: candidate sections come from the audit's unmet requirements and the
student's hard constraints. Every section left out carries a reason."""

from __future__ import annotations

from datetime import time

import pytest
from tests.engine_helpers import audit, requirement, section

from app.api import fixture_data
from app.contracts import (
    ConstraintSet,
    CourseRecordStatus,
    Day,
    DeliveryMethod,
    ExclusionReason,
    SeatStatus,
    Section,
)
from app.engine.candidates import build_candidates, remaining_requirements


def test_remaining_requirements_are_the_unmet_ones() -> None:
    remaining = remaining_requirements(fixture_data.audit())
    assert remaining
    assert all(r.status == "not_met" for r in remaining)
    assert "core-data-structures" in {r.id for r in remaining}
    assert "core-classes" not in {r.id for r in remaining}  # in progress


def test_fixture_candidates_skip_completed_and_in_progress_courses() -> None:
    a = fixture_data.audit()
    done = {
        c.course_code
        for c in a.courses
        if c.status in (CourseRecordStatus.complete, CourseRecordStatus.in_progress)
    }
    pool = build_candidates(a, fixture_data.sections(), ConstraintSet())
    codes = {c.section.course_code for c in pool.candidates}
    assert codes and not codes & done


def test_requirement_ids_attached() -> None:
    a = audit(requirement("r-ds", "CSE 212"), requirement("r-web", "CSE 340", "CSE 341"))
    pool = build_candidates(
        a, [section("CSE 212"), section("CSE 341", when="TR 10:15-11:15")], ConstraintSet()
    )
    by_code = {c.section.course_code: c.requirement_ids for c in pool.candidates}
    assert by_code == {"CSE 212": ("r-ds",), "CSE 341": ("r-web",)}


@pytest.mark.parametrize(
    ("constraints", "sec", "reason", "detail_part"),
    [
        (
            ConstraintSet(earliest_start=time(10, 0)),
            section("AAA 101", when="MWF 09:00-10:00"),
            ExclusionReason.excluded_by_you,
            "before 10:00",
        ),
        (
            ConstraintSet(latest_end=time(15, 0)),
            section("AAA 101", when="TR 14:00-15:30"),
            ExclusionReason.excluded_by_you,
            "after 15:00",
        ),
        (
            ConstraintSet(days_off=[Day.F]),
            section("AAA 101", when="MWF 10:15-11:15"),
            ExclusionReason.excluded_by_you,
            "F",
        ),
        (
            ConstraintSet(exclude_courses=["AAA 101"]),
            section("AAA 101"),
            ExclusionReason.excluded_by_you,
            "AAA 101",
        ),
        (
            ConstraintSet(exclude_section_ids=["2027;WI|AAA 101-01"]),
            section("AAA 101"),
            ExclusionReason.excluded_by_you,
            "section",
        ),
        (
            ConstraintSet(delivery_methods=[DeliveryMethod.online]),
            section("AAA 101"),
            ExclusionReason.excluded_by_you,
            "campus",
        ),
        (
            ConstraintSet(),
            section("AAA 101", status=SeatStatus.closed),
            ExclusionReason.closed,
            "closed",
        ),
        (
            ConstraintSet(only_required=True),
            section("ZZZ 999"),
            ExclusionReason.excluded_by_you,
            "not required",
        ),
    ],
)
def test_exclusions_carry_a_reason(
    constraints: ConstraintSet, sec: Section, reason: ExclusionReason, detail_part: str
) -> None:
    pool = build_candidates(audit(requirement("r", "AAA 101")), [sec], constraints)
    assert pool.candidates == []
    [ex] = pool.excluded
    assert ex.reason == reason
    assert ex.detail and detail_part in ex.detail


def test_closed_section_kept_as_waitlisted_when_allowed() -> None:
    pool = build_candidates(
        audit(requirement("r", "AAA 101")),
        [section("AAA 101", status=SeatStatus.closed)],
        ConstraintSet(allow_waitlist=True),
    )
    [cand] = pool.candidates
    assert cand.waitlisted


def test_online_section_with_no_time_passes_time_filters() -> None:
    pool = build_candidates(
        audit(requirement("r", "AAA 101")),
        [section("AAA 101", when=None, online=True)],
        ConstraintSet(earliest_start=time(10, 0), days_off=[Day.F]),
    )
    assert len(pool.candidates) == 1


def test_included_course_survives_only_required() -> None:
    pool = build_candidates(
        audit(requirement("r", "AAA 101")),
        [section("ZZZ 999")],
        ConstraintSet(only_required=True, include_courses=["ZZZ 999"]),
    )
    assert [c.section.course_code for c in pool.candidates] == ["ZZZ 999"]
