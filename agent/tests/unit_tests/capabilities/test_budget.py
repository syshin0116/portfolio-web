"""Behavior tests for the atomic per-run resource ledger."""

from __future__ import annotations

import asyncio
import json
import pickle
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, asdict, replace
from threading import Barrier

import pytest
from anthropic.types import CacheCreation, Usage
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain.agents.middleware.types import ToolCallRequest
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.chat_models import _create_usage_metadata
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from agent.capabilities.budget import (
    DEFAULT_RUN_BUDGET_POLICY,
    CapabilityDeniedError,
    InvalidDelegationError,
    QuickJSReservation,
    RunBudget,
    RunBudgetExceededError,
    RunBudgetMiddleware,
    RunBudgetUnsettledError,
    TaskReservation,
)
from agent.capabilities.token_counting import InputTokenCountError

VALID_DESCRIPTION = """\
Question:
Find the exact Docker evidence.
Allowed corpus/method scope:
Published posts via exact retrieval only.
Expected output schema:
DocId and one evidence sentence.
Stopping condition:
Stop after one supported DocId.
"""


@tool
def cache_parity_tool(query: str) -> str:
    """Return a bounded value for prompt-cache parity testing."""
    return query


async def _zero_input_tokens(_request: ModelRequest) -> int:
    return 0


