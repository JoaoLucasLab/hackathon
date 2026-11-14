"""Anonymous sessions (DATA-01): a signed, HttpOnly `sid` cookie -> one `students` row.

The cookie holds the student's random id and an HMAC of it made with
`SESSION_SECRET`, so a changed or made-up cookie is ignored and gets a new
session. Nothing else identifies the student: no name, email or password is
asked anywhere.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request, Response

from app import config
from app.contracts import SessionRequest, SessionResponse, Student
from app.db import engine
from app.db.models import Student as StudentRow

router = APIRouter(prefix="/api", tags=["session"])

COOKIE = "sid"
MAX_AGE_S = 90 * 24 * 60 * 60

# Without SESSION_SECRET (local dev, tests) a random key: sessions end on restart.
_secret = config.SESSION_SECRET.encode() or secrets.token_bytes(32)
_SAMESITE: dict[str, Literal["lax", "strict", "none"]] = {
    "lax": "lax",
    "strict": "strict",
    "none": "none",
}
_samesite = _SAMESITE.get(config.COOKIE_SAMESITE, "lax")


def sign(student_id: str) -> str:
    mac = hmac.new(_secret, student_id.encode(), hashlib.sha256).digest()
    return f"{student_id}.{base64.urlsafe_b64encode(mac).rstrip(b'=').decode()}"


def unsign(value: str | None) -> uuid.UUID | None:
    """The student id in a cookie, or None when the cookie is missing or not ours."""
    if not value or "." not in value:
        return None
    student_id = value.rpartition(".")[0]
    if not hmac.compare_digest(sign(student_id), value):
        return None
    try:
        return uuid.UUID(student_id)
    except ValueError:
        return None


def get_or_create(student_id: uuid.UUID | None, *, consent: bool = False) -> StudentRow:
    """The student with this id, or a new row when the id is None or unknown.
    Marks the row as seen now, and records the consent time the first time `consent` is set."""
    now = datetime.now(UTC)
    with engine.session() as db:
        student = db.get(StudentRow, student_id) if student_id else None
        if student is None:
            student = StudentRow(id=uuid.uuid4(), created_at=now)
            db.add(student)
        student.last_seen_at = now
        if consent and student.consented_at is None:
            student.consented_at = now
        db.commit()
        return student


def current_student(request: Request, response: Response, *, consent: bool = False) -> StudentRow:
    """The request's student. A request without a valid cookie gets a new row and cookie."""
    cookie_id = unsign(request.cookies.get(COOKIE))
    student = get_or_create(cookie_id, consent=consent)
    if student.id != cookie_id:
        response.set_cookie(
            COOKIE,
            sign(str(student.id)),
            max_age=MAX_AGE_S,
            path="/",
            secure=True,
            httponly=True,
            samesite=_samesite,
        )
    return student


@router.post("/session", response_model=SessionResponse)
def create_session(body: SessionRequest, request: Request, response: Response) -> SessionResponse:
    row = current_student(request, response, consent=body.consent)
    student = Student(
        id=str(row.id),
        track=row.track,
        catalog_year=row.catalog_year,
        consented_at=row.consented_at,
    )
    return SessionResponse(student=student)
