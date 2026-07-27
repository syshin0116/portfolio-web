"""Unit tests for the agent module."""

import hashlib
import inspect
from types import SimpleNamespace

import pytest
from aegra_api.core import database as aegra_database
from aegra_api.services.langgraph_service import LangGraphService
from deepagents import FilesystemPermission
from deepagents.backends import (
    CompositeBackend,
    FilesystemBackend,
    StateBackend,
    StoreBackend,
)
from deepagents.middleware.skills import SkillsMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime, ServerInfo
from langgraph.store.memory import InMemoryStore

from agent.graph import (
    DEFAULT_MODEL,
    _build_backend,
    _filesystem_permissions,
    _memory_namespace,
    _normalized_model_spec,
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


async def test_aegra_injects_request_scoped_persistence_into_static_graph(
    monkeypatch,
):
    checkpointer = InMemorySaver()
    store = InMemoryStore()
    monkeypatch.setattr(
        aegra_database.db_manager,
        "get_checkpointer",
        lambda: checkpointer,
    )
    monkeypatch.setattr(aegra_database.db_manager, "get_store", lambda: store)

    service = LangGraphService()
    service._graph_registry = {
        "agent": {
            "file_path": "./agent/src/agent/graph.py",
            "export_name": "graph",
        }
    }
    service._base_graph_cache["agent"] = graph

    async with service.get_graph("agent") as request_graph:
        assert request_graph is not graph
        assert request_graph.checkpointer is checkpointer
        assert request_graph.store is store

    assert graph.checkpointer is None
    assert graph.store is None


def test_graph_module_never_constructs_its_own_persistence():
    source = inspect.getsource(__import__("agent.graph", fromlist=["graph"]))

    assert "AsyncPostgresSaver" not in source
    assert "AsyncPostgresStore" not in source
    assert "checkpointer=" not in source


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
    assert isinstance(backend.routes["/skills/"], FilesystemBackend)
    assert set(backend.routes) == {"/memories/", "/skills/"}


def test_skills_are_the_only_host_filesystem_route_and_are_write_denied():
    permissions = _filesystem_permissions()

    assert permissions == [
        FilesystemPermission(
            operations=["write"],
            paths=["/skills", "/skills/**"],
            mode="deny",
        )
    ]


def test_single_blog_workflow_skill_loads_without_warnings(caplog):
    middleware = SkillsMiddleware(backend=_build_backend(), sources=["/skills/"])

    update = middleware.before_agent({}, Runtime(), {})

    assert update is not None
    assert update.get("skills_load_errors", []) == []
    assert [(skill["name"], skill["path"]) for skill in update["skills_metadata"]] == [
        ("blog-retrieval", "/skills/blog-retrieval/SKILL.md")
    ]
    assert not caplog.records


def test_expected_blog_tools_are_registered():
    assert {tool.name for tool in TOOLS} == {
        "graph_traverse",
        "keyword_search",
        "list_posts",
        "metadata_filter",
        "read_post",
        "semantic_search",
    }


def test_persistent_memory_namespace_uses_only_runtime_server_identity():
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


def test_persistent_memory_namespace_fails_closed_without_runtime_identity():
    with pytest.raises(ValueError, match="runtime authentication identity"):
        _memory_namespace(Runtime())

    with pytest.raises(ValueError, match="runtime authentication identity"):
        _memory_namespace(
            Runtime(
                server_info=ServerInfo(
                    assistant_id="fixture",
                    graph_id="agent",
                    user=SimpleNamespace(identity=""),
                )
            )
        )