def _task_request(
    *,
    description: str = VALID_DESCRIPTION,
    subagent_type: str = "retrieval-researcher",
    configurable: dict | None = None,
) -> ToolCallRequest:
    runtime = ToolRuntime(
        state={},
        context=None,
        config={"configurable": configurable or {}},
        stream_writer=lambda _event: None,
        tool_call_id="task-call-1",
        store=None,
    )
    return ToolCallRequest(
        tool_call={
            "name": "task",
            "args": {
                "description": description,
                "subagent_type": subagent_type,
            },
            "id": "task-call-1",
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=runtime,
    )


def _quickjs_request() -> ToolCallRequest:
    runtime = ToolRuntime(
        state={},
        context=None,
        config={"configurable": {}},
        stream_writer=lambda _event: None,
        tool_call_id="eval-call-1",
        store=None,
    )
    return ToolCallRequest(
        tool_call={
            "name": "eval",
            "args": {"code": "21 * 2"},
            "id": "eval-call-1",
            "type": "tool_call",
        },
        tool=None,
        state={},
        runtime=runtime,
    )


def _middleware(
    budget: RunBudget,
    *,
    allow_subagents: bool = True,
    depth: int = 0,
) -> RunBudgetMiddleware:
    return RunBudgetMiddleware(
        budget,
        depth=depth,
        allow_subagents=allow_subagents,
        allowed_subagents=frozenset({"retrieval-researcher"}),
        input_token_counter=_zero_input_tokens,
        quickjs_tool_name="eval",
        allow_quickjs=True,
    )


def test_task_reservation_with_100_concurrent_attempts_commits_exactly_two():
    budget = RunBudget(clock=lambda: 0.0)
    barrier = Barrier(100)

    def reserve() -> TaskReservation | None:
        barrier.wait()
        try:
            return budget.reserve_task(depth=1)
        except RunBudgetExceededError:
            return None

    with ThreadPoolExecutor(max_workers=100) as executor:
        accepted = list(executor.map(lambda _index: reserve(), range(100)))
    reservations = [reservation for reservation in accepted if reservation is not None]

    assert len(reservations) == 2
    assert accepted.count(None) == 98
    assert asdict(budget.snapshot()) == {
        "policy_id": "owner-capability-lab-v2",
        "model_calls": 0,
        "model_reservations_in_flight": 0,
        "tool_calls": 2,
        "quickjs_calls": 0,
        "quickjs_in_flight": 0,
        "quickjs_output_bytes": 0,
        "task_calls": 2,
        "tasks_in_flight": 2,
        "charged_tokens": 4_096,
        "provider_input_tokens": 0,
        "provider_output_tokens": 0,
        "provider_cache_read_input_tokens": 0,
        "provider_cache_write_input_tokens": 0,
        "provider_usage_complete": True,
        "elapsed_ms": 0,
        "exhausted": True,
        "finalized": False,
    }

    for reservation in reservations:
        budget.finish_task(reservation)
    assert budget.snapshot().tasks_in_flight == 0


def test_quickjs_reservation_with_100_concurrent_attempts_commits_exactly_one():
    budget = RunBudget(clock=lambda: 0.0)
    barrier = Barrier(100)

    def reserve() -> QuickJSReservation | None:
        barrier.wait()
        try:
            return budget.reserve_quickjs()
        except RunBudgetExceededError:
            return None

    with ThreadPoolExecutor(max_workers=100) as executor:
        accepted = list(executor.map(lambda _index: reserve(), range(100)))
    reservations = [reservation for reservation in accepted if reservation is not None]

    assert len(reservations) == 1
    assert accepted.count(None) == 99
    snapshot = budget.snapshot()
    assert (
        snapshot.tool_calls,
        snapshot.quickjs_calls,
        snapshot.quickjs_in_flight,
        snapshot.quickjs_output_bytes,
    ) == (1, 1, 1, 4_096)

    budget.settle_quickjs(reservations[0], actual_output_bytes=100)
    snapshot = budget.snapshot()
    assert (snapshot.quickjs_in_flight, snapshot.quickjs_output_bytes) == (0, 100)


def test_quickjs_output_reservation_refunds_only_measured_unused_bytes():
    policy = replace(
        DEFAULT_RUN_BUDGET_POLICY,
        max_quickjs_calls=3,
        max_quickjs_output_bytes=100,
        max_quickjs_total_output_bytes=150,
    )
    budget = RunBudget(policy, clock=lambda: 0.0)
    first = budget.reserve_quickjs()
    budget.settle_quickjs(first, actual_output_bytes=50)
    second = budget.reserve_quickjs()

    assert budget.snapshot().quickjs_output_bytes == 150
    budget.settle_quickjs(second, actual_output_bytes=100)

    with pytest.raises(RunBudgetExceededError, match="output"):
        budget.reserve_quickjs()
    assert budget.snapshot().quickjs_calls == 2


def test_repeated_quickjs_execution_stops_at_the_run_total():
    budget = RunBudget(clock=lambda: 0.0)

    for _index in range(4):
        reservation = budget.reserve_quickjs()
        budget.settle_quickjs(reservation, actual_output_bytes=0)

    with pytest.raises(RunBudgetExceededError, match="execution"):
        budget.reserve_quickjs()
    snapshot = budget.snapshot()
    assert (
        snapshot.tool_calls,
        snapshot.quickjs_calls,
        snapshot.quickjs_in_flight,
        snapshot.quickjs_output_bytes,
    ) == (4, 4, 0, 0)


async def test_quickjs_handler_cancellation_releases_only_the_execution_slot():
    budget = RunBudget()
    middleware = _middleware(budget)
    entered = asyncio.Event()

    async def block(_request):
        entered.set()
        await asyncio.Event().wait()

    call = asyncio.create_task(middleware.awrap_tool_call(_quickjs_request(), block))
    await entered.wait()
    call.cancel()

    with pytest.raises(asyncio.CancelledError):
        await call

    snapshot = budget.snapshot()
    assert (
        snapshot.tool_calls,
        snapshot.quickjs_calls,
        snapshot.quickjs_in_flight,
        snapshot.quickjs_output_bytes,
    ) == (1, 1, 0, 4_096)


async def test_quickjs_middleware_rejects_concurrent_execution_before_handler():
    budget = RunBudget()
    middleware = _middleware(budget)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def block(_request):
        entered.set()
        await release.wait()
        return ToolMessage(content="{}", tool_call_id="eval-call-1")

    first = asyncio.create_task(middleware.awrap_tool_call(_quickjs_request(), block))
    await entered.wait()
    second_handler_called = False

    async def should_not_run(_request):
        nonlocal second_handler_called
        second_handler_called = True
        return ToolMessage(content="{}", tool_call_id="eval-call-2")

    with pytest.raises(RunBudgetExceededError, match="concurrency"):
        await middleware.awrap_tool_call(_quickjs_request(), should_not_run)
    assert second_handler_called is False

    release.set()
    await first
    snapshot = budget.snapshot()
    assert (
        snapshot.tool_calls,
        snapshot.quickjs_calls,
        snapshot.quickjs_in_flight,
        snapshot.quickjs_output_bytes,
    ) == (1, 1, 0, 2)


async def test_unauthorized_quickjs_fails_before_spending_budget():
    budget = RunBudget()
    middleware = RunBudgetMiddleware(
        budget,
        depth=0,
        allow_subagents=False,
        allowed_subagents=frozenset(),
        quickjs_tool_name="eval",
        allow_quickjs=False,
    )
    called = False

    async def should_not_run(_request):
        nonlocal called
        called = True
        return ToolMessage(content="unexpected", tool_call_id="eval-call-1")

    with pytest.raises(CapabilityDeniedError, match="QuickJS"):
        await middleware.awrap_tool_call(_quickjs_request(), should_not_run)
    assert called is False
    snapshot = budget.snapshot()
    assert (
        snapshot.tool_calls,
        snapshot.quickjs_calls,
        snapshot.quickjs_output_bytes,
    ) == (0, 0, 0)


def test_task_token_tranche_is_atomic_under_100_way_contention():
    policy = replace(
        DEFAULT_RUN_BUDGET_POLICY,
        max_tool_calls=100,
        max_task_calls=100,
        max_tasks_in_flight=100,
        max_total_tokens=2_048,
    )
    budget = RunBudget(policy, clock=lambda: 0.0)
    barrier = Barrier(100)

    def reserve() -> TaskReservation | None:
        barrier.wait()
        try:
            return budget.reserve_task(depth=1)
        except RunBudgetExceededError:
            return None

    with ThreadPoolExecutor(max_workers=100) as executor:
        attempts = list(executor.map(lambda _index: reserve(), range(100)))
    reservations = [reservation for reservation in attempts if reservation is not None]

    assert len(reservations) == 1
    assert attempts.count(None) == 99
    snapshot = budget.snapshot()
    assert (
        snapshot.tool_calls,
        snapshot.task_calls,
        snapshot.tasks_in_flight,
        snapshot.charged_tokens,
    ) == (1, 1, 1, 2_048)

    budget.finish_task(reservations[0])


def test_task_tranche_transfers_to_first_child_model_without_double_charge():
    budget = RunBudget(clock=lambda: 0.0)
    task = budget.reserve_task(depth=1)
    assert budget.snapshot().charged_tokens == 2_048

    first_model = budget.reserve_model(
        input_tokens=100,
        task_reservation=task,
    )
    assert budget.snapshot().charged_tokens == 2_148
    budget.settle_model(first_model, actual_tokens=120)
    assert budget.snapshot().charged_tokens == 120

    second_model = budget.reserve_model(
        input_tokens=100,
        task_reservation=task,
    )
    assert budget.snapshot().charged_tokens == 2_268
    budget.settle_model(second_model, actual_tokens=120)
    budget.finish_task(task)
    assert budget.snapshot().charged_tokens == 240


def test_failed_task_reservation_does_not_partially_spend_any_counter():
    budget = RunBudget()

    with pytest.raises(RunBudgetExceededError, match="depth"):
        budget.reserve_task(depth=2)

    snapshot = budget.snapshot()
    assert (
        snapshot.model_calls,
        snapshot.tool_calls,
        snapshot.task_calls,
        snapshot.tasks_in_flight,
        snapshot.charged_tokens,
    ) == (0, 0, 0, 0, 0)
    assert snapshot.exhausted is True


async def test_task_handler_error_returns_only_the_in_flight_slot():
    budget = RunBudget()
    middleware = _middleware(budget)

    async def fail(_request):
        raise RuntimeError("child failed")

    with pytest.raises(RuntimeError, match="child failed"):
        await middleware.awrap_tool_call(_task_request(), fail)

    snapshot = budget.snapshot()
    assert (
        snapshot.tool_calls,
        snapshot.task_calls,
        snapshot.tasks_in_flight,
        snapshot.charged_tokens,
    ) == (1, 1, 0, 2_048)


async def test_task_handler_cancellation_returns_only_the_in_flight_slot():
    budget = RunBudget()
    middleware = _middleware(budget)
    entered = asyncio.Event()

    async def block(_request):
        entered.set()
        await asyncio.Event().wait()

    call = asyncio.create_task(middleware.awrap_tool_call(_task_request(), block))
    await entered.wait()
    call.cancel()

    with pytest.raises(asyncio.CancelledError):
        await call

    snapshot = budget.snapshot()
    assert (
        snapshot.tool_calls,
        snapshot.task_calls,
        snapshot.tasks_in_flight,
        snapshot.charged_tokens,
    ) == (1, 1, 0, 2_048)


async def test_model_usage_metadata_refunds_unused_token_reservation():
    budget = RunBudget()
    middleware = _middleware(budget)
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        messages=[],
        tools=[],
    )

    async def respond(_request):
        return ModelResponse(
            result=[
                AIMessage(
                    content="bounded",
                    usage_metadata={
                        "input_tokens": 75,
                        "output_tokens": 25,
                        "total_tokens": 100,
                    },
                )
            ]
        )

    response = await middleware.awrap_model_call(request, respond)

    assert response.result[0].content == "bounded"
    assert (budget.snapshot().model_calls, budget.snapshot().charged_tokens) == (
        1,
        100,
    )
    snapshot = budget.snapshot()
    assert snapshot.provider_usage_complete is False
    assert snapshot.provider_input_tokens is None
    assert snapshot.provider_output_tokens is None
    assert snapshot.provider_cache_read_input_tokens is None
    assert snapshot.provider_cache_write_input_tokens is None


