"""Bounded local OpenAI executor for the QuickJS x subagent capability lab."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from agent.capabilities.budget import (
    CapabilityDeniedError,
    InvalidDelegationError,
    RunBudgetExceededError,
    RunBudgetPolicy,
)
from agent.capabilities.quickjs import QUICKJS_TOOL_NAME, BoundedQuickJSMiddleware
from agent.capabilities.token_counting import (
    OPENAI_API_BASE_URL,
    OPENAI_GUEST_MODEL_NAME,
    OPENAI_GUEST_RESPONSE_MODEL_NAMES,
    InputTokenCountError,
    OpenAIResponsesInputTokenContract,
    openai_responses_input_token_counter,
    require_exact_openai_responses_model,
    require_official_openai_routing,
    require_openai_api_key,
)
from agent.retrieval.corpus import PublishedCorpus
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from openai import OpenAIError

from blogeval.capability_runner import (
    CAPABILITY_PROVIDER_EVIDENCE_STATUS,
    OPENAI_CAPABILITY_CACHE_MODE,
    OPENAI_CAPABILITY_EXECUTOR_ID,
    OPENAI_CAPABILITY_MAX_ATTEMPTS,
    OPENAI_CAPABILITY_MODEL_ID,
    OPENAI_CAPABILITY_PRICING,
    OPENAI_CAPABILITY_PROVIDER_CONTRACT,
    CapabilityEvaluationError,
    CapabilityExecutionContext,
    CapabilityExecutorDiagnosticError,
    CapabilityExecutorIdentity,
    CapabilityObservation,
    CapabilityTaskSet,
    RootToolTraceEvent,
    activated_capabilities,
    build_capability_graph,
    recorded_root_tool_trace,
    recorded_subagent_types,
    run_capability_experiment,
    write_capability_artifacts,
)

OPENAI_CAPABILITY_POLICY = RunBudgetPolicy(
    policy_id="openai-luna-capability-lab-v1",
    max_model_calls=12,
    max_tool_calls=24,
    max_quickjs_calls=4,
    max_quickjs_in_flight=1,
    max_quickjs_output_bytes=4_096,
    max_quickjs_total_output_bytes=16_384,
    max_task_calls=1,
    max_tasks_in_flight=1,
    max_depth=1,
    max_output_tokens=1_024,
    max_total_tokens=48_000,
    max_count_risk_tokens_per_attempt=48_000,
    max_count_risk_tokens_per_run=48_000,
    max_elapsed_seconds=90,
)
_EXPECTED_DISTRIBUTIONS = {
    "deepagents": "0.7.5",
    "langchain-openai": "1.3.5",
    "openai": "2.53.0",
}
_MAX_FINAL_JSON_BYTES = 64 * 1024
_SAFETY_IDENTIFIER = (
    "owner_" + hashlib.sha256(b"syshin0116-capability-eval-owner-v1").hexdigest()[:58]
)
_INPUT_TOKEN_CONTRACT = OpenAIResponsesInputTokenContract(
    model_name=OPENAI_GUEST_MODEL_NAME,
    max_output_tokens=OPENAI_CAPABILITY_POLICY.max_output_tokens,
    timeout_seconds=60.0,
    safety_identifier=_SAFETY_IDENTIFIER,
)
_COUNT_OPENAI_CAPABILITY_INPUT_TOKENS = openai_responses_input_token_counter(
    _INPUT_TOKEN_CONTRACT
)


def _executor_reason_code(error: BaseException) -> str:
    """Classify a failure without copying provider or prompt text into diagnostics."""

    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, InvalidDelegationError):
            return "delegation_contract"
        if isinstance(current, RunBudgetExceededError):
            return "budget"
        if isinstance(current, InputTokenCountError):
            return "input_count"
        if isinstance(current, CapabilityDeniedError):
            return "root_tool_denied"
        if isinstance(current, OpenAIError):
            return "provider"
        current = current.__cause__ or current.__context__
    return "graph_other"


def _redacted_root_tool_events(messages: object) -> tuple[str, ...]:
    """Return only allowlisted root event categories, never call IDs or arguments."""

    if not isinstance(messages, list):
        return ()
    events: list[str] = []
    maximum_events = OPENAI_CAPABILITY_POLICY.max_tool_calls * 2

    def category(name: object) -> str:
        if name == QUICKJS_TOOL_NAME:
            return "eval"
        if name == "task":
            return "task"
        return "other"

    try:
        for message in messages:
            if isinstance(message, BaseMessage):
                tool_calls = getattr(message, "tool_calls", None)
                if isinstance(tool_calls, list):
                    for tool_call in tool_calls:
                        name = (
                            tool_call.get("name")
                            if isinstance(tool_call, Mapping)
                            else None
                        )
                        events.append(f"call:{category(name)}")
                        if len(events) == maximum_events:
                            return tuple(events)
            if isinstance(message, ToolMessage):
                events.append(f"completion:{category(message.name)}")
                if len(events) == maximum_events:
                    return tuple(events)
    except Exception:
        return tuple(events)
    return tuple(events)


def _verify_provider_versions() -> None:
    observed = {
        distribution: importlib.metadata.version(distribution)
        for distribution in _EXPECTED_DISTRIBUTIONS
    }
    if observed != _EXPECTED_DISTRIBUTIONS:
        raise CapabilityEvaluationError(
            "installed provider stack differs from the reviewed exact versions"
        )


def build_openai_executor_identity(
    *,
    content_tree_sha: str,
    max_generation_cost_usd_micros: int,
    random_seed: int,
) -> CapabilityExecutorIdentity:
    """Derive the live provider identity; callers cannot select model or prices."""

    _verify_provider_versions()
    return CapabilityExecutorIdentity(
        executor_id=OPENAI_CAPABILITY_EXECUTOR_ID,
        execution_id=str(uuid4()),
        content_tree_sha=content_tree_sha,
        model_id=OPENAI_CAPABILITY_MODEL_ID,
        provider_contract=OPENAI_CAPABILITY_PROVIDER_CONTRACT,
        random_seed=random_seed,
        max_attempts=OPENAI_CAPABILITY_MAX_ATTEMPTS,
        cache_mode=OPENAI_CAPABILITY_CACHE_MODE,
        max_generation_cost_usd_micros=max_generation_cost_usd_micros,
        uncached_input_usd_micros_per_million_tokens=(
            OPENAI_CAPABILITY_PRICING["uncached_input_usd_micros_per_million_tokens"]
        ),
        output_usd_micros_per_million_tokens=OPENAI_CAPABILITY_PRICING[
            "output_usd_micros_per_million_tokens"
        ],
        cache_read_input_usd_micros_per_million_tokens=(
            OPENAI_CAPABILITY_PRICING["cache_read_input_usd_micros_per_million_tokens"]
        ),
        cache_write_input_usd_micros_per_million_tokens=(
            OPENAI_CAPABILITY_PRICING["cache_write_input_usd_micros_per_million_tokens"]
        ),
    )


def _runtime(store: InMemoryStore, *, workspace_root: Path):
    from aegra_api.services.graph_factory import build_server_runtime

    return build_server_runtime(
        access_context="threads.create_run",
        store=store,
        user=SimpleNamespace(
            identity="capability-eval-owner",
            display_name="capability-eval-owner",
            is_authenticated=True,
            permissions=["eval"],
        ),
        context={"workspace_root": str(workspace_root)},
    )


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise CapabilityEvaluationError("provider returned a non-text final message")
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if isinstance(block, dict) and block.get("type") in {
            "text",
            "output_text",
        }:
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    if not parts:
        raise CapabilityEvaluationError("provider returned no final text")
    return "".join(parts)


def _strict_object(payload: str) -> dict[str, Any]:
    try:
        encoded = payload.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CapabilityEvaluationError("provider final JSON is not UTF-8") from exc
    if len(encoded) > _MAX_FINAL_JSON_BYTES:
        raise CapabilityEvaluationError("provider final JSON exceeds its byte bound")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise CapabilityEvaluationError(
                    "provider final JSON contains a duplicate key"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            payload,
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                CapabilityEvaluationError(f"provider final JSON contains {value}")
            ),
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise CapabilityEvaluationError(
            "provider final message is not strict JSON"
        ) from exc
    if not isinstance(value, dict):
        raise CapabilityEvaluationError("provider final JSON must be an object")
    return value


def _observation(
    message: BaseMessage,
    *,
    cache_mode: str,
    delegated_subagent_types: tuple[str, ...] = (),
    root_tool_trace: tuple[RootToolTraceEvent, ...] = (),
) -> CapabilityObservation:
    value = _strict_object(_message_text(message))
    if set(value) != {"answer", "citations", "failure_code", "status"}:
        raise CapabilityEvaluationError("provider final JSON has an unexpected shape")
    status = value["status"]
    citations = value["citations"]
    if status not in {"completed", "failed"} or not isinstance(citations, list):
        raise CapabilityEvaluationError(
            "provider final JSON has invalid status/citations"
        )
    try:
        from agent.retrieval.protocol import DocId

        doc_ids = tuple(DocId(item) for item in citations)
    except (TypeError, ValueError) as exc:
        raise CapabilityEvaluationError(
            "provider final JSON contains an invalid citation"
        ) from exc
    answer = value["answer"]
    if answer is not None and not isinstance(answer, dict):
        raise CapabilityEvaluationError(
            "provider final answer must be an object or null"
        )
    failure_code = value["failure_code"]
    if failure_code is not None and not isinstance(failure_code, str):
        raise CapabilityEvaluationError(
            "provider final failure code must be a string or null"
        )
    return CapabilityObservation(
        status=status,
        answer=answer,
        citations=doc_ids,
        persistence_empty=True,
        cache_mode=cache_mode,
        delegated_subagent_types=delegated_subagent_types,
        root_tool_trace=root_tool_trace,
        failure_code=failure_code,
    )


def _task_payload(context: CapabilityExecutionContext) -> str:
    quickjs_required = "quickjs" in context.task.tags or "combined" in context.task.tags
    subagents_required = (
        "subagents" in context.task.tags or "combined" in context.task.tags
    )
    quickjs_active, subagents_active = activated_capabilities(context)
    missing_required_capabilities: list[str] = []
    if quickjs_required and not context.arm.quickjs_enabled:
        missing_required_capabilities.append("quickjs")
    if subagents_required and not context.arm.subagents_enabled:
        missing_required_capabilities.append("subagents")
    permitted_tool_calls: list[dict[str, str]] = []
    if quickjs_active:
        permitted_tool_calls.append(
            {
                "name": QUICKJS_TOOL_NAME,
                "purpose": "one deterministic pure-data transform",
            }
        )
    if subagents_active:
        permitted_tool_calls.append(
            {
                "name": "task",
                "purpose": "one complete stateless envelope to evidence-checker",
            }
        )
    return json.dumps(
        {
            "capability_contract": {
                "quickjs_enabled": quickjs_active,
                "quickjs_required": quickjs_required,
                "subagents_enabled": subagents_active,
                "subagents_required": subagents_required,
            },
            "instructions": [
                "If missing_required_capabilities is non-empty, call no tools and immediately return the exact capability_unavailable value below.",
                'When missing_required_capabilities is non-empty, the final value must be exactly {"answer":null,"citations":[],"failure_code":"capability_unavailable","status":"failed"}.',
                "Otherwise, use each required capability exactly once and return a completed result; capabilities with required=false never affect status.",
                "When subagents are required, delegate one complete stateless envelope to evidence-checker and synthesize its result.",
                "When QuickJS is required, execute one deterministic pure-data transform with the QuickJS tool.",
                "Do not use capabilities that are not required by this task.",
                "Call only the tools listed in permitted_tool_calls; never call write_todos, filesystem, retrieval, memory, or any other tool.",
                "When both tools are permitted, request only eval first; wait for its matching ToolMessage completion, then request task exactly once in a later model turn.",
                "For status=completed, answer MUST be a JSON object matching the schema implied by inputs; never return answer as a string, list, number, or boolean.",
                "For status=failed, return answer=null and citations=[]; for status=completed, return failure_code=null.",
                "Return citations as sorted unique content-relative DocId strings.",
                "Return only one compact JSON object with exactly answer, citations, failure_code, status. Use status=completed and failure_code=null on success.",
            ],
            "inputs": context.task.inputs,
            "missing_required_capabilities": missing_required_capabilities,
            "permitted_tool_calls": permitted_tool_calls,
            "prompt": context.task.prompt,
            "task_id": context.task.task_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class OpenAICapabilityExecutor:
    """Run the production graph against the exact bounded Luna contract."""

    def __init__(self, *, workspace_root: Path, cache_mode: str) -> None:
        self._workspace_root = workspace_root.resolve()
        self._cache_mode = cache_mode
        self._model: ChatOpenAI | None = None

    def _model_client(self) -> ChatOpenAI:
        """Read the credential only after the runner's complete cost preflight."""
        if self._model is None:
            require_official_openai_routing()
            self._model = ChatOpenAI(
                model=OPENAI_GUEST_MODEL_NAME,
                api_key=require_openai_api_key(),
                base_url=OPENAI_API_BASE_URL,
                stream_usage=True,
                max_tokens=OPENAI_CAPABILITY_POLICY.max_output_tokens,
                max_retries=0,
                timeout=60.0,
                use_responses_api=True,
                output_version="responses/v1",
                reasoning={"context": "current_turn", "effort": "none"},
                store=False,
                truncation="disabled",
                cache=False,
                extra_body={"safety_identifier": _SAFETY_IDENTIFIER},
            )
            require_exact_openai_responses_model(
                self._model,
                contract=_INPUT_TOKEN_CONTRACT,
            )
        return self._model

    async def execute(
        self,
        context: CapabilityExecutionContext,
    ) -> CapabilityObservation:
        checkpointer = InMemorySaver()
        store = InMemoryStore()
        persistence_failure_reason: str | None = None
        try:
            persistence_empty = (
                await checkpointer.aget_tuple(context.run_config) is None
                and store.list_namespaces() == []
            )
        except Exception as exc:
            persistence_failure_reason = _executor_reason_code(exc)
        if persistence_failure_reason is not None:
            raise CapabilityExecutorDiagnosticError(
                phase="persistence_preflight",
                reason_code=persistence_failure_reason,
            )
        if not persistence_empty:
            raise CapabilityExecutorDiagnosticError(
                phase="persistence_preflight",
                reason_code="graph_other",
            )
        quickjs_active, _subagents_active = activated_capabilities(context)
        quickjs = BoundedQuickJSMiddleware(enabled=quickjs_active)
        primary_error: BaseException | None = None
        cleanup_error: BaseException | None = None
        primary_phase = "graph_build"
        result: object = None
        try:
            compiled = build_capability_graph(
                context,
                runtime=_runtime(store, workspace_root=self._workspace_root),
                model=self._model_client(),
                input_token_counter=_COUNT_OPENAI_CAPABILITY_INPUT_TOKENS,
                model_provider="openai",
                expected_response_models=OPENAI_GUEST_RESPONSE_MODEL_NAMES,
                quickjs_middleware=quickjs,
            ).copy(update={"checkpointer": checkpointer, "store": store})
            primary_phase = "graph_invoke"
            result = await compiled.ainvoke(
                {"messages": [{"role": "user", "content": _task_payload(context)}]},
                context.run_config,
            )
        except BaseException as exc:
            primary_error = exc
        finally:
            try:
                await quickjs.aclose()
            except BaseException as exc:
                cleanup_error = exc
        control_flow_errors = (KeyboardInterrupt, SystemExit, asyncio.CancelledError)
        if isinstance(primary_error, control_flow_errors):
            raise primary_error
        if isinstance(cleanup_error, control_flow_errors):
            primary_error = None
            raise cleanup_error
        if primary_error is not None:
            primary_reason = _executor_reason_code(primary_error)
            primary_error = None
            cleanup_error = None
            raise CapabilityExecutorDiagnosticError(
                phase=primary_phase,
                reason_code=primary_reason,
            )
        if cleanup_error is not None:
            cleanup_error = None
            raise CapabilityExecutorDiagnosticError(
                phase="quickjs_cleanup",
                reason_code="cleanup",
            )
        messages = result.get("messages") if isinstance(result, Mapping) else None
        if not isinstance(messages, list) or not messages:
            raise CapabilityExecutorDiagnosticError(
                phase="result_shape",
                reason_code="result_shape",
                root_tool_events=_redacted_root_tool_events(messages),
            )
        final = messages[-1]
        if not isinstance(final, BaseMessage):
            raise CapabilityExecutorDiagnosticError(
                phase="result_shape",
                reason_code="result_shape",
                root_tool_events=_redacted_root_tool_events(messages),
            )
        redacted_root_tool_events = _redacted_root_tool_events(messages)
        subtype_trace_failed = False
        try:
            delegated_subagent_types = recorded_subagent_types(messages)
        except Exception:
            subtype_trace_failed = True
        if subtype_trace_failed:
            raise CapabilityExecutorDiagnosticError(
                phase="subtype_trace",
                reason_code="trace",
                root_tool_events=redacted_root_tool_events,
            )
        root_trace_failed = False
        try:
            root_tool_trace = recorded_root_tool_trace(messages)
        except Exception:
            root_trace_failed = True
        if root_trace_failed:
            raise CapabilityExecutorDiagnosticError(
                phase="root_trace",
                reason_code="trace",
                root_tool_events=redacted_root_tool_events,
            )
        observation_failed = False
        try:
            observation = _observation(
                final,
                cache_mode=self._cache_mode,
                delegated_subagent_types=delegated_subagent_types,
                root_tool_trace=root_tool_trace,
            )
        except Exception:
            observation_failed = True
        if observation_failed:
            raise CapabilityExecutorDiagnosticError(
                phase="final_json",
                reason_code="strict_json",
                root_tool_events=redacted_root_tool_events,
            )
        return observation


