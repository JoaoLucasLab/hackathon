"""The confirmed audit for each session (AI-04).

STUB STORAGE: in memory, keyed by the `sid` cookie, like the chat sessions in
`app/api/chat.py`. Lost on restart. DATA-01 / DATA-06 replace it with a table that
holds the audit JSON encrypted with `DATA_KEY`; keep these three functions as the
interface so callers do not change. Only the validated `DegreeAudit` is kept: no
PDF, no name, no student ID number.
"""

from __future__ import annotations

from fastapi import Request

from app.api import fixture_data
from app.contracts import DegreeAudit

_audits: dict[str, DegreeAudit] = {}


def session_id(request: Request) -> str:
    return request.cookies.get("sid", "local")


def get(sid: str) -> DegreeAudit:
    """The session's confirmed audit, or the sample audit when it has none yet."""
    return _audits.get(sid) or fixture_data.audit()


def put(sid: str, audit: DegreeAudit) -> None:
    _audits[sid] = audit


def forget(sid: str) -> None:
    _audits.pop(sid, None)
