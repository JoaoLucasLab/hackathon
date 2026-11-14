"""DATA-05: matching class-schedule instructors to directory profiles (no database,
no network). The names below are made up."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.schools.byui import professor_matching as pm

REPO = Path(__file__).resolve().parents[2]
CSE = "Computer Science & Engineering"
MATH = "Mathematics"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def profile(name: str, dept: str = "computer-science-engineering", **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "url": f"https://www.byui.edu/directories/{pm.slug(name)}",
        "fetched_at": "2026-11-14T09:32:20+00:00",
        "job_title": "Faculty",
        "tags": [],
        "departments": [dept],
        "sections": {},
        "description": "",
        **extra,
    }


def match_one(full_name: str, department: str, profiles: list[dict[str, Any]]) -> pm.Match:
    [m] = pm.match_all([pm.ScheduleName.parse(full_name, department)], profiles)
    return m


@pytest.mark.parametrize(
    ("schedule", "directory", "confidence"),
    [
        ("Doe, Alice M.", "Alice Doe", 1.0),
        ("Doe, Bradley W.", "Brad Doe", 0.9),  # prefix nickname
        ("Doe, William", "Bill Doe", 0.9),  # nickname table
        ("Doe, Edward Darrell", "Ted Doe", 0.9),
        ("Doe, Kenneth Nathan", "Nate Doe", 0.9),  # goes by the middle name
        ("Santa Maria, Karen E", "Karen Santa Maria", 1.0),  # two-word last name
        ("Doé, Alice", "Alice Doe", 1.0),  # accents ignored
    ],
)
def test_matches_with_confidence(schedule: str, directory: str, confidence: float) -> None:
    m = match_one(schedule, CSE, [profile(directory)])
    assert m.profile is not None and m.profile["name"] == directory
    assert m.confidence == confidence


@pytest.mark.parametrize(
    ("schedule", "directory"),
    [
        ("Doe, Alice", "Mary Doe"),  # other first name
        ("Doe, Al", "Allen Doe"),  # a 2-letter prefix is not a nickname
        ("Smith, Alice", "Alice Doe"),  # other last name
    ],
)
def test_different_people_do_not_match(schedule: str, directory: str) -> None:
    m = match_one(schedule, CSE, [profile(directory)])
    assert m.profile is None and m.reason == "not in the directory"


def test_other_department_is_below_threshold_and_listed() -> None:
    m = match_one("Doe, Alice", CSE, [profile("Alice Doe", dept="mathematics")])
    assert m.profile is None
    assert m.confidence == 0.7 < pm.MIN_CONFIDENCE
    assert "low confidence" in m.reason


def test_department_can_come_from_the_directory_tags() -> None:
    p = profile("Alice Doe", dept="engineering-technology", tags=["CS/SE"])
    assert match_one("Doe, Alice", CSE, [p]).confidence == 1.0


def test_two_equal_candidates_are_ambiguous() -> None:
    m = match_one("Doe, Bradley", CSE, [profile("Brad Doe"), profile("Bradley Doe")])
    # Bradley Doe is the exact name and wins over the nickname.
    assert m.profile is not None and m.profile["name"] == "Bradley Doe"
    two = [
        profile("Brad Doe"),
        profile("Brad Doe", url="https://www.byui.edu/directories/brad-doe-2"),
    ]
    m = match_one("Doe, Bradley", CSE, two)
    assert m.profile is None and m.reason.startswith("ambiguous")


def test_overrides_fix_or_forbid_a_match() -> None:
    p = profile("Alice Doe", dept="mathematics")
    s = [pm.ScheduleName.parse("Doe, Alice", CSE)]
    fix = [{"full_name": "Doe, Alice", "department": CSE, "directory_url": p["url"]}]
    [m] = pm.match_all(s, [p], fix)
    assert m.profile is p and m.confidence == 1.0
    block: list[dict[str, Any]] = [
        {"full_name": "Doe, Alice", "department": CSE, "directory_url": None}
    ]
    [m] = pm.match_all(s, [profile("Alice Doe")], block)
    assert m.profile is None


def test_two_john_smiths_in_different_departments_stay_two_rows() -> None:
    populate = _load("populate_db")
    data = {
        "source": "https://student.byui.edu/ICS/Class_Schedule/",
        "term": "2027;WI",
        "subjects": ["CSE", "MATH"],
        "scraped_at": "2026-11-14T00:00:00+00:00",
        "count": 2,
        "sections": [
            {"instructors": ["Smith, John"], "department": CSE},
            {"instructors": ["Smith, John"], "department": MATH},
            {"instructors": ["Smith, John"], "department": CSE},
        ],
    }
    names = populate.schedule_names(data)
    assert [(n.full_name, n.department) for n in names] == [
        ("Smith, John", CSE),
        ("Smith, John", MATH),
    ]
    # Each department's John Smith gets the profile from his own department only.
    cse = profile("John Smith", dept="computer-science-engineering")
    math = profile("John Smith", dept="mathematics")
    math["url"] += "-math"
    matches = pm.match_all(names, [cse, math])
    assert [m.profile["url"] if m.profile else None for m in matches] == [cse["url"], math["url"]]


def test_teaching_titles() -> None:
    for title in ["Faculty", "Adjunct Faculty", "Department Chair", "Dean", "Online Faculty"]:
        assert pm.is_teaching({"job_title": title})
    for other in ["Office Manager", "Data Analyst", None]:
        assert not pm.is_teaching({"job_title": other})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Interests: Undergraduate Research, chemistry education", True),
        ("He mentored student research for ten years.", True),
        ("I love doing research with students.", True),
        ("Research: number theory.", None),  # research, but nothing about students
        ("", None),
    ],
)
def test_undergrad_research_only_when_the_profile_says_so(text: str, expected: bool | None) -> None:
    assert pm.lists_undergrad_research({"description": text}) is expected
