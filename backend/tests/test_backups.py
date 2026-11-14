"""ENG-05: each chosen class has up to 2 backup sections that fit the rest of
that schedule with no conflict."""

from __future__ import annotations

from tests.engine_helpers import audit, requirement, section

from app.api.schedules import build_schedules as build_api
from app.contracts import BuildSchedulesRequest, ConstraintSet, SeatStatus
from app.engine.backups import backup_sections
from app.engine.candidates import Candidate
from app.engine.conflicts import sections_conflict
from app.engine.solver import build_schedules
from app.schools.byui.rules import ByuiRules

RULES = ByuiRules()


def test_backups_fit_the_rest_of_the_schedule() -> None:
    a = audit(requirement("ra", "AAA 101"), requirement("rb", "BBB 101"))
    secs = [
        section("AAA 101", "01", "MWF 09:00-10:00"),
        section("AAA 101", "02", "MWF 11:00-12:00"),  # fits
        section("AAA 101", "03", "TR 10:00-11:00"),  # clashes with BBB 101-01
        section("AAA 101", "04", "MWF 13:00-14:00"),  # fits
        section("AAA 101", "05", "MWF 15:00-16:00"),  # fits, but only 2 backups
        section("BBB 101", "01", "TR 10:00-11:00"),
    ]
    res = build_schedules(
        a,
        secs,
        ConstraintSet(),
        max_results=1,
        credit_range=(6, 6),
        rules=RULES,
    )
    s = res.schedules[0]
    by_code = {c.section.course_code: c for c in s.classes}
    aaa = by_code["AAA 101"]
    assert len(aaa.backups) == 2
    assert all(b.course_code == "AAA 101" for b in aaa.backups)
    assert all(b.id != aaa.section.id for b in aaa.backups)
    assert "2027;WI|AAA 101-03" not in {b.id for b in aaa.backups}
    assert by_code["BBB 101"].backups == []  # its only section is the chosen one


def test_open_backups_come_before_waitlisted() -> None:
    picks = [Candidate(section("AAA 101", "01", "MWF 09:00-10:00"), ("ra",))]
    pool = [
        *picks,
        Candidate(
            section("AAA 101", "02", "MWF 11:00-12:00", status=SeatStatus.closed),
            ("ra",),
            waitlisted=True,
        ),
        Candidate(section("AAA 101", "03", "MWF 13:00-14:00"), ("ra",)),
    ]
    out = backup_sections(picks, pool, 12)
    assert [s.id for s in out[picks[0].section.id]] == [
        "2027;WI|AAA 101-03",
        "2027;WI|AAA 101-02",
    ]


def test_waitlisted_backup_respects_the_credit_cap() -> None:
    others = [
        Candidate(section(f"W{c}A 101", "01", None, credits=4), (), waitlisted=True) for c in "ABC"
    ]  # 12 waitlisted credits already
    pick = Candidate(section("AAA 101", "01", "MWF 09:00-10:00"), ("ra",))
    waitlisted_alt = Candidate(
        section("AAA 101", "02", "MWF 11:00-12:00", status=SeatStatus.closed),
        ("ra",),
        waitlisted=True,
    )
    out = backup_sections([pick, *others], [pick, *others, waitlisted_alt], 12)
    assert out[pick.section.id] == []


def test_fixture_backups_never_conflict() -> None:
    res = build_api(BuildSchedulesRequest(max_results=5))
    assert res.schedules
    assert any(c.backups for s in res.schedules for c in s.classes)
    for s in res.schedules:
        for cls in s.classes:
            assert len(cls.backups) <= 2
            others = [c.section for c in s.classes if c is not cls]
            for b in cls.backups:
                assert b.course_code == cls.section.course_code
                assert not any(sections_conflict(b, o) for o in others)
