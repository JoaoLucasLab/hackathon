"""AI-02: the eight chat tools have strict schemas and validate their arguments."""

from __future__ import annotations

from datetime import time
from typing import Any

import pytest

from app.api import fixture_data
from app.contracts import ConstraintSet, Day
from app.llm import tools

EXPECTED_NAMES = [
    "get_remaining_requirements",
    "search_sections",
    "check_prerequisites",
    "build_schedules",
    "get_professor_profile",
    "toggle_favorite_professor",
    "find_mentors",
    "draft_outreach_email",
]

EMPTY_CONSTRAINTS: dict[str, Any] = {
    "credit_min": None,
    "credit_max": None,
    "earliest_start": None,
    "latest_end": None,
    "days_off": [],
    "include_courses": [],
    "exclude_courses": [],
    "exclude_section_ids": [],
    "delivery_methods": [],
    "only_required": False,
    "allow_waitlist": False,
    "only_favorite_professors": False,
}


def _prof_id() -> str:
    return fixture_data.professors()[0].id


def _valid_inputs() -> dict[str, dict[str, Any]]:
    return {
        "get_remaining_requirements": {},
        "search_sections": {"course_codes": ["CSE 212"], "delivery_method": None},
        "check_prerequisites": {"course_codes": ["CSE 212"]},
        "build_schedules": {"constraints": EMPTY_CONSTRAINTS, "max_results": 3},
        "get_professor_profile": {"professor_id": _prof_id(), "name": None},
        "toggle_favorite_professor": {"professor_id": _prof_id(), "favorite": True},
        "find_mentors": {"goal": "research", "tags": ["machine learning"]},
        "draft_outreach_email": {
            "professor_id": _prof_id(),
            "goal": "research",
            "mention_grade": False,
        },
    }


@pytest.fixture
def ctx() -> tools.ToolContext:
    return tools.ToolContext(audit=fixture_data.audit())


def _objects(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Every object schema inside `schema`, including nested ones."""
    found: list[dict[str, Any]] = []
    if schema.get("type") == "object":
        found.append(schema)
        for sub in schema["properties"].values():
            found.extend(_objects(sub))
    for option in schema.get("anyOf", []):
        found.extend(_objects(option))
    if "items" in schema:
        found.extend(_objects(schema["items"]))
    return found


def test_exactly_the_eight_tools_in_fixed_order() -> None:
    assert [d["name"] for d in tools.tool_definitions()] == EXPECTED_NAMES
    assert tools.tool_definitions() == tools.tool_definitions()


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_schema_is_strict(name: str) -> None:
    definition = tools.TOOLS_BY_NAME[name].definition()
    assert definition["strict"] is True
    assert definition["description"]
    for obj in _objects(tools.TOOLS_BY_NAME[name].input_schema):
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj["properties"])


def test_constraint_schema_matches_contract() -> None:
    schema = tools.TOOLS_BY_NAME["build_schedules"].input_schema
    constraint_props = schema["properties"]["constraints"]["properties"]
    assert set(constraint_props) == set(ConstraintSet.model_fields)
    assert constraint_props["days_off"]["items"]["enum"] == [d.value for d in Day]


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_valid_input_runs(ctx: tools.ToolContext, name: str) -> None:
    result = tools.run_tool(ctx, name, _valid_inputs()[name])
    assert isinstance(result, dict)


@pytest.mark.parametrize("name", EXPECTED_NAMES)
def test_extra_field_rejected(ctx: tools.ToolContext, name: str) -> None:
    bad = {**_valid_inputs()[name], "student_name": "x"}
    with pytest.raises(tools.ToolInputError, match="student_name"):
        tools.run_tool(ctx, name, bad)


def test_bad_course_code_gives_fixable_message(ctx: tools.ToolContext) -> None:
    with pytest.raises(tools.ToolInputError, match=r"course_codes\.0"):
        tools.run_tool(
            ctx, "search_sections", {"course_codes": ["cse212"], "delivery_method": None}
        )


def test_unknown_tool(ctx: tools.ToolContext) -> None:
    with pytest.raises(tools.ToolInputError, match="Unknown tool"):
        tools.run_tool(ctx, "delete_everything", {})


def test_unknown_course_is_not_found(ctx: tools.ToolContext) -> None:
    result = tools.run_tool(
        ctx, "search_sections", {"course_codes": ["CSE 999", "CSE 212"], "delivery_method": None}
    )
    assert result["not_found"] == ["CSE 999"]
    assert [c["course_code"] for c in result["courses"]] == ["CSE 212"]


def test_build_schedules_stores_constraints(ctx: tools.ToolContext) -> None:
    constraints = {**EMPTY_CONSTRAINTS, "earliest_start": "11:30", "days_off": ["F"]}
    result = tools.run_tool(
        ctx, "build_schedules", {"constraints": constraints, "max_results": 3}
    )
    assert len(result["schedules"]) == 3
    assert ctx.constraints.earliest_start == time(11, 30)
    assert ctx.constraints.days_off == [Day.F]
    assert all(
        s["advising_note"] == "Confirm with BYU-Idaho Academic Advising."
        for s in result["schedules"]
    )


def test_prerequisites_are_evaluated_against_the_record(ctx: tools.ToolContext) -> None:
    result = tools.run_tool(ctx, "check_prerequisites", {"course_codes": ["CSE 212", "CSE 270"]})
    assert result["evaluated"] is True
    assert "does NOT mean there are no prerequisites" in result["note"]
    by_code = {c["course_code"]: c for c in result["courses"]}
    # CSE 210 is in progress on the fixture audit: counts, labeled pending grade.
    assert by_code["CSE 212"]["status"] == "met"
    assert any("pending grade" in m for m in by_code["CSE 212"]["pending_grade"])
    assert by_code["CSE 270"]["status"] == "not_met"
    assert by_code["CSE 270"]["needs"] == ["CSE 212"]


def test_unknown_professor_is_execution_error(ctx: tools.ToolContext) -> None:
    with pytest.raises(tools.ToolExecutionError):
        tools.run_tool(
            ctx, "toggle_favorite_professor", {"professor_id": "nobody", "favorite": True}
        )


def test_favorite_toggle_updates_context(ctx: tools.ToolContext) -> None:
    pid = _prof_id()
    tools.run_tool(ctx, "toggle_favorite_professor", {"professor_id": pid, "favorite": True})
    assert pid in ctx.favorite_professor_ids
    tools.run_tool(ctx, "toggle_favorite_professor", {"professor_id": pid, "favorite": False})
    assert pid not in ctx.favorite_professor_ids


def test_email_is_draft_only(ctx: tools.ToolContext) -> None:
    result = tools.run_tool(ctx, "draft_outreach_email", _valid_inputs()["draft_outreach_email"])
    assert result["sent"] is False
