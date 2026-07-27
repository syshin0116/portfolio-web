"""Server-declared, stateless Deep Agents specialists."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from deepagents import FilesystemPermission
from deepagents.middleware.subagents import SubAgent
from langchain_core.language_models import BaseChatModel
from langgraph_sdk.runtime import ServerRuntime

from agent.capabilities.budget import RunBudget, RunBudgetMiddleware
from agent.tools import (
    graph_traverse,
    keyword_search,
    list_posts,
    metadata_filter,
    read_post,
    semantic_search,
)

SUBAGENT_NAMES = frozenset(
    {
        "retrieval-researcher",
        "evidence-checker",
        "comparison-synthesizer",
        "general-purpose",
    }
)
DYNAMIC_SUBAGENT_PERMISSIONS = frozenset({"admin", "eval"})
SUBAGENT_SKILLS = ["/skills/"]

SUBAGENT_ROOT_PROMPT = """\
Dynamic delegation is an owner/evaluation capability. Use it only when isolating a
multi-step investigation materially improves the result. Every `task` description must
be a complete, stateless envelope with these headings in this exact order:

Question:
Allowed corpus/method scope:
Expected output schema:
Stopping condition:

The child cannot ask follow-up questions or remember another dispatch. Delegate at most
two independent tasks, never ask a child to create another child, and synthesize the
visitor-facing answer in the root agent. Do not request a dynamic response schema through
run configuration.
"""

_RETRIEVAL_RESEARCHER_PROMPT = """\
You are the retrieval-researcher for a published-blog RAG evaluation testbed.
Treat the dispatch as your entire stateless context. Stay inside its allowed corpus and
method scope. Use only the provided retrieval tools and the explicitly mounted
blog-retrieval skill. Return concise findings with exact content-relative DocIds, the
retrieval method used for each finding, and evidence snippets. Stop as soon as the stated
stopping condition is met. Never write files, delegate work, run code, or produce the
visitor-facing final answer.
"""

_EVIDENCE_CHECKER_PROMPT = """\
You are the evidence-checker for a published-blog RAG evaluation testbed.
Treat the dispatch as your entire stateless context. Verify each supplied claim against
the allowed published DocIds using literal lookup and direct post reads. Return a compact
claim-by-claim verdict containing supported/unsupported, exact DocIds, and a short reason.
Stop at the stated stopping condition. Never invent a citation, write files, delegate
work, run code, or produce the visitor-facing final answer.
"""

_COMPARISON_SYNTHESIZER_PROMPT = """\
You are the comparison-synthesizer for retrieval experiment evidence.
Treat the dispatch as your entire stateless context. Compare only the supplied methods,
ranked IDs, and allowed published posts. Use direct post reads solely to resolve a stated
evidence ambiguity. Return the requested comparison schema with method-attributed DocIds,
agreements, disagreements, and unresolved gaps. Stop at the stated stopping condition.
Never broaden scope, write files, delegate work, run code, or produce the visitor-facing
final answer.
"""

_GENERAL_PURPOSE_PROMPT = """\
You are a bounded general-purpose specialist for unusual RAG-analysis decompositions.
Treat the dispatch as your entire stateless context and stay strictly inside its allowed
published corpus/method scope. Use the minimum provided read-only retrieval tools, cite
exact content-relative DocIds, and return only the requested output schema. Stop at the
stated stopping condition. Never write files, delegate work, run code, change capability
settings, or produce the visitor-facing final answer.
"""

_FORBIDDEN_CONFIG_KEYS = frozenset(
    {
        "__deepagents_subagent_response_format",
        "budget",
        "capabilities",
        "capability",
        "code_interpreter",
        "enable_subagents",
        "model",
        "permissions",
        "quickjs",
        "run_budget",
        "subagents",
        "subagent_types",
        "tools",
    }
)


def _permission_set(permissions: Sequence[str] | None) -> frozenset[str]:
    if permissions is None or isinstance(permissions, str):
        return frozenset()
    if any(
        not isinstance(permission, str) or not permission for permission in permissions
    ):
        return frozenset()
    return frozenset(permissions)


def dynamic_subagents_allowed(runtime: ServerRuntime[Any]) -> bool:
    """Authorize only from the authenticated server runtime, never run config."""
    user = runtime.user
    if user is None:
        return False
    return bool(
        _permission_set(getattr(user, "permissions", None))
        & DYNAMIC_SUBAGENT_PERMISSIONS
    )


def _reject_reserved_keys(mapping: Mapping[Any, Any], *, location: str) -> None:
    for key in mapping:
        if not isinstance(key, str):
            raise ValueError(f"{location} keys must be strings")
        normalized = key.casefold()
        if (
            normalized in _FORBIDDEN_CONFIG_KEYS
            or normalized.startswith("__deepagents_")
            or normalized.startswith("capability_")
        ):
            raise ValueError(f"{location}.{key} is server-owned")


def validate_capability_config(config: Mapping[str, Any]) -> None:
    """Reject client fields that could alter model, budget, or child capabilities."""
    if not isinstance(config, Mapping):
        raise ValueError("run config must be a mapping")
    _reject_reserved_keys(config, location="config")
    configurable = config.get("configurable", {})
    if not isinstance(configurable, Mapping):
        raise ValueError("config.configurable must be a mapping")
    _reject_reserved_keys(configurable, location="config.configurable")


def _read_only_permissions() -> list[FilesystemPermission]:
    return [
        FilesystemPermission(
            operations=["write"],
            paths=["/**"],
            mode="deny",
        )
    ]


def _middleware(budget: RunBudget) -> list[RunBudgetMiddleware]:
    return [
        RunBudgetMiddleware(
            budget,
            depth=1,
            allow_subagents=False,
            allowed_subagents=frozenset(),
        )
    ]


def build_subagents(
    *,
    model: BaseChatModel,
    budget: RunBudget,
) -> list[SubAgent]:
    """Return four declarative specs sharing one root-owned ledger."""
    permissions = _read_only_permissions()
    return [
        {
            "name": "retrieval-researcher",
            "description": (
                "Research one bounded corpus/method question and return ranked "
                "DocIds with method-attributed evidence."
            ),
            "system_prompt": _RETRIEVAL_RESEARCHER_PROMPT,
            "model": model,
            "tools": [
                keyword_search,
                semantic_search,
                metadata_filter,
                graph_traverse,
                list_posts,
                read_post,
            ],
            "middleware": _middleware(budget),
            "skills": list(SUBAGENT_SKILLS),
            "permissions": list(permissions),
        },
        {
            "name": "evidence-checker",
            "description": (
                "Verify supplied claims and citations against exact published DocIds."
            ),
            "system_prompt": _EVIDENCE_CHECKER_PROMPT,
            "model": model,
            "tools": [keyword_search, read_post],
            "middleware": _middleware(budget),
            "skills": list(SUBAGENT_SKILLS),
            "permissions": list(permissions),
        },
        {
            "name": "comparison-synthesizer",
            "description": (
                "Compare supplied retrieval outputs without running a new broad search."
            ),
            "system_prompt": _COMPARISON_SYNTHESIZER_PROMPT,
            "model": model,
            "tools": [read_post],
            "middleware": _middleware(budget),
            "skills": list(SUBAGENT_SKILLS),
            "permissions": list(permissions),
        },
        {
            "name": "general-purpose",
            "description": (
                "Handle a novel but explicitly bounded RAG-analysis decomposition "
                "that does not fit another specialist."
            ),
            "system_prompt": _GENERAL_PURPOSE_PROMPT,
            "model": model,
            "tools": [
                keyword_search,
                semantic_search,
                metadata_filter,
                graph_traverse,
                list_posts,
                read_post,
            ],
            "middleware": _middleware(budget),
            "skills": list(SUBAGENT_SKILLS),
            "permissions": list(permissions),
        },
    ]


__all__ = [
    "DYNAMIC_SUBAGENT_PERMISSIONS",
    "SUBAGENT_NAMES",
    "SUBAGENT_ROOT_PROMPT",
    "SUBAGENT_SKILLS",
    "build_subagents",
    "dynamic_subagents_allowed",
    "validate_capability_config",
]
