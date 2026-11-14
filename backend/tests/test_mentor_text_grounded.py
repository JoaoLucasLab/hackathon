"""AI-05: mentor reasons and topic tags are grounded in structured facts only.

Replays recorded Claude replies (no network, no live Claude call).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import fixture_data
from app.api import mentors as mentors_api
from app.contracts import MentorGoal, MentorMatch, MentorSearchRequest
from app.llm import client as llm_client
from app.llm import mentor_text
from app.main import app

RECORDINGS = Path(__file__).parent / "data" / "recordings" / "mentors"
api = TestClient(app)


class Recorded:
    """A Caller that replays replies in order and keeps every request it got."""

    def __init__(self, replies: list[str | None]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, params: dict[str, Any]) -> str | None:
        self.requests.append(params)
        return self.replies.pop(0)


def _recording(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((RECORDINGS / f"{name}.json").read_text())
    return data


def _matches(*tags: str) -> list[MentorMatch]:
    return mentors_api.rank_mentors(MentorSearchRequest(goal=MentorGoal.research, tags=list(tags)))


def _reasons_reply(items: dict[str, str]) -> str:
    return json.dumps({"items": [{"professor_id": k, "text": v} for k, v in items.items()]})


# --- Reasons ----------------------------------------------------------------------


def test_recorded_reasons_name_nothing_outside_the_structured_list() -> None:
    rec = _recording("reasons-data-science")
    matches = _matches(*rec["tags"])
    assert [m.professor.id for m in matches] == ["p-hale", "p-reyes"]
    result = mentor_text.describe_matches(matches, caller=Recorded(rec["replies"]))
    everyone = fixture_data.professors()
    for match in result:
        assert match.reason_text, match.professor.id
        # The same check the module runs: no course, tag or professor outside the reasons.
        mentor_text.check_reason_text(match.reason_text, match, everyone)
        assert mentor_text.course_codes_in(match.reason_text) <= mentor_text.allowed_course_codes(
            match
        )
        # The structured reasons are still returned, unchanged.
        assert [r.detail for r in match.reasons]


def test_only_structured_facts_are_sent() -> None:
    rec = _recording("reasons-data-science")
    caller = Recorded(rec["replies"])
    mentor_text.describe_matches(_matches(*rec["tags"]), caller=caller)
    sent = json.loads(caller.requests[0]["messages"][0]["content"])
    hale = next(m for m in sent["matches"] if m["professor_id"] == "p-hale")
    assert set(hale) == {"professor_id", "name", "department", "reasons"}
    # Not the bio, not the winter courses: Claude cannot reword what it never sees.
    body = json.dumps(sent)
    assert "CSE 450" not in body
    assert "neural networks" not in body


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Professor Hale teaches CSE 450 and studies machine learning.", "CSE 450"),
        ("Professor Hale works on machine learning and neural networks.", "neural networks"),
        ("Like Professor Reyes, Professor Hale studies machine learning.", "another professor"),
        ("Professor Hale will accept you into his machine learning lab.", "promises"),
    ],
)
def test_reason_text_outside_the_reasons_is_rejected(text: str, problem: str) -> None:
    match = _matches("machine learning")[0]
    assert match.professor.id == "p-hale"
    with pytest.raises(mentor_text.NotGroundedError, match=problem):
        mentor_text.check_reason_text(text, match, fixture_data.professors())


def test_bad_text_is_retried_once_with_the_error() -> None:
    matches = _matches("machine learning")
    good = "Professor Hale lists machine learning among his interests."
    caller = Recorded(
        [
            _reasons_reply({"p-hale": "Professor Hale teaches CSE 450 and machine learning."}),
            _reasons_reply({"p-hale": good}),
        ]
    )
    result = mentor_text.describe_matches(matches, caller=caller)
    assert result[0].reason_text == good
    assert len(caller.requests) == 2
    assert "CSE 450" in caller.requests[1]["messages"][-1]["content"]


def test_two_failures_fall_back_to_the_structured_reasons() -> None:
    matches = _matches("machine learning")
    bad = _reasons_reply({"p-hale": "Professor Hale teaches CSE 450."})
    result = mentor_text.describe_matches(matches, caller=Recorded([bad, "not json"]))
    assert result[0].reason_text is None
    assert [r.detail for r in result[0].reasons] == ["machine learning"]


def test_missing_or_extra_professor_is_rejected() -> None:
    matches = _matches("data science")
    only_one = _reasons_reply({"p-hale": "Professor Hale lists data science."})
    result = mentor_text.describe_matches(matches, caller=Recorded([only_one, only_one]))
    assert all(m.reason_text is None for m in result)


def test_search_endpoint_returns_at_most_five_with_reasons() -> None:
    tags = sorted({t for p in fixture_data.professors() for t in p.topic_tags})
    response = api.post("/api/mentors/search", json={"goal": "research", "tags": tags})
    assert response.status_code == 200
    body = response.json()
    assert 1 <= len(body) <= 5
    assert all(m["reasons"] for m in body)
    # No Claude in tests: the structured reasons are what the screen shows.
    assert all(m["reason_text"] is None for m in body)


# --- Topic to existing tags -------------------------------------------------------


def test_topic_maps_to_existing_tags_only() -> None:
    rec = _recording("topic-ai")
    known = mentors_api.known_tags()
    caller = Recorded(rec["replies"])
    tags = mentor_text.map_topic(rec["topic"], known, caller=caller)
    assert tags == ["machine learning", "neural networks"]
    assert set(tags) <= set(known)
    sent = json.loads(caller.requests[0]["messages"][0]["content"])
    assert sent == {"topic": rec["topic"], "known_tags": known}
    assert caller.requests[0]["model"] == llm_client.bulk_model()


def test_unrelated_topic_gives_no_tags() -> None:
    rec = _recording("topic-unrelated")
    tags = mentor_text.map_topic(rec["topic"], mentors_api.known_tags(), Recorded(rec["replies"]))
    assert tags == []


def test_invented_tag_is_retried_then_dropped() -> None:
    known = mentors_api.known_tags()
    invented = json.dumps({"tags": ["robotics", "machine learning"]})
    caller = Recorded([invented, invented])
    tags = mentor_text.map_topic("robots that learn", known, caller=caller)
    assert len(caller.requests) == 2
    assert "robotics" in caller.requests[1]["messages"][-1]["content"]
    # After two invalid answers, the no-Claude fallback runs on existing tags only.
    assert set(tags) <= set(known)
    assert "robotics" not in tags


def test_tag_case_is_taken_from_the_known_list() -> None:
    tags = mentor_text.map_topic(
        "SQL", mentors_api.known_tags(), Recorded([json.dumps({"tags": ["SQL"]})])
    )
    assert tags == ["sql"]


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("machine learning", ["machine learning"]),
        ("I like web development and accessibility", ["accessibility", "web development"]),
        ("secur", ["computer security"]),
        ("underwater basket weaving", []),
    ],
)
def test_fallback_without_claude(topic: str, expected: list[str]) -> None:
    assert mentor_text.fallback_tags(topic, mentors_api.known_tags()) == expected


def test_topic_endpoint() -> None:
    hit = api.post("/api/mentors/topic", json={"topic": "machine learning"})
    assert hit.status_code == 200
    assert hit.json() == {"topic": "machine learning", "tags": ["machine learning"]}
    miss = api.post("/api/mentors/topic", json={"topic": "pizza"})
    assert miss.json()["tags"] == []
    assert api.post("/api/mentors/topic", json={"topic": ""}).status_code == 422
