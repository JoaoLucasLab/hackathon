"""Scheduler (ENG-03 core, ENG-05 rules and scoring): Google OR-Tools CP-SAT.

One boolean per candidate section. Hard constraints: at most one section per
course, no time conflict, total credits inside the range, included courses taken
when offered, at least one class. With school rules: at most N religion courses
and at most M waitlisted credits.

The objective is the score in `engine/scoring.py`: requirements filled, credits,
favorite professors, open seats, prerequisite unlocks, minus idle time between
classes. The reported score is recomputed exactly from the final picks, and the
schedules are ranked by it.

Results come back one at a time: after each solve, a constraint forces the next
schedule to differ by at least one course or by the sections of two courses.

When nothing fits, `engine/relax.py` loosens one constraint at a time in the
school's order and reports the first that gives schedules. Each chosen class
gets up to 2 backup sections from `engine/backups.py`.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model

from app import config
from app.contracts import (
    BuildSchedulesResponse,
    ConstraintSet,
    DegreeAudit,
    Schedule,
    ScheduledClass,
    ScheduleWarning,
    ScheduleWhy,
    Section,
    Student,
)
from app.engine.backups import backup_sections
from app.engine.candidates import Candidate, CandidatePool, build_candidates
from app.engine.conflicts import sections_conflict
from app.engine.explain import explain, section_warnings
from app.engine.prereqs.evaluator import PrereqChecker
from app.engine.relax import find_relaxation
from app.engine.scoring import (
    HALVES,
    ScoreInputs,
    Weights,
    day_slots,
    open_share,
    score_schedule,
    unlock_counts,
)
from app.schools.base import SchoolRules

CREDIT_SCALE = 10  # credits are floats like 2.5; CP-SAT wants integers
OBJ_SCALE = 100  # objective points -> integer coefficients
DEFAULT_CREDIT_RANGE = (12.0, 15.0)  # only when no school rules are given
RELAX_TIME_LIMIT_S = 1.0  # cap per relaxation solve, so trying options stays fast
DEFAULT_WEIGHTS = Weights()

__all__ = ["Limits", "Solution", "Weights", "build_schedules", "schedules_differ", "solve"]


@dataclass(frozen=True)
class Limits:
    """Per-schedule school limits. None means no limit."""

    max_religion: int | None = None
    is_religion: Callable[[str], bool] = lambda _code: False
    max_waitlisted_credits: float | None = None

    @classmethod
    def from_rules(cls, rules: SchoolRules) -> Limits:
        return cls(
            max_religion=rules.max_religion_courses_at_registration(),
            is_religion=rules.is_religion_course,
            max_waitlisted_credits=rules.max_waitlisted_credits(),
        )


@dataclass(frozen=True)
class Solution:
    picks: tuple[Candidate, ...]
    score: float
    optimal: bool


def _sum(terms: Iterable[cp_model.LinearExprT]) -> cp_model.LinearExpr:
    return cp_model.LinearExpr.sum(list(terms))


def _scaled(credits: float) -> int:
    return round(credits * CREDIT_SCALE)


def _requirement_slots(pool: CandidatePool, audit: DegreeAudit) -> dict[str, int]:
    """How many courses each requirement can usefully take (only_required)."""
    max_credits: dict[str, float] = defaultdict(float)
    for c in pool.candidates:
        for rid in c.requirement_ids:
            max_credits[rid] = max(max_credits[rid], c.section.credits)
    needed = {r.id: r.credits_needed for r in audit.requirements}
    return {
        rid: max(1, math.ceil(needed.get(rid, 0) / mc)) if mc > 0 else 1
        for rid, mc in max_credits.items()
    }


def effective_credit_range(
    constraints: ConstraintSet, default: tuple[float, float]
) -> tuple[float, float]:
    """The student's own bounds win; a default bound gives way to them.

    "At most 9 credits" with a school default of 12 to 15 means 9 at most (and
    at least as many as fit under 9), not an impossible 12 to 9.
    """
    lo, hi = default
    if constraints.credit_min is not None:
        lo = constraints.credit_min
        if constraints.credit_max is None:
            hi = max(hi, lo)
    if constraints.credit_max is not None:
        hi = constraints.credit_max
        if constraints.credit_min is None:
            lo = min(lo, hi)
    return lo, hi


def _add_gap_terms(
    m: cp_model.CpModel, x: list[cp_model.IntVar], cands: Sequence[Candidate]
) -> list[cp_model.IntVar]:
    """Span (first start to last end) per weekday and semester half. With no
    overlaps, span minus class minutes is the idle time, and class minutes are
    fixed by the picks, so minimizing spans minimizes gaps."""
    members: dict[tuple[object, int], list[tuple[int, int, int]]] = defaultdict(list)
    for i, c in enumerate(cands):
        for d, p, start, end in day_slots(c.section):
            members[(d, p)].append((i, start, end))
    spans: list[cp_model.IntVar] = []
    for key, items in members.items():
        if len({i for i, _, _ in items}) < 2:
            continue  # one possible class that day: never a gap
        first = m.new_int_var(0, 24 * 60, f"first_{key}")
        last = m.new_int_var(0, 24 * 60, f"last_{key}")
        used = m.new_bool_var(f"used_{key}")
        for i, start, end in items:
            m.add(first <= start).only_enforce_if(x[i])
            m.add(last >= end).only_enforce_if(x[i])
            m.add_implication(x[i], used)
        m.add(last >= first)
        m.add(last == first).only_enforce_if(used.Not())
        span = m.new_int_var(0, 24 * 60, f"span_{key}")
        m.add(span == last - first)
        spans.append(span)
    return spans


def solve(
    pool: CandidatePool,
    audit: DegreeAudit,
    constraints: ConstraintSet,
    *,
    credit_range: tuple[float, float],
    max_results: int,
    time_limit_s: float,
    weights: Weights = DEFAULT_WEIGHTS,
    inputs: ScoreInputs | None = None,
    limits: Limits = Limits(),
) -> list[Solution]:
    cands = pool.candidates
    if not cands:
        return []
    lo, hi = effective_credit_range(constraints, credit_range)
    if lo > hi:
        return []
    inputs = inputs or ScoreInputs(weights=weights)

    m = cp_model.CpModel()
    x = [m.new_bool_var(f"x{i}") for i in range(len(cands))]

    by_course: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(cands):
        by_course[c.section.course_code].append(i)
    y: dict[str, cp_model.LinearExpr] = {
        code: _sum(x[i] for i in idx) for code, idx in by_course.items()
    }
    for idx in by_course.values():
        m.add_at_most_one(x[i] for i in idx)

    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            a, b = cands[i].section, cands[j].section
            if a.course_code != b.course_code and sections_conflict(a, b):
                m.add_bool_or([x[i].Not(), x[j].Not()])

    credits = sum(_scaled(c.section.credits) * x[i] for i, c in enumerate(cands))
    m.add(credits >= _scaled(lo))
    m.add(credits <= _scaled(hi))
    m.add(sum(x) >= 1)

    for code in constraints.include_courses:
        if code in y:
            m.add(y[code] >= 1)

    if limits.max_religion is not None:
        religion = [x[i] for i, c in enumerate(cands) if limits.is_religion(c.section.course_code)]
        if religion:
            m.add(sum(religion) <= limits.max_religion)
    if limits.max_waitlisted_credits is not None:
        waitlisted = [(i, c) for i, c in enumerate(cands) if c.waitlisted]
        if waitlisted:
            m.add(
                sum(_scaled(c.section.credits) * x[i] for i, c in waitlisted)
                <= _scaled(limits.max_waitlisted_credits)
            )

    by_req: dict[str, set[str]] = defaultdict(set)
    for c in cands:
        for rid in c.requirement_ids:
            by_req[rid].add(c.section.course_code)
    filled = []
    for rid, codes in by_req.items():
        f = m.new_bool_var(f"f_{rid}")
        m.add(f <= sum(y[code] for code in codes))
        filled.append(f)
    if constraints.only_required:
        slots = _requirement_slots(pool, audit)
        for rid, codes in by_req.items():
            m.add(sum(y[code] for code in codes) <= slots[rid])

    w = inputs.weights
    per_class = [
        round(
            OBJ_SCALE
            * (
                w.credit * c.section.credits
                + w.favorite_professor * inputs.is_favorite_class(c.section)
                + w.open_seats * open_share(c.section)
                + w.unlocks * inputs.unlock_count(c.section.course_code)
            )
        )
        for c in cands
    ]
    objective = round(OBJ_SCALE * w.requirement) * sum(filled) + sum(
        k * x[i] for i, k in enumerate(per_class)
    )
    if w.gap_per_hour > 0:
        # Spans are per semester half; the score averages the two halves.
        per_minute = round(OBJ_SCALE * w.gap_per_hour / 60 / len(HALVES))
        objective -= per_minute * sum(_add_gap_terms(m, x, cands))
    m.maximize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = 8
    solver.parameters.random_seed = 0

    solutions: list[Solution] = []
    while len(solutions) < max_results:
        status = solver.solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        chosen = [i for i in range(len(cands)) if solver.boolean_value(x[i])]
        solutions.append(
            Solution(
                picks=tuple(cands[i] for i in chosen),
                score=solver.objective_value / OBJ_SCALE,
                optimal=status == cp_model.OPTIMAL,
            )
        )
        _forbid_similar(m, x, y, cands, chosen)
    return solutions


def _forbid_similar(
    m: cp_model.CpModel,
    x: list[cp_model.IntVar],
    y: dict[str, cp_model.LinearExpr],
    cands: Sequence[Candidate],
    chosen: list[int],
) -> None:
    """Next schedule differs by >= 1 course, or keeps the courses and changes >= 2 sections."""
    picked = set(chosen)
    courses = {cands[i].section.course_code for i in chosen}
    course_diff = (
        len(courses) - _sum(y[c] for c in courses) + _sum(y[c] for c in y if c not in courses)
    )
    section_diff = (
        len(picked)
        - _sum(x[i] for i in picked)
        + _sum(x[i] for i in range(len(x)) if i not in picked)
    )
    new_course = m.new_bool_var("")
    m.add(course_diff >= 1).only_enforce_if(new_course)
    # Same courses: each changed section counts twice (one out, one in).
    m.add(section_diff >= 4).only_enforce_if(new_course.Not())


def schedules_differ(a: Schedule, b: Schedule) -> bool:
    """True if the course sets differ, or the same courses use 2+ different sections."""
    sa = {c.section.course_code: c.section.id for c in a.classes}
    sb = {c.section.course_code: c.section.id for c in b.classes}
    if sa.keys() != sb.keys():
        return True
    return sum(sa[k] != sb[k] for k in sa) >= 2


def _schedule_id(sections: Iterable[Section]) -> str:
    key = "|".join(sorted(s.id for s in sections))
    return "sch-" + hashlib.sha256(key.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class _Run:
    """Everything one build needs besides the constraints, so relaxation can rerun it."""

    audit: DegreeAudit
    sections: tuple[Section, ...]
    credit_range: tuple[float, float]
    favorites: frozenset[str]
    inputs: ScoreInputs
    limits: Limits
    prereqs: PrereqChecker | None
    rules: SchoolRules | None
    student: Student | None

    def pool(self, constraints: ConstraintSet) -> CandidatePool:
        return build_candidates(
            self.audit,
            self.sections,
            constraints,
            self.prereqs,
            rules=self.rules,
            student=self.student,
            favorite_professor_ids=self.favorites,
        )

    def solve(
        self, pool: CandidatePool, constraints: ConstraintSet, max_results: int, time_limit_s: float
    ) -> list[Solution]:
        return solve(
            pool,
            self.audit,
            constraints,
            credit_range=self.credit_range,
            max_results=max_results,
            time_limit_s=time_limit_s,
            weights=self.inputs.weights,
            inputs=self.inputs,
            limits=self.limits,
        )


def _religion_warning(
    rules: SchoolRules | None, sections: Sequence[Section]
) -> list[ScheduleWarning]:
    if rules is None:
        return []
    religion = [s for s in sections if rules.is_religion_course(s.course_code)]
    if not religion:
        return []
    return [
        ScheduleWarning(
            kind="religion_limit",
            message=rules.religion_note(),
            course_code=religion[0].course_code,
            section_id=religion[0].id,
        )
    ]


def build_schedules(
    audit: DegreeAudit,
    sections: Iterable[Section],
    constraints: ConstraintSet,
    *,
    max_results: int = 3,
    credit_range: tuple[float, float] | None = None,
    time_limit_s: float | None = None,
    favorite_professor_ids: Iterable[str] = (),
    weights: Weights | None = None,
    prereqs: PrereqChecker | None = None,
    rules: SchoolRules | None = None,
    student: Student | None = None,
) -> BuildSchedulesResponse:
    """Candidates, solve, score, backups, explain; relaxation when nothing fits.

    Same function behind the endpoint and the chat tool. With `rules`, the credit
    range, weights and limits come from the school config unless passed here.
    """
    favorites = frozenset(favorite_professor_ids)
    if weights is None:
        weights = Weights.from_mapping(rules.scoring_weights()) if rules else Weights()
    if credit_range is None:
        credit_range = rules.default_credit_range() if rules else DEFAULT_CREDIT_RANGE
    limit_s = config.SOLVER_TIME_LIMIT_S if time_limit_s is None else time_limit_s
    unlocks = None
    if prereqs is not None and weights.unlocks:
        unlocks = unlock_counts(audit, prereqs.expression)
    run = _Run(
        audit=audit,
        sections=tuple(sections),
        credit_range=credit_range,
        favorites=favorites,
        inputs=ScoreInputs(weights=weights, favorite_professor_ids=favorites, unlocks=unlocks),
        limits=Limits.from_rules(rules) if rules else Limits(),
        prereqs=prereqs,
        rules=rules,
        student=student,
    )

    pool = run.pool(constraints)
    solutions = run.solve(pool, constraints, max_results, limit_s)

    scored: list[tuple[float, int, Solution, ScheduleWhy]] = []
    for order, sol in enumerate(solutions):
        secs = [c.section for c in sol.picks]
        why = explain(secs, constraints, favorites)
        filled = len({rid for c in sol.picks for rid in c.requirement_ids})
        score = score_schedule(secs, filled, len(why.preferences_met), run.inputs)
        scored.append((score, order, sol, why))
    scored.sort(key=lambda t: (-t[0], t[1]))  # ties keep solve order

    schedules: list[Schedule] = []
    for rank, (score, _, sol, why) in enumerate(scored, start=1):
        picks = sorted(sol.picks, key=lambda c: c.section.id)
        secs = [c.section for c in picks]
        backups = backup_sections(picks, pool.candidates, run.limits.max_waitlisted_credits)
        classes = [
            ScheduledClass(
                section=c.section,
                requirement_ids=list(c.requirement_ids),
                waitlisted=c.waitlisted,
                backups=backups.get(c.section.id, []),
                warnings=[*section_warnings(c.section), *c.warnings],
            )
            for c in picks
        ]
        schedules.append(
            Schedule(
                id=_schedule_id(secs),
                rank=rank,
                score=score,
                total_credits=sum(s.credits for s in secs),
                optimal=sol.optimal,
                classes=classes,
                why=why,
                warnings=[
                    *(w for c in classes for w in c.warnings),
                    *_religion_warning(rules, secs),
                ],
            )
        )

    relaxation = None
    if not schedules and rules is not None:
        relax_s = min(limit_s, RELAX_TIME_LIMIT_S)

        def count(patch: ConstraintSet) -> int:
            return len(run.solve(run.pool(patch), patch, max_results, relax_s))

        relaxation = find_relaxation(
            constraints,
            rules.relaxation_order(),
            count,
            sections=run.sections,
            credit_range=effective_credit_range(constraints, credit_range),
            max_credit_limit=rules.max_credit_limit(),
        )
    return BuildSchedulesResponse(
        schedules=schedules, excluded=pool.excluded, relaxation=relaxation
    )
