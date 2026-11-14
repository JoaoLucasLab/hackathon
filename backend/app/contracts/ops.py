"""Session, chat and request-log payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.contracts.common import Contract
from app.contracts.schedules import Relaxation, Schedule
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


class ChatTurn(Contract):
    """One message of the conversation as the chat shows it (AI-08)."""

    role: Literal["student", "assistant"]
    text: str = ""
    schedule: Schedule | None = Field(
        default=None, description="The one schedule this assistant message shows."
    )
    option: int | None = Field(default=None, ge=1, description='The card label: "Option 2".')
    relaxation: Relaxation | None = Field(
        default=None, description="No schedule fits: the rule to loosen."
    )
    no_schedule: bool = Field(default=False, description="A build ran and no schedule fits.")
    quick_replies: list[str] = Field(default_factory=list)
    error: str | None = None


class ChatHistory(Contract):
    """The session's conversation, so a reload keeps it (AI-08)."""

    turns: list[ChatTurn] = Field(default_factory=list)


class RequestLogEntry(Contract):
    id: int
    at: datetime
    method: str
    url: str
    status: int | None
    cookie_sent: bool
    auth_sent: bool
