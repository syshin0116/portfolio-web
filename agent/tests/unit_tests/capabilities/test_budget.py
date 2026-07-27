"""Behavior tests for the atomic per-run resource ledger."""

from __future__ import annotations

import asyncio
import json
import pickle
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from threading import Barrier

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import ToolRuntime

from agent.capabilities.budget import (
    DEFAULT_RUN_BUDGET_POLICY,
    CapabilityDeniedError,
    InvalidDelegationError,
    RunBudget,
    RunBudgetExceededError,
    RunBudgetMiddleware,
    TaskReservation,
)

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
        "policy_id": "owner-dynamic-subagents-v1",
        "model_calls": 0,
        "tool_calls": 2,
        "task_calls": 2,
        "tasks_in_flight": 2,
        "charged_tokens": 4_096,
        "elapsed_ms": 0,
        "exhausted": True,
    }

    for reservation in reservations:
        budget.finish_task(reservation)
    assert budget.snapshot().tasks_in_flight == 0


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
        estimated_input_tokens=100,
        task_reservation=task,
    )
    assert budget.snapshot().charged_tokens == 2_148
    budget.settle_model(first_model, actual_tokens=120)
    assert budget.snapshot().charged_tokens == 120

    second_model = budget.reserve_model(
        estimated_input_tokens=100,
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

    assert budget.snapshot().charged_tokens == 2_048


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

    assert budget.snapshot().charged_tokens == 2_048


async def test_oversized_model_input_is_rejected_before_calling_provider():
    budget = RunBudget()
    middleware = _middleware(budget)
    request = ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="unused")]),
        messages=[HumanMessage(content="x" * 100_000)],
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
        '"model_calls": 1, "policy_id": "owner-dynamic-subagents-v1", '
        '"task_calls": 0, "tasks_in_flight": 0, "tool_calls": 0}'
    )


def test_elapsed_deadline_rejects_reservation_without_spending_counters():
    now = [10.0]
    budget = RunBudget(clock=lambda: now[0])
    now[0] = 100.0

    with pytest.raises(RunBudgetExceededError, match="elapsed-time"):
        budget.reserve_tool()

    assert asdict(budget.snapshot()) == {
        "policy_id": "owner-dynamic-subagents-v1",
        "model_calls": 0,
        "tool_calls": 0,
        "task_calls": 0,
        "tasks_in_flight": 0,
        "charged_tokens": 0,
        "elapsed_ms": 90_000,
        "exhausted": True,
    }


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
        ("max_depth", 1.0),
        ("max_total_tokens", 48_000.0),
        ("max_elapsed_seconds", 90.0),
    ],
)
def test_policy_integer_limits_reject_non_integer_values(field, value):
    with pytest.raises(ValueError, match="positive and coherent"):
        replace(DEFAULT_RUN_BUDGET_POLICY, **{field: value})


@pytest.mark.parametrize("estimated_input_tokens", [1.0, True, -1])
def test_model_reservation_rejects_non_integer_input_without_spending(
    estimated_input_tokens,
):
    budget = RunBudget()

    with pytest.raises(ValueError, match="non-negative integer"):
        budget.reserve_model(estimated_input_tokens=estimated_input_tokens)

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
