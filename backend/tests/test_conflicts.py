from datetime import date, time

import pytest

from app.contracts import Day, Meeting
from app.engine.conflicts import conflicts

FULL = (date(2027, 1, 6), date(2027, 4, 8))
FIRST = (date(2027, 1, 6), date(2027, 2, 23))
SECOND = (date(2027, 2, 24), date(2027, 4, 8))


def mt(
    days: str,
    start: tuple[int, int],
    end: tuple[int, int],
    dates: tuple[date, date] = FULL,
) -> Meeting:
    return Meeting(
        days=[Day(d) for d in days],
        start_time=time(*start),
        end_time=time(*end),
        start_date=dates[0],
        end_date=dates[1],
    )


def tba(dates: tuple[date, date] = FULL) -> Meeting:
    return Meeting(start_date=dates[0], end_date=dates[1], tba=True)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        pytest.param(mt("MWF", (9, 0), (10, 0)), mt("MWF", (9, 0), (10, 0)), True, id="same"),
        pytest.param(mt("MWF", (9, 0), (10, 0)), mt("W", (9, 30), (10, 30)), True, id="overlap"),
        pytest.param(mt("MWF", (9, 0), (10, 0)), mt("TR", (9, 0), (10, 0)), False, id="no-day"),
        pytest.param(
            mt("MWF", (9, 0), (10, 15)), mt("MWF", (10, 15), (11, 15)), False, id="back-to-back"
        ),
        pytest.param(
            mt("TR", (12, 45), (13, 45), FIRST),
            mt("TR", (12, 45), (13, 45), SECOND),
            False,
            id="first-vs-second-block",
        ),
        pytest.param(
            mt("TR", (12, 45), (13, 45), FULL),
            mt("TR", (12, 45), (13, 45), FIRST),
            True,
            id="full-vs-first-block",
        ),
        pytest.param(
            mt("TR", (12, 45), (13, 45), FULL),
            mt("TR", (12, 45), (13, 45), SECOND),
            True,
            id="full-vs-second-block",
        ),
        pytest.param(tba(), mt("MWF", (9, 0), (10, 0)), False, id="tba-never-conflicts"),
        pytest.param(tba(), tba(), False, id="tba-vs-tba"),
    ],
)
def test_conflicts(a: Meeting, b: Meeting, expected: bool) -> None:
    assert conflicts(a, b) is expected
    assert conflicts(b, a) is expected
