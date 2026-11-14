"""Mentor finder text (AI-05): topic to tags, reasons, outreach email.

Claude writes three things here, each from structured facts only:

- `map_topic`: what the student typed, mapped to topic tags that already exist on
  professor profiles. Unknown tags are rejected (one retry), then dropped. No tag
  fits: an empty list, and the screen asks the student to rephrase.
- `describe_matches`: one sentence per mentor match, reworded from the ranking's
  structured `MentorReason`s. A sentence that names a course, topic or professor
  outside that professor's reasons is rejected.
- `draft_email`: a short draft the student copies. It names the class the student
  took with the professor when there is one, and the grade only when the student
  asked for it (otherwise the grade is never sent to Claude). The app never sends
  email.

Each call validates the JSON with Pydantic and the grounding checks; a failure is
retried once with the error. If the retry fails, or Claude is not configured, the
result falls back to text built from the same facts without Claude (the cut-list
fallback: structured reasons and a fixed email template).

Results are cached by a SHA-256 of the facts and the model name (in memory until
DATA-01 adds `llm_cache`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterable
from typing import Any

import anthropic
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.contracts import (
    AuditCourse,
    CourseRecordStatus,
    EmailDraft,
    MentorGoal,
    MentorMatch,
    Professor,
)
from app.llm import client

log = logging.getLogger(__name__)

MAX_TOKENS = 4000
EMAIL_MAX_WORDS = 180
REASON_MAX_CHARS = 300

COURSE_CODE = re.compile(r"\b([A-Z]{2,4}) ?(\d{3}[A-Z]?)\b")
PROMISES = re.compile(r"guarantee|\bpromise|\bsecured?\b|will (?:hire|accept|admit)", re.IGNORECASE)
GRADE_WORD = re.compile(r"\bgrades?\b|\bearned an? [A-F]\b|\bgot an? [A-F]\b", re.IGNORECASE)

# A Caller takes the request parameters and returns the reply's JSON text, or None
# when Claude declined. Tests pass a recorded one; nothing here hits the API itself.
Caller = Callable[[dict[str, Any]], str | None]


class NotGroundedError(ValueError):
    """The text names something outside the facts it was given."""


_cache: dict[str, Any] = {}


def course_codes_in(text: str) -> set[str]:
    return {f"{subject} {number}" for subject, number in COURSE_CODE.findall(text)}


def _key(kind: str, model: str, facts: Any) -> str:
    raw = json.dumps({"kind": kind, "model": model, "facts": facts}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _params(
    prompt: str, model: str, facts: Any, schema: dict[str, Any], history: list[dict[str, Any]]
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": client.cached_system(prompt),
        "messages": [{"role": "user", "content": json.dumps(facts, sort_keys=True)}, *history],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": schema}},
    }
    if model == client.chat_model():
        params.update(client.chat_fallback_options())
    return params


def _api() -> anthropic.Anthropic:
    """Seam for tests: conftest makes this raise, so no test calls Claude live."""
    return client.get_client()


def claude_caller(params: dict[str, Any]) -> str | None:
    """The real Caller. Returns None on a refusal or a cut-off reply."""
    api = _api()
    if "betas" in params:
        message = api.beta.messages.create(**params)
    else:
        message = api.messages.create(**params)
    if message.stop_reason in ("refusal", "max_tokens"):
        log.warning("mentor_text: no answer, stop_reason=%s", message.stop_reason)
        return None
    return next((b.text for b in message.content if b.type == "text"), None)


def _ask[T: BaseModel](
    *,
    kind: str,
    prompt: str,
    model: str,
    facts: Any,
    schema: dict[str, Any],
    answer_type: type[T],
    check: Callable[[T], None],
    caller: Caller,
) -> T | None:
    """One Claude call with validation, one retry with the error, then None."""
    history: list[dict[str, Any]] = []
    for _attempt in range(2):
        try:
            text = caller(_params(prompt, model, facts, schema, history))
        except client.ClaudeNotConfiguredError:
            log.info("mentor_text: ANTHROPIC_API_KEY is not set; using the %s fallback", kind)
            return None
        except anthropic.APIError as exc:
            # Only the error type and status: never the request body.
            log.warning(
                "mentor_text: Claude API error %s (status %s) on %s",
                type(exc).__name__,
                getattr(exc, "status_code", None),
                kind,
            )
            return None
        if text is None:
            return None
        try:
            answer = answer_type.model_validate_json(text)
            check(answer)
        except (ValidationError, NotGroundedError) as exc:
            log.info("mentor_text: %s answer rejected: %s", kind, type(exc).__name__)
            history += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That answer was rejected: {exc}. Try again."},
            ]
            continue
        return answer
    log.warning("mentor_text: two %s answers failed validation", kind)
    return None


# --- Topic to existing tags ----------------------------------------------------------


class _TopicAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags: list[str] = Field(max_length=8)


def fallback_tags(topic: str, known_tags: Iterable[str]) -> list[str]:
    """Without Claude: existing tags that appear in the topic, or contain it."""
    text = topic.strip().lower()
    found = [
        tag for tag in known_tags if tag.lower() in text or (len(text) >= 3 and text in tag.lower())
    ]
    return sorted(set(found))[:8]


def map_topic(topic: str, known_tags: Iterable[str], caller: Caller = claude_caller) -> list[str]:
    """The student's topic as existing tags only. Empty: ask the student to rephrase."""
    known = sorted({t for t in known_tags if t})
    by_lower = {t.lower(): t for t in known}
    facts = {"topic": topic.strip(), "known_tags": known}
    key = _key("topic", client.bulk_model(), facts)
    if key in _cache:
        return list(_cache[key])

    def check(answer: _TopicAnswer) -> None:
        unknown = [t for t in answer.tags if t.lower() not in by_lower]
        if unknown:
            raise NotGroundedError(
                f"{', '.join(unknown)} is not in known_tags. Use only tags from known_tags, "
                "or an empty list."
            )

    answer = _ask(
        kind="topic",
        prompt="mentor_topic",
        model=client.bulk_model(),
        facts=facts,
        schema=_schema({"tags": {"type": "array", "items": {"type": "string"}}}),
        answer_type=_TopicAnswer,
        check=check,
        caller=caller,
    )
    if answer is None:
        return fallback_tags(topic, known)
    tags = sorted({by_lower[t.lower()] for t in answer.tags})
    _cache[key] = tags
    return tags


