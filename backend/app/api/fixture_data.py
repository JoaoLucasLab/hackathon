"""Loads the checked-in fixtures, validated against the contracts.

Stub endpoints read from here until each block's real code lands.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter

from app import config
from app.contracts import Course, DegreeAudit, Professor, Section, Term


class StubSchedule(BaseModel):
    """`fixtures/stub_schedules.json`: section ids for the stub schedule endpoint."""

    id: str
    section_ids: list[str]
    preferences_met: list[str] = Field(default_factory=list)
    preferences_missed: list[str] = Field(default_factory=list)


def _read(name: str) -> Any:
    path: Path = config.FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def audit() -> DegreeAudit:
    return DegreeAudit.model_validate(_read("audit.json"))


@cache
def courses() -> list[Course]:
    return TypeAdapter(list[Course]).validate_python(_read("courses.json"))


@cache
def sections() -> list[Section]:
    return TypeAdapter(list[Section]).validate_python(_read("sections.json"))


@cache
def professors() -> list[Professor]:
    return TypeAdapter(list[Professor]).validate_python(_read("professors.json"))


@cache
def terms() -> list[Term]:
    return TypeAdapter(list[Term]).validate_python(_read("terms.json"))


@cache
def stub_schedules() -> list[StubSchedule]:
    return TypeAdapter(list[StubSchedule]).validate_python(_read("stub_schedules.json"))


def section_by_id() -> dict[str, Section]:
    return {s.id: s for s in sections()}


def professor_by_id() -> dict[str, Professor]:
    return {p.id: p for p in professors()}
