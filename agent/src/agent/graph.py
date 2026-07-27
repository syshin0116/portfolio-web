"""Deep Agent — LangGraph standard agent with built-in middleware."""

import hashlib
import os
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
from langgraph.runtime import Runtime

from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOLS

DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"
NO_GENERAL_PURPOSE_SUBAGENT = HarnessProfile(
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
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
    """Return the configured model in Deep Agents' canonical spec form."""
    model = os.environ.get("MODEL") or DEFAULT_MODEL
    # Normalize "provider/model" → "provider:model" for deepagents compatibility
    if "/" in model and ":" not in model:
        model = model.replace("/", ":", 1)
    return model


def _disable_general_purpose_subagent(model: str) -> None:
    """Apply the fail-closed subagent policy to the selected model."""
    register_harness_profile(model, NO_GENERAL_PURPOSE_SUBAGENT)


def create_graph():
    """Build a compiled Deep Agent for Aegra to register.

    Aegra copies the compiled graph and injects its Postgres checkpointer and
    store for each request.

    Set the MODEL env var to override the default model.
    """
    model = _normalized_model_spec()
    _disable_general_purpose_subagent(model)

    return create_deep_agent(
        model=model,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        backend=_build_backend(),
        skills=["/skills/"],
        permissions=_filesystem_permissions(),
    )


def _validate_aegra_registration() -> None:
    """Cover startup even when config discovery omits the custom HTTP app."""
    from agent.preflight import validate_runtime_preflight

    validate_runtime_preflight()


_validate_aegra_registration()
graph = create_graph()

__all__ = ["graph", "create_graph"]