async def test_missing_model_usage_metadata_never_refunds_reservation():
    budget = RunBudget()
    middleware = _middleware(budget)
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        messages=[],
        tools=[],
    )

    async def respond(_request):
        return ModelResponse(result=[AIMessage(content="no usage")])

    await middleware.awrap_model_call(request, respond)

    snapshot = budget.snapshot()
    assert snapshot.charged_tokens == 2_048
    assert snapshot.provider_usage_complete is False
    assert (
        snapshot.provider_input_tokens,
        snapshot.provider_output_tokens,
        snapshot.provider_cache_read_input_tokens,
        snapshot.provider_cache_write_input_tokens,
    ) == (None, None, None, None)


@pytest.mark.parametrize(
    ("anthropic_usage", "expected"),
    [
        (
            Usage(
                input_tokens=80,
                output_tokens=20,
                cache_read_input_tokens=30,
                cache_creation_input_tokens=10,
            ),
            (80, 20, 30, 10),
        ),
        (
            Usage(
                input_tokens=89,
                output_tokens=20,
                cache_read_input_tokens=11,
                cache_creation_input_tokens=20,
                cache_creation=CacheCreation(
                    ephemeral_5m_input_tokens=7,
                    ephemeral_1h_input_tokens=13,
                ),
            ),
            (89, 20, 11, 20),
        ),
        (
            Usage(
                input_tokens=80,
                output_tokens=20,
                cache_read_input_tokens=30,
                cache_creation_input_tokens=10,
                cache_creation=CacheCreation(
                    ephemeral_5m_input_tokens=0,
                    ephemeral_1h_input_tokens=0,
                ),
            ),
            (80, 20, 30, 10),
        ),
    ],
    ids=[
        "generic-cache-creation",
        "ttl-cache-creation",
        "zero-ttl-details-use-generic",
    ],
)
async def test_anthropic_usage_tracks_exact_provider_pricing_buckets(
    anthropic_usage,
    expected,
):
    budget = RunBudget()
    middleware = _middleware(budget)
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        messages=[],
        tools=[],
    )

    async def respond(_request):
        return ModelResponse(
            result=[
                AIMessage(
                    content="bounded",
                    usage_metadata=_create_usage_metadata(anthropic_usage),
                )
            ]
        )

    await middleware.awrap_model_call(request, respond)

    snapshot = budget.finalize()
    assert snapshot.provider_usage_complete is True
    assert (
        snapshot.provider_input_tokens,
        snapshot.provider_output_tokens,
        snapshot.provider_cache_read_input_tokens,
        snapshot.provider_cache_write_input_tokens,
    ) == expected
    assert snapshot.charged_tokens == 140


