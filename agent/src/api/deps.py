"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph

from api.run_manager_base import RunManagerBase
from db import DB


def get_checkpointer(request: Request) -> AsyncPostgresSaver:
    return request.app.state.checkpointer


def get_db(request: Request) -> DB:
    return request.app.state.db


def get_run_manager(request: Request) -> RunManagerBase:
    return request.app.state.run_manager


def get_graph_registry(request: Request) -> dict[str, CompiledStateGraph]:
    return request.app.state.graphs


def resolve_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.graphs["agent"]
