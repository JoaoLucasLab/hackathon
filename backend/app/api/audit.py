"""Audit endpoints.

`POST /api/audit/sample` is real (ENG-01). Upload and update are STUBS until AI-04.
"""

from fastapi import APIRouter, UploadFile

from app.api import fixture_data
from app.contracts import AuditRequirement, DegreeAudit
from app.engine.candidates import remaining_requirements as unmet_requirements

router = APIRouter(prefix="/api", tags=["audit"])


@router.post("/audit", response_model=DegreeAudit)
async def upload_audit(file: UploadFile) -> DegreeAudit:
    # STUB: the real version (AI-04) sends the PDF to Claude once and never stores it.
    await file.close()
    return fixture_data.audit()


@router.put("/audit", response_model=DegreeAudit)
def update_audit(body: DegreeAudit) -> DegreeAudit:
    # STUB: echoes the confirmed audit; AI-04 stores it encrypted.
    return body


@router.post("/audit/sample", response_model=DegreeAudit)
def sample_audit() -> DegreeAudit:
    return fixture_data.audit()


@router.get("/requirements/remaining", response_model=list[AuditRequirement])
def remaining_requirements() -> list[AuditRequirement]:
    # Fixture audit until AI-04 stores the session's own audit.
    return unmet_requirements(fixture_data.audit())
