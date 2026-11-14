"""Mentor search (ENG-06) and email drafts (STUB until AI-05).

Ranking is `engine/mentors.py`: a deterministic score with structured reasons. The
student free text (reworded reasons, the email) is AI-05's job in `llm/`.

Professors and sections come from the fixtures until DATA-05 / DATA-03 load them
into the database; the audit is the session's confirmed audit (or the sample).
"""

from collections.abc import Iterable

from fastapi import APIRouter, HTTPException, Request

from app.api import audit_store, fixture_data
from app.api import professors as professors_api
from app.contracts import (
    DegreeAudit,
    EmailDraft,
    EmailDraftRequest,
    MentorMatch,
    MentorSearchRequest,
)
from app.engine.mentors import MentorSettings, rank_mentors
from app.schools.base import default_school

router = APIRouter(prefix="/api", tags=["mentors"])


def find_mentors(
    body: MentorSearchRequest, audit: DegreeAudit, favorite_professor_ids: Iterable[str] = ()
) -> list[MentorMatch]:
    """Same function behind the endpoint and the `find_mentors` chat tool."""
    rules = default_school().rules
    if rules is None:
        raise RuntimeError("The registered school has no rules")
    matches = rank_mentors(
        body.goal,
        body.tags,
        fixture_data.professors(),
        audit.courses,
        fixture_data.sections(),
        fixture_data.courses(),
        MentorSettings.from_rules(rules, body.goal),
    )
    favorites = set(favorite_professor_ids)
    return [
        m.model_copy(
            update={
                "professor": m.professor.model_copy(
                    update={"is_favorite": m.professor.id in favorites}
                )
            }
        )
        for m in matches
    ]


@router.post("/mentors/search", response_model=list[MentorMatch])
def search_mentors(body: MentorSearchRequest, request: Request) -> list[MentorMatch]:
    audit = audit_store.get(audit_store.session_id(request))
    favorites = professors_api.favorites_for(professors_api.session_id(request))
    return find_mentors(body, audit, favorites)


@router.post("/mentors/{professor_id}/email-draft", response_model=EmailDraft)
def email_draft(professor_id: str, body: EmailDraftRequest) -> EmailDraft:
    # STUB (ENG-01). AI-05 writes the real draft in `llm/`. (A comment, not a
    # docstring: FastAPI would put a docstring in the OpenAPI spec.)
    prof = fixture_data.professor_by_id().get(professor_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="Professor not found")
    return EmailDraft(
        professor_id=prof.id,
        subject=f"Question about {body.goal.value}",
        body=(
            f"Dear Professor {prof.last_name},\n\n"
            f"I am interested in {body.goal.value} opportunities related to your work. "
            "Would you have a few minutes to talk this semester?\n\nThank you,\n"
        ),
    )
