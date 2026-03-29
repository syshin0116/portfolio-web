"""Models API routes — manage available LLM models."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from db import DB
from schemas import ModelCreate, ModelResponse, ModelUpdate

router = APIRouter(prefix="/models", tags=["models"])


def _to_response(row: dict) -> ModelResponse:
    return ModelResponse(
        id=str(row["id"]),
        provider=row["provider"],
        model_id=row["model_id"],
        display_name=row["display_name"],
        is_default=row["is_default"],
        enabled=row["enabled"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("", response_model=list[ModelResponse])
async def list_models(
    db: Annotated[DB, Depends(get_db)],
    enabled_only: bool = True,
):
    rows = await db.list_models(enabled_only=enabled_only)
    return [_to_response(r) for r in rows]


@router.post("", response_model=ModelResponse, status_code=201)
async def create_model(
    body: ModelCreate,
    db: Annotated[DB, Depends(get_db)],
):
    row = await db.create_model(
        provider=body.provider,
        model_id=body.model_id,
        display_name=body.display_name,
        is_default=body.is_default,
        enabled=body.enabled,
    )
    return _to_response(row)


@router.patch("/{model_id}", response_model=ModelResponse)
async def update_model(
    model_id: str,
    body: ModelUpdate,
    db: Annotated[DB, Depends(get_db)],
):
    row = await db.update_model(model_id, **body.model_dump(exclude_none=True))
    if not row:
        raise HTTPException(status_code=404, detail="Model not found")
    return _to_response(row)


@router.delete("/{model_id}")
async def delete_model(
    model_id: str,
    db: Annotated[DB, Depends(get_db)],
):
    await db.delete_model(model_id)
    return {"ok": True}
