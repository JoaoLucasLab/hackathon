"""STUB (ENG-01). Real code: DATA-06 (deletes audit, chats, favorites, session).

AI-08: already clears the session's chat (its conversation is kept so a reload can
restore it) and its confirmed plan, which both live in memory.
"""

from fastapi import APIRouter, Request, Response

from app.api import chat as chat_api
from app.api import professors as professors_api
from app.api import schedules as schedules_api

router = APIRouter(prefix="/api", tags=["me"])


@router.delete("/me", status_code=204, response_class=Response)
def delete_me(request: Request) -> Response:
    sid = professors_api.session_id(request)
    chat_api.forget(sid)
    schedules_api.forget_plan(sid)
    return Response(status_code=204)
