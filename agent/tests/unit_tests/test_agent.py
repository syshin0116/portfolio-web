"""Unit tests for the agent module."""

from agent.graph import create_graph, graph
from agent.tools import TOOLS, get_weather, search_web


def test_graph_compiles():
    """The default graph (no checkpointer) should compile."""
    assert graph is not None


def test_create_graph_factory():
    """create_graph should return a compiled graph."""
    g = create_graph()
    assert g is not None


def test_graph_has_model_node():
    """Deep agent should have a 'model' node."""
    assert "model" in graph.nodes


def test_graph_has_tools_node():
    assert "tools" in graph.nodes


def test_tools_not_empty():
    """Boilerplate should include example tools."""
    assert len(TOOLS) >= 2


def test_get_weather_tool():
    result = get_weather.invoke({"city": "Seoul"})
    assert "Seoul" in result
    assert isinstance(result, str)


def test_search_web_tool():
    result = search_web.invoke({"query": "test query"})
    assert "test query" in result
    assert isinstance(result, str)
