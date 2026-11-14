"""Shared enums and base model for every contract."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    """Base for every contract model.

    `extra="forbid"` means a payload with an unknown field (for example a student
    name slipped into an audit) fails validation instead of being silently kept.
    """

    model_config = ConfigDict(extra="forbid")


class Day(StrEnum):
    """Day letters as BYU-Idaho prints them. T is Tuesday, R is Thursday, S is Saturday."""

    M = "M"
    T = "T"
    W = "W"
    R = "R"
    F = "F"
    S = "S"


class BlockKind(StrEnum):
    full = "full"  # full semester, term code 2027;WI
    first = "first"  # First Block, 2027;WI;W1
    second = "second"  # Second Block, 2027;WI;W2


class Track(StrEnum):
    fall_winter = "fall_winter"
    winter_spring = "winter_spring"
    spring_fall = "spring_fall"
    online = "online"


class DeliveryMethod(StrEnum):
    campus = "campus"
    online = "online"
    hybrid = "hybrid"


class SeatStatus(StrEnum):
    open = "open"
    closed = "closed"
    waitlist = "waitlist"


class RequirementStatus(StrEnum):
    complete = "complete"
    in_progress = "in_progress"
    not_met = "not_met"
