#!/usr/bin/env python3
"""Verify the repository-owned GCP surface with exact-project read calls only.

This verifier intentionally makes no claim about inherited organization/folder IAM or
the project's parent.  It does not follow or query those scopes, ignores any parent
field returned by the exact project describe, and never mutates Google Cloud.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

try:
    from scripts.ops_foundation_live_toolchain import (
        ToolchainError,
        trusted_home,
        validate_trusted_executable,
    )
    from scripts.ops_foundation_contract import ContractError, validate_live_wif
except ModuleNotFoundError:  # Direct `python scripts/...` execution.
    from ops_foundation_live_toolchain import (  # type: ignore[no-redef]
        ToolchainError,
        trusted_home,
        validate_trusted_executable,
    )
    from ops_foundation_contract import ContractError, validate_live_wif

PROJECT_ID = "festive-ally-503605-v7"
PROJECT_NUMBER = "72919926064"
REGION = "asia-southeast1"
LEGACY_REGION = "us-east4"
STATE_BUCKET = f"{PROJECT_ID}-tfstate"
STATE_OBJECT = "syshin0116.dev/gcp/foundation/default.tfstate"
GCLOUD_ACCOUNT_ENV = "OPS_FOUNDATION_GCLOUD_ACCOUNT"
EXPECTED_GCLOUD_ACCOUNT_SHA256 = (
    "8d855626e841898add1ba4e401a4c7789a97b0f30d1ca837a3c6af90b1d48695"
)
MAX_GCLOUD_OUTPUT_BYTES = 16 * 1024 * 1024
READINESS_CONTRACT_PATH = Path(__file__).with_name(
    "gcp_project_readiness_contract.json"
)
READINESS_CONTRACT_SHA256 = (
    "e4ad8de73b80e70f290626dbadcb9ae02189060510f4167c58391ce71cdbb520"
)

PRODUCTION_RUNTIME_SA = f"agent-runtime@{PROJECT_ID}.iam.gserviceaccount.com"
PREVIEW_RUNTIME_SA = f"agent-preview-runtime@{PROJECT_ID}.iam.gserviceaccount.com"
PREVIEW_DEPLOYER_SA = f"agent-preview-deployer@{PROJECT_ID}.iam.gserviceaccount.com"
PRODUCTION_DEPLOYER_SA = f"agent-prod-deployer@{PROJECT_ID}.iam.gserviceaccount.com"
BUILDER_SA = f"agent-image-builder@{PROJECT_ID}.iam.gserviceaccount.com"
PREVIEW_BUILDER_SA = f"agent-preview-image-builder@{PROJECT_ID}.iam.gserviceaccount.com"
PREVIEW_MIGRATOR_SA = f"agent-preview-migrator@{PROJECT_ID}.iam.gserviceaccount.com"
PRODUCTION_MIGRATOR_SA = f"agent-prod-migrator@{PROJECT_ID}.iam.gserviceaccount.com"
MAINTENANCE_SCHEDULER_SA = (
    f"agent-maintenance-scheduler@{PROJECT_ID}.iam.gserviceaccount.com"
)
CLOUD_RUN_SERVICE_AGENT = (
    f"service-{PROJECT_NUMBER}@serverless-robot-prod.iam.gserviceaccount.com"
)
CLOUD_SCHEDULER_SERVICE_AGENT = (
    f"service-{PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
)
CLOUD_RUN_DELIVERY_ROLE = f"projects/{PROJECT_ID}/roles/cloudRunAgentDelivery"

WORKLOAD_SERVICE_ACCOUNTS = frozenset(
    {
        PRODUCTION_RUNTIME_SA,
        PREVIEW_RUNTIME_SA,
        PREVIEW_DEPLOYER_SA,
        PRODUCTION_DEPLOYER_SA,
        BUILDER_SA,
        PREVIEW_BUILDER_SA,
        PREVIEW_MIGRATOR_SA,
        PRODUCTION_MIGRATOR_SA,
        MAINTENANCE_SCHEDULER_SA,
    }
)
REQUIRED_APIS = frozenset(
    {
        "artifactregistry.googleapis.com",
        "cloudscheduler.googleapis.com",
        "cloudresourcemanager.googleapis.com",
        "iam.googleapis.com",
        "iamcredentials.googleapis.com",
        "run.googleapis.com",
        "secretmanager.googleapis.com",
        "storage.googleapis.com",
        "sts.googleapis.com",
    }
)

PRODUCTION_SECRET_POLICIES = {
    "agent-auth-secret": PRODUCTION_RUNTIME_SA,
    "agent-database-url": PRODUCTION_RUNTIME_SA,
    "anthropic-api-key": PRODUCTION_RUNTIME_SA,
    "langsmith-api-key": PRODUCTION_RUNTIME_SA,
    "openai-api-key": PRODUCTION_RUNTIME_SA,
    "agent-migration-database-url": PRODUCTION_MIGRATOR_SA,
}
PREVIEW_SECRET_POLICIES = {
    "agent-preview-anthropic-api-key": PREVIEW_RUNTIME_SA,
    "agent-preview-auth-secret": PREVIEW_RUNTIME_SA,
    "agent-preview-database-url": PREVIEW_RUNTIME_SA,
    "agent-preview-langsmith-api-key": PREVIEW_RUNTIME_SA,
    "agent-preview-migration-database-url": PREVIEW_MIGRATOR_SA,
}
SECRET_POLICIES = PRODUCTION_SECRET_POLICIES | PREVIEW_SECRET_POLICIES

COMMON_RUNTIME_ENV = {
    "AEGRA_CONFIG": "/app/aegra.json",
    "BG_JOB_MAX_RETRIES": "0",
    "ENV_MODE": "PRODUCTION",
    "FF_V2_EVENT_STREAMING": "true",
    "HOST": "0.0.0.0",
    "LANGGRAPH_MAX_POOL_SIZE": "4",
    "LANGGRAPH_MIN_POOL_SIZE": "1",
    "MODEL": "openai:gpt-5.6-luna",
    "PORT": "8080",
    "REDIS_BROKER_ENABLED": "false",
    "RUN_MIGRATIONS_ON_STARTUP": "false",
    "SQLALCHEMY_MAX_OVERFLOW": "0",
    "SQLALCHEMY_POOL_SIZE": "2",
}
PREVIEW_RUNTIME_ENV = COMMON_RUNTIME_ENV | {
    "AGENT_ANONYMOUS_ACCESS_ENABLED": "false",
    "GUEST_DAILY_BUDGET_MICRO_USD": "",
    "GUEST_MODEL": "",
    "GUEST_RUN_RESERVATION_MICRO_USD": "",
}
PRODUCTION_RUNTIME_ENV = COMMON_RUNTIME_ENV | {
    "AGENT_ANONYMOUS_ACCESS_ENABLED": "true",
    "GUEST_DAILY_BUDGET_MICRO_USD": "500000",
    "GUEST_MODEL": "openai:gpt-5.6-luna",
    "GUEST_RUN_RESERVATION_MICRO_USD": "18892",
}
PREVIEW_RUNTIME_SECRETS = {
    "AGENT_AUTH_SECRET": "agent-preview-auth-secret",
    "ANTHROPIC_API_KEY": "agent-preview-anthropic-api-key",
    "DATABASE_URL": "agent-preview-database-url",
    "LANGCHAIN_API_KEY": "agent-preview-langsmith-api-key",
}
PRODUCTION_RUNTIME_SECRETS = {
    "AGENT_AUTH_SECRET": "agent-auth-secret",
    "DATABASE_URL": "agent-database-url",
    "OPENAI_API_KEY": "openai-api-key",
}

SERVICE_SPECS = {
    "agent": {
        "runtime": PRODUCTION_RUNTIME_SA,
        "deployer": PRODUCTION_DEPLOYER_SA,
        "repository": "agent",
        "plain_env": PRODUCTION_RUNTIME_ENV,
        "secrets": PRODUCTION_RUNTIME_SECRETS,
    },
}
JOB_SPECS = {
    "agent-migrate": {
        "service_account": PRODUCTION_MIGRATOR_SA,
        "deployer": PRODUCTION_DEPLOYER_SA,
        "repository": "agent",
        "container": "migration",
        "module": "agent.migrate",
        "secret": "agent-migration-database-url",
        "timeout": 900,
        "scheduler": None,
    },
    "agent-grants": {
        "service_account": PRODUCTION_RUNTIME_SA,
        "deployer": PRODUCTION_DEPLOYER_SA,
        "repository": "agent",
        "container": "grant-probe",
        "module": "agent.neon_grant_probe",
        "secret": "agent-database-url",
        "timeout": 600,
        "scheduler": None,
    },
    "agent-maintenance": {
        "service_account": PRODUCTION_RUNTIME_SA,
        "deployer": PRODUCTION_DEPLOYER_SA,
        "repository": "agent",
        "container": "maintenance",
        "module": "agent.maintenance",
        "secret": "agent-database-url",
        "timeout": 600,
        "scheduler": MAINTENANCE_SCHEDULER_SA,
    },
}


class ReadinessError(RuntimeError):
    """The exact-project live state is unsafe, incomplete, or unreadable."""


def _fail(message: str) -> None:
    raise ReadinessError(message)


BUCKET_DISCOVERY_COMMAND = (
    "storage",
    "buckets",
    "list",
    f"--filter=name={STATE_BUCKET}",
    "--format=json(name,projectNumber)",
)
STATE_BUCKET_COMMANDS = frozenset(
    {
        (
            "storage",
            "buckets",
            "describe",
            f"gs://{STATE_BUCKET}",
            "--format=json",
        ),
        (
            "storage",
            "buckets",
            "get-iam-policy",
            f"gs://{STATE_BUCKET}",
            "--format=json",
        ),
        (
            "storage",
            "objects",
            "describe",
            f"gs://{STATE_BUCKET}/{STATE_OBJECT}",
            "--format=json",
        ),
    }
)


def _fixed_commands() -> frozenset[tuple[str, ...]]:
    commands: set[tuple[str, ...]] = {
        ("projects", "describe", PROJECT_ID, "--format=json"),
        ("projects", "get-iam-policy", PROJECT_ID, "--format=json"),
        ("services", "list", "--enabled", "--format=value(config.name)"),
        (
            "iam",
            "roles",
            "describe",
            "cloudRunAgentDelivery",
            "--format=json",
        ),
        ("iam", "service-accounts", "list", "--format=json"),
        BUCKET_DISCOVERY_COMMAND,
        *STATE_BUCKET_COMMANDS,
        (
            "iam",
            "workload-identity-pools",
            "describe",
            "github",
            "--location",
            "global",
            "--format=json",
        ),
        (
            "iam",
            "workload-identity-pools",
            "providers",
            "list",
            "--location",
            "global",
            "--workload-identity-pool",
            "github",
            "--format=json",
        ),
        (
            "scheduler",
            "jobs",
            "describe",
            "agent-guest-maintenance",
            "--location",
            REGION,
            "--format=json",
        ),
    }
    for repository in ("agent", "agent-preview"):
        for location in (REGION, LEGACY_REGION):
            for operation in ("describe", "get-iam-policy"):
                commands.add(
                    (
                        "artifacts",
                        "repositories",
                        operation,
                        repository,
                        "--location",
                        location,
                        "--format=json",
                    )
                )
    for service in SERVICE_SPECS:
        for operation in ("describe", "get-iam-policy"):
            commands.add(
                (
                    "run",
                    "services",
                    operation,
                    service,
                    "--region",
                    REGION,
                    "--format=json",
                )
            )
    for job in JOB_SPECS:
        for operation in ("describe", "get-iam-policy"):
            commands.add(
                (
                    "run",
                    "jobs",
                    operation,
                    job,
                    "--region",
                    REGION,
                    "--format=json",
                )
            )
    for service_account in WORKLOAD_SERVICE_ACCOUNTS:
        commands.add(
            (
                "iam",
                "service-accounts",
                "get-iam-policy",
                service_account,
                "--format=json",
            )
        )
    for secret in SECRET_POLICIES:
        commands.add(("secrets", "describe", secret, "--format=json"))
        commands.add(("secrets", "get-iam-policy", secret, "--format=json"))
    for provider in ("github-preview", "github-production"):
        commands.add(
            (
                "iam",
                "workload-identity-pools",
                "providers",
                "describe",
                provider,
                "--location",
                "global",
                "--workload-identity-pool",
                "github",
                "--format=json",
            )
        )
    return frozenset(commands)


FIXED_GCLOUD_COMMANDS = _fixed_commands()


def is_allowed_gcloud_command(
    command: tuple[str, ...],
    *,
    validated_service_accounts: frozenset[str],
    trusted_state_bucket: bool = False,
) -> bool:
    """Return whether a command is one exact, read-only request in this project."""
    if command in STATE_BUCKET_COMMANDS:
        return trusted_state_bucket
    if command in FIXED_GCLOUD_COMMANDS:
        return True
    if len(command) != 8:
        return False
    return (
        command[:5]
        == (
            "iam",
            "service-accounts",
            "keys",
            "list",
            "--iam-account",
        )
        and command[5] in validated_service_accounts
        and command[6:] == ("--managed-by=user", "--format=value(name)")
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            _fail(f"gcloud JSON contains duplicate key: {key!r}")
        document[key] = value
    return document


def _load_json(raw: str, label: str) -> Any:
    if not raw or len(raw.encode("utf-8")) > MAX_GCLOUD_OUTPUT_BYTES:
        _fail(f"{label} returned empty or oversized output")
    try:
        return json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ReadinessError(f"{label} did not return valid JSON") from exc


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{label} must be a JSON array")
    return value


def _contract_string_list(contract: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = _array(contract.get(key), f"readiness contract {key}")
    if any(not isinstance(value, str) or not value for value in values):
        _fail(f"readiness contract {key} must contain non-empty strings")
    result = tuple(values)
    if len(result) != len(set(result)):
        _fail(f"readiness contract {key} contains duplicates")
    return result


def _approved_fixed_commands(contract: Mapping[str, Any]) -> frozenset[tuple[str, ...]]:
    commands: set[tuple[str, ...]] = set()
    singleton_commands = _array(
        contract.get("fixedSingletonCommands"),
        "readiness contract fixed singleton commands",
    )
    for raw_command in singleton_commands:
        tokens = _array(raw_command, "readiness contract command")
        if any(not isinstance(token, str) or not token for token in tokens):
            _fail("readiness contract commands must contain non-empty strings")
        command = tuple(tokens)
        if command in commands:
            _fail("readiness contract contains duplicate commands")
        commands.add(command)

    region = contract.get("region")
    for repository in _contract_string_list(contract, "repositories"):
        for operation in _contract_string_list(contract, "repositoryOperations"):
            commands.add(
                (
                    "artifacts",
                    "repositories",
                    operation,
                    repository,
                    "--location",
                    str(region),
                    "--format=json",
                )
            )
    legacy_region = contract.get("legacyRegion")
    for repository in _contract_string_list(contract, "legacyRepositories"):
        for operation in _contract_string_list(contract, "repositoryOperations"):
            commands.add(
                (
                    "artifacts",
                    "repositories",
                    operation,
                    repository,
                    "--location",
                    str(legacy_region),
                    "--format=json",
                )
            )
    for service in _contract_string_list(contract, "services"):
        for operation in _contract_string_list(contract, "serviceOperations"):
            commands.add(
                (
                    "run",
                    "services",
                    operation,
                    service,
                    "--region",
                    str(region),
                    "--format=json",
                )
            )
    for job in _contract_string_list(contract, "jobs"):
        for operation in _contract_string_list(contract, "jobOperations"):
            commands.add(
                (
                    "run",
                    "jobs",
                    operation,
                    job,
                    "--region",
                    str(region),
                    "--format=json",
                )
            )
    for account in _contract_string_list(contract, "workloadServiceAccounts"):
        commands.add(
            (
                "iam",
                "service-accounts",
                "get-iam-policy",
                account,
                "--format=json",
            )
        )
    for secret in _contract_string_list(contract, "secrets"):
        for operation in _contract_string_list(contract, "secretOperations"):
            commands.add(("secrets", operation, secret, "--format=json"))
    for provider in _contract_string_list(contract, "wifProviders"):
        commands.add(
            (
                "iam",
                "workload-identity-pools",
                "providers",
                "describe",
                provider,
                "--location",
                "global",
                "--workload-identity-pool",
                "github",
                "--format=json",
            )
        )
    return frozenset(commands)


def validate_readiness_source_contract() -> None:
    """Match source constants and every command shape to the pinned literal oracle."""
    path = READINESS_CONTRACT_PATH
    if path.is_symlink():
        _fail("readiness contract manifest must not be a symlink")
    try:
        raw = path.read_bytes()
        metadata = path.stat()
    except OSError as exc:
        raise ReadinessError("cannot read readiness contract manifest") from exc
    if not path.is_file() or metadata.st_size != len(raw):
        _fail("readiness contract manifest must be a regular file")
    if hashlib.sha256(raw).hexdigest() != READINESS_CONTRACT_SHA256:
        _fail("readiness contract manifest digest drifted")
    try:
        contract = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ReadinessError("readiness contract manifest is invalid JSON") from exc
    document = _object(contract, "readiness contract manifest")
    expected_keys = {
        "schemaVersion",
        "projectId",
        "projectNumber",
        "region",
        "legacyRegion",
        "stateBucket",
        "stateObject",
        "requiredApis",
        "workloadServiceAccounts",
        "repositories",
        "legacyRepositories",
        "services",
        "jobs",
        "secrets",
        "wifProviders",
        "repositoryOperations",
        "serviceOperations",
        "jobOperations",
        "secretOperations",
        "fixedSingletonCommands",
        "dynamicServiceAccountKeyCommand",
        "anonymousRuntimeContract",
    }
    if set(document) != expected_keys or document.get("schemaVersion") != 1:
        _fail("readiness contract manifest schema drifted")
    scalar_contract = {
        "projectId": PROJECT_ID,
        "projectNumber": PROJECT_NUMBER,
        "region": REGION,
        "legacyRegion": LEGACY_REGION,
        "stateBucket": STATE_BUCKET,
        "stateObject": STATE_OBJECT,
    }
    if any(document.get(key) != value for key, value in scalar_contract.items()):
        _fail("readiness source project, number, region, or state target drifted")
    inventory_contract = {
        "requiredApis": REQUIRED_APIS,
        "workloadServiceAccounts": WORKLOAD_SERVICE_ACCOUNTS,
        "repositories": frozenset({"agent", "agent-preview"}),
        "legacyRepositories": frozenset({"agent", "agent-preview"}),
        "services": frozenset(SERVICE_SPECS),
        "jobs": frozenset(JOB_SPECS),
        "secrets": frozenset(SECRET_POLICIES),
        "wifProviders": frozenset({"github-preview", "github-production"}),
    }
    if any(
        frozenset(_contract_string_list(document, key)) != expected
        for key, expected in inventory_contract.items()
    ):
        _fail("readiness source resource inventory drifted")
    anonymous_runtime = _object(
        document.get("anonymousRuntimeContract"),
        "anonymous runtime contract",
    )
    expected_anonymous_runtime = {
        "preview": {
            key: PREVIEW_RUNTIME_ENV[key]
            for key in (
                "AGENT_ANONYMOUS_ACCESS_ENABLED",
                "GUEST_DAILY_BUDGET_MICRO_USD",
                "GUEST_MODEL",
                "GUEST_RUN_RESERVATION_MICRO_USD",
            )
        },
        "production": {
            key: PRODUCTION_RUNTIME_ENV[key]
            for key in (
                "AGENT_ANONYMOUS_ACCESS_ENABLED",
                "GUEST_DAILY_BUDGET_MICRO_USD",
                "GUEST_MODEL",
                "GUEST_RUN_RESERVATION_MICRO_USD",
            )
        },
    }
    if anonymous_runtime != expected_anonymous_runtime:
        _fail("readiness source anonymous runtime contract drifted")
    operation_contract = {
        "repositoryOperations": ("describe", "get-iam-policy"),
        "serviceOperations": ("describe", "get-iam-policy"),
        "jobOperations": ("describe", "get-iam-policy"),
        "secretOperations": ("describe", "get-iam-policy"),
    }
    if any(
        _contract_string_list(document, key) != expected
        for key, expected in operation_contract.items()
    ):
        _fail("readiness source operation catalogue drifted")
    key_command = _object(
        document.get("dynamicServiceAccountKeyCommand"),
        "dynamic service-account key command",
    )
    if key_command != {
        "prefix": [
            "iam",
            "service-accounts",
            "keys",
            "list",
            "--iam-account",
        ],
        "suffix": ["--managed-by=user", "--format=value(name)"],
        "accountSource": "validatedExactProjectInventory",
    }:
        _fail("dynamic service-account key command shape drifted")
    if _approved_fixed_commands(document) != FIXED_GCLOUD_COMMANDS:
        _fail("fixed gcloud command catalogue drifted from the literal oracle")


class GCloudReader:
    """Execute only the repository-owned exact-project read catalogue."""

    def __init__(self, gcloud_binary: Path) -> None:
        validate_readiness_source_contract()
        overrides = sorted(
            name for name in os.environ if name.startswith(("CLOUDSDK_", "GOOGLE_"))
        )
        if overrides:
            _fail("caller Google/gcloud environment overrides are forbidden")
        account = os.environ.get(GCLOUD_ACCOUNT_ENV, "")
        digest = hashlib.sha256(account.encode()).hexdigest()
        if not account or digest != EXPECTED_GCLOUD_ACCOUNT_SHA256:
            _fail("gcloud account does not match the repository-pinned identity")
        try:
            binary = validate_trusted_executable(gcloud_binary, "gcloud")
            python = validate_trusted_executable(sys.executable, "live Python")
            home = trusted_home()
        except ToolchainError as exc:
            raise ReadinessError(str(exc)) from exc

        self._account = account
        self._binary = binary
        self._environment = {
            "CLOUDSDK_CORE_DISABLE_PROMPTS": "1",
            "CLOUDSDK_ENCODING": "UTF-8",
            "CLOUDSDK_PYTHON": str(python),
            "CLOUDSDK_PYTHON_ARGS": "-I -S",
            "HOME": str(home),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        }
        self._validated_service_accounts: frozenset[str] = frozenset()
        self._state_bucket_trusted = False

    def trust_service_account_inventory(self, accounts: Iterable[str]) -> None:
        self._validated_service_accounts = frozenset(accounts)

    def trust_state_bucket(self) -> None:
        self._state_bucket_trusted = True

    def __call__(self, command: tuple[str, ...]) -> str:
        if not is_allowed_gcloud_command(
            command,
            validated_service_accounts=self._validated_service_accounts,
            trusted_state_bucket=self._state_bucket_trusted,
        ):
            _fail("gcloud command tuple or target is not allowlisted")
        argv = (
            str(self._binary),
            "--configuration=NONE",
            f"--account={self._account}",
            f"--project={PROJECT_ID}",
            "--quiet",
            *command,
        )
        try:
            result = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                env=self._environment,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
            raise ReadinessError(
                "exact-project gcloud read could not complete"
            ) from exc
        if result.returncode != 0:
            _fail("exact-project gcloud read failed")
        if len(result.stdout.encode("utf-8")) > MAX_GCLOUD_OUTPUT_BYTES:
            _fail("exact-project gcloud read exceeded the output limit")
        return result.stdout


Read = Callable[[tuple[str, ...]], str]


def _read_json(read: Read, command: tuple[str, ...], label: str) -> Any:
    return _load_json(read(command), label)


def _positive_integer(value: Any) -> bool:
    return (
        isinstance(value, (int, str))
        and re.fullmatch(r"[1-9][0-9]*", str(value)) is not None
    )


def _integer_equals(value: Any, expected: int) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return False
    return (
        re.fullmatch(r"0|[1-9][0-9]*", str(value)) is not None
        and int(value) == expected
    )


def _policy_pairs(
    policy: Mapping[str, Any], *, require_unconditional: bool
) -> frozenset[tuple[str, str]]:
    bindings = _array(policy.get("bindings", []), "IAM policy bindings")
    pairs: set[tuple[str, str]] = set()
    for raw_binding in bindings:
        binding = _object(raw_binding, "IAM binding")
        role = binding.get("role")
        members = binding.get("members")
        if not isinstance(role, str) or not role:
            _fail("IAM binding role must be a non-empty string")
        values = _array(members, f"{role} members")
        if not values or not all(
            isinstance(member, str) and member for member in values
        ):
            _fail(f"{role} members must be non-empty strings")
        if require_unconditional and "condition" in binding:
            _fail("managed resource IAM must not contain conditional bindings")
        for member in values:
            pair = (role, member)
            if pair in pairs:
                _fail("IAM policy contains duplicate role/member pairs")
            pairs.add(pair)
    return frozenset(pairs)


def _require_exact_policy(
    policy: Mapping[str, Any], expected: Iterable[tuple[str, str]], label: str
) -> None:
    actual = _policy_pairs(policy, require_unconditional=True)
    if actual != frozenset(expected):
        _fail(f"{label} IAM does not match the exact repository-owned bindings")


def _require_no_public(policy: Mapping[str, Any], label: str) -> None:
    pairs = _policy_pairs(policy, require_unconditional=False)
    if any(member in {"allUsers", "allAuthenticatedUsers"} for _, member in pairs):
        _fail(f"{label} IAM exposes a public principal")


def _validate_project(document: Any) -> None:
    project = _object(document, "project")
    if (
        project.get("projectId") != PROJECT_ID
        or str(project.get("projectNumber")) != PROJECT_NUMBER
        or project.get("lifecycleState") != "ACTIVE"
    ):
        _fail("live project identity or lifecycle does not match the exact target")


def _validate_project_policy(document: Any) -> None:
    policy = _object(document, "project IAM policy")
    bindings = _array(policy.get("bindings", []), "project IAM bindings")
    pairs = _policy_pairs(policy, require_unconditional=False)
    public = {"allUsers", "allAuthenticatedUsers"}
    if any(member in public for _, member in pairs):
        _fail("project IAM must not contain public principals")
    if any(
        re.fullmatch(
            r"principalSet://cloudresourcemanager[.]googleapis[.]com/"
            r"(?:projects|folders|organizations)/[^/]+/type/ServiceAccount",
            member,
        )
        for _, member in pairs
    ):
        _fail("project IAM contains a broad service-account principal set")
    workload_members = {
        f"serviceAccount:{email}" for email in WORKLOAD_SERVICE_ACCOUNTS
    }
    if any(member in workload_members for _, member in pairs):
        _fail("a managed workload identity has a direct project-level role")
    forbidden_roles = {
        "roles/iam.serviceAccountUser",
        "roles/iam.serviceAccountTokenCreator",
        "roles/secretmanager.secretAccessor",
        "roles/secretmanager.admin",
    }
    if any(role in forbidden_roles for role, _ in pairs):
        _fail("project IAM contains a project-wide boundary-bypass role")
    scheduler_members = {
        member for role, member in pairs if role == "roles/cloudscheduler.serviceAgent"
    }
    scheduler_bindings = [
        _object(binding, "Cloud Scheduler service-agent binding")
        for binding in bindings
        if _object(binding, "project IAM binding").get("role")
        == "roles/cloudscheduler.serviceAgent"
    ]
    if len(scheduler_bindings) != 1 or "condition" in scheduler_bindings[0]:
        _fail("Cloud Scheduler service-agent binding must be unconditional")
    if scheduler_members != {f"serviceAccount:{CLOUD_SCHEDULER_SERVICE_AGENT}"}:
        _fail("Cloud Scheduler service-agent binding is not exact")


def _validate_delivery_role(document: Any) -> None:
    role = _object(document, "Cloud Run delivery role")
    expected_permissions = {
        "run.jobs.get",
        "run.jobs.run",
        "run.jobs.update",
        "run.operations.get",
        "run.revisions.get",
        "run.services.get",
        "run.services.update",
    }
    permissions = role.get("includedPermissions")
    if (
        role.get("name") != CLOUD_RUN_DELIVERY_ROLE
        or role.get("deleted", False) is not False
        or role.get("stage") != "GA"
        or not isinstance(permissions, list)
        or not all(isinstance(permission, str) for permission in permissions)
        or set(permissions) != expected_permissions
        or len(permissions) != len(expected_permissions)
    ):
        _fail("Cloud Run delivery role is not the exact seven-permission role")


def _validate_enabled_apis(raw: str) -> None:
    enabled = {line.strip() for line in raw.splitlines() if line.strip()}
    missing = sorted(REQUIRED_APIS - enabled)
    if missing:
        _fail(f"required Google APIs are not enabled: {missing}")


def _validate_artifact_repository(
    document: Any,
    repository: str,
    *,
    region: str,
) -> None:
    repo = _object(document, f"Artifact Registry {repository}")
    expected = {
        "agent": ("delete-after-90-days", "7776000s", "keep-last-30", 30),
        "agent-preview": ("delete-after-14-days", "1209600s", "keep-last-20", 20),
    }[repository]
    delete_id, delete_after, keep_id, keep_count = expected
    if (
        repo.get("name")
        != f"projects/{PROJECT_ID}/locations/{region}/repositories/{repository}"
        or repo.get("format") != "DOCKER"
        or repo.get("mode") != "STANDARD_REPOSITORY"
    ):
        _fail(f"Artifact Registry {repository} identity, format, or mode drifted")
    if repo.get("kmsKeyName") not in (None, ""):
        _fail(f"Artifact Registry {repository} must use Google-managed encryption")
    policies = repo.get("cleanupPolicies")
    if not isinstance(policies, dict) or set(policies) != {delete_id, keep_id}:
        _fail(f"Artifact Registry {repository} cleanup inventory drifted")
    delete = _object(policies[delete_id], f"{repository} delete policy")
    keep = _object(policies[keep_id], f"{repository} keep policy")
    condition = _object(delete.get("condition"), f"{repository} delete condition")
    recent = _object(keep.get("mostRecentVersions"), f"{repository} keep count")
    if (
        set(delete) != {"id", "action", "condition"}
        or set(keep)
        != {
            "id",
            "action",
            "mostRecentVersions",
        }
        or delete.get("id") != delete_id
        or keep.get("id") != keep_id
    ):
        _fail(f"Artifact Registry {repository} cleanup policy fields or IDs drifted")
    condition_fields = {
        "newerThan",
        "olderThan",
        "packageNamePrefixes",
        "tagPrefixes",
        "tagState",
        "versionNamePrefixes",
    }
    if not set(condition) <= condition_fields or not set(recent) <= {
        "keepCount",
        "packageNamePrefixes",
    }:
        _fail(f"Artifact Registry {repository} cleanup selector fields drifted")
    empty_selectors = (None, "", [])
    if (
        any(
            condition.get(field) not in empty_selectors
            for field in (
                "newerThan",
                "packageNamePrefixes",
                "tagPrefixes",
                "versionNamePrefixes",
            )
        )
        or recent.get("packageNamePrefixes") not in empty_selectors
    ):
        _fail(f"Artifact Registry {repository} cleanup selector narrowed")
    if (
        _object(repo.get("dockerConfig", {}), "docker config").get(
            "immutableTags", False
        )
        is not False
        or repo.get("cleanupPolicyDryRun", False) is not False
        or delete.get("action") != "DELETE"
        or condition.get("tagState") != "ANY"
        or condition.get("olderThan") != delete_after
        or "newerThan" in condition
        or keep.get("action") != "KEEP"
        or not _integer_equals(recent.get("keepCount"), keep_count)
    ):
        _fail(f"Artifact Registry {repository} metadata or retention drifted")


def _validate_bucket(document: Any) -> None:
    bucket = _object(document, "Terraform state bucket")
    owner = bucket.get("projectNumber", bucket.get("project_number"))
    location = bucket.get("location")
    iam = _object(bucket.get("iamConfiguration", {}), "bucket IAM configuration")
    uniform = bucket.get(
        "uniform_bucket_level_access",
        _object(iam.get("uniformBucketLevelAccess", {}), "uniform bucket access").get(
            "enabled"
        ),
    )
    public_prevention = bucket.get(
        "public_access_prevention", iam.get("publicAccessPrevention")
    )
    versioning = _object(bucket.get("versioning", {}), "bucket versioning").get(
        "enabled", bucket.get("versioning_enabled")
    )
    soft_delete = _object(
        bucket.get("softDeletePolicy", bucket.get("soft_delete_policy", {})),
        "bucket soft-delete policy",
    )
    retention = soft_delete.get(
        "retentionDurationSeconds", soft_delete.get("retention_duration_seconds", 0)
    )
    encryption = _object(bucket.get("encryption", {}), "bucket encryption")
    if encryption.get("defaultKmsKeyName") not in (None, ""):
        _fail("Terraform state bucket must use Google-managed encryption")
    if (
        bucket.get("name") != STATE_BUCKET
        or str(owner) != PROJECT_NUMBER
        or not isinstance(location, str)
        or location.upper() != LEGACY_REGION.upper()
        or public_prevention != "enforced"
        or uniform is not True
        or versioning is not True
        or not _positive_integer(retention)
        or int(retention) < 2_592_000
    ):
        _fail("Terraform state bucket owner or protection metadata drifted")


def _validate_bucket_discovery(document: Any) -> None:
    buckets = _array(document, "exact-project bucket discovery")
    if len(buckets) != 1:
        _fail("exact-project bucket discovery must return the one state bucket")
    bucket = _object(buckets[0], "discovered state bucket")
    if (
        bucket.get("name") != STATE_BUCKET
        or str(bucket.get("projectNumber")) != PROJECT_NUMBER
    ):
        _fail("state bucket was not discovered under the exact project")


def _validate_state_object(document: Any) -> None:
    state = _object(document, "Terraform state object")
    bucket = state.get("bucket")
    if state.get("kmsKeyName") not in (None, ""):
        _fail("Terraform state object must use Google-managed encryption")
    if (
        state.get("name") != STATE_OBJECT
        or (bucket is not None and bucket != STATE_BUCKET)
        or not _positive_integer(state.get("generation"))
        or not _positive_integer(state.get("size"))
    ):
        _fail("Terraform state object identity, generation, or size is invalid")


def _valid_exact_project_service_account(email: str) -> bool:
    user_managed = re.fullmatch(
        rf"[a-z][a-z0-9-]{{2,28}}[a-z0-9]@{re.escape(PROJECT_ID)}"
        r"[.]iam[.]gserviceaccount[.]com",
        email,
    )
    google_managed = email in {
        f"{PROJECT_ID}@appspot.gserviceaccount.com",
        f"{PROJECT_NUMBER}-compute@developer.gserviceaccount.com",
        f"{PROJECT_NUMBER}@cloudbuild.gserviceaccount.com",
        f"{PROJECT_NUMBER}@cloudservices.gserviceaccount.com",
    } or re.fullmatch(
        rf"service-{PROJECT_NUMBER}@[a-z0-9-]+[.]iam[.]gserviceaccount[.]com",
        email,
    )
    return user_managed is not None or bool(google_managed)


def _validate_service_account_inventory(document: Any) -> frozenset[str]:
    accounts = _array(document, "service-account inventory")
    emails: set[str] = set()
    for raw in accounts:
        account = _object(raw, "service-account record")
        email = account.get("email")
        if (
            not isinstance(email, str)
            or not _valid_exact_project_service_account(email)
            or account.get("name") != f"projects/{PROJECT_ID}/serviceAccounts/{email}"
            or email in emails
        ):
            _fail("service-account inventory escaped the exact project boundary")
        if (
            email in WORKLOAD_SERVICE_ACCOUNTS
            and account.get("disabled", False) is not False
        ):
            _fail("a managed workload service account is disabled")
        emails.add(email)
    if not emails or not WORKLOAD_SERVICE_ACCOUNTS <= emails:
        _fail("managed workload service-account inventory is incomplete")
    return frozenset(emails)


def _validate_secret_metadata(document: Any, secret: str) -> None:
    metadata = _object(document, f"Secret Manager {secret}")
    valid_names = {
        f"projects/{PROJECT_ID}/secrets/{secret}",
        f"projects/{PROJECT_NUMBER}/secrets/{secret}",
    }
    replication = _object(metadata.get("replication", {}), "secret replication")
    automatic_keys = set(replication) & {"automatic", "auto"}
    if (
        metadata.get("name") not in valid_names
        or len(automatic_keys) != 1
        or set(replication) != automatic_keys
    ):
        _fail(f"Secret Manager {secret} identity or replication drifted")
    automatic = _object(
        replication[next(iter(automatic_keys))], "automatic secret replication"
    )
    if (
        automatic
        or metadata.get("expireTime") not in (None, "")
        or metadata.get("expire_time") not in (None, "")
        or metadata.get("ttl") not in (None, "")
    ):
        _fail(f"Secret Manager {secret} encryption or expiration drifted")


def _normalize_secret_ref(entry: Mapping[str, Any]) -> tuple[str, str] | None:
    source = entry.get("valueFrom", entry.get("valueSource"))
    if source is None:
        return None
    source_object = _object(source, "environment value source")
    secret_ref = _object(source_object.get("secretKeyRef"), "secret reference")
    secret = secret_ref.get("name", secret_ref.get("secret"))
    version = secret_ref.get("key", secret_ref.get("version"))
    if not isinstance(secret, str) or not isinstance(version, str):
        _fail("secret environment reference is malformed")
    return secret, version


def _validate_environment(
    entries: Any,
    expected_plain: Mapping[str, str],
    expected_secrets: Mapping[str, str],
) -> None:
    plain: dict[str, str] = {}
    secrets: dict[str, tuple[str, str]] = {}
    for raw in _array(entries, "container environment"):
        entry = _object(raw, "container environment entry")
        name = entry.get("name")
        if not isinstance(name, str) or not name or name in plain or name in secrets:
            _fail("container environment names must be unique non-empty strings")
        secret_ref = _normalize_secret_ref(entry)
        if secret_ref is None:
            value = entry.get("value", "")
            if not isinstance(value, str):
                _fail("plain environment values must be strings")
            plain[name] = value
        else:
            secrets[name] = secret_ref
    if plain != dict(expected_plain):
        _fail("Cloud Run plain environment drifted from the reviewed guest boundary")
    if set(secrets) != set(expected_secrets):
        _fail("Cloud Run secret environment inventory drifted")
    for name, expected_secret in expected_secrets.items():
        secret, version = secrets[name]
        if secret != expected_secret or not _positive_integer(version):
            _fail("Cloud Run secret name or positive numeric version drifted")


def _image_is_exact(repository: str, image: Any) -> bool:
    prefix = f"{REGION}-docker.pkg.dev/{PROJECT_ID}/{repository}/agent@sha256:"
    return (
        isinstance(image, str)
        and re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", image) is not None
    )


def _validate_service(document: Any, service: str) -> None:
    spec = SERVICE_SPECS[service]
    resource = _object(document, f"Cloud Run service {service}")
    metadata = _object(resource.get("metadata"), "service metadata")
    service_spec = _object(resource.get("spec"), "service spec")
    template = _object(service_spec.get("template"), "service template")
    template_metadata = _object(template.get("metadata", {}), "template metadata")
    template_spec = _object(template.get("spec"), "template spec")
    containers = _array(template_spec.get("containers"), "service containers")
    if len(containers) != 1:
        _fail(f"Cloud Run service {service} must have exactly one container")
    container = _object(containers[0], "service container")
    annotations = _object(template_metadata.get("annotations", {}), "annotations")
    top_annotations = _object(metadata.get("annotations", {}), "service annotations")
    max_scale = annotations.get("autoscaling.knative.dev/maxScale")
    revision_min_scale = annotations.get("autoscaling.knative.dev/minScale", "0")
    service_min_scale = top_annotations.get("run.googleapis.com/minScale", "0")
    ingress = top_annotations.get("run.googleapis.com/ingress")
    if not _integer_equals(revision_min_scale, 0) or not _integer_equals(
        service_min_scale, 0
    ):
        _fail(f"Cloud Run service {service} scaling boundary drifted")
    if (
        metadata.get("name") != service
        or ingress != "all"
        or template_spec.get("serviceAccountName") != spec["runtime"]
        or not _integer_equals(template_spec.get("containerConcurrency"), 8)
        or not _integer_equals(template_spec.get("timeoutSeconds"), 300)
        or max_scale != "1"
        or annotations.get("run.googleapis.com/execution-environment") != "gen2"
        or container.get("name", "agent") != "agent"
        or not _image_is_exact(str(spec["repository"]), container.get("image"))
        or container.get("command") != ["uvicorn"]
        or container.get("args")
        != [
            "aegra_api.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
            "--workers",
            "1",
        ]
    ):
        _fail(f"Cloud Run service {service} identity or runtime template drifted")
    _validate_environment(
        container.get("env", []),
        spec["plain_env"],  # type: ignore[arg-type]
        spec["secrets"],  # type: ignore[arg-type]
    )


def _validate_job(document: Any, job: str) -> None:
    spec = JOB_SPECS[job]
    resource = _object(document, f"Cloud Run job {job}")
    metadata = _object(resource.get("metadata"), "job metadata")
    outer_spec = _object(resource.get("spec"), "job spec")
    task_template = _object(outer_spec.get("template"), "job execution template")
    task_spec = _object(task_template.get("spec"), "job execution spec")
    template = _object(task_spec.get("template"), "job task template")
    template_spec = _object(template.get("spec"), "job task spec")
    containers = _array(template_spec.get("containers"), "job containers")
    if len(containers) != 1:
        _fail(f"Cloud Run job {job} must have exactly one container")
    container = _object(containers[0], "job container")
    if not _integer_equals(task_spec.get("taskCount", 1), 1) or not _integer_equals(
        task_spec.get("parallelism", 1), 1
    ):
        _fail(f"Cloud Run job {job} task fan-out drifted")
    if (
        metadata.get("name") != job
        or template_spec.get("serviceAccountName") != spec["service_account"]
        or not _integer_equals(template_spec.get("maxRetries"), 0)
        or not _integer_equals(
            template_spec.get("timeoutSeconds"), int(spec["timeout"])
        )
        or not _image_is_exact(str(spec["repository"]), container.get("image"))
        or container.get("name") != spec["container"]
        or container.get("command") != ["python"]
        or container.get("args") != ["-m", spec["module"]]
    ):
        _fail(f"Cloud Run job {job} identity, timeout, or command drifted")
    _validate_environment(
        container.get("env", []),
        {
            "ENV_MODE": "PRODUCTION",
            "RUN_MIGRATIONS_ON_STARTUP": "false",
        },
        {"DATABASE_URL": str(spec["secret"])},
    )


def _validate_scheduler(document: Any) -> None:
    scheduler = _object(document, "Cloud Scheduler job")
    target = _object(scheduler.get("httpTarget"), "Scheduler HTTP target")
    headers = _object(target.get("headers"), "Scheduler headers")
    oauth = _object(target.get("oauthToken"), "Scheduler OAuth token")
    allowed_headers = {"Content-Type", "User-Agent"}
    expected_uri = (
        f"https://run.googleapis.com/v2/projects/{PROJECT_ID}/locations/{REGION}/"
        "jobs/agent-maintenance:run"
    )
    if (
        scheduler.get("name")
        != f"projects/{PROJECT_ID}/locations/{REGION}/jobs/agent-guest-maintenance"
        or scheduler.get("schedule") != "*/15 * * * *"
        or scheduler.get("timeZone") != "Etc/UTC"
        or scheduler.get("attemptDeadline") != "60s"
        or scheduler.get("state") != "ENABLED"
        or not _integer_equals(
            _object(scheduler.get("retryConfig", {}), "Scheduler retry").get(
                "retryCount", 0
            ),
            0,
        )
        or target.get("httpMethod") != "POST"
        or target.get("uri") != expected_uri
        or target.get("body") != "e30="
        or headers.get("Content-Type") != "application/json"
        or not set(headers) <= allowed_headers
        or oauth.get("serviceAccountEmail") != MAINTENANCE_SCHEDULER_SA
        or oauth.get("scope") != "https://www.googleapis.com/auth/cloud-platform"
        or "oidcToken" in target
    ):
        _fail("Cloud Scheduler guest-maintenance contract drifted")


def verify_exact_project_readiness(
    read: Read,
    *,
    trust_service_accounts: Callable[[Iterable[str]], None] | None = None,
    trust_state_bucket: Callable[[], None] | None = None,
) -> None:
    """Read and validate every repository-owned exact-project readiness invariant."""
    validate_readiness_source_contract()
    _validate_project(
        _read_json(
            read,
            ("projects", "describe", PROJECT_ID, "--format=json"),
            "project describe",
        )
    )
    _validate_delivery_role(
        _read_json(
            read,
            (
                "iam",
                "roles",
                "describe",
                "cloudRunAgentDelivery",
                "--format=json",
            ),
            "Cloud Run delivery role",
        )
    )
    _validate_enabled_apis(
        read(("services", "list", "--enabled", "--format=value(config.name)"))
    )

    _validate_project_policy(
        _read_json(
            read,
            ("projects", "get-iam-policy", PROJECT_ID, "--format=json"),
            "project IAM policy",
        )
    )
    for repository, expected_policy in {
        "agent": {
            (
                "roles/artifactregistry.reader",
                f"serviceAccount:{CLOUD_RUN_SERVICE_AGENT}",
            ),
            (
                "roles/artifactregistry.reader",
                f"serviceAccount:{PRODUCTION_DEPLOYER_SA}",
            ),
            ("roles/artifactregistry.writer", f"serviceAccount:{BUILDER_SA}"),
        },
        "agent-preview": {
            (
                "roles/artifactregistry.reader",
                f"serviceAccount:{CLOUD_RUN_SERVICE_AGENT}",
            ),
            ("roles/artifactregistry.reader", f"serviceAccount:{PREVIEW_DEPLOYER_SA}"),
            ("roles/artifactregistry.writer", f"serviceAccount:{PREVIEW_BUILDER_SA}"),
        },
    }.items():
        prefix = ("artifacts", "repositories")
        suffix = (repository, "--location", REGION, "--format=json")
        _validate_artifact_repository(
            _read_json(read, (*prefix, "describe", *suffix), repository),
            repository,
            region=REGION,
        )
        policy = _object(
            _read_json(read, (*prefix, "get-iam-policy", *suffix), f"{repository} IAM"),
            f"{repository} IAM",
        )
        _require_exact_policy(policy, expected_policy, repository)

        legacy_suffix = (
            repository,
            "--location",
            LEGACY_REGION,
            "--format=json",
        )
        _validate_artifact_repository(
            _read_json(
                read,
                (*prefix, "describe", *legacy_suffix),
                f"legacy {repository}",
            ),
            repository,
            region=LEGACY_REGION,
        )
        legacy_policy = _object(
            _read_json(
                read,
                (*prefix, "get-iam-policy", *legacy_suffix),
                f"legacy {repository} IAM",
            ),
            f"legacy {repository} IAM",
        )
        _require_exact_policy(legacy_policy, set(), f"legacy {repository}")

    _validate_bucket_discovery(
        _read_json(
            read,
            (*BUCKET_DISCOVERY_COMMAND,),
            "exact-project bucket discovery",
        )
    )
    if trust_state_bucket is not None:
        trust_state_bucket()
    _validate_bucket(
        _read_json(
            read,
            (
                "storage",
                "buckets",
                "describe",
                f"gs://{STATE_BUCKET}",
                "--format=json",
            ),
            "state bucket",
        )
    )
    bucket_policy = _object(
        _read_json(
            read,
            (
                "storage",
                "buckets",
                "get-iam-policy",
                f"gs://{STATE_BUCKET}",
                "--format=json",
            ),
            "state bucket IAM",
        ),
        "state bucket IAM",
    )
    _require_no_public(bucket_policy, "state bucket")
    bucket_pairs = _policy_pairs(bucket_policy, require_unconditional=False)
    workload_members = {
        f"serviceAccount:{email}" for email in WORKLOAD_SERVICE_ACCOUNTS
    }
    if any(member in workload_members for _, member in bucket_pairs):
        _fail("a managed workload identity has direct Terraform-state access")
    _validate_state_object(
        _read_json(
            read,
            (
                "storage",
                "objects",
                "describe",
                f"gs://{STATE_BUCKET}/{STATE_OBJECT}",
                "--format=json",
            ),
            "state object",
        )
    )

    accounts = _validate_service_account_inventory(
        _read_json(
            read,
            ("iam", "service-accounts", "list", "--format=json"),
            "service-account inventory",
        )
    )
    if trust_service_accounts is not None:
        trust_service_accounts(accounts)
    for account in sorted(accounts):
        user_keys = read(
            (
                "iam",
                "service-accounts",
                "keys",
                "list",
                "--iam-account",
                account,
                "--managed-by=user",
                "--format=value(name)",
            )
        )
        if user_keys.strip():
            _fail("an exact-project service account has a user-managed key")

    runtime_act_as = {
        PRODUCTION_RUNTIME_SA: PRODUCTION_DEPLOYER_SA,
        PREVIEW_RUNTIME_SA: PREVIEW_DEPLOYER_SA,
        PRODUCTION_MIGRATOR_SA: PRODUCTION_DEPLOYER_SA,
        PREVIEW_MIGRATOR_SA: PREVIEW_DEPLOYER_SA,
    }
    delivery_federation = {
        PREVIEW_DEPLOYER_SA: "preview-deployer",
        PRODUCTION_DEPLOYER_SA: "production-deployer",
        BUILDER_SA: "production-builder",
        PREVIEW_BUILDER_SA: "preview-builder",
    }
    for account in sorted(WORKLOAD_SERVICE_ACCOUNTS):
        policy = _object(
            _read_json(
                read,
                (
                    "iam",
                    "service-accounts",
                    "get-iam-policy",
                    account,
                    "--format=json",
                ),
                f"{account} IAM",
            ),
            f"{account} IAM",
        )
        if account in runtime_act_as:
            expected = {
                (
                    "roles/iam.serviceAccountUser",
                    f"serviceAccount:{runtime_act_as[account]}",
                )
            }
        elif account in delivery_federation:
            role = delivery_federation[account]
            expected = {
                (
                    "roles/iam.workloadIdentityUser",
                    "principalSet://iam.googleapis.com/projects/"
                    f"{PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/"
                    f"attribute.delivery_role/{role}",
                )
            }
        else:
            expected = set()
        _require_exact_policy(policy, expected, account)

    for secret, expected_account in sorted(SECRET_POLICIES.items()):
        _validate_secret_metadata(
            _read_json(
                read,
                ("secrets", "describe", secret, "--format=json"),
                f"Secret Manager {secret}",
            ),
            secret,
        )
        policy = _object(
            _read_json(
                read,
                ("secrets", "get-iam-policy", secret, "--format=json"),
                f"Secret Manager {secret} IAM",
            ),
            f"Secret Manager {secret} IAM",
        )
        _require_exact_policy(
            policy,
            {
                (
                    "roles/secretmanager.secretAccessor",
                    f"serviceAccount:{expected_account}",
                )
            },
            f"Secret Manager {secret}",
        )

    pool = _read_json(
        read,
        (
            "iam",
            "workload-identity-pools",
            "describe",
            "github",
            "--location",
            "global",
            "--format=json",
        ),
        "WIF pool",
    )
    listed = _read_json(
        read,
        (
            "iam",
            "workload-identity-pools",
            "providers",
            "list",
            "--location",
            "global",
            "--workload-identity-pool",
            "github",
            "--format=json",
        ),
        "WIF provider list",
    )
    described = [
        _read_json(
            read,
            (
                "iam",
                "workload-identity-pools",
                "providers",
                "describe",
                provider,
                "--location",
                "global",
                "--workload-identity-pool",
                "github",
                "--format=json",
            ),
            f"WIF provider {provider}",
        )
        for provider in ("github-preview", "github-production")
    ]
    expected_pool_prefix = (
        f"projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/github"
    )
    listed_resources = [
        _object(item, "listed WIF provider")
        for item in _array(listed, "listed WIF providers")
    ]
    resources = [
        _object(pool, "WIF pool"),
        *listed_resources,
        *map(lambda item: _object(item, "WIF provider"), described),
    ]
    if resources[0].get("name") != expected_pool_prefix or any(
        not str(resource.get("name", "")).startswith(expected_pool_prefix + "/")
        for resource in resources[1:]
    ):
        _fail("WIF resources escaped the exact project number")
    try:
        validate_live_wif({"pool": pool, "listed": listed, "described": described})
    except ContractError as exc:
        raise ReadinessError(str(exc)) from exc

    for service, spec in SERVICE_SPECS.items():
        suffix = (service, "--region", REGION, "--format=json")
        _validate_service(
            _read_json(read, ("run", "services", "describe", *suffix), service),
            service,
        )
        policy = _object(
            _read_json(
                read,
                ("run", "services", "get-iam-policy", *suffix),
                f"{service} IAM",
            ),
            f"{service} IAM",
        )
        _require_exact_policy(
            policy,
            {
                (CLOUD_RUN_DELIVERY_ROLE, f"serviceAccount:{spec['deployer']}"),
                ("roles/run.invoker", "allUsers"),
            },
            service,
        )

    for job, spec in JOB_SPECS.items():
        suffix = (job, "--region", REGION, "--format=json")
        _validate_job(_read_json(read, ("run", "jobs", "describe", *suffix), job), job)
        expected_policy = {
            (CLOUD_RUN_DELIVERY_ROLE, f"serviceAccount:{spec['deployer']}")
        }
        scheduler = spec["scheduler"]
        if scheduler is not None:
            expected_policy.add(("roles/run.invoker", f"serviceAccount:{scheduler}"))
        policy = _object(
            _read_json(
                read,
                ("run", "jobs", "get-iam-policy", *suffix),
                f"{job} IAM",
            ),
            f"{job} IAM",
        )
        _require_exact_policy(policy, expected_policy, job)
        _require_no_public(policy, job)

    _validate_scheduler(
        _read_json(
            read,
            (
                "scheduler",
                "jobs",
                "describe",
                "agent-guest-maintenance",
                "--location",
                REGION,
                "--format=json",
            ),
            "guest maintenance Scheduler",
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcloud-bin", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        reader = GCloudReader(args.gcloud_bin)
        verify_exact_project_readiness(
            reader,
            trust_service_accounts=reader.trust_service_account_inventory,
            trust_state_bucket=reader.trust_state_bucket,
        )
    except ReadinessError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "OK: exact-project direct IAM and resource readiness verified; "
        "public launch and spend safety are not claimed, and inherited "
        "organization/folder IAM was not queried or claimed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
