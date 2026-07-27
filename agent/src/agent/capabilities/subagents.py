"""Server-declared, stateless Deep Agents specialists."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.middleware.skills import SkillsMiddleware
from deepagents.middleware.subagents import (
    TASK_SYSTEM_PROMPT,
    CompiledSubAgent,
)
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import BaseTool, tool
from langgraph_sdk.runtime import ServerRuntime

from agent.capabilities.budget import RunBudget, RunBudgetMiddleware
from agent.capabilities.quickjs import QUICKJS_TOOL_NAME
from agent.capabilities.token_counting import InputTokenCounter
from agent.tools import (
    graph_traverse,
    keyword_search,
    list_posts,
    metadata_filter,
    read_post,
    semantic_search,
)

DYNAMIC_SUBAGENT_PERMISSIONS = frozenset({"admin", "eval"})
SUBAGENT_SKILLS = ("/blog-retrieval/SKILL.md",)
_BLOG_RETRIEVAL_SKILL_DIR = (
    Path(__file__).resolve().parents[3] / "skills" / "blog-retrieval"
)
_BLOG_RETRIEVAL_SKILL_FILE = _BLOG_RETRIEVAL_SKILL_DIR / "SKILL.md"
_BLOG_RETRIEVAL_SKILL_TEXT = _BLOG_RETRIEVAL_SKILL_FILE.read_text(encoding="utf-8")

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
method scope. Use only the provided retrieval tools and the explicitly assigned
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

_CHILD_SKILLS_SYSTEM_PROMPT = """\
## Assigned skill

Exactly one server-owned skill is assigned to this specialist.

{skills_locations}{skills_load_warnings}

{skills_list}

Call `read_blog_retrieval_skill` to load its complete instructions before using
retrieval tools. No general filesystem, parent working files, persistent memories,
or sibling state is available.
"""

_SUBAGENT_DEFINITIONS: tuple[
    tuple[str, str, str, tuple[BaseTool, ...]],
    ...,
] = (
    (
        "retrieval-researcher",
        (
            "Research one bounded corpus/method question and return ranked "
            "DocIds with method-attributed evidence."
        ),
        _RETRIEVAL_RESEARCHER_PROMPT,
        (
            keyword_search,
            semantic_search,
            metadata_filter,
            graph_traverse,
            list_posts,
            read_post,
        ),
    ),
    (
        "evidence-checker",
        "Verify supplied claims and citations against exact published DocIds.",
        _EVIDENCE_CHECKER_PROMPT,
        (keyword_search, read_post),
    ),
    (
        "comparison-synthesizer",
        "Compare supplied retrieval outputs without running a new broad search.",
        _COMPARISON_SYNTHESIZER_PROMPT,
        (read_post,),
    ),
    (
        "general-purpose",
        (
            "Handle a novel but explicitly bounded RAG-analysis decomposition "
            "that does not fit another specialist."
        ),
        _GENERAL_PURPOSE_PROMPT,
        (
            keyword_search,
            semantic_search,
            metadata_filter,
            graph_traverse,
            list_posts,
            read_post,
        ),
    ),
)
SUBAGENT_NAMES = frozenset(
    name for name, _description, _prompt, _tools in _SUBAGENT_DEFINITIONS
)
NATIVE_SUBAGENT_SYSTEM_PROMPT = (
    TASK_SYSTEM_PROMPT
    + "\n\nAvailable subagent types:\n\n"
    + "\n".join(
        f"- {name}: {description}"
        for name, description, _prompt, _tools in _SUBAGENT_DEFINITIONS
    )
)

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


def _permission_set(permissions: object) -> frozenset[str]:
    if not isinstance(permissions, Sequence) or isinstance(
        permissions,
        (str, bytes, bytearray),
    ):
        return frozenset()
    if any(
        not isinstance(permission, str) or not permission for permission in permissions
    ):
        return frozenset()
    return frozenset(permissions)


def dynamic_subagents_allowed(
    runtime: ServerRuntime[Any],
    *,
    server_enabled: bool = True,
) -> bool:
    """Authorize from server selection plus runtime identity, never run config."""
    if not isinstance(server_enabled, bool):
        raise TypeError("server_enabled must be a boolean")
    user = runtime.user
    if (
        not server_enabled
        or user is None
        or getattr(user, "is_authenticated", False) is not True
    ):
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


@tool
def read_blog_retrieval_skill() -> str:
    """Read the one server-curated blog-retrieval skill assigned to this child."""
    return _BLOG_RETRIEVAL_SKILL_TEXT


def _isolated_skill_backend() -> CompositeBackend:
    """Expose one read-only virtual skill tree and no parent/store backend."""
    skill_files = FilesystemBackend(
        root_dir=_BLOG_RETRIEVAL_SKILL_DIR,
        virtual_mode=True,
    )
    return CompositeBackend(
        default=skill_files,
        routes={"/blog-retrieval/": skill_files},
    )


def _sanitize_child_input(state: Mapping[str, Any]) -> dict[str, Any]:
    """Allow only the task envelope messages across the child boundary."""
    messages = state.get("messages")
    if not isinstance(messages, list):
        raise TypeError("compiled subagent input requires a messages list")
    return {"messages": list(messages)}


def _sanitize_child_output(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return only child messages; never merge files or middleware state."""
    messages = state.get("messages")
    if not isinstance(messages, list):
        raise TypeError("compiled subagent output requires a messages list")
    return {"messages": list(messages)}


def _compiled_subagent(
    *,
    name: str,
    description: str,
    system_prompt: str,
    tools: tuple[BaseTool, ...],
    model: BaseChatModel,
    budget: RunBudget,
    input_token_counter: InputTokenCounter,
) -> CompiledSubAgent:
    skill_backend = _isolated_skill_backend()
    child = create_agent(
        model,
        tools=[*tools, read_blog_retrieval_skill],
        system_prompt=system_prompt,
        middleware=[
            SkillsMiddleware(
                backend=skill_backend,
                sources=["/"],
                system_prompt=_CHILD_SKILLS_SYSTEM_PROMPT,
            ),
            RunBudgetMiddleware(
                budget,
                depth=1,
                allow_subagents=False,
                allowed_subagents=frozenset(),
                input_token_counter=input_token_counter,
                quickjs_tool_name=QUICKJS_TOOL_NAME,
                allow_quickjs=False,
            ),
        ],
        name=name,
    )
    isolated = (
        RunnableLambda(_sanitize_child_input)
        | child
        | RunnableLambda(_sanitize_child_output)
    )
    return {
        "name": name,
        "description": description,
        "runnable": isolated,
    }


def build_subagents(
    *,
    model: BaseChatModel,
    budget: RunBudget,
    input_token_counter: InputTokenCounter,
) -> list[CompiledSubAgent]:
    """Return four public compiled specialists with isolated state/backends."""
    return [
        _compiled_subagent(
            name=name,
            description=description,
            system_prompt=system_prompt,
            tools=tools,
            model=model,
            budget=budget,
            input_token_counter=input_token_counter,
        )
        for name, description, system_prompt, tools in _SUBAGENT_DEFINITIONS
    ]


__all__ = [
    "DYNAMIC_SUBAGENT_PERMISSIONS",
    "NATIVE_SUBAGENT_SYSTEM_PROMPT",
    "SUBAGENT_NAMES",
    "SUBAGENT_ROOT_PROMPT",
    "SUBAGENT_SKILLS",
    "build_subagents",
    "dynamic_subagents_allowed",
    "read_blog_retrieval_skill",
    "validate_capability_config",
]
