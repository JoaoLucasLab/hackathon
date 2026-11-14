"""Claude Haiku fallback for prerequisite text the code parser cannot read (ENG-04).

Order for each text:
1. `engine/prereqs/parser.py` (code, no Claude call). Every fixture course stops here.
2. The cache, keyed by a SHA-256 of the input text. A text is sent to Claude once.
3. Claude Haiku (`CLAUDE_MODEL_BULK`). The reply must validate against
   `PrereqExpression` and may name only course codes that appear in the text (it
   restructures, it never invents). A failed reply is retried once with the error.
4. Still failing: an `unparsed` node, shown as a warning. Never "no prerequisites".

A reply that failed both attempts is cached as `unparsed`, so the next run makes no
call either. A missing key or an API error is not cached: it may work next time.

The cache is in memory until the Data owner adds the `llm_cache` table (it is not
in `db/schema.sql` yet); `PrereqCache` is the seam for that table.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from typing import Any, Protocol

import anthropic
from pydantic import TypeAdapter, ValidationError

from app.contracts import PrereqAll, PrereqCourse, PrereqExpression, PrereqUnparsed
from app.engine.prereqs.parser import PrereqParseError, parse_prereq_text
from app.llm import client

log = logging.getLogger(__name__)

MAX_TOKENS = 2000
EFFORT = "low"
CACHE_NAMESPACE = "prereq_parse"

_ADAPTER: TypeAdapter[PrereqExpression] = TypeAdapter(PrereqExpression)
_CODE_IN_TEXT = re.compile(r"\b([A-Z]{2,5})\s?(\d{3}[A-Z]?)\b")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

# Takes the request parameters, returns the reply text (None on a refusal).
# Tests pass a recorded one; nothing in the test suite reaches the API.
Caller = Callable[[dict[str, Any]], str | None]


class PrereqCache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value


_default_cache = MemoryCache()


class NotGroundedError(ValueError):
    """The tree names a course that is not in the text."""


def cache_key(text: str) -> str:
    return f"{CACHE_NAMESPACE}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def build_params(text: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": client.bulk_model(),
        "max_tokens": MAX_TOKENS,
        "system": client.cached_system("prereq_fallback"),
        "messages": [
            {"role": "user", "content": f"<prereq_text>\n{text}\n</prereq_text>"},
            *history,
        ],
        "output_config": {"effort": EFFORT},
    }


def claude_caller(params: dict[str, Any]) -> str | None:
    message = client.get_client().messages.create(**params)
    if message.stop_reason in ("refusal", "max_tokens"):
        log.warning("prereq fallback: no answer, stop_reason=%s", message.stop_reason)
        return None
    return next((b.text for b in message.content if b.type == "text"), None)


def _courses(expr: PrereqExpression) -> list[str]:
    if isinstance(expr, PrereqCourse):
        return [expr.course_code]
    if isinstance(expr, PrereqUnparsed) or not hasattr(expr, "items"):
        return []
    return [c for item in expr.items for c in _courses(item)]


def validate_reply(reply: str, text: str) -> PrereqAll:
    """Parse and check one reply. Raises ValidationError or NotGroundedError."""
    expr = _ADAPTER.validate_json(_FENCE.sub("", reply.strip()))
    allowed = {f"{s} {n}" for s, n in _CODE_IN_TEXT.findall(text.upper())}
    invented = sorted(set(_courses(expr)) - allowed)
    if invented:
        raise NotGroundedError(
            f"{', '.join(invented)} is not in the text. Use only courses written in it: "
            f"{', '.join(sorted(allowed)) or 'none'}."
        )
    return expr if isinstance(expr, PrereqAll) else PrereqAll(items=[expr])


def parse_with_fallback(
    text: str | None,
    *,
    caller: Caller = claude_caller,
    cache: PrereqCache = _default_cache,
) -> PrereqExpression:
    try:
        return parse_prereq_text(text)
    except PrereqParseError as exc:
        log.info("prereq parser could not read the text (%s); trying the fallback", exc)
    assert text is not None  # parse_prereq_text accepts None and empty text

    key = cache_key(text)
    hit = cache.get(key)
    if hit is not None:
        return _ADAPTER.validate_json(hit)

    history: list[dict[str, Any]] = []
    for _attempt in range(2):
        try:
            reply = caller(build_params(text, history))
        except client.ClaudeNotConfiguredError:
            log.warning("prereq fallback: ANTHROPIC_API_KEY is not set; storing as unparsed")
            return PrereqUnparsed(text=text)
        except anthropic.APIError as exc:
            log.warning(
                "prereq fallback: Claude API error %s (status %s)",
                type(exc).__name__,
                getattr(exc, "status_code", None),
            )
            return PrereqUnparsed(text=text)
        if reply is None:
            break
        try:
            expr = validate_reply(reply, text)
        except (ValidationError, NotGroundedError) as exc:
            log.info("prereq fallback: reply rejected: %s", type(exc).__name__)
            history += [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": (
                        f"That reply was rejected: {exc}. Reply with the corrected JSON only."
                    ),
                },
            ]
            continue
        cache.set(key, json.dumps(expr.model_dump(mode="json")))
        return expr

    result = PrereqUnparsed(text=text)
    cache.set(key, json.dumps(result.model_dump(mode="json")))
    return result
