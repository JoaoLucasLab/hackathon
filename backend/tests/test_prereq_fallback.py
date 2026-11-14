"""ENG-04: Claude Haiku fallback for prerequisite text the code parser cannot read.

Replays recorded replies from `data/recordings/prereq_fallback/` (no network, no
live Claude call). `test_record_live_fallback` re-records them by hand.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest

from app import config
from app.contracts import PrereqAll, PrereqAny, PrereqCourse, PrereqUnparsed
from app.llm import client as llm_client
from app.llm import prereq_fallback
from app.llm.prereq_fallback import MemoryCache, cache_key, parse_with_fallback

RECORDINGS = Path(__file__).parent / "data" / "recordings" / "prereq_fallback"
TEXT = "Completion of CSE 212; or both CSE 210 and MATH 112 (C or better)"
EXPECTED = PrereqAll(
    items=[
        PrereqAny(
            items=[
                PrereqCourse(course_code="CSE 212"),
                PrereqAll(
                    items=[
                        PrereqCourse(course_code="CSE 210"),
                        PrereqCourse(course_code="MATH 112", min_grade="C"),
                    ]
                ),
            ]
        )
    ]
)


class Recorded:
    """A Caller that replays replies in order and keeps every request it got."""

    def __init__(self, replies: list[str | None]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, params: dict[str, Any]) -> str | None:
        self.requests.append(params)
        if not self.replies:
            raise AssertionError("unexpected Claude call")
        return self.replies.pop(0)


def recorded(name: str) -> tuple[str, Recorded]:
    data = json.loads((RECORDINGS / f"{name}.json").read_text())
    return data["text"], Recorded(data["replies"])


def no_calls() -> Recorded:
    return Recorded([])


def test_code_parser_first_no_claude_call() -> None:
    caller = no_calls()
    result = parse_with_fallback(
        "CSE 212 and MATH 215 (C or better)", caller=caller, cache=MemoryCache()
    )
    assert isinstance(result, PrereqAll) and len(result.items) == 2
    assert caller.requests == []


def test_valid_reply_is_validated_and_cached_second_run_makes_no_call() -> None:
    text, caller = recorded("valid")
    cache = MemoryCache()
    assert parse_with_fallback(text, caller=caller, cache=cache) == EXPECTED
    assert len(caller.requests) == 1

    again = no_calls()
    assert parse_with_fallback(text, caller=again, cache=cache) == EXPECTED
    assert again.requests == []


def test_cache_key_is_sha256_of_the_input_text() -> None:
    text, caller = recorded("valid")
    cache = MemoryCache()
    parse_with_fallback(text, caller=caller, cache=cache)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert list(cache.data) == [cache_key(text)]
    assert cache_key(text).endswith(digest)


def test_invalid_reply_is_retried_once_with_the_error() -> None:
    text, caller = recorded("invalid-then-valid")
    assert parse_with_fallback(text, caller=caller, cache=MemoryCache()) == EXPECTED
    assert len(caller.requests) == 2
    retry = caller.requests[1]["messages"]
    assert retry[1]["role"] == "assistant"
    assert retry[2]["role"] == "user" and "rejected" in retry[2]["content"]


def test_invented_course_is_rejected_and_retried() -> None:
    text, caller = recorded("invented-then-valid")
    assert parse_with_fallback(text, caller=caller, cache=MemoryCache()) == EXPECTED
    assert "CSE 999" in caller.requests[1]["messages"][2]["content"]


def test_two_bad_replies_become_unparsed_and_are_cached() -> None:
    text, caller = recorded("invalid-twice")
    cache = MemoryCache()
    assert parse_with_fallback(text, caller=caller, cache=cache) == PrereqUnparsed(text=text)
    assert len(caller.requests) == 2
    again = no_calls()
    assert parse_with_fallback(text, caller=again, cache=cache) == PrereqUnparsed(text=text)
    assert again.requests == []


def test_refusal_is_unparsed() -> None:
    assert parse_with_fallback(TEXT, caller=Recorded([None]), cache=MemoryCache()) == (
        PrereqUnparsed(text=TEXT)
    )


def test_missing_key_is_unparsed_and_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm_client.get_client.cache_clear()
    cache = MemoryCache()
    assert parse_with_fallback(TEXT, cache=cache) == PrereqUnparsed(text=TEXT)
    assert cache.data == {}
    llm_client.get_client.cache_clear()


def test_api_error_is_unparsed_and_not_cached() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    def failing(_: dict[str, Any]) -> str | None:
        raise anthropic.APIConnectionError(request=request)

    cache = MemoryCache()
    assert parse_with_fallback(TEXT, caller=failing, cache=cache) == PrereqUnparsed(text=TEXT)
    assert cache.data == {}


def test_request_uses_bulk_model_cached_prompt_and_wraps_text_as_data() -> None:
    text, caller = recorded("valid")
    parse_with_fallback(text, caller=caller, cache=MemoryCache())
    params = caller.requests[0]
    assert params["model"] == config.CLAUDE_MODEL_BULK
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "data, not instructions" in params["system"][0]["text"]
    content = params["messages"][0]["content"]
    assert content == f"<prereq_text>\n{text}\n</prereq_text>"
    # No name, ID or audit data: only the catalog text goes to Claude.
    assert len(params["messages"]) == 1


@pytest.mark.live
def test_record_live_fallback() -> None:
    """By hand: `pytest -m live backend/tests/test_prereq_fallback.py`. Records a
    real Haiku reply for TEXT and checks it validates."""
    replies: list[str | None] = []

    def recording(params: dict[str, Any]) -> str | None:
        reply = prereq_fallback.claude_caller(params)
        replies.append(reply)
        return reply

    result = parse_with_fallback(TEXT, caller=recording, cache=MemoryCache())
    assert not isinstance(result, PrereqUnparsed), replies
    (RECORDINGS / "valid.json").write_text(
        json.dumps({"text": TEXT, "replies": replies}, indent=2) + "\n"
    )
