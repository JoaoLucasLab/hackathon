"""Candidate sections for the solver (ENG-03).

Starts from the audit's unmet requirements and every offered section, drops
courses the student has done or is taking, then applies the student's hard
constraints. Every section dropped by a constraint carries an `Excluded` reason.

Prerequisites (ENG-04) are checked when a `PrereqChecker` is passed: `not_met`
drops the section with "prerequisite: needs <...>"; `met_with_warnings` keeps it
and carries the "Check this before registering" items.

School rules (ENG-05) come in through `SchoolRules`: the track rule drops sections
with reason `track`. "Only my favorites" drops sections no favorite teaches. A
section that clashes with every section of a must-take course (`include_courses`)
is dropped with reason `conflict`. The religion limit and the waitlist credit cap
are per-schedule limits, so they live in the solver.

Checks run in this order and the first one that fails gives the reason: track,
prerequisite, the student's own constraints (including closed sections), then
conflicts with must-take courses.
"""

from __future__ import annotations

from collections.abc import Iterable, Set
from dataclasses import dataclass, field
from datetime import time

from app.contracts import (
    AuditRequirement,
    ConstraintSet,
    CourseRecordStatus,
    DegreeAudit,
    Excluded,
    ExclusionReason,
    RequirementStatus,
    ScheduleWarning,
    SeatStatus,
    Section,
    Student,
)
from app.engine.conflicts import sections_conflict
from app.engine.prereqs.evaluator import PrereqChecker, PrereqStatus
from app.schools.base import SchoolRules


@dataclass(frozen=True)
class Candidate:
    section: Section
    requirement_ids: tuple[str, ...]  # unmet AuditRequirement ids this class fills
    waitlisted: bool = False
    # Prerequisite items to check before registering. Not part of equality/hash.
    warnings: tuple[ScheduleWarning, ...] = field(default=(), compare=False, hash=False)


@dataclass
class CandidatePool:
    candidates: list[Candidate] = field(default_factory=list)
    excluded: list[Excluded] = field(default_factory=list)


def remaining_requirements(audit: DegreeAudit) -> list[AuditRequirement]:
    return [r for r in audit.requirements if r.status == RequirementStatus.not_met]


def taken_courses(audit: DegreeAudit) -> set[str]:
    """Courses complete, transferred or in progress, including what they stand in for."""
    done: set[str] = set()
    for c in audit.courses:
        if c.status in (
            CourseRecordStatus.complete,
            CourseRecordStatus.in_progress,
            CourseRecordStatus.transfer,
        ):
            done.add(c.course_code)
            if c.equivalent_of:
                done.add(c.equivalent_of)
    return done


def _fmt(t: time) -> str:
    return t.strftime("%H:%M")


def _constraint_exclusion(
    s: Section,
    constraints: ConstraintSet,
    requirement_ids: tuple[str, ...],
    favorite_professor_ids: Set[str] = frozenset(),
) -> Excluded | None:
    def out(reason: ExclusionReason, detail: str) -> Excluded:
        return Excluded(section_id=s.id, reason=reason, detail=detail)

    you = ExclusionReason.excluded_by_you
    if s.id in constraints.exclude_section_ids:
        return out(you, f"you excluded section {s.course_code}-{s.section}")
    if s.course_code in constraints.exclude_courses:
        return out(you, f"you excluded {s.course_code}")
    if constraints.delivery_methods and s.delivery_method not in constraints.delivery_methods:
        return out(you, f"delivery: {s.delivery_method.value}")
    days_off = set(constraints.days_off)
    for m in s.meetings:
        if m.tba:
            continue
        hit = sorted(days_off & set(m.days))
        if hit:
            return out(you, f"meets on {','.join(hit)} (day off)")
        if (
            constraints.earliest_start
            and m.start_time
            and m.start_time < constraints.earliest_start
        ):
            return out(
                you, f"starts at {_fmt(m.start_time)}, before {_fmt(constraints.earliest_start)}"
            )
        if constraints.latest_end and m.end_time and m.end_time > constraints.latest_end:
            return out(you, f"ends at {_fmt(m.end_time)}, after {_fmt(constraints.latest_end)}")
    if s.seats.status != SeatStatus.open and not constraints.allow_waitlist:
        return out(ExclusionReason.closed, f"section is {s.seats.status.value}")
    if (
        constraints.only_required
        and not requirement_ids
        and s.course_code not in constraints.include_courses
    ):
        return out(you, "not required to graduate")
    if constraints.only_favorite_professors and not (
        set(s.instructor_ids) & favorite_professor_ids
    ):
        return out(you, "not taught by a favorite professor")
    return None


