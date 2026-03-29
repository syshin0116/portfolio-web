"""Runs API routes — matching LangGraph Platform."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from api.deps import get_db, get_run_manager
from api.run_manager_base import RunConflictError, RunManagerBase
from db import DB
from schemas import RunCreate, RunResponse

router = APIRouter(tags=["runs"])


def _to_response(row: dict) -> RunResponse:
    return RunResponse(
        run_id=str(row["run_id"]),
        thread_id=str(row["thread_id"]),
        assistant_id=str(row["assistant_id"]) if row.get("assistant_id") else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        status=row["status"],
        metadata=row["metadata"],
        multitask_strategy=row.get("multitask_strategy"),
    )


async def _ensure_thread(db: DB, thread_id: str, if_not_exists: str | None = None):
    row = await db.get_thread(thread_id)
    if not row:
        if if_not_exists == "reject":
            raise HTTPException(status_code=404, detail="Thread not found")
        await db.create_thread(thread_id=thread_id)


def _resolve_checkpoint_id(body) -> str | None:
    """Extract checkpoint_id from request body (checkpoint object or checkpoint_id field)."""
    if body.checkpoint_id:
        return body.checkpoint_id
    if body.checkpoint and isinstance(body.checkpoint, dict):
        return body.checkpoint.get("checkpoint_id")
    return None


def _resolve_graph_id(assistant_id: str | None) -> str:
    """Resolve graph_id from assistant_id. Non-UUID values are treated as graph_id directly."""
    if not assistant_id:
        return "agent"
    try:
        uuid.UUID(assistant_id)
        return "agent"  # UUID → look up from DB assistant, default to "agent"
    except ValueError:
        return assistant_id  # e.g. "agent" string → use as graph_id


async def _get_assistant_config(db: DB, assistant_id: str | None) -> dict | None:
    """Look up assistant config from DB. If assistant_id is a graph_id (not UUID), skip DB lookup."""
    if not assistant_id:
        return None
    try:
        uuid.UUID(assistant_id)
    except ValueError:
        return None
    assistant = await db.get_assistant(assistant_id)
    if not assistant:
        return None
    return assistant.get("config")


# =============================================================================
# Stateful runs (with thread_id)
# =============================================================================


@router.post("/threads/{thread_id}/runs", response_model=RunResponse)
async def create_run(
    thread_id: str,
    body: RunCreate,
    db: Annotated[DB, Depends(get_db)],
    run_manager: Annotated[RunManagerBase, Depends(get_run_manager)],
):
    await _ensure_thread(db, thread_id, body.if_not_exists)
    assistant_config = await _get_assistant_config(db, body.assistant_id)
    try:
        row = await run_manager.create_run(
            thread_id,
            run_input=body.input,
            command=body.command,
            config=body.config,
            graph_id=_resolve_graph_id(body.assistant_id),
            assistant_id=body.assistant_id,
            assistant_config=assistant_config,
            metadata=body.metadata,
            stream_mode=body.stream_mode,
            multitask_strategy=body.multitask_strategy,
            interrupt_before=body.interrupt_before,
            interrupt_after=body.interrupt_after,
            webhook=body.webhook,
            checkpoint_id=_resolve_checkpoint_id(body),
        )
    except RunConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _to_response(row)


@router.post("/threads/{thread_id}/runs/stream")
async def stream_run(
    thread_id: str,
    body: RunCreate,
    db: Annotated[DB, Depends(get_db)],
    run_manager: Annotated[RunManagerBase, Depends(get_run_manager)],
):
    await _ensure_thread(db, thread_id, body.if_not_exists)
    assistant_config = await _get_assistant_config(db, body.assistant_id)
    try:
        run_id, event_gen = await run_manager.stream_run(
            thread_id,
            run_input=body.input,
            command=body.command,
            config=body.config,
            graph_id=_resolve_graph_id(body.assistant_id),
            assistant_id=body.assistant_id,
            assistant_config=assistant_config,
            metadata=body.metadata,
            stream_mode=body.stream_mode or "values",
            multitask_strategy=body.multitask_strategy,
            interrupt_before=body.interrupt_before,
            interrupt_after=body.interrupt_after,
            on_disconnect=body.on_disconnect,
            checkpoint_id=_resolve_checkpoint_id(body),
        )
    except RunConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    response = EventSourceResponse(event_gen)
    response.headers["Location"] = f"/threads/{thread_id}/runs/{run_id}/stream"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@router.post("/threads/{thread_id}/runs/wait")
async def wait_run(
    thread_id: str,
    body: RunCreate,
    db: Annotated[DB, Depends(get_db)],
    run_manager: Annotated[RunManagerBase, Depends(get_run_manager)],
):
    await _ensure_thread(db, thread_id, body.if_not_exists)
    assistant_config = await _get_assistant_config(db, body.assistant_id)
    try:
        result = await run_manager.wait_run(
            thread_id,
            run_input=body.input,
            command=body.command,
            config=body.config,
            graph_id=_resolve_graph_id(body.assistant_id),
            assistant_id=body.assistant_id,
            assistant_config=assistant_config,
            metadata=body.metadata,
            multitask_strategy=body.multitask_strategy,
            interrupt_before=body.interrupt_before,
            interrupt_after=body.interrupt_after,
            checkpoint_id=_resolve_checkpoint_id(body),
        )
    except RunConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return result


@router.get("/threads/{thread_id}/runs", response_model=list[RunResponse])
async def list_runs(
    thread_id: str,
    db: Annotated[DB, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: str | None = None,
):
    rows = await db.list_runs(thread_id, limit=limit, offset=offset, status=status)
    return [_to_response(r) for r in rows]


@router.get("/threads/{thread_id}/runs/{run_id}", response_model=RunResponse)
async def get_run(
    thread_id: str,
    run_id: str,
    db: Annotated[DB, Depends(get_db)],
):
    row = await db.get_run(thread_id, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return _to_response(row)


@router.get("/threads/{thread_id}/runs/{run_id}/stream")
async def stream_existing_run(
    thread_id: str,
    run_id: str,
    run_manager: Annotated[RunManagerBase, Depends(get_run_manager)],
):
    """Rejoin an existing run's SSE stream (reconnection after disconnect)."""
    event_gen = run_manager.join_stream(thread_id, run_id)
    response = EventSourceResponse(event_gen)
    response.headers["X-Accel-Buffering"] = "no"
    return response


