"""ENG-04: prerequisite trees checked against a student's record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from tests.engine_helpers import audit, requirement, section

from app.contracts import (
    AuditCourse,
    ConstraintSet,
    Course,
    CourseRecordStatus,
    ExclusionReason,
    PrereqExpression,
    PrereqUnparsed,
)
from app.engine.candidates import build_candidates
from app.engine.prereqs.evaluator import (
    PrereqChecker,
    PrereqStatus,
    StudentRecord,
    equivalence_groups,
    evaluate,
)
from app.engine.prereqs.parser import parse_prereq_text
from app.engine.solver import build_schedules

SAMPLE = (
    "CSE 110 or CS 101 (last offered 2023) or CIT 160 or PathwayConnect "
    "or LUC test score of at least 110"
)
CHECK = "Check this before registering"


def took(
    code: str,
    grade: str | None = "B",
    status: CourseRecordStatus = CourseRecordStatus.complete,
    equivalent_of: str | None = None,
) -> AuditCourse:
    if status == CourseRecordStatus.in_progress:
        grade = None
    return AuditCourse(
        course_code=code,
        title=code,
        credits=3,
        grade=grade,
        term="Fall 2026",
        status=status,
        equivalent_of=equivalent_of,
    )


def course(
    code: str,
    prereq_text: str | None = None,
    equivalents: list[str] | None = None,
    prereq: PrereqExpression | None = None,
) -> Course:
    return Course(
        code=code,
        title=code,
        credits=3,
        department=code.split()[0],
        prereq_text=prereq_text,
        prereq=prereq,
        equivalents=equivalents or [],
        catalog_year="2026-2027",
        source_url="https://example.invalid/catalog",
    )


def check(text: str, *record: AuditCourse, catalog: list[Course] | None = None):  # type: ignore[no-untyped-def]
    rec = StudentRecord(list(record), equivalence_groups(catalog or []))
    return evaluate(parse_prereq_text(text), rec)


IN_PROGRESS = CourseRecordStatus.in_progress


# --- The brief's sample ------------------------------------------------------------


def test_sample_met_by_a_last_offered_course_on_the_record() -> None:
    result = check(SAMPLE, took("CS 101"))
    assert result.status == PrereqStatus.met
    assert result.notes == ()


def test_sample_with_none_of_the_courses_warns_twice_and_is_still_offered() -> None:
    result = check(SAMPLE, took("ENG 150"))
    assert result.status == PrereqStatus.met_with_warnings
    messages = [n.message for n in result.notes]
    assert messages == [
        f"{CHECK}: PathwayConnect",
        f"{CHECK}: LUC test score of at least 110",
    ]
    sec = section("CSE 111")
    checker = PrereqChecker([course("CSE 111", SAMPLE)], [took("ENG 150")])
    pool = build_candidates(audit(requirement("r", "CSE 111")), [sec], ConstraintSet(), checker)
    assert [c.section.id for c in pool.candidates] == [sec.id]
    assert [w.message for w in pool.candidates[0].warnings] == messages
    assert {w.kind for w in pool.candidates[0].warnings} == {"prerequisite_check"}


# --- Missing required course ----------------------------------------------------------


def test_missing_course_in_all_group_is_not_met() -> None:
    result = check("CSE 210 and MATH 112", took("CSE 210"))
    assert result.status == PrereqStatus.not_met
    assert result.reason == "prerequisite: needs MATH 112"


def test_candidate_builder_drops_section_with_the_reason() -> None:
    sec = section("MATH 215")
    checker = PrereqChecker([course("MATH 215", "MATH 112")], [took("CSE 110")])
    pool = build_candidates(audit(requirement("r", "MATH 215")), [sec], ConstraintSet(), checker)
    assert pool.candidates == []
    assert len(pool.excluded) == 1
    assert pool.excluded[0].section_id == sec.id
    assert pool.excluded[0].reason == ExclusionReason.prerequisite
    assert pool.excluded[0].detail == "prerequisite: needs MATH 112"


def test_any_group_lists_the_options() -> None:
    result = check("CSE 212 and (WDD 231 or CIT 230)")
    assert result.status == PrereqStatus.not_met
    assert result.reason == "prerequisite: needs CSE 212 and one of WDD 231, CIT 230"


# --- Grades -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("grade", "status"),
    [
        ("A", PrereqStatus.met),
        ("B+", PrereqStatus.met),
        ("C", PrereqStatus.met),
        ("C-", PrereqStatus.not_met),
        ("D", PrereqStatus.not_met),
        ("F", PrereqStatus.not_met),
        ("P", PrereqStatus.met_with_warnings),  # pass/fail: cannot compare, so check
    ],
)
def test_minimum_grade(grade: str, status: PrereqStatus) -> None:
    assert check("MATH 112 with a C or better", took("MATH 112", grade)).status == status


def test_grade_too_low_reason_names_the_grade() -> None:
    result = check("CSE 212 and MATH 215 (C or better)", took("CSE 212"), took("MATH 215", "D"))
    assert result.reason == "prerequisite: needs MATH 215 with C or better"


def test_failed_course_does_not_count_without_a_minimum() -> None:
    assert check("CSE 210", took("CSE 210", "F")).status == PrereqStatus.not_met
    assert check("CSE 210", took("CSE 210", "D")).status == PrereqStatus.met


def test_a_retake_with_a_better_grade_counts() -> None:
    record = (took("MATH 112", "D"), took("MATH 112", "B"))
    assert check("MATH 112 with a C or better", *record).status == PrereqStatus.met


# --- In progress ----------------------------------------------------------------------


def test_in_progress_counts_and_is_labeled_pending_grade() -> None:
    result = check("CSE 210", took("CSE 210", status=IN_PROGRESS))
    assert result.status == PrereqStatus.met
    assert [n.kind for n in result.notes] == ["pending_grade"]
    assert "pending grade" in result.notes[0].message


def test_in_progress_counts_even_with_a_minimum_grade() -> None:
    result = check("MATH 112 with a C or better", took("MATH 112", status=IN_PROGRESS))
    assert result.status == PrereqStatus.met
    assert "pending grade" in result.notes[0].message
    assert "C or better" in result.notes[0].message


def test_a_completed_option_beats_a_pending_one() -> None:
    result = check("CSE 110 or CIT 160", took("CSE 110", status=IN_PROGRESS), took("CIT 160", "A"))
    assert result.status == PrereqStatus.met
    assert result.notes == ()


# --- Equivalents ------------------------------------------------------------------------


def test_catalog_equivalent_counts_as_the_course_it_replaces() -> None:
    catalog = [course("CSE 111", equivalents=["CS 124"])]
    assert check("CSE 111", took("CS 124"), catalog=catalog).status == PrereqStatus.met
    # Either direction of the catalog link.
    catalog = [course("CS 124", equivalents=["CSE 111"])]
    assert check("CSE 111", took("CS 124"), catalog=catalog).status == PrereqStatus.met


def test_equivalents_chain_through_the_catalog() -> None:
    catalog = [course("CSE 111", equivalents=["CS 124"]), course("CS 124", equivalents=["CS 102"])]
    assert check("CSE 111", took("CS 102"), catalog=catalog).status == PrereqStatus.met


def test_audit_equivalent_of_counts() -> None:
    record = took("TRAN 101", status=CourseRecordStatus.transfer, equivalent_of="MATH 112")
    assert check("MATH 112", record).status == PrereqStatus.met


def test_unrelated_course_does_not_count() -> None:
    catalog = [course("CSE 111", equivalents=["CS 124"])]
    assert check("CSE 111", took("CS 999"), catalog=catalog).status == PrereqStatus.not_met


# --- Nesting, conditions, unparsed ----------------------------------------------------


NESTED = "CSE 212 and (MATH 112 or (MATH 110 and math placement score of at least 75))"


@pytest.mark.parametrize(
    ("record", "status"),
    [
        ((took("CSE 212"), took("MATH 112")), PrereqStatus.met),
        ((took("CSE 212"), took("MATH 110")), PrereqStatus.met_with_warnings),
        ((took("CSE 212"),), PrereqStatus.not_met),
        ((took("MATH 112"),), PrereqStatus.not_met),
        ((took("CSE 212", status=IN_PROGRESS), took("MATH 112")), PrereqStatus.met),
    ],
)
def test_and_or_nested_three_levels(record: tuple[AuditCourse, ...], status: PrereqStatus) -> None:
    assert check(NESTED, *record).status == status


def test_nested_not_met_reason() -> None:
    result = check(NESTED, took("CSE 212"))
    assert result.reason == (
        "prerequisite: needs one of MATH 112, (MATH 110 and math placement score of at least 75)"
    )


@pytest.mark.parametrize("text", ["junior standing", "instructor consent", "PathwayConnect"])
def test_conditions_are_warnings_not_blocks(text: str) -> None:
    result = check(text)
    assert result.status == PrereqStatus.met_with_warnings
    assert [n.message for n in result.notes] == [f"{CHECK}: {text}"]


def test_unparsed_is_a_warning_never_no_prerequisites() -> None:
    rec = StudentRecord([])
    result = evaluate(PrereqUnparsed(text="Completion of the foundations sequence"), rec)
    assert result.status == PrereqStatus.met_with_warnings
    assert result.notes[0].kind == "unparsed"
    assert "Completion of the foundations sequence" in result.notes[0].message
    warnings = result.warnings("CSE 499")
    assert warnings[0].kind == "unparsed_prereq"


def test_co_requisite_not_yet_taken_is_a_warning() -> None:
    result = check("CSE 210 (may be taken concurrently)")
    assert result.status == PrereqStatus.met_with_warnings


# --- PrereqChecker --------------------------------------------------------------------


def test_checker_prefers_the_stored_tree_and_parses_text_otherwise() -> None:
    stored = parse_prereq_text("MATH 112")
    checker = PrereqChecker(
        [course("MATH 215", "CSE 999", prereq=stored), course("CSE 212", "CSE 210")],
        [took("MATH 112")],
    )
    assert checker.check("MATH 215").status == PrereqStatus.met  # tree wins over the text
    assert checker.check("CSE 212").reason == "prerequisite: needs CSE 210"


def test_checker_unreadable_text_is_unparsed() -> None:
    checker = PrereqChecker([course("CSE 499", "Completion of the foundations sequence")], [])
    result = checker.check("CSE 499")
    assert result.status == PrereqStatus.met_with_warnings
    assert result.notes[0].kind == "unparsed"


def test_course_missing_from_catalog_is_a_warning() -> None:
    result = PrereqChecker([], []).check("CSE 999")
    assert result.status == PrereqStatus.met_with_warnings
    assert result.notes[0].kind == "unparsed"


def test_no_prereq_text_means_none_listed() -> None:
    assert PrereqChecker([course("CSE 110")], []).check("CSE 110").status == PrereqStatus.met


def test_warnings_reach_the_built_schedule() -> None:
    checker = PrereqChecker([course("CSE 300", "CSE 212 and junior standing")], [took("CSE 212")])
    response = build_schedules(
        audit(requirement("r", "CSE 300")),
        [section("CSE 300", credits=12)],
        ConstraintSet(),
        credit_range=(12, 15),
        max_results=1,
        prereqs=checker,
    )
    assert response.schedules, response
    cls = response.schedules[0].classes[0]
    assert [w.message for w in cls.warnings] == [f"{CHECK}: junior standing"]
    assert response.schedules[0].warnings == cls.warnings


# --- Trees from the Course Search scrape (DATA-04) ------------------------------------
# DATA-04 stores, per course, the tree built by scripts/data_cleaner.py in `prereq` and
# the site's "requisites_expression" in `prereq_text`. The trees below are copied from
# scripts/out/course_search_clean.json (public catalog data).

CLEAN_JSON = Path(__file__).resolve().parents[2] / "scripts" / "out" / "course_search_clean.json"
_TREE: TypeAdapter[PrereqExpression] = TypeAdapter(PrereqExpression)


def _c(code: str, concurrent_ok: bool = False) -> dict[str, object]:
    return {
        "type": "course",
        "course_code": code,
        "min_grade": "C-",
        "concurrent_ok": concurrent_ok,
    }


CSE_111 = _TREE.validate_python(
    {
        "type": "any",
        "items": [
            _c("CS 101"),
            _c("CSE 110"),
            _c("CIT 160"),
            _c("PW 100T"),
            {"type": "condition", "text": "LUC exam: SCORE >= 110"},
        ],
    }
)
CSE_131 = _TREE.validate_python(
    {
        "type": "any",
        "items": [
            {"type": "all", "items": [_c("CSE 111"), _c("CSE 130")]},
            {"type": "all", "items": [_c("CS 124"), _c("CSE 130")]},
        ],
    }
)
CSE_121C = _TREE.validate_python(_c("CSE 111", concurrent_ok=True))
CSE_111_TEXT = (
    "[9656] Course Prerequisite: CS 101 (C- or better) OR [9658] Course Prerequisite: "
    "CSE 110 (C- or better) OR [9659] Course Prerequisite: CIT 160 (C- or better) OR "
    "[9841] Course Prerequisite: PW 100T (C- or better) OR [10549] Course Prerequisite: "
    "Literacy and Understanding Computing exam must be taken with a SCORE score of 110 "
    "or greater."
)


def _eval(expr: PrereqExpression, *record: AuditCourse):  # type: ignore[no-untyped-def]
    return evaluate(expr, StudentRecord(list(record)))


@pytest.mark.parametrize(
    ("record", "status"),
    [
        ((took("CSE 110", "C-"),), PrereqStatus.met),
        ((took("PW 100T", "A"),), PrereqStatus.met),
        ((took("CSE 110", None, IN_PROGRESS),), PrereqStatus.met),
        # Below C- or none of the courses: the LUC exam is still possible, so a warning.
        ((took("CSE 110", "D"),), PrereqStatus.met_with_warnings),
        ((), PrereqStatus.met_with_warnings),
    ],
)
def test_course_search_tree_cse_111(record: tuple[AuditCourse, ...], status: PrereqStatus) -> None:
    result = _eval(CSE_111, *record)
    assert result.status == status
    if status == PrereqStatus.met_with_warnings:
        assert [n.message for n in result.notes] == [f"{CHECK}: LUC exam: SCORE >= 110"]


def test_course_search_tree_any_of_all_groups() -> None:
    assert _eval(CSE_131, took("CS 124"), took("CSE 130")).status == PrereqStatus.met
    result = _eval(CSE_131, took("CSE 111"))
    assert result.status == PrereqStatus.not_met
    assert result.reason == (
        "prerequisite: needs one of (CSE 111 with C- or better and CSE 130 with C- or "
        "better), (CS 124 with C- or better and CSE 130 with C- or better)"
    )


def test_course_search_co_requisite() -> None:
    assert _eval(CSE_121C, took("CSE 111")).status == PrereqStatus.met
    pending = _eval(CSE_121C, took("CSE 111", None, IN_PROGRESS))
    assert pending.status == PrereqStatus.met
    assert pending.notes[0].kind == "pending_grade"
    assert _eval(CSE_121C).status == PrereqStatus.met_with_warnings


def test_stored_tree_means_the_site_text_is_never_parsed() -> None:
    """A DATA-04 row has both; the tree is used and the fallback (Haiku) is never called."""

    def no_parse(text: str | None) -> PrereqExpression:
        raise AssertionError(f"parsed {text!r}")

    checker = PrereqChecker(
        [course("CSE 111", CSE_111_TEXT, prereq=CSE_111)], [took("CS 101")], parse=no_parse
    )
    assert checker.check("CSE 111").status == PrereqStatus.met


@pytest.mark.skipif(not CLEAN_JSON.exists(), reason="no scrape in scripts/out")
def test_every_scraped_tree_validates_and_evaluates() -> None:
    data = json.loads(CLEAN_JSON.read_text(encoding="utf-8"))
    trees = {s["course"]: s["prereq"] for s in data["sections"]}
    assert trees
    for code, tree in trees.items():
        assert tree is not None, f"{code}: prereq is null (unreadable requisites)"
        result = evaluate(_TREE.validate_python(tree), StudentRecord([]))
        assert isinstance(result.status, PrereqStatus), code
