"""ARQ liveness checks and stale Redis run-queue recovery."""

from __future__ import annotations

from typing import Any

from arq.constants import default_queue_name, in_progress_key_prefix

from api.run_queue import get_run_head, has_run_heartbeat, unregister_run

_ACTIVE_STATUSES = {"pending", "running"}


async def arq_job_is_live(redis: Any, run_id: str) -> bool:
    """Return whether ARQ still has a queued or executing job for a run."""
    job_id = f"run:{run_id}"
    return bool(
        await redis.exists(f"{in_progress_key_prefix}{job_id}")
        or await redis.zscore(default_queue_name, job_id) is not None
    )


async def prune_stale_heads(
    db: Any,
    redis: Any,
    *,
    thread_id: str,
    thread_key: str,
    run_id: str,
    user_id: str,
) -> bool:
    """Remove dead predecessors and report whether ``run_id`` is now head."""
    while True:
        head_run_id = await get_run_head(redis, thread_key)
        if head_run_id == run_id:
            return True
        if head_run_id is None:
            raise RuntimeError(f"Run {run_id} is missing from its thread queue")

        if await has_run_heartbeat(redis, thread_key, head_run_id):
            return False

        head_record = await db.get_run(thread_id, head_run_id, user_id)
        if head_record and head_record.get("status") in _ACTIVE_STATUSES:
            if await arq_job_is_live(redis, head_run_id):
                return False
            await db.update_run_status(head_run_id, "error", user_id)

        await unregister_run(redis, thread_key, head_run_id)
