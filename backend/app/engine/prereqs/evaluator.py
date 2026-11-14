"""Check a `PrereqExpression` against a student's course record (ENG-04).

Results:
- `met`: every required course is on the record (an in-progress course counts and
  is labeled "pending grade").
- `met_with_warnings`: nothing is missing that the app can verify, but some part
  can only be checked by the student: a condition (test score, PathwayConnect,
  standing, consent), text that could not be parsed, a co-requisite that is not
  on the record yet, or a grade the record does not show. The section is still
  offered, with "Check this before registering" items.
- `not_met`: a required course is missing, or its grade is below the minimum. The
  candidate builder leaves the section out with "prerequisite: needs <...>".

Unparsed text is never treated as "no prerequisites": it is always a warning.
Equivalent courses count as the course they replace, both from the catalog
(`Course.equivalents`) and from the audit (`AuditCourse.equivalent_of`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from app.contracts import (
    AuditCourse,
    Course,
    CourseRecordStatus,
    PrereqAll,
    PrereqAny,
    PrereqCondition,
    PrereqCourse,
    PrereqExpression,
    PrereqUnparsed,
    ScheduleWarning,
)
from app.engine.prereqs.parser import parse_or_unparsed

CHECK = "Check this before registering"

# Highest first. Grades not on this scale (P, CR, T, ...) cannot be compared.
GRADE_SCALE = ["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-"]
FAILING = {"F", "W", "WF", "UW", "I", "NC", "E"}


class PrereqStatus(StrEnum):
    met = "met"
    met_with_warnings = "met_with_warnings"
    not_met = "not_met"


NoteKind = Literal["check", "pending_grade", "unparsed"]


@dataclass(frozen=True)
class PrereqNote:
    kind: NoteKind
    message: str
    course_code: str | None = None


@dataclass(frozen=True)
class PrereqResult:
    status: PrereqStatus
    notes: tuple[PrereqNote, ...] = ()
    missing: tuple[str, ...] = ()  # e.g. "MATH 112", "one of CSE 110, CS 101"

    @property
    def reason(self) -> str:
        """The `Excluded.detail` for a `not_met` result."""
        return "prerequisite: needs " + " and ".join(self.missing)

    def warnings(self, course_code: str, section_id: str | None = None) -> list[ScheduleWarning]:
        return [
            ScheduleWarning(
                kind="unparsed_prereq" if n.kind == "unparsed" else "prerequisite_check",
                message=n.message,
                course_code=course_code,
                section_id=section_id,
            )
            for n in self.notes
        ]


_MET = PrereqResult(PrereqStatus.met)
_RANK = {PrereqStatus.met: 0, PrereqStatus.met_with_warnings: 1, PrereqStatus.not_met: 2}


def _unique(notes: Iterable[PrereqNote]) -> tuple[PrereqNote, ...]:
    return tuple(dict.fromkeys(notes))


def _grade_text(code: str, grade: str | None) -> str:
    return f"{code} with {grade} or better" if grade else code


# --- Student record ------------------------------------------------------------------


def equivalence_groups(courses: Iterable[Course]) -> dict[str, frozenset[str]]:
    """Course code -> every code the catalog treats as the same course (itself included)."""
    links: dict[str, set[str]] = {}
    for c in courses:
        for eq in c.equivalents:
            links.setdefault(c.code, set()).add(eq)
            links.setdefault(eq, set()).add(c.code)
    groups: dict[str, frozenset[str]] = {}
    for start in links:
        if start in groups:
            continue
        seen, todo = {start}, [start]
        while todo:
            for nxt in links.get(todo.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        group = frozenset(seen)
        for code in group:
            groups[code] = group
    return groups


@dataclass
class StudentRecord:
    """The courses on a student's record, indexed by every code they count as."""

    courses: list[AuditCourse]
    equivalents: Mapping[str, frozenset[str]] = field(default_factory=dict)
    _by_code: dict[str, list[AuditCourse]] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        for c in self.courses:
            codes = {c.course_code}
            if c.equivalent_of:
                codes.add(c.equivalent_of)
            for code in list(codes):
                codes |= self.equivalents.get(code, frozenset())
            for code in codes:
                self._by_code.setdefault(code, []).append(c)

    def find(self, code: str) -> list[AuditCourse]:
        return self._by_code.get(code, [])


# --- Evaluation ----------------------------------------------------------------------


def _course(node: PrereqCourse, record: StudentRecord) -> PrereqResult:
    best: PrereqResult | None = None
    for taken in record.find(node.course_code):
        result = _taken(node, taken)
        if result is None:
            continue
        if best is None or _RANK[result.status] < _RANK[best.status]:
            best = result
    if best is not None:
        return best
    if node.concurrent_ok:
        return PrereqResult(
            PrereqStatus.met_with_warnings,
            (
                PrereqNote(
                    "check",
                    f"{CHECK}: take {node.course_code} before or at the same time",
                    node.course_code,
                ),
            ),
        )
    return PrereqResult(
        PrereqStatus.not_met, missing=(_grade_text(node.course_code, node.min_grade),)
    )