def _drop_must_take_conflicts(pool: CandidatePool, constraints: ConstraintSet) -> None:
    """A section that clashes with every remaining section of a must-take course can
    never be picked with it: drop it with reason `conflict`."""
    must = {
        code: [c for c in pool.candidates if c.section.course_code == code]
        for code in dict.fromkeys(constraints.include_courses)
    }
    must = {code: cands for code, cands in must.items() if cands}
    if not must:
        return
    kept: list[Candidate] = []
    for cand in pool.candidates:
        s = cand.section
        clash = next(
            (
                (code, options)
                for code, options in must.items()
                if code != s.course_code and all(sections_conflict(s, o.section) for o in options)
            ),
            None,
        )
        if clash is None:
            kept.append(cand)
            continue
        code, options = clash
        names = ", ".join(f"{o.section.course_code}-{o.section.section}" for o in options)
        pool.excluded.append(
            Excluded(
                section_id=s.id,
                reason=ExclusionReason.conflict,
                detail=f"conflicts with {names} (must-take {code})",
            )
        )
    pool.candidates = kept


def build_candidates(
    audit: DegreeAudit,
    sections: Iterable[Section],
    constraints: ConstraintSet,
    prereqs: PrereqChecker | None = None,
    *,
    rules: SchoolRules | None = None,
    student: Student | None = None,
    favorite_professor_ids: Iterable[str] = (),
) -> CandidatePool:
    fills: dict[str, list[str]] = {}
    for r in remaining_requirements(audit):
        for code in r.options:
            fills.setdefault(code, []).append(r.id)
    done = taken_courses(audit)
    favorites = frozenset(favorite_professor_ids)
    if rules is not None and student is None:
        student = student_from_audit(audit)

    pool = CandidatePool()
    for s in sections:
        if s.course_code in done:
            continue  # already on the record: not a choice, not an exclusion
        if rules is not None and student is not None:
            rule_out = rules.exclusion(s, student, constraints)
            if rule_out is not None:
                pool.excluded.append(rule_out)
                continue
        req_ids = tuple(fills.get(s.course_code, ()))
        warnings: tuple[ScheduleWarning, ...] = ()
        if prereqs is not None:
            result = prereqs.check(s.course_code)
            if result.status == PrereqStatus.not_met:
                pool.excluded.append(
                    Excluded(
                        section_id=s.id, reason=ExclusionReason.prerequisite, detail=result.reason
                    )
                )
                continue
            warnings = tuple(result.warnings(s.course_code, s.id))
        excluded = _constraint_exclusion(s, constraints, req_ids, favorites)
        if excluded is not None:
            pool.excluded.append(excluded)
            continue
        pool.candidates.append(
            Candidate(
                section=s,
                requirement_ids=req_ids,
                waitlisted=s.seats.status != SeatStatus.open,
                warnings=warnings,
            )
        )
    _drop_must_take_conflicts(pool, constraints)
    return pool


def student_from_audit(audit: DegreeAudit) -> Student:
    """The rules only need the track and catalog year; no name or ID is involved."""
    return Student(id="session", track=audit.track, catalog_year=audit.catalog_year)