# --- Reasons for each match ----------------------------------------------------------


class _ReasonItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    professor_id: str
    text: str = Field(min_length=1, max_length=REASON_MAX_CHARS)


class _ReasonsAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[_ReasonItem]


def _name(p: Professor) -> str:
    return f"{p.first_name} {p.last_name}"


def match_facts(match: MentorMatch) -> dict[str, Any]:
    """Only the structured reasons and the professor's public name and department."""
    return {
        "professor_id": match.professor.id,
        "name": _name(match.professor),
        "department": match.professor.department,
        "reasons": [
            {
                "kind": r.kind,
                "detail": r.detail,
                "course": r.source.ref if r.source.kind in ("audit_row", "section") else None,
            }
            for r in match.reasons
        ],
    }


def allowed_course_codes(match: MentorMatch) -> set[str]:
    codes: set[str] = set()
    for r in match.reasons:
        codes |= course_codes_in(r.detail)
        if r.source.kind in ("audit_row", "section"):
            codes |= course_codes_in(r.source.ref)
    return codes


def check_reason_text(text: str, match: MentorMatch, others: Iterable[Professor]) -> None:
    """Raises NotGroundedError when `text` states something outside `match.reasons`."""
    problems: list[str] = []
    extra = sorted(course_codes_in(text) - allowed_course_codes(match))
    if extra:
        problems.append(f"names {', '.join(extra)}, which is not in the reasons")
    details = " ".join(r.detail.lower() for r in match.reasons)
    lowered = text.lower()
    unlisted = sorted(
        t for t in match.professor.topic_tags if t.lower() in lowered and t.lower() not in details
    )
    if unlisted:
        problems.append(f"mentions {', '.join(unlisted)}, which is not one of the reasons")
    named = sorted(
        _name(p)
        for p in others
        if p.id != match.professor.id and re.search(rf"\b{re.escape(p.last_name)}\b", text)
    )
    if named:
        problems.append(f"names another professor ({', '.join(named)})")
    if PROMISES.search(text):
        problems.append("promises an outcome")
    if problems:
        raise NotGroundedError(f"The text for {match.professor.id} " + "; ".join(problems) + ".")


