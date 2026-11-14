"""STUB (ENG-01). Real code: AI-02 (Claude with tools, streamed)."""

from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.contracts import ChatEvent, ChatRequest, ConstraintSet

router = APIRouter(prefix="/api", tags=["chat"])

_constraints = ConstraintSet()


def _sse(event: ChatEvent) -> str:
    return f"data: {event.model_dump_json(exclude_none=True)}\n\n"


@router.post(
    "/chat",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "ChatEvent stream"}},
)
def chat(body: ChatRequest) -> StreamingResponse:
    def events() -> Iterator[str]:
        stub = "This is a stub reply. The real chat lands in AI-02."
        yield _sse(ChatEvent(type="text", text=stub))
        yield _sse(ChatEvent(type="done"))

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/constraints", response_model=ConstraintSet)
def get_constraints() -> ConstraintSet:
    return _constraints


@router.put("/constraints", response_model=ConstraintSet)
def put_constraints(body: ConstraintSet) -> ConstraintSet:
    # STUB: echoes; AI-02 stores it per session.
    return body
