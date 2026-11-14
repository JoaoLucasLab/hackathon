"""The eight chat tools (AI-02).

Each tool has:
- a strict JSON schema sent to Claude (`strict: true`, `additionalProperties: false`,
  every property required; optional values are nullable instead of omitted),
- a Pydantic model that validates the arguments before anything runs,
- a function that calls the same Python function as the matching API endpoint.

Bad arguments raise ToolInputError with a message Claude can fix and retry once
(the chat loop owns the retry). A failure while running (unknown professor, ...)
raises ToolExecutionError. Both go back to Claude as an `is_error` tool result.

Tool results are facts for Claude to cite. Free text inside them (course
descriptions, professor bios) is data, never instructions: see prompts/system.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from anthropic.types import ToolParam
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api import audit as audit_api
from app.api import fixture_data
from app.api import mentors as mentors_api
from app.api import professors as professors_api
from app.api import schedules as schedules_api
from app.contracts import (
    BuildSchedulesRequest,
    ConstraintSet,
    CourseCode,
    CourseRecordStatus,
    DegreeAudit,
    DeliveryMethod,
    EmailDraftRequest,
    FavoriteUpdate,
    MentorGoal,
    MentorSearchRequest,
)


class ToolInputError(ValueError):
    """Claude sent arguments that do not validate. Retry once with this message."""


class ToolExecutionError(RuntimeError):
    """The arguments were valid but the tool could not do it (e.g. not found)."""


@dataclass
class ToolContext:
    """Per-session state the tools read and update. No name or student ID in here."""

    audit: DegreeAudit
    constraints: ConstraintSet = field(default_factory=ConstraintSet)
    favorite_professor_ids: set[str] = field(default_factory=set)


# --- JSON schema helpers (strict mode: every property required, no extras) ---------


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _str(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _enum(values: list[str], description: str) -> dict[str, Any]:
    return {"type": "string", "enum": values, "description": description}


_COURSE_CODE = _str('Course code: subject letters, one space, number. Example: "CSE 212".')
_COURSE_CODES = {"type": "array", "items": _COURSE_CODE}
_DAYS = [d for d in ("M", "T", "W", "R", "F", "S")]
_GOALS = [g.value for g in MentorGoal]
_DELIVERY = [d.value for d in DeliveryMethod]

_CONSTRAINT_SET = _obj(
    {
        "credit_min": _nullable({"type": "number", "description": "Minimum credits."}),
        "credit_max": _nullable({"type": "number", "description": "Maximum credits."}),
        "earliest_start": _nullable(
            _str('No class starts before this. 24-hour "HH:MM". No morning classes = "11:30".')
        ),
        "latest_end": _nullable(_str('No class ends after this. 24-hour "HH:MM".')),
        "days_off": {
            "type": "array",
            "items": _enum(_DAYS, "M Mon, T Tue, W Wed, R Thu, F Fri, S Sat."),
        },
        "include_courses": {**_COURSE_CODES, "description": "Courses the student must take."},
        "exclude_courses": {**_COURSE_CODES, "description": "Courses the student does not want."},
        "exclude_section_ids": {
            "type": "array",
            "items": _str("Section id from search_sections."),
        },
        "delivery_methods": {
            "type": "array",
            "items": _enum(_DELIVERY, "Delivery method."),
            "description": "Empty means any.",
        },
        "only_required": {"type": "boolean", "description": "Only classes required to graduate."},
        "allow_waitlist": {"type": "boolean", "description": "Closed sections may be waitlisted."},
        "only_favorite_professors": {"type": "boolean"},
    }
)


# --- Argument models (validated before a tool runs) --------------------------------


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class SearchSectionsArgs(_Args):
    course_codes: list[CourseCode] = Field(min_length=1, max_length=10)
    delivery_method: DeliveryMethod | None


class CheckPrerequisitesArgs(_Args):
    course_codes: list[CourseCode] = Field(min_length=1, max_length=10)


class BuildSchedulesArgs(_Args):
    constraints: ConstraintSet
    max_results: int = Field(ge=1, le=5)


class ProfessorProfileArgs(_Args):
    professor_id: str | None
    name: str | None


class ToggleFavoriteArgs(_Args):
    professor_id: str
    favorite: bool


class FindMentorsArgs(_Args):
    goal: MentorGoal
    tags: list[str] = Field(min_length=1, max_length=8)


class DraftEmailArgs(_Args):
    professor_id: str
    goal: MentorGoal
    mention_grade: bool


# --- Tool functions -----------------------------------------------------------------

Json = dict[str, Any]


def _dump(model: BaseModel) -> Json:
    return model.model_dump(mode="json")


def _not_found(exc: HTTPException) -> ToolExecutionError:
    return ToolExecutionError(str(exc.detail))


def get_remaining_requirements(ctx: ToolContext, _: NoArgs) -> Json:
    return {
        "track": ctx.audit.track.value if ctx.audit.track else None,
        "track_known": ctx.audit.track is not None,
        "requirements": [_dump(r) for r in audit_api.remaining_requirements()],
    }


def search_sections(ctx: ToolContext, args: SearchSectionsArgs) -> Json:
    courses = {c.code: c for c in fixture_data.courses()}
    sections = fixture_data.sections()
    found: list[Json] = []
    not_found: list[str] = []
    for code in args.course_codes:
        matches = [
            s
            for s in sections
            if s.course_code == code
            and (args.delivery_method is None or s.delivery_method == args.delivery_method)
        ]
        course = courses.get(code)
        if course is None and not matches:
            not_found.append(code)
            continue
        found.append(
            {
                "course_code": code,
                "title": course.title if course else matches[0].title,
                "credits": course.credits if course else matches[0].credits,
                "description": course.description if course else "",
                "sections": [_dump(s) for s in matches],
            }
        )
    return {"courses": found, "not_found": not_found}


def check_prerequisites(ctx: ToolContext, args: CheckPrerequisitesArgs) -> Json:
    courses = {c.code: c for c in fixture_data.courses()}
    record = [
        {
            "course_code": c.course_code,
            "status": c.status.value,
            "grade": c.grade,
            "pending_grade": c.status == CourseRecordStatus.in_progress,
        }
        for c in ctx.audit.courses
    ]
    results: list[Json] = []
    not_found: list[str] = []
    for code in args.course_codes:
        course = courses.get(code)
        if course is None:
            not_found.append(code)
            continue
        results.append(
            {
                "course_code": code,
                "prereq_text": course.prereq_text,
                "prereq": _dump(course.prereq) if course.prereq is not None else None,
                "parsed": course.prereq is not None,
            }
        )
    return {
        "courses": results,
        "not_found": not_found,
        "student_record": record,
        # ENG-04 (evaluator) is not merged yet: report the rule, never a verdict.
        "evaluated": False,
        "note": (
            "Eligibility is not evaluated yet. Show the prerequisite text and say to "
            "check it before registering. If prereq is null it was not parsed: that "
            "does NOT mean there are no prerequisites."
        ),
    }


def build_schedules(ctx: ToolContext, args: BuildSchedulesArgs) -> Json:
    response = schedules_api.build_schedules(
        BuildSchedulesRequest(constraints=args.constraints, max_results=args.max_results)
    )
    ctx.constraints = args.constraints
    return {"constraints": _dump(args.constraints), **_dump(response)}


def get_professor_profile(ctx: ToolContext, args: ProfessorProfileArgs) -> Json:
    if args.professor_id:
        try:
            profs = [professors_api.get_professor(args.professor_id)]
        except HTTPException as exc:
            raise _not_found(exc) from exc
    elif args.name:
        profs = professors_api.list_professors(q=args.name)[:5]
    else:
        raise ToolInputError("Give either professor_id or name.")
    return {
        "professors": [
            {**_dump(p), "is_favorite": p.id in ctx.favorite_professor_ids} for p in profs
        ]
    }


def toggle_favorite_professor(ctx: ToolContext, args: ToggleFavoriteArgs) -> Json:
    try:
        fav = professors_api.set_favorite(
            args.professor_id, FavoriteUpdate(favorite=args.favorite)
        )
    except HTTPException as exc:
        raise _not_found(exc) from exc
    if fav.favorite:
        ctx.favorite_professor_ids.add(fav.professor_id)
    else:
        ctx.favorite_professor_ids.discard(fav.professor_id)
    return _dump(fav)


def find_mentors(ctx: ToolContext, args: FindMentorsArgs) -> Json:
    matches = mentors_api.search_mentors(MentorSearchRequest(goal=args.goal, tags=args.tags))
    return {"matches": [_dump(m) for m in matches]}


def draft_outreach_email(ctx: ToolContext, args: DraftEmailArgs) -> Json:
    try:
        draft = mentors_api.email_draft(
            args.professor_id,
            EmailDraftRequest(goal=args.goal, mention_grade=args.mention_grade),
        )
    except HTTPException as exc:
        raise _not_found(exc) from exc
    return {**_dump(draft), "sent": False, "note": "Draft only. The student copies it."}


# --- Registry -----------------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    args_model: type[_Args]
    run: Callable[[ToolContext, Any], Json]

    def definition(self) -> ToolParam:
        return ToolParam(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            strict=True,
        )


TOOLS: tuple[Tool, ...] = (
    Tool(
        "get_remaining_requirements",
        "The student's unmet degree requirements from their audit, with the courses that "
        "can fill each one, and the student's track (null if unknown: then ask).",
        _obj({}),
        NoArgs,
        get_remaining_requirements,
    ),
    Tool(
        "search_sections",
        "Winter 2027 sections for the given courses: days, times, block, delivery method, "
        "and seats with the time they were checked. Codes the catalog does not have are "
        "listed in not_found.",
        _obj(
            {
                "course_codes": {**_COURSE_CODES, "description": "1 to 10 course codes."},
                "delivery_method": _nullable(_enum(_DELIVERY, "Filter, or null for any.")),
            }
        ),
        SearchSectionsArgs,
        search_sections,
    ),
    Tool(
        "check_prerequisites",
        "Prerequisite rules for the given courses and the student's course record "
        "(in-progress courses count, labeled pending grade).",
        _obj({"course_codes": {**_COURSE_CODES, "description": "1 to 10 course codes."}}),
        CheckPrerequisitesArgs,
        check_prerequisites,
    ),
    Tool(
        "build_schedules",
        "Build 1 to 5 Winter 2027 schedules. Send the complete set of constraints the "
        "student wants now, including earlier ones still in force.",
        _obj(
            {
                "constraints": _CONSTRAINT_SET,
                "max_results": {"type": "integer", "description": "1 to 5. Usually 3."},
            }
        ),
        BuildSchedulesArgs,
        build_schedules,
    ),
    Tool(
        "get_professor_profile",
        "A professor's public profile from official university pages. Give professor_id, "
        "or a name (or part of one) to search. No ratings.",
        _obj(
            {
                "professor_id": _nullable(_str("Exact professor id.")),
                "name": _nullable(_str("Name or part of a name.")),
            }
        ),
        ProfessorProfileArgs,
        get_professor_profile,
    ),
    Tool(
        "toggle_favorite_professor",
        "Mark or unmark a professor as one of the student's favorites.",
        _obj(
            {
                "professor_id": _str("Exact professor id."),
                "favorite": {"type": "boolean"},
            }
        ),
        ToggleFavoriteArgs,
        toggle_favorite_professor,
    ),
    Tool(
        "find_mentors",
        "Rank professors as possible mentors for a goal, by overlap with topic tags.",
        _obj(
            {
                "goal": _enum(_GOALS, "What the student wants from the mentor."),
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "1 to 8 topic tags.",
                },
            }
        ),
        FindMentorsArgs,
        find_mentors,
    ),
    Tool(
        "draft_outreach_email",
        "Draft an email to a professor for the student to copy. The app never sends it.",
        _obj(
            {
                "professor_id": _str("Exact professor id."),
                "goal": _enum(_GOALS, "Why the student is writing."),
                "mention_grade": {"type": "boolean"},
            }
        ),
        DraftEmailArgs,
        draft_outreach_email,
    ),
)

TOOLS_BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}


def tool_definitions() -> list[ToolParam]:
    """Tool list for the Messages API. Fixed order, so the prompt cache keeps hitting."""
    return [t.definition() for t in TOOLS]


def run_tool(ctx: ToolContext, name: str, raw_input: Any) -> Json:
    """Validate Claude's arguments with Pydantic, then run the tool."""
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        raise ToolInputError(f"Unknown tool {name!r}. Use one of: {', '.join(TOOLS_BY_NAME)}.")
    try:
        args = tool.args_model.model_validate(raw_input)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'input'}: {err['msg']}"
            for err in exc.errors()
        )
        raise ToolInputError(f"Invalid arguments for {name}: {problems}") from exc
    return tool.run(ctx, args)
