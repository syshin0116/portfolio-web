"""Crons API routes — matching LangGraph Platform."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_db
from db import DB
from schemas import CronCreate, CronResponse, CronSearch, CronUpdate

router = APIRouter(tags=["crons"])


def _to_response(row: dict) -> CronResponse:
    return CronResponse(
        cron_id=str(row["cron_id"]),
        assistant_id=str(row["assistant_id"]) if row.get("assistant_id") else None,
        thread_id=str(row["thread_id"]) if row.get("thread_id") else None,
        schedule=row["schedule"],
        timezone=row.get("timezone"),
        end_time=row.get("end_time"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        next_run_date=row.get("next_run_date"),
        metadata=row["metadata"],
        enabled=row["enabled"],
    )


@router.post("/threads/{thread_id}/runs/crons", response_model=CronResponse)
async def create_thread_cron(
    thread_id: str, body: CronCreate, db: Annotated[DB, Depends(get_db)]
):
    row = await db.create_cron(
        schedule=body.schedule,
        assistant_id=body.assistant_id,
        thread_id=thread_id,
        input=body.input,
        config=body.config,
        metadata=body.metadata,
        enabled=body.enabled,
        timezone=body.timezone,
        end_time=body.end_time,
    )
    return _to_response(row)


@router.post("/runs/crons", response_model=CronResponse)
async def create_stateless_cron(body: CronCreate, db: Annotated[DB, Depends(get_db)]):
    row = await db.create_cron(
        schedule=body.schedule,
        assistant_id=body.assistant_id,
        input=body.input,
        config=body.config,
        metadata=body.metadata,
        enabled=body.enabled,
        timezone=body.timezone,
        end_time=body.end_time,
    )
    return _to_response(row)


@router.patch("/runs/crons/{cron_id}", response_model=CronResponse)
async def update_cron(
    cron_id: str, body: CronUpdate, db: Annotated[DB, Depends(get_db)]
):
    row = await db.update_cron(
        cron_id,
        schedule=body.schedule,
        end_time=body.end_time,
        input=body.input,
        metadata=body.metadata,
        config=body.config,
        context=body.context,
        webhook=body.webhook,
        enabled=body.enabled,
        timezone=body.timezone,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Cron not found")
    return _to_response(row)


@router.delete("/runs/crons/{cron_id}")
async def delete_cron(cron_id: str, db: Annotated[DB, Depends(get_db)]):
    await db.delete_cron(cron_id)
    return {"ok": True}


@router.post("/runs/crons/search", response_model=list[CronResponse])
async def search_crons(body: CronSearch, db: Annotated[DB, Depends(get_db)]):
    rows = await db.search_crons(
        assistant_id=body.assistant_id,
        thread_id=body.thread_id,
        enabled=body.enabled,
        limit=body.limit,
        offset=body.offset,
    )
    return [_to_response(r) for r in rows]
