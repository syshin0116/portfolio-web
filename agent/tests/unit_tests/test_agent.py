"""Unit tests for the agent module."""

from types import SimpleNamespace

from agent.graph import _memory_namespace, graph
from agent.tools import TOOLS


def test_graph_entrypoint_is_lazy_factory():
    assert callable(graph)


def test_expected_blog_tools_are_registered():
    assert {tool.name for tool in TOOLS} == {
        "graph_traverse",
        "keyword_search",
        "list_posts",
        "metadata_filter",
        "read_post",
        "semantic_search",
    }


def test_persistent_memory_namespace_is_user_scoped():
    alice = SimpleNamespace(
        runtime=SimpleNamespace(config={"configurable": {"user_id": "alice"}})
    )
    bob = SimpleNamespace(
        runtime=SimpleNamespace(config={"configurable": {"user_id": "bob"}})
    )

    assert _memory_namespace(alice) != _memory_namespace(bob)
    assert _memory_namespace(alice)[0] == "users"
