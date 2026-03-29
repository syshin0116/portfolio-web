"""Store API routes — matching LangGraph Platform."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_db
from db import DB
from schemas import (
    ItemResponse,
    StoreItemDelete,
    StoreItemPut,
    StoreItemSearch,
    StoreNamespaceList,
)

router = APIRouter(prefix="/store", tags=["store"])


@router.put("/items")
async def put_item(body: StoreItemPut, db: Annotated[DB, Depends(get_db)]):
    await db.store_put(body.namespace, body.key, body.value)
    return {"ok": True}


@router.get("/items", response_model=ItemResponse)
async def get_item(
    db: Annotated[DB, Depends(get_db)],
    namespace: Annotated[str, Query(description="Dot-separated namespace")],
    key: Annotated[str, Query()],
):
    ns = namespace.split(".")
    item = await db.store_get(ns, key)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return ItemResponse(
        namespace=item["namespace"],
        key=item["key"],
        value=item["value"],
        created_at=item["created_at"],
        updated_at=item["updated_at"],
    )


@router.delete("/items")
async def delete_item(body: StoreItemDelete, db: Annotated[DB, Depends(get_db)]):
    await db.store_delete(body.namespace, body.key)
    return {"ok": True}


@router.post("/items/search", response_model=list[ItemResponse])
async def search_items(body: StoreItemSearch, db: Annotated[DB, Depends(get_db)]):
    items = await db.store_search(
        body.namespace_prefix,
        filter=body.filter,
        limit=body.limit,
        offset=body.offset,
    )
    return [
        ItemResponse(
            namespace=i["namespace"],
            key=i["key"],
            value=i["value"],
            created_at=i["created_at"],
            updated_at=i["updated_at"],
        )
        for i in items
    ]


@router.post("/namespaces")
async def list_namespaces(body: StoreNamespaceList, db: Annotated[DB, Depends(get_db)]):
    namespaces = await db.store_list_namespaces(
        prefix=body.prefix,
        suffix=body.suffix,
        max_depth=body.max_depth,
        limit=body.limit,
        offset=body.offset,
    )
    return {"namespaces": namespaces}
