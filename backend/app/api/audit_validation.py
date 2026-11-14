"""Checks on a parsed or edited degree audit (AI-04).

Pure functions: no database, no network, no Claude. The confirm screen highlights
every flag and lets the student edit the value. Flags are always recomputed by the
server; flags sent by the client are ignored.

Flag kinds:

- `unknown_course`: a course option of an unmet requirement that is not in this
  semester's course list. The catalog (DATA-04) is the Course Search scrape, so it
  holds only the courses offered in the scraped term: a missing code may be a typo
  or a course not offered this term, and the message says both. Courses already on
  the student's record (and transfer equivalents) are not checked: they were taken
  in earlier terms and need not be offered now. Codes in subjects the catalog does
  not hold (general education, before those subjects are scraped) are not checked
  either: we cannot tell a typo from a subject we have no data for.

The audit's `catalog_year` is the student's catalog (for example `2024-2025`). The
catalog year DATA-04 stores is the scraped term's (`2026-2027`). They are different
things and are never compared.
- `credit_mismatch`: credit numbers that do not add up.
- `invalid_status`: a status that contradicts the rest of the line.
- `stale_audit`: the audit is older than `AUDIT_MAX_AGE_DAYS`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.contracts import (
    CourseRecordStatus,
    DegreeAudit,
    RequirementStatus,
    ValidationFlag,
)

EPS = 0.01


def _subject(code: str) -> str:
    return code.split(" ", 1)[0]


def _flag(field: str, kind: str, message: str) -> ValidationFlag:
    return ValidationFlag(field=field, kind=kind, message=message)


def _fmt(n: float) -> str:
    return f"{n:g}"


def _unknown_courses(audit: DegreeAudit, known: set[str]) -> Iterable[ValidationFlag]:
    subjects = {_subject(c) for c in known}
    for i, req in enumerate(audit.requirements):
        if req.status == RequirementStatus.complete:
            continue
        for j, code in enumerate(req.options):
            if _subject(code) in subjects and code not in known:
                yield _flag(
                    f"requirements[{i}].options[{j}]",
                    "unknown_course",
                    f"{code} isn't in this semester's course list. It may not be offered "
                    "this term, or the code may be wrong.",
                )


def _credit_mismatches(audit: DegreeAudit) -> Iterable[ValidationFlag]:
    credits_by_code = {c.course_code: c.credits for c in audit.courses}
    earned = sum(
        c.credits
        for c in audit.courses
        if c.status in (CourseRecordStatus.complete, CourseRecordStatus.transfer)
    )
    if audit.total_credits_earned + EPS < earned:
        yield _flag(
            "total_credits_earned",
            "credit_mismatch",
            f"The audit says {_fmt(audit.total_credits_earned)} credits earned, but the "
            f"completed and transfer courses add up to {_fmt(earned)}.",
        )
    for i, req in enumerate(audit.requirements):
        field = f"requirements[{i}].credits_needed"
        if req.credits_needed > req.credits_required + EPS:
            yield _flag(
                field,
                "credit_mismatch",
                f"{req.name} needs {_fmt(req.credits_needed)} credits, more than the "
                f"{_fmt(req.credits_required)} it requires.",
            )
            continue
        counted = [credits_by_code[c] for c in req.courses_counted if c in credits_by_code]
        if req.credits_required > 0 and len(counted) == len(req.courses_counted) and counted:
            expected = max(0.0, req.credits_required - sum(counted))
            if abs(expected - req.credits_needed) > EPS:
                yield _flag(
                    field,
                    "credit_mismatch",
                    f"{req.name} requires {_fmt(req.credits_required)} credits and counts "
                    f"{_fmt(sum(counted))}, so {_fmt(expected)} should be needed, not "
                    f"{_fmt(req.credits_needed)}.",
                )


def _invalid_statuses(audit: DegreeAudit) -> Iterable[ValidationFlag]:
    status_by_code = {c.course_code: c.status for c in audit.courses}
    for i, course in enumerate(audit.courses):
        if course.status == CourseRecordStatus.in_progress and course.grade:
            yield _flag(
                f"courses[{i}].status",
                "invalid_status",
                f"{course.course_code} is in progress but has the grade {course.grade}.",
            )
        elif course.status == CourseRecordStatus.complete and not course.grade:
            yield _flag(
                f"courses[{i}].status",
                "invalid_status",
                f"{course.course_code} is marked complete but has no grade.",
            )
    for i, req in enumerate(audit.requirements):
        field = f"requirements[{i}].status"
        counted = [status_by_code.get(c) for c in req.courses_counted]
        if req.status == RequirementStatus.complete and req.credits_needed > EPS:
            yield _flag(
                field,
                "invalid_status",
                f"{req.name} is marked complete but still needs "
                f"{_fmt(req.credits_needed)} credits.",
            )
        elif req.status == RequirementStatus.complete and CourseRecordStatus.in_progress in counted:
            yield _flag(
                field,
                "invalid_status",
                f"{req.name} is marked complete but counts a course that is still in progress.",
            )
        elif (
            req.status == RequirementStatus.not_met
            and req.credits_required > 0
            and req.credits_needed <= EPS
        ):
            yield _flag(
                field,
                "invalid_status",
                f"{req.name} is marked not met but needs no more credits.",
            )
        elif req.status == RequirementStatus.in_progress and req.courses_counted and (
            CourseRecordStatus.in_progress not in counted
        ):
            yield _flag(
                field,
                "invalid_status",
                f"{req.name} is marked in progress but none of its courses is in progress.",
            )


def is_stale(audit_date: date, today: date, max_age_days: int) -> bool:
    return (today - audit_date).days > max_age_days


def validate(
    audit: DegreeAudit, known_courses: set[str], today: date, max_age_days: int
) -> list[ValidationFlag]:
    flags = [
        *_unknown_courses(audit, known_courses),
        *_credit_mismatches(audit),
        *_invalid_statuses(audit),
    ]
    if is_stale(audit.audit_date, today, max_age_days):
        flags.append(
            _flag(
                "audit_date",
                "stale_audit",
                f"This audit is from {audit.audit_date.isoformat()}, more than {max_age_days} "
                "days ago. Download a fresh one so it shows your latest grades.",
            )
        )
    return flags


def with_flags(
    audit: DegreeAudit, known_courses: set[str], today: date, max_age_days: int
) -> DegreeAudit:
    """The audit with its flags recomputed (any flags it came with are dropped)."""
    clean = audit.model_copy(update={"validation_flags": []})
    return clean.model_copy(
        update={"validation_flags": validate(clean, known_courses, today, max_age_days)}
    )
