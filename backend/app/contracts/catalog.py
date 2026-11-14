"""Terms, blocks, courses and prerequisite expressions."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from app.contracts.common import BlockKind, Contract

COURSE_CODE_PATTERN = r"^[A-Z]{2,5} \d{3}[A-Z]?$"
CourseCode = Annotated[str, Field(pattern=COURSE_CODE_PATTERN, examples=["CSE 111"])]


class Block(Contract):
    """One part of a term: the full semester, First Block or Second Block."""

    kind: BlockKind
    term_code: str = Field(examples=["2027;WI", "2027;WI;W1", "2027;WI;W2"])
    label: str = Field(examples=["First Block"])
    start_date: date
    end_date: date


class Term(Contract):
    code: str = Field(examples=["2027;WI"])
    name: str = Field(examples=["Winter 2027"])
    start_date: date
    end_date: date
    blocks: list[Block]


# --- Prerequisite expression tree -------------------------------------------------


class PrereqCourse(Contract):
    type: Literal["course"] = "course"
    course_code: CourseCode
    min_grade: str | None = Field(default=None, examples=["C"])
    concurrent_ok: bool = False


class PrereqCondition(Contract):
    """A condition the app cannot verify (test score, PathwayConnect, standing,
    instructor consent). Always shown as "Check this before registering"."""

    type: Literal["condition"] = "condition"
    text: str


class PrereqUnparsed(Contract):
    """Text we could not parse. Shown as a warning, never treated as "no prereqs"."""

    type: Literal["unparsed"] = "unparsed"
    text: str


class PrereqAll(Contract):
    type: Literal["all"] = "all"
    items: list[PrereqExpression]


class PrereqAny(Contract):
    type: Literal["any"] = "any"
    items: list[PrereqExpression]


PrereqExpression = Annotated[
    PrereqAll | PrereqAny | PrereqCourse | PrereqCondition | PrereqUnparsed,
    Field(discriminator="type"),
]

PrereqAll.model_rebuild()
PrereqAny.model_rebuild()


class Course(Contract):
    code: CourseCode
    title: str
    credits: float = Field(ge=0)
    department: str
    description: str = ""
    prereq_text: str | None = Field(
        default=None, description="Raw prerequisite text exactly as the catalog prints it."
    )
    prereq: PrereqExpression | None = Field(
        default=None,
        description="Parsed tree. None means not parsed yet, NOT 'no prerequisites'.",
    )
    equivalents: list[CourseCode] = Field(default_factory=list)
    is_religion: bool = False
    catalog_year: str = Field(examples=["2026-2027"])
    source_url: str
