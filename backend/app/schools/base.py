"""School-agnostic interfaces.

`engine/`, `llm/` and `api/` depend only on these. Everything specific to
BYU-Idaho implements them in `schools/byui/` and is wired in at startup through
`register_school`. `tests/test_layering.py` enforces the boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from app.contracts import (
    ConstraintSet,
    Course,
    DegreeAudit,
    DeliveryMethod,
    Excluded,
    Professor,
    ProfessorSource,
    Section,
    Student,
    Term,
)


@dataclass
class ImportSummary:
    """Printed at the end of every importer run."""

    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    notes: list[str] = field(default_factory=list)


class CatalogImporter(ABC):
    """Loads courses (with raw prerequisite text) into our own database."""

    @abstractmethod
    def catalog_year(self) -> str: ...

    @abstractmethod
    def courses(self) -> Iterable[Course]:
        """Every course in the source, codes already normalized."""


class ScheduleImporter(ABC):
    """Turns public class-schedule pages into sections for one term."""

    @abstractmethod
    def term(self) -> Term: ...

    @abstractmethod
    def sections(self, term_code: str) -> Iterable[Section]:
        """Sections for a term code (full semester or one block)."""


class DirectoryImporter(ABC):
    """Reads official public faculty profile pages."""

    @abstractmethod
    def profile_sources(self, professor: Professor) -> list[ProfessorSource]:
        """Sources for one professor. Empty list when no safe match exists."""


class DegreeAuditParser(ABC):
    """Turns a degree-audit PDF into a `DegreeAudit` with no name or ID number.

    The PDF bytes are never written to disk or the database.
    """

    @abstractmethod
    def parse(self, pdf: bytes) -> DegreeAudit: ...


class SchoolRules(ABC):
    """School policy. Values come from the school's config file, not from code."""

    @abstractmethod
    def default_credit_range(self) -> tuple[float, float]: ...

    @abstractmethod
    def allowed_delivery(self, student: Student, term: Term) -> set[DeliveryMethod]:
        """Delivery methods the student may take this term (track rule)."""

    @abstractmethod
    def exclusion(
        self, section: Section, student: Student, constraints: ConstraintSet
    ) -> Excluded | None:
        """Why a section is left out by a school rule, or None if it is allowed."""

    @abstractmethod
    def is_religion_course(self, course_code: str) -> bool: ...

    @abstractmethod
    def max_religion_courses_at_registration(self) -> int: ...

    @abstractmethod
    def max_waitlisted_credits(self) -> float: ...

    @abstractmethod
    def relaxation_order(self) -> list[str]:
        """Constraint names to loosen, in order, when nothing fits."""

    @abstractmethod
    def audit_max_age_days(self) -> int: ...

    def audit_is_stale(self, audit_date: date, today: date) -> bool:
        return (today - audit_date).days > self.audit_max_age_days()


@dataclass
class School:
    """Everything one school plugs into the app."""

    university_id: str
    name: str
    rules: SchoolRules | None = None
    catalog: CatalogImporter | None = None
    schedule: ScheduleImporter | None = None
    directory: DirectoryImporter | None = None
    audit_parser: DegreeAuditParser | None = None


_SCHOOLS: dict[str, School] = {}


def register_school(school: School) -> None:
    _SCHOOLS[school.university_id] = school


def get_school(university_id: str) -> School:
    try:
        return _SCHOOLS[university_id]
    except KeyError:
        raise LookupError(f"No school registered with id {university_id!r}") from None
