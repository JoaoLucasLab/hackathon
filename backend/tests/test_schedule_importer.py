"""DATA-03: the Course Search scraper and cleaner on saved pages (no network).

The pages in fixtures/html/course_search/ were saved from the public BYU-Idaho
Course Search (Winter 2027, CSE) on Nov 13, 2026. The scraper's HTML parsers and
the cleaner's time step (which calls ENG-02's parser) run on them here; the scraper
and cleaner themselves live in scripts/.
"""

from __future__ import annotations

import importlib.util
from datetime import date, time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.contracts import Day
from app.schools.byui.parsing import parse_meeting

REPO = Path(__file__).resolve().parents[2]
PAGES = REPO / "fixtures" / "html" / "course_search"

Row = dict[str, Any]  # one section row as the scraper returns it


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scraper = _load("scrape_course_search")
cleaner = _load("data_cleaner")


def _page(name: str) -> str:
    return (PAGES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rows() -> dict[str, Row]:
    parsed = scraper.parse_list(_page("results_CSE_2027WI_page1.html"))
    return {f"{r['course']}-{r['section']}": r for r in parsed}


def test_results_page_has_every_row(rows: dict[str, Row]) -> None:
    assert len(rows) == 20
    assert list(rows)[:2] == ["CSE 110-01", "CSE 110-02"]


def test_cse_110_01_row(rows: dict[str, Row]) -> None:
    """The plan's example: CSE 110-01, TR 12:45-01:45PM (01/06/2027 - 04/08/2027) STC 231."""
    row = rows["CSE 110-01"]
    assert (row["course"], row["section"]) == ("CSE 110", "01")
    assert row["title"] == "Intro to Programming"
    assert row["credits"] == 2.0
    assert (row["class_type"], row["delivery_method"]) == ("DAY", "In-Person")
    assert row["block"] is None
    [meeting] = row["meetings"]
    assert meeting["raw"] == "TR 12:45-01:45PM"
    assert (meeting["start_date"], meeting["end_date"]) == ("2027-01-06", "2027-04-08")
    assert meeting["room"] == "STC 231"


def test_cse_110_01_times_come_from_eng02_parser(rows: dict[str, Row]) -> None:
    [meeting] = rows["CSE 110-01"]["meetings"]
    cleaned, error = cleaner.with_times(meeting)
    assert error is None
    assert (cleaned["start_time"], cleaned["end_time"], cleaned["tba"]) == ("12:45", "13:45", False)

    # The same line through ENG-02's parser gives Tuesday and Thursday, 12:45 to 13:45.
    parsed = parse_meeting("TR 12:45-01:45PM (01/06/2027 - 04/08/2027) STC 231")
    assert parsed is not None
    assert parsed.days == [Day.T, Day.R]
    assert (parsed.start_time, parsed.end_time) == (time(12, 45), time(13, 45))
    assert (parsed.start_date, parsed.end_date) == (date(2027, 1, 6), date(2027, 4, 8))
    assert parsed.room == "STC 231"


@pytest.mark.parametrize(
    ("key", "start", "end"),
    [
        ("CSE 110-04", "09:00", "10:00"),  # MTWR 09:00-10:00AM, First Block
        ("CSE 110-06", "11:30", "12:30"),  # 11:30AM-12:30PM: both markers present
        ("CSE 110-10", "14:00", "15:00"),  # 02:00-03:00PM
        ("CSE 110-A1", None, None),  # online: 00:00-00:00AM, no set time
    ],
)
def test_times(rows: dict[str, Row], key: str, start: str | None, end: str | None) -> None:
    cleaned, error = cleaner.with_times(rows[key]["meetings"][0])
    assert error is None
    assert (cleaned["start_time"], cleaned["end_time"]) == (start, end)


def test_cleaner_keeps_original_meeting_fields(rows: dict[str, Row]) -> None:
    meeting = rows["CSE 110-01"]["meetings"][0]
    cleaned, _ = cleaner.with_times(meeting)
    assert {k: cleaned[k] for k in meeting} == meeting
    keys = list(cleaned)
    after = keys.index("time_raw") + 1
    assert keys[after : after + 3] == ["start_time", "end_time", "tba"]


@pytest.mark.parametrize(
    ("key", "block", "term_code", "dates"),
    [
        ("CSE 110-01", None, "2027;WI", ("2027-01-06", "2027-04-08")),
        ("CSE 110-04", "Winter First Block", "2027;WI;W1", ("2027-01-06", "2027-02-19")),
        ("CSE 110-A5", "Winter Second Block", "2027;WI;W2", ("2027-02-22", "2027-04-08")),
    ],
)
def test_blocks(
    rows: dict[str, Row], key: str, block: str | None, term_code: str, dates: tuple[str, str]
) -> None:
    row = rows[key]
    assert row["block"] == block
    assert scraper.BLOCK_TERMS.get(row["block"] or "", "2027;WI") == term_code
    meeting = row["meetings"][0]
    assert (meeting["start_date"], meeting["end_date"]) == dates


def test_section_details_page() -> None:
    detail = scraper.parse_detail(_page("details_CSE110-01.html"))
    assert detail["code_on_page"] == ("CSE 110", "01")
    assert detail["instructors"] == ["Lawrence, Bradley W."]
    assert detail["status_raw"] == "Closed (0 out of 30 seats)"
    assert (detail["status"], detail["seats_open"], detail["seats_total"]) == ("closed", 0, 30)
    assert detail["department"] == "Computer Science & Engineering"
    assert detail["locations"][0]["location"] == "MAIN Campus, Science & Technology Ctr, 231"


def test_requisites_page_to_prereq_tree() -> None:
    rows = scraper.parse_requisites(_page("requisites_CSE111-01.html"))["requisites"]
    assert [r["connector_before"] for r in rows] == [None, "OR", "OR", "OR", "OR"]
    tree = cleaner.build_prereq(rows, {"CS 101", "CSE 110", "CIT 160", "PW 100T"})
    assert tree["type"] == "any"
    courses = [i["course_code"] for i in tree["items"] if i["type"] == "course"]
    assert courses == ["CS 101", "CSE 110", "CIT 160", "PW 100T"]
    assert {"type": "condition", "text": "LUC exam: SCORE >= 110"} in tree["items"]