@contextmanager
def _local_runtime_environment(*, workspace_root: Path, index_root: Path):
    values = {
        "AEGRA_CONFIG": str(workspace_root / "aegra.json"),
        "AGENT_AUTH_SECRET": "local-capability-eval-secret-at-least-32-bytes",
        "BG_JOB_MAX_RETRIES": "0",
        "BLOG_INDEX_PATH": str(index_root.resolve()),
        "FF_V2_EVENT_STREAMING": "true",
        "REDIS_BROKER_ENABLED": "false",
    }
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


async def run_openai_capability_sweep(
    *,
    dataset: CapabilityTaskSet,
    workspace_root: Path,
    index_root: Path,
    output_root: Path,
    max_generation_cost_usd_micros: int,
    random_seed: int,
    paid_run_accepted: bool,
    unpriced_counting_accepted: bool,
):
    """Run one paid local sweep with bounded calls and generation-token cost."""

    if paid_run_accepted is not True:
        raise CapabilityEvaluationError(
            "paid OpenAI capability execution requires explicit acceptance"
        )
    if unpriced_counting_accepted is not True:
        raise CapabilityEvaluationError(
            "OpenAI input-token count request billing requires explicit acceptance"
        )
    workspace_root = workspace_root.resolve()
    index_root = index_root.resolve()
    corpus = PublishedCorpus(index_root)
    if corpus.content_git_tree_sha != dataset.content_tree_sha:
        raise CapabilityEvaluationError(
            "published corpus content tree differs from the capability task-set"
        )
    identity = build_openai_executor_identity(
        content_tree_sha=dataset.content_tree_sha,
        max_generation_cost_usd_micros=max_generation_cost_usd_micros,
        random_seed=random_seed,
    )
    with _local_runtime_environment(
        workspace_root=workspace_root,
        index_root=index_root,
    ):
        executor = OpenAICapabilityExecutor(
            workspace_root=workspace_root,
            cache_mode=identity.cache_mode,
        )
        run = await run_capability_experiment(
            dataset=dataset,
            executor=executor,
            executor_identity=identity,
            budget_policy=OPENAI_CAPABILITY_POLICY,
            evidence_status=CAPABILITY_PROVIDER_EVIDENCE_STATUS,
        )
    return write_capability_artifacts(run, output_root=output_root)


__all__ = [
    "OPENAI_CAPABILITY_EXECUTOR_ID",
    "OPENAI_CAPABILITY_MODEL_ID",
    "OPENAI_CAPABILITY_POLICY",
    "OPENAI_CAPABILITY_PROVIDER_CONTRACT",
    "OpenAICapabilityExecutor",
    "build_openai_executor_identity",
    "run_openai_capability_sweep",
]
