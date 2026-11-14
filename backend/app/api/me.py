"""STUB (ENG-01). Real code: DATA-06 (deletes audit, chats, favorites, session)."""

from fastapi import APIRouter, Response

router = APIRouter(prefix="/api", tags=["me"])


@router.delete("/me", status_code=204, response_class=Response)
def delete_me() -> Response:
    return Response(status_code=204)
