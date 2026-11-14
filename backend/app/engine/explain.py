"""Structured `why` for a schedule (ENG-03).

Only keys and ids, never sentences: Claude rewords these facts in `llm/`.
Preference keys: `credit_range`, `earliest_start`, `latest_end`, `days_off:<D>`,
`delivery_methods`, `only_required`, `include_courses:<CODE>`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.contracts import ConstraintSet, ScheduleWarning, ScheduleWhy, Section


def explain(
    sections: Sequence[Section],
    constraints: ConstraintSet,
    favorite_professor_ids: Iterable[str] = (),
) -> ScheduleWhy:
    """Every hard constraint is met by construction; only included courses can be missed."""
    met: list[str] = ["credit_range"]
    missed: list[str] = []
    if constraints.earliest_start is not None:
        met.append("earliest_start")
    if constraints.latest_end is not None:
        met.append("latest_end")
    met.extend(f"days_off:{d.value}" for d in constraints.days_off)
    if constraints.delivery_methods:
        met.append("delivery_methods")
    if constraints.only_required:
        met.append("only_required")
    codes = {s.course_code for s in sections}
    for code in constraints.include_courses:
        (met if code in codes else missed).append(f"include_courses:{code}")

    favorites = set(favorite_professor_ids)
    fav_ids = sorted({p for s in sections for p in s.instructor_ids if p in favorites})
    return ScheduleWhy(
        preferences_met=met, preferences_missed=missed, favorite_professor_ids=fav_ids
    )


def section_warnings(section: Section) -> list[ScheduleWarning]:
    return [
        ScheduleWarning(
            kind="tba_meeting",
            message="Meeting time is TBA. Check this before registering.",
            course_code=section.course_code,
            section_id=section.id,
        )
        for m in section.meetings
        if m.tba
    ]
