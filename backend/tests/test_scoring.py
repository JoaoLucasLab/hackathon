"""ENG-05: the full score, favorite professors, and config-driven results."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from tests.engine_helpers import audit, requirement, section
from tests.test_prereq_evaluator import course

from app.api import fixture_data
from app.api import professors as professors_api
from app.api.schedules import prereq_checker
from app.contracts import (
    BlockKind,
    BuildSchedulesResponse,
    ConstraintSet,
    ExclusionReason,
    SeatStatus,
)
from app.engine.prereqs.evaluator import PrereqChecker
from app.engine.scoring import (
    ScoreInputs,
    Weights,
    idle_minutes,
    open_share,
    score_schedule,
    unlock_counts,
)
from app.engine.solver import build_schedules
from app.main import app
from app.schools.byui.rules import CONFIG_PATH, ByuiRules, load_config

RULES = ByuiRules()
W = Weights.from_mapping(RULES.scoring_weights())


def _one(**weights: float) -> Weights:
    """Weights with only the named terms switched on."""
    return Weights(**{"requirement": 0, "credit": 0, **weights})


# --- each score term --------------------------------------------------------------


def test_requirements_filled_raise_the_score() -> None:
    secs = [section("AAA 101")]
    inputs = ScoreInputs(weights=_one(requirement=100))
    assert score_schedule(secs, 2, 0, inputs) - score_schedule(secs, 1, 0, inputs) == 100


def test_preferences_met_raise_the_score() -> None:
    inputs = ScoreInputs(weights=_one(preference=5))
    assert score_schedule([section("AAA 101")], 0, 3, inputs) == 15


def test_favorite_professor_raises_the_score() -> None:
    inputs = ScoreInputs(
        weights=_one(favorite_professor=20), favorite_professor_ids=frozenset({"p-fav"})
    )
    fav = section("AAA 101", instructor="p-fav")
    other = section("AAA 101", instructor="p-other")
    assert score_schedule([fav], 0, 0, inputs) == 20
    assert score_schedule([other], 0, 0, inputs) == 0


@pytest.mark.parametrize(
    ("whens", "blocks", "idle"),
    [
        (["MWF 09:00-10:00", "MWF 11:00-12:00"], [BlockKind.full] * 2, 180),  # 1 h x 3 days
        (["MWF 09:00-10:00", "MWF 10:00-11:00"], [BlockKind.full] * 2, 0),  # back to back
        (["MWF 09:00-10:00", "TR 11:00-12:00"], [BlockKind.full] * 2, 0),  # different days
        # First Block and Second Block at the same time: no overlap and no gap.
        (["MWF 10:00-11:00", "MWF 10:00-11:00"], [BlockKind.first, BlockKind.second], 0),
        # A gap only in First Block weeks counts for half the semester.
        (["M 09:00-10:00", "M 11:00-12:00"], [BlockKind.full, BlockKind.first], 30),
        (
            ["M 09:00-10:00", "M 10:00-11:00", "M 13:00-14:00"],
            [BlockKind.full] * 3,
            120,
        ),
    ],
)
def test_idle_minutes(whens: list[str], blocks: list[BlockKind], idle: float) -> None:
    secs = [
        section(f"C{chr(65 + i)}C 101", when=w, block=b)
        for i, (w, b) in enumerate(zip(whens, blocks, strict=True))
    ]
    assert idle_minutes(secs) == idle


def test_gaps_lower_the_score() -> None:
    inputs = ScoreInputs(weights=_one(gap_per_hour=4))
    tight = [section("AAA 101", when="MWF 09:00-10:00"), section("BBB 101", when="MWF 10:00-11:00")]
    loose = [section("AAA 101", when="MWF 09:00-10:00"), section("BBB 101", when="MWF 12:00-13:00")]
    assert score_schedule(tight, 0, 0, inputs) == 0
    assert score_schedule(loose, 0, 0, inputs) == -4 * 6  # 2 h x 3 days


def test_open_seats_raise_the_score() -> None:
    inputs = ScoreInputs(weights=_one(open_seats=3))
    open_ = section("AAA 101")  # 10 of 30 open
    closed = section("AAA 101", status=SeatStatus.closed)
    assert open_share(open_) == pytest.approx(1 / 3)
    assert score_schedule([open_], 0, 0, inputs) == pytest.approx(1.0)
    assert score_schedule([closed], 0, 0, inputs) == 0


def test_unlock_counts_from_prerequisite_trees() -> None:
    """CSE 212 is a prerequisite for two other remaining requirements."""
    a = audit(
        requirement("r212", "CSE 212"),
        requirement("r300", "CSE 300"),
        requirement("r310", "CSE 310", "CSE 311"),
        requirement("rmath", "MATH 113"),
    )
    checker = PrereqChecker(
        [
            course("CSE 300", "CSE 212"),
            course("CSE 310", "CSE 212 and MATH 113"),
            course("CSE 311", "CSE 212"),  # same requirement as CSE 310: counted once
            course("MATH 113", "MATH 112"),
        ],
        [],
    )
    counts = unlock_counts(a, checker.expression)
    assert counts["CSE 212"] == 2
    assert counts["MATH 113"] == 1
    assert "MATH 112" in counts  # a course not in any requirement still unlocks MATH 113


def test_class_that_unlocks_others_is_preferred() -> None:
    """Room for one 3-credit elective: the one that is a prerequisite for a
    remaining requirement wins."""
    a = audit(requirement("elective", "AAA 101", "BBB 101"), requirement("next", "CCC 201"))
    checker = PrereqChecker(
        [course("AAA 101"), course("BBB 101"), course("CCC 201", "BBB 101")], []
    )
    secs = [
        section("AAA 101", when="MWF 09:00-10:00"),
        section("BBB 101", when="TR 09:00-10:00"),
    ]
    res = build_schedules(
        a, secs, ConstraintSet(), max_results=1, credit_range=(3, 3), prereqs=checker, rules=RULES
    )
    assert [c.section.course_code for c in res.schedules[0].classes] == ["BBB 101"]


# --- favorite professors ------------------------------------------------------------


def test_all_else_equal_favorite_professor_ranks_first() -> None:
    a = audit(requirement("ra", "AAA 101"), requirement("rb", "BBB 101"))
    secs = [
        section("AAA 101", "01", "MWF 09:00-10:00", instructor="p-other"),
        section("BBB 101", "01", "MWF 09:00-10:00", instructor="p-fav"),
    ]

    def build(favorites: set[str]) -> BuildSchedulesResponse:
        return build_schedules(
            a,
            secs,
            ConstraintSet(),
            max_results=2,
            credit_range=(3, 3),
            favorite_professor_ids=favorites,
            rules=RULES,
        )

    res = build({"p-fav"})
    assert len(res.schedules) == 2
    top, second = res.schedules
    assert top.classes[0].section.instructor_ids == ["p-fav"]
    assert top.why.favorite_professor_ids == ["p-fav"]
    assert top.score > second.score
    # Without the star the two are tied and the order is the solve order.
    plain = build(set())
    assert plain.schedules[0].score == plain.schedules[1].score


def test_only_my_favorites_is_a_hard_constraint() -> None:
    a = audit(requirement("ra", "AAA 101"), requirement("rb", "BBB 101"))
    secs = [
        section("AAA 101", "01", "MWF 09:00-10:00", instructor="p-fav"),
        section("AAA 101", "02", "MWF 11:00-12:00", instructor="p-other"),
        section("BBB 101", "01", "TR 09:00-10:00", instructor="p-other"),
    ]
    res = build_schedules(
        a,
        secs,
        ConstraintSet(only_favorite_professors=True),
        max_results=3,
        credit_range=(3, 6),
        favorite_professor_ids={"p-fav"},
        rules=RULES,
    )
    assert res.schedules
    for s in res.schedules:
        assert all("p-fav" in c.section.instructor_ids for c in s.classes)
    out = {e.section_id: e for e in res.excluded}
    for sid in ("2027;WI|AAA 101-02", "2027;WI|BBB 101-01"):
        assert out[sid].reason == ExclusionReason.excluded_by_you
        assert out[sid].detail == "not taught by a favorite professor"


def test_starring_a_professor_moves_their_schedule_to_the_top() -> None:
    """Fixture demo: star a professor who is not in the top schedule, rebuild,
    and the new top schedule has a class with them."""
    api = TestClient(app)
    api.cookies.set("sid", "test-scoring-star")
    try:
        first = api.post("/api/schedules/build", json={"max_results": 3}).json()
        top_profs = {
            p for c in first["schedules"][0]["classes"] for p in c["section"]["instructor_ids"]
        }
        offered = {
            p
            for s in first["schedules"]
            for c in s["classes"]
            for b in [c["section"], *c["backups"]]
            for p in b["instructor_ids"]
        }
        pick = sorted(offered - top_profs)[0]
        professors_api.favorites_for("test-scoring-star").add(pick)
        again = api.post("/api/schedules/build", json={"max_results": 3}).json()
        top = again["schedules"][0]
        assert pick in {p for c in top["classes"] for p in c["section"]["instructor_ids"]}
        assert pick in top["why"]["favorite_professor_ids"]
    finally:
        professors_api.favorites_for("test-scoring-star").clear()


# --- config drives results -------------------------------------------------------------


def _rules_with(tmp_path: Path, **changes: object) -> ByuiRules:
    data = load_config(CONFIG_PATH)
    for key, value in changes.items():
        if key.startswith("weights."):
            data["weights"][key.split(".", 1)[1]] = value
        else:
            data[key] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return ByuiRules.from_file(path, fixture_data.courses())


def _fixture_build(rules: ByuiRules) -> list[tuple[float, list[str]]]:
    a = fixture_data.audit()
    res = build_schedules(
        a,
        fixture_data.sections(),
        ConstraintSet(),
        max_results=3,
        prereqs=prereq_checker(a),
        rules=rules,
    )
    return [(s.total_credits, sorted(c.section.id for c in s.classes)) for s in res.schedules]


def test_credit_default_max_in_config_changes_results(tmp_path: Path) -> None:
    base = _fixture_build(ByuiRules.from_file(CONFIG_PATH, fixture_data.courses()))
    lower = _fixture_build(_rules_with(tmp_path, credit_default_min=6, credit_default_max=9))
    assert base and lower
    assert all(12 <= credits <= 15 for credits, _ in base)
    assert all(6 <= credits <= 9 for credits, _ in lower)


def test_weight_in_config_changes_results(tmp_path: Path) -> None:
    """A heavy gap penalty changes which sections are picked."""
    base = _fixture_build(ByuiRules.from_file(CONFIG_PATH, fixture_data.courses()))
    gappy = _fixture_build(_rules_with(tmp_path, **{"weights.gap_per_hour": 200}))
    assert base and gappy
    assert base != gappy


def test_unknown_weight_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown score weights: typo"):
        Weights.from_mapping({"typo": 1})


def test_config_weights_cover_every_score_term() -> None:
    assert set(RULES.scoring_weights()) == set(Weights.__dataclass_fields__)
    assert W.requirement > W.favorite_professor > 0
