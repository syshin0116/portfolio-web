"""Offline compatibility checks for the pinned Aegra runtime."""

import json
import runpy
from importlib.metadata import version
from pathlib import Path

import pytest
from aegra_api.main import app
from aegra_api.services.event_streaming.capabilities import (
    _probe_runtime_symbols,
    get_v2_capabilities,
)
from aegra_api.services.event_streaming.native_stream import stream_native_v3_events
from aegra_api.settings import settings
from langchain_core._api import LangChainBetaWarning
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agent.graph import graph

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def test_runtime_dependencies_are_the_spike_versions():
    assert {
        package: version(package)
        for package in (
            "aegra-api",
            "aegra-cli",
            "deepagents",
            "langchain",
            "langchain-core",
            "langgraph",
            "langgraph-checkpoint-postgres",
            "langgraph-sdk",
            "langsmith",
        )
    } == {
        "aegra-api": "0.9.24",
        "aegra-cli": "0.9.24",
        "deepagents": "0.6.12",
        "langchain": "1.3.14",
        "langchain-core": "1.4.9",
        "langgraph": "1.2.9",
        "langgraph-checkpoint-postgres": "3.1.0",
        "langgraph-sdk": "0.4.2",
        "langsmith": "0.10.2",
    }


def test_aegra_config_registers_the_compiled_graph():
    config = json.loads((REPO_ROOT / "aegra.json").read_text())

    assert config == {
        "dependencies": ["./agent/src"],
        "graphs": {"agent": "./agent/src/agent/graph.py:graph"},
    }
    assert isinstance(graph, CompiledStateGraph)


def test_pinned_runtime_supports_aegra_v2_dialect(monkeypatch):
    monkeypatch.setattr(settings.event_streaming, "FF_V2_EVENT_STREAMING", True)
    _probe_runtime_symbols.cache_clear()

    capabilities = get_v2_capabilities()

    assert capabilities.ok
    assert capabilities.missing == ()
    route_paths = {route.path for route in app.routes}
    assert "/threads/{thread_id}/stream/events" in route_paths
    assert "/threads/{thread_id}/commands" in route_paths
    assert "/threads/{thread_id}/stream" not in route_paths


@pytest.mark.filterwarnings(
    f"ignore:The v3 streaming protocol on Pregel is experimental:{LangChainBetaWarning.__module__}.{LangChainBetaWarning.__name__}"
)
async def test_native_stream_fixture_covers_tools_nested_interrupt_and_content_blocks():
    fixture_graph = runpy.run_path(FIXTURE_ROOT / "aegra_graph.py")["graph"]
    runtime_graph = fixture_graph.copy(
        update={
            "checkpointer": InMemorySaver(),
            "store": InMemoryStore(),
        }
    )
    config = {"configurable": {"thread_id": "deterministic-runtime-test"}}

    first_events = [
        event
        async for event in stream_native_v3_events(
            graph=runtime_graph,
            input_data={"messages": [HumanMessage(content="fixture request")]},
            config=config,
        )
    ]

    tool_events = [
        event["params"]["data"]["event"]
        for method, event in first_events
        if method == "tools"
    ]
    namespaces = {
        tuple(event["params"]["namespace"]) for _method, event in first_events
    }
    assert tool_events == ["tool-started", "tool-finished"]
    assert any(
        namespace and namespace[0].startswith("nested_subgraph:")
        for namespace in namespaces
    )
    assert any(event["params"].get("interrupts") for _method, event in first_events)

    resumed_events = [
        event
        async for event in stream_native_v3_events(
            graph=runtime_graph,
            input_data=Command(resume="approved"),
            config=config,
        )
    ]
    message_events = [
        event["params"]["data"]
        for method, event in resumed_events
        if method == "messages"
    ]
    assert message_events[0]["event"] == "message-start"
    assert any(
        event["event"] == "content-block-delta"
        and event["delta"]["type"] == "text-delta"
        for event in message_events
    )
    assert message_events[-1]["event"] == "message-finish"

    snapshot = await runtime_graph.aget_state(config)
    assert not snapshot.interrupts
    assert snapshot.values["nested_result"] == "nested-ok"
    assert snapshot.values["approval"] == "approved"
    assert any(
        isinstance(message, ToolMessage) and message.content == "fixture-result:aegra"
        for message in snapshot.values["messages"]
    )
    assert snapshot.values["messages"][-1].text == "fixture-complete"
