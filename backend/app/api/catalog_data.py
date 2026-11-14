"""Courses, sections and professors for the app: from Postgres when `DATABASE_URL`
is set, from the checked-in fixtures when it is empty (tests, CI, a laptop with no
database).

Read only. The tables are filled by the Data scripts (`scripts/populate_db.py`,
`scripts/refresh_data.py`) from the public Course Search scrape; this module never
writes to them. If `DATABASE_URL` is set and the database cannot be read, the
error is raised: the app never falls back to fixture data in that case, because
students would see invented sections.

The data is read once per process and kept in memory (about 300 sections). After
a refresh of the database, restart the backend, or call `reload()`.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from functools import cache
from typing import Any
from urllib.parse import quote

from pydantic import TypeAdapter, ValidationError

from app.api import fixture_data
from app.contracts import (
    BlockKind,
    Course,
    Day,
    DeliveryMethod,
    Meeting,
    Professor,
    SeatInfo,
    SeatStatus,
    Section,
)
from app.contracts.catalog import PrereqExpression, PrereqUnparsed

log = logging.getLogger(__name__)

Row = Mapping[str, Any]

# Only one school is loaded (plan.md scope); this is `universities.short_code`.
UNIVERSITY = "byui"

# Course Search prints these delivery methods. Anything not done in a campus
# classroom counts as online, so an off-track student can still take it.
DELIVERY = {
    "in-person": DeliveryMethod.campus,
    "blended": DeliveryMethod.hybrid,
    "online": DeliveryMethod.online,
    "virtual live": DeliveryMethod.online,
    "professionally mentored": DeliveryMethod.online,
}

UNREADABLE_PREREQ = "The prerequisites for this course could not be read."

_prereq_adapter: TypeAdapter[PrereqExpression] = TypeAdapter(PrereqExpression)


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def source() -> str:
    """ "database" or "fixtures": where courses, sections and professors come from."""
    return "database" if database_url() else "fixtures"


# --------------------------------------------------------------- row -> contract


def professor_id(full_name: str, department: str) -> str:
    """Stable id from name and department, so favorites survive a database reload
    (row ids change on every full refresh). Same name in another department is
    another professor (AGENTS.md)."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{full_name} {department}".lower()).strip("-")
    return f"p-{slug}"


def rmp_url(first_name: str, last_name: str) -> str:
    """Plain search link opened in the student's browser. Nothing is fetched from it."""
    name = quote(f"{first_name} {last_name}".strip())
    return f"https://www.ratemyprofessors.com/search/professors/0?q={name}"


def to_prereq(tree: Any, text: str | None, code: str) -> PrereqExpression | None:
    """NULL stays None (not read yet). A tree that does not fit the contract becomes
    `unparsed`, never "no prerequisites"."""
    if tree is None:
        return None
    try:
        return _prereq_adapter.validate_python(tree)
    except ValidationError:
        log.warning("Prerequisite tree for %s does not fit the contract; stored as unparsed", code)
        return PrereqUnparsed(text=text or UNREADABLE_PREREQ)


def to_course(row: Row) -> Course:
    return Course(
        code=row["code"],
        title=row["title"],
        credits=float(row["credits"] or 0),
        department=row["department"],
        description=row["description"] or "",
        prereq_text=row["prereq_text"],
        prereq=to_prereq(row["prereq"], row["prereq_text"], row["code"]),
        catalog_year=row["catalog_year"] or "",
        source_url=row["source_url"] or "",
    )


def to_days(days: str) -> list[Day]:
    known = {d.value for d in Day}
    unknown = set(days) - known
    if unknown:
        log.warning("Unknown day letters %s left out of a meeting", sorted(unknown))
    return [Day(d) for d in days if d in known]