@pytest.mark.parametrize(
    "input_details",
    [
        {},
        {"cache_creation": 0},
        {"cache_read": 0},
        {"cache_read": -1, "cache_creation": 0},
        {"cache_read": 80, "cache_creation": 50},
        {
            "cache_read": 10,
            "cache_creation": 5,
            "ephemeral_5m_input_tokens": 5,
            "ephemeral_1h_input_tokens": 0,
        },
        {
            "cache_read": 10,
            "cache_creation": 0,
            "ephemeral_24h_input_tokens": 5,
        },
        {
            "cache_read": 10,
            "cache_creation": 0,
            "audio": 5,
        },
        {
            "cache_read": 10,
            "cache_creation": 0,
            "ephemeral_5m_input_tokens": 5,
        },
    ],
    ids=[
        "missing-cache-details",
        "missing-cache-read",
        "missing-cache-write",
        "negative-cache-read",
        "cache-sum-above-input",
        "generic-and-ttl-double-count",
        "unknown-ttl-bucket",
        "unknown-audio-bucket",
        "partial-ttl-buckets",
    ],
)
async def test_malformed_or_incomplete_anthropic_cache_usage_stays_incomplete(
    input_details,
):
    budget = RunBudget()
    middleware = _middleware(budget)
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        messages=[],
        tools=[],
    )

    async def respond(_request):
        message = AIMessage(content="bounded")
        message.usage_metadata = {
            "input_tokens": 120,
            "output_tokens": 20,
            "total_tokens": 140,
            "input_token_details": input_details,
        }
        return ModelResponse(result=[message])

    await middleware.awrap_model_call(request, respond)

    snapshot = budget.finalize()
    assert snapshot.provider_usage_complete is False
    assert (
        snapshot.provider_input_tokens,
        snapshot.provider_output_tokens,
        snapshot.provider_cache_read_input_tokens,
        snapshot.provider_cache_write_input_tokens,
    ) == (None, None, None, None)
    assert snapshot.charged_tokens == 140


def test_provider_usage_above_exact_reservation_closes_the_ledger():
    budget = RunBudget()
    reservation = budget.reserve_model(input_tokens=2)

    with pytest.raises(RunBudgetExceededError, match="exact model reservation"):
        budget.settle_model(reservation, actual_tokens=2_051)

    snapshot = budget.snapshot()
    assert snapshot.charged_tokens == 2_051
    assert snapshot.exhausted is True
    with pytest.raises(RunBudgetExceededError, match="already exhausted"):
        budget.reserve_tool()


@pytest.mark.parametrize(
    "second_usage",
    [
        None,
        {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": -1,
        },
        {
            "input_tokens": 2,
            "output_tokens": 3,
            "total_tokens": 10,
        },
    ],
    ids=["mixed-missing", "mixed-invalid", "mixed-inconsistent"],
)
async def test_any_missing_or_invalid_message_usage_prevents_partial_refund(
    second_usage,
):
    budget = RunBudget()
    middleware = _middleware(budget)
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        messages=[],
        tools=[],
    )
    second = AIMessage(content="untrusted usage")
    if second_usage is not None:
        second.usage_metadata = second_usage

    async def respond(_request):
        return ModelResponse(
            result=[
                AIMessage(
                    content="valid usage",
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                ),
                second,
            ]
        )

    await middleware.awrap_model_call(request, respond)

    snapshot = budget.snapshot()
    assert snapshot.charged_tokens == 2_048
    assert snapshot.provider_usage_complete is False


async def test_dense_unicode_input_is_rejected_before_calling_provider():
    budget = RunBudget()
    dense_content = "🧑🏽‍💻" * 7_000

    async def exact_dense_count(request):
        assert request.messages[0].content == dense_content
        return 56_000

    middleware = RunBudgetMiddleware(
        budget,
        depth=0,
        allow_subagents=True,
        allowed_subagents=frozenset({"retrieval-researcher"}),
        input_token_counter=exact_dense_count,
    )
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        messages=[HumanMessage(content=dense_content)],
        tools=[],
    )
    called = False

    async def should_not_run(_request):
        nonlocal called
        called = True
        return ModelResponse(result=[AIMessage(content="unexpected")])

    with pytest.raises(RunBudgetExceededError, match="token"):
        await middleware.awrap_model_call(request, should_not_run)

    assert called is False
    snapshot = budget.snapshot()
    assert (snapshot.model_calls, snapshot.charged_tokens) == (0, 0)
    assert snapshot.exhausted is True


