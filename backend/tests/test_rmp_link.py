"""DATA-05: the Rate My Professors link is a plain URL, and the backend never talks to
ratemyprofessors.com."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from app.schools.byui.rmp_link import rmp_link

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "backend" / "app"


@pytest.mark.parametrize(
    ("first", "last", "school", "url"),
    [
        ("Alice", "Doe", "1234", "https://www.ratemyprofessors.com/search/professors/1234?q=Alice%20Doe"),
        ("Karen", "Santa Maria", "1234", "https://www.ratemyprofessors.com/search/professors/1234?q=Karen%20Santa%20Maria"),
        ("Alice", "Doe", "", "https://www.ratemyprofessors.com/search/professors?q=Alice%20Doe"),
        ("", "Doe", "1234", "https://www.ratemyprofessors.com/search/professors/1234?q=Doe"),
    ],
)  # fmt: skip
def test_rmp_link(first: str, last: str, school: str, url: str) -> None:
    assert rmp_link(first, last, school_id=school) == url


def test_school_id_comes_from_the_school_config() -> None:
    """BYU-Idaho's id was looked up once by hand and lives in config.yaml."""
    from app.schools.byui.rules import ByuiRules

    assert ByuiRules().rmp_link("Alice", "Doe") == (
        "https://www.ratemyprofessors.com/search/professors/1754?q=Alice%20Doe"
    )


def test_backend_never_requests_ratemyprofessors() -> None:
    """Only rmp_link.py may name the site, and it only builds a string."""
    mentions = [
        p.relative_to(APP).as_posix()
        for p in APP.rglob("*.py")
        if "ratemyprofessors" in p.read_text(encoding="utf-8").lower()
    ]
    assert mentions == ["schools/byui/rmp_link.py"]
    source = (APP / "schools" / "byui" / "rmp_link.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(httpx|requests|urllib\.request|aiohttp|socket)\b", source)


def test_rate_my_professor_api_is_not_a_dependency() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    deps = project["dependencies"] + [
        d for extra in project.get("optional-dependencies", {}).values() for d in extra
    ]
    assert not any("ratemyprofessor" in d.lower() for d in deps)
