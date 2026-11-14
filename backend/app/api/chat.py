"""Chat and constraints endpoints (AI-02).

Sessions live in memory, keyed by the `sid` cookie, until DATA-01 adds the
signed session cookie and the database (and DATA-06 encrypts chats at rest).
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api import fixture_data
from app.api import professors as professors_api
from app.contracts import ChatEvent, ChatRequest, ConstraintSet

# Module imports (not names) avoid a circular import: see app/llm/chat.py.
from app.llm import chat as llm_chat
from app.llm import tools as llm_tools

router = APIRouter(prefix="/api", tags=["chat"])

_sessions: dict[str, llm_chat.ChatSession] = {}


def get_session(request: Request) -> llm_chat.ChatSession:
    sid = request.cookies.get("sid", "local")
    if sid not in _sessions:
        # STUB until AI-04: every session starts from the sample audit.
        # The favorite set is shared with the professors API, so stars agree.
        _sessions[sid] = llm_chat.ChatSession(
            ctx=llm_tools.ToolContext(
                audit=fixture_data.audit(),
                favorite_professor_ids=professors_api.favorites_for(sid),
            )
        )
    return _sessions[sid]


def _sse(event: ChatEvent) -> str:
    return f"data: {event.model_dump_json(exclude_none=True)}\n\n"


@router.post(
    "/chat",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "ChatEvent stream"}},
)
def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    session = get_session(request)

    def events() -> Iterator[str]:
        for event in llm_chat.run_turn(session, body.message, llm_chat.claude_caller):
            yield _sse(event)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/constraints", response_model=ConstraintSet)
def get_constraints(request: Request) -> ConstraintSet:
    return get_session(request).ctx.constraints


@router.put("/constraints", response_model=ConstraintSet)
def put_constraints(body: ConstraintSet, request: Request) -> ConstraintSet:
    get_session(request).ctx.constraints = body
    return body
