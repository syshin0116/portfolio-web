"""The Aegra process must never degrade auth configuration failures to anonymous."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

VALID_SECRET = "test-secret-that-is-at-least-thirty-two-bytes"
VALID_CONFIG = {
    "dependencies": ["./agent/src"],
    "graphs": {"agent": "./agent/src/agent/graph.py:graph"},
    "auth": {
        "path": "agent.auth:auth",
        "disable_studio_auth": False,
    },
    "http": {
        "app": "agent.http:app",
        "enable_custom_route_auth": False,
    },
}


def _import_runtime(
    tmp_path,
    config,
    *,
    discover_from_cwd: bool = False,
    **environment,
):
    config_path = tmp_path / "aegra.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    env = {
        **os.environ,
        "AEGRA_CONFIG": str(config_path),
        "AGENT_AUTH_SECRET": VALID_SECRET,
        "FF_V2_EVENT_STREAMING": "true",
        "ENV_MODE": "PRODUCTION",
        "RUN_MIGRATIONS_ON_STARTUP": "false",
        "REDIS_BROKER_ENABLED": "false",
        "BG_JOB_MAX_RETRIES": "0",
        "QUICKJS_ENABLED": "false",
        "AGENT_ANONYMOUS_ACCESS_ENABLED": "false",
        "GUEST_MODEL": "",
        "GUEST_DAILY_BUDGET_MICRO_USD": "",
        "GUEST_RUN_RESERVATION_MICRO_USD": "",
        "PYTHONDONTWRITEBYTECODE": "1",
        **environment,
    }
    cwd = None
    if discover_from_cwd:
        env.pop("AEGRA_CONFIG", None)
        cwd = tmp_path
    return subprocess.run(
        [sys.executable, "-c", "import aegra_api.main; import agent.graph"],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("discover_from_cwd", [False, True], ids=["env", "cwd"])
def test_valid_runtime_registration_constructs_the_aegra_app(
    tmp_path,
    discover_from_cwd,
):
    result = _import_runtime(
        tmp_path,
        VALID_CONFIG,
        discover_from_cwd=discover_from_cwd,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda config: config.pop("dependencies"), "dependencies"),
        (
            lambda config: config.update({"dependencies": ["./wrong"]}),
            "dependencies",
        ),
        (lambda config: config.pop("graphs"), "graphs"),
        (
            lambda config: config["graphs"].update({"agent": "./wrong.py:graph"}),
            "graphs",
        ),
        (
            lambda config: config["graphs"].update({"unexpected": "./wrong.py:graph"}),
            "graphs",
        ),
        (lambda config: config.pop("auth"), "auth"),
        (
            lambda config: config["auth"].update({"path": "agent.auth:missing"}),
            "auth",
        ),
        (
            lambda config: config["auth"].update({"disable_studio_auth": True}),
            "auth",
        ),
        (lambda config: config.pop("http"), "http"),
        (
            lambda config: config["http"].update({"app": "agent.http:missing"}),
            "http",
        ),
        (
            lambda config: config["http"].update({"enable_custom_route_auth": True}),
            "http",
        ),
    ],
    ids=[
        "missing-dependencies",
        "bad-dependencies",
        "missing-graphs",
        "bad-graph-path",
        "extra-graph",
        "missing-auth",
        "bad-auth-symbol",
        "studio-auth-disabled",
        "missing-http",
        "bad-http-symbol",
        "global-custom-auth",
    ],
)
@pytest.mark.parametrize("discover_from_cwd", [False, True], ids=["env", "cwd"])
def test_missing_or_bad_aegra_registration_refuses_startup(
    tmp_path,
    mutation,
    message,
    discover_from_cwd,
):
    config = json.loads(json.dumps(VALID_CONFIG))
    mutation(config)

    result = _import_runtime(
        tmp_path,
        config,
        discover_from_cwd=discover_from_cwd,
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_local_runtime_may_run_startup_migrations(tmp_path):
    result = _import_runtime(
        tmp_path,
        VALID_CONFIG,
        ENV_MODE="LOCAL",
        RUN_MIGRATIONS_ON_STARTUP="true",
    )

    assert result.returncode == 0, result.stderr


def test_runtime_accepts_exact_quickjs_opt_in(tmp_path):
    result = _import_runtime(
        tmp_path,
        VALID_CONFIG,
        QUICKJS_ENABLED="true",
    )

    assert result.returncode == 0, result.stderr


def test_runtime_accepts_anonymous_access_only_with_an_explicit_guest_model(tmp_path):
    result = _import_runtime(
        tmp_path,
        VALID_CONFIG,
        AGENT_ANONYMOUS_ACCESS_ENABLED="true",
        GUEST_MODEL="anthropic:claude-haiku-4-5",
        GUEST_DAILY_BUDGET_MICRO_USD="500000",
        GUEST_RUN_RESERVATION_MICRO_USD="25000",
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"AGENT_AUTH_SECRET": "too-short"}, "at least 32"),
        ({"FF_V2_EVENT_STREAMING": "false"}, "FF_V2_EVENT_STREAMING"),
        ({"RUN_MIGRATIONS_ON_STARTUP": "true"}, "RUN_MIGRATIONS_ON_STARTUP"),
        ({"REDIS_BROKER_ENABLED": "true"}, "REDIS_BROKER_ENABLED"),
        ({"BG_JOB_MAX_RETRIES": "1"}, "BG_JOB_MAX_RETRIES"),
        ({"QUICKJS_ENABLED": "TRUE"}, "QUICKJS_ENABLED"),
        (
            {"AGENT_ANONYMOUS_ACCESS_ENABLED": "TRUE"},
            "AGENT_ANONYMOUS_ACCESS_ENABLED",
        ),
        (
            {
                "AGENT_ANONYMOUS_ACCESS_ENABLED": "true",
                "GUEST_MODEL": "",
            },
            "GUEST_MODEL",
        ),
        (
            {
                "AGENT_ANONYMOUS_ACCESS_ENABLED": "true",
                "GUEST_MODEL": "openai:gpt-5",
                "GUEST_DAILY_BUDGET_MICRO_USD": "500000",
                "GUEST_RUN_RESERVATION_MICRO_USD": "25000",
            },
            "GUEST_MODEL",
        ),
        (
            {
                "AGENT_ANONYMOUS_ACCESS_ENABLED": "true",
                "GUEST_MODEL": "anthropic:claude-haiku-4-5",
                "GUEST_DAILY_BUDGET_MICRO_USD": "",
                "GUEST_RUN_RESERVATION_MICRO_USD": "",
            },
            "GUEST_DAILY_BUDGET_MICRO_USD",
        ),
        (
            {
                "AGENT_ANONYMOUS_ACCESS_ENABLED": "true",
                "GUEST_MODEL": "anthropic:claude-haiku-4-5",
                "GUEST_DAILY_BUDGET_MICRO_USD": "25000",
                "GUEST_RUN_RESERVATION_MICRO_USD": "25001",
            },
            "cannot exceed",
        ),
        (
            {
                "DATABASE_URL": (
                    "postgresql://user:pass@"
                    "ep-example-pooler.us-east-1.aws.neon.tech/db"
                )
            },
            "direct Neon",
        ),
        (
            {
                "DATABASE_URL": (
                    "postgresql:///db?host=ep-example-pooler.us-east-1.aws.neon.tech"
                )
            },
            "direct Neon",
        ),
        (
            {
                "DATABASE_URL": "",
                "POSTGRES_HOST": ("ep-example-pooler.us-east-1.aws.neon.tech"),
            },
            "direct Neon",
        ),
    ],
    ids=[
        "short-secret",
        "v2-disabled",
        "startup-migrations",
        "redis-budget-bypass",
        "retry-budget-reset",
        "invalid-quickjs-opt-in",
        "invalid-anonymous-opt-in",
        "missing-guest-model",
        "unsupported-guest-model",
        "missing-guest-budget",
        "incoherent-guest-budget",
        "neon-pooler",
        "neon-pooler-query-host",
        "neon-pooler-component-host",
    ],
)
def test_unsafe_required_runtime_environment_refuses_startup(
    tmp_path,
    environment,
    message,
):
    result = _import_runtime(tmp_path, VALID_CONFIG, **environment)

    assert result.returncode != 0
    assert message in result.stderr
