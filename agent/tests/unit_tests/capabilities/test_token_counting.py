"""Provider-native input token counting contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    message_chunk_to_message,
)
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from openai.resources.responses.input_tokens import AsyncInputTokens

from agent.capabilities.budget import RunBudget
from agent.capabilities.token_counting import (
    _OPENAI_INPUT_TOKEN_FIELDS,
    OPENAI_GUEST_MAX_OUTPUT_TOKENS,
    OPENAI_GUEST_MODEL_NAME,
    OPENAI_GUEST_RESPONSE_MODEL_NAMES,
    OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH,
    OPENAI_GUEST_TIMEOUT_SECONDS,
    InputTokenCountError,
    _capture_openai_generation_payload,
    _count_openai_responses_input_tokens,
    _openai_input_count_payload,
    count_anthropic_input_tokens,
    count_openai_input_tokens,
    openai_guest_safety_identifier,
)

_GUEST_IDENTITY = "anon:00000000-0000-4000-8000-000000000001"
_GUEST_SAFETY_IDENTIFIER = openai_guest_safety_identifier(_GUEST_IDENTITY)


@tool
def exact_count_tool(query: str) -> str:
    """Tool whose complete schema must reach the provider's official counter."""
    return query


def _openai_guest_model(**overrides) -> ChatOpenAI:
    settings = {
        "model": OPENAI_GUEST_MODEL_NAME,
        "api_key": "test-provider-token-count-key",
        "max_tokens": OPENAI_GUEST_MAX_OUTPUT_TOKENS,
        "max_retries": 0,
        "timeout": OPENAI_GUEST_TIMEOUT_SECONDS,
        "use_responses_api": True,
        "output_version": "responses/v1",
        "reasoning": {"context": "current_turn", "effort": "none"},
        "store": False,
        "truncation": "disabled",
        "cache": False,
        "extra_body": {"safety_identifier": _GUEST_SAFETY_IDENTIFIER},
    }
    settings.update(overrides)
    return ChatOpenAI(**settings)


def test_openai_guest_safety_identifier_is_stable_private_and_scoped():
    other_identity = "anon:00000000-0000-4000-8000-000000000002"

    assert openai_guest_safety_identifier(_GUEST_IDENTITY) == _GUEST_SAFETY_IDENTIFIER
    assert openai_guest_safety_identifier(other_identity) != _GUEST_SAFETY_IDENTIFIER
    assert _GUEST_SAFETY_IDENTIFIER.startswith("guest_")
    assert len(_GUEST_SAFETY_IDENTIFIER) == OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH
    assert _GUEST_IDENTITY not in _GUEST_SAFETY_IDENTIFIER
    with pytest.raises(ValueError, match="canonical anonymous identity"):
        openai_guest_safety_identifier("owner@example.com")


async def test_openai_official_counter_receives_final_stateless_payload(
    monkeypatch,
):
    observed = {}

    async def official_count(_self, **payload):
        observed["payload"] = payload
        return SimpleNamespace(input_tokens=321)

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", official_count)
    request = ModelRequest(
        model=_openai_guest_model(),
        system_message=SystemMessage(content="final system prompt"),
        messages=[
            HumanMessage(content="first dense 🧑🏽‍💻 input"),
            AIMessage(content="prior answer", id="resp_must_not_be_reused"),
            HumanMessage(content="final question"),
        ],
        tools=[exact_count_tool],
        tool_choice="required",
    )

    count = await count_openai_input_tokens(request)

    assert count == 321
    assert "safety_identifier" not in observed["payload"]
    assert observed["payload"] == {
        "input": [
            {
                "content": "final system prompt",
                "role": "system",
                "type": "message",
            },
            {
                "content": "first dense 🧑🏽‍💻 input",
                "role": "user",
                "type": "message",
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "prior answer",
                        "annotations": [],
                    }
                ],
            },
            {
                "content": "final question",
                "role": "user",
                "type": "message",
            },
        ],
        "model": OPENAI_GUEST_MODEL_NAME,
        "reasoning": {"context": "current_turn", "effort": "none"},
        "tool_choice": "required",
        "tools": [
            {
                "type": "function",
                "name": "exact_count_tool",
                "description": (
                    "Tool whose complete schema must reach the provider's official "
                    "counter."
                ),
                "parameters": {
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "type": "object",
                },
            }
        ],
        "truncation": "disabled",
    }


