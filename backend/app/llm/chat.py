"""The chat turn loop (AI-02).

One student message -> Claude (cached system prompt + 8 tools) -> run the tools
Claude asks for -> send results back -> repeat until Claude answers in text.
Every step is yielded as a ChatEvent so the endpoint can stream it.

The Claude call goes through a `Caller`, so tests replay recorded responses and
never call the API. The history is append-only: assistant turns are stored
exactly as returned (thinking and fallback blocks included) and never edited.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.contracts import ChatEvent

# Module imports (not names): app.llm.tools imports app.api, whose chat router imports
# this module, so a name import here would fail when tools is imported first.
from app.llm import client, tools

MAX_MODEL_CALLS = 8
MAX_TOKENS = 16000
CHAT_EFFORT = "medium"

ERR_RETRY_FAILED = (
    "Sorry, I couldn't turn that into a request I can run. Could you say it another way?"
)
ERR_UNAVAILABLE = "The assistant is unavailable right now. Please try again in a minute."
ERR_NOT_CONFIGURED = "The assistant is not set up on this server yet."
ERR_DECLINED = "I can't help with that. I can help you plan your Winter 2027 classes."
ERR_TOO_LONG = "That took too many steps. Could you ask one thing at a time?"


@dataclass
class TurnResult:
    """The finished assistant message of one Claude call."""

    content: list[dict[str, Any]]
    stop_reason: str | None


# A Caller takes the request parameters and yields text deltas (str) as they
# stream, then exactly one TurnResult.
Caller = Callable[[dict[str, Any]], Iterator[str | TurnResult]]


@dataclass
class ChatSession:
    """Per-session chat state. In memory until DATA-01 adds the database."""

    ctx: tools.ToolContext
    history: list[dict[str, Any]] = field(default_factory=list)


def build_params(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Request body for one call. Tools and system come first and never change,
    so they stay in the prompt cache; the top-level breakpoint caches the history."""
    return {
        "model": client.chat_model(),
        "max_tokens": MAX_TOKENS,
        "system": client.cached_system(),
        "tools": tools.tool_definitions(),
        "messages": list(history),
        "output_config": {"effort": CHAT_EFFORT},
        "cache_control": {"type": "ephemeral"},
        **client.chat_fallback_options(),
    }


def claude_caller(params: dict[str, Any]) -> Iterator[str | TurnResult]:
    """The real Caller: streams from the Claude API (beta endpoint for fallbacks)."""
    with client.get_client().beta.messages.stream(**params) as stream:
        for event in stream:
            if event.type == "text":
                yield event.text
        final = stream.get_final_message()
    yield TurnResult(
        content=[block.to_dict() for block in final.content],
        stop_reason=final.stop_reason,
    )


def _tool_result(tool_use_id: str, content: str, is_error: bool = False) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    return block


def run_turn(session: ChatSession, message: str, caller: Caller) -> Iterator[ChatEvent]:
    """Handle one student message. Always ends with a `done` event."""
    session.history.append({"role": "user", "content": message})
    input_errors: Counter[str] = Counter()

    try:
        for _ in range(MAX_MODEL_CALLS):
            result: TurnResult | None = None
            for item in caller(build_params(session.history)):
                if isinstance(item, str):
                    yield ChatEvent(type="text", text=item)
                else:
                    result = item
            if result is None:
                raise RuntimeError("Caller ended without a TurnResult")

            session.history.append({"role": "assistant", "content": result.content})

            if result.stop_reason == "refusal":
                yield ChatEvent(type="error", text=ERR_DECLINED)
                break

            tool_uses = [b for b in result.content if b.get("type") == "tool_use"]
            if not tool_uses:
                break

            results: list[dict[str, Any]] = []
            give_up = False
            truncated = result.stop_reason == "max_tokens"
            for block in tool_uses:
                name, args = block["name"], block.get("input", {})
                if truncated:
                    # A cut-off tool input may parse as a valid partial object: never run it.
                    results.append(_tool_result(block["id"], "Input was cut off.", True))
                    give_up = True
                    continue
                yield ChatEvent(type="tool_call", tool=name, data=args)
                try:
                    output = tools.run_tool(session.ctx, name, args)
                except tools.ToolInputError as exc:
                    input_errors[name] += 1
                    give_up = give_up or input_errors[name] >= 2
                    results.append(_tool_result(block["id"], str(exc), True))
                    continue
                except tools.ToolExecutionError as exc:
                    results.append(_tool_result(block["id"], str(exc), True))
                    continue
                yield ChatEvent(type="tool_result", tool=name, data=output)
                results.append(_tool_result(block["id"], json.dumps(output)))

            # Every tool_use gets its tool_result, even when we stop, so the
            # history stays valid for the student's next message.
            session.history.append({"role": "user", "content": results})
            if give_up:
                yield ChatEvent(type="error", text=ERR_RETRY_FAILED)
                break
        else:
            yield ChatEvent(type="error", text=ERR_TOO_LONG)
    except client.ClaudeNotConfiguredError:
        yield ChatEvent(type="error", text=ERR_NOT_CONFIGURED)
    except anthropic.APIError:
        # The SDK already retried rate limits and server errors with backoff.
        yield ChatEvent(type="error", text=ERR_UNAVAILABLE)

    yield ChatEvent(type="done")