def describe_matches(
    matches: list[MentorMatch], caller: Caller = claude_caller
) -> list[MentorMatch]:
    """Adds `reason_text` to each match. A match whose text fails keeps None, so the
    screen shows its structured reasons instead."""
    if not matches:
        return matches
    facts = {"matches": [match_facts(m) for m in matches]}
    key = _key("reasons", client.chat_model(), facts)
    texts: dict[str, str] | None = _cache.get(key)
    if texts is None:
        professors = [m.professor for m in matches]
        by_id = {m.professor.id: m for m in matches}

        def check(answer: _ReasonsAnswer) -> None:
            ids = [i.professor_id for i in answer.items]
            if sorted(ids) != sorted(by_id):
                raise NotGroundedError(
                    "Return exactly one item per professor_id in matches: "
                    + ", ".join(sorted(by_id))
                )
            errors = []
            for item in answer.items:
                try:
                    check_reason_text(item.text, by_id[item.professor_id], professors)
                except NotGroundedError as exc:
                    errors.append(str(exc))
            if errors:
                raise NotGroundedError(" ".join(errors))

        answer = _ask(
            kind="reasons",
            prompt="mentor_reasons",
            model=client.chat_model(),
            facts=facts,
            schema=_schema(
                {
                    "items": {
                        "type": "array",
                        "items": _schema(
                            {"professor_id": {"type": "string"}, "text": {"type": "string"}}
                        ),
                    }
                }
            ),
            answer_type=_ReasonsAnswer,
            check=check,
            caller=caller,
        )
        if answer is None:
            return matches
        texts = {i.professor_id: i.text.strip() for i in answer.items}
        _cache[key] = texts
    return [m.model_copy(update={"reason_text": texts.get(m.professor.id)}) for m in matches]


# --- Outreach email ------------------------------------------------------------------

GOAL_ASKS: dict[MentorGoal, str] = {
    MentorGoal.research: (
        "I would like to ask whether you have room for an undergraduate student to help "
        "with research"
    ),
    MentorGoal.recommendation_letter: (
        "I would like to ask whether you would consider writing a recommendation letter for me"
    ),
    MentorGoal.ta_job: "I would like to ask whether you are looking for a teaching assistant",
    MentorGoal.internship_referral: (
        "I am looking for an internship and would value your advice, or a referral if you "
        "know of an opening"
    ),
}

GOAL_SUBJECTS: dict[MentorGoal, str] = {
    MentorGoal.research: "Undergraduate research",
    MentorGoal.recommendation_letter: "Recommendation letter request",
    MentorGoal.ta_job: "Teaching assistant position",
    MentorGoal.internship_referral: "Internship advice",
}

SIGN_OFF = "[Your name]"


def _norm(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.lower())


def _subject_of(code: str) -> str:
    return code.split(" ", 1)[0]


def classes_with(professor: Professor, courses: Iterable[AuditCourse]) -> list[AuditCourse]:
    """Audit rows taught by this professor: same last and first name (and middle
    initial when both show one), and a subject this professor teaches. Two people
    with the same name in different departments are never merged."""
    subjects = {_subject_of(c) for c in professor.winter_courses}
    found = []
    for course in courses:
        if not course.instructor or "," not in course.instructor:
            continue
        last, _, rest = course.instructor.partition(",")
        parts = rest.split()
        if _norm(last) != _norm(professor.last_name) or not parts:
            continue
        if _norm(parts[0]) != _norm(professor.first_name):
            continue
        middle = _norm(parts[1])[:1] if len(parts) > 1 else ""
        if middle and professor.middle and middle != _norm(professor.middle)[:1]:
            continue
        if subjects and _subject_of(course.course_code) not in subjects:
            continue
        found.append(course)
    return found


def pick_class(professor: Professor, courses: Iterable[AuditCourse]) -> AuditCourse | None:
    """The class to name in the email: a finished one first, then one in progress."""
    taken = classes_with(professor, courses)
    done = [c for c in taken if c.status == CourseRecordStatus.complete]
    pool = done or taken
    return pool[-1] if pool else None


