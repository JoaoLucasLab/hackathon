"""The chat turn loop (AI-02).

One student message -> Claude (cached system prompt + tools) -> run the tools
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

from app import config
from app.contracts import ChatEvent, ChatTurn, Relaxation, Schedule

# Module imports (not names): app.llm.tools imports app.api, whose chat router imports
# this module, so a name import here would fail when tools is imported first.
from app.llm import client, tools
from app.llm.intake import OFFER_DEFAULTS_NOTE, ChoiceFilter

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
    # AI-08: the conversation as the chat showed it (text, the schedule card, quick
    # replies), so a reload can restore it. `history` is what Claude sees.
    transcript: list[ChatTurn] = field(default_factory=list)


APPLY_RELAXATION = "Apply this change"


def _show_build(reply: ChatTurn, output: dict[str, Any]) -> None:
    """AI-08: what a `build_schedules` result puts on the assistant's message. Exactly
    one schedule card, or the "no schedule fits" hint. The latest build wins."""
    schedules = output.get("schedules") or []
    reply.schedule = Schedule.model_validate(schedules[0]) if schedules else None
    reply.option = output.get("option") if schedules else None
    relaxation = output.get("relaxation")
    reply.relaxation = (
        Relaxation.model_validate(relaxation) if relaxation and not schedules else None
    )
    reply.no_schedule = not schedules


def system_prompt_name() -> str:
    """`system` has the intake rules (AI-07). `system_classic` is the prompt from
    before them, used while FEATURE_CONVERSATIONAL_PLANNER is off."""
    return "system" if config.FEATURE_CONVERSATIONAL_PLANNER else "system_classic"


def build_params(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Request body for one call. Tools and system come first and never change,
    so they stay in the prompt cache; the top-level breakpoint caches the history."""
    return {
        "model": client.chat_model(),
        "max_tokens": MAX_TOKENS,
        "system": client.cached_system(system_prompt_name()),
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
    conversational = config.FEATURE_CONVERSATIONAL_PLANNER
    intake = session.ctx.intake
    content: str | list[dict[str, Any]] = message
    if conversational:
        intake.start_turn()
        if intake.should_offer_defaults():
            content = [
                {"type": "text", "text": message},
                {"type": "text", "text": OFFER_DEFAULTS_NOTE},
            ]
    session.history.append({"role": "user", "content": content})
    input_errors: Counter[str] = Counter()
    was_built = intake.built
    quick_replies: list[str] = []
    reply = ChatTurn(role="assistant")
    session.transcript += [ChatTurn(role="student", text=message), reply]
    after_tool = False

    def say(text: str) -> ChatEvent:
        # The same joining rule as the chat panel: text after a tool starts a paragraph.
        nonlocal after_tool
        reply.text += ("\n\n" if after_tool and reply.text else "") + text
        after_tool = False
        return ChatEvent(type="text", text=text)

    def fail(text: str) -> ChatEvent:
        reply.error = text
        return ChatEvent(type="error", text=text)

    try:
        for _ in range(MAX_MODEL_CALLS):
            result: TurnResult | None = None
            # AI-07: the model's `<<choices: ...>>` line is not shown as text; it
            # becomes quick replies on the `done` event.
            choices = ChoiceFilter() if conversational else None
            for item in caller(build_params(session.history)):
                if isinstance(item, str):
                    shown = choices.feed(item) if choices else item
                    if shown:
                        yield say(shown)
                else:
                    result = item
            if result is None:
                raise RuntimeError("Caller ended without a TurnResult")
            if choices:
                tail = choices.finish()
                if tail:
                    yield say(tail)
                quick_replies = choices.choices

            session.history.append({"role": "assistant", "content": result.content})

            if result.stop_reason == "refusal":
                yield fail(ERR_DECLINED)
                break

            tool_uses = [b for b in result.content if b.get("type") == "tool_use"]
            if not tool_uses:
                break

            results: list[dict[str, Any]] = []
            give_up = False
            truncated = result.stop_reason == "max_tokens"
            after_tool = True
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
                if conversational and name == "build_schedules":
                    _show_build(reply, output)
                yield ChatEvent(type="tool_result", tool=name, data=output)
                results.append(_tool_result(block["id"], json.dumps(output)))

            # Every tool_use gets its tool_result, even when we stop, so the
            # history stays valid for the student's next message.
            session.history.append({"role": "user", "content": results})
            if give_up:
                yield fail(ERR_RETRY_FAILED)
                break
        else:
            yield fail(ERR_TOO_LONG)
    except client.ClaudeNotConfiguredError:
        yield fail(ERR_NOT_CONFIGURED)
    except anthropic.APIError:
        # The SDK already retried rate limits and server errors with backoff.
        yield fail(ERR_UNAVAILABLE)

    if conversational:
        intake.end_turn(built_this_turn=intake.built and not was_built)
        # AI-08: a schedule card has its own two replies ("This works", "Change
        # something"), and the "no schedule fits" hint has exactly one.
        if reply.schedule is not None:
            quick_replies = []
        elif reply.relaxation is not None:
            quick_replies = [APPLY_RELAXATION]
        if quick_replies:
            reply.quick_replies = quick_replies
            yield ChatEvent(type="done", data={"quick_replies": quick_replies})
            return
    yield ChatEvent(type="done")
