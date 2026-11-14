"""AI-02: the turn loop's control flow, with hand-scripted Claude responses."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import anthropic
import httpx2 as httpx
import pytest

from app import config
from app.api import fixture_data
from app.llm import chat
from app.llm.chat import ChatSession, TurnResult, run_turn
from app.llm.tools import ToolContext


def _session() -> ChatSession:
    return ChatSession(ctx=ToolContext(audit=fixture_data.audit()))


def _tool_use(i: int, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": f"toolu_{i}", "name": name, "input": args}


def _text(t: str) -> dict[str, Any]:
    return {"type": "text", "text": t}


class Script:
    def __init__(self, *turns: TurnResult) -> None:
        self.turns = list(turns)
        self.params: list[dict[str, Any]] = []

    def __call__(self, params: dict[str, Any]) -> Iterator[str | TurnResult]:
        self.params.append(params)
        turn = self.turns.pop(0)
        for block in turn.content:
            if block["type"] == "text":
                yield block["text"]
        yield turn


BAD = {"course_codes": ["cse212"], "delivery_method": None}
GOOD = {"course_codes": ["CSE 212"], "delivery_method": None}


def test_text_streams_then_done() -> None:
    script = Script(TurnResult([_text("Hi there.")], "end_turn"))
    events = list(run_turn(_session(), "hello", script))
    assert [e.type for e in events] == ["text", "done"]


def test_bad_args_are_retried_once_with_the_error() -> None:
    script = Script(
        TurnResult([_tool_use(1, "search_sections", BAD)], "tool_use"),
        TurnResult([_tool_use(2, "search_sections", GOOD)], "tool_use"),
        TurnResult([_text("CSE 212 has 4 sections.")], "end_turn"),
    )
    session = _session()
    events = list(run_turn(session, "is cse212 offered?", script))
    retry_request = script.params[1]["messages"][-1]["content"][0]
    assert retry_request["is_error"] is True
    assert "course_codes.0" in retry_request["content"]
    assert "error" not in [e.type for e in events]
    assert events[-1].type == "done"


def test_second_bad_args_give_a_clear_message() -> None:
    script = Script(
        TurnResult([_tool_use(1, "search_sections", BAD)], "tool_use"),
        TurnResult([_tool_use(2, "search_sections", BAD)], "tool_use"),
    )
    session = _session()
    events = list(run_turn(session, "is cse212 offered?", script))
    errors = [e for e in events if e.type == "error"]
    assert [e.text for e in errors] == [chat.ERR_RETRY_FAILED]
    assert script.turns == []  # no third call
    # history stays valid: the last tool_use has its tool_result
    assert session.history[-1]["content"][0]["tool_use_id"] == "toolu_2"


def test_refusal_is_a_polite_message() -> None:
    script = Script(TurnResult([], "refusal"))
    events = list(run_turn(_session(), "something", script))
    assert [(e.type, e.text) for e in events] == [("error", chat.ERR_DECLINED), ("done", None)]


def test_truncated_tool_input_is_never_run() -> None:
    args = {"constraints": {}, "max_results": 3}
    script = Script(TurnResult([_tool_use(1, "build_schedules", args)], "max_tokens"))
    session = _session()
    events = list(run_turn(session, "build", script))
    assert "tool_call" not in [e.type for e in events]
    assert session.history[-1]["content"][0]["is_error"] is True


def test_api_error_is_a_clear_message() -> None:
    def failing(params: dict[str, Any]) -> Iterator[str | TurnResult]:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.APIConnectionError(request=request)
        yield ""  # pragma: no cover

    events = list(run_turn(_session(), "hi", failing))
    assert [(e.type, e.text) for e in events] == [("error", chat.ERR_UNAVAILABLE), ("done", None)]


def test_request_uses_cache_and_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "CLAUDE_MODEL_CHAT", "model-from-env")
    params = chat.build_params([{"role": "user", "content": "hi"}])
    assert params["model"] == "model-from-env"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in params["tools"]][0] == "get_remaining_requirements"


def test_tool_call_and_result_events_carry_data() -> None:
    script = Script(
        TurnResult([_tool_use(1, "search_sections", GOOD)], "tool_use"),
        TurnResult([_text("Done.")], "end_turn"),
    )
    events = list(run_turn(_session(), "cse 212?", script))
    call = next(e for e in events if e.type == "tool_call")
    result = next(e for e in events if e.type == "tool_result")
    assert call.data == GOOD
    assert (result.data or {})["not_found"] == []
