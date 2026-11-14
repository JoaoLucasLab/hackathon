"""ENG-04: catalog prerequisite text -> PrereqExpression, in code (no Claude call)."""

from __future__ import annotations

import pytest

from app.api import fixture_data
from app.contracts import (
    PrereqAll,
    PrereqAny,
    PrereqCondition,
    PrereqCourse,
    PrereqExpression,
    PrereqUnparsed,
)
from app.engine.prereqs.parser import PrereqParseError, parse_or_unparsed, parse_prereq_text


def C(code: str, min_grade: str | None = None, concurrent_ok: bool = False) -> PrereqCourse:
    return PrereqCourse(course_code=code, min_grade=min_grade, concurrent_ok=concurrent_ok)


def Cond(text: str) -> PrereqCondition:
    return PrereqCondition(text=text)


def ALL(*items: PrereqExpression) -> PrereqAll:
    return PrereqAll(items=list(items))


def ANY(*items: PrereqExpression) -> PrereqAny:
    return PrereqAny(items=list(items))


def _has_unparsed(expr: PrereqExpression) -> bool:
    if isinstance(expr, PrereqUnparsed):
        return True
    return isinstance(expr, PrereqAll | PrereqAny) and any(_has_unparsed(i) for i in expr.items)


def test_brief_sample() -> None:
    text = (
        "CSE 110 or CS 101 (last offered 2023) or CIT 160 or PathwayConnect "
        "or LUC test score of at least 110"
    )
    assert parse_prereq_text(text) == ALL(
        ANY(
            C("CSE 110"),
            C("CS 101"),
            C("CIT 160"),
            Cond("PathwayConnect"),
            Cond("LUC test score of at least 110"),
        )
    )


def test_every_fixture_course_parses_in_code() -> None:
    courses = [c for c in fixture_data.courses() if c.prereq_text]
    assert len(courses) >= 20
    for course in courses:
        expr = parse_prereq_text(course.prereq_text)
        assert not _has_unparsed(expr), course.code
        assert expr.items, f"{course.code}: text parsed to no prerequisites"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CSE 210", ALL(C("CSE 210"))),
        ("CSE111", ALL(C("CSE 111"))),
        ("CSE 111-01", ALL(C("CSE 111"))),
        ("Prerequisite: CSE 210.", ALL(C("CSE 210"))),
        ("CSE 212 and junior standing", ALL(C("CSE 212"), Cond("junior standing"))),
        ("CSE 212 and (WDD 231 or CIT 230)", ALL(C("CSE 212"), ANY(C("WDD 231"), C("CIT 230")))),
        ("CSE 212 and MATH 215 (C or better)", ALL(C("CSE 212"), C("MATH 215", "C"))),
        ("MATH 112 with a C or better", ALL(C("MATH 112", "C"))),
        ("MATH 112 with a grade of B- or better", ALL(C("MATH 112", "B-"))),
        ("MATH 221A or instructor consent", ALL(ANY(C("MATH 221A"), Cond("instructor consent")))),
        ("CSE 110 or 111", ALL(ANY(C("CSE 110"), C("CSE 111")))),
        ("CSE 110, CSE 111, and CSE 210", ALL(C("CSE 110"), C("CSE 111"), C("CSE 210"))),
        ("CSE 110, CIT 160, or CS 101", ALL(ANY(C("CSE 110"), C("CIT 160"), C("CS 101")))),
        ("CSE 210 (may be taken concurrently)", ALL(C("CSE 210", concurrent_ok=True))),
        (
            "(CSE 110 or CIT 160) with a C or better",
            ALL(ANY(C("CSE 110", "C"), C("CIT 160", "C"))),
        ),
    ],
)
def test_parses(text: str, expected: PrereqAll) -> None:
    assert parse_prereq_text(text) == expected


def test_nested_three_levels() -> None:
    text = "CSE 212 and (MATH 112 or (MATH 110 and math placement score of at least 75))"
    assert parse_prereq_text(text) == ALL(
        C("CSE 212"),
        ANY(C("MATH 112"), ALL(C("MATH 110"), Cond("math placement score of at least 75"))),
    )


@pytest.mark.parametrize("text", [None, "", "   ", "None", "none."])
def test_no_text_means_the_catalog_lists_none(text: str | None) -> None:
    assert parse_prereq_text(text) == ALL()


@pytest.mark.parametrize(
    "text",
    [
        "CSE 212 and MATH 112 or MATH 221A",  # ambiguous grouping: not guessed
        "CSE 212 and (MATH 112 or MATH 221A",  # parenthesis not closed
        "Completion of the foundations sequence",
        "CSE 212 and",
        "or better",
        "CS 1A",
    ],
)
def test_unreadable_text_raises(text: str) -> None:
    with pytest.raises(PrereqParseError):
        parse_prereq_text(text)


def test_unreadable_text_becomes_unparsed_never_no_prereqs() -> None:
    text = "CSE 212 and MATH 112 or MATH 221A"
    assert parse_or_unparsed(text) == PrereqUnparsed(text=text)
