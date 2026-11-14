"""STUB (ENG-01). Real code: DATA-02 (reads the request_log table)."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.contracts import RequestLogEntry

router = APIRouter(prefix="/admin", tags=["admin"])

_CSV_HEADER = ",".join(RequestLogEntry.model_fields) + "\n"


@router.get("/request-log", response_class=HTMLResponse)
def request_log() -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><title>Request log</title><p>0 outbound requests: running on fixtures</p>"
    )


@router.get("/request-log.csv", response_class=PlainTextResponse)
def request_log_csv() -> PlainTextResponse:
    return PlainTextResponse(
        _CSV_HEADER,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="request-log.csv"'},
    )