async def test_openai_counter_preserves_the_complete_stateless_tool_transcript(
    monkeypatch,
):
    observed = {}

    async def official_count(_self, **payload):
        observed["payload"] = payload
        return SimpleNamespace(input_tokens=42)

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", official_count)
    request = ModelRequest(
        model=_openai_guest_model(),
        messages=[
            HumanMessage(content="use the exact tool"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "exact_count_tool",
                        "args": {"query": "needle"},
                        "id": "call_exact_1",
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(content="found", tool_call_id="call_exact_1"),
            HumanMessage(content="finish without provider state"),
        ],
        tools=[exact_count_tool],
    )

    assert await count_openai_input_tokens(request) == 42
    assert observed["payload"]["input"] == [
        {
            "content": "use the exact tool",
            "role": "user",
            "type": "message",
        },
        {
            "type": "function_call",
            "name": "exact_count_tool",
            "arguments": '{"query": "needle"}',
            "call_id": "call_exact_1",
        },
        {
            "type": "function_call_output",
            "output": "found",
            "call_id": "call_exact_1",
        },
        {
            "content": "finish without provider state",
            "role": "user",
            "type": "message",
        },
    ]
    assert "previous_response_id" not in observed["payload"]
    assert "conversation" not in observed["payload"]


async def test_openai_counter_sdk_boundary_is_exact_and_has_no_retry(monkeypatch):
    payload = {
        "input": [{"type": "message", "role": "user", "content": "count me"}],
        "model": OPENAI_GUEST_MODEL_NAME,
        "reasoning": {"context": "current_turn", "effort": "none"},
        "truncation": "disabled",
    }
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.openai.com/v1/responses/input_tokens"
        assert request.headers.get("authorization") == (
            "Bearer test-provider-token-count-key"
        )
        assert json.loads(request.content) == payload
        assert set(request.extensions["timeout"].values()) == {
            OPENAI_GUEST_TIMEOUT_SECONDS
        }
        return httpx.Response(
            200,
            request=request,
            json={
                "object": "response.input_tokens",
                "input_tokens": 321,
            },
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    assert (
        await _count_openai_responses_input_tokens(
            payload,
            http_client=client,
        )
        == 321
    )
    assert len(requests) == 1

    failures = 0

    async def fail_once(request: httpx.Request) -> httpx.Response:
        nonlocal failures
        failures += 1
        return httpx.Response(
            500,
            request=request,
            json={"error": {"message": "do not retry"}},
        )

    failing_client = httpx.AsyncClient(transport=httpx.MockTransport(fail_once))
    with pytest.raises(InputTokenCountError, match="failed before generation"):
        await _count_openai_responses_input_tokens(
            payload,
            http_client=failing_client,
        )
    assert failures == 1


def _stream_response_fixture() -> dict:
    return {
        "id": "resp_mock_stream",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": OPENAI_GUEST_MAX_OUTPUT_TOKENS,
        "model": OPENAI_GUEST_MODEL_NAME,
        "output": [
            {
                "id": "msg_mock_stream",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "hello",
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            }
        ],
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {
            "context": "current_turn",
            "effort": "none",
            "summary": None,
        },
        "store": False,
        "temperature": None,
        "text": {"format": {"type": "text"}},
        "tool_choice": "auto",
        "tools": [],
        "top_p": None,
        "truncation": "disabled",
        "usage": {
            "input_tokens": 3,
            "input_tokens_details": {
                "cache_write_tokens": 1,
                "cached_tokens": 0,
            },
            "output_tokens": 2,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 5,
        },
        "metadata": {},
    }


async def test_openai_native_stream_and_capture_have_identical_token_payloads():
    streamed_payload = {}
    response = _stream_response_fixture()
    events = [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": response,
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 1,
            "output_index": 0,
            "content_index": 0,
            "item_id": "msg_mock_stream",
            "delta": "hel",
            "logprobs": [],
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 2,
            "output_index": 0,
            "content_index": 0,
            "item_id": "msg_mock_stream",
            "delta": "lo",
            "logprobs": [],
        },
        {
            "type": "response.output_text.done",
            "sequence_number": 3,
            "output_index": 0,
            "content_index": 0,
            "item_id": "msg_mock_stream",
            "text": "hello",
            "logprobs": [],
        },
        {
            "type": "response.completed",
            "sequence_number": 4,
            "response": response,
        },
    ]

    async def stream_handler(request: httpx.Request) -> httpx.Response:
        streamed_payload.update(json.loads(request.content))
        body = "".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
        )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=body,
        )

    request = ModelRequest(
        model=_openai_guest_model(),
        system_message=SystemMessage(content="same stream system"),
        messages=[HumanMessage(content="same stream question")],
        tools=[exact_count_tool],
        tool_choice="required",
    )
    captured_payload = await _capture_openai_generation_payload(request)

    async_transport = httpx.MockTransport(stream_handler)
    sync_transport = httpx.MockTransport(
        lambda _request: pytest.fail("native async streaming used the sync client")
    )
    with httpx.Client(transport=sync_transport) as sync_client:
        async with httpx.AsyncClient(transport=async_transport) as async_client:
            stream_model = _openai_guest_model(
                http_client=sync_client,
                http_async_client=async_client,
            ).bind_tools(request.tools, tool_choice=request.tool_choice)
            chunks = [
                chunk
                async for chunk in stream_model.astream(
                    [request.system_message, *request.messages]
                )
            ]

    assert (
        "".join(
            block["text"]
            for chunk in chunks
            for block in chunk.content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
        == "hello"
    )
    assert chunks[-1].usage_metadata == {
        "input_tokens": 3,
        "output_tokens": 2,
        "total_tokens": 5,
        "input_token_details": {
            "cache_creation": 1,
            "cache_read": 0,
        },
        "output_token_details": {"reasoning": 0},
    }
    assert chunks[-1].response_metadata["model_provider"] == "openai"
    assert (
        chunks[-1].response_metadata["model_name"] in OPENAI_GUEST_RESPONSE_MODEL_NAMES
    )
    assert captured_payload["stream"] is False
    assert captured_payload["safety_identifier"] == _GUEST_SAFETY_IDENTIFIER
    assert streamed_payload["stream"] is True
    assert set(captured_payload) == set(streamed_payload)
    assert {
        key
        for key in captured_payload
        if captured_payload[key] != streamed_payload[key]
    } == {"stream"}
    assert {
        key: captured_payload[key]
        for key in captured_payload
        if key in _OPENAI_INPUT_TOKEN_FIELDS
    } == {
        key: streamed_payload[key]
        for key in streamed_payload
        if key in _OPENAI_INPUT_TOKEN_FIELDS
    }

    assembled_chunk = chunks[0]
    for chunk in chunks[1:]:
        assembled_chunk += chunk
    assembled = message_chunk_to_message(assembled_chunk)
    budget = RunBudget()
    attempt = budget.reserve_model_attempt()
    reservation = budget.reserve_model_input(attempt, input_tokens=3)
    budget._settle_model_response(
        reservation,
        ModelResponse(result=[assembled]),
        model_provider="openai",
        expected_response_models=OPENAI_GUEST_RESPONSE_MODEL_NAMES,
    )
    snapshot = budget.finalize()
    assert snapshot.charged_tokens == 5
    assert snapshot.provider_usage_complete is True
    assert (
        snapshot.provider_input_tokens,
        snapshot.provider_output_tokens,
        snapshot.provider_cache_read_input_tokens,
        snapshot.provider_cache_write_input_tokens,
    ) == (2, 2, 0, 1)


@pytest.mark.parametrize("result", [-1, True, "321"])
async def test_openai_malformed_official_count_fails_closed(
    monkeypatch,
    result,
):
    async def malformed_count(_self, **_payload):
        return SimpleNamespace(input_tokens=result)

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", malformed_count)
    request = ModelRequest(
        model=_openai_guest_model(),
        messages=[HumanMessage(content="never estimate this")],
        tools=[],
    )

    with pytest.raises(InputTokenCountError, match="malformed"):
        await count_openai_input_tokens(request)


async def test_openai_official_counter_error_is_wrapped_without_fallback(
    monkeypatch,
):
    async def unavailable(_self, **_payload):
        raise ConnectionError("count endpoint unavailable")

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", unavailable)
    request = ModelRequest(
        model=_openai_guest_model(),
        messages=[HumanMessage(content="never estimate this")],
        tools=[],
    )

    with pytest.raises(
        InputTokenCountError,
        match="failed before generation",
    ) as exc_info:
        await count_openai_input_tokens(request)

    assert isinstance(exc_info.value.__cause__, ConnectionError)


@pytest.mark.parametrize("invalid_key", ["", " ", "test key", "\ttest-key"])
async def test_openai_invalid_counter_key_fails_before_provider_boundary(
    monkeypatch,
    invalid_key,
):
    async def unexpected_provider_call(_self, **_payload):
        pytest.fail("missing-key requests must not reach the provider boundary")

    monkeypatch.setenv("OPENAI_API_KEY", invalid_key)
    monkeypatch.setattr(AsyncInputTokens, "count", unexpected_provider_call)
    request = ModelRequest(
        model=_openai_guest_model(),
        messages=[HumanMessage(content="never estimate this")],
        tools=[],
    )

    with pytest.raises(InputTokenCountError, match="OPENAI_API_KEY is required"):
        await count_openai_input_tokens(request)


@pytest.mark.parametrize(
    "model_override",
    [
        {"model": "gpt-5.4-mini"},
        {"reasoning": {"effort": "none"}},
        {"reasoning": {"context": "all_turns", "effort": "none"}},
        {"use_previous_response_id": True},
        {"max_tokens": OPENAI_GUEST_MAX_OUTPUT_TOKENS + 1},
        {"streaming": False},
        {"verbosity": "high"},
        {"service_tier": "flex"},
        {"stream_usage": False},
        {"seed": 7},
        {"organization": "unreviewed-organization"},
        {"extra_body": {"safety_identifier": "guest_invalid"}},
    ],
)
async def test_openai_server_model_contract_drift_fails_before_counter(
    monkeypatch,
    model_override,
):
    async def unexpected_provider_call(_self, **_payload):
        pytest.fail("drifted models must not reach the provider boundary")

    monkeypatch.setenv("OPENAI_API_KEY", "test-provider-token-count-key")
    monkeypatch.setattr(AsyncInputTokens, "count", unexpected_provider_call)
    request = ModelRequest(
        model=_openai_guest_model(**model_override),
        messages=[HumanMessage(content="never count a drifted request")],
        tools=[],
    )

    with pytest.raises(InputTokenCountError, match="left its exact request contract"):
        await count_openai_input_tokens(request)


@pytest.mark.parametrize(
    "payload_drift",
    [
        {"previous_response_id": "resp_stateful"},
        {"conversation": "conv_stateful"},
    ],
)
def test_openai_stateful_generation_payload_drift_fails_closed(payload_drift):
    generation_payload = {
        "input": [{"type": "message", "role": "user", "content": "question"}],
        "max_output_tokens": OPENAI_GUEST_MAX_OUTPUT_TOKENS,
        "model": OPENAI_GUEST_MODEL_NAME,
        "reasoning": {"context": "current_turn", "effort": "none"},
        "safety_identifier": _GUEST_SAFETY_IDENTIFIER,
        "store": False,
        "stream": False,
        "truncation": "disabled",
        **payload_drift,
    }

    with pytest.raises(InputTokenCountError, match="stateless guest contract"):
        _openai_input_count_payload(generation_payload)


def test_openai_unreviewed_generation_field_fails_closed():
    generation_payload = {
        "input": [{"type": "message", "role": "user", "content": "question"}],
        "max_output_tokens": OPENAI_GUEST_MAX_OUTPUT_TOKENS,
        "model": OPENAI_GUEST_MODEL_NAME,
        "reasoning": {"context": "current_turn", "effort": "none"},
        "safety_identifier": _GUEST_SAFETY_IDENTIFIER,
        "store": False,
        "stream": False,
        "truncation": "disabled",
        "unreviewed_future_field": "changes tokenization",
    }

    with pytest.raises(InputTokenCountError, match="unreviewed request fields"):
        _openai_input_count_payload(generation_payload)


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
        model_settings={
            "cache_control": {
                "type": "ephemeral",
                "ttl": "5m",
            }
        },
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
        "kwargs": {
            "cache_control": {
                "type": "ephemeral",
                "ttl": "5m",
            }
        },
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
