"""Shared test environment for the native Aegra registration."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault(
    "AGENT_AUTH_SECRET",
    "test-secret-that-is-at-least-thirty-two-bytes",
)
os.environ.setdefault("AEGRA_CONFIG", str(REPO_ROOT / "aegra.json"))
os.environ.setdefault("FF_V2_EVENT_STREAMING", "true")
os.environ.setdefault("REDIS_BROKER_ENABLED", "false")
os.environ.setdefault("BG_JOB_MAX_RETRIES", "0")
