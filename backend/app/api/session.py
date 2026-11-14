"""STUB (ENG-01). Real code: DATA-01 (signed HttpOnly `sid` cookie, students row)."""

from datetime import UTC, datetime

from fastapi import APIRouter

from app.api import fixture_data
from app.contracts import SessionRequest, SessionResponse, Student

router = APIRouter(prefix="/api", tags=["session"])


@router.post("/session", response_model=SessionResponse)
def create_session(body: SessionRequest) -> SessionResponse:
    audit = fixture_data.audit()
    student = Student(
        id="stub-session",
        track=audit.track,
        catalog_year=audit.catalog_year,
        consented_at=datetime.now(UTC) if body.consent else None,
    )
    return SessionResponse(student=student)
