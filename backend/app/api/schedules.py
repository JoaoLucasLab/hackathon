"""Schedule building (ENG-03). ENG-05 adds school rules, relaxation and backups.

Prerequisites (ENG-04) are checked against the audit: sections the student is not
eligible for are left out with a reason, and conditions to verify become warnings.

The audit is the fixture audit until AI-04 stores the session's own audit, and
sections come from the fixtures until DATA-03 loads them into the database.
"""

from fastapi import APIRouter

from app import config
from app.api import fixture_data
from app.contracts import (
    BuildSchedulesRequest,
    BuildSchedulesResponse,
    ConstraintSet,
    DegreeAudit,
)
from app.engine import solver
from app.engine.prereqs.evaluator import PrereqChecker
from app.llm.prereq_fallback import parse_with_fallback

router = APIRouter(prefix="/api", tags=["schedules"])


def prereq_checker(audit: DegreeAudit) -> PrereqChecker:
    """Catalog trees first; text without a tree goes through the parser + Haiku fallback."""
    return PrereqChecker(fixture_data.courses(), audit.courses, parse=parse_with_fallback)


@router.post("/schedules/build", response_model=BuildSchedulesResponse)
def build_schedules(body: BuildSchedulesRequest) -> BuildSchedulesResponse:
    # TODO(AI-02): None should mean the session's saved constraints; the chat tool
    # always sends them, so until the endpoint can see the session it uses defaults.
    constraints = body.constraints or ConstraintSet()
    audit = fixture_data.audit()
    return solver.build_schedules(
        audit,
        fixture_data.sections(),
        constraints,
        max_results=body.max_results,
        credit_range=(config.CREDIT_DEFAULT_MIN, config.CREDIT_DEFAULT_MAX),
        time_limit_s=config.SOLVER_TIME_LIMIT_S,
        prereqs=prereq_checker(audit),
    )
