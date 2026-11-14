"""ENG-03: over 200 random constraint sets, no schedule has a time conflict, two
sections of one course, an excluded section or credits above the maximum."""

from __future__ import annotations

import random
from datetime import time
from itertools import combinations

import pytest

from app.api import fixture_data
from app.contracts import ConstraintSet, Day, DeliveryMethod, SeatStatus
from app.engine.conflicts import sections_conflict
from app.engine.solver import build_schedules

N_CASES = 200
SEED = 20270106


def _random_constraints(rng: random.Random, codes: list[str], ids: list[str]) -> ConstraintSet:
    lo = rng.choice([0, 3, 6, 9, 12])
    hi = lo + rng.choice([0, 2, 3, 4, 6])
    return ConstraintSet(
        credit_min=lo,
        credit_max=hi,
        earliest_start=rng.choice([None, time(9, 0), time(10, 0), time(11, 30)]),
        latest_end=rng.choice([None, time(14, 0), time(16, 30)]),
        days_off=rng.sample(list(Day), k=rng.choice([0, 0, 1, 2])),
        include_courses=rng.sample(codes, k=rng.choice([0, 0, 1, 2])),
        exclude_courses=rng.sample(codes, k=rng.choice([0, 1, 3])),
        exclude_section_ids=rng.sample(ids, k=rng.choice([0, 2, 5])),
        delivery_methods=rng.choice([[], [], [DeliveryMethod.campus], [DeliveryMethod.online]]),
        only_required=rng.random() < 0.5,
        allow_waitlist=rng.random() < 0.3,
    )


def _cases() -> list[ConstraintSet]:
    rng = random.Random(SEED)
    sections = fixture_data.sections()
    codes = sorted({s.course_code for s in sections})
    ids = [s.id for s in sections]
    return [_random_constraints(rng, codes, ids) for _ in range(N_CASES)]


@pytest.mark.parametrize("constraints", _cases())
def test_random_constraints_never_break_hard_rules(constraints: ConstraintSet) -> None:
    res = build_schedules(
        fixture_data.audit(),
        fixture_data.sections(),
        constraints,
        max_results=2,
        credit_range=(12, 15),
        time_limit_s=1.0,
    )
    excluded_ids = {e.section_id for e in res.excluded}
    cmax = constraints.credit_max
    for s in res.schedules:
        secs = [c.section for c in s.classes]
        assert s.classes
        assert len({x.course_code for x in secs}) == len(secs), "two sections of one course"
        for a, b in combinations(secs, 2):
            assert not sections_conflict(a, b), f"{a.id} conflicts with {b.id}"
        for x in secs:
            assert x.id not in excluded_ids
            assert x.id not in constraints.exclude_section_ids
            assert x.course_code not in constraints.exclude_courses
            if not constraints.allow_waitlist:
                assert x.seats.status == SeatStatus.open
        assert cmax is None or s.total_credits <= cmax
