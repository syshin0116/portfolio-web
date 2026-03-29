"""Assistants API routes — matching LangGraph Platform."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db, get_graph_registry
from db import DB
from schemas import (
    AssistantCreate,
    AssistantResponse,
    AssistantSearch,
    AssistantUpdate,
)

router = APIRouter(prefix="/assistants", tags=["assistants"])


def _to_response(row: dict) -> AssistantResponse:
    return AssistantResponse(
        assistant_id=str(row["assistant_id"]),
        graph_id=row["graph_id"],
        config=row["config"],
        context=row["context"],
        metadata=row["metadata"],
        name=row["name"],
        description=row.get("description"),
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("", response_model=AssistantResponse)
async def create_assistant(
    body: AssistantCreate,
    db: Annotated[DB, Depends(get_db)],
    graphs: Annotated[dict, Depends(get_graph_registry)],
):
    if body.graph_id not in graphs:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown graph_id '{body.graph_id}'. Available: {list(graphs.keys())}",
        )
    row = await db.create_assistant(
        graph_id=body.graph_id,
        config=body.config,
        context=body.context,
        metadata=body.metadata,
        assistant_id=body.assistant_id,
        if_exists=body.if_exists,
        name=body.name,
        description=body.description,
    )
    return _to_response(row)


@router.get("/{assistant_id}", response_model=AssistantResponse)
async def get_assistant(
    assistant_id: str,
    db: Annotated[DB, Depends(get_db)],
):
    row = await db.get_assistant(assistant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Assistant not found")
    return _to_response(row)


@router.patch("/{assistant_id}", response_model=AssistantResponse)
async def update_assistant(
    assistant_id: str,
    body: AssistantUpdate,
    db: Annotated[DB, Depends(get_db)],
):
    row = await db.update_assistant(
        assistant_id,
        graph_id=body.graph_id,
        config=body.config,
        context=body.context,
        metadata=body.metadata,
        name=body.name,
        description=body.description,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Assistant not found")
    return _to_response(row)


@router.delete("/{assistant_id}")
async def delete_assistant(
    assistant_id: str,
    db: Annotated[DB, Depends(get_db)],
):
    await db.delete_assistant(assistant_id)
    return {"ok": True}


@router.post("/search", response_model=list[AssistantResponse])
async def search_assistants(
    body: AssistantSearch,
    db: Annotated[DB, Depends(get_db)],
):
    rows = await db.search_assistants(
        metadata=body.metadata,
        graph_id=body.graph_id,
        name=body.name,
        limit=body.limit,
        offset=body.offset,
    )
    return [_to_response(r) for r in rows]


@router.get("/{assistant_id}/graph")
async def get_assistant_graph(
    assistant_id: str,
    db: Annotated[DB, Depends(get_db)],
    graphs: Annotated[dict, Depends(get_graph_registry)],
):
    row = await db.get_assistant(assistant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Assistant not found")
    compiled_graph = graphs.get(row["graph_id"])
    if not compiled_graph:
        raise HTTPException(status_code=404, detail="Graph not found")
    return compiled_graph.get_graph().to_json()


@router.get("/{assistant_id}/schemas")
async def get_assistant_schemas(
    assistant_id: str,
    db: Annotated[DB, Depends(get_db)],
    graphs: Annotated[dict, Depends(get_graph_registry)],
):
    row = await db.get_assistant(assistant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Assistant not found")
    compiled_graph = graphs.get(row["graph_id"])
    if not compiled_graph:
        raise HTTPException(status_code=404, detail="Graph not found")
    return {
        "graph_id": row["graph_id"],
        "input_schema": compiled_graph.get_input_jsonschema(),
        "output_schema": compiled_graph.get_output_jsonschema(),
        "config_schema": {},
    }
