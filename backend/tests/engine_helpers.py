"""Small builders for hand-made sections and audits in engine tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from app.contracts import (
    AuditRequirement,
    BlockKind,
    Day,
    DegreeAudit,
    DeliveryMethod,
    Meeting,
    RequirementStatus,
    SeatInfo,
    SeatStatus,
    Section,
)

FULL = (date(2027, 1, 6), date(2027, 4, 8))
FIRST = (date(2027, 1, 6), date(2027, 2, 20))
SECOND = (date(2027, 2, 23), date(2027, 4, 8))
_BLOCK_DATES = {BlockKind.full: FULL, BlockKind.first: FIRST, BlockKind.second: SECOND}
_TERM = {BlockKind.full: "2027;WI", BlockKind.first: "2027;WI;W1", BlockKind.second: "2027;WI;W2"}
AS_OF = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def section(
    code: str,
    num: str = "01",
    when: str | None = "MWF 10:15-11:15",
    *,
    credits: float = 3,
    block: BlockKind = BlockKind.full,
    online: bool = False,
    status: SeatStatus = SeatStatus.open,
    instructor: str = "p-test",
) -> Section:
    """`when` is `"<days> HH:MM-HH:MM"` in 24-hour time, or None for no set time."""
    start_date, end_date = _BLOCK_DATES[block]
    meetings: list[Meeting] = []
    if when is not None:
        days, span = when.split()
        start, end = span.split("-")
        meetings.append(
            Meeting(
                days=[Day(d) for d in days],
                start_time=_t(start),
                end_time=_t(end),
                start_date=start_date,
                end_date=end_date,
                room="STC 101",
            )
        )
    return Section(
        id=f"{_TERM[block]}|{code}-{num}",
        course_code=code,
        section=num,
        title=code,
        credits=credits,
        term_code=_TERM[block],
        block=block,
        delivery_method=DeliveryMethod.online if online else DeliveryMethod.campus,
        department=code.split()[0],
        instructor_ids=[instructor],
        meetings=meetings,
        seats=SeatInfo(status=status, open=0 if status != "open" else 10, total=30, as_of=AS_OF),
        source_url="https://example.test/section",
        fetched_at=AS_OF,
    )


def requirement(rid: str, *options: str, needed: float = 3) -> AuditRequirement:
    return AuditRequirement(
        id=rid,
        group="Test",
        name=rid,
        status=RequirementStatus.not_met,
        credits_required=needed,
        credits_needed=needed,
        options=list(options),
    )


def audit(*requirements: AuditRequirement) -> DegreeAudit:
    return DegreeAudit(
        audit_date=date(2026, 11, 1),
        catalog_year="2024-2025",
        major="Test",
        track="fall_winter",
        total_credits_required=120,
        total_credits_earned=30,
        requirements=list(requirements),
    )
