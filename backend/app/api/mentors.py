"""STUB (ENG-01). Real code: ENG-06 (ranking) and AI-05 (reasons text, email draft).

The stub scores topic-tag overlap only, so the frontend has realistic data.
"""

from fastapi import APIRouter, HTTPException

from app.api import fixture_data
from app.contracts import (
    EmailDraft,
    EmailDraftRequest,
    MentorMatch,
    MentorReason,
    MentorSearchRequest,
    SourceRef,
)

router = APIRouter(prefix="/api", tags=["mentors"])


@router.post("/mentors/search", response_model=list[MentorMatch])
def search_mentors(body: MentorSearchRequest) -> list[MentorMatch]:
    wanted = {t.lower() for t in body.tags}
    matches: list[MentorMatch] = []
    for prof in fixture_data.professors():
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
    return matches[:5]


@router.post("/mentors/{professor_id}/email-draft", response_model=EmailDraft)
def email_draft(professor_id: str, body: EmailDraftRequest) -> EmailDraft:
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
