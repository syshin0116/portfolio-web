"""Contract tests for server-declared dynamic specialists."""

from types import SimpleNamespace

import pytest
from aegra_api.services.graph_factory import build_server_runtime
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.memory import InMemoryStore
from pydantic import Field

from agent.capabilities.budget import RunBudget
from agent.capabilities.quickjs import QUICKJS_SYSTEM_PROMPT
from agent.capabilities.subagents import (
    BOUNDED_TASK_TOOL_DESCRIPTION,
    SUBAGENT_NAMES,
    SUBAGENT_SKILLS,
    build_subagents,
    dynamic_subagents_allowed,
    validate_capability_config,
)

EXPECTED_TOOLS = {
    "retrieval-researcher": {
        "graph_traverse",
        "keyword_search",
        "list_posts",
        "metadata_filter",
        "read_blog_retrieval_skill",
        "read_post",
        "semantic_search",
    },
    "evidence-checker": {
        "keyword_search",
        "read_blog_retrieval_skill",
        "read_post",
    },
    "comparison-synthesizer": {
        "read_blog_retrieval_skill",
        "read_post",
    },
    "general-purpose": {
        "graph_traverse",
        "keyword_search",
        "list_posts",
        "metadata_filter",
        "read_blog_retrieval_skill",
        "read_post",
        "semantic_search",
    },
}


class ToolCapableFakeModel(FakeMessagesListChatModel):
    """Fake model that preserves the exact tool surface under test."""

    bound_tool_names: list[frozenset[str]] = Field(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        del tool_choice, kwargs
        self.bound_tool_names.append(
            frozenset(
                tool.get("name") if isinstance(tool, dict) else tool.name
                for tool in tools
            )
        )
        return self


def _model() -> ToolCapableFakeModel:
    return ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="bounded",
                usage_metadata={
                    "input_tokens": 9,
                    "output_tokens": 1,
                    "total_tokens": 10,
                },
            )
            for _index in range(4)
        ]
    )


def _runtime(permissions, *, context=None, is_authenticated=True):
    user = SimpleNamespace(
        identity="owner",
        display_name="owner",
        is_authenticated=is_authenticated,
        permissions=permissions,
    )
    return build_server_runtime(
        access_context="threads.create_run",
        store=InMemoryStore(),
        user=user,
        context=context,
    )


async def test_compiled_subagents_enforce_real_state_and_backend_isolation():
    budget = RunBudget()
    observed_requests = []

    async def exact_input_tokens(request):
        observed_requests.append(request)
        return 10

    specs = build_subagents(
        model=_model(),
        budget=budget,
        input_token_counter=exact_input_tokens,
    )

    assert [spec["name"] for spec in specs] == [
        "retrieval-researcher",
        "evidence-checker",
        "comparison-synthesizer",
        "general-purpose",
    ]
    assert {spec["name"] for spec in specs} == SUBAGENT_NAMES
    assert SUBAGENT_SKILLS == ("/blog-retrieval/SKILL.md",)

    for spec in specs:
        assert set(spec) == {"name", "description", "runnable"}
        assert "graph_id" not in spec
        result = await spec["runnable"].ainvoke(
            {
                "messages": [HumanMessage(content=f"dispatch:{spec['name']}")],
                "files": {
                    "/parent-secret.txt": {
                        "content": "PARENT_ONLY_SECRET",
                        "encoding": "utf-8",
                    },
                    f"/sibling-{spec['name']}.txt": {
                        "content": "SIBLING_ONLY_SECRET",
                        "encoding": "utf-8",
                    },
                },
                "memory_contents": {"preference": "PERSISTENT_ONLY_SECRET"},
            },
            {"configurable": {"thread_id": f"isolated-{spec['name']}"}},
        )
        assert set(result) == {"messages"}

    assert len(observed_requests) == 4
    for spec, request in zip(specs, observed_requests, strict=True):
        assert "files" not in request.state
        assert "memory_contents" not in request.state
        assert len(request.messages) == 1
        assert request.messages[0].content == f"dispatch:{spec['name']}"
        tool_names = {
            tool.get("name") if isinstance(tool, dict) else tool.name
            for tool in request.tools
        }
        assert tool_names == EXPECTED_TOOLS[spec["name"]]
        assert {
            "task",
            "eval",
            "ls",
            "read_file",
            "write_file",
            "edit_file",
            "glob",
            "grep",
            "execute",
            "fetch",
            "http",
            "network",
            "shell",
            "python",
            "process",
            "env",
        }.isdisjoint(tool_names)
        system_text = str(request.system_message.content)
        assert "Exactly one server-owned skill" in system_text
        assert "blog-retrieval" in system_text
        assert "/blog-retrieval/SKILL.md" in system_text
        assert QUICKJS_SYSTEM_PROMPT.strip() not in system_text
        assert "QuickJS" not in system_text
        assert "tools.eval" not in system_text
        assert "task()" not in system_text

    snapshot = budget.snapshot()
    assert (snapshot.model_calls, snapshot.charged_tokens) == (4, 40)


