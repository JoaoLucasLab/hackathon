"""Live smoke test: one tiny real call per model. Run by hand only:

    set -a; source .env; set +a
    pytest -m live backend/tests/test_llm_live.py
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.llm import client

pytestmark = pytest.mark.live


@pytest.mark.parametrize("model_fn", [client.chat_model, client.bulk_model])
def test_model_answers(model_fn: Callable[[], str]) -> None:
    if not client.is_configured():
        pytest.skip("ANTHROPIC_API_KEY not set")
    reply = client.get_client().messages.create(
        model=model_fn(),
        max_tokens=256,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": "Reply with the single word: ready"}],
    )
    text = "".join(b.text for b in reply.content if b.type == "text")
    assert "ready" in text.lower()


def test_api_accepts_the_strict_tool_schemas() -> None:
    """A 400 here means a schema uses something strict mode does not support."""
    if not client.is_configured():
        pytest.skip("ANTHROPIC_API_KEY not set")
    from app.llm.tools import tool_definitions

    reply = client.get_client().messages.create(
        model=client.bulk_model(),
        max_tokens=256,
        output_config={"effort": "low"},
        tools=tool_definitions(),
        messages=[{"role": "user", "content": "Reply with the single word: ready"}],
    )
    assert reply.stop_reason in {"end_turn", "tool_use"}