async def test_native_prompt_cache_shape_is_counted_before_generation():
    model = ChatAnthropic(
        model="claude-sonnet-4-6",
        anthropic_api_key="test-cache-parity-key",
        max_tokens=2_048,
        max_retries=0,
        timeout=60,
    )
    budget = RunBudget()
    counted_requests = []
    generated_requests = []

    async def capture_count(request):
        counted_requests.append(request)
        return 1

    middleware = RunBudgetMiddleware(
        budget,
        depth=0,
        allow_subagents=True,
        allowed_subagents=frozenset(),
        input_token_counter=capture_count,
    )
    downstream_cache = AnthropicPromptCachingMiddleware(
        unsupported_model_behavior="ignore"
    )
    request = ModelRequest(
        model=model,
        system_message=SystemMessage(content="stable system prompt"),
        messages=[HumanMessage(content="count the final cache-tagged payload")],
        tools=[cache_parity_tool],
    )

    async def generate(final_request):
        generated_requests.append(final_request)
        return ModelResponse(
            result=[
                AIMessage(
                    content="bounded",
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )

    async def apply_downstream_cache(final_request):
        return await downstream_cache.awrap_model_call(final_request, generate)

    await middleware.awrap_model_call(request, apply_downstream_cache)

    assert len(counted_requests) == len(generated_requests) == 1
    counted = counted_requests[0]
    generated = generated_requests[0]
    assert counted.system_message == generated.system_message
    assert counted.messages == generated.messages
    assert counted.tools == generated.tools
    assert (
        counted.model_settings
        == generated.model_settings
        == {
            "cache_control": {
                "type": "ephemeral",
                "ttl": "5m",
            }
        }
    )
    assert counted.system_message.content[-1]["cache_control"] == {
        "type": "ephemeral",
        "ttl": "5m",
    }
    assert counted.tools[-1].extras["cache_control"] == {
        "type": "ephemeral",
        "ttl": "5m",
    }


@pytest.mark.parametrize("failure", ["error", "negative", "boolean", "string"])
async def test_exact_count_failure_is_closed_before_generation(failure):
    budget = RunBudget()

    async def failing_count(_request):
        if failure == "error":
            raise InputTokenCountError("official count unavailable")
        return {
            "negative": -1,
            "boolean": True,
            "string": "100",
        }[failure]

    middleware = RunBudgetMiddleware(
        budget,
        depth=0,
        allow_subagents=True,
        allowed_subagents=frozenset(),
        input_token_counter=failing_count,
    )
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        messages=[HumanMessage(content="do not generate")],
        tools=[],
    )
    generated = False

    async def provider(_request):
        nonlocal generated
        generated = True
        return ModelResponse(result=[AIMessage(content="unexpected")])

    with pytest.raises(InputTokenCountError):
        await middleware.awrap_model_call(request, provider)

    assert generated is False
    snapshot = budget.snapshot()
    assert (snapshot.model_calls, snapshot.charged_tokens) == (0, 0)
    assert snapshot.exhausted is True


async def test_exact_count_timeout_is_closed_before_generation(monkeypatch):
    budget = RunBudget()
    monkeypatch.setattr(RunBudget, "remaining_seconds", lambda _self: 0)

    async def blocked_count(_request):
        await asyncio.Event().wait()

    middleware = RunBudgetMiddleware(
        budget,
        depth=0,
        allow_subagents=True,
        allowed_subagents=frozenset(),
        input_token_counter=blocked_count,
    )
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        messages=[HumanMessage(content="do not generate")],
        tools=[],
    )
    generated = False

    async def provider(_request):
        nonlocal generated
        generated = True
        return ModelResponse(result=[AIMessage(content="unexpected")])

    with pytest.raises(InputTokenCountError, match="deadline"):
        await middleware.awrap_model_call(request, provider)

    assert generated is False
    assert budget.snapshot().model_calls == 0
    assert budget.snapshot().exhausted is True


