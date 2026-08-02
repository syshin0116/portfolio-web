"""Deep Agent — LangGraph standard agent with built-in middleware."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
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
from deepagents.backends.protocol import WriteResult
from langchain.agents.middleware import TodoListMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.runtime import Runtime
from langgraph_sdk.runtime import ServerRuntime

from agent.auth import ANONYMOUS_PERMISSION, is_anonymous_identity
from agent.capabilities.budget import (
    TASK_TOOL_NAME,
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
    BOUNDED_TASK_TOOL_DESCRIPTION,
    SUBAGENT_NAMES,
    SUBAGENT_ROOT_PROMPT,
    build_subagents,
    dynamic_subagents_allowed,
    validate_capability_config,
)
from agent.capabilities.token_counting import (
    OPENAI_API_BASE_URL,
    OPENAI_GUEST_MAX_OUTPUT_TOKENS,
    OPENAI_GUEST_MODEL_NAME,
    OPENAI_GUEST_MODEL_SPEC,
    OPENAI_GUEST_RESPONSE_MODEL_NAMES,
    OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH,
    OPENAI_GUEST_TIMEOUT_SECONDS,
    InputTokenCounter,
    count_anthropic_input_tokens,
    count_openai_input_tokens,
    openai_guest_safety_identifier,
    prepare_openai_input_token_count,
    require_exact_openai_guest_model,
    require_official_openai_routing,
    require_openai_api_key,
)
from agent.inspection import InspectionEventTransformer
from agent.prompts import GUEST_SYSTEM_PROMPT, SYSTEM_PROMPT
from agent.run_liveness import (
    GUEST_RUN_MAX_ELAPSED_SECONDS,
    acquire_guest_execution_fence,
    validate_guest_execution_fencing_factory,
)
from agent.tools import TOOLS

DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"
MODEL_MAX_OUTPUT_TOKENS = 2_048
GUEST_MODEL_MAX_OUTPUT_TOKENS = OPENAI_GUEST_MAX_OUTPUT_TOKENS
MODEL_TIMEOUT_SECONDS = OPENAI_GUEST_TIMEOUT_SECONDS
SUPPORTED_OWNER_MODEL_PROVIDERS = frozenset({"anthropic"})
_MODEL_SPEC = re.compile(r"^[a-z][a-z0-9_-]*:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
NO_GENERAL_PURPOSE_SUBAGENT = HarnessProfile(
    tool_description_overrides={"task": BOUNDED_TASK_TOOL_DESCRIPTION},
    excluded_tools=frozenset({"delete"}),
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    # This middleware performs its own provider call outside user middleware,
    # which would bypass the shared model reservation.
    excluded_middleware=frozenset({"SummarizationMiddleware"}),
)
logger = logging.getLogger(__name__)

# Cloud Run is deliberately constrained to one instance and one application worker.
# Serialize persistent-memory creates at that server boundary so StoreBackend's
# get/put pair cannot race after deepagents 0.7 changed write_file to overwrite.
_PERSISTENT_MEMORY_WRITE_LOCK = threading.Lock()

GUEST_RUN_BUDGET_POLICY = RunBudgetPolicy(
    policy_id="anonymous-public-v2",
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
    max_count_risk_tokens_per_attempt=48_000,
    max_count_risk_tokens_per_run=48_000,
    max_elapsed_seconds=GUEST_RUN_MAX_ELAPSED_SECONDS,
)
_GUEST_ROOT_TOOL_ORDER = (
    "keyword_search",
    "semantic_search",
    "metadata_filter",
    "graph_traverse",
    "list_posts",
    "read_post",
)
ROOT_TOOL_DENYLIST = frozenset({"delete"})
GUEST_ROOT_TOOL_NAMES = frozenset(
    {
        "keyword_search",
        "semantic_search",
        "metadata_filter",
        "graph_traverse",
        "list_posts",
        "read_post",
    }
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


async def _acquire_persistent_memory_write_lock() -> None:
    """Acquire the cross-mode memory lock without blocking the event loop."""
    acquire_task = asyncio.create_task(
        asyncio.to_thread(_PERSISTENT_MEMORY_WRITE_LOCK.acquire)
    )
    interrupted: asyncio.CancelledError | None = None
    while not acquire_task.done():
        try:
            await asyncio.shield(acquire_task)
        except asyncio.CancelledError as error:
            interrupted = error

    acquired = acquire_task.result()
    if interrupted is not None:
        if acquired:
            _PERSISTENT_MEMORY_WRITE_LOCK.release()
        raise interrupted


class CreateOnlyStoreBackend(StoreBackend):
    """Keep persistent write_file create-only; edit_file remains the update path."""

    @staticmethod
    def _already_exists(file_path: str) -> WriteResult:
        return WriteResult(
            error=(
                f"Cannot write to {file_path} because it already exists. "
                "Read and then make an edit, or write to a new path."
            )
        )

    def write(self, file_path: str, content: str) -> WriteResult:
        with _PERSISTENT_MEMORY_WRITE_LOCK:
            store = self._get_store()
            namespace = self._get_namespace()
            if store.get(namespace, file_path) is not None:
                return self._already_exists(file_path)
            return super().write(file_path, content)

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        await _acquire_persistent_memory_write_lock()
        try:
            store = self._get_store()
            namespace = self._get_namespace()
            if await store.aget(namespace, file_path) is not None:
                return self._already_exists(file_path)
            return await super().awrite(file_path, content)
        finally:
            _PERSISTENT_MEMORY_WRITE_LOCK.release()


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
        routes["/memories/"] = CreateOnlyStoreBackend(namespace=_memory_namespace)
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


def _validate_guest_root_tool_contract() -> None:
    """Fail startup/compilation when the reviewed guest tool surface drifts."""
    actual = tuple(tool.name for tool in TOOLS)
    if len(actual) != len(set(actual)):
        raise RuntimeError("guest root tools contain a duplicate name")
    if actual != _GUEST_ROOT_TOOL_ORDER or frozenset(actual) != GUEST_ROOT_TOOL_NAMES:
        raise RuntimeError(
            "guest root tools must equal the reviewed six-name ordered allowlist"
        )


def _normalize_model_spec(
    model: str,
    *,
    variable: str,
    supported_providers: frozenset[str],
) -> str:
    """Validate one non-configurable server-owned provider/model identifier."""
    # Normalize "provider/model" → "provider:model" for deepagents compatibility
    if "/" in model and ":" not in model:
        model = model.replace("/", ":", 1)
    if _MODEL_SPEC.fullmatch(model) is None:
        raise RuntimeError(f"{variable} must be one bounded provider:model spec")
    provider, _separator, _name = model.partition(":")
    if provider not in supported_providers:
        raise RuntimeError(f"{variable} provider {provider!r} is not supported")
    return model


def _normalized_model_spec() -> str:
    """Return the supported owner/evaluation model in canonical form."""
    return _normalize_model_spec(
        os.environ.get("MODEL") or DEFAULT_MODEL,
        variable="MODEL",
        supported_providers=SUPPORTED_OWNER_MODEL_PROVIDERS,
    )


def _normalized_guest_model_spec() -> str:
    """Return the explicitly configured lower-cost anonymous model."""
    model = os.environ.get("GUEST_MODEL", "")
    if not model:
        raise RuntimeError(
            "GUEST_MODEL is required when anonymous agent access is enabled"
        )
    normalized = _normalize_model_spec(
        model,
        variable="GUEST_MODEL",
        supported_providers=frozenset({"openai"}),
    )
    if normalized != OPENAI_GUEST_MODEL_SPEC:
        raise RuntimeError(f"GUEST_MODEL must be exactly {OPENAI_GUEST_MODEL_SPEC!r}")
    return normalized


def _runtime_is_guest(runtime: ServerRuntime[Any]) -> bool:
    """Recognize only the canonical identity and exact permission minted for guests."""
    user = runtime.user
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False) is True
        and is_anonymous_identity(getattr(user, "identity", None))
        and getattr(user, "permissions", None) == [ANONYMOUS_PERMISSION]
    )


@lru_cache(maxsize=(len(SUPPORTED_OWNER_MODEL_PROVIDERS) + 1) * 4)
def _disable_general_purpose_subagent(model: str) -> None:
    """Register the fail-closed profile once per normalized server model."""
    register_harness_profile(model, NO_GENERAL_PURPOSE_SUBAGENT)


@lru_cache(maxsize=len(SUPPORTED_OWNER_MODEL_PROVIDERS) * 4)
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


@lru_cache(maxsize=256)
def _bounded_guest_model(
    model_spec: str,
    safety_identifier: str,
) -> BaseChatModel:
    """Create the anonymous tier client with a lower hard output ceiling."""
    if model_spec != OPENAI_GUEST_MODEL_SPEC:
        raise RuntimeError(f"GUEST_MODEL must be exactly {OPENAI_GUEST_MODEL_SPEC!r}")
    if (
        not isinstance(safety_identifier, str)
        or not safety_identifier.startswith("guest_")
        or len(safety_identifier) != OPENAI_GUEST_SAFETY_IDENTIFIER_LENGTH
    ):
        raise RuntimeError("guest safety identifier is invalid")
    require_official_openai_routing()
    model = ChatOpenAI(
        model=OPENAI_GUEST_MODEL_NAME,
        api_key=require_openai_api_key(),
        base_url=OPENAI_API_BASE_URL,
        stream_usage=True,
        max_tokens=GUEST_MODEL_MAX_OUTPUT_TOKENS,
        max_retries=0,
        timeout=MODEL_TIMEOUT_SECONDS,
        use_responses_api=True,
        output_version="responses/v1",
        reasoning={"context": "current_turn", "effort": "none"},
        store=False,
        truncation="disabled",
        cache=False,
        extra_body={"safety_identifier": safety_identifier},
    )
    if not isinstance(model, BaseChatModel):
        raise RuntimeError("GUEST_MODEL resolved to a runtime-configurable wrapper")
    return require_exact_openai_guest_model(model)


def create_graph(
    *,
    runtime: ServerRuntime[Any],
    config: Mapping[str, Any],
    budget: RunBudget | None = None,
    model: BaseChatModel | None = None,
    input_token_counter: InputTokenCounter | None = None,
    model_provider: str | None = None,
    expected_response_models: frozenset[str] | None = None,
    dynamic_subagents_enabled: bool | None = None,
    quickjs_enabled: bool | None = None,
    quickjs_middleware: BoundedQuickJSMiddleware | None = None,
    root_tool_allowlist: frozenset[str] | None = None,
    experiment_subagent_allowlist: frozenset[str] | None = None,
):
    """Compile one topology-stable Deep Agent around a run-local budget.

    Aegra copies the compiled graph and injects its Postgres checkpointer and
    store after this function returns. Capability authorization comes only
    from ``ServerRuntime.user.permissions``; client config cannot enable it.
    """
    _validate_guest_root_tool_contract()
    validate_capability_config(config)
    is_guest = _runtime_is_guest(runtime)
    if model_provider is not None and model is None:
        raise ValueError("model_provider override requires an injected model")
    if expected_response_models is not None and model is None:
        raise ValueError("expected_response_models override requires an injected model")
    if is_guest and (
        model_provider is not None or expected_response_models is not None
    ):
        raise ValueError("guest provider contract cannot be overridden")
    usage_model_provider = model_provider or ("openai" if is_guest else "anthropic")
    usage_response_models = (
        expected_response_models
        if expected_response_models is not None
        else (OPENAI_GUEST_RESPONSE_MODEL_NAMES if is_guest else frozenset())
    )
    if usage_model_provider not in {"anthropic", "openai"}:
        raise ValueError("model_provider must be anthropic or openai")
    if (usage_model_provider == "openai") is not bool(usage_response_models):
        raise ValueError("OpenAI provider contract requires exact response models")
    if (
        usage_model_provider == "openai"
        and usage_response_models != OPENAI_GUEST_RESPONSE_MODEL_NAMES
    ):
        raise ValueError("OpenAI provider contract requires exact response models")
    model_spec = (
        _normalized_guest_model_spec()
        if is_guest
        else (
            OPENAI_GUEST_MODEL_SPEC
            if model is not None and usage_model_provider == "openai"
            else _normalized_model_spec()
        )
    )
    _disable_general_purpose_subagent(model_spec)
    selected_model = model or (
        _bounded_guest_model(
            model_spec,
            openai_guest_safety_identifier(getattr(runtime.user, "identity", None)),
        )
        if is_guest
        else _bounded_model(model_spec)
    )
    if is_guest and budget is not None and budget.policy != GUEST_RUN_BUDGET_POLICY:
        raise ValueError("guest graph requires the anonymous run budget policy")
    run_budget = budget or (
        RunBudget(GUEST_RUN_BUDGET_POLICY) if is_guest else RunBudget()
    )
    exact_input_counter = input_token_counter or (
        count_openai_input_tokens
        if model_spec == OPENAI_GUEST_MODEL_SPEC
        else count_anthropic_input_tokens
    )
    exact_input_preparer = (
        prepare_openai_input_token_count
        if (
            input_token_counter is None
            and model_spec == OPENAI_GUEST_MODEL_SPEC
            and isinstance(selected_model, ChatOpenAI)
        )
        else None
    )
    if (
        dynamic_subagents_enabled is not None
        and type(dynamic_subagents_enabled) is not bool
    ):
        raise TypeError("dynamic_subagents_enabled must be a boolean")
    allow_subagents = not is_guest and dynamic_subagents_allowed(
        runtime,
        server_enabled=(
            True if dynamic_subagents_enabled is None else dynamic_subagents_enabled
        ),
    )
    allow_quickjs = not is_guest and quickjs_allowed(
        runtime,
        server_enabled=quickjs_enabled,
    )
    if root_tool_allowlist is not None:
        expected_root_tools = frozenset(
            tool_name
            for tool_name, enabled in (
                (QUICKJS_TOOL_NAME, allow_quickjs),
                (TASK_TOOL_NAME, allow_subagents),
            )
            if enabled
        )
        if (
            model is None
            or is_guest
            or not isinstance(root_tool_allowlist, frozenset)
            or root_tool_allowlist != expected_root_tools
        ):
            raise ValueError(
                "experiment root tool allowlist must exactly match server capabilities"
            )
    effective_root_tool_allowlist = (
        GUEST_ROOT_TOOL_NAMES if is_guest else root_tool_allowlist
    )
    if experiment_subagent_allowlist is not None and (
        model is None
        or is_guest
        or root_tool_allowlist is None
        or not isinstance(experiment_subagent_allowlist, frozenset)
        or not experiment_subagent_allowlist
        or not experiment_subagent_allowlist <= SUBAGENT_NAMES
    ):
        raise ValueError(
            "experiment subagent allowlist must be a non-empty server-declared "
            "frozenset on an injected experiment graph"
        )
    selected_subagents = experiment_subagent_allowlist or SUBAGENT_NAMES
    if quickjs_middleware is None:
        quickjs_middleware = BoundedQuickJSMiddleware(enabled=allow_quickjs)
    elif (
        not isinstance(quickjs_middleware, BoundedQuickJSMiddleware)
        or quickjs_middleware.enabled is not allow_quickjs
    ):
        raise ValueError(
            "quickjs_middleware must match server-side QuickJS authorization"
        )
    system_prompt = GUEST_SYSTEM_PROMPT if is_guest else SYSTEM_PROMPT
    if allow_subagents:
        system_prompt = f"{system_prompt}\n\n{SUBAGENT_ROOT_PROMPT}"
    todo_middleware = (
        TodoListMiddleware(system_prompt="") if is_guest else TodoListMiddleware()
    )

    compiled = create_deep_agent(
        model=selected_model,
        tools=TOOLS,
        system_prompt=system_prompt,
        middleware=[
            todo_middleware,
            quickjs_middleware,
            RunBudgetMiddleware(
                run_budget,
                depth=0,
                allow_subagents=allow_subagents,
                allowed_subagents=selected_subagents,
                input_token_counter=exact_input_counter,
                input_token_count_preparer=exact_input_preparer,
                model_provider=usage_model_provider,
                expected_response_models=usage_response_models,
                quickjs_tool_name=QUICKJS_TOOL_NAME,
                allow_quickjs=allow_quickjs,
                root_tool_allowlist=effective_root_tool_allowlist,
                root_tool_denylist=ROOT_TOOL_DENYLIST,
            ),
        ],
        subagents=build_subagents(
            model=selected_model,
            budget=run_budget,
            input_token_counter=exact_input_counter,
            input_token_count_preparer=exact_input_preparer,
            model_provider=usage_model_provider,
            expected_response_models=usage_response_models,
            allowed_subagents=selected_subagents,
        ),
        backend=_build_backend(persistent_memory=not is_guest),
        skills=[] if is_guest else ["/skills/"],
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
    """Aegra 0.9.25 factory: one non-serializable ledger per run/access call."""
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
                "task=%d tokens=%d count_risk=%d"
            ),
            snapshot.policy_id,
            snapshot.model_calls,
            snapshot.tool_calls,
            snapshot.quickjs_calls,
            snapshot.task_calls,
            snapshot.charged_tokens,
            snapshot.count_risk_tokens,
        )


def _validate_aegra_registration() -> None:
    """Cover startup even when config discovery omits the custom HTTP app."""
    from agent.preflight import validate_runtime_preflight

    _validate_guest_root_tool_contract()
    validate_runtime_preflight()
    validate_guest_execution_fencing_factory(graph)
    if os.environ.get("AGENT_ANONYMOUS_ACCESS_ENABLED", "false") == "true":
        guest_model = _normalized_guest_model_spec()
        if guest_model == OPENAI_GUEST_MODEL_SPEC:
            require_official_openai_routing()
            require_openai_api_key()


_validate_aegra_registration()

__all__ = [
    "GUEST_MODEL_MAX_OUTPUT_TOKENS",
    "GUEST_ROOT_TOOL_NAMES",
    "GUEST_RUN_BUDGET_POLICY",
    "MODEL_MAX_OUTPUT_TOKENS",
    "MODEL_TIMEOUT_SECONDS",
    "create_graph",
    "graph",
]
