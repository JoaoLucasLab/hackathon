"""Sections and meetings for one term."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import Field, model_validator

from app.contracts.catalog import CourseCode
from app.contracts.common import BlockKind, Contract, Day, DeliveryMethod, SeatStatus


class Meeting(Contract):
    """One meeting line. `TR 12:45-01:45PM (01/06/2027 - 04/08/2027) STC 231`."""

    days: list[Day] = Field(default_factory=list)
    start_time: time | None = None
    end_time: time | None = None
    start_date: date
    end_date: date
    room: str | None = None
    tba: bool = Field(default=False, description="TBA meetings never conflict; shown as a warning.")

    @model_validator(mode="after")
    def _times_consistent(self) -> Meeting:
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("start_time and end_time must both be set or both be empty")
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class SeatInfo(Contract):
    status: SeatStatus
    open: int = Field(ge=0)
    total: int = Field(ge=0)
    as_of: datetime = Field(description='Always shown to students as "seats as of <time>".')


class Section(Contract):
    id: str = Field(examples=["2027;WI|CSE 110-01"])
    course_code: CourseCode
    section: str = Field(examples=["01"])
    title: str
    credits: float = Field(ge=0)
    term_code: str = Field(examples=["2027;WI"])
    block: BlockKind
    delivery_method: DeliveryMethod
    class_type: str = Field(default="Lecture", examples=["Lecture", "Lab"])
    department: str
    instructor_ids: list[str] = Field(default_factory=list)
    meetings: list[Meeting] = Field(
        default_factory=list, description="Empty for online sections with no set time."
    )
    seats: SeatInfo
    source_url: str
    fetched_at: datetime