@router.post("/threads/{thread_id}/runs/{run_id}/cancel")
async def cancel_run(
    thread_id: str,
    run_id: str,
    run_manager: Annotated[RunManagerBase, Depends(get_run_manager)],
):
    await run_manager.cancel_run(thread_id, run_id)
    return {"ok": True}


@router.get("/threads/{thread_id}/runs/{run_id}/join")
async def join_run(
    thread_id: str,
    run_id: str,
    run_manager: Annotated[RunManagerBase, Depends(get_run_manager)],
):
    result = await run_manager.join_run(thread_id, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found or no state")
    return result


@router.delete("/threads/{thread_id}/runs/{run_id}")
async def delete_run(
    thread_id: str,
    run_id: str,
    db: Annotated[DB, Depends(get_db)],
):
    await db.delete_run(thread_id, run_id)
    return {"ok": True}


# =============================================================================
# Stateless runs (ephemeral thread)
# =============================================================================


@router.post("/runs/stream")
async def stateless_stream_run(
    body: RunCreate,
    db: Annotated[DB, Depends(get_db)],
    run_manager: Annotated[RunManagerBase, Depends(get_run_manager)],
):
    thread_id = str(uuid.uuid4())
    await db.create_thread(thread_id=thread_id)
    assistant_config = await _get_assistant_config(db, body.assistant_id)
    run_id, event_gen = await run_manager.stream_run(
        thread_id,
        run_input=body.input,
        command=body.command,
        config=body.config,
        assistant_id=body.assistant_id,
        assistant_config=assistant_config,
        metadata=body.metadata,
        stream_mode=body.stream_mode or "values",
        interrupt_before=body.interrupt_before,
        interrupt_after=body.interrupt_after,
    )
    response = EventSourceResponse(event_gen)
    response.headers["Location"] = f"/threads/{thread_id}/runs/{run_id}/stream"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@router.post("/runs", response_model=RunResponse)
async def stateless_create_run(
    body: RunCreate,
    db: Annotated[DB, Depends(get_db)],
    run_manager: Annotated[RunManagerBase, Depends(get_run_manager)],
):
    thread_id = str(uuid.uuid4())
    await db.create_thread(thread_id=thread_id)
    assistant_config = await _get_assistant_config(db, body.assistant_id)
    row = await run_manager.create_run(
        thread_id,
        run_input=body.input,
        command=body.command,
        config=body.config,
        assistant_id=body.assistant_id,
        assistant_config=assistant_config,
        metadata=body.metadata,
        multitask_strategy=body.multitask_strategy,
        interrupt_before=body.interrupt_before,
        interrupt_after=body.interrupt_after,
    )
    return _to_response(row)


@router.post("/runs/wait")
async def stateless_wait_run(
    body: RunCreate,
    db: Annotated[DB, Depends(get_db)],
    run_manager: Annotated[RunManagerBase, Depends(get_run_manager)],
):
    thread_id = str(uuid.uuid4())
    await db.create_thread(thread_id=thread_id)
    assistant_config = await _get_assistant_config(db, body.assistant_id)
    result = await run_manager.wait_run(
        thread_id,
        run_input=body.input,
        command=body.command,
        config=body.config,
        assistant_id=body.assistant_id,
        assistant_config=assistant_config,
        metadata=body.metadata,
        interrupt_before=body.interrupt_before,
        interrupt_after=body.interrupt_after,
    )
    return result
