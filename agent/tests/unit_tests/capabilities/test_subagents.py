"""Contract tests for server-declared dynamic specialists."""

from types import SimpleNamespace

import pytest
from aegra_api.services.graph_factory import build_server_runtime
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.store.memory import InMemoryStore

from agent.capabilities.budget import RunBudget, RunBudgetMiddleware
from agent.capabilities.subagents import (
    SUBAGENT_NAMES,
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
        "read_post",
        "semantic_search",
    },
    "evidence-checker": {"keyword_search", "read_post"},
    "comparison-synthesizer": {"read_post"},
    "general-purpose": {
        "graph_traverse",
        "keyword_search",
        "list_posts",
        "metadata_filter",
        "read_post",
        "semantic_search",
    },
}


def _model() -> FakeMessagesListChatModel:
    return FakeMessagesListChatModel(responses=[AIMessage(content="bounded")])


def _runtime(permissions, *, context=None):
    user = SimpleNamespace(
        identity="owner",
        display_name="owner",
        is_authenticated=True,
        permissions=permissions,
    )
    return build_server_runtime(
        access_context="threads.create_run",
        store=InMemoryStore(),
        user=user,
        context=context,
    )


def test_declared_subagents_have_explicit_read_only_stateless_contracts():
    budget = RunBudget()
    specs = build_subagents(model=_model(), budget=budget)

    assert [spec["name"] for spec in specs] == [
        "retrieval-researcher",
        "evidence-checker",
        "comparison-synthesizer",
        "general-purpose",
    ]
    assert {spec["name"] for spec in specs} == SUBAGENT_NAMES

    for spec in specs:
        assert "runnable" not in spec
        assert "graph_id" not in spec
        assert {tool.name for tool in spec["tools"]} == EXPECTED_TOOLS[spec["name"]]
        assert {"task", "eval"}.isdisjoint(tool.name for tool in spec["tools"])
        assert spec["skills"] == ["/skills/"]
        assert len(spec["permissions"]) == 1
        permission = spec["permissions"][0]
        assert permission.operations == ["write"]
        assert permission.paths == ["/**"]
        assert permission.mode == "deny"
        prompt = " ".join(spec["system_prompt"].split())
        assert "stateless context" in prompt
        assert "Stop" in prompt
        assert "delegate work" in prompt
        assert "run code" in prompt

        middleware = spec["middleware"]
        assert len(middleware) == 1
        assert isinstance(middleware[0], RunBudgetMiddleware)
        assert middleware[0]._budget is budget
        assert middleware[0]._depth == 1
        assert middleware[0]._allow_subagents is False


@pytest.mark.parametrize("permission", ["admin", "eval"])
def test_server_runtime_permission_enables_dynamic_subagents(permission):
    assert dynamic_subagents_allowed(_runtime([permission])) is True


@pytest.mark.parametrize(
    "permissions",
    [
        [],
        ["anon"],
        "admin",
        ["admin", object()],
    ],
)
def test_missing_or_malformed_runtime_permissions_fail_closed(permissions):
    assert dynamic_subagents_allowed(_runtime(permissions)) is False


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
