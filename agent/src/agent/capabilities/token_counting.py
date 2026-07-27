"""Provider-native, fail-closed input token counting."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import ModelRequest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage


class InputTokenCountError(RuntimeError):
    """Raised when an exact provider-native input count is unavailable."""


type InputTokenCounter = Callable[[ModelRequest[Any]], Awaitable[int]]


async def count_anthropic_input_tokens(request: ModelRequest[Any]) -> int:
    """Count the exact Anthropic request input, including the final tool schemas.

    ``ChatAnthropic`` exposes Anthropic's official token-counting endpoint through
    ``get_num_tokens_from_messages``. The helper is synchronous, so it runs in a
    worker thread while the caller owns the enclosing run-deadline timeout.
    """
    model = request.model
    if not isinstance(model, ChatAnthropic):
        raise InputTokenCountError(
            "exact input counting requires the server-owned ChatAnthropic model"
        )

    messages: list[BaseMessage] = []
    if request.system_message is not None:
        messages.append(request.system_message)
    messages.extend(request.messages)

    try:
        token_count = await asyncio.to_thread(
            model.get_num_tokens_from_messages,
            messages,
            tools=request.tools,
        )
    except Exception as exc:
        raise InputTokenCountError(
            "Anthropic input token counting failed before generation"
        ) from exc

    if (
        not isinstance(token_count, int)
        or isinstance(token_count, bool)
        or token_count < 0
    ):
        raise InputTokenCountError("Anthropic returned a malformed input token count")
    return token_count


__all__ = [
    "InputTokenCountError",
    "InputTokenCounter",
    "count_anthropic_input_tokens",
]
