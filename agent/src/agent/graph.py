"""Deep Agent — LangGraph standard agent with built-in middleware."""

from __future__ import annotations

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

from agent.capabilities.budget import RunBudget, RunBudgetMiddleware
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
from agent.tools import TOOLS

DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"
MODEL_MAX_OUTPUT_TOKENS = 2_048
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


def _build_backend() -> CompositeBackend:
    """Build the instance backend used by every Aegra graph copy.

    /            -> StateBackend (ephemeral working files per thread)
    /memories/   -> StoreBackend (persistent cross-thread memory)
    /skills/     -> read-only Deep Agents skills
    """
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/memories/": StoreBackend(namespace=_memory_namespace),
            "/skills/": FilesystemBackend(root_dir=SKILLS_DIR, virtual_mode=True),
        },
    )


def _filesystem_permissions() -> list[FilesystemPermission]:
    """Keep mounted skills read-only while leaving thread and memory files writable."""

    return [
        FilesystemPermission(
            operations=["write"],
            paths=["/skills", "/skills/**"],
            mode="deny",
        )
    ]


def _normalized_model_spec() -> str:
    """Return one supported server-configured model in canonical form."""
    model = os.environ.get("MODEL") or DEFAULT_MODEL
    # Normalize "provider/model" → "provider:model" for deepagents compatibility
    if "/" in model and ":" not in model:
        model = model.replace("/", ":", 1)
    if _MODEL_SPEC.fullmatch(model) is None:
        raise RuntimeError("MODEL must be one bounded provider:model spec")
    provider, _separator, _name = model.partition(":")
    if provider not in SUPPORTED_MODEL_PROVIDERS:
        raise RuntimeError(f"MODEL provider {provider!r} is not supported")
    return model


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


def create_graph(
    *,
    runtime: ServerRuntime[Any],
    config: Mapping[str, Any],
    budget: RunBudget | None = None,
    model: BaseChatModel | None = None,
    input_token_counter: InputTokenCounter | None = None,
):
    """Compile one topology-stable Deep Agent around a run-local budget.

    Aegra copies the compiled graph and injects its Postgres checkpointer and
    store after this function returns. Capability authorization comes only
    from ``ServerRuntime.user.permissions``; client config cannot enable it.
    """
    validate_capability_config(config)
    model_spec = _normalized_model_spec()
    _disable_general_purpose_subagent(model_spec)
    selected_model = model or _bounded_model(model_spec)
    run_budget = budget or RunBudget()
    exact_input_counter = input_token_counter or count_anthropic_input_tokens
    allow_subagents = dynamic_subagents_allowed(runtime)
    system_prompt = SYSTEM_PROMPT
    if allow_subagents:
        system_prompt = f"{system_prompt}\n\n{SUBAGENT_ROOT_PROMPT}"

    compiled = create_deep_agent(
        model=selected_model,
        tools=TOOLS,
        system_prompt=system_prompt,
        middleware=[
            RunBudgetMiddleware(
                run_budget,
                depth=0,
                allow_subagents=allow_subagents,
                allowed_subagents=SUBAGENT_NAMES,
                input_token_counter=exact_input_counter,
                native_subagent_prompt=NATIVE_SUBAGENT_SYSTEM_PROMPT,
            )
        ],
        subagents=build_subagents(
            model=selected_model,
            budget=run_budget,
            input_token_counter=exact_input_counter,
        ),
        backend=_build_backend(),
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


@asynccontextmanager
async def graph(
    config: RunnableConfig,
    runtime: ServerRuntime[Any],
) -> AsyncIterator[Any]:
    """Aegra 0.9.24 factory: one non-serializable ledger per run/access call."""
    budget = RunBudget()
    compiled = create_graph(runtime=runtime, config=config, budget=budget)
    try:
        yield compiled
    finally:
        snapshot = budget.snapshot()
        logger.debug(
            "run budget observed policy=%s model=%d tool=%d task=%d tokens=%d",
            snapshot.policy_id,
            snapshot.model_calls,
            snapshot.tool_calls,
            snapshot.task_calls,
            snapshot.charged_tokens,
        )


def _validate_aegra_registration() -> None:
    """Cover startup even when config discovery omits the custom HTTP app."""
    from agent.preflight import validate_runtime_preflight

    validate_runtime_preflight()


_validate_aegra_registration()

__all__ = [
    "MODEL_MAX_OUTPUT_TOKENS",
    "MODEL_TIMEOUT_SECONDS",
    "create_graph",
    "graph",
]
