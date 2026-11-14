"""DATA-04: populate_db.py loads the catalog from the scrape (no database, no network).

The SQL is checked as text; scripts/populate_db.py runs it through psql. The run on a
real database (second run changes 0 course rows) is checked by hand, since CI has no
Postgres.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
CLEAN = REPO / "scripts" / "out" / "course_search_clean.json"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


populate = _load("populate_db")
refresh = _load("refresh_data")


@pytest.fixture(scope="module")
def data() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(CLEAN.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def sql(data: dict[str, Any]) -> list[str]:
    return str(populate.build_sql(data)).splitlines()


def _course_insert(sql: list[str], code: str) -> str:
    return next(
        line for line in sql if line.startswith("INSERT INTO courses") and f"'{code}'" in line
    )


@pytest.mark.parametrize(
    ("term", "year"),
    [("2027;WI", "2026-2027"), ("2027;SP", "2026-2027"), ("2026;FA", "2026-2027")],
)
def test_catalog_year_comes_from_the_term(term: str, year: str) -> None:
    assert populate.catalog_year(term) == year


def test_every_course_is_stored_with_its_catalog_fields(
    data: dict[str, Any], sql: list[str]
) -> None:
    courses = {s["course"] for s in data["sections"]}
    assert len(courses) >= 40
    assert sum(line.startswith("INSERT INTO courses") for line in sql) == len(courses)
    line = _course_insert(sql, "CSE 111")
    for column in ("title", "credits", "description", "prereq_text", "catalog_year", "source_url"):
        assert column in line
    assert "'2026-2027'" in line
    # The raw prerequisite text keeps CS 101 as an option.
    assert "CS 101 (C- or better) OR" in line


def test_variable_credit_course_stores_the_most_a_section_offers(sql: list[str]) -> None:
    line = _course_insert(sql, "CSE 290R")
    assert ", 3.0, " in line


def test_catalog_year_can_be_overridden(data: dict[str, Any]) -> None:
    assert "'2027-2028'" in _course_insert(
        populate.build_sql(data, "2027-2028").splitlines(), "CSE 110"
    )


def test_unchanged_courses_are_not_written(sql: list[str]) -> None:
    """The upsert writes a course only when a value differs, and reports added vs updated."""
    line = _course_insert(sql, "CSE 110")
    assert "ON CONFLICT (university_id, code) DO UPDATE" in line
    assert "IS DISTINCT FROM" in line and "RETURNING (xmax = 0)" in line


def test_courses_are_kept_and_the_schedule_is_replaced(
    data: dict[str, Any], sql: list[str]
) -> None:
    assert sql[0] == "BEGIN;" and sql[-1] == "COMMIT;"
    truncate = next(line for line in sql if line.startswith("TRUNCATE"))
    assert "sections" in truncate and "meetings" in truncate
    assert "courses," not in truncate and "universities" not in truncate
    # Courses no longer in the scrape are removed, after the upserts.
    delete = next(i for i, line in enumerate(sql) if line.startswith("DELETE FROM courses"))
    last_course = max(i for i, line in enumerate(sql) if line.startswith("INSERT INTO courses"))
    assert delete > last_course
    assert "'CSE 111'" in sql[delete]


def test_refresh_refuses_an_incomplete_scrape(tmp_path: Path) -> None:
    def scrape(sections: list[tuple[str, str]]) -> Path:
        path = tmp_path / f"scrape_{len(sections)}.json"
        rows = [{"course": c, "section": s} for c, s in sections]
        path.write_text(json.dumps({"subjects": ["CSE", "MATH"], "sections": rows}))
        return path

    good = scrape([("CSE 110", "01"), ("CSE 111", "01"), ("MATH 100A", "01"), ("MATH 108X", "01")])
    assert refresh.scrape_problems(good, good, 0.8) == []
    no_math = scrape([("CSE 110", "01"), ("CSE 111", "01"), ("CSE 210", "01"), ("CSE 212", "01")])
    assert refresh.scrape_problems(no_math, good, 0.8) == ["subject MATH has no sections"]
    shrunk = scrape([("CSE 110", "01"), ("MATH 100A", "01")])
    [problem] = refresh.scrape_problems(shrunk, good, 0.8)
    assert "fewer than 80%" in problem
