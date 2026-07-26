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
    _build_backend,
    _memory_namespace,
    _trusted_identity,
    graph,
)
from agent.tools import TOOLS


def test_graph_entrypoint_is_compiled_for_aegra():
    assert isinstance(graph, CompiledStateGraph)
    assert graph.checkpointer is None
    assert graph.store is None


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
