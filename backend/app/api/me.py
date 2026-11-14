"""`DELETE /api/me` (DATA-06): deletes everything the app keeps about this session.

The stored audit, chat messages, constraints, favorites and the `students` row (one
transaction, app/db/student_store.py), and the copies in memory: the chat session,
the confirmed plan, the favorites and the audit. The same cookie then gets 404 from
the endpoints that read student data (`stored_student` in app/api/session.py), and
the response asks the browser to drop the cookie. Deleting twice is not an error.
"""

from fastapi import APIRouter, Request, Response

from app.api import audit_store
from app.api import chat as chat_api
from app.api import professors as professors_api
from app.api import schedules as schedules_api
from app.api import session as session_api
from app.db import student_store

router = APIRouter(prefix="/api", tags=["me"])


@router.delete("/me", status_code=204, response_class=Response)
def delete_me(request: Request) -> Response:
    sid = audit_store.session_id(request)
    student_id = session_api.unsign(sid)
    if student_id is not None:
        student_store.delete_student(student_id)
    chat_api.forget(sid)
    schedules_api.forget_plan(sid)
    professors_api.forget(sid)
    audit_store.forget(sid)
    response = Response(status_code=204)
    session_api.clear_cookie(response)
    return response
