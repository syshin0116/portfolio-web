"""Side-effect-free durable markers for project-owned run recovery."""

from __future__ import annotations

RECOVERED_GUEST_RUN_FENCE_KEY = "_syshin0116_guest_recovery"
RECOVERED_GUEST_RUN_FENCE_VALUE = "stale-local-executor-v1"

__all__ = [
    "RECOVERED_GUEST_RUN_FENCE_KEY",
    "RECOVERED_GUEST_RUN_FENCE_VALUE",
]
