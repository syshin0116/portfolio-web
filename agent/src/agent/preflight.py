"""Fail-closed checks around Aegra 0.9.24's permissive auth loader."""

from __future__ import annotations

import inspect
import os

from aegra_api.config import load_config
from aegra_api.core.auth_middleware import (
    LangGraphAuthBackend,
    get_auth_backend,
)
from aegra_api.settings import settings
from langgraph_sdk import Auth

from agent.auth import auth, authenticate, server_anonymous_access_enabled
from agent.capabilities.quickjs import server_quickjs_enabled
from agent.database_url import require_direct_neon_database_url

EXPECTED_DEPENDENCIES = ["./agent/src"]
EXPECTED_GRAPHS = {"agent": "./agent/src/agent/graph.py:graph"}
EXPECTED_AUTH = {
    "path": "agent.auth:auth",
    "disable_studio_auth": False,
}
EXPECTED_HTTP = {
    "app": "agent.http:app",
    "enable_custom_route_auth": False,
}


def _require_exact_registration(config: dict) -> None:
    expected = {
        "dependencies": EXPECTED_DEPENDENCIES,
        "graphs": EXPECTED_GRAPHS,
        "auth": EXPECTED_AUTH,
        "http": EXPECTED_HTTP,
    }
    for key, value in expected.items():
        if config.get(key) != value:
            raise RuntimeError(f"aegra.json {key!r} registration is invalid")


def _require_auth_handler() -> None:
    backend = get_auth_backend()
    if not isinstance(backend, LangGraphAuthBackend):
        raise RuntimeError("Aegra custom authentication backend is not active")
    if backend.auth_instance is not auth or not isinstance(auth, Auth):
        raise RuntimeError("Aegra did not load the configured Auth instance")
    if auth._authenticate_handler is not authenticate:
        raise RuntimeError("Aegra did not load the configured authenticate handler")

    signature = inspect.signature(authenticate)
    parameters = list(signature.parameters.values())
    if (
        len(parameters) != 1
        or parameters[0].name != "headers"
        or parameters[0].kind
        not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        or parameters[0].default is not inspect.Parameter.empty
    ):
        raise RuntimeError(
            "Aegra 0.9.24 authenticate must accept one positional headers mapping"
        )


def validate_runtime_preflight() -> None:
    """Abort application construction if auth/runtime registration is unsafe."""
    server_quickjs_enabled()
    if server_anonymous_access_enabled() and not os.environ.get("GUEST_MODEL"):
        raise RuntimeError(
            "GUEST_MODEL is required when anonymous agent access is enabled"
        )
    config = load_config()
    if not isinstance(config, dict):
        raise RuntimeError("Aegra configuration is missing or invalid")
    _require_exact_registration(config)

    if not settings.event_streaming.FF_V2_EVENT_STREAMING:
        raise RuntimeError("FF_V2_EVENT_STREAMING=true is required")
    if settings.app.ENV_MODE == "PRODUCTION" and settings.app.RUN_MIGRATIONS_ON_STARTUP:
        raise RuntimeError("RUN_MIGRATIONS_ON_STARTUP=false is required in production")
    if settings.redis.REDIS_BROKER_ENABLED:
        raise RuntimeError(
            "REDIS_BROKER_ENABLED=false is required for the in-process run budget"
        )
    if settings.worker.BG_JOB_MAX_RETRIES != 0:
        raise RuntimeError(
            "BG_JOB_MAX_RETRIES=0 is required so retries cannot reset run budgets"
        )
    for configured in {
        settings.db.database_url,
        settings.db.database_url_sync,
    }:
        require_direct_neon_database_url(
            configured,
            purpose="Aegra runtime",
        )

    _require_auth_handler()


__all__ = ["validate_runtime_preflight"]
