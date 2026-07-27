"""Unit tests for the agent module."""

import hashlib
import importlib
import warnings
from types import SimpleNamespace

import pytest
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime, ServerInfo

from agent.graph import (
    DEFAULT_MODEL,
    _build_backend,
    _memory_namespace,
    _normalized_model_spec,
    _trusted_identity,
    create_graph,
    graph,
)
from agent.tools import TOOLS


def _compiled_tool_names(compiled_graph: CompiledStateGraph) -> set[str]:
    return set(compiled_graph.nodes["tools"].bound._tools_by_name)


def test_graph_entrypoint_is_compiled_for_aegra():
    assert isinstance(graph, CompiledStateGraph)
    assert graph.checkpointer is None
    assert graph.store is None


def test_compiled_graph_disables_general_purpose_subagent_dispatch():
    registered_tools = _compiled_tool_names(graph)

    assert {tool.name for tool in TOOLS} <= registered_tools
    assert "task" not in registered_tools


@pytest.mark.parametrize(
    ("configured_model", "expected_model"),
    [
        (None, DEFAULT_MODEL),
        ("anthropic/claude-haiku-4-5", "anthropic:claude-haiku-4-5"),
    ],
    ids=["default-model", "normalized-model-override"],
)
def test_create_graph_for_selected_model_disables_general_purpose_dispatch(
    monkeypatch,
    configured_model,
    expected_model,
):
    if configured_model is None:
        monkeypatch.delenv("MODEL", raising=False)
    else:
        monkeypatch.setenv("MODEL", configured_model)

    compiled_graph = create_graph()

    assert _normalized_model_spec() == expected_model
    assert isinstance(compiled_graph, CompiledStateGraph)
    assert {tool.name for tool in TOOLS} <= _compiled_tool_names(compiled_graph)
    assert "task" not in _compiled_tool_names(compiled_graph)


def test_backend_uses_instances_for_all_routes():
    backend = _build_backend()

    assert isinstance(backend, CompositeBackend)
    assert not callable(backend)
    assert isinstance(backend.default, StateBackend)
    assert isinstance(backend.routes["/memories/"], StoreBackend)
    assert set(backend.routes) == {"/blog/", "/memories/", "/skills/"}


def test_expected_blog_tools_are_registered():
    assert {tool.name for tool in TOOLS} == {
        "graph_traverse",
        "keyword_search",
        "list_posts",
        "metadata_filter",
        "read_post",
        "semantic_search",
    }


def test_persistent_memory_namespace_uses_trusted_identity(monkeypatch):
    graph_module = importlib.import_module("agent.graph")
    config = {
        "configurable": {
            "user_id": "spoofed-client-value",
            "langgraph_auth_user": SimpleNamespace(identity="alice"),
        }
    }
    monkeypatch.setattr(graph_module, "get_config", lambda: config)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        alice = _memory_namespace(Runtime())
        config["configurable"]["user_id"] = "another-spoofed-value"
        assert _memory_namespace(Runtime()) == alice

        config["configurable"]["langgraph_auth_user"] = {"identity": "bob"}
        bob = _memory_namespace(Runtime())

    assert alice != bob
    assert alice[0] == "users"
    assert bob[0] == "users"
    assert not [
        warning
        for warning in caught
        if issubclass(warning.category, DeprecationWarning)
    ]


def test_persistent_memory_namespace_prefers_runtime_server_identity(monkeypatch):
    graph_module = importlib.import_module("agent.graph")
    monkeypatch.setattr(
        graph_module,
        "get_config",
        lambda: {
            "configurable": {
                "user_id": "spoofed-client-value",
                "langgraph_auth_user": {"identity": "stale-config-value"},
            }
        },
    )
    runtime = Runtime(
        server_info=ServerInfo(
            assistant_id="fixture",
            graph_id="agent",
            user=SimpleNamespace(identity="runtime-user"),
        )
    )

    assert _memory_namespace(runtime) == (
        "users",
        hashlib.sha256(b"runtime-user").hexdigest(),
        "filesystem",
    )


def test_trusted_identity_requires_aegra_auth_context():
    with pytest.raises(ValueError, match="authentication context"):
        _trusted_identity({})

    with pytest.raises(ValueError, match="authentication identity"):
        _trusted_identity({"configurable": {"user_id": "client-controlled"}})
