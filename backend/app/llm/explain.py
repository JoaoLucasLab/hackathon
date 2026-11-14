"""Why this schedule" and the trade-offs (AI-03).

The solver returns structured facts only (`Schedule.why`, the classes, the
requirements they fill). Claude rewords those facts for the student; this module
is the only place that text is written.

Grounding rules, checked on every answer before it is returned:
- every course code in the text is a class in this schedule,
- nothing promises a seat, admission or a graduation date.
A failed check (or invalid JSON) is retried once with the error. If the retry
fails too, the result is `available=False` and the screen shows the structured
`why` instead of text.

Results are cached by a SHA-256 of the facts and the model name: the same
schedule is never explained twice. (In memory until DATA-01 adds `llm_cache`.)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from typing import Any

import anthropic
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.contracts import Schedule, ScheduleExplanation
from app.llm import client

log = logging.getLogger(__name__)

MAX_TOKENS = 4000
EXPLAIN_EFFORT = "low"

# "CSE 111", "CSE111", "MATH 221A". Subject codes are 2 to 4 capital letters.
COURSE_CODE = re.compile(r"\b([A-Z]{2,4}) ?(\d{3}[A-Z]?)\b")
PROMISES = re.compile(
    r"guarantee|\bsecured?\b|\breserved?\b|\bpromise|you(?:'ll| will) (?:get|have) (?:a|your) seat"
    r"|seat is yours|(?:will|on track to) graduate",
    re.IGNORECASE,
)

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "why": {"type": "string"},
        "tradeoffs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["why", "tradeoffs"],
    "additionalProperties": False,
}


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    why: str = Field(min_length=1, max_length=400)
    tradeoffs: list[str] = Field(default_factory=list, max_length=3)


class NotGroundedError(ValueError):
    """The text names something outside the facts, or promises a seat."""


# A Caller takes the request parameters and returns the reply's JSON text, or
# None when Claude declined. Tests pass a recorded one; nothing here hits the API.
Caller = Callable[[dict[str, Any]], str | None]

_cache: dict[str, ScheduleExplanation] = {}

BLOCK_NAMES = {"full": "full semester", "first": "First Block", "second": "Second Block"}


def _hhmm(value: Any) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def schedule_facts(
    schedule: Schedule,
    requirement_names: dict[str, str],
    professor_names: dict[str, str],
) -> dict[str, Any]:
    """Only the structured fields Claude needs. No student name, no ID number."""
    favorites = set(schedule.why.favorite_professor_ids)
    classes = []
    for c in schedule.classes:
        s = c.section
        classes.append(
            {
                "course_code": s.course_code,
                "title": s.title,
                "credits": s.credits,
                "block": BLOCK_NAMES[s.block.value],
                "delivery": s.delivery_method.value,
                "meetings": [
                    {
                        "days": "".join(m.days),
                        "start": _hhmm(m.start_time),
                        "end": _hhmm(m.end_time),
                    }
                    for m in s.meetings
                    if not m.tba and m.start_time is not None
                ],
                "no_set_time": not any(m.start_time for m in s.meetings),
                "fills": [requirement_names.get(r, r) for r in c.requirement_ids],
                "professors": [professor_names.get(p, p) for p in s.instructor_ids],
                "waitlisted": c.waitlisted,
                "warnings": [w.message for w in c.warnings],
            }
        )
    return {
        "rank": schedule.rank,
        "total_credits": schedule.total_credits,
        "classes": classes,
        "preferences_met": schedule.why.preferences_met,
        "preferences_missed": schedule.why.preferences_missed,
        "favorite_professors": sorted(professor_names.get(p, p) for p in favorites),
        "schedule_warnings": [w.message for w in schedule.warnings],
    }


def course_codes_in(text: str) -> set[str]:
    return {f"{subject} {number}" for subject, number in COURSE_CODE.findall(text)}


def check_grounded(answer: _Answer, schedule: Schedule) -> None:
    allowed = {c.section.course_code for c in schedule.classes}
    text = " ".join([answer.why, *answer.tradeoffs])
    unknown = sorted(course_codes_in(text) - allowed)
    if unknown:
        raise NotGroundedError(
            f"The text names {', '.join(unknown)}, which is not in this schedule. "
            f"Only name these courses: {', '.join(sorted(allowed))}."
        )
    if PROMISES.search(text):
        raise NotGroundedError(
            "The text promises a seat, admission or graduation. Remove that wording."
        )


def build_params(facts: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": client.chat_model(),
        "max_tokens": MAX_TOKENS,
        "system": client.cached_system("explain"),
        "messages": [{"role": "user", "content": json.dumps(facts, sort_keys=True)}, *history],
        "output_config": {
            "effort": EXPLAIN_EFFORT,
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
        },
        **client.chat_fallback_options(),
    }


def claude_caller(params: dict[str, Any]) -> str | None:
    """The real Caller. Returns None on a refusal."""
    message = client.get_client().beta.messages.create(**params)
    if message.stop_reason in ("refusal", "max_tokens"):
        log.warning("explain: no answer, stop_reason=%s", message.stop_reason)
        return None
    return next((b.text for b in message.content if b.type == "text"), None)


def _unavailable(schedule: Schedule) -> ScheduleExplanation:
    return ScheduleExplanation(schedule_id=schedule.id, available=False)


def explain_schedule(
    schedule: Schedule,
    requirement_names: dict[str, str],
    professor_names: dict[str, str],
    caller: Caller = claude_caller,
) -> ScheduleExplanation:
    facts = schedule_facts(schedule, requirement_names, professor_names)
    key = hashlib.sha256(
        json.dumps({"model": client.chat_model(), "facts": facts}, sort_keys=True).encode()
    ).hexdigest()
    if key in _cache:
        return _cache[key].model_copy(update={"schedule_id": schedule.id})

    history: list[dict[str, Any]] = []
    for _attempt in range(2):
        try:
            text = caller(build_params(facts, history))
        except client.ClaudeNotConfiguredError:
            log.warning("explain: ANTHROPIC_API_KEY is not set; showing the structured why")
            return _unavailable(schedule)
        except anthropic.APIError as exc:
            # Only the error type and status: never the request body.
            log.warning(
                "explain: Claude API error %s (status %s) for schedule %s",
                type(exc).__name__,
                getattr(exc, "status_code", None),
                schedule.id,
            )
            return _unavailable(schedule)
        if text is None:
            return _unavailable(schedule)
        try:
            answer = _Answer.model_validate_json(text)
            check_grounded(answer, schedule)
        except (ValidationError, NotGroundedError) as exc:
            log.info(
                "explain: answer rejected for schedule %s: %s", schedule.id, type(exc).__name__
            )
            history += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That answer was rejected: {exc}. Try again."},
            ]
            continue
        result = ScheduleExplanation(
            schedule_id=schedule.id,
            available=True,
            why=answer.why.strip(),
            tradeoffs=[t.strip() for t in answer.tradeoffs if t.strip()],
        )
        _cache[key] = result
        return result
    log.warning("explain: two answers failed the grounding check for schedule %s", schedule.id)
    return _unavailable(schedule)
