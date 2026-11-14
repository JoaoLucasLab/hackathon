"""Mentor ranking (ENG-06). A deterministic score; no Claude call happens here.

The score adds four parts, each times its weight for the goal (weights come from
the school config through `SchoolRules`, never from code):

- topic_overlap: per requested tag that is on the professor's profile,
- took_class: per audit class taught by this professor and passed at the minimum
  grade or better (in-progress classes have no grade yet and do not count),
- teaches_winter: once, when the professor teaches a Winter course whose title
  or description names a requested tag (the first such section is cited),
- lists_research: once, when the profile lists undergraduate research.

Every part that scored becomes a `MentorReason` pointing at its source: an audit
row, a section, or a profile source URL. A professor with no topic overlap and no
shared class is never returned. Ties break by score, then last name (then first
name and id, so the order is always the same).

Audit rows name the professor as printed ("Hale, Marcus" or "Okafor, Ruth A.").
A row is matched to a professor only when the first and last names agree AND the
course links to that professor (they teach it, or it is in their department), so
two professors with the same name in different departments are never merged.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.contracts import (
    AuditCourse,
    Course,
    CourseRecordStatus,
    MentorGoal,
    MentorMatch,
    MentorReason,
    Professor,
    ProfessorSource,
    Section,
    SourceRef,
)
from app.schools.base import SchoolRules

REASON_KINDS = ("topic_overlap", "took_class", "teaches_winter", "lists_research")
# Profile sections that can back a topic tag, most specific first.
_TAG_SOURCE_KINDS = ("interests", "research", "biography")


@dataclass(frozen=True)
class MentorWeights:
    topic_overlap: float = 10
    took_class: float = 15
    teaches_winter: float = 8
    lists_research: float = 0

    @classmethod
    def from_mapping(cls, values: Mapping[str, float]) -> MentorWeights:
        unknown = set(values) - set(REASON_KINDS)
        if unknown:
            raise ValueError(f"unknown mentor weights: {sorted(unknown)}")
        return cls(**{k: float(v) for k, v in values.items()})


@dataclass(frozen=True)
class MentorSettings:
    weights: MentorWeights
    min_grade: str = "B"
    grade_scale: tuple[str, ...] = ("A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F")
    max_results: int = 5

    @classmethod
    def from_rules(cls, rules: SchoolRules, goal: MentorGoal) -> MentorSettings:
        return cls(
            weights=MentorWeights.from_mapping(rules.mentor_weights(goal.value)),
            min_grade=rules.mentor_min_grade(),
            grade_scale=tuple(rules.grade_scale()),
            max_results=rules.mentor_max_results(),
        )

    def passed(self, grade: str | None) -> bool:
        if grade is None:
            return False
        scale = list(self.grade_scale)
        g = grade.strip().upper()
        return g in scale and scale.index(g) <= scale.index(self.min_grade)


# --- normalizing --------------------------------------------------------------------


def norm_tag(tag: str) -> str:
    return " ".join(tag.lower().split())


def _norm_name(name: str) -> str:
    return " ".join(re.sub(r"[^\w\s-]", " ", name.lower()).split())


def split_audit_name(printed: str) -> tuple[str, str] | None:
    """`"Okafor, Ruth A."` or `"Ruth A. Okafor"` -> `("okafor", "ruth")`."""
    if "," in printed:
        last, _, rest = printed.partition(",")
        first = rest.split()[0] if rest.split() else ""
    else:
        parts = printed.split()
        if len(parts) < 2:
            return None
        first, last = parts[0], parts[-1]
    last_n, first_n = _norm_name(last), _norm_name(first)
    if not last_n or not first_n:
        return None
    return last_n, first_n


def _mentions(text: str, tag: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(tag)}(?!\w)", text.lower()) is not None


# --- matching audit rows to professors ----------------------------------------------


def _teaches(prof: Professor, code: str, sections: Sequence[Section]) -> bool:
    return code in prof.winter_courses or any(
        s.course_code == code and prof.id in s.instructor_ids for s in sections
    )


def match_audit_instructor(
    row: AuditCourse,
    professors: Sequence[Professor],
    sections: Sequence[Section],
    course_departments: Mapping[str, str],
) -> Professor | None:
    """The one professor an audit row names, or None if it is missing or ambiguous."""
    if not row.instructor:
        return None
    name = split_audit_name(row.instructor)
    if name is None:
        return None
    last, first = name
    same_name = [
        p
        for p in professors
        if _norm_name(p.last_name) == last and _norm_name(p.first_name).split()[:1] == [first]
    ]
    codes = {row.course_code, *([row.equivalent_of] if row.equivalent_of else [])}
    linked = [
        p
        for p in same_name
        if any(_teaches(p, c, sections) for c in codes)
        or any(course_departments.get(c) == p.department for c in codes)
    ]
    return linked[0] if len(linked) == 1 else None


# --- scoring ------------------------------------------------------------------------


def _tag_source(prof: Professor) -> ProfessorSource | None:
    for kind in _TAG_SOURCE_KINDS:
        for src in prof.sources:
            if src.kind == kind and src.value:
                return src
    return next((s for s in prof.sources if s.kind in _TAG_SOURCE_KINDS), None)


def _research_source(prof: Professor) -> ProfessorSource | None:
    return next((s for s in prof.sources if s.kind == "research"), None) or _tag_source(prof)


def _reasons_for(
    prof: Professor,
    tags: Sequence[str],
    taken: Sequence[AuditCourse],
    sections: Sequence[Section],
    courses: Mapping[str, Course],
    goal: MentorGoal,
    settings: MentorSettings,
) -> list[MentorReason]:
    w = settings.weights
    reasons: list[MentorReason] = []

    prof_tags = {norm_tag(t) for t in prof.topic_tags}
    tag_src = _tag_source(prof)
    for tag in tags:
        if tag in prof_tags and w.topic_overlap:
            reasons.append(
                MentorReason(
                    kind="topic_overlap",
                    points=w.topic_overlap,
                    detail=tag,
                    source=SourceRef(
                        kind="profile",
                        ref=tag_src.kind.value if tag_src else "topic_tags",
                        url=tag_src.source_url if tag_src else None,
                    ),
                )
            )

    if w.took_class:
        for row in taken:
            reasons.append(
                MentorReason(
                    kind="took_class",
                    points=w.took_class,
                    detail=f"{row.course_code} ({row.term}, {row.grade})",
                    source=SourceRef(kind="audit_row", ref=row.course_code),
                )
            )

    if w.teaches_winter and tags:
        for sec in sorted(sections, key=lambda s: s.id):
            if prof.id not in sec.instructor_ids:
                continue
            course = courses.get(sec.course_code)
            text = f"{sec.title} {course.title if course else ''} "
            text += course.description if course else ""
            hit = next((t for t in tags if _mentions(text, t)), None)
            if hit is None:
                continue
            reasons.append(
                MentorReason(
                    kind="teaches_winter",
                    points=w.teaches_winter,
                    detail=f"{sec.course_code} {sec.title} ({hit})",
                    source=SourceRef(kind="section", ref=sec.id, url=sec.source_url),
                )
            )
            break

    if goal is MentorGoal.research and w.lists_research and prof.lists_undergrad_research:
        src = _research_source(prof)
        reasons.append(
            MentorReason(
                kind="lists_research",
                points=w.lists_research,
                detail="lists undergraduate research",
                source=SourceRef(
                    kind="profile",
                    ref=src.kind.value if src else "research",
                    url=src.source_url if src else None,
                ),
            )
        )
    return reasons


def rank_mentors(
    goal: MentorGoal,
    tags: Iterable[str],
    professors: Sequence[Professor],
    audit_courses: Sequence[AuditCourse],
    sections: Sequence[Section],
    courses: Sequence[Course],
    settings: MentorSettings,
) -> list[MentorMatch]:
    """Professors ranked for a goal and topic tags, best first, at most `max_results`."""
    wanted = sorted({norm_tag(t) for t in tags if norm_tag(t)})
    course_map = {c.code: c for c in courses}
    departments = {c.code: c.department for c in courses}
    for s in sections:
        departments.setdefault(s.course_code, s.department)

    taken: dict[str, list[AuditCourse]] = {}
    for row in audit_courses:
        if row.status is CourseRecordStatus.in_progress or not settings.passed(row.grade):
            continue
        prof = match_audit_instructor(row, professors, sections, departments)
        if prof is not None:
            taken.setdefault(prof.id, []).append(row)

    matches: list[MentorMatch] = []
    for prof in professors:
        reasons = _reasons_for(
            prof, wanted, taken.get(prof.id, []), sections, course_map, goal, settings
        )
        if not any(r.kind in ("topic_overlap", "took_class") for r in reasons):
            continue
        matches.append(
            MentorMatch(professor=prof, score=sum(r.points for r in reasons), reasons=reasons)
        )
    matches.sort(
        key=lambda m: (-m.score, m.professor.last_name, m.professor.first_name, m.professor.id)
    )
    return matches[: settings.max_results]