def email_facts(
    professor: Professor,
    goal: MentorGoal,
    tags: list[str],
    taken: AuditCourse | None,
    mention_grade: bool,
) -> dict[str, Any]:
    """What Claude may use. No student name or ID; the grade only when asked for."""
    own = {t.lower(): t for t in professor.topic_tags}
    topics = sorted({own[t.lower()] for t in tags if t.lower() in own})
    taken_facts = None
    if taken is not None:
        taken_facts = {
            "course_code": taken.course_code,
            "title": taken.title,
            "term": taken.term,
            "in_progress": taken.status != CourseRecordStatus.complete,
        }
        if mention_grade and taken.grade and taken.status == CourseRecordStatus.complete:
            taken_facts["grade"] = taken.grade
    return {
        "goal": goal.value,
        "professor": {
            "last_name": professor.last_name,
            "title": professor.title,
            "department": professor.department,
        },
        "topics": topics,
        "class_taken": taken_facts,
        "sign_off": SIGN_OFF,
    }


def word_count(text: str) -> int:
    return len(text.split())


def check_email(subject: str, body: str, facts: dict[str, Any]) -> None:
    problems: list[str] = []
    if word_count(body) >= EMAIL_MAX_WORDS:
        problems.append(f"the body has {word_count(body)} words; keep it under {EMAIL_MAX_WORDS}")
    taken = facts["class_taken"]
    allowed = {taken["course_code"]} if taken else set()
    extra = sorted(course_codes_in(f"{subject} {body}") - allowed)
    if extra:
        problems.append(f"it names {', '.join(extra)}; name only the class in class_taken")
    if taken and taken["course_code"] not in course_codes_in(body):
        problems.append(f"it must name {taken['course_code']} from class_taken")
    if not (taken and "grade" in taken) and GRADE_WORD.search(f"{subject} {body}"):
        problems.append("it mentions a grade; leave grades out")
    if PROMISES.search(body):
        problems.append("it promises an outcome")
    if problems:
        raise NotGroundedError("The draft was rejected: " + "; ".join(problems) + ".")


class _EmailAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=2000)


def template_email(professor: Professor, facts: dict[str, Any]) -> tuple[str, str]:
    """The fixed template, written from the same facts as the Claude draft."""
    goal = MentorGoal(facts["goal"])
    taken = facts["class_taken"]
    lines = [f"Dear Professor {professor.last_name},", ""]
    intro = f"My name is {SIGN_OFF}, and I am a student at BYU-Idaho."
    if taken and taken["in_progress"]:
        intro += f" I am taking {taken['course_code']} ({taken['title']}) with you this semester."
    elif taken:
        intro += f" I took {taken['course_code']} ({taken['title']}) with you in {taken['term']}"
        intro += f" and earned a {taken['grade']}." if "grade" in taken else "."
    paragraph = [intro]
    if facts["topics"]:
        paragraph.append(
            f"I am interested in {' and '.join(facts['topics'][:2])}, which I saw is part "
            "of your work."
        )
    paragraph.append(f"{GOAL_ASKS[goal]}.")
    paragraph.append("Would you have 15 minutes to talk in the coming weeks?")
    lines += [" ".join(paragraph), "", "Thank you for your time,", SIGN_OFF]
    subject = GOAL_SUBJECTS[goal]
    if taken:
        subject += f" from a {taken['course_code']} student"
    return subject, "\n".join(lines)


def draft_email(
    professor: Professor,
    goal: MentorGoal,
    tags: list[str],
    courses: Iterable[AuditCourse],
    mention_grade: bool,
    caller: Caller = claude_caller,
) -> EmailDraft:
    taken = pick_class(professor, courses)
    facts = email_facts(professor, goal, tags, taken, mention_grade)
    class_named = taken.course_code if taken else None
    key = _key("email", client.chat_model(), {"id": professor.id, **facts})
    if key in _cache:
        return _cache[key]  # type: ignore[no-any-return]

    answer = _ask(
        kind="email",
        prompt="mentor_email",
        model=client.chat_model(),
        facts=facts,
        schema=_schema({"subject": {"type": "string"}, "body": {"type": "string"}}),
        answer_type=_EmailAnswer,
        check=lambda a: check_email(a.subject, a.body, facts),
        caller=caller,
    )
    if answer is None:
        subject, body = template_email(professor, facts)
        return EmailDraft(
            professor_id=professor.id,
            subject=subject,
            body=body,
            class_named=class_named,
            written_by="template",
        )
    draft = EmailDraft(
        professor_id=professor.id,
        subject=answer.subject.strip(),
        body=answer.body.strip(),
        class_named=class_named,
        written_by="claude",
    )
    _cache[key] = draft
    return draft