def _taken(node: PrereqCourse, taken: AuditCourse) -> PrereqResult | None:
    """How one record entry meets one course node. None: it does not count at all."""
    code, need = node.course_code, node.min_grade
    if taken.status == CourseRecordStatus.in_progress:
        via = f" (as {taken.course_code})" if taken.course_code != code else ""
        label = f"Prerequisite {code}{via} is in progress: pending grade"
        if need:
            label += f" (needs {need} or better)"
        return PrereqResult(PrereqStatus.met, (PrereqNote("pending_grade", label, code),))
    grade = (taken.grade or "").strip().upper() or None
    if grade in FAILING:
        return None
    if need is None:
        return _MET
    if grade in GRADE_SCALE and need.upper() in GRADE_SCALE:
        if GRADE_SCALE.index(grade) <= GRADE_SCALE.index(need.upper()):
            return _MET
        return PrereqResult(PrereqStatus.not_met, missing=(_grade_text(code, need),))
    shown = f"grade {grade}" if grade else "no grade"
    return PrereqResult(
        PrereqStatus.met_with_warnings,
        (
            PrereqNote(
                "check",
                f"{CHECK}: {code} needs {need} or better; your record shows {shown}",
                code,
            ),
        ),
    )


def _all(results: list[PrereqResult]) -> PrereqResult:
    notes = _unique(n for r in results for n in r.notes)
    missing = tuple(dict.fromkeys(m for r in results for m in r.missing))
    worst = max((r.status for r in results), key=_RANK.__getitem__, default=PrereqStatus.met)
    return PrereqResult(worst, notes, missing)


def _describe(expr: PrereqExpression) -> str:
    """One option of an "any" group, in full: what the student would need for it."""
    if isinstance(expr, PrereqCourse):
        return _grade_text(expr.course_code, expr.min_grade)
    if isinstance(expr, PrereqCondition | PrereqUnparsed):
        return expr.text
    parts = [_describe(i) for i in expr.items]
    parts = [f"({p})" if " and " in p or " one of " in f" {p}" else p for p in parts]
    return " and ".join(parts) if isinstance(expr, PrereqAll) else "one of " + ", ".join(parts)


def _any(results: list[PrereqResult], node: PrereqAny) -> PrereqResult:
    met = [r for r in results if r.status == PrereqStatus.met]
    if met:
        return min(met, key=lambda r: len(r.notes))  # a clean match beats "pending grade"
    warned = [r for r in results if r.status == PrereqStatus.met_with_warnings]
    if warned:
        return PrereqResult(
            PrereqStatus.met_with_warnings, _unique(n for r in warned for n in r.notes)
        )
    if not results:
        return _unparsed("an empty list of options")
    return PrereqResult(PrereqStatus.not_met, missing=(_describe(node),))


def _unparsed(text: str) -> PrereqResult:
    return _warn_unparsed(f"{CHECK}: prerequisites we could not read: {text}")


def _warn_unparsed(message: str) -> PrereqResult:
    return PrereqResult(PrereqStatus.met_with_warnings, (PrereqNote("unparsed", message),))


def evaluate(expr: PrereqExpression, record: StudentRecord) -> PrereqResult:
    if isinstance(expr, PrereqCourse):
        return _course(expr, record)
    if isinstance(expr, PrereqCondition):
        return PrereqResult(
            PrereqStatus.met_with_warnings, (PrereqNote("check", f"{CHECK}: {expr.text}"),)
        )
    if isinstance(expr, PrereqUnparsed):
        return _unparsed(expr.text)
    if isinstance(expr, PrereqAll):
        return _all([evaluate(i, record) for i in expr.items])
    if isinstance(expr, PrereqAny):
        return _any([evaluate(i, record) for i in expr.items], expr)
    raise TypeError(f"unknown prerequisite node {expr!r}")


# --- Per-course checker used by the candidate builder and the chat tool ----------------

TextParser = Callable[[str | None], PrereqExpression]


class PrereqChecker:
    """Checks courses for one student. Each course is parsed and evaluated once.

    A course with no tree yet is parsed from its `prereq_text` with `parse`
    (the code parser by default; the API passes the one with the Haiku fallback).
    A course missing from the catalog gets a warning, never "no prerequisites".
    """

    def __init__(
        self,
        courses: Iterable[Course],
        record: Iterable[AuditCourse],
        parse: TextParser = parse_or_unparsed,
    ) -> None:
        catalog = list(courses)
        self.courses = {c.code: c for c in catalog}
        self.record = StudentRecord(list(record), equivalence_groups(catalog))
        self._parse = parse
        self._results: dict[str, PrereqResult] = {}

    def expression(self, course_code: str) -> PrereqExpression | None:
        course = self.courses.get(course_code)
        if course is None:
            return None
        return course.prereq if course.prereq is not None else self._parse(course.prereq_text)

    def check(self, course_code: str) -> PrereqResult:
        if course_code not in self._results:
            expr = self.expression(course_code)
            self._results[course_code] = (
                _warn_unparsed(
                    f"{CHECK}: {course_code} is not in our catalog, so its prerequisites "
                    "are unknown"
                )
                if expr is None
                else evaluate(expr, self.record)
            )
        return self._results[course_code]
