"""Schedule building (ENG-03, ENG-05).

Prerequisites (ENG-04) are checked against the audit: sections the student is not
eligible for are left out with a reason, and conditions to verify become warnings.
School rules (track, religion, waitlist cap, credit range, score weights,
relaxation order) come from the registered school's `SchoolRules`.

The audit is the fixture audit until AI-04 stores the session's own audit, and
sections come from the fixtures until DATA-03 loads them into the database.
"""

from collections.abc import Iterable

from fastapi import APIRouter, Request

from app.api import fixture_data
from app.api import professors as professors_api
from app.contracts import (
    BuildSchedulesRequest,
    BuildSchedulesResponse,
    ConstraintSet,
    DegreeAudit,
)
from app.engine import solver
from app.engine.prereqs.evaluator import PrereqChecker
from app.llm.prereq_fallback import parse_with_fallback
from app.schools.base import default_school

router = APIRouter(prefix="/api", tags=["schedules"])


def prereq_checker(audit: DegreeAudit) -> PrereqChecker:
    """Catalog trees first; text without a tree goes through the parser + Haiku fallback."""
    return PrereqChecker(fixture_data.courses(), audit.courses, parse=parse_with_fallback)


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
        fixture_data.sections(),
        constraints,
        max_results=body.max_results,
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