def test_eval_inventory_compiles_only_the_evidence_checker():
    specs = build_subagents(
        model=_model(),
        budget=RunBudget(),
        input_token_counter=lambda _request: 1,
        allowed_subagents=frozenset({"evidence-checker"}),
    )

    assert [spec["name"] for spec in specs] == ["evidence-checker"]


def test_bounded_task_description_preserves_native_inventory_and_budget_hooks():
    assert "{available_agents}" in BOUNDED_TASK_TOOL_DESCRIPTION
    assert "Launch an ephemeral subagent" in BOUNDED_TASK_TOOL_DESCRIPTION
    assert "shared run budget" in BOUNDED_TASK_TOOL_DESCRIPTION
    assert "at most two task dispatches" in BOUNDED_TASK_TOOL_DESCRIPTION
    for heading in (
        "Question:",
        "Allowed corpus/method scope:",
        "Expected output schema:",
        "Stopping condition:",
    ):
        assert heading in BOUNDED_TASK_TOOL_DESCRIPTION


@pytest.mark.parametrize("permission", ["admin", "eval"])
def test_server_runtime_permission_enables_dynamic_subagents(permission):
    assert dynamic_subagents_allowed(_runtime([permission])) is True


def test_server_selected_off_arm_cannot_be_reenabled_by_eval_permission():
    assert (
        dynamic_subagents_allowed(
            _runtime(["eval"]),
            server_enabled=False,
        )
        is False
    )


def test_malformed_server_subagent_selection_fails_closed():
    with pytest.raises(TypeError, match="boolean"):
        dynamic_subagents_allowed(
            _runtime(["eval"]),
            server_enabled=1,
        )


@pytest.mark.parametrize(
    "permissions",
    [
        [],
        ["anon"],
        "admin",
        b"admin",
        bytearray(b"admin"),
        7,
        {"admin"},
        {"admin": True},
        ["admin", object()],
        ["admin", ""],
    ],
)
def test_missing_or_malformed_runtime_permissions_fail_closed(permissions):
    assert dynamic_subagents_allowed(_runtime(permissions)) is False


@pytest.mark.parametrize(
    "is_authenticated",
    [False, None, 0, 1, "true", object()],
)
def test_non_boolean_or_false_authentication_state_fails_closed(is_authenticated):
    assert (
        dynamic_subagents_allowed(
            _runtime(["admin"], is_authenticated=is_authenticated)
        )
        is False
    )


def test_client_context_permissions_cannot_escalate_server_runtime():
    runtime = _runtime(
        [],
        context={
            "permissions": ["admin"],
            "enable_subagents": True,
        },
    )

    assert dynamic_subagents_allowed(runtime) is False


def test_normal_aegra_config_is_accepted_without_mutation():
    config = {
        "configurable": {
            "thread_id": "thread-1",
            "run_id": "run-1",
            "user_id": "owner",
            "langgraph_auth_user": object(),
        },
        "metadata": {"trace_id": "trace-1"},
        "recursion_limit": 9999,
    }

    validate_capability_config(config)

    assert config["configurable"]["thread_id"] == "thread-1"


@pytest.mark.parametrize(
    "config",
    [
        {"model": "client:model"},
        {"quickjs": True},
        {"configurable": {"enable_subagents": True}},
        {"configurable": {"__deepagents_subagent_response_format": {"type": "object"}}},
        {"configurable": {"capability_dynamic_subagents": "on"}},
        {"configurable": []},
        {"configurable": {1: "not-a-string-key"}},
    ],
)
def test_client_capability_or_model_overrides_fail_closed(config):
    with pytest.raises(ValueError, match="server-owned|mapping|strings"):
        validate_capability_config(config)
