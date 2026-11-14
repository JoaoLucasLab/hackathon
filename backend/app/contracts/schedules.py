"""Constraints the student sets, and the schedules the solver returns."""

from __future__ import annotations

from datetime import time
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field, model_validator

from app.contracts.catalog import CourseCode
from app.contracts.common import Contract, Day, DeliveryMethod
from app.contracts.sections import Section

ADVISING_NOTE: Final = "Confirm with BYU-Idaho Academic Advising."


class ConstraintSet(Contract):
    credit_min: float | None = Field(default=None, ge=0, description="None: use school default.")
    credit_max: float | None = Field(default=None, ge=0, description="None: use school default.")
    earliest_start: time | None = Field(default=None, description="No class starts before this.")
    latest_end: time | None = Field(default=None, description="No class ends after this.")
    days_off: list[Day] = Field(default_factory=list)
    include_courses: list[CourseCode] = Field(default_factory=list)
    exclude_courses: list[CourseCode] = Field(default_factory=list)
    exclude_section_ids: list[str] = Field(default_factory=list)
    delivery_methods: list[DeliveryMethod] = Field(
        default_factory=list, description="Empty means any."
    )
    only_required: bool = Field(default=False, description="Only classes required to graduate.")
    allow_waitlist: bool = False
    only_favorite_professors: bool = False

    @model_validator(mode="after")
    def _range_ok(self) -> ConstraintSet:
        if self.credit_min is not None and self.credit_max is not None:
            if self.credit_min > self.credit_max:
                raise ValueError("credit_min must not exceed credit_max")
        return self


class ExclusionReason(StrEnum):
    track = "track"
    prerequisite = "prerequisite"
    conflict = "conflict"
    closed = "closed"
    excluded_by_you = "excluded by you"


class ScheduleWarning(Contract):
    kind: Literal["prerequisite_check", "tba_meeting", "unparsed_prereq", "religion_limit", "other"]
    message: str = Field(examples=["Check this before registering: LUC test score of at least 110"])
    course_code: CourseCode | None = None
    section_id: str | None = None


class ScheduledClass(Contract):
    section: Section
    requirement_ids: list[str] = Field(
        default_factory=list, description="AuditRequirement ids this class fills."
    )
    waitlisted: bool = False
    backups: list[Section] = Field(default_factory=list, max_length=2)
    warnings: list[ScheduleWarning] = Field(default_factory=list)


class ScheduleWhy(Contract):
    """Structured facts behind a schedule. The solver writes no free text."""

    preferences_met: list[str] = Field(default_factory=list, examples=[["earliest_start"]])
    preferences_missed: list[str] = Field(default_factory=list, examples=[["days_off:F"]])
    favorite_professor_ids: list[str] = Field(default_factory=list)


class Schedule(Contract):
    id: str
    rank: int = Field(ge=1)
    score: float
    total_credits: float = Field(ge=0)
    optimal: bool
    classes: list[ScheduledClass]
    why: ScheduleWhy
    warnings: list[ScheduleWarning] = Field(default_factory=list)
    advising_note: Literal["Confirm with BYU-Idaho Academic Advising."] = ADVISING_NOTE


class Excluded(Contract):
    section_id: str
    reason: ExclusionReason
    detail: str | None = Field(default=None, examples=["prerequisite: needs MATH 112"])


class Relaxation(Contract):
    constraint: str = Field(examples=["earliest_start"])
    change: str = Field(examples=["allow one class before 10:00"])
    schedules_available: int = Field(ge=1)
    patch: ConstraintSet = Field(description="The ConstraintSet to apply with one click.")


class BuildSchedulesRequest(Contract):
    constraints: ConstraintSet | None = Field(
        default=None, description="None: use the session's saved constraints."
    )
    max_results: int = Field(default=3, ge=1, le=5)


class BuildSchedulesResponse(Contract):
    schedules: list[Schedule]
    excluded: list[Excluded] = Field(default_factory=list)
    relaxation: Relaxation | None = None


class ExplainScheduleRequest(Contract):
    """The schedule to explain, exactly as `POST /api/schedules/build` returned it."""

    schedule: Schedule


class ScheduleExplanation(Contract):
    """Claude's wording of a schedule's structured `why` (AI-03). Facts only from it."""

    schedule_id: str
    available: bool = Field(
        description="False when no grounded text could be written; show the structured why."
    )
    why: str | None = Field(default=None, examples=["Every class counts toward your degree."])
    tradeoffs: list[str] = Field(default_factory=list, max_length=3)
    advising_note: Literal["Confirm with BYU-Idaho Academic Advising."] = ADVISING_NOTE
