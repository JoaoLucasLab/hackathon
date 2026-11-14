from datetime import date, time

import pytest

from app.contracts import Day
from app.schools.byui.parsing import (
    ParseError,
    parse_days,
    parse_meeting,
    parse_meetings,
    parse_time_range,
)

WINTER = (date(2027, 1, 6), date(2027, 4, 8))


def test_full_meeting_line() -> None:
    m = parse_meeting("TR 12:45-01:45PM (01/06/2027 - 04/08/2027) STC 231")
    assert m is not None
    assert m.days == [Day.T, Day.R]
    assert (m.start_time, m.end_time) == (time(12, 45), time(13, 45))
    assert (m.start_date, m.end_date) == (date(2027, 1, 6), date(2027, 4, 8))
    assert m.room == "STC 231"
    assert m.tba is False


@pytest.mark.parametrize(
    ("raw", "start", "end"),
    [
        ("11:30-12:30PM", time(11, 30), time(12, 30)),  # marker belongs to the end
        ("12:45-01:45PM", time(12, 45), time(13, 45)),
        ("12:45-02:15PM", time(12, 45), time(14, 15)),
        ("09:00-10:00AM", time(9, 0), time(10, 0)),
        ("07:45-08:45AM", time(7, 45), time(8, 45)),
        ("04:30-06:00PM", time(16, 30), time(18, 0)),
        ("11:30AM-12:30PM", time(11, 30), time(12, 30)),  # both markers present
        ("10:15-11:15AM", time(10, 15), time(11, 15)),
    ],
)
def test_time_range(raw: str, start: time, end: time) -> None:
    assert parse_time_range(raw) == (start, end)


def test_mwf_with_default_dates() -> None:
    m = parse_meeting("MWF 11:30-12:30PM", default_dates=WINTER)
    assert m is not None
    assert m.days == [Day.M, Day.W, Day.F]
    assert (m.start_time, m.end_time) == (time(11, 30), time(12, 30))
    assert (m.start_date, m.end_date) == WINTER


@pytest.mark.parametrize(
    ("letters", "expected"),
    [
        ("R", [Day.R]),  # Thursday
        ("T", [Day.T]),  # Tuesday
        ("S", [Day.S]),  # Saturday
        ("MTWRF", [Day.M, Day.T, Day.W, Day.R, Day.F]),
    ],
)
def test_day_letters(letters: str, expected: list[Day]) -> None:
    assert parse_days(letters) == expected


def test_two_meeting_lines_give_two_meetings() -> None:
    text = (
        "MW 09:00-10:00AM (01/06/2027 - 04/08/2027) STC 231\n"
        "F 02:00-04:00PM (01/06/2027 - 04/08/2027) STC 290"
    )
    meetings = parse_meetings(text)
    assert len(meetings) == 2
    assert meetings[1].days == [Day.F]
    assert (meetings[1].start_time, meetings[1].end_time) == (time(14, 0), time(16, 0))
    assert meetings[1].room == "STC 290"


@pytest.mark.parametrize(
    "text",
    ["", "00:00-00:00AM (01/06/2027 - 04/08/2027)", "(01/06/2027 - 04/08/2027)"],
)
def test_online_with_no_time_gives_empty_list(text: str) -> None:
    assert parse_meetings(text, default_dates=WINTER) == []


@pytest.mark.parametrize(
    "line", ["TBA", "TBA (01/06/2027 - 04/08/2027) TBA", "TBA (01/06/2027 - 02/23/2027)"]
)
def test_tba_meeting(line: str) -> None:
    m = parse_meeting(line, default_dates=WINTER)
    assert m is not None
    assert m.tba is True
    assert m.days == []
    assert m.start_time is None and m.end_time is None
    assert m.room is None


@pytest.mark.parametrize(
    "line",
    [
        "TR 12:45-01:45PM",  # no dates and no defaults
        "XZ 12:45-01:45PM (01/06/2027 - 04/08/2027)",  # unknown day letters
        "TR 12:45-01:45 (01/06/2027 - 04/08/2027)",  # no AM/PM at all
        "hello world",
    ],
)
def test_bad_lines_raise(line: str) -> None:
    with pytest.raises(ParseError):
        parse_meeting(line)
