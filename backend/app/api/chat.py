"""Chat and constraints endpoints (AI-02).

Sessions live in memory, keyed by the `sid` cookie. For a signed session cookie,
each turn is also stored (DATA-06): the messages encrypted with DATA_KEY, the
constraints and the favorites (app/db/student_store.py). After a restart the chat
history and constraints come back from there.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Request, Response, Depends
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.api import audit_store, limits
from app.api import professors as professors_api
from app.api import schedules as schedules_api
from app.api import session as session_api
from app.contracts import (
    ChatEvent,
    ChatHistory,
    ChatRequest,
    ChatTurn,
    ConstraintSet,
    DegreeAudit,
)
from app.db import student_store

# Module imports (not names) avoid a circular import: see app/llm/chat.py.
from app.llm import chat as llm_chat
from app.llm import tools as llm_tools

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

# ChatTurn.role -> the `chats.role` column.
_ROLE = {"student": "user", "assistant": "assistant"}

_sessions: dict[str, llm_chat.ChatSession] = {}


def get_session(request: Request) -> llm_chat.ChatSession:
    sid = request.cookies.get("sid", "local")
    if sid not in _sessions:
        # The session's confirmed audit (AI-04), or the sample audit until it has one.
        # The favorite set is shared with the professors API, so stars agree.
        session = llm_chat.ChatSession(
            ctx=llm_tools.ToolContext(
                audit=audit_store.get(sid),
                favorite_professor_ids=professors_api.favorites_for(sid),
                # Shared with /api/plan, so the chat tool and the endpoint agree.
                plan=schedules_api.plan_for(sid),
            )
        )
        student_id = session_api.stored_student(sid)
        if student_id is not None:
            _restore(student_id, session)
        _sessions[sid] = session
    return _sessions[sid]


def _restore(student_id: uuid.UUID, session: llm_chat.ChatSession) -> None:
    """Stored constraints and chat messages, for a session no longer in memory.
    Claude gets the conversation's text back; tool calls are not replayed."""
    try:
        stored = student_store.load_constraints(student_id)
        if stored is not None:
            session.ctx.constraints = ConstraintSet.model_validate(stored)
        session.transcript = [
            ChatTurn.model_validate_json(text)
            for _, text in student_store.chat_messages(student_id)
        ]
    except ValidationError:
        log.warning("chat: stored session no longer matches the contracts; starting fresh")
        session.transcript = []
        return
    history: list[dict[str, Any]] = []
    for asked, reply in zip(session.transcript[::2], session.transcript[1::2], strict=False):
        if asked.role == "student" and reply.role == "assistant" and asked.text and reply.text:
            history += [
                {"role": "user", "content": asked.text},
                {"role": "assistant", "content": reply.text},
            ]
    session.history = history


def _store_turn(student_id: uuid.UUID, session: llm_chat.ChatSession, start: int) -> None:
    """Saves the turn's messages (encrypted), the constraints and the favorites, which
    the chat tools may have changed. A failure is logged and does not break the reply."""
    try:
        turns = session.transcript[start:]
        student_store.add_chat_messages(
            student_id, [(_ROLE[t.role], t.model_dump_json()) for t in turns]
        )
        student_store.save_constraints(
            student_id, session.ctx.constraints.model_dump(mode="json")
        )
        student_store.save_favorites(student_id, session.ctx.favorite_professor_ids)
    except Exception:
        log.exception("chat: could not store the turn")


def use_audit(sid: str, audit: DegreeAudit) -> None:
    """A newly confirmed audit replaces the one an open chat session was using."""
    if sid in _sessions:
        _sessions[sid].ctx.audit = audit


def forget(sid: str) -> None:
    _sessions.pop(sid, None)


def _sse(event: ChatEvent) -> str:
    return f"data: {event.model_dump_json(exclude_none=True)}\n\n"


@router.post(
    "/chat",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "ChatEvent stream"},
        429: {"description": "More than 20 messages in 5 minutes."},
    },
    dependencies=[Depends(limits.CHAT)],
)
def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    session = get_session(request)
    student_id = session_api.stored_student(audit_store.session_id(request))

    def events() -> Iterator[str]:
        start = len(session.transcript)
        try:
            for event in llm_chat.run_turn(session, body.message, llm_chat.claude_caller):
                yield _sse(event)
        finally:
            if student_id is not None:
                _store_turn(student_id, session, start)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/chat/history", response_model=ChatHistory)
def chat_history(request: Request) -> ChatHistory:
    """The conversation as the chat showed it, so a reload keeps it (AI-08)."""
    return ChatHistory(turns=get_session(request).transcript)


@router.delete("/chat/history", status_code=204, response_class=Response)
def clear_chat_history(request: Request) -> Response:
    """Starts a new conversation: drops the transcript, what Claude saw and the rules.
    The audit, favorites and the confirmed plan stay (they live outside the chat)."""
    forget(request.cookies.get("sid", "local"))
    return Response(status_code=204)


@router.get("/constraints", response_model=ConstraintSet)
def get_constraints(request: Request) -> ConstraintSet:
    return get_session(request).ctx.constraints


@router.put("/constraints", response_model=ConstraintSet)
def put_constraints(body: ConstraintSet, request: Request) -> ConstraintSet:
    get_session(request).ctx.constraints = body
    student_id = session_api.stored_student(audit_store.session_id(request))
    if student_id is not None:
        student_store.save_constraints(student_id, body.model_dump(mode="json"))
    return body
