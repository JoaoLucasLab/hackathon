"""Schedule building (ENG-03). ENG-05 adds school rules, relaxation and backups.

The audit is the fixture audit until AI-04 stores the session's own audit, and
sections come from the fixtures until DATA-03 loads them into the database.
"""

from fastapi import APIRouter

from app import config
from app.api import fixture_data
from app.contracts import BuildSchedulesRequest, BuildSchedulesResponse, ConstraintSet
from app.engine import solver

router = APIRouter(prefix="/api", tags=["schedules"])


@router.post("/schedules/build", response_model=BuildSchedulesResponse)
def build_schedules(body: BuildSchedulesRequest) -> BuildSchedulesResponse:
    # TODO(AI-02): None should mean the session's saved constraints; the chat tool
    # always sends them, so until the endpoint can see the session it uses defaults.
    constraints = body.constraints or ConstraintSet()
    return solver.build_schedules(
        fixture_data.audit(),
        fixture_data.sections(),
        constraints,
        max_results=body.max_results,
        credit_range=(config.CREDIT_DEFAULT_MIN, config.CREDIT_DEFAULT_MAX),
        time_limit_s=config.SOLVER_TIME_LIMIT_S,
    )
