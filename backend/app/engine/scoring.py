"""Schedule score (ENG-05). Weights come from the school config, never from code.

The score adds, each times its weight:
- requirements filled: unmet audit requirements the schedule fills,
- credits,
- preferences met: entries in the structured `why.preferences_met`,
- favorite professors: classes taught by a favorite professor,
- open seats: per class, the share of seats still open (0 for a waitlisted class),
- unlocks: per class, how many *other* remaining requirements list a course that
  needs this class as a prerequisite,
minus gaps: idle hours between classes in a day.

Gaps are counted per weekday and per half of the semester (First Block weeks and
Second Block weeks; a full-semester class is in both), then averaged over the two
halves. A First Block class and a Second Block class at the same time never count
as overlapping or as a gap.

The solver uses the same terms as its objective (gaps as day spans, which give the
same idle time once classes do not overlap). The reported score is computed here
from the final picks, so it is exact.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import time

from app.contracts import (
    BlockKind,
    Day,
    DegreeAudit,
    PrereqExpression,
    RequirementStatus,
    SeatStatus,
    Section,
)
from app.contracts.catalog import PrereqAll, PrereqAny, PrereqCourse

HALVES = (1, 2)
# Halves of the semester a block's weeks fall in.
PERIODS: Mapping[BlockKind, tuple[int, ...]] = {
    BlockKind.full: (1, 2),
    BlockKind.first: (1,),
    BlockKind.second: (2,),
}


@dataclass(frozen=True)
class Weights:
    """Points per unit for each score term. Defaults match ENG-03 behavior."""

    requirement: float = 100
    credit: float = 1
    preference: float = 0
    favorite_professor: float = 0
    open_seats: float = 0
    unlocks: float = 0
    gap_per_hour: float = 0

    @classmethod
    def from_mapping(cls, values: Mapping[str, float]) -> Weights:
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"unknown score weights: {', '.join(unknown)}")
        return cls(**{k: float(v) for k, v in values.items()})


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def day_slots(section: Section) -> list[tuple[Day, int, int, int]]:
    """(day, period, start minute, end minute) for every timed meeting."""
    out: list[tuple[Day, int, int, int]] = []
    for m in section.meetings:
        if m.tba or m.start_time is None or m.end_time is None:
            continue
        for d in m.days:
            for p in PERIODS[section.block]:
                out.append((d, p, _minutes(m.start_time), _minutes(m.end_time)))
    return out


def idle_minutes(sections: Iterable[Section]) -> float:
    """Idle minutes per week between classes, averaged over the two semester halves
    (a gap between two full-semester classes counts once, a First Block gap half)."""
    by_slot: dict[tuple[Day, int], list[tuple[int, int]]] = defaultdict(list)
    for s in sections:
        for d, p, start, end in day_slots(s):
            by_slot[(d, p)].append((start, end))
    total = 0
    for spans in by_slot.values():
        spans.sort()
        last_end = spans[0][1]
        for start, end in spans[1:]:
            total += max(0, start - last_end)
            last_end = max(last_end, end)
    return total / len(HALVES)


def open_share(section: Section) -> float:
    if section.seats.status != SeatStatus.open or section.seats.total <= 0:
        return 0.0
    return min(1.0, section.seats.open / section.seats.total)


def _required_courses(expr: PrereqExpression | None) -> set[str]:
    """Every course named in a prerequisite tree (in ALL or ANY groups)."""
    if expr is None:
        return set()
    if isinstance(expr, PrereqCourse):
        return {expr.course_code}
    if isinstance(expr, PrereqAll | PrereqAny):
        return set().union(*(_required_courses(i) for i in expr.items))
    return set()


def unlock_counts(
    audit: DegreeAudit, expression: Callable[[str], PrereqExpression | None]
) -> dict[str, int]:
    """Course code -> how many other remaining requirements it is a prerequisite for."""
    counts: dict[str, int] = defaultdict(int)
    for r in audit.requirements:
        if r.status != RequirementStatus.not_met:
            continue
        needed: set[str] = set()
        for option in r.options:
            needed |= _required_courses(expression(option))
        for code in needed - set(r.options):
            counts[code] += 1
    return dict(counts)


@dataclass(frozen=True)
class ScoreInputs:
    """Facts about the student that the score needs, shared by every schedule."""

    weights: Weights
    favorite_professor_ids: frozenset[str] = frozenset()
    unlocks: Mapping[str, int] | None = None

    def is_favorite_class(self, section: Section) -> bool:
        return any(p in self.favorite_professor_ids for p in section.instructor_ids)

    def unlock_count(self, course_code: str) -> int:
        return (self.unlocks or {}).get(course_code, 0)


def score_schedule(
    sections: Sequence[Section],
    requirements_filled: int,
    preferences_met: int,
    inputs: ScoreInputs,
) -> float:
    w = inputs.weights
    total = (
        w.requirement * requirements_filled
        + w.credit * sum(s.credits for s in sections)
        + w.preference * preferences_met
        + w.favorite_professor * sum(inputs.is_favorite_class(s) for s in sections)
        + w.open_seats * sum(open_share(s) for s in sections)
        + w.unlocks * sum(inputs.unlock_count(s.course_code) for s in sections)
        - w.gap_per_hour * idle_minutes(sections) / 60
    )
    return round(total, 4)
