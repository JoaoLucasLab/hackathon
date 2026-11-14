"""Audit endpoints (AI-04; `POST /api/audit/sample` from ENG-01).

`POST /api/audit` reads the student's degree audit PDF with Claude and returns the
parsed audit with validation flags. Nothing is stored: the student checks it on the
confirm screen, then `PUT /api/audit` saves the confirmed version.

The PDF never touches the disk:
- the request must declare its size (`Content-Length`) and stay under the limit, so
  the multipart parser keeps the whole file in memory (it would otherwise spill
  files above 1 MB to a temporary file);
- the bytes go to the school's `DegreeAuditParser` once and are dropped;
- nothing about the PDF is logged.
"""

from __future__ import annotations

import os
from datetime import date
from functools import cache

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartParser

from app.api import audit_store, catalog_data, fixture_data, limits
from app.api import chat as chat_api
from app.api.audit_validation import with_flags
from app.contracts import AuditRequirement, DegreeAudit
from app.engine.candidates import remaining_requirements as unmet_requirements
from app.llm.audit import UNREADABLE, AuditParseError
from app.schools.base import get_school

router = APIRouter(prefix="/api", tags=["audit"])

UNIVERSITY_ID = "byui"

# AI-04 settings, read here so this block does not change app/config.py (DATA-01).
# Same names on Render and WSL (.env.example, deploy/wsl/).
FEATURE_AUDIT_UPLOAD = os.environ.get("FEATURE_AUDIT_UPLOAD", "false").strip().lower() == "true"
AUDIT_MAX_AGE_DAYS = int(os.environ.get("AUDIT_MAX_AGE_DAYS", "30"))
# Largest audit PDF accepted. nginx's client_max_body_size (12m) stays above it.
AUDIT_MAX_BYTES = 10 * 1024 * 1024
# Room for the multipart boundary and headers around the file.
FORM_OVERHEAD = 64 * 1024
MAX_REQUEST_BYTES = AUDIT_MAX_BYTES + FORM_OVERHEAD

# Keep every accepted upload in memory: files above `spool_max_size` are written to
# a temporary file. Requests are capped at MAX_REQUEST_BYTES before parsing.
MultiPartParser.spool_max_size = max(MultiPartParser.spool_max_size, MAX_REQUEST_BYTES + 1)

TOO_LARGE = "This file is larger than 10 MB. Upload the degree audit PDF only."
NOT_PDF = "This file is not a PDF. Download your degree audit as a PDF and upload that."


@cache
def known_course_codes() -> set[str]:
    """This semester's course codes, from `catalog_data` (Postgres when
    `DATABASE_URL` is set, else the fixtures)."""
    return {c.code for c in catalog_data.courses()} | {
        s.course_code for s in catalog_data.sections()
    }


def _checked(audit: DegreeAudit) -> DegreeAudit:
    return with_flags(audit, known_course_codes(), date.today(), AUDIT_MAX_AGE_DAYS)


def _store(request: Request, audit: DegreeAudit) -> DegreeAudit:
    """Saves the audit; returns it as stored (any student ID number removed)."""
    sid = audit_store.session_id(request)
    stored = audit_store.put(sid, audit)
    chat_api.use_audit(sid, stored)
    return stored


async def _read_pdf(request: Request) -> bytes:
    length = request.headers.get("content-length")
    if length is None or not length.isdigit():
        raise HTTPException(411, "Send the file with its size (Content-Length).")
    if int(length) > MAX_REQUEST_BYTES:
        raise HTTPException(413, TOO_LARGE)
    form = await request.form(max_files=1, max_fields=1)
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(422, "Attach the PDF as the `file` field.")
        pdf = await upload.read()
    finally:
        await form.close()
    if len(pdf) > AUDIT_MAX_BYTES:
        raise HTTPException(413, TOO_LARGE)
    if not pdf.startswith(b"%PDF-"):
        raise HTTPException(415, NOT_PDF)
    return pdf


@router.post(
    "/audit",
    response_model=DegreeAudit,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {"file": {"type": "string", "format": "binary"}},
                        "required": ["file"],
                    }
                }
            },
        }
    },
    responses={
        404: {"description": "Audit upload is turned off (FEATURE_AUDIT_UPLOAD)."},
        413: {"description": "The file is larger than 10 MB."},
        415: {"description": "The file is not a PDF."},
        422: {"description": "We couldn't read this audit."},
        429: {"description": "More than 5 uploads in an hour."},
    },
    dependencies=[Depends(limits.UPLOAD)],
)
async def upload_audit(request: Request) -> DegreeAudit:
    if not FEATURE_AUDIT_UPLOAD:
        raise HTTPException(404, "Audit upload is turned off.")
    parser = get_school(UNIVERSITY_ID).audit_parser
    if parser is None:
        raise HTTPException(503, UNREADABLE)
    pdf = await _read_pdf(request)
    try:
        audit = await run_in_threadpool(parser.parse, pdf)
    except AuditParseError as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        del pdf
    return _checked(audit)


@router.put("/audit", response_model=DegreeAudit)
def update_audit(body: DegreeAudit, request: Request) -> DegreeAudit:
    """Saves the audit the student confirmed. Flags are recomputed, not trusted."""
    if body.track is None:
        raise HTTPException(422, "Choose your track before saving.")
    return _store(request, _checked(body))


@router.post("/audit/sample", response_model=DegreeAudit)
def sample_audit(request: Request) -> DegreeAudit:
    return _store(request, fixture_data.audit())


@router.get("/requirements/remaining", response_model=list[AuditRequirement])
def remaining_requirements(request: Request) -> list[AuditRequirement]:
    return unmet_requirements(audit_store.get(audit_store.session_id(request)))
