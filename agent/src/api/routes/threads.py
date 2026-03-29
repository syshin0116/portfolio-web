"""Threads API routes — matching LangGraph Platform."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import BaseMessage
from langgraph.graph.state import CompiledStateGraph

from api.deps import get_db, resolve_graph
from db import DB
from schemas import (
    ThreadCreate,
    ThreadResponse,
    ThreadSearch,
    ThreadStateUpdate,
    ThreadUpdate,
)

router = APIRouter(prefix="/threads", tags=["threads"])


def _to_response(row: dict) -> ThreadResponse:
    return ThreadResponse(
        thread_id=str(row["thread_id"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        metadata=row["metadata"],
        status=row["status"],
        values=row.get("values"),
        interrupts=row.get("interrupts"),
    )


@router.post("", response_model=ThreadResponse)
async def create_thread(
    body: ThreadCreate,
    db: Annotated[DB, Depends(get_db)],
):
    row = await db.create_thread(
        thread_id=body.thread_id,
        metadata=body.metadata,
        if_exists=body.if_exists,
    )
    return _to_response(row)


@router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(
    thread_id: str,
    db: Annotated[DB, Depends(get_db)],
):
    row = await db.get_thread(thread_id)
    if not row:
        raise HTTPException(status_code=404, detail="Thread not found")
    return _to_response(row)


@router.patch("/{thread_id}", response_model=ThreadResponse)
async def update_thread(
    thread_id: str,
    body: ThreadUpdate,
    db: Annotated[DB, Depends(get_db)],
):
    row = await db.update_thread(thread_id, metadata=body.metadata)
    if not row:
        raise HTTPException(status_code=404, detail="Thread not found")
    return _to_response(row)


@router.delete("/{thread_id}")
async def delete_thread(
    thread_id: str,
    db: Annotated[DB, Depends(get_db)],
):
    await db.delete_thread(thread_id)
    return {"ok": True}


@router.post("/search", response_model=list[ThreadResponse])
async def search_threads(
    body: ThreadSearch,
    db: Annotated[DB, Depends(get_db)],
):
    rows = await db.search_threads(
        metadata=body.metadata,
        status=body.status,
        limit=body.limit,
        offset=body.offset,
    )
    return [_to_response(r) for r in rows]


@router.get("/{thread_id}/state")
async def get_thread_state(
    thread_id: str,
    db: Annotated[DB, Depends(get_db)],
    graph: Annotated[CompiledStateGraph, Depends(resolve_graph)],
):
    row = await db.get_thread(thread_id)
    if not row:
        raise HTTPException(status_code=404, detail="Thread not found")

    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)

    if not snapshot or not snapshot.config:
        return {
            "thread_id": thread_id,
            "values": {},
            "next": [],
            "tasks": [],
            "checkpoint": None,
        }

    # Build tasks with interrupt data (matches LangGraph Platform format)
    tasks = []
    for task in snapshot.tasks:
        task_dict: dict[str, Any] = {
            "id": task.id,
            "name": task.name,
            "interrupts": [],
        }
        if task.error:
            task_dict["error"] = str(task.error)
        if task.interrupts:
            task_dict["interrupts"] = [
                {
                    "value": _serialize_value(i.value),
                    "resumable": getattr(i, "resumable", True),
                    "ns": getattr(i, "ns", None),
                    "when": getattr(i, "when", "during"),
                }
                for i in task.interrupts
            ]
        tasks.append(task_dict)

    checkpoint_config = snapshot.config.get("configurable", {})

    return {
        "thread_id": thread_id,
        "values": _serialize_state_values(snapshot.values),
        "next": list(snapshot.next),
        "tasks": tasks,
        "checkpoint": {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_config.get("checkpoint_ns", ""),
            "checkpoint_id": checkpoint_config.get("checkpoint_id"),
        },
        "parent_checkpoint": {
            "thread_id": thread_id,
            "checkpoint_ns": snapshot.parent_config["configurable"].get(
                "checkpoint_ns", ""
            ),
            "checkpoint_id": snapshot.parent_config["configurable"].get(
                "checkpoint_id"
            ),
        }
        if snapshot.parent_config
        else None,
        "created_at": snapshot.created_at,
        "metadata": snapshot.metadata or {},
    }


@router.post("/{thread_id}/state")
async def update_thread_state(
    thread_id: str,
    body: ThreadStateUpdate,
    db: Annotated[DB, Depends(get_db)],
    graph: Annotated[CompiledStateGraph, Depends(resolve_graph)],
):
    row = await db.get_thread(thread_id)
    if not row:
        raise HTTPException(status_code=404, detail="Thread not found")

    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if body.checkpoint_id:
        config["configurable"]["checkpoint_id"] = body.checkpoint_id

    result = await graph.aupdate_state(config, body.values, as_node=body.as_node)
    return {"checkpoint": result}


@router.post("/{thread_id}/history")
async def get_thread_history(
    thread_id: str,
    db: Annotated[DB, Depends(get_db)],
    graph: Annotated[CompiledStateGraph, Depends(resolve_graph)],
    limit: int = 10,
):
    row = await db.get_thread(thread_id)
    if not row:
        raise HTTPException(status_code=404, detail="Thread not found")

    config = {"configurable": {"thread_id": thread_id}}
    history = []

    async for snapshot in graph.aget_state_history(config):
        if len(history) >= limit:
            break

        checkpoint_config = snapshot.config.get("configurable", {})

        tasks = []
        for task in snapshot.tasks:
            task_dict: dict[str, Any] = {
                "id": task.id,
                "name": task.name,
                "interrupts": [],
            }
            if task.interrupts:
                task_dict["interrupts"] = [
                    {
                        "value": _serialize_value(i.value),
                        "resumable": getattr(i, "resumable", True),
                        "ns": getattr(i, "ns", None),
                        "when": getattr(i, "when", "during"),
                    }
                    for i in task.interrupts
                ]
            tasks.append(task_dict)

        history.append(
            {
                "values": _serialize_state_values(snapshot.values),
                "next": list(snapshot.next),
                "tasks": tasks,
                "checkpoint": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_config.get("checkpoint_ns", ""),
                    "checkpoint_id": checkpoint_config.get("checkpoint_id"),
                },
                "parent_checkpoint": {
                    "thread_id": thread_id,
                    "checkpoint_ns": snapshot.parent_config["configurable"].get(
                        "checkpoint_ns", ""
                    ),
                    "checkpoint_id": snapshot.parent_config["configurable"].get(
                        "checkpoint_id"
                    ),
                }
                if snapshot.parent_config
                else None,
                "created_at": snapshot.created_at,
                "metadata": snapshot.metadata or {},
            }
        )

    return history


def _serialize_value(v: Any) -> Any:
    """Make a value JSON-serializable."""
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, dict):
        return {k: _serialize_value(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_serialize_value(item) for item in v]
    if hasattr(v, "model_dump"):
        return v.model_dump()
    if hasattr(v, "dict"):
        return v.dict()
    return str(v)


def _serialize_state_values(values: dict) -> dict:
    result = {}
    for k, v in values.items():
        if isinstance(v, list):
            result[k] = [_serialize_message(m) if hasattr(m, "type") else m for m in v]
        elif hasattr(v, "model_dump"):
            result[k] = v.model_dump()
        else:
            result[k] = v
    return result


def _get_message_text(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return content.get("text", "")
    txts = [c if isinstance(c, str) else (c.get("text") or "") for c in content]
    return "".join(txts).strip()


def _serialize_message(msg: Any) -> dict:
    if hasattr(msg, "model_dump"):
        return msg.model_dump()
    if hasattr(msg, "dict"):
        return msg.dict()
    return {
        "type": getattr(msg, "type", "unknown"),
        "content": _get_message_text(msg) if hasattr(msg, "content") else str(msg),
    }
