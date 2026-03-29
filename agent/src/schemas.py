"""Request/response schemas matching LangGraph Platform API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

# --- Type Aliases ---
ThreadStatus = Literal["idle", "busy", "interrupted", "error"]
RunStatus = Literal["pending", "running", "error", "success", "timeout", "interrupted"]
MultitaskStrategy = Literal["reject", "interrupt", "rollback", "enqueue"]
StreamMode = Literal[
    "values", "messages", "updates", "events", "debug", "custom", "messages-tuple"
]
OnConflictBehavior = Literal["raise", "do_nothing"]
OnCompletionBehavior = Literal["delete", "keep"]
DisconnectMode = Literal["cancel", "continue"]


# ============================================================
# Assistants
# ============================================================
class AssistantCreate(BaseModel):
    graph_id: str
    config: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    assistant_id: str | None = None
    if_exists: OnConflictBehavior | None = None
    name: str = "Untitled"
    description: str | None = None


class AssistantUpdate(BaseModel):
    graph_id: str | None = None
    config: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    name: str | None = None
    description: str | None = None


class AssistantResponse(BaseModel):
    assistant_id: str
    graph_id: str
    config: dict[str, Any]
    context: dict[str, Any]
    metadata: dict[str, Any]
    name: str
    description: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class AssistantSearch(BaseModel):
    metadata: dict[str, Any] | None = None
    graph_id: str | None = None
    name: str | None = None
    limit: int = 10
    offset: int = 0


# ============================================================
# Threads
# ============================================================
class ThreadCreate(BaseModel):
    metadata: dict[str, Any] | None = None
    thread_id: str | None = None
    if_exists: OnConflictBehavior | None = None


class ThreadUpdate(BaseModel):
    metadata: dict[str, Any] | None = None


class ThreadResponse(BaseModel):
    thread_id: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]
    status: ThreadStatus
    values: dict[str, Any] | None = None
    interrupts: dict[str, Any] | None = None


class ThreadSearch(BaseModel):
    metadata: dict[str, Any] | None = None
    values: dict[str, Any] | None = None
    status: ThreadStatus | None = None
    limit: int = 10
    offset: int = 0


class ThreadStateUpdate(BaseModel):
    values: dict[str, Any] | list[dict[str, Any]]
    as_node: str | None = None
    checkpoint: dict[str, Any] | None = None
    checkpoint_id: str | None = None


# ============================================================
# Runs
# ============================================================
class RunCreate(BaseModel):
    assistant_id: str | None = None
    input: dict[str, Any] | None = None
    command: dict[str, Any] | None = None
    stream_mode: list[str] | str | None = None
    stream_subgraphs: bool = False
    config: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    interrupt_before: list[str] | Literal["*"] | None = None
    interrupt_after: list[str] | Literal["*"] | None = None
    webhook: str | None = None
    multitask_strategy: MultitaskStrategy = "reject"
    if_not_exists: Literal["create", "reject"] | None = None
    on_disconnect: DisconnectMode = "cancel"
    on_completion: OnCompletionBehavior | None = None
    checkpoint: dict[str, Any] | None = None
    checkpoint_id: str | None = None
    after_seconds: int | None = None


class RunResponse(BaseModel):
    run_id: str
    thread_id: str
    assistant_id: str | None = None
    created_at: datetime
    updated_at: datetime
    status: RunStatus
    metadata: dict[str, Any]
    multitask_strategy: str | None = None


# ============================================================
# Store
# ============================================================
class StoreItemPut(BaseModel):
    namespace: list[str]
    key: str
    value: dict[str, Any]
    index: bool | list[str] | None = None
    ttl: int | None = None


class StoreItemDelete(BaseModel):
    namespace: list[str]
    key: str


class StoreItemSearch(BaseModel):
    namespace_prefix: list[str]
    filter: dict[str, Any] | None = None
    limit: int = 10
    offset: int = 0
    query: str | None = None


class StoreNamespaceList(BaseModel):
    prefix: list[str] | None = None
    suffix: list[str] | None = None
    max_depth: int | None = None
    limit: int = 100
    offset: int = 0


class ItemResponse(BaseModel):
    namespace: list[str]
    key: str
    value: dict[str, Any]
    created_at: datetime
    updated_at: datetime


# ============================================================
# Crons
# ============================================================
class CronCreate(BaseModel):
    assistant_id: str | None = None
    schedule: str
    input: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    interrupt_before: list[str] | Literal["*"] | None = None
    interrupt_after: list[str] | Literal["*"] | None = None
    webhook: str | None = None
    multitask_strategy: MultitaskStrategy = "reject"
    end_time: datetime | None = None
    enabled: bool = True
    timezone: str | None = None


class CronUpdate(BaseModel):
    schedule: str | None = None
    end_time: datetime | None = None
    input: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    webhook: str | None = None
    interrupt_before: list[str] | Literal["*"] | None = None
    interrupt_after: list[str] | Literal["*"] | None = None
    enabled: bool | None = None
    timezone: str | None = None


class CronResponse(BaseModel):
    cron_id: str
    assistant_id: str | None = None
    thread_id: str | None = None
    schedule: str
    timezone: str | None = None
    end_time: datetime | None = None
    created_at: datetime
    updated_at: datetime
    next_run_date: datetime | None = None
    metadata: dict[str, Any]
    enabled: bool


class CronSearch(BaseModel):
    assistant_id: str | None = None
    thread_id: str | None = None
    enabled: bool | None = None
    limit: int = 10
    offset: int = 0


# ============================================================
# Models
# ============================================================
class ModelCreate(BaseModel):
    provider: str
    model_id: str
    display_name: str
    is_default: bool = False
    enabled: bool = True


class ModelUpdate(BaseModel):
    provider: str | None = None
    model_id: str | None = None
    display_name: str | None = None
    is_default: bool | None = None
    enabled: bool | None = None


class ModelResponse(BaseModel):
    id: str
    provider: str
    model_id: str
    display_name: str
    is_default: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime
