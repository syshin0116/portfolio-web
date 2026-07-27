"""Deep Agent — LangGraph standard agent with built-in middleware."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import (
    CompositeBackend,
    FilesystemBackend,
    StateBackend,
    StoreBackend,
)
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph_sdk.runtime import ServerRuntime

from agent.auth import ANONYMOUS_PERMISSION, is_anonymous_identity
from agent.capabilities.budget import (
    RunBudget,
    RunBudgetMiddleware,
    RunBudgetPolicy,
)
from agent.capabilities.quickjs import (
    QUICKJS_TOOL_NAME,
    BoundedQuickJSMiddleware,
    quickjs_allowed,
)
from agent.capabilities.subagents import (
    NATIVE_SUBAGENT_SYSTEM_PROMPT,
    SUBAGENT_NAMES,
    SUBAGENT_ROOT_PROMPT,
    build_subagents,
    dynamic_subagents_allowed,
    validate_capability_config,
)
from agent.capabilities.token_counting import (
    InputTokenCounter,
    count_anthropic_input_tokens,
)
from agent.inspection import InspectionEventTransformer
from agent.prompts import SYSTEM_PROMPT
from agent.run_liveness import (
    GUEST_RUN_MAX_ELAPSED_SECONDS,
    acquire_guest_execution_fence,
    validate_guest_execution_fencing_factory,
)
from agent.tools import TOOLS

DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"
MODEL_MAX_OUTPUT_TOKENS = 2_048
GUEST_MODEL_MAX_OUTPUT_TOKENS = 1_024
MODEL_TIMEOUT_SECONDS = 60.0
SUPPORTED_MODEL_PROVIDERS = frozenset({"anthropic"})
_MODEL_SPEC = re.compile(r"^[a-z][a-z0-9_-]*:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
NO_GENERAL_PURPOSE_SUBAGENT = HarnessProfile(
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    # This middleware performs its own provider call outside user middleware,
    # which would bypass the shared model reservation.
    excluded_middleware=frozenset({"SummarizationMiddleware"}),
)
logger = logging.getLogger(__name__)

GUEST_RUN_BUDGET_POLICY = RunBudgetPolicy(
    policy_id="anonymous-public-v1",
    max_model_calls=4,
    max_tool_calls=8,
    max_quickjs_calls=1,
    max_quickjs_in_flight=1,
    max_quickjs_output_bytes=1_024,
    max_quickjs_total_output_bytes=1_024,
    max_task_calls=1,
    max_tasks_in_flight=1,
    max_depth=1,
    max_output_tokens=GUEST_MODEL_MAX_OUTPUT_TOKENS,
    max_total_tokens=12_000,
    max_elapsed_seconds=GUEST_RUN_MAX_ELAPSED_SECONDS,
)

AGENT_DIR = Path(__file__).resolve().parent.parent.parent  # agent/
SKILLS_DIR = str(AGENT_DIR / "skills")


def _memory_namespace(runtime: Runtime[Any]) -> tuple[str, str, str]:
    """Scope persistent files to the authenticated Aegra identity."""
    server_info = runtime.server_info
    server_user = server_info.user if server_info is not None else None
    identity = getattr(server_user, "identity", None)
    if not isinstance(identity, str) or not identity:
        raise ValueError("Aegra runtime authentication identity is required for memory")
    return (
        "users",
        hashlib.sha256(identity.encode()).hexdigest(),
        "filesystem",
    )


def _build_backend(*, persistent_memory: bool = True) -> CompositeBackend:
    """Build the instance backend used by every Aegra graph copy.

    /            -> StateBackend (ephemeral working files per thread)
    /memories/   -> StoreBackend (persistent cross-thread memory)
    /skills/     -> read-only Deep Agents skills
    """
    routes = {
        "/skills/": FilesystemBackend(root_dir=SKILLS_DIR, virtual_mode=True),
    }
    if persistent_memory:
        routes["/memories/"] = StoreBackend(namespace=_memory_namespace)
    return CompositeBackend(default=StateBackend(), routes=routes)


def _filesystem_permissions() -> list[FilesystemPermission]:
    """Keep mounted skills read-only while leaving thread and memory files writable."""

    return [
        FilesystemPermission(
            operations=["write"],
            paths=["/skills", "/skills/**"],
            mode="deny",
        )
    ]


def _normalize_model_spec(model: str, *, variable: str) -> str:
    """Validate one non-configurable server-owned provider/model identifier."""
    # Normalize "provider/model" → "provider:model" for deepagents compatibility
    if "/" in model and ":" not in model:
        model = model.replace("/", ":", 1)
    if _MODEL_SPEC.fullmatch(model) is None:
        raise RuntimeError(f"{variable} must be one bounded provider:model spec")
    provider, _separator, _name = model.partition(":")
    if provider not in SUPPORTED_MODEL_PROVIDERS:
        raise RuntimeError(f"{variable} provider {provider!r} is not supported")
    return model


def _normalized_model_spec() -> str:
    """Return the supported owner/evaluation model in canonical form."""
    return _normalize_model_spec(
        os.environ.get("MODEL") or DEFAULT_MODEL,
        variable="MODEL",
    )


def _normalized_guest_model_spec() -> str:
    """Return the explicitly configured lower-cost anonymous model."""
    model = os.environ.get("GUEST_MODEL", "")
    if not model:
        raise RuntimeError(
            "GUEST_MODEL is required when anonymous agent access is enabled"
        )
    return _normalize_model_spec(model, variable="GUEST_MODEL")


def _runtime_is_guest(runtime: ServerRuntime[Any]) -> bool:
    """Recognize only the canonical identity and exact permission minted for guests."""
    user = runtime.user
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False) is True
        and is_anonymous_identity(getattr(user, "identity", None))
        and getattr(user, "permissions", None) == [ANONYMOUS_PERMISSION]
    )


@lru_cache(maxsize=len(SUPPORTED_MODEL_PROVIDERS) * 4)
def _disable_general_purpose_subagent(model: str) -> None:
    """Register the fail-closed profile once per normalized server model."""
    register_harness_profile(model, NO_GENERAL_PURPOSE_SUBAGENT)


@lru_cache(maxsize=len(SUPPORTED_MODEL_PROVIDERS) * 4)
def _bounded_model(model_spec: str) -> BaseChatModel:
    """Create a non-configurable provider client with hard request bounds."""
    model = init_chat_model(
        model_spec,
        max_tokens=MODEL_MAX_OUTPUT_TOKENS,
        max_retries=0,
        timeout=MODEL_TIMEOUT_SECONDS,
    )
    if not isinstance(model, BaseChatModel):
        raise RuntimeError("MODEL resolved to a runtime-configurable wrapper")
    return model


@lru_cache(maxsize=len(SUPPORTED_MODEL_PROVIDERS) * 4)
def _bounded_guest_model(model_spec: str) -> BaseChatModel:
    """Create the anonymous tier client with a lower hard output ceiling."""
    model = init_chat_model(
        model_spec,
        max_tokens=GUEST_MODEL_MAX_OUTPUT_TOKENS,
        max_retries=0,
        timeout=MODEL_TIMEOUT_SECONDS,
    )
    if not isinstance(model, BaseChatModel):
        raise RuntimeError("GUEST_MODEL resolved to a runtime-configurable wrapper")
    return model


def create_graph(
    *,
    runtime: ServerRuntime[Any],
    config: Mapping[str, Any],
    budget: RunBudget | None = None,
    model: BaseChatModel | None = None,
    input_token_counter: InputTokenCounter | None = None,
    dynamic_subagents_enabled: bool | None = None,
    quickjs_enabled: bool | None = None,
    quickjs_middleware: BoundedQuickJSMiddleware | None = None,
):
    """Compile one topology-stable Deep Agent around a run-local budget.

    Aegra copies the compiled graph and injects its Postgres checkpointer and
    store after this function returns. Capability authorization comes only
    from ``ServerRuntime.user.permissions``; client config cannot enable it.
    """
    validate_capability_config(config)
    is_guest = _runtime_is_guest(runtime)
    model_spec = (
        _normalized_guest_model_spec() if is_guest else _normalized_model_spec()
    )
    _disable_general_purpose_subagent(model_spec)
    selected_model = model or (
        _bounded_guest_model(model_spec) if is_guest else _bounded_model(model_spec)
    )
    if is_guest and budget is not None and budget.policy != GUEST_RUN_BUDGET_POLICY:
        raise ValueError("guest graph requires the anonymous run budget policy")
    run_budget = budget or (
        RunBudget(GUEST_RUN_BUDGET_POLICY) if is_guest else RunBudget()
    )
    exact_input_counter = input_token_counter or count_anthropic_input_tokens
    if (
        dynamic_subagents_enabled is not None
        and type(dynamic_subagents_enabled) is not bool
    ):
        raise TypeError("dynamic_subagents_enabled must be a boolean")
    allow_subagents = not is_guest and dynamic_subagents_allowed(
        runtime,
        server_enabled=(
            True
            if dynamic_subagents_enabled is None
            else dynamic_subagents_enabled
        ),
    )
    allow_quickjs = not is_guest and quickjs_allowed(
        runtime,
        server_enabled=quickjs_enabled,
    )
    if quickjs_middleware is None:
        quickjs_middleware = BoundedQuickJSMiddleware(enabled=allow_quickjs)
    elif (
        not isinstance(quickjs_middleware, BoundedQuickJSMiddleware)
        or quickjs_middleware.enabled is not allow_quickjs
    ):
        raise ValueError(
            "quickjs_middleware must match server-side QuickJS authorization"
        )
    system_prompt = SYSTEM_PROMPT
    if allow_subagents:
        system_prompt = f"{system_prompt}\n\n{SUBAGENT_ROOT_PROMPT}"

    compiled = create_deep_agent(
        model=selected_model,
        tools=TOOLS,
        system_prompt=system_prompt,
        middleware=[
            quickjs_middleware,
            RunBudgetMiddleware(
                run_budget,
                depth=0,
                allow_subagents=allow_subagents,
                allowed_subagents=SUBAGENT_NAMES,
                input_token_counter=exact_input_counter,
                native_subagent_prompt=NATIVE_SUBAGENT_SYSTEM_PROMPT,
                quickjs_tool_name=QUICKJS_TOOL_NAME,
                allow_quickjs=allow_quickjs,
            ),
        ],
        subagents=build_subagents(
            model=selected_model,
            budget=run_budget,
            input_token_counter=exact_input_counter,
        ),
        backend=_build_backend(persistent_memory=not is_guest),
        skills=["/skills/"],
        permissions=_filesystem_permissions(),
    )
    return compiled.copy(
        update={
            "stream_transformers": (
                *compiled.stream_transformers,
                InspectionEventTransformer,
            )
        }
    )


async def _await_quickjs_cleanup(middleware: BoundedQuickJSMiddleware) -> None:
    """Finish native cleanup even if the graph task receives another cancel."""
    cleanup = asyncio.create_task(middleware.aclose())
    interrupted: asyncio.CancelledError | None = None
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError as error:
            interrupted = error

    try:
        cleanup.result()
    except BaseException:
        if interrupted is None:
            raise
        logger.exception("QuickJS cleanup failed while graph cancellation was pending")
    if interrupted is not None:
        raise interrupted


@asynccontextmanager
async def graph(
    config: RunnableConfig,
    runtime: ServerRuntime[Any],
) -> AsyncIterator[Any]:
    """Aegra 0.9.24 factory: one non-serializable ledger per run/access call."""
    is_guest = _runtime_is_guest(runtime)
    budget = RunBudget(GUEST_RUN_BUDGET_POLICY) if is_guest else RunBudget()
    quickjs_middleware = BoundedQuickJSMiddleware(
        enabled=not is_guest and quickjs_allowed(runtime)
    )
    if is_guest and runtime.access_context == "threads.create_run":
        configurable = config.get("configurable")
        if not isinstance(configurable, Mapping):
            raise RuntimeError(
                "guest execution requires server-owned configurable identity"
            )
        run_id = configurable.get("run_id")
        thread_id = configurable.get("thread_id")
        identity = getattr(runtime.user, "identity", None)
        if (
            not isinstance(run_id, str)
            or not run_id
            or not isinstance(thread_id, str)
            or not thread_id
            or not isinstance(identity, str)
        ):
            raise RuntimeError(
                "guest execution requires run, thread, and user identity"
            )
        fence = await acquire_guest_execution_fence(
            run_id=run_id,
            thread_id=thread_id,
            identity=identity,
        )
        try:
            fence.start_owner_monitor()
        except BaseException:
            try:
                await fence.aclose()
            except BaseException:
                logger.exception(
                    "guest execution fence cleanup failed after monitor start"
                )
            raise
    execution_error: BaseException | None = None
    try:
        compiled = create_graph(
            runtime=runtime,
            config=config,
            budget=budget,
            quickjs_middleware=quickjs_middleware,
        )
        yield compiled
    except BaseException as error:
        execution_error = error
        raise
    finally:
        try:
            await _await_quickjs_cleanup(quickjs_middleware)
        except BaseException:
            if execution_error is None:
                raise
            logger.exception(
                "QuickJS cleanup failed; preserving the active graph exception"
            )
        snapshot = budget.snapshot()
        logger.debug(
            (
                "run budget observed policy=%s model=%d tool=%d quickjs=%d "
                "task=%d tokens=%d"
            ),
            snapshot.policy_id,
            snapshot.model_calls,
            snapshot.tool_calls,
            snapshot.quickjs_calls,
            snapshot.task_calls,
            snapshot.charged_tokens,
        )


def _validate_aegra_registration() -> None:
    """Cover startup even when config discovery omits the custom HTTP app."""
    from agent.preflight import validate_runtime_preflight

    validate_runtime_preflight()
    validate_guest_execution_fencing_factory(graph)
    if os.environ.get("AGENT_ANONYMOUS_ACCESS_ENABLED", "false") == "true":
        _normalized_guest_model_spec()


_validate_aegra_registration()

__all__ = [
    "GUEST_MODEL_MAX_OUTPUT_TOKENS",
    "GUEST_RUN_BUDGET_POLICY",
    "MODEL_MAX_OUTPUT_TOKENS",
    "MODEL_TIMEOUT_SECONDS",
    "create_graph",
    "graph",
]
