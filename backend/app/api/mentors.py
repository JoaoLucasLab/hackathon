"""Mentor finder endpoints.

Ranking is ENG-06's `engine/mentors.py`: a deterministic score with structured
reasons. AI-05 owns the rest: topic to existing tags, the reworded reasons and the
email draft, all written in `llm/mentor_text.py` from structured facts only. The
app never sends email.
"""

from collections.abc import Iterable

from fastapi import APIRouter, HTTPException, Request

from app.api import audit_store, catalog_data
from app.api import professors as professors_api
from app.contracts import (
    DegreeAudit,
    EmailDraft,
    EmailDraftRequest,
    MentorMatch,
    MentorSearchRequest,
    MentorTopicMatch,
    MentorTopicRequest,
)
from app.engine.mentors import MentorSettings, rank_mentors
from app.llm import mentor_text
from app.schools.base import default_school

router = APIRouter(prefix="/api", tags=["mentors"])


def known_tags() -> list[str]:
    """Every topic tag on a professor profile."""
    return sorted({t for p in professors_api.find_professors() for t in p.topic_tags})


def find_mentors(
    body: MentorSearchRequest, audit: DegreeAudit, favorite_professor_ids: Iterable[str] = ()
) -> list[MentorMatch]:
    """Same function behind the endpoint and the `find_mentors` chat tool.

    Structured reasons only, no Claude call; the endpoint rewords them for students.
    """
    rules = default_school().rules
    if rules is None:
        raise RuntimeError("The registered school has no rules")
    matches = rank_mentors(
        body.goal,
        body.tags,
        catalog_data.professors(),
        audit.courses,
        catalog_data.sections(),
        catalog_data.courses(),
        MentorSettings.from_rules(rules, body.goal),
    )
    favorites = set(favorite_professor_ids)
    return [
        m.model_copy(update={"professor": professors_api.marked(m.professor, favorites)})
        for m in matches
    ]


@router.post("/mentors/topic", response_model=MentorTopicMatch)
def topic_tags(body: MentorTopicRequest) -> MentorTopicMatch:
    """The student's topic as existing tags. Empty `tags`: ask the student to rephrase."""
    return MentorTopicMatch(topic=body.topic, tags=mentor_text.map_topic(body.topic, known_tags()))


@router.post("/mentors/search", response_model=list[MentorMatch])
def search_mentors(body: MentorSearchRequest, request: Request) -> list[MentorMatch]:
    audit = audit_store.get(audit_store.session_id(request))
    favorites = professors_api.favorites_for(professors_api.session_id(request))
    return mentor_text.describe_matches(find_mentors(body, audit, favorites))


def draft_for(audit: DegreeAudit, professor_id: str, body: EmailDraftRequest) -> EmailDraft:
    """Shared by the endpoint and the `draft_outreach_email` chat tool."""
    prof = catalog_data.professor_by_id().get(professor_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="Professor not found")
    return mentor_text.draft_email(prof, body.goal, body.tags, audit.courses, body.mention_grade)


@router.post("/mentors/{professor_id}/email-draft", response_model=EmailDraft)
def email_draft(professor_id: str, body: EmailDraftRequest, request: Request) -> EmailDraft:
    return draft_for(audit_store.get(audit_store.session_id(request)), professor_id, body)
