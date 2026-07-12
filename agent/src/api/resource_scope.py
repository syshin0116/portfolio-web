"""Stable internal identities for user-owned persistent resources."""

from uuid import UUID, uuid5

_CHECKPOINT_NAMESPACE = UUID("e2971bdb-d04e-4c2c-aa20-a00c9d42e720")


def scoped_checkpoint_thread_id(user_id: str, public_thread_id: str) -> str:
    """Map a public thread ID to an owner-specific checkpointer identity."""
    if not user_id:
        raise ValueError("user_id is required")
    return str(uuid5(_CHECKPOINT_NAMESPACE, f"{user_id}\0{public_thread_id}"))
