"""Candidate sections for the solver (ENG-03).

Starts from the audit's unmet requirements and every offered section, drops
courses the student has done or is taking, then applies the student's hard
constraints. Every section dropped by a constraint carries an `Excluded` reason.

School rules (track, religion, waitlist credit cap) are ENG-05 and prerequisites
are ENG-04; both plug in here later.
"""

from __future__ import annotations

from collections.abc import Iterable
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
    SeatStatus,
    Section,
)


@dataclass(frozen=True)
class Candidate:
    section: Section
    requirement_ids: tuple[str, ...]  # unmet AuditRequirement ids this class fills
    waitlisted: bool = False


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
    s: Section, constraints: ConstraintSet, requirement_ids: tuple[str, ...]
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
    return None


def build_candidates(
    audit: DegreeAudit, sections: Iterable[Section], constraints: ConstraintSet
) -> CandidatePool:
    fills: dict[str, list[str]] = {}
    for r in remaining_requirements(audit):
        for code in r.options:
            fills.setdefault(code, []).append(r.id)
    done = taken_courses(audit)

    pool = CandidatePool()
    for s in sections:
        if s.course_code in done:
            continue  # already on the record: not a choice, not an exclusion
        req_ids = tuple(fills.get(s.course_code, ()))
        excluded = _constraint_exclusion(s, constraints, req_ids)
        if excluded is not None:
            pool.excluded.append(excluded)
            continue
        pool.candidates.append(
            Candidate(
                section=s, requirement_ids=req_ids, waitlisted=s.seats.status != SeatStatus.open
            )
        )
    return pool
