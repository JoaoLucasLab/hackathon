"""DATA-05: directory profile pages -> ProfessorSource kinds, LinkedIn removed, and
the professor rows populate_db.py writes (no database, no network).

The first tests run the scraper's HTML parser on two public profile pages saved in
fixtures/html/directory/ (fetched once by hand, Nov 14, 2026). The rest start from
the scraper's JSON and use made-up names.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from app.contracts.professors import ProfessorSource, ProfessorSourceKind
from app.schools.byui import professor_matching as pm

REPO = Path(__file__).resolve().parents[2]
URL = "https://www.byui.edu/directories/alice-doe"
FETCHED = "2026-11-14T09:32:20+00:00"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- saved pages --------------------------------------------------------------------

PAGES = REPO / "fixtures" / "html" / "directory"
BASE = "https://www.byui.edu/directories/"


def parse_saved(slug: str) -> dict[str, Any]:
    scraper = _load("scrape_faculty")
    html = (PAGES / f"{slug}.html").read_text(encoding="utf-8")
    profile = scraper.parse_profile(BASE + slug, html)
    assert profile is not None, f"{slug}.html is not read as a profile page"
    return dict(scraper.clean_profile(profile))


def test_page_with_headed_sections() -> None:
    p = parse_saved("scott-burton")
    assert (p["name"], p["job_title"]) == ("Scott Burton", "Faculty")
    assert p["url"] == BASE + "scott-burton" and p["fetched_at"]
    assert list(p["sections"]) == [
        "Biography",
        "Education",
        "Industry Experience",
        "Research Interests",
    ]
    sources = pm.profile_sources(p)
    assert sources["education"].startswith("Ph.D., Computer Science, Brigham Young University")
    assert "Zillow" in sources["work_experience"]
    assert "Machine Learning" in sources["research"]
    assert sources["biography"].startswith("Scott Burton holds a Ph.D. in computer science")
    assert sources["interests"] == ""  # no such section on the page


def test_page_with_only_a_description_gives_empty_sections() -> None:
    """Text without headings is the biography; the other kinds are empty, not errors,
    even though the text itself mentions "EDUCATION:" (no guessing)."""
    sources = pm.profile_sources(parse_saved("masaru-okuda"))
    assert sources["biography"].startswith("EDUCATION:")
    assert {k: v for k, v in sources.items() if k != "biography"} == {
        "education": "",
        "interests": "",
        "work_experience": "",
        "research": "",
    }


def test_saved_pages_become_professor_source_rows_with_url_and_time() -> None:
    populate = _load("populate_db")
    for slug in ("scott-burton", "masaru-okuda"):
        p = parse_saved(slug)
        rows = populate.source_rows("(SELECT 1)", p)
        assert len(rows) == 5
        assert all(f"'{BASE}{slug}'" in r and f"'{p['fetched_at']}'" in r for r in rows)
        for kind, value in pm.profile_sources(p).items():
            ProfessorSource(kind=kind, value=value, source_url=p["url"], fetched_at=p["fetched_at"])


def test_saved_pages_have_no_linkedin() -> None:
    for slug in ("scott-burton", "masaru-okuda"):
        assert "linkedin" not in str(parse_saved(slug)).lower()


def test_a_page_that_is_not_a_profile_is_skipped() -> None:
    scraper = _load("scrape_faculty")
    assert scraper.parse_profile(BASE + "cse-1", "<html><body><h1>CSE</h1></body></html>") is None


def full_profile() -> dict[str, Any]:
    return {
        "name": "Alice Doe",
        "url": URL,
        "fetched_at": FETCHED,
        "job_title": "Faculty",
        "email": "doea@example.edu",
        "office": "100 STC",
        "image_url": None,
        "tags": ["CSE"],
        "departments": ["computer-science-engineering"],
        "links": {"Schedule": "https://example.edu/s", "LinkedIn": "https://www.linkedin.com/in/x"},
        "sections": {
            "Description": "Alice Doe teaches programming.",
            "Education:": ["Ph.D., Computer Science", "B.S., Mathematics"],
            "Interests": "Compilers",
            "Previous Work Experience": ["Software engineer, 2010-2015"],
            "Research": "Program analysis",
            "LinkedIn Profile": "www.linkedin.com/in/x",
            "Hobbies and Activities": ["Hiking"],
        },
        "description": "Alice Doe teaches programming.\nLinkedIn Profile\nwww.linkedin.com/in/x",
    }


def test_sections_map_to_the_five_contract_kinds() -> None:
    sources = pm.profile_sources(full_profile())
    assert set(sources) == {k.value for k in ProfessorSourceKind}
    assert sources["education"] == "Ph.D., Computer Science\nB.S., Mathematics"
    assert sources["interests"] == "Compilers\n\nHiking"
    assert sources["work_experience"] == "Software engineer, 2010-2015"
    assert sources["research"] == "Program analysis"
    assert sources["biography"] == "Alice Doe teaches programming."


def test_a_missing_section_is_empty_not_an_error() -> None:
    p = full_profile()
    p["sections"] = {"Education": "M.S., Physics"}
    sources = pm.profile_sources(p)
    assert sources["education"] == "M.S., Physics"
    assert sources["research"] == sources["biography"] == ""
    assert pm.profile_sources({"sections": {}}) == {k: "" for k in pm.SOURCE_KINDS}


def test_scraper_drops_linkedin() -> None:
    scraper = _load("scrape_faculty")
    p = scraper.clean_profile(full_profile())
    assert "linkedin" not in str(p).lower()
    assert p["links"] == {"Schedule": "https://example.edu/s"}
    assert "Research" in p["sections"]


def test_populate_writes_profile_and_sources_with_url_and_time() -> None:
    populate = _load("populate_db")
    cse = "Computer Science & Engineering"
    data = {"sections": [{"instructors": ["Doe, Alice M."], "department": cse}]}
    p = full_profile()
    office = {**p, "name": "Bob Roe", "url": URL + "-roe", "job_title": "Office Manager"}
    teacher = {**p, "name": "Carol Poe", "url": URL + "-poe", "tags": ["Biology"]}
    matches = populate.match_faculty(data, [p, office, teacher])
    sql = populate.faculty_rows([p, office, teacher], matches)

    update = next(line for line in sql if line.startswith("UPDATE professors"))
    assert f"directory_url = '{URL}'" in update and "match_confidence = 1.0" in update
    sources = [line for line in sql if "INSERT INTO professor_sources" in line]
    assert len(sources) == 10  # five kinds for Alice, five for Carol
    assert all(f"'{FETCHED}'" in line for line in sources)
    assert all("source_url" in line for line in sources)
    # Directory-only teaching faculty get a row; office staff do not.
    assert any("'Poe, Carol'" in line and "'Biology'" in line for line in sql)
    assert not any("Roe" in line for line in sql)
