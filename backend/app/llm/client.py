"""Claude API client setup (AI-02).

The only place the app builds an Anthropic client. Backend only: the key is read
from the server environment and never reaches the frontend.

- Model names come from `CLAUDE_MODEL_CHAT` / `CLAUDE_MODEL_BULK` (app.config).
  Never hard-code a model name anywhere else.
- Rate limits and 5xx errors are retried with exponential backoff by the SDK
  (`MAX_RETRIES`).
- The system prompt is sent with `cache_control` so it is cached between turns.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Any

import anthropic

from app import config

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# SDK retries 408/409/429/5xx and connection errors with exponential backoff.
MAX_RETRIES = 4
TIMEOUT_S = 60.0

# Server-side refusal fallback: if the chat model declines for policy reasons the API
# re-runs the turn on the model's default fallback. On a model without fallback
# support the request just runs on the requested model, so this is safe to always send.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeNotConfiguredError(RuntimeError):
    """ANTHROPIC_API_KEY is not set on the server."""


def is_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


@cache
def get_client() -> anthropic.Anthropic:
    """Shared client. Raises ClaudeNotConfiguredError when the key is missing,
    so callers can show a clear message instead of a stack trace."""
    if not is_configured():
        raise ClaudeNotConfiguredError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add the key."
        )
    return anthropic.Anthropic(max_retries=MAX_RETRIES, timeout=TIMEOUT_S)


def chat_model() -> str:
    """Audits, chat to constraints, explanations, mentor reasons, email drafts."""
    return config.CLAUDE_MODEL_CHAT


def bulk_model() -> str:
    """Prerequisite fallback parsing, topic tags, bio summaries."""
    return config.CLAUDE_MODEL_BULK


@cache
def load_prompt(name: str) -> str:
    """Read `prompts/<name>.md`. Cached, so the text is byte-identical on every
    request and the prompt cache keeps hitting."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def cached_system(name: str = "system") -> list[dict[str, Any]]:
    """System prompt as a content block with a cache breakpoint. Nothing that
    changes per request (dates, session data) may go in here."""
    return [
        {
            "type": "text",
            "text": load_prompt(name),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def chat_fallback_options() -> dict[str, Any]:
    """Extra arguments for `client.beta.messages.stream(...)` on chat-model calls."""
    return {"betas": [FALLBACK_BETA], "fallbacks": "default"}
