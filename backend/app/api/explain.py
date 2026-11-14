"""Why this schedule" endpoint (AI-03).

Kept apart from `schedules.py` (ENG-03/ENG-05 own the solver endpoint). The
client sends back a schedule exactly as `/api/schedules/build` returned it; the
text is written only from that schedule's structured facts.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api import catalog_data
from app.api import chat as chat_api
from app.contracts import ExplainScheduleRequest, ScheduleExplanation
from app.llm import explain as llm_explain

router = APIRouter(prefix="/api", tags=["schedules"])


@router.post("/schedules/explain", response_model=ScheduleExplanation)
def explain_schedule(body: ExplainScheduleRequest, request: Request) -> ScheduleExplanation:
    audit = chat_api.get_session(request).ctx.audit
    requirement_names = {r.id: r.name for r in audit.requirements}
    professor_names = {p.id: f"{p.first_name} {p.last_name}" for p in catalog_data.professors()}
    return llm_explain.explain_schedule(body.schedule, requirement_names, professor_names)
