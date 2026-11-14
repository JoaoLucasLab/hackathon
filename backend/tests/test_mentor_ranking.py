"""ENG-06: mentor ranking. Deterministic score, structured reasons with sources."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from tests.engine_helpers import section

from app.api import fixture_data
from app.api.mentors import find_mentors
from app.contracts import (
    AuditCourse,
    CourseRecordStatus,
    MentorGoal,
    MentorMatch,
    MentorSearchRequest,
    Professor,
    ProfessorSource,
)
from app.engine.mentors import (
    MentorSettings,
    MentorWeights,
    match_audit_instructor,
    rank_mentors,
    split_audit_name,
)
from app.main import app
from app.schools.byui.rules import ByuiRules, load_config

RULES = ByuiRules()
NOW = datetime(2026, 11, 10, tzinfo=UTC)
DEMO_TAGS = ["machine learning", "data science"]


def prof(
    pid: str,
    last: str,
    first: str = "Pat",
    *,
    dept: str = "Computer Science",
    tags: tuple[str, ...] = (),
    research: bool | None = None,
    courses: tuple[str, ...] = (),
) -> Professor:
    return Professor(
        id=pid,
        first_name=first,
        last_name=last,
        department=dept,
        topic_tags=list(tags),
        lists_undergrad_research=research,
        winter_courses=list(courses),
        sources=[
            ProfessorSource(
                kind=kind,
                value="x",
                source_url=f"https://example.test/{pid}#{kind}",
                fetched_at=NOW,
            )
            for kind in ("interests", "research")
        ],
        rmp_url="https://example.test/rmp",
    )


def took(code: str, instructor: str | None, grade: str | None = "A") -> AuditCourse:
    return AuditCourse(
        course_code=code,
        title=code,
        credits=3,
        grade=grade,
        term="Fall 2025",
        status=CourseRecordStatus.complete if grade else CourseRecordStatus.in_progress,
        instructor=instructor,
    )


W = MentorWeights(topic_overlap=10, took_class=15, teaches_winter=8, lists_research=25)
S = MentorSettings(weights=W)


def ids(matches: list[MentorMatch]) -> list[str]:
    return [m.professor.id for m in matches]


def rank(
    profs: list[Professor],
    tags: list[str],
    audit: list[AuditCourse] = (),  # type: ignore[assignment]
    goal: MentorGoal = MentorGoal.research,
    sections: list = (),  # type: ignore[assignment,type-arg]
    settings: MentorSettings = S,
) -> list[MentorMatch]:
    return rank_mentors(goal, tags, profs, list(audit), list(sections), [], settings)


# --- endpoint on fixtures ----------------------------------------------------------


def test_endpoint_research_demo_topic_at_most_5_sorted_fast() -> None:
    client = TestClient(app)
    start = time.perf_counter()
    resp = client.post("/api/mentors/search", json={"goal": "research", "tags": DEMO_TAGS})
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200
    matches = [MentorMatch.model_validate(m) for m in resp.json()]
    assert 1 <= len(matches) <= 5
    scores = [m.score for m in matches]
    assert scores == sorted(scores, reverse=True)
    assert matches[0].professor.id == "p-hale"
    assert elapsed < 1.0
    for m in matches:
        assert m.score == pytest.approx(sum(r.points for r in m.reasons))


# --- the four parts ------------------------------------------------------------------


def test_each_part_scores_with_a_source_pointer() -> None:
    p = prof("p-a", "Alpha", "Ann", tags=("machine learning",), research=True)
    sec = section("CSE 450", instructor="p-a").model_copy(update={"title": "Machine Learning"})
    [match] = rank([p], ["Machine Learning"], [took("CSE 450", "Alpha, Ann")], sections=[sec])
    by_kind = {r.kind: r for r in match.reasons}
    assert set(by_kind) == {"topic_overlap", "took_class", "teaches_winter", "lists_research"}
    assert match.score == 10 + 15 + 8 + 25

    assert by_kind["topic_overlap"].source.kind == "profile"
    assert by_kind["topic_overlap"].source.url == "https://example.test/p-a#interests"
    assert by_kind["took_class"].source.kind == "audit_row"
    assert by_kind["took_class"].source.ref == "CSE 450"
    assert by_kind["teaches_winter"].source.kind == "section"
    assert by_kind["teaches_winter"].source.ref == sec.id
    assert by_kind["teaches_winter"].source.url == sec.source_url
    assert by_kind["lists_research"].source.kind == "profile"
    assert by_kind["lists_research"].source.url == "https://example.test/p-a#research"


def test_research_points_only_for_goal_research() -> None:
    p = prof("p-a", "Alpha", tags=("ai",), research=True)
    settings = MentorSettings(weights=W)
    [m] = rank([p], ["ai"], goal=MentorGoal.ta_job, settings=settings)
    assert "lists_research" not in {r.kind for r in m.reasons}


def test_teaches_winter_needs_a_course_in_the_area() -> None:
    p = prof("p-a", "Alpha", tags=("ai",))
    off_topic = section("CSE 110", instructor="p-a")
    [m] = rank([p], ["ai"], sections=[off_topic])
    assert "teaches_winter" not in {r.kind for r in m.reasons}


@pytest.mark.parametrize(
    ("grade", "counts"),
    [
        ("A", True),
        ("B+", True),
        ("B", True),
        ("B-", False),
        ("C", False),
        ("P", False),
        (None, False),
    ],
)
def test_took_class_needs_b_or_better(grade: str | None, counts: bool) -> None:
    p = prof("p-a", "Alpha", "Ann", courses=("CSE 110",))
    got = rank([p], ["nothing"], [took("CSE 110", "Alpha, Ann", grade)])
    assert (ids(got) == ["p-a"]) is counts


def test_min_grade_comes_from_config() -> None:
    assert RULES.mentor_min_grade() == "B"
    stricter = MentorSettings(weights=W, min_grade="A-", grade_scale=tuple(RULES.grade_scale()))
    p = prof("p-a", "Alpha", "Ann", courses=("CSE 110",))
    assert rank([p], ["x"], [took("CSE 110", "Alpha, Ann", "B+")], settings=stricter) == []


# --- who is returned ------------------------------------------------------------------


def test_no_overlap_and_no_shared_class_is_never_returned() -> None:
    lonely = prof("p-x", "Xu", tags=("graphics",), research=True)
    teaches = section("CSE 450", instructor="p-x").model_copy(update={"title": "Machine Learning"})
    assert rank([lonely], ["machine learning"], sections=[teaches]) == []


def test_fixture_search_never_returns_unrelated_professors() -> None:
    audit = fixture_data.audit()
    for goal in MentorGoal:
        for m in find_mentors(MentorSearchRequest(goal=goal, tags=DEMO_TAGS), audit):
            assert {r.kind for r in m.reasons} & {"topic_overlap", "took_class"}


def test_recommendation_letter_ranks_shared_class_above_topic_matches() -> None:
    topical = prof("p-t", "Aaron", tags=("ai", "ml", "nlp"), research=True, courses=("CSE 450",))
    teacher = prof("p-c", "Zed", "Zoe", courses=("CSE 110",))
    settings = MentorSettings.from_rules(RULES, MentorGoal.recommendation_letter)
    got = rank(
        [topical, teacher],
        ["ai", "ml", "nlp"],
        [took("CSE 110", "Zed, Zoe")],
        goal=MentorGoal.recommendation_letter,
        settings=settings,
    )
    assert ids(got) == ["p-c", "p-t"]


def test_recommendation_letter_weights_keep_the_guarantee() -> None:
    """A shared class beats the most a pure topic match can score (8 tags)."""
    w = MentorSettings.from_rules(RULES, MentorGoal.recommendation_letter).weights
    assert w.took_class > 8 * w.topic_overlap + w.teaches_winter + w.lists_research


def test_recommendation_letter_on_fixtures() -> None:
    body = MentorSearchRequest(goal=MentorGoal.recommendation_letter, tags=["data science"])
    matches = find_mentors(body, fixture_data.audit())
    took_any = [any(r.kind == "took_class" for r in m.reasons) for m in matches]
    assert took_any == sorted(took_any, reverse=True)  # all shared-class profs come first
    assert "p-reyes" not in ids(matches)[: sum(took_any)]


# --- determinism ----------------------------------------------------------------------


def test_same_input_same_order_ties_by_last_name() -> None:
    profs = [prof(f"p-{n}", n, tags=("ai",)) for n in ("Moss", "Abel", "Zane", "Kim")]
    first = rank(profs, ["ai"])
    assert ids(first) == ["p-Abel", "p-Kim", "p-Moss", "p-Zane"]
    for _ in range(5):
        assert ids(rank(list(reversed(profs)), ["ai"])) == ids(first)


def test_at_most_max_results() -> None:
    profs = [prof(f"p-{i}", f"L{i:02}", tags=("ai",)) for i in range(9)]
    assert len(rank(profs, ["ai"])) == 5


def test_tags_match_case_and_space_insensitive() -> None:
    p = prof("p-a", "Alpha", tags=("Machine Learning",))
    [m] = rank([p], ["  machine   LEARNING "])
    assert m.reasons[0].detail == "machine learning"


# --- audit name matching ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("Hale, Marcus", ("hale", "marcus")),
        ("Okafor, Ruth A.", ("okafor", "ruth")),
        ("Ruth A. Okafor", ("okafor", "ruth")),
        ("Okafor", None),
        ("", None),
    ],
)
def test_split_audit_name(printed: str, expected: tuple[str, str] | None) -> None:
    assert split_audit_name(printed) == expected


def test_same_name_different_department_is_not_merged() -> None:
    """The fixture has two John Smiths. REL 250 belongs to the Religious Education one."""
    profs = fixture_data.professors()
    row = took("REL 250", "Smith, John T.")
    courses = {c.code: c.department for c in fixture_data.courses()}
    match = match_audit_instructor(row, profs, fixture_data.sections(), courses)
    assert match is not None and match.id == "p-smith-rel"


def test_ambiguous_name_with_no_course_link_matches_nobody() -> None:
    a = prof("p-1", "Smith", "John", dept="Computer Science")
    b = prof("p-2", "Smith", "John", dept="History")
    assert match_audit_instructor(took("ART 101", "Smith, John"), [a, b], [], {}) is None


def test_name_alone_is_not_enough() -> None:
    a = prof("p-1", "Smith", "John", dept="Computer Science", courses=("CSE 110",))
    assert match_audit_instructor(took("HIST 201", "Smith, John"), [a], [], {}) is None


# --- grounding ----------------------------------------------------------------------------


def test_every_reason_points_at_data_that_exists() -> None:
    """Every course, section and professor in the reasons exists in the data."""
    courses = {c.code for c in fixture_data.courses()}
    sections = fixture_data.section_by_id()
    profs = fixture_data.professor_by_id()
    audit = fixture_data.audit()
    audit_codes = {c.course_code for c in audit.courses}
    for goal in MentorGoal:
        for tags in (DEMO_TAGS, ["book of mormon"], ["web development", "sql"]):
            for m in find_mentors(MentorSearchRequest(goal=goal, tags=tags), audit):
                p = profs[m.professor.id]
                for r in m.reasons:
                    src = r.source
                    if src.kind == "audit_row":
                        assert src.ref in audit_codes and src.ref in courses
                    elif src.kind == "section":
                        assert src.ref in sections
                        assert p.id in sections[src.ref].instructor_ids
                        assert sections[src.ref].course_code in courses
                    else:
                        assert src.url in {s.source_url for s in p.sources}
                    if r.kind == "topic_overlap":
                        assert r.detail in {t.lower() for t in p.topic_tags}


# --- config ---------------------------------------------------------------------------------


def test_every_goal_has_weights_in_config() -> None:
    config = load_config()
    assert set(config["mentors"]["weights"]) == {g.value for g in MentorGoal}
    for goal in MentorGoal:
        MentorSettings.from_rules(RULES, goal)  # unknown names raise


def test_changing_a_weight_in_config_changes_the_order() -> None:
    config = load_config()
    config["mentors"]["weights"]["research"]["lists_research"] = 500
    rules = ByuiRules(config)
    researcher = prof("p-r", "Zed", tags=("ai",), research=True)
    topical = prof("p-t", "Abe", tags=("ai", "ml"), research=False)
    base = rank(
        [researcher, topical],
        ["ai", "ml"],
        settings=MentorSettings.from_rules(RULES, MentorGoal.research),
    )
    changed = rank(
        [researcher, topical],
        ["ai", "ml"],
        settings=MentorSettings.from_rules(rules, MentorGoal.research),
    )
    assert ids(base) == ["p-t", "p-r"]
    assert ids(changed) == ["p-r", "p-t"]


def test_chat_tool_uses_the_session_audit() -> None:
    from app.llm.tools import FindMentorsArgs, ToolContext
    from app.llm.tools import find_mentors as tool

    audit = fixture_data.audit().model_copy(update={"courses": []})
    out = tool(ToolContext(audit=audit), FindMentorsArgs(goal=MentorGoal.research, tags=["sql"]))
    reasons = [r for m in out["matches"] for r in m["reasons"]]
    assert reasons and all(r["kind"] != "took_class" for r in reasons)
