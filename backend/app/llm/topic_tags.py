"""Professor topic tags with Claude Haiku (DATA-05).

For each professor with a public profile:
1. Build the input from the profile sections (no name, no contact details).
2. The cache, keyed by a SHA-256 of that input. A profile is sent to Claude once,
   so a second run makes 0 calls.
3. Claude Haiku (`CLAUDE_MODEL_BULK`). The reply must validate as 3 to 8 tags, and
   every tag must come from words in the profile (it summarizes, it never invents).
   A failed reply is retried once with the error.
4. Still failing: no tags (cached as [], so the next run makes no call either).
   An API error is not cached: it may work next time. A missing key raises
   ClaudeNotConfiguredError, so the run stops instead of skipping every profile.

A profile with too little text to tag (fewer than MIN_WORDS words) is skipped
without a call: three honest tags need something to read.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.llm import client

log = logging.getLogger(__name__)

MAX_TOKENS = 2000
EFFORT = "low"
CACHE_NAMESPACE = "topic_tags"
MIN_WORDS = 20

# Sections sent to Claude, in this order. Contact details and the name are left out.
SECTIONS = ("interests", "research", "work_experience", "education", "biography")

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
_WORD = re.compile(r"[a-z0-9+#]+")

# Takes the request parameters, returns the reply text (None on a refusal).
# Tests pass a recorded one; nothing in the test suite reaches the API.
Caller = Callable[[dict[str, Any]], str | None]


class TagCache(Protocol):
    def get(self, key: str) -> list[str] | None: ...
    def set(self, key: str, tags: list[str], *, subject: str | None, model: str) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, list[str]] = {}

    def get(self, key: str) -> list[str] | None:
        return self.data.get(key)

    def set(self, key: str, tags: list[str], *, subject: str | None, model: str) -> None:
        self.data[key] = tags


class TagReply(BaseModel):
    tags: list[str] = Field(min_length=3, max_length=8)

    @field_validator("tags")
    @classmethod
    def _clean(cls, tags: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(re.sub(r"\s+", " ", t).strip().lower() for t in tags))
        if len(cleaned) < 3:
            raise ValueError("give at least 3 different tags")
        for t in cleaned:
            if not 2 <= len(t) <= 40 or len(t.split()) > 4:
                raise ValueError(f"tag {t!r} must be 1 to 4 words and at most 40 characters")
        return cleaned


class NotGroundedError(ValueError):
    """A tag names something the profile does not mention."""


@dataclass(frozen=True)
class TagResult:
    tags: list[str]
    status: Literal["tagged", "cached", "skipped", "failed", "error"]
    input_sha256: str


def profile_input(sources: dict[str, str]) -> str:
    """The text Claude reads: labelled sections, empty ones left out."""
    parts = [
        f"{kind.replace('_', ' ').title()}:\n{sources[kind].strip()}"
        for kind in SECTIONS
        if sources.get(kind, "").strip()
    ]
    return "\n\n".join(parts)


def input_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(text: str) -> str:
    return f"{CACHE_NAMESPACE}:{input_sha256(text)}"


def build_params(text: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": client.bulk_model(),
        "max_tokens": MAX_TOKENS,
        "system": client.cached_system("topic_tags"),
        "messages": [
            {"role": "user", "content": f"<profile>\n{text}\n</profile>"},
            *history,
        ],
        "output_config": {"effort": EFFORT},
    }


def claude_caller(params: dict[str, Any]) -> str | None:
    message = client.get_client().messages.create(**params)
    if message.stop_reason in ("refusal", "max_tokens"):
        log.warning("topic tags: no answer, stop_reason=%s", message.stop_reason)
        return None
    return next((b.text for b in message.content if b.type == "text"), None)


_STOPWORDS = {"and", "or", "of", "the", "in", "for", "with", "to", "a", "an", "on"}


def _grounded(tag: str, words: set[str]) -> bool:
    """Every word of the tag comes from the profile ("quantum computing" fails on a
    profile that only says "computer"). Words of 5+ letters may differ in their
    ending ('teaching' / 'teaches'); shorter words must appear as written."""
    wanted = [w for w in _WORD.findall(tag) if w not in _STOPWORDS]
    return bool(wanted) and all(
        any(x.startswith(w[:5]) for x in words) if len(w) >= 5 else w in words for w in wanted
    )


def validate_reply(reply: str, text: str) -> list[str]:
    """Parse and check one reply. Raises ValidationError or NotGroundedError."""
    tags = TagReply.model_validate_json(_FENCE.sub("", reply.strip())).tags
    words = set(_WORD.findall(text.lower()))
    invented = [t for t in tags if not _grounded(t, words)]
    if invented:
        raise NotGroundedError(
            f"{', '.join(invented)} is not in the profile. Use only topics the profile names."
        )
    return tags


def tag_profile(
    sources: dict[str, str],
    *,
    subject: str | None = None,
    caller: Caller = claude_caller,
    cache: TagCache,
) -> TagResult:
    text = profile_input(sources)
    sha = input_sha256(text)
    if len(text.split()) < MIN_WORDS:
        return TagResult([], "skipped", sha)

    key = cache_key(text)
    hit = cache.get(key)
    if hit is not None:
        return TagResult(hit, "cached", sha)

    history: list[dict[str, Any]] = []
    for _attempt in range(2):
        try:
            reply = caller(build_params(text, history))
        except anthropic.APIError as exc:
            log.warning(
                "topic tags: Claude API error %s (status %s)",
                type(exc).__name__,
                getattr(exc, "status_code", None),
            )
            return TagResult([], "error", sha)
        if reply is None:
            break
        try:
            tags = validate_reply(reply, text)
        except (ValidationError, NotGroundedError) as exc:
            log.info("topic tags: reply rejected: %s", type(exc).__name__)
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
        cache.set(key, tags, subject=subject, model=client.bulk_model())
        return TagResult(tags, "tagged", sha)

    cache.set(key, [], subject=subject, model=client.bulk_model())
    return TagResult([], "failed", sha)
