"""Relaxation (ENG-05): when nothing fits, name the one constraint to loosen.

Constraints are tried in the school's fixed order (`relaxation_order` in the
school config). For each, the smallest change comes first (for example the
latest earlier start time before an earlier one). The first change that gives at
least one schedule is returned with the number of schedules it gives and the full
`ConstraintSet` to apply with one click.

Exclusions the student typed (`exclude_courses`, `exclude_section_ids`) are never
loosened. `change` is a short fixed template filled with values; Claude rewords it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import time
from typing import Any

from app.contracts import ConstraintSet, Relaxation, Section

# Options tried per constraint at most, so an impossible request stays fast.
MAX_OPTIONS = 6

Option = tuple[str, ConstraintSet]


def _fmt(t: time) -> str:
    return t.strftime("%H:%M")


def _credits(value: float) -> str:
    return f"{value:g}"


def _patch(c: ConstraintSet, **changes: Any) -> ConstraintSet:
    return ConstraintSet.model_validate({**c.model_dump(), **changes})


def _starts(sections: Iterable[Section]) -> set[time]:
    return {m.start_time for s in sections for m in s.meetings if m.start_time and not m.tba}


def _ends(sections: Iterable[Section]) -> set[time]:
    return {m.end_time for s in sections for m in s.meetings if m.end_time and not m.tba}


def _options(
    name: str,
    c: ConstraintSet,
    sections: Sequence[Section],
    credit_range: tuple[float, float],
    max_credit_limit: float,
) -> Iterator[Option]:
    lo, hi = credit_range
    if name == "only_favorite_professors" and c.only_favorite_professors:
        yield "allow professors who are not favorites", _patch(c, only_favorite_professors=False)
    elif name == "earliest_start" and c.earliest_start is not None:
        earliest = c.earliest_start
        for t in sorted((t for t in _starts(sections) if t < earliest), reverse=True):
            yield (
                f"allow classes from {_fmt(t)} instead of {_fmt(earliest)}",
                _patch(c, earliest_start=t),
            )
    elif name == "latest_end" and c.latest_end is not None:
        latest = c.latest_end
        for t in sorted(t for t in _ends(sections) if t > latest):
            yield (
                f"allow classes until {_fmt(t)} instead of {_fmt(latest)}",
                _patch(c, latest_end=t),
            )
    elif name == "days_off":
        for day in c.days_off:
            yield (
                f"allow classes on {day.value}",
                _patch(c, days_off=[d for d in c.days_off if d != day]),
            )
    elif name == "delivery_methods" and c.delivery_methods:
        yield "allow any delivery method", _patch(c, delivery_methods=[])
    elif name == "allow_waitlist" and not c.allow_waitlist:
        yield "allow waitlisted sections", _patch(c, allow_waitlist=True)
    elif name == "only_required" and c.only_required:
        yield "allow classes not required to graduate", _patch(c, only_required=False)
    elif name == "credit_min":
        new = min(lo - 1, hi)
        while new >= 1:
            yield f"lower the minimum to {_credits(new)} credits", _patch(c, credit_min=new)
            new -= 1
    elif name == "credit_max":
        new = max(hi + 1, lo)
        while new <= max_credit_limit:
            yield f"raise the maximum to {_credits(new)} credits", _patch(c, credit_max=new)
            new += 1
    elif name == "include_courses":
        for code in c.include_courses:
            yield (
                f"drop {code} from your must-take courses",
                _patch(c, include_courses=[x for x in c.include_courses if x != code]),
            )


def find_relaxation(
    constraints: ConstraintSet,
    order: Sequence[str],
    count: Callable[[ConstraintSet], int],
    *,
    sections: Sequence[Section],
    credit_range: tuple[float, float],
    max_credit_limit: float,
    max_options: int = MAX_OPTIONS,
) -> Relaxation | None:
    """First single loosening (in `order`) that gives schedules, or None."""
    for name in order:
        options = _options(name, constraints, sections, credit_range, max_credit_limit)
        for n, (change, patch) in enumerate(options):
            if n >= max_options:
                break
            found = count(patch)
            if found > 0:
                return Relaxation(
                    constraint=name, change=change, schedules_available=found, patch=patch
                )
    return None
