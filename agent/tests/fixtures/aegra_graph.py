"""Deterministic graph for Aegra runtime compatibility tests."""

from typing import Annotated

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import ToolCallTransformer, ToolNode, ToolRuntime
from langgraph.types import interrupt
from typing_extensions import TypedDict

from agent.graph import _build_backend
from agent.inspection import (
    InspectionEventTransformer,
    emit_inspection_payload,
)

FIXTURE_CORPUS_REVISION = "sha256:" + ("a" * 64)
FIXTURE_METHOD_FINGERPRINT = "sha256:" + ("b" * 64)


class FixtureState(TypedDict, total=False):
    """State shared by the root graph and deterministic nested graph."""

    messages: Annotated[list[AnyMessage], add_messages]
    nested_result: str
    approval: str


class MemoryFixtureState(TypedDict, total=False):
    """Input and result for deterministic persistent-memory operations."""

    operation: str
    content: str
    result: str


@tool
def fixture_lookup(
    query: str,
    runtime: ToolRuntime = None,  # type: ignore[assignment]
) -> str:
    """Return a deterministic lookup result."""
    if runtime is not None and runtime.tool_call_id is not None:
        emit_inspection_payload(
            runtime,
            {
                "schema_version": 1,
                "kind": "retrieval",
                "tool_call_id": runtime.tool_call_id,
                "query": query,
                "query_truncated": False,
                "method_id": "fixture-retriever",
                "method_identity": {
                    "method_id": "fixture-retriever",
                    "implementation_id": "agent.tests.fixture:retrieve@1",
                    "fingerprint": FIXTURE_METHOD_FINGERPRINT,
                },
                "hit_count": 1,
                "corpus_revision": FIXTURE_CORPUS_REVISION,
                "corpus_document_count": 1,
                "sources": [
                    {
                        "doc_id": "AI/fixture.md",
                        "title": "Fixture",
                        "rank": 1,
                        "score": 1.0,
                        "provenance": {
                            "kind": "published-corpus",
                            "corpus_revision": FIXTURE_CORPUS_REVISION,
                            "retriever_fingerprint": (FIXTURE_METHOD_FINGERPRINT),
                        },
                    }
                ],
                "sources_truncated": False,
                "stages": [
                    {
                        "stage_id": "fixture-retriever",
                        "implementation_id": "agent.tests.fixture:retrieve@1",
                        "fingerprint": FIXTURE_METHOD_FINGERPRINT,
                        "elapsed_ms": 1.0,
                        "application": {
                            "status": "applied",
                            "input_count": 1,
                            "output_count": 1,
                        },
                    }
                ],
            },
        )
    return f"fixture-result:{query}"


def request_tool(_state: FixtureState) -> FixtureState:
    """Emit a fixed tool call without using a model provider."""
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": fixture_lookup.name,
                        "args": {"query": "aegra"},
                        "id": "fixture-tool-call",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    }


def run_nested_step(_state: FixtureState) -> FixtureState:
    """Produce an update inside a nested namespace."""
    return {"nested_result": "nested-ok"}


def request_approval(_state: FixtureState) -> FixtureState:
    """Pause so the AP v2 input.respond command has a deterministic target."""
    response = interrupt(
        {
            "kind": "fixture-approval",
            "question": "Continue the deterministic Aegra fixture?",
        }
    )
    return {"approval": str(response)}


def finish(state: FixtureState) -> FixtureState:
    """Stream one stable visible assistant message without a provider."""
    return {"messages": [fixture_model.invoke(state["messages"])]}


async def exercise_persistent_memory(
    state: MemoryFixtureState,
) -> MemoryFixtureState:
    """Exercise the production /memories/ route inside LangGraph runtime context."""
    backend = _build_backend()
    path = "/memories/preference.txt"
    if state["operation"] == "write":
        result = await backend.awrite(path, state["content"])
        if result.error:
            raise RuntimeError(result.error)
        return {"result": result.path or ""}
    if state["operation"] == "read":
        result = await backend.aread(path)
        if result.error:
            raise RuntimeError(result.error)
        file_data = result.file_data
        if file_data is None or not isinstance(file_data.get("content"), str):
            raise RuntimeError("persistent memory did not return text content")
        return {"result": file_data["content"]}
    raise ValueError(f"unsupported memory fixture operation: {state['operation']}")


nested_builder = StateGraph(FixtureState)
nested_builder.add_node("nested_worker", run_nested_step)
nested_builder.add_edge(START, "nested_worker")
nested_builder.add_edge("nested_worker", END)
nested_graph = nested_builder.compile()
fixture_model = FakeListChatModel(responses=["fixture-complete"])

builder = StateGraph(FixtureState)
builder.add_node("request_tool", request_tool)
builder.add_node("fixture_tool", ToolNode([fixture_lookup]))
builder.add_node("nested_subgraph", nested_graph)
builder.add_node("request_approval", request_approval)
builder.add_node("finish", finish)
builder.add_edge(START, "request_tool")
builder.add_edge("request_tool", "fixture_tool")
builder.add_edge("fixture_tool", "nested_subgraph")
builder.add_edge("nested_subgraph", "request_approval")
builder.add_edge("request_approval", "finish")
builder.add_edge("finish", END)
graph = builder.compile(transformers=[ToolCallTransformer, InspectionEventTransformer])

memory_builder = StateGraph(MemoryFixtureState)
memory_builder.add_node("memory", exercise_persistent_memory)
memory_builder.add_edge(START, "memory")
memory_builder.add_edge("memory", END)
memory_graph = memory_builder.compile()
