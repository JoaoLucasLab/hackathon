"""Student, degree audit and requirements.

None of these models has a name or student-ID field, and `extra="forbid"` rejects
any payload that tries to add one.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field

from app.contracts.catalog import CourseCode
from app.contracts.common import Contract, RequirementStatus, Track


class Student(Contract):
    id: str = Field(description="Anonymous session id. Not a BYU-Idaho ID.")
    track: Track | None = Field(default=None, description="None means unknown: ask the student.")
    catalog_year: str | None = Field(default=None, examples=["2024-2025"])
    consented_at: datetime | None = None


class CourseRecordStatus(StrEnum):
    complete = "complete"
    in_progress = "in_progress"  # counts for prerequisites, labeled "pending grade"
    transfer = "transfer"


class AuditCourse(Contract):
    course_code: CourseCode
    title: str
    credits: float = Field(ge=0)
    grade: str | None = Field(default=None, description="None while in progress.")
    term: str = Field(examples=["Fall 2026"])
    status: CourseRecordStatus
    equivalent_of: CourseCode | None = Field(
        default=None, description="BYU-Idaho equivalent for transfer or AP credit."
    )
    instructor: str | None = Field(
        default=None,
        examples=["Hale, Marcus"],
        description="Professor as the audit prints it, when shown. Used by mentor ranking.",
    )


class AuditRequirement(Contract):
    id: str = Field(examples=["major-core-1"])
    group: str = Field(examples=["Major Core"])
    name: str = Field(examples=["Programming with Functions"])
    status: RequirementStatus
    credits_required: float = Field(ge=0)
    credits_needed: float = Field(ge=0)
    options: list[CourseCode] = Field(
        default_factory=list, description="Courses that can fill this requirement."
    )
    courses_counted: list[CourseCode] = Field(default_factory=list)


class ValidationFlag(Contract):
    field: str = Field(examples=["requirements[3].options[0]"])
    kind: str = Field(examples=["unknown_course", "credit_mismatch", "invalid_status"])
    message: str


class DegreeAudit(Contract):
    audit_date: date
    catalog_year: str
    major: str
    minor: str | None = None
    track: Track | None = Field(default=None, description="None when the audit does not show it.")
    total_credits_required: float = Field(ge=0)
    total_credits_earned: float = Field(ge=0)
    courses: list[AuditCourse] = Field(default_factory=list)
    requirements: list[AuditRequirement] = Field(default_factory=list)
    validation_flags: list[ValidationFlag] = Field(default_factory=list)
