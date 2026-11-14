"""Pure parsers for BYU-Idaho Course Search strings (ENG-02).

No database and no network. The schedule importer (DATA-03) calls these and has no
parser of its own.

Formats handled:

- Meeting line: ``TR 12:45-01:45PM (01/06/2027 - 04/08/2027) STC 231``
- Time range where only the end has AM/PM: ``12:45-01:45PM``. The marker belongs to
  the end time; the start is the latest reading (AM or PM) that is before the end.
- Time range with both markers: ``11:30AM-12:30PM``.
- ``TBA`` meetings: a ``Meeting`` with ``tba=True`` and no days or times.
- No set time (online): ``00:00-00:00`` or an empty line gives no meeting.
- Course codes: ``CSE111``, ``CSE 111``, ``CSE 111-01``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time

from app.contracts import Day, Meeting


class ParseError(ValueError):
    """A string from Course Search that we could not read."""


# --- Course codes -------------------------------------------------------------------

_COURSE_CODE_RE = re.compile(
    r"^\s*(?P<subject>[A-Za-z]{2,5})\s*(?P<number>\d{3}[A-Za-z]?)"
    r"(?:\s*-\s*(?P<section>[A-Za-z0-9]{1,4}))?\s*$"
)


@dataclass(frozen=True)
class CourseRef:
    course_code: str  # "CSE 111"
    section: str | None = None  # "01"


def normalize_course_code(text: str) -> CourseRef:
    """``CSE111``, ``CSE 111`` and ``CSE 111-01`` -> ``CSE 111`` (section ``01`` for the last)."""
    m = _COURSE_CODE_RE.match(text)
    if not m:
        raise ParseError(f"not a course code: {text!r}")
    code = f"{m['subject'].upper()} {m['number'].upper()}"
    section = m["section"].upper() if m["section"] else None
    return CourseRef(code, section)


# --- Days -------------------------------------------------------------------------

_DAY_LETTERS = {d.value: d for d in Day}


def parse_days(text: str) -> list[Day]:
    """``MWF`` -> [M, W, F]. ``T`` is Tuesday, ``R`` Thursday, ``S`` Saturday."""
    days: list[Day] = []
    for ch in text.strip().upper():
        if ch not in _DAY_LETTERS:
            raise ParseError(f"unknown day letter {ch!r} in {text!r}")
        day = _DAY_LETTERS[ch]
        if day not in days:
            days.append(day)
    return days


# --- Times ------------------------------------------------------------------------

_CLOCK = r"(\d{1,2}):(\d{2})\s*(AM|PM)?"
_TIME_RANGE_RE = re.compile(rf"^\s*{_CLOCK}\s*-\s*{_CLOCK}\s*$", re.I)


def _to_24h(hour: int, minute: int, marker: str) -> time:
    if not (1 <= hour <= 12 and 0 <= minute < 60):
        raise ParseError(f"bad clock time {hour}:{minute:02d}{marker}")
    hour = hour % 12 + (12 if marker == "PM" else 0)
    return time(hour, minute)


def parse_time_range(text: str) -> tuple[time, time]:
    """``12:45-01:45PM`` -> (12:45, 13:45). ``MWF 11:30-12:30PM`` style -> (11:30, 12:30)."""
    m = _TIME_RANGE_RE.match(text)
    if not m:
        raise ParseError(f"not a time range: {text!r}")
    sh, sm, smark, eh, em, emark = m.groups()
    if not emark:
        raise ParseError(f"time range has no AM/PM on the end time: {text!r}")
    end = _to_24h(int(eh), int(em), emark.upper())
    if smark:
        start = _to_24h(int(sh), int(sm), smark.upper())
    else:
        # The marker belongs to the end time. Pick the latest reading of the start
        # that is still before the end.
        readings = [_to_24h(int(sh), int(sm), mk) for mk in ("AM", "PM")]
        before = [t for t in readings if t < end]
        if not before:
            raise ParseError(f"start is not before end in {text!r}")
        start = max(before)
    if start >= end:
        raise ParseError(f"start is not before end in {text!r}")
    return start, end


# --- Meeting lines ----------------------------------------------------------------

_DATE = r"\d{1,2}/\d{1,2}/\d{4}"
_MEETING_RE = re.compile(
    r"^\s*"
    r"(?:(?P<tba>TBA)\b|(?:(?P<days>[A-Z]+)\s+)?(?P<times>\d{1,2}:\d{2}\s*(?:AM|PM)?"
    r"\s*-\s*\d{1,2}:\d{2}\s*(?:AM|PM)?))?"
    rf"\s*(?:\(\s*(?P<start_date>{_DATE})\s*-\s*(?P<end_date>{_DATE})\s*\))?"
    r"\s*(?P<room>.*?)\s*$",
    re.I,
)
_NO_TIME_RE = re.compile(r"^\s*0?0:00\s*(?:AM|PM)?\s*-\s*0?0:00\s*(?:AM|PM)?\s*$", re.I)


def _parse_date(text: str) -> date:
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError as exc:
        raise ParseError(f"bad date {text!r}") from exc


def parse_meeting(
    line: str,
    *,
    default_dates: tuple[date, date] | None = None,
) -> Meeting | None:
    """Parse one meeting line.

    Returns ``None`` for a line with no set time (empty or ``00:00-00:00``), which is
    how online sections appear. ``default_dates`` (usually the block's dates) is used
    when the line has no ``(start - end)`` part.
    """
    if not line.strip():
        return None
    m = _MEETING_RE.match(line)
    if not m or not (m["tba"] or m["times"] or m["start_date"]):
        raise ParseError(f"not a meeting line: {line!r}")

    if m["start_date"]:
        start_date, end_date = _parse_date(m["start_date"]), _parse_date(m["end_date"])
    elif default_dates:
        start_date, end_date = default_dates
    else:
        raise ParseError(f"meeting line has no dates and no default dates: {line!r}")
    if start_date > end_date:
        raise ParseError(f"start date is after end date in {line!r}")

    room = m["room"] or None
    if room and room.upper() == "TBA":
        room = None

    if m["tba"]:
        return Meeting(start_date=start_date, end_date=end_date, room=room, tba=True)

    times = m["times"]
    if times is None or _NO_TIME_RE.match(times):
        if m["days"]:
            raise ParseError(f"meeting has days but no time: {line!r}")
        return None  # dates only, no set time: online

    start_time, end_time = parse_time_range(times)
    days = parse_days(m["days"] or "")
    if not days:
        raise ParseError(f"meeting has a time but no days: {line!r}")
    return Meeting(
        days=days,
        start_time=start_time,
        end_time=end_time,
        start_date=start_date,
        end_date=end_date,
        room=room,
    )


def parse_meetings(
    text: str | Iterable[str],
    *,
    default_dates: tuple[date, date] | None = None,
) -> list[Meeting]:
    """Parse every meeting line. A string is split on newlines.

    An online section with no set time gives an empty list.
    """
    lines = text.splitlines() if isinstance(text, str) else list(text)
    meetings = []
    for line in lines:
        meeting = parse_meeting(line, default_dates=default_dates)
        if meeting is not None:
            meetings.append(meeting)
    return meetings
