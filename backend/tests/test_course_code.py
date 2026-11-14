import pytest

from app.schools.byui.parsing import CourseRef, ParseError, normalize_course_code


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CSE111", CourseRef("CSE 111", None)),
        ("CSE 111", CourseRef("CSE 111", None)),
        ("CSE 111-01", CourseRef("CSE 111", "01")),
        ("cse 111", CourseRef("CSE 111", None)),
        ("  MATH 221A ", CourseRef("MATH 221A", None)),
        ("REL 250-12", CourseRef("REL 250", "12")),
        ("CSE111-01", CourseRef("CSE 111", "01")),
    ],
)
def test_normalize(raw: str, expected: CourseRef) -> None:
    assert normalize_course_code(raw) == expected


@pytest.mark.parametrize("raw", ["", "CSE", "111", "C 111", "CSE 11"])
def test_bad_codes_raise(raw: str) -> None:
    with pytest.raises(ParseError):
        normalize_course_code(raw)
