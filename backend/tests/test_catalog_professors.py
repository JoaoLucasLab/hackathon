"""DATA-05: professors from catalog_data carry the public directory profile.

No Postgres (CI has none): rows are dicts shaped like the query results, as in
test_catalog_data.py. Names are made up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.api import catalog_data
from app.contracts import ProfessorSource

FETCHED = datetime(2026, 11, 14, 9, 32, 20, tzinfo=UTC)
URL = "https://www.byui.edu/directories/alice-doe"


def prof_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "row_id": 3,
        "full_name": "Doe, Alice M.",
        "first_name": "Alice",
        "last_name": "Doe",
        "middle_name": "M.",
        "department": "Computer Science & Engineering",
        "job_title": "Faculty",
        "lists_undergrad_research": None,
    }
    return row | over


def source_row(kind: str, value: str, professor_id: int = 3) -> dict[str, Any]:
    return {
        "professor_id": professor_id,
        "kind": kind,
        "value": value,
        "source_url": URL,
        "fetched_at": FETCHED,
    }


def source(kind: str, value: str) -> ProfessorSource:
    return catalog_data.to_source(source_row(kind, value))


@pytest.mark.parametrize(
    ("bio", "summary"),
    [
        ("", None),
        ("Alice Doe teaches   programming.", "Alice Doe teaches programming."),
        (
            "Alice Doe holds an M.S. in physics. " + "She likes long walks. " * 20,
            ("Alice Doe holds an M.S. in physics. " + "She likes long walks. " * 11).strip(),
        ),
    ],
)
def test_bio_summary_quotes_whole_sentences(bio: str, summary: str | None) -> None:
    got = catalog_data.bio_summary([source("education", "B.S."), source("biography", bio)])
    assert got == summary
    assert got is None or len(got) <= catalog_data.BIO_SUMMARY_MAX


def test_profile_reaches_the_contract() -> None:
    rows = [
        source_row("biography", "Alice teaches compilers."),
        source_row("education", "Ph.D., Computer Science"),
        source_row("research", ""),
    ]
    p = catalog_data.to_professor(prof_row(lists_undergrad_research=True), ["CSE 111"], rows)
    assert p.title == "Faculty"
    assert p.lists_undergrad_research is True
    assert [s.kind for s in p.sources] == ["education", "research", "biography"]  # contract order
    assert all(s.source_url == URL and s.fetched_at == FETCHED for s in p.sources)
    assert p.bio_summary == "Alice teaches compilers."
    assert p.winter_courses == ["CSE 111"]


def test_professor_without_profile() -> None:
    """Old query rows (no profile columns) and unmatched professors still work."""
    row = {
        k: v for k, v in prof_row().items() if k not in ("job_title", "lists_undergrad_research")
    }
    p = catalog_data.to_professor(row, [])
    assert p.sources == [] and p.bio_summary is None and p.title is None
    assert p.lists_undergrad_research is None  # unknown, never False


def test_catalog_attaches_sources_to_the_right_professor() -> None:
    catalog = catalog_data.Catalog(
        courses=[],
        sections=[],
        meetings=[],
        professors=[prof_row(), prof_row(row_id=4, full_name="Roe, Bob", last_name="Roe")],
        instructors=[],
        professor_sources=[source_row("interests", "Compilers", professor_id=3)],
    )
    alice, bob = catalog.professors
    assert [s.value for s in alice.sources] == ["Compilers"]
    assert bob.sources == []


def test_rmp_link_uses_the_school_id() -> None:
    """conftest registers BYU-Idaho, as app startup does; its id is 1754."""
    p = catalog_data.to_professor(prof_row(), [])
    assert p.rmp_url == "https://www.ratemyprofessors.com/search/professors/1754?q=Alice%20Doe"


def test_rmp_link_filled_after_startup_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """app.main loads the catalog before registering the school; the link still
    appears once professors are read."""
    built = catalog_data.Catalog([], [], [], [prof_row()], [])
    built.professors = [p.model_copy(update={"rmp_url": ""}) for p in built.professors]
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(catalog_data, "_database", lambda: built)
    [p] = catalog_data.professors()
    assert p.rmp_url.endswith("/search/professors/1754?q=Alice%20Doe")
