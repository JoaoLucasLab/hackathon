"""The confirmed audit for each session (AI-04; storage DATA-06).

Kept in memory, keyed by the `sid` cookie, and, for a signed session cookie, in the
`audits` table as JSON encrypted with `DATA_KEY` (app/db/student_store.py), so it
survives a restart. Only the validated `DegreeAudit` is kept: no PDF, no name, and
any student ID number in a text field is removed before it is stored.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.api import fixture_data
from app.api import session as session_api
from app.contracts import DegreeAudit
from app.db import student_store
from app.llm.audit import ID_NUMBER

REMOVED = "[removed]"

_audits: dict[str, DegreeAudit] = {}


def session_id(request: Request) -> str:
    return request.cookies.get("sid", "local")


def _scrubbed(value: Any) -> Any:
    if isinstance(value, str):
        return ID_NUMBER.sub(REMOVED, value)
    if isinstance(value, dict):
        return {k: _scrubbed(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrubbed(v) for v in value]
    return value


def without_id_numbers(audit: DegreeAudit) -> DegreeAudit:
    """The audit with every student ID number in its text replaced by "[removed]".
    The parser already rejects them (app/llm/audit.py); this guards the store."""
    raw = audit.model_dump(mode="json")
    clean = _scrubbed(raw)
    return audit if clean == raw else DegreeAudit.model_validate(clean)


def get(sid: str) -> DegreeAudit:
    """The session's confirmed audit, or the sample audit when it has none yet.
    404 for a deleted session (`stored_student` in app/api/session.py)."""
    if sid in _audits:
        return _audits[sid]
    student_id = session_api.stored_student(sid)
    stored = student_store.latest_audit(student_id) if student_id else None
    if stored is None:
        return fixture_data.audit()
    audit = DegreeAudit.model_validate_json(stored)
    _audits[sid] = audit
    return audit


def put(sid: str, audit: DegreeAudit) -> DegreeAudit:
    """Stores the audit and returns it as stored."""
    audit = without_id_numbers(audit)
    student_id = session_api.stored_student(sid)
    if student_id is not None:
        student_store.save_audit(student_id, audit.model_dump_json())
    _audits[sid] = audit
    return audit


def forget(sid: str) -> None:
    _audits.pop(sid, None)
