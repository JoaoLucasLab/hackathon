"""Mentor finder endpoints.

Ranking is still the ENG-01 STUB (topic-tag overlap only) until ENG-06 lands in
`engine/mentors.py`; swap `rank_mentors` for it then. AI-05 owns the rest:
topic to existing tags, the reworded reasons and the email draft, all written in
`llm/mentor_text.py` from structured facts only. The app never sends email.
"""

from fastapi import APIRouter, HTTPException, Request

from app.api import audit_store, catalog_data
from app.api import professors as professors_api
from app.contracts import (
    DegreeAudit,
    EmailDraft,
    EmailDraftRequest,
    MentorMatch,
    MentorReason,
    MentorSearchRequest,
    MentorTopicMatch,
    MentorTopicRequest,
    SourceRef,
)
from app.llm import mentor_text

router = APIRouter(prefix="/api", tags=["mentors"])

MAX_MATCHES = 5


def known_tags() -> list[str]:
    """Every topic tag on a professor profile."""
    return sorted({t for p in professors_api.find_professors() for t in p.topic_tags})


def rank_mentors(body: MentorSearchRequest) -> list[MentorMatch]:
    """STUB ranking (ENG-06 replaces it). Structured reasons only, no Claude call."""
    wanted = {t.lower() for t in body.tags}
    matches: list[MentorMatch] = []
    for prof in catalog_data.professors():
        overlap = sorted(wanted & {t.lower() for t in prof.topic_tags})
        if not overlap:
            continue
        interests = next((s for s in prof.sources if s.kind == "interests"), None)
        reasons = [
            MentorReason(
                kind="topic_overlap",
                points=1.0,
                detail=tag,
                source=SourceRef(
                    kind="profile",
                    ref="interests",
                    url=interests.source_url if interests else None,
                ),
            )
            for tag in overlap
        ]
        matches.append(
            MentorMatch(professor=prof, score=sum(r.points for r in reasons), reasons=reasons)
        )
    matches.sort(key=lambda m: (-m.score, m.professor.last_name))
    return matches[:MAX_MATCHES]


@router.post("/mentors/topic", response_model=MentorTopicMatch)
def topic_tags(body: MentorTopicRequest) -> MentorTopicMatch:
    """The student's topic as existing tags. Empty `tags`: ask the student to rephrase."""
    return MentorTopicMatch(topic=body.topic, tags=mentor_text.map_topic(body.topic, known_tags()))


@router.post("/mentors/search", response_model=list[MentorMatch])
def search_mentors(body: MentorSearchRequest, request: Request) -> list[MentorMatch]:
    favorites = professors_api.favorites_for(professors_api.session_id(request))
    matches = mentor_text.describe_matches(rank_mentors(body))
    return [
        m.model_copy(update={"professor": professors_api.marked(m.professor, favorites)})
        for m in matches
    ]


def draft_for(audit: DegreeAudit, professor_id: str, body: EmailDraftRequest) -> EmailDraft:
    """Shared by the endpoint and the `draft_outreach_email` chat tool."""
    prof = catalog_data.professor_by_id().get(professor_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="Professor not found")
    return mentor_text.draft_email(prof, body.goal, body.tags, audit.courses, body.mention_grade)


@router.post("/mentors/{professor_id}/email-draft", response_model=EmailDraft)
def email_draft(professor_id: str, body: EmailDraftRequest, request: Request) -> EmailDraft:
    return draft_for(audit_store.get(audit_store.session_id(request)), professor_id, body)
