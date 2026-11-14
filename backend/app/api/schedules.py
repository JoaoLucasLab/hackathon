"""Schedule building (ENG-03, ENG-05).

Prerequisites (ENG-04) are checked against the audit: sections the student is not
eligible for are left out with a reason, and conditions to verify become warnings.
School rules (track, religion, waitlist cap, credit range, score weights,
relaxation order) come from the registered school's `SchoolRules`.

The audit is the fixture audit until AI-04 stores the session's own audit.
Courses and sections come from `catalog_data`: Postgres when `DATABASE_URL` is set.

AI-08: the confirmed plan. The chat shows one schedule at a time; the student
confirms the one shown last, and it becomes the session's Winter 2027 plan.
Plans live in memory, keyed by the `sid` cookie (like favorites and the chat
session), until sessions move to Postgres; then they are encrypted at rest like
chats. The chat's ToolContext holds the very same `PlanState` object.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, Request, Response

from app.api import catalog_data, fixture_data
from app.api import professors as professors_api
from app.contracts import (
    BuildSchedulesRequest,
    BuildSchedulesResponse,
    ConfirmPlanRequest,
    ConstraintSet,
    DegreeAudit,
    Schedule,
)
from app.engine import solver
from app.engine.prereqs.evaluator import PrereqChecker
from app.llm.prereq_fallback import parse_with_fallback
from app.schools.base import default_school

router = APIRouter(prefix="/api", tags=["schedules"])


def prereq_checker(audit: DegreeAudit) -> PrereqChecker:
    """Catalog trees first; text without a tree goes through the parser + Haiku fallback."""
    return PrereqChecker(catalog_data.courses(), audit.courses, parse=parse_with_fallback)


def build_schedules(
    body: BuildSchedulesRequest, favorite_professor_ids: Iterable[str] = ()
) -> BuildSchedulesResponse:
    """Same function behind the endpoint and the `build_schedules` chat tool."""
    # TODO(AI-02): None should mean the session's saved constraints; the chat tool
    # always sends them, so until the endpoint can see the session it uses defaults.
    constraints = body.constraints or ConstraintSet()
    audit = fixture_data.audit()
    return solver.build_schedules(
        audit,
        catalog_data.sections(),
        constraints,
        max_results=body.max_results,
        avoid_schedules=body.avoid_schedules,
        favorite_professor_ids=favorite_professor_ids,
        prereqs=prereq_checker(audit),
        rules=default_school().rules,
    )


@router.post("/schedules/build", response_model=BuildSchedulesResponse, name="build_schedules")
def build_schedules_endpoint(
    body: BuildSchedulesRequest, request: Request
) -> BuildSchedulesResponse:
    favorites = professors_api.favorites_for(professors_api.session_id(request))
    return build_schedules(body, favorites)


# --- AI-08: the confirmed plan -----------------------------------------------------

# The solver accepts at most this many avoided schedules (BuildSchedulesRequest).
MAX_AVOIDED = 50


class PlanError(ValueError):
    """The schedule cannot be confirmed. The message says why."""


@dataclass
class PlanState:
    """What one session was shown and what it confirmed. No personal details."""

    # Every schedule the chat showed, oldest first. The last one is the only one
    # that can be confirmed; all of them are avoided in later builds.
    shown: list[Schedule] = field(default_factory=list)
    confirmed: Schedule | None = None

    @property
    def last_shown(self) -> Schedule | None:
        return self.shown[-1] if self.shown else None

    def record_shown(self, schedule: Schedule) -> int:
        """Remember a schedule the chat is about to show. Returns its option number."""
        self.shown.append(schedule)
        return len(self.shown)

    def avoid_lists(self, extra: Iterable[list[str]] = ()) -> list[list[str]]:
        """Section ids of every schedule already shown, plus `extra`, without repeats.
        A schedule the student saw never comes back (ENG-07)."""
        seen: set[frozenset[str]] = set()
        lists: list[list[str]] = []
        for ids in [*extra, *([c.section.id for c in s.classes] for s in self.shown)]:
            key = frozenset(ids)
            if key and key not in seen:
                seen.add(key)
                lists.append(sorted(key))
        return lists[-MAX_AVOIDED:]


_plans: dict[str, PlanState] = {}


def plan_for(sid: str) -> PlanState:
    """The live plan state for a session (shared, not a copy)."""
    return _plans.setdefault(sid, PlanState())


def forget_plan(sid: str) -> None:
    _plans.pop(sid, None)


def confirm_schedule(plan: PlanState, schedule_id: str) -> Schedule:
    """Same function behind `PUT /api/plan` and the `confirm_schedule` chat tool.
    Only the schedule shown last can be confirmed."""
    last = plan.last_shown
    if last is None:
        raise PlanError("No schedule has been shown yet. Build one first.")
    if schedule_id != last.id:
        raise PlanError(
            f"Only the schedule shown last can be confirmed (id {last.id}). "
            f"{schedule_id!r} is not it."
        )
    plan.confirmed = last
    return last


def _plan(request: Request) -> PlanState:
    return plan_for(professors_api.session_id(request))


@router.get("/plan", response_model=Schedule, responses={404: {"description": "No plan yet"}})
def get_plan(request: Request) -> Schedule:
    confirmed = _plan(request).confirmed
    if confirmed is None:
        raise HTTPException(status_code=404, detail="No plan confirmed yet")
    return confirmed


@router.put(
    "/plan",
    response_model=Schedule,
    responses={409: {"description": "Not the schedule shown last"}},
)
def put_plan(body: ConfirmPlanRequest, request: Request) -> Schedule:
    try:
        return confirm_schedule(_plan(request), body.schedule_id)
    except PlanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/plan", status_code=204, response_class=Response)
def delete_plan(request: Request) -> Response:
    _plan(request).confirmed = None
    return Response(status_code=204)
