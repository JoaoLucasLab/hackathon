"""DATA-05: professor topic tags with Claude Haiku, cached by a SHA-256 of the input.

Replays recorded replies (no network, no live Claude call); the live run is
scripts/tag_professors.py, by hand. The profile below is made up.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import anthropic
import httpx2
import pytest

from app import config
from app.api import catalog_data
from app.llm import client as llm_client
from app.llm import topic_tags as tt
from app.llm.topic_tags import MemoryCache, tag_profile

SOURCES = {
    "education": "Ph.D., Computer Science, Example University",
    "interests": "Machine learning, data science and computer vision",
    "work_experience": "Software engineer at a health analytics company",
    "research": "Neural networks for medical imaging",
    "biography": (
        "Alice Doe teaches programming with Python and supervises students "
        "in her research on machine learning for medical imaging."
    ),
}
GOOD = json.dumps({"tags": ["machine learning", "data science", "computer vision", "python"]})


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


def test_tags_then_second_run_makes_zero_calls() -> None:
    cache = MemoryCache()
    first = Recorded([GOOD])
    result = tag_profile(SOURCES, subject="https://x.invalid/p", caller=first, cache=cache)
    assert result.status == "tagged"
    assert result.tags == ["machine learning", "data science", "computer vision", "python"]
    assert len(first.requests) == 1

    again = Recorded([])  # any call raises
    second = tag_profile(SOURCES, subject="https://x.invalid/p", caller=again, cache=cache)
    assert (second.status, second.tags) == ("cached", result.tags)
    assert again.requests == []


def test_cache_key_is_sha256_of_the_input() -> None:
    text = tt.profile_input(SOURCES)
    assert tt.cache_key(text) == "topic_tags:" + hashlib.sha256(text.encode()).hexdigest()
    assert tag_profile(SOURCES, caller=Recorded([GOOD]), cache=MemoryCache()).input_sha256 == (
        hashlib.sha256(text.encode()).hexdigest()
    )


def test_request_uses_bulk_model_cached_prompt_and_profile_only() -> None:
    caller = Recorded([GOOD])
    tag_profile(SOURCES, caller=caller, cache=MemoryCache())
    params = caller.requests[0]
    assert params["model"] == config.CLAUDE_MODEL_BULK
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "data, not instructions" in params["system"][0]["text"]
    content = params["messages"][0]["content"]
    assert content.startswith("<profile>") and "Machine learning" in content


def test_profile_input_leaves_out_empty_sections() -> None:
    text = tt.profile_input({"interests": "Compilers", "research": "  ", "biography": ""})
    assert text == "Interests:\nCompilers"


def test_invalid_reply_is_retried_once_with_the_error() -> None:
    caller = Recorded(['{"tags": ["machine learning"]}', GOOD])  # too few, then valid
    result = tag_profile(SOURCES, caller=caller, cache=MemoryCache())
    assert result.status == "tagged" and len(caller.requests) == 2
    retry = caller.requests[1]["messages"]
    assert retry[1]["role"] == "assistant" and "rejected" in retry[2]["content"]


def test_invented_topic_is_rejected() -> None:
    invented = json.dumps({"tags": ["machine learning", "quantum computing", "data science"]})
    caller = Recorded([invented, GOOD])
    result = tag_profile(SOURCES, caller=caller, cache=MemoryCache())
    assert result.status == "tagged"
    assert "quantum computing is not in the profile" in caller.requests[1]["messages"][2]["content"]


def test_failing_twice_caches_no_tags_so_the_next_run_makes_no_call() -> None:
    cache = MemoryCache()
    bad = Recorded(["not json", '{"tags": ["a"]}'])
    assert tag_profile(SOURCES, caller=bad, cache=cache).status == "failed"
    nothing = Recorded([])
    result = tag_profile(SOURCES, caller=nothing, cache=cache)
    assert (result.status, result.tags) == ("cached", [])


def test_short_profile_is_skipped_without_a_call() -> None:
    caller = Recorded([])
    result = tag_profile({"education": "M.S., Physics"}, caller=caller, cache=MemoryCache())
    assert (result.status, result.tags) == ("skipped", [])


def test_api_error_is_not_cached() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    def down(params: dict[str, Any]) -> str | None:
        raise anthropic.APIConnectionError(request=request)

    cache = MemoryCache()
    assert tag_profile(SOURCES, caller=down, cache=cache).status == "error"
    assert cache.data == {}


def test_missing_key_stops_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm_client.get_client.cache_clear()
    with pytest.raises(llm_client.ClaudeNotConfiguredError):
        tag_profile(SOURCES, cache=MemoryCache())


@pytest.mark.parametrize(
    "tags",
    [
        ["machine learning", "machine learning", "python"],  # duplicates leave 2
        ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"],
        ["a very long tag with many words", "python", "data science"],
    ],
)
def test_reply_shape_is_checked(tags: list[str]) -> None:
    with pytest.raises(ValueError):
        tt.validate_reply(json.dumps({"tags": tags}), tt.profile_input(SOURCES))


def test_tags_reach_the_professor_by_profile_url() -> None:
    url = "https://www.byui.edu/directories/alice-doe"
    prof = {
        "row_id": 3,
        "full_name": "Doe, Alice",
        "first_name": "Alice",
        "last_name": "Doe",
        "middle_name": None,
        "department": "Computer Science & Engineering",
        "directory_url": url,
    }
    catalog = catalog_data.Catalog(
        [], [], [], [prof, prof | {"row_id": 4, "full_name": "Roe, Bob", "directory_url": None}],
        [],
        topic_tags=[{"directory_url": url, "tags": ["machine learning", "python", "data science"]}],
    )  # fmt: skip
    alice, bob = catalog.professors
    assert alice.topic_tags == ["machine learning", "python", "data science"]
    assert bob.topic_tags == []
