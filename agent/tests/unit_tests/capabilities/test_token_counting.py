"""Provider-native input token counting contracts."""

from __future__ import annotations

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from agent.capabilities.token_counting import (
    InputTokenCountError,
    count_anthropic_input_tokens,
)


@tool
def exact_count_tool(query: str) -> str:
    """Tool whose complete schema must reach Anthropic's official counter."""
    return query


async def test_anthropic_official_counter_receives_final_messages_and_tools(
    monkeypatch,
):
    observed = {}

    def official_count(self, messages, tools=None, **kwargs):
        observed["self"] = self
        observed["messages"] = messages
        observed["tools"] = tools
        observed["kwargs"] = kwargs
        return 321

    monkeypatch.setattr(
        ChatAnthropic,
        "get_num_tokens_from_messages",
        official_count,
    )
    model = ChatAnthropic(
        model="claude-sonnet-4-6",
        anthropic_api_key="test-provider-token-count-key",
        max_tokens=2_048,
        max_retries=0,
        timeout=60,
    )
    request = ModelRequest(
        model=model,
        system_message=SystemMessage(content="final system prompt"),
        messages=[HumanMessage(content="dense 🧑🏽‍💻 input")],
        tools=[exact_count_tool],
    )

    count = await count_anthropic_input_tokens(request)

    assert count == 321
    assert observed == {
        "self": model,
        "messages": [
            request.system_message,
            *request.messages,
        ],
        "tools": [exact_count_tool],
        "kwargs": {},
    }


@pytest.mark.parametrize("result", [-1, True, "321"])
async def test_anthropic_malformed_official_count_fails_closed(
    monkeypatch,
    result,
):
    monkeypatch.setattr(
        ChatAnthropic,
        "get_num_tokens_from_messages",
        lambda _self, _messages, **_kwargs: result,
    )
    model = ChatAnthropic(
        model="claude-sonnet-4-6",
        anthropic_api_key="test-provider-token-count-key",
        max_tokens=2_048,
        max_retries=0,
        timeout=60,
    )
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="never estimate this")],
        tools=[],
    )

    with pytest.raises(InputTokenCountError, match="malformed"):
        await count_anthropic_input_tokens(request)


async def test_anthropic_counter_error_is_wrapped_without_fallback(monkeypatch):
    def unavailable(_self, _messages, **_kwargs):
        raise ConnectionError("count endpoint unavailable")

    monkeypatch.setattr(
        ChatAnthropic,
        "get_num_tokens_from_messages",
        unavailable,
    )
    model = ChatAnthropic(
        model="claude-sonnet-4-6",
        anthropic_api_key="test-provider-token-count-key",
        max_tokens=2_048,
        max_retries=0,
        timeout=60,
    )
    request = ModelRequest(
        model=model,
        messages=[HumanMessage(content="never estimate this")],
        tools=[],
    )

    with pytest.raises(InputTokenCountError, match="failed before generation"):
        await count_anthropic_input_tokens(request)
