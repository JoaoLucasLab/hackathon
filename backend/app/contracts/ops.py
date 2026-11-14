"""Session, chat and request-log payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.contracts.common import Contract
from app.contracts.students import Student


class SessionRequest(Contract):
    consent: bool = Field(description="The student checked the consent box.")


class SessionResponse(Contract):
    student: Student


class ChatRequest(Contract):
    message: str = Field(min_length=1, max_length=4000)


class ChatEvent(Contract):
    """One server-sent event in a streamed chat reply."""

    type: Literal["text", "tool_call", "tool_result", "done", "error"]
    text: str | None = None
    tool: str | None = None
    data: dict[str, Any] | None = None


class RequestLogEntry(Contract):
    id: int
    at: datetime
    method: str
    url: str
    status: int | None
    cookie_sent: bool
    auth_sent: bool
