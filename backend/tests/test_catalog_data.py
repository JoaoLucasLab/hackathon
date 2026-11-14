"""catalog_data: database rows -> contracts, and the fixture fallback.

No Postgres here (CI has none): the row mapping runs on dicts shaped like the
query results. The real database was checked by hand (see the PR).
"""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

import pytest

from app.api import catalog_data, fixture_data
from app.contracts import BlockKind, DeliveryMethod, SeatStatus
from app.contracts.catalog import PrereqAll, PrereqUnparsed

AS_OF = datetime(2026, 11, 14, 5, 11, 39, tzinfo=UTC)


def course_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": "CSE 111",
        "title": "Programming with Functions",
        "department": "Computer Science & Engineering",
        "description": "Functions.",
        "credits": Decimal("2.00"),
        "prereq_text": "CSE 110",
        "prereq": {"type": "course", "course_code": "CSE 110"},
        "catalog_year": "2026-2027",
        "source_url": "https://student.byui.edu/ICS/Class_Schedule/",
    }
    return row | over


def section_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "row_id": 7,
        "course_code": "CSE 110",
        "title": "Intro to Programming",
        "department": "Computer Science & Engineering",
        "section": "01",
        "credits": Decimal("2.00"),
        "term_code": "2027;WI",
        "block_kind": "full",
        "delivery_method": "In-Person",
        "class_type": "DAY",
        "status": "closed",
        "seats_open": 0,
        "seats_total": 30,
        "seats_as_of": AS_OF,
        "source_url": "https://student.byui.edu/ICS/Class_Schedule/",
        "fetched_at": AS_OF,
        "created_at": AS_OF,
    }
    return row | over


MEETING = {
    "section_id": 7,
    "days": "TR",
    "start_time": time(12, 45),
    "end_time": time(13, 45),
    "start_date": date(2027, 1, 6),
    "end_date": date(2027, 4, 8),
    "room": "STC 231",
    "tba": False,
}

PROFESSOR = {
    "row_id": 3,
    "full_name": "Lawrence, Bradley W.",
    "first_name": "Bradley",
    "last_name": "Lawrence",
    "middle_name": "W.",
    "department": "Computer Science & Engineering",
}


def test_section_maps_to_contract() -> None:
    s = catalog_data.to_section(section_row(), [MEETING], ["p-x"])
    assert s.id == "2027;WI|CSE 110-01"
    assert s.block is BlockKind.full
    assert s.delivery_method is DeliveryMethod.campus
    assert s.credits == 2.0
    assert [d.value for d in s.meetings[0].days] == ["T", "R"]
    assert s.meetings[0].start_time == time(12, 45)
    assert s.seats.status is SeatStatus.closed
    assert s.seats.as_of == AS_OF
    assert s.instructor_ids == ["p-x"]


def test_first_block_section() -> None:
    s = catalog_data.to_section(section_row(term_code="2027;WI;W1", block_kind="first"), [], [])
    assert s.id == "2027;WI;W1|CSE 110-01"
    assert s.block is BlockKind.first
    assert s.meetings == []


@pytest.mark.parametrize(
    ("site", "expected"),
    [
        ("In-Person", DeliveryMethod.campus),
        ("Blended", DeliveryMethod.hybrid),
        ("Online", DeliveryMethod.online),
        ("Virtual Live", DeliveryMethod.online),
        ("Professionally Mentored", DeliveryMethod.online),
    ],
)
def test_delivery_methods(site: str, expected: DeliveryMethod) -> None:
    assert catalog_data.to_delivery(site) is expected


@pytest.mark.parametrize(
    ("status", "seats_open", "expected"),
    [
        ("open", 5, SeatStatus.open),
        ("reopened", 2, SeatStatus.open),
        ("closed", 0, SeatStatus.closed),
        (None, 0, SeatStatus.closed),
        (None, 3, SeatStatus.open),
    ],
)
def test_seat_status(status: str | None, seats_open: int, expected: SeatStatus) -> None:
    seats = catalog_data.to_seats(section_row(status=status, seats_open=seats_open))
    assert seats.status is expected


def test_seats_without_time_use_fetched_at() -> None:
    seats = catalog_data.to_seats(section_row(seats_as_of=None))
    assert seats.as_of == AS_OF


def test_course_prereq_tree() -> None:
    course = catalog_data.to_course(course_row())
    assert course.credits == 2.0
    assert course.prereq is not None and course.prereq.type == "course"


def test_null_prereq_is_not_read_yet() -> None:
    """NULL stays None: not read yet, never "no prerequisites"."""
    assert catalog_data.to_course(course_row(prereq=None)).prereq is None


def test_site_lists_no_prereqs() -> None:
    prereq = catalog_data.to_course(course_row(prereq={"type": "all", "items": []})).prereq
    assert isinstance(prereq, PrereqAll) and prereq.items == []


def test_bad_prereq_tree_becomes_unparsed() -> None:
    course = catalog_data.to_course(course_row(prereq={"type": "course", "course_code": "bad"}))
    assert isinstance(course.prereq, PrereqUnparsed)
    assert course.prereq.text == "CSE 110"


def test_professor_ids_stable_and_split_by_department() -> None:
    a = catalog_data.professor_id("Lawrence, Bradley W.", "Computer Science & Engineering")
    assert a == catalog_data.professor_id("Lawrence, Bradley W.", "Computer Science & Engineering")
    assert a != catalog_data.professor_id("Lawrence, Bradley W.", "Mathematics")


def test_catalog_links_professors_and_sections() -> None:
    catalog = catalog_data.Catalog(
        courses=[course_row()],
        sections=[section_row()],
        meetings=[MEETING],
        professors=[PROFESSOR],
        instructors=[{"section_id": 7, "professor_id": 3, "course_code": "CSE 110"}],
    )
    prof = catalog.professors[0]
    assert catalog.sections[0].instructor_ids == [prof.id]
    assert prof.winter_courses == ["CSE 110"]
    assert (prof.first_name, prof.last_name) == ("Bradley", "Lawrence")
    assert prof.rmp_url.startswith("https://www.ratemyprofessors.com/search/")
    assert prof.topic_tags == [] and prof.sources == []


def test_no_database_url_uses_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert catalog_data.source() == "fixtures"
    assert catalog_data.sections() == fixture_data.sections()
    assert catalog_data.courses() == fixture_data.courses()


def test_database_error_is_raised_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    """A set but broken DATABASE_URL never falls back to fixture data."""

    def boom(url: str) -> catalog_data.Catalog:
        raise RuntimeError("database down")

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@127.0.0.1:1/none")
    monkeypatch.setattr(catalog_data, "_read_database", boom)
    catalog_data.reload()
    try:
        with pytest.raises(RuntimeError, match="database down"):
            catalog_data.sections()
    finally:
        catalog_data.reload()