def to_meeting(row: Row) -> Meeting:
    return Meeting(
        days=to_days(row["days"] or ""),
        start_time=row["start_time"],
        end_time=row["end_time"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        room=row["room"],
        tba=bool(row["tba"]),
    )


def to_delivery(value: str | None) -> DeliveryMethod:
    method = DELIVERY.get((value or "").strip().lower())
    if method is None:
        log.warning("Unknown delivery method %r, treated as campus", value)
        return DeliveryMethod.campus
    return method


def to_seats(row: Row) -> SeatInfo:
    """'reopened' is an open section again. Seat counts always carry their time."""
    seats_open = int(row["seats_open"] or 0)
    status = (row["status"] or "").strip().lower()
    if status == "closed":
        seat_status = SeatStatus.closed
    elif status in {"open", "reopened"}:
        seat_status = SeatStatus.open
    else:
        seat_status = SeatStatus.open if seats_open > 0 else SeatStatus.closed
    as_of: datetime = row["seats_as_of"] or row["fetched_at"] or row["created_at"]
    return SeatInfo(
        status=seat_status, open=seats_open, total=int(row["seats_total"] or 0), as_of=as_of
    )


def to_section(row: Row, meetings: Iterable[Row], instructor_ids: list[str]) -> Section:
    return Section(
        id=f"{row['term_code']}|{row['course_code']}-{row['section']}",
        course_code=row["course_code"],
        section=row["section"],
        title=row["title"],
        credits=float(row["credits"]),
        term_code=row["term_code"],
        block=BlockKind(row["block_kind"]),
        delivery_method=to_delivery(row["delivery_method"]),
        class_type=row["class_type"] or "Lecture",
        department=row["department"],
        instructor_ids=instructor_ids,
        meetings=[to_meeting(m) for m in meetings],
        seats=to_seats(row),
        source_url=row["source_url"],
        fetched_at=row["fetched_at"] or row["seats_as_of"] or row["created_at"],
    )


def to_professor(row: Row, winter_courses: Iterable[str]) -> Professor:
    first = row["first_name"] or ""
    last = row["last_name"] or row["full_name"]
    return Professor(
        id=professor_id(row["full_name"], row["department"]),
        first_name=first,
        last_name=last,
        middle=row["middle_name"],
        department=row["department"],
        winter_courses=sorted(set(winter_courses)),
        rmp_url=rmp_url(first, last),
    )


# ------------------------------------------------------------------------ reads

_COURSES_SQL = """
SELECT c.code, c.title, c.department, c.description, c.credits, c.prereq_text,
       c.prereq, c.catalog_year, c.source_url
FROM courses c JOIN universities u ON u.id = c.university_id
WHERE u.short_code = %(uni)s
ORDER BY c.code
"""

_SECTIONS_SQL = """
SELECT s.id AS row_id, c.code AS course_code, c.title, c.department, s.section,
       s.credits, t.code AS term_code, t.block_kind, s.delivery_method, s.class_type,
       s.status, s.seats_open, s.seats_total, s.seats_as_of, s.source_url,
       s.fetched_at, s.created_at
FROM sections s
JOIN courses c ON c.id = s.course_id
JOIN terms t ON t.id = s.term_id
JOIN universities u ON u.id = s.university_id
WHERE u.short_code = %(uni)s
ORDER BY c.code, s.section, t.code
"""

_MEETINGS_SQL = """
SELECT m.section_id, m.days, m.start_time, m.end_time, m.start_date, m.end_date,
       m.room, m.tba
FROM meetings m
JOIN sections s ON s.id = m.section_id
JOIN universities u ON u.id = s.university_id
WHERE u.short_code = %(uni)s
ORDER BY m.section_id, m.position
"""

_PROFESSORS_SQL = """
SELECT p.id AS row_id, p.full_name, p.first_name, p.last_name, p.middle_name, p.department
FROM professors p JOIN universities u ON u.id = p.university_id
WHERE u.short_code = %(uni)s
ORDER BY p.last_name, p.first_name, p.department
"""

_INSTRUCTORS_SQL = """
SELECT si.section_id, si.professor_id, c.code AS course_code
FROM section_instructors si
JOIN sections s ON s.id = si.section_id
JOIN courses c ON c.id = s.course_id
JOIN universities u ON u.id = s.university_id
WHERE u.short_code = %(uni)s
ORDER BY si.section_id, si.position
"""


class Catalog:
    """Everything read from the database in one go, mapped to the contracts."""

    def __init__(
        self,
        courses: list[Row],
        sections: list[Row],
        meetings: list[Row],
        professors: list[Row],
        instructors: list[Row],
    ) -> None:
        prof_ids = {p["row_id"]: professor_id(p["full_name"], p["department"]) for p in professors}
        meetings_by_section: dict[Any, list[Row]] = defaultdict(list)
        for m in meetings:
            meetings_by_section[m["section_id"]].append(m)
        instructors_by_section: dict[Any, list[str]] = defaultdict(list)
        courses_by_prof: dict[Any, set[str]] = defaultdict(set)
        for i in instructors:
            instructors_by_section[i["section_id"]].append(prof_ids[i["professor_id"]])
            courses_by_prof[i["professor_id"]].add(i["course_code"])

        self.courses = [to_course(c) for c in courses]
        self.sections = [
            to_section(s, meetings_by_section[s["row_id"]], instructors_by_section[s["row_id"]])
            for s in sections
        ]
        self.professors = [to_professor(p, courses_by_prof[p["row_id"]]) for p in professors]


def _read_database(url: str) -> Catalog:
    import psycopg
    from psycopg.rows import dict_row

    params = {"uni": UNIVERSITY}
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=10) as conn:
        conn.read_only = True

        def rows(sql: str) -> list[Row]:
            return list(conn.execute(sql, params).fetchall())

        catalog = Catalog(
            courses=rows(_COURSES_SQL),
            sections=rows(_SECTIONS_SQL),
            meetings=rows(_MEETINGS_SQL),
            professors=rows(_PROFESSORS_SQL),
            instructors=rows(_INSTRUCTORS_SQL),
        )
    if not catalog.sections:
        raise RuntimeError(
            "DATABASE_URL is set but the database has no sections. Load it with "
            "`python3 scripts/refresh_data.py --skip-scrape`, or unset DATABASE_URL "
            "to run on the fixtures."
        )
    log.info(
        "Catalog from the database: %d courses, %d sections, %d professors",
        len(catalog.courses),
        len(catalog.sections),
        len(catalog.professors),
    )
    return catalog


@cache
def _database() -> Catalog:
    return _read_database(database_url())


def reload() -> None:
    """Forget the cached data; the next call reads again."""
    _database.cache_clear()


# ------------------------------------------------------------------- public API


def courses() -> list[Course]:
    return _database().courses if database_url() else fixture_data.courses()


def sections() -> list[Section]:
    return _database().sections if database_url() else fixture_data.sections()


def professors() -> list[Professor]:
    return _database().professors if database_url() else fixture_data.professors()


def section_by_id() -> dict[str, Section]:
    return {s.id: s for s in sections()}


def professor_by_id() -> dict[str, Professor]:
    return {p.id: p for p in professors()}
