"""Professors, their public sources, favorites and mentor matches."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from app.contracts.catalog import CourseCode
from app.contracts.common import Contract


class ProfessorSourceKind(StrEnum):
    education = "education"
    interests = "interests"
    work_experience = "work_experience"
    research = "research"
    biography = "biography"


class ProfessorSource(Contract):
    """One fact from an official public university page."""

    kind: ProfessorSourceKind
    value: str = Field(description="Empty string when the page has no such section.")
    source_url: str
    fetched_at: datetime


class Professor(Contract):
    id: str
    first_name: str
    last_name: str
    middle: str | None = None
    department: str
    title: str | None = Field(default=None, examples=["Professor"])
    bio_summary: str | None = None
    topic_tags: list[str] = Field(default_factory=list)
    lists_undergrad_research: bool | None = Field(
        default=None, description="True only when the profile says so. None: unknown."
    )
    winter_courses: list[CourseCode] = Field(default_factory=list)
    sources: list[ProfessorSource] = Field(default_factory=list)
    rmp_url: str = Field(description="Plain link opened in the student's browser. No ratings.")
    is_favorite: bool = False


class FavoriteProfessor(Contract):
    professor_id: str
    favorite: bool
    updated_at: datetime


class FavoriteUpdate(Contract):
    favorite: bool


class TopicTags(Contract):
    professor_id: str
    tags: list[str] = Field(min_length=3, max_length=8)
    model: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MentorGoal(StrEnum):
    research = "research"
    recommendation_letter = "recommendation letter"
    ta_job = "TA job"
    internship_referral = "internship referral"


class SourceRef(Contract):
    kind: Literal["audit_row", "section", "profile"]
    ref: str = Field(description="Course code, section id, or ProfessorSource kind.")
    url: str | None = None


class MentorReason(Contract):
    kind: Literal["topic_overlap", "took_class", "teaches_winter", "lists_research"]
    points: float
    detail: str = Field(examples=["machine learning"])
    source: SourceRef


class MentorMatch(Contract):
    professor: Professor
    score: float
    reasons: list[MentorReason]
    reason_text: str | None = Field(
        default=None,
        description="Claude's rewording of `reasons` (AI-05). None: show the structured reasons.",
    )


class MentorSearchRequest(Contract):
    goal: MentorGoal
    tags: list[str] = Field(min_length=1)


class MentorTopicRequest(Contract):
    """What the student typed. Mapped to existing topic tags only (AI-05)."""

    topic: str = Field(min_length=1, max_length=200, examples=["AI and neural nets"])


class MentorTopicMatch(Contract):
    topic: str
    tags: list[str] = Field(
        default_factory=list,
        description="Existing professor topic tags only. Empty: ask the student to rephrase.",
    )


class EmailDraftRequest(Contract):
    goal: MentorGoal
    mention_grade: bool = False
    tags: list[str] = Field(
        default_factory=list,
        description="Topic tags from the search. Only the professor's own tags are used.",
    )


class EmailDraft(Contract):
    """A draft the student copies. The app never sends email."""

    professor_id: str
    subject: str
    body: str
    class_named: CourseCode | None = Field(
        default=None, description="The class the student took with this professor, if any."
    )
    written_by: Literal["claude", "template"] = "template"
