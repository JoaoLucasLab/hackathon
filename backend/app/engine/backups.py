"""Backup sections (ENG-05).

For each chosen class, up to 2 other sections of the same course that fit the rest
of that schedule: no time conflict with any other chosen class, and, for a
waitlisted backup, the waitlisted-credit cap still holds. Backups come from the
candidate pool, so they already passed every rule and constraint.

Open sections come first, then the most open seats, then the section id.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.contracts import Section
from app.engine.candidates import Candidate
from app.engine.conflicts import sections_conflict

MAX_BACKUPS = 2


def backup_sections(
    picks: Sequence[Candidate],
    candidates: Sequence[Candidate],
    max_waitlisted_credits: float | None = None,
    limit: int = MAX_BACKUPS,
) -> dict[str, list[Section]]:
    """Chosen section id -> its backups, best first."""
    chosen_ids = {p.section.id for p in picks}
    out: dict[str, list[Section]] = {}
    for pick in picks:
        others = [p for p in picks if p.section.id != pick.section.id]
        waitlisted_others = sum(p.section.credits for p in others if p.waitlisted)
        fits: list[Candidate] = []
        for alt in candidates:
            s = alt.section
            if s.course_code != pick.section.course_code or s.id in chosen_ids:
                continue
            if any(sections_conflict(s, o.section) for o in others):
                continue
            if (
                alt.waitlisted
                and max_waitlisted_credits is not None
                and waitlisted_others + s.credits > max_waitlisted_credits
            ):
                continue
            fits.append(alt)
        fits.sort(key=lambda c: (c.waitlisted, -c.section.seats.open, c.section.id))
        out[pick.section.id] = [c.section for c in fits[:limit]]
    return out
