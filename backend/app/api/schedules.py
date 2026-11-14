"""STUB (ENG-01). Real code: ENG-03 (solver) and ENG-05 (rules, relaxation, backups)."""

from fastapi import APIRouter

from app.api import fixture_data
from app.contracts import (
    BuildSchedulesRequest,
    BuildSchedulesResponse,
    Schedule,
    ScheduledClass,
    ScheduleWhy,
)

router = APIRouter(prefix="/api", tags=["schedules"])


@router.post("/schedules/build", response_model=BuildSchedulesResponse)
def build_schedules(body: BuildSchedulesRequest) -> BuildSchedulesResponse:
    sections = fixture_data.section_by_id()
    requirements = fixture_data.audit().requirements
    schedules: list[Schedule] = []
    for rank, stub in enumerate(fixture_data.stub_schedules()[: body.max_results], start=1):
        classes = [
            ScheduledClass(
                section=sections[sid],
                requirement_ids=[
                    r.id for r in requirements if sections[sid].course_code in r.options
                ],
            )
            for sid in stub.section_ids
        ]
        schedules.append(
            Schedule(
                id=stub.id,
                rank=rank,
                score=float(100 - rank),
                total_credits=sum(c.section.credits for c in classes),
                optimal=True,
                classes=classes,
                why=ScheduleWhy(
                    preferences_met=stub.preferences_met,
                    preferences_missed=stub.preferences_missed,
                ),
            )
        )
    return BuildSchedulesResponse(schedules=schedules)
