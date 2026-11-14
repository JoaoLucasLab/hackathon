"""Block-aware conflict check (ENG-02). Pure functions, no database, no network.

Two meetings conflict only if they share a weekday, their times overlap and their
date ranges overlap. Same time in First Block and Second Block is not a conflict.
Back-to-back classes (one ends at 10:15, the next starts at 10:15) do not conflict.
TBA meetings and meetings with no set time never conflict.
"""

from __future__ import annotations

from app.contracts import Meeting, Section


def conflicts(a: Meeting, b: Meeting) -> bool:
    if a.tba or b.tba:
        return False
    if a.start_time is None or a.end_time is None or b.start_time is None or b.end_time is None:
        return False
    if not set(a.days) & set(b.days):
        return False
    if not (a.start_time < b.end_time and b.start_time < a.end_time):
        return False
    # Date ranges are inclusive on both ends.
    return a.start_date <= b.end_date and b.start_date <= a.end_date


def sections_conflict(a: Section, b: Section) -> bool:
    """True if any meeting of ``a`` conflicts with any meeting of ``b``."""
    return any(conflicts(ma, mb) for ma in a.meetings for mb in b.meetings)
