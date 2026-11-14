"""Scheduler core (ENG-03): Google OR-Tools CP-SAT.

One boolean per candidate section. Hard constraints: at most one section per
course, no time conflict, total credits inside the range, included courses taken
when offered, at least one class. The objective rewards filled requirements
first and credits second. ENG-05 adds full scoring, school rules, relaxation and
backups on top of this.

Results come back one at a time: after each solve, a constraint forces the next
schedule to differ by at least one course or by the sections of two courses.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model

from app import config
from app.contracts import (
    BuildSchedulesResponse,
    ConstraintSet,
    DegreeAudit,
    Schedule,
    ScheduledClass,
    Section,
)
from app.engine.candidates import Candidate, CandidatePool, build_candidates
from app.engine.conflicts import sections_conflict
from app.engine.explain import explain, section_warnings
from app.engine.prereqs.evaluator import PrereqChecker

CREDIT_SCALE = 10  # credits are floats like 2.5; CP-SAT wants integers


@dataclass(frozen=True)
class Weights:
    """Objective weights. ENG-05 reads these from the school config."""

    requirement: int = 100  # per unmet requirement filled
    credit: int = 1  # per credit


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


def solve(
    pool: CandidatePool,
    audit: DegreeAudit,
    constraints: ConstraintSet,
    *,
    credit_range: tuple[float, float],
    max_results: int,
    time_limit_s: float,
    weights: Weights = Weights(),
) -> list[Solution]:
    cands = pool.candidates
    if not cands:
        return []
    lo, hi = credit_range
    if constraints.credit_min is not None:
        lo = constraints.credit_min
    if constraints.credit_max is not None:
        hi = constraints.credit_max
    if lo > hi:
        return []

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

    m.maximize(weights.requirement * CREDIT_SCALE * sum(filled) + weights.credit * credits)

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
                score=solver.objective_value / CREDIT_SCALE,
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


def build_schedules(
    audit: DegreeAudit,
    sections: Iterable[Section],
    constraints: ConstraintSet,
    *,
    max_results: int = 3,
    credit_range: tuple[float, float] | None = None,
    time_limit_s: float | None = None,
    favorite_professor_ids: Iterable[str] = (),
    weights: Weights = Weights(),
    prereqs: PrereqChecker | None = None,
) -> BuildSchedulesResponse:
    """Candidates, solve, explain. Same function behind the endpoint and the chat tool."""
    pool = build_candidates(audit, sections, constraints, prereqs)
    favorites = set(favorite_professor_ids)
    solutions = solve(
        pool,
        audit,
        constraints,
        credit_range=credit_range or (config.CREDIT_DEFAULT_MIN, config.CREDIT_DEFAULT_MAX),
        max_results=max_results,
        time_limit_s=config.SOLVER_TIME_LIMIT_S if time_limit_s is None else time_limit_s,
        weights=weights,
    )
    ordered = sorted(solutions, key=lambda s: -s.score)  # stable: ties keep solve order
    schedules: list[Schedule] = []
    for rank, sol in enumerate(ordered, start=1):
        picks = sorted(sol.picks, key=lambda c: c.section.id)
        secs = [c.section for c in picks]
        classes = [
            ScheduledClass(
                section=c.section,
                requirement_ids=list(c.requirement_ids),
                waitlisted=c.waitlisted,
                warnings=[*section_warnings(c.section), *c.warnings],
            )
            for c in picks
        ]
        schedules.append(
            Schedule(
                id=_schedule_id(secs),
                rank=rank,
                score=sol.score,
                total_credits=sum(s.credits for s in secs),
                optimal=sol.optimal,
                classes=classes,
                why=explain(secs, constraints, favorites),
                warnings=[w for c in classes for w in c.warnings],
            )
        )
    return BuildSchedulesResponse(schedules=schedules, excluded=pool.excluded)
