"""ENG-01: fixtures pass schema validation, meet the counts in plan.md, and
point only at things that exist."""

from __future__ import annotations

import re
from collections import Counter

from app.api import fixture_data
from app.contracts import BlockKind, DeliveryMethod, RequirementStatus, SeatStatus

TERM_BLOCKS = {
    "2027;WI": BlockKind.full,
    "2027;WI;W1": BlockKind.first,
    "2027;WI;W2": BlockKind.second,
}
NON_COURSE = re.compile(r"standing|score|PathwayConnect|consent", re.IGNORECASE)


def test_one_parsed_audit_for_demo_persona() -> None:
    audit = fixture_data.audit()
    assert audit.track is not None
    assert any(r.status == RequirementStatus.not_met for r in audit.requirements)
    assert any(c.status == "in_progress" for c in audit.courses)


def test_fifty_winter_sections() -> None:
    sections = fixture_data.sections()
    assert len(sections) == 50
    assert len({s.id for s in sections}) == 50
    assert {s.block for s in sections} == set(BlockKind)
    per_course = Counter(s.course_code for s in sections)
    assert sum(1 for n in per_course.values() if n >= 2) >= 8
    assert sum(1 for s in sections if s.seats.status == SeatStatus.closed) >= 1
    assert sum(1 for s in sections if s.delivery_method == DeliveryMethod.online) >= 3


def test_sections_are_consistent_with_terms() -> None:
    blocks = {b.term_code: b for t in fixture_data.terms() for b in t.blocks}
    for s in fixture_data.sections():
        assert TERM_BLOCKS[s.term_code] == s.block, s.id
        block = blocks[s.term_code]
        for m in s.meetings:
            assert block.start_date <= m.start_date <= m.end_date <= block.end_date, s.id
        if s.delivery_method == DeliveryMethod.online:
            assert all(m.start_time is None for m in s.meetings), s.id


def test_twenty_courses_with_prereq_text() -> None:
    with_text = [c for c in fixture_data.courses() if c.prereq_text]
    assert len(with_text) >= 20
    assert sum(1 for c in with_text if " or " in (c.prereq_text or "").lower()) >= 3
    assert sum(1 for c in with_text if NON_COURSE.search(c.prereq_text or "")) >= 2


def test_ten_professors_with_topic_tags() -> None:
    profs = fixture_data.professors()
    assert len(profs) == 10
    assert all(3 <= len(p.topic_tags) <= 8 for p in profs)
    assert all(p.sources for p in profs)


def test_same_name_different_department_stays_two_professors() -> None:
    smiths = [
        p for p in fixture_data.professors() if (p.first_name, p.last_name) == ("John", "Smith")
    ]
    assert len(smiths) == 2
    assert len({p.department for p in smiths}) == 2


def test_cross_references_exist() -> None:
    codes = {c.code for c in fixture_data.courses()}
    profs = fixture_data.professor_by_id()
    for s in fixture_data.sections():
        assert s.course_code in codes, s.id
        assert all(i in profs for i in s.instructor_ids), s.id
    audit = fixture_data.audit()
    for c in audit.courses:
        assert c.course_code in codes, c.course_code
    for r in audit.requirements:
        assert set(r.options) <= codes, r.id
    for p in profs.values():
        assert set(p.winter_courses) <= codes, p.id


def test_stub_schedules_reference_real_sections_within_default_credits() -> None:
    sections = fixture_data.section_by_id()
    for stub in fixture_data.stub_schedules():
        chosen = [sections[sid] for sid in stub.section_ids]
        assert 12 <= sum(s.credits for s in chosen) <= 15, stub.id
        assert len({s.course_code for s in chosen}) == len(chosen), stub.id


def test_no_real_urls_or_personal_fields() -> None:
    for s in fixture_data.sections():
        assert ".invalid/" in s.source_url
    for p in fixture_data.professors():
        assert all(".invalid/" in src.source_url for src in p.sources)