async def test_unauthorized_middleware_hides_and_rejects_task_tool():
    budget = RunBudget()
    middleware = _middleware(budget, allow_subagents=False)
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        messages=[],
        tools=[{"name": "task"}, {"name": "read_post"}],
    )

    async def capture(filtered_request):
        assert filtered_request.tools == [{"name": "read_post"}]
        return ModelResponse(
            result=[
                AIMessage(
                    content="done",
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )

    await middleware.awrap_model_call(request, capture)

    async def unused(_request):
        return ToolMessage(content="unexpected", tool_call_id="task-call-1")

    with pytest.raises(CapabilityDeniedError, match="owner or eval"):
        await middleware.awrap_tool_call(_task_request(), unused)
    assert budget.snapshot().task_calls == 0


async def test_unauthorized_native_prompt_shape_drift_fails_before_count():
    budget = RunBudget()
    counted = False

    async def counter(_request):
        nonlocal counted
        counted = True
        return 1

    middleware = RunBudgetMiddleware(
        budget,
        depth=0,
        allow_subagents=False,
        allowed_subagents=frozenset(),
        input_token_counter=counter,
        native_subagent_prompt="expected native task prompt",
    )
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        system_message=HumanMessage(content="drifted prompt shape"),
        messages=[],
        tools=[{"name": "task"}],
    )

    with pytest.raises(CapabilityDeniedError, match="shape changed"):
        await middleware.awrap_model_call(
            request,
            lambda _request: pytest.fail("provider must not run"),
        )

    assert counted is False
    assert budget.snapshot().model_calls == 0


async def test_unauthorized_native_prompt_removal_preserves_later_capability_prompt():
    budget = RunBudget()
    counted_requests = []
    generated_requests = []
    native_prompt = "expected native task prompt"
    quickjs_prompt = "\n\nbounded QuickJS eval prompt"

    async def counter(request):
        counted_requests.append(request)
        return 1

    middleware = RunBudgetMiddleware(
        budget,
        depth=0,
        allow_subagents=False,
        allowed_subagents=frozenset(),
        input_token_counter=counter,
        native_subagent_prompt=native_prompt,
    )
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        system_message=SystemMessage(
            content=[
                {"type": "text", "text": "root prompt"},
                {"type": "text", "text": f"\n\n{native_prompt}"},
                {"type": "text", "text": quickjs_prompt},
            ]
        ),
        messages=[],
        tools=[{"name": "task"}, {"name": "quickjs_eval"}],
    )

    async def capture(filtered_request):
        generated_requests.append(filtered_request)
        return ModelResponse(
            result=[
                AIMessage(
                    content="done",
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        )

    await middleware.awrap_model_call(request, capture)

    assert len(counted_requests) == len(generated_requests) == 1
    assert counted_requests[0] == generated_requests[0]
    filtered = generated_requests[0]
    assert filtered.tools == [{"name": "quickjs_eval"}]
    assert filtered.system_message.content == [
        {"type": "text", "text": "root prompt"},
        {"type": "text", "text": quickjs_prompt},
    ]


async def test_duplicate_native_task_prompt_fails_closed_before_count():
    budget = RunBudget()
    counted = False
    native_prompt = "expected native task prompt"

    async def counter(_request):
        nonlocal counted
        counted = True
        return 1

    middleware = RunBudgetMiddleware(
        budget,
        depth=0,
        allow_subagents=False,
        allowed_subagents=frozenset(),
        input_token_counter=counter,
        native_subagent_prompt=native_prompt,
    )
    native_block = {"type": "text", "text": f"\n\n{native_prompt}"}
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        system_message=SystemMessage(content=[native_block, native_block]),
        messages=[],
        tools=[{"name": "task"}],
    )

    with pytest.raises(CapabilityDeniedError, match="shape changed"):
        await middleware.awrap_model_call(
            request,
            lambda _request: pytest.fail("provider must not run"),
        )

    assert counted is False
    assert budget.snapshot().model_calls == 0


@pytest.mark.parametrize(
    ("description", "subagent_type", "message"),
    [
        ("Question: incomplete", "retrieval-researcher", "exact section"),
        (
            f"{VALID_DESCRIPTION}\nQuestion:\nDuplicate.",
            "retrieval-researcher",
            "exact section once",
        ),
        (
            """\
Allowed corpus/method scope:
Published posts.
Question:
Find evidence.
Expected output schema:
One DocId.
Stopping condition:
Stop after one.
""",
            "retrieval-researcher",
            "stateless envelope",
        ),
        (
            f"{VALID_DESCRIPTION}{'가' * 6_000}",
            "retrieval-researcher",
            "too large",
        ),
        (VALID_DESCRIPTION, "client-defined-agent", "server-declared"),
    ],
)
async def test_malformed_task_delegation_fails_before_spending_budget(
    description,
    subagent_type,
    message,
):
    budget = RunBudget()
    middleware = _middleware(budget)

    async def unused(_request):
        return ToolMessage(content="unexpected", tool_call_id="task-call-1")

    with pytest.raises(InvalidDelegationError, match=message):
        await middleware.awrap_tool_call(
            _task_request(
                description=description,
                subagent_type=subagent_type,
            ),
            unused,
        )

    assert (budget.snapshot().tool_calls, budget.snapshot().task_calls) == (0, 0)


@pytest.mark.parametrize(
    "description",
    [
        VALID_DESCRIPTION.replace("Find the exact Docker evidence.", "   "),
        VALID_DESCRIPTION.replace(
            "Published posts via exact retrieval only.",
            "\t",
        ),
        VALID_DESCRIPTION.replace(
            "DocId and one evidence sentence.",
            " ",
        ),
        VALID_DESCRIPTION.replace(
            "Stop after one supported DocId.",
            "\t ",
        ),
    ],
    ids=[
        "empty-question",
        "empty-scope",
        "empty-output-schema",
        "empty-stopping-condition",
    ],
)
async def test_every_task_section_requires_non_whitespace_content(description):
    budget = RunBudget()
    middleware = _middleware(budget)

    async def unused(_request):
        return ToolMessage(content="unexpected", tool_call_id="task-call-1")

    with pytest.raises(InvalidDelegationError, match="non-whitespace"):
        await middleware.awrap_tool_call(
            _task_request(description=description),
            unused,
        )

    assert (budget.snapshot().tool_calls, budget.snapshot().task_calls) == (0, 0)


async def test_dynamic_response_format_config_fails_before_spending_budget():
    budget = RunBudget()
    middleware = _middleware(budget)

    async def unused(_request):
        return ToolMessage(content="unexpected", tool_call_id="task-call-1")

    with pytest.raises(CapabilityDeniedError, match="server-owned"):
        await middleware.awrap_tool_call(
            _task_request(
                configurable={
                    "__deepagents_subagent_response_format": {
                        "type": "object",
                    }
                }
            ),
            unused,
        )

    assert (budget.snapshot().tool_calls, budget.snapshot().task_calls) == (0, 0)


def test_run_budget_is_non_serializable_but_snapshot_is_bounded_json():
    budget = RunBudget(clock=lambda: 0.0)
    budget.reserve_model()

    with pytest.raises(TypeError, match="must not be serialized"):
        pickle.dumps(budget)

    encoded = json.dumps(asdict(budget.snapshot()), sort_keys=True)
    assert encoded == (
        '{"charged_tokens": 2048, "elapsed_ms": 0, "exhausted": false, '
        '"finalized": false, "model_calls": 1, '
        '"model_reservations_in_flight": 1, '
        '"policy_id": "owner-capability-lab-v2", '
        '"provider_cache_read_input_tokens": 0, '
        '"provider_cache_write_input_tokens": 0, '
        '"provider_input_tokens": 0, "provider_output_tokens": 0, '
        '"provider_usage_complete": true, '
        '"quickjs_calls": 0, "quickjs_in_flight": 0, '
        '"quickjs_output_bytes": 0, '
        '"task_calls": 0, "tasks_in_flight": 0, "tool_calls": 0}'
    )


def test_snapshot_is_observational_and_finalize_is_frozen_terminal_and_idempotent():
    now = [10.0]
    budget = RunBudget(clock=lambda: now[0])

    observation = budget.snapshot()
    assert observation.finalized is False
    assert observation.provider_usage_complete is True
    budget.reserve_tool()

    now[0] = 11.25
    finalized = budget.finalize()
    now[0] = 40.0

    assert finalized.finalized is True
    assert finalized.exhausted is False
    assert finalized.elapsed_ms == 1_250
    assert budget.finalize() is finalized
    assert budget.snapshot() is finalized
    with pytest.raises(FrozenInstanceError):
        finalized.model_calls = 99
    with pytest.raises(RunBudgetExceededError, match="finalized"):
        budget.reserve_tool()
    with pytest.raises(RunBudgetExceededError, match="finalized"):
        budget.exhaust()


def test_explicitly_exhausted_settled_budget_finalizes_without_looking_clean():
    budget = RunBudget(clock=lambda: 0.0)
    budget.exhaust()

    finalized = budget.finalize()

    assert finalized.finalized is True
    assert finalized.exhausted is True
    assert finalized.model_reservations_in_flight == 0
    assert finalized.tasks_in_flight == 0


def test_concurrent_finalize_calls_return_one_atomic_frozen_snapshot():
    budget = RunBudget(clock=lambda: 0.0)
    budget.reserve_tool()

    with ThreadPoolExecutor(max_workers=32) as executor:
        snapshots = list(executor.map(lambda _index: budget.finalize(), range(100)))

    assert all(snapshot is snapshots[0] for snapshot in snapshots)
    assert snapshots[0].finalized is True
    assert snapshots[0].tool_calls == 1


def test_open_model_and_task_reservations_are_visible_and_prevent_finalization():
    budget = RunBudget(clock=lambda: 0.0)
    task = budget.reserve_task(depth=1)
    model = budget.reserve_model(input_tokens=1, task_reservation=task)

    observation = budget.snapshot()
    assert observation.model_reservations_in_flight == 1
    assert observation.tasks_in_flight == 1
    assert observation.finalized is False

    with pytest.raises(
        RunBudgetUnsettledError,
        match="1 model and 1 task",
    ):
        budget.finalize()
    with pytest.raises(RunBudgetExceededError, match="terminal"):
        budget.reserve_tool()

    budget.settle_model(model, actual_tokens=None)
    budget.finish_task(task)
    finalized = budget.finalize()
    assert finalized.model_reservations_in_flight == 0
    assert finalized.tasks_in_flight == 0
    assert finalized.provider_usage_complete is False
    assert finalized.provider_input_tokens is None
    assert finalized.provider_output_tokens is None
    assert finalized.provider_cache_read_input_tokens is None
    assert finalized.provider_cache_write_input_tokens is None
    assert finalized.finalized is True


@pytest.mark.parametrize(
    ("elapsed", "succeeds"),
    [
        (89.999, True),
        (90.0, False),
        (90.001, False),
    ],
    ids=["below-deadline", "at-deadline", "above-deadline"],
)
def test_finalize_enforces_exact_elapsed_deadline_boundary(elapsed, succeeds):
    now = [10.0]
    budget = RunBudget(clock=lambda: now[0])
    now[0] += elapsed

    if succeeds:
        snapshot = budget.finalize()
        assert snapshot.finalized is True
        assert snapshot.exhausted is False
        assert snapshot.elapsed_ms == 89_999
    else:
        with pytest.raises(RunBudgetExceededError, match="elapsed-time"):
            budget.finalize()
        snapshot = budget.snapshot()
        assert snapshot.finalized is False
        assert snapshot.exhausted is True
        assert snapshot.elapsed_ms == 90_000


def test_finalize_uses_one_atomic_clock_observation_for_deadline_and_snapshot():
    ticks = iter((0.0, 89.999))
    budget = RunBudget(clock=lambda: next(ticks))

    snapshot = budget.finalize()

    assert snapshot.elapsed_ms == 89_999
    assert snapshot.exhausted is False
    assert snapshot.finalized is True


def test_elapsed_deadline_rejects_reservation_without_spending_counters():
    now = [10.0]
    budget = RunBudget(clock=lambda: now[0])
    now[0] = 100.0

    with pytest.raises(RunBudgetExceededError, match="elapsed-time"):
        budget.reserve_tool()

    assert asdict(budget.snapshot()) == {
        "policy_id": "owner-capability-lab-v2",
        "model_calls": 0,
        "model_reservations_in_flight": 0,
        "tool_calls": 0,
        "quickjs_calls": 0,
        "quickjs_in_flight": 0,
        "quickjs_output_bytes": 0,
        "task_calls": 0,
        "tasks_in_flight": 0,
        "charged_tokens": 0,
        "provider_input_tokens": 0,
        "provider_output_tokens": 0,
        "provider_cache_read_input_tokens": 0,
        "provider_cache_write_input_tokens": 0,
        "provider_usage_complete": True,
        "elapsed_ms": 90_000,
        "exhausted": True,
        "finalized": False,
    }


def test_exhaustion_is_terminal_but_open_reservations_can_be_cleaned_up():
    budget = RunBudget(clock=lambda: 0.0)
    task = budget.reserve_task(depth=1)
    model = budget.reserve_model(input_tokens=1, task_reservation=task)

    budget.exhaust()

    operations = (
        budget.remaining_seconds,
        budget.reserve_tool,
        lambda: budget.reserve_task(depth=1),
        lambda: budget.reserve_model(input_tokens=0),
    )
    for operation in operations:
        with pytest.raises(RunBudgetExceededError, match="already exhausted"):
            operation()

    budget.settle_model(model, actual_tokens=2)
    budget.finish_task(task)
    snapshot = budget.snapshot()
    assert snapshot.exhausted is True
    assert snapshot.tasks_in_flight == 0
    assert snapshot.charged_tokens == 2


def test_limit_failure_permanently_closes_every_new_reservation():
    budget = RunBudget()

    with pytest.raises(RunBudgetExceededError, match="depth"):
        budget.reserve_task(depth=2)

    with pytest.raises(RunBudgetExceededError, match="already exhausted"):
        budget.reserve_tool()
    with pytest.raises(RunBudgetExceededError, match="already exhausted"):
        budget.reserve_model()
    with pytest.raises(RunBudgetExceededError, match="already exhausted"):
        budget.reserve_task(depth=1)


def test_task_token_check_is_atomic_with_other_task_limits():
    policy = replace(
        DEFAULT_RUN_BUDGET_POLICY,
        max_total_tokens=2_048,
    )
    budget = RunBudget(policy)
    reservation = budget.reserve_model()
    budget.settle_model(reservation, actual_tokens=None)

    with pytest.raises(RunBudgetExceededError, match="token"):
        budget.reserve_task(depth=1)

    snapshot = budget.snapshot()
    assert (
        snapshot.model_calls,
        snapshot.tool_calls,
        snapshot.task_calls,
        snapshot.tasks_in_flight,
        snapshot.charged_tokens,
    ) == (1, 0, 0, 0, 2_048)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_model_calls", 1.5),
        ("max_tool_calls", True),
        ("max_quickjs_calls", 1.0),
        ("max_quickjs_output_bytes", 4_096.0),
        ("max_depth", 1.0),
        ("max_total_tokens", 48_000.0),
        ("max_elapsed_seconds", 90.0),
    ],
)
def test_policy_integer_limits_reject_non_integer_values(field, value):
    with pytest.raises(ValueError, match="positive and coherent"):
        replace(DEFAULT_RUN_BUDGET_POLICY, **{field: value})


def test_policy_rejects_quickjs_per_call_output_above_total():
    with pytest.raises(ValueError, match="positive and coherent"):
        replace(
            DEFAULT_RUN_BUDGET_POLICY,
            max_quickjs_output_bytes=16_385,
            max_quickjs_total_output_bytes=16_384,
        )


@pytest.mark.parametrize("input_tokens", [1.0, True, -1])
def test_model_reservation_rejects_non_integer_input_without_spending(
    input_tokens,
):
    budget = RunBudget()

    with pytest.raises(ValueError, match="non-negative integer"):
        budget.reserve_model(input_tokens=input_tokens)

    assert (budget.snapshot().model_calls, budget.snapshot().charged_tokens) == (0, 0)


@pytest.mark.parametrize("depth", [1.0, True, 0, -1])
def test_task_reservation_rejects_non_integer_depth_without_spending(depth):
    budget = RunBudget()

    with pytest.raises(ValueError, match="positive integer"):
        budget.reserve_task(depth=depth)

    snapshot = budget.snapshot()
    assert (
        snapshot.tool_calls,
        snapshot.task_calls,
        snapshot.tasks_in_flight,
        snapshot.charged_tokens,
    ) == (0, 0, 0, 0)
