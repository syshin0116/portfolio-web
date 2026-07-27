#!/usr/bin/env python3
"""Verify repository-local and read-only GitHub governance contracts."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shlex
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import yaml
    from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
    from yaml.tokens import AliasToken, AnchorToken, DirectiveToken, TagToken
except ModuleNotFoundError:
    yaml = None
    MappingNode = Node = ScalarNode = SequenceNode = Any
    AliasToken = AnchorToken = DirectiveToken = TagToken = object

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = REPO_ROOT / ".github/repository-governance.json"
FULL_SHA_ACTION = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
    r"(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}$"
)
FULL_SHA_REUSABLE_WORKFLOW = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/"
    r"\.github/workflows/[A-Za-z0-9_.-]+\.(?:yml|yaml)@[0-9a-f]{40}$"
)
LOCAL_REUSABLE_WORKFLOW = re.compile(
    r"^\./\.github/workflows/[A-Za-z0-9_.-]+\.(?:yml|yaml)$"
)
REQUIRED_CHECK_TRIGGERS = {
    "pull_request": {},
    "push": {"branches": ["main"]},
    "merge_group": {"types": ["checks_requested"]},
    "workflow_dispatch": {},
}
EXPECTED_REPOSITORY = "syshin0116/syshin0116.dev"
EXPECTED_API_VERSION = "2026-03-10"
EXPECTED_DEFAULT_BRANCH = "main"
EXPECTED_MAIN_REF = "refs/heads/main"
MAIN_RULE_TYPES = [
    "deletion",
    "non_fast_forward",
    "pull_request",
    "required_status_checks",
]
MAIN_RULESET_CONDITIONS = {
    "ref_name": {
        "include": ["~DEFAULT_BRANCH"],
        "exclude": [],
    }
}
MERGE_METHODS = ["merge", "squash", "rebase"]
SOLO_PULL_REQUEST_PARAMETERS = {
    "allowed_merge_methods": MERGE_METHODS,
    "dismiss_stale_reviews_on_push": False,
    "require_code_owner_review": False,
    "require_last_push_approval": False,
    "required_approving_review_count": 0,
    "required_review_thread_resolution": False,
    "required_reviewers": [],
}
MAIN_STATUS_CHECK_PARAMETERS = {
    "do_not_enforce_on_create": False,
    "strict_required_status_checks_policy": True,
}
EXPECTED_REQUIRED_CHECKS = [
    {
        "context": "ci/check",
        "integration_id": 15368,
        "workflow": ".github/workflows/ci.yml",
        "job": "check",
        "triggers": REQUIRED_CHECK_TRIGGERS,
    },
    {
        "context": "protocol/compat",
        "integration_id": 15368,
        "workflow": ".github/workflows/protocol-compat.yml",
        "job": "protocol-compat",
        "triggers": REQUIRED_CHECK_TRIGGERS,
    },
    {
        "context": "wiki/verify",
        "integration_id": 15368,
        "workflow": ".github/workflows/wiki-verify.yml",
        "job": "verify-wiki",
        "triggers": REQUIRED_CHECK_TRIGGERS,
    },
]
EXPECTED_ACTIONS = {
    "enabled": True,
    "allowed_actions": "all",
    "sha_pinning_required": True,
}
EXPECTED_ENVIRONMENTS = {
    "Preview": {
        "can_admins_bypass": True,
        "deployment_branch_policy": None,
        "branch_policies": [],
        "protection_rules": [],
    },
    "Production": {
        "can_admins_bypass": True,
        "deployment_branch_policy": {
            "protected_branches": False,
            "custom_branch_policies": True,
        },
        "branch_policies": [{"name": "main", "type": "branch"}],
        "protection_rules": [
            {
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [{"type": "User", "login": "syshin0116"}],
            },
            {"type": "branch_policy"},
        ],
    },
}
EXPECTED_AUTOMATED_SECURITY_FIXES = {
    "enabled": True,
    "paused": False,
}
EXPECTED_DEPENDABOT_SECURITY_UPDATES_STATUS = "enabled"
AGENT_CI_WORKFLOW = ".github/workflows/ci.yml"
AGENT_CI_JOB = "agent"
AGENT_CI_WORKING_DIRECTORY = "agent"
AGENT_CI_CHANGED_CONDITION = "needs.changes.outputs.agent == 'true'"
AGENT_CI_ENV = {
    "AGENT_AUTH_SECRET": "ci-only-agent-secret-ci-only-agent-secret",
}
AGENT_LOCK_COMMAND = ("uv", "lock", "--check")
AGENT_SYNC_COMMAND = ("uv", "sync", "--frozen", "--all-extras", "--dev")
AGENT_RUN_COMMANDS = (
    (
        "uv",
        "run",
        "--frozen",
        "ruff",
        "check",
        "src",
        "tests",
        "../scripts/build_index.py",
        "../scripts/ci_changed_components.py",
        "../scripts/verify_repository_governance.py",
        "../scripts/tests",
    ),
    (
        "uv",
        "run",
        "--frozen",
        "ruff",
        "format",
        "--check",
        "src",
        "tests",
        "../scripts/build_index.py",
        "../scripts/ci_changed_components.py",
        "../scripts/verify_repository_governance.py",
        "../scripts/tests",
    ),
    (
        "uv",
        "run",
        "--frozen",
        "python",
        "../scripts/build_index.py",
        "--expect-document-count",
        "335",
    ),
    ("uv", "run", "--frozen", "--all-extras", "pytest", "-q"),
)
AGENT_RUN_STEP_INVENTORY = (
    (
        "Fail closed if change detection failed",
        "needs.changes.result != 'success'",
        ("exit", "1"),
    ),
    (
        "Report an unaffected component",
        "needs.changes.outputs.agent != 'true'",
        (
            "echo",
            "No agent-affecting paths changed; "
            "ci/agent reports success without rebuilding.",
        ),
    ),
    (
        "Verify the agent lockfile is current",
        AGENT_CI_CHANGED_CONDITION,
        AGENT_LOCK_COMMAND,
    ),
    (None, AGENT_CI_CHANGED_CONDITION, AGENT_SYNC_COMMAND),
    (None, AGENT_CI_CHANGED_CONDITION, AGENT_RUN_COMMANDS[0]),
    (None, AGENT_CI_CHANGED_CONDITION, AGENT_RUN_COMMANDS[1]),
    (
        "Build and audit the published corpus and BM25 artifacts",
        AGENT_CI_CHANGED_CONDITION,
        AGENT_RUN_COMMANDS[2],
    ),
    (None, AGENT_CI_CHANGED_CONDITION, AGENT_RUN_COMMANDS[3]),
)
EXPECTED_AGENT_CI_JOB = {
    "name": "ci/agent",
    "if": "always()",
    "needs": ["changes"],
    "runs-on": "ubuntu-latest",
    "timeout-minutes": "20",
    "defaults": {
        "run": {
            "working-directory": AGENT_CI_WORKING_DIRECTORY,
        }
    },
    "env": AGENT_CI_ENV,
    "steps": [
        {
            "uses": ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"),
            "with": {
                "persist-credentials": "false",
            },
        },
        {
            "name": "Fail closed if change detection failed",
            "if": "needs.changes.result != 'success'",
            "run": "exit 1",
        },
        {
            "name": "Report an unaffected component",
            "if": "needs.changes.outputs.agent != 'true'",
            "run": (
                'echo "No agent-affecting paths changed; '
                'ci/agent reports success without rebuilding."'
            ),
        },
        {
            "uses": ("actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"),
            "if": AGENT_CI_CHANGED_CONDITION,
            "with": {
                "python-version": "3.12",
            },
        },
        {
            "uses": ("astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78"),
            "if": AGENT_CI_CHANGED_CONDITION,
            "with": {
                "enable-cache": "true",
                "cache-dependency-glob": "agent/uv.lock",
            },
        },
        {
            "name": "Verify the agent lockfile is current",
            "if": AGENT_CI_CHANGED_CONDITION,
            "run": " ".join(AGENT_LOCK_COMMAND),
        },
        {
            "if": AGENT_CI_CHANGED_CONDITION,
            "run": " ".join(AGENT_SYNC_COMMAND),
        },
        {
            "if": AGENT_CI_CHANGED_CONDITION,
            "run": " ".join(AGENT_RUN_COMMANDS[0]),
        },
        {
            "if": AGENT_CI_CHANGED_CONDITION,
            "run": " ".join(AGENT_RUN_COMMANDS[1]),
        },
        {
            "name": "Build and audit the published corpus and BM25 artifacts",
            "if": AGENT_CI_CHANGED_CONDITION,
            "run": " ".join(AGENT_RUN_COMMANDS[2]),
        },
        {
            "if": AGENT_CI_CHANGED_CONDITION,
            "run": " ".join(AGENT_RUN_COMMANDS[3]),
        },
    ],
}
EXPECTED_DEPENDABOT = {
    "vulnerability_alerts_enabled": True,
    "automated_security_fixes": EXPECTED_AUTOMATED_SECURITY_FIXES,
    "repository_security_updates_status": EXPECTED_DEPENDABOT_SECURITY_UPDATES_STATUS,
    "version": 2,
    "updates": [
        {
            "package_ecosystem": "npm",
            "directory": "/web",
            "schedule": {
                "interval": "weekly",
                "day": "monday",
                "time": "04:00",
                "timezone": "Asia/Seoul",
            },
            "open_pull_requests_limit": 3,
            "cooldown": {
                "default_days": 7,
                "semver_major_days": 14,
                "semver_minor_days": 7,
                "semver_patch_days": 3,
            },
            "groups": [
                {
                    "name": "web-routine",
                    "applies_to": "version-updates",
                    "patterns": ["*"],
                    "exclude_patterns": [
                        "@assistant-ui/*",
                        "@auth/*",
                        "@langchain/*",
                        "next",
                        "next-auth",
                    ],
                    "update_types": ["minor", "patch"],
                }
            ],
        },
        {
            "package_ecosystem": "pip",
            "directory": "/agent",
            "schedule": {
                "interval": "weekly",
                "day": "monday",
                "time": "04:20",
                "timezone": "Asia/Seoul",
            },
            "open_pull_requests_limit": 3,
            "cooldown": {
                "default_days": 7,
                "semver_major_days": 14,
                "semver_minor_days": 7,
                "semver_patch_days": 3,
            },
            "groups": [
                {
                    "name": "agent-routine",
                    "applies_to": "version-updates",
                    "patterns": ["*"],
                    "exclude_patterns": [
                        "aegra-*",
                        "deepagents",
                        "langchain",
                        "langchain-*",
                        "langgraph",
                        "langgraph-*",
                        "langsmith",
                    ],
                    "update_types": ["minor", "patch"],
                }
            ],
        },
        {
            "package_ecosystem": "github-actions",
            "directory": "/",
            "schedule": {
                "interval": "weekly",
                "day": "monday",
                "time": "04:40",
                "timezone": "Asia/Seoul",
            },
            "open_pull_requests_limit": 3,
            "cooldown": {
                "default_days": 7,
            },
            "groups": [
                {
                    "name": "actions-routine",
                    "applies_to": "version-updates",
                    "patterns": ["*"],
                    "exclude_patterns": [],
                    "update_types": ["minor", "patch"],
                }
            ],
        },
    ],
}

JsonObject = dict[str, Any]
ApiGet = Callable[[str], Any]


class GovernanceError(RuntimeError):
    """A live GitHub governance query could not be completed."""


@dataclass(frozen=True)
class YamlDocument:
    """One ambiguity-checked YAML syntax tree."""

    path: Path
    root: MappingNode


@dataclass(frozen=True)
class ApiResponse:
    """One GitHub API payload together with lower-cased response headers."""

    payload: Any
    headers: dict[str, str]
    status: int = 200


@dataclass(frozen=True)
class UsesReference:
    """A semantically valid `uses` position and the target kind it requires."""

    line_number: int
    reference: str
    target_kind: str


@dataclass(frozen=True)
class RequiredCheckContract:
    """One required check and the workflow/job that must always emit it."""

    context: str
    integration_id: int
    workflow: str
    job: str
    triggers: JsonObject


def _json_exact(actual: Any, expected: Any) -> bool:
    """Compare JSON values without treating booleans as integers."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _json_exact(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _json_exact(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected, strict=True)
        )
    return actual == expected


def _require_yaml() -> None:
    if yaml is None:
        raise GovernanceError(
            "PyYAML is required; run with `uv run --with pyyaml==6.0.3 python ...`"
        )


def _node_location(node: Node) -> str:
    return f"line {node.start_mark.line + 1}, column {node.start_mark.column + 1}"


def _mapping_items(node: MappingNode) -> Iterable[tuple[str, Node, ScalarNode]]:
    for key_node, value_node in node.value:
        if not isinstance(key_node, ScalarNode):
            raise GovernanceError(
                f"complex YAML mapping key at {_node_location(key_node)} is forbidden"
            )
        yield key_node.value, value_node, key_node


def _validate_yaml_node(node: Node) -> None:
    if isinstance(node, MappingNode):
        seen: dict[str, ScalarNode] = {}
        for key, value_node, key_node in _mapping_items(node):
            if key == "<<":
                raise GovernanceError(
                    f"YAML merge key at {_node_location(key_node)} is forbidden"
                )
            if key in seen:
                first = seen[key]
                raise GovernanceError(
                    f"duplicate YAML key {key!r} at {_node_location(key_node)} "
                    f"(first defined at {_node_location(first)})"
                )
            seen[key] = key_node
            _validate_yaml_node(value_node)
        return
    if isinstance(node, SequenceNode):
        for item in node.value:
            _validate_yaml_node(item)
        return
    if not isinstance(node, ScalarNode):
        raise GovernanceError(f"unsupported YAML node at {_node_location(node)}")


def load_yaml_document(path: Path) -> YamlDocument:
    """Parse one mapping document while rejecting ambiguous YAML features."""
    _require_yaml()
    try:
        text = path.read_text(encoding="utf-8")
        forbidden_tokens = (AliasToken, AnchorToken, DirectiveToken, TagToken)
        for token in yaml.scan(text, Loader=yaml.BaseLoader):
            if isinstance(token, forbidden_tokens):
                raise GovernanceError(
                    f"{path}: YAML anchors, aliases, directives, and explicit "
                    f"tags are forbidden ({type(token).__name__} at "
                    f"line {token.start_mark.line + 1})"
                )
        documents = list(yaml.compose_all(text, Loader=yaml.BaseLoader))
    except OSError as exc:
        raise GovernanceError(f"cannot read YAML {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise GovernanceError(f"invalid YAML {path}: {exc}") from exc

    if len(documents) != 1 or documents[0] is None:
        raise GovernanceError(
            f"{path}: expected exactly one non-empty YAML document, "
            f"found {len(documents)}"
        )
    root = documents[0]
    if not isinstance(root, MappingNode):
        raise GovernanceError(f"{path}: YAML root must be a mapping")
    try:
        _validate_yaml_node(root)
    except GovernanceError as exc:
        raise GovernanceError(f"{path}: {exc}") from exc
    return YamlDocument(path=path, root=root)


def _mapping_value(node: MappingNode, key: str) -> Node | None:
    for candidate, value_node, _ in _mapping_items(node):
        if candidate == key:
            return value_node
    return None


def _scalar_value(node: Node, *, context: str) -> str:
    if not isinstance(node, ScalarNode):
        raise GovernanceError(f"{context} must be a scalar at {_node_location(node)}")
    return node.value


def _node_to_data(node: Node) -> Any:
    if isinstance(node, ScalarNode):
        return node.value
    if isinstance(node, SequenceNode):
        return [_node_to_data(item) for item in node.value]
    if isinstance(node, MappingNode):
        return {
            key: _node_to_data(value_node)
            for key, value_node, _ in _mapping_items(node)
        }
    raise GovernanceError(f"unsupported YAML node at {_node_location(node)}")


def load_policy(path: Path = DEFAULT_POLICY) -> JsonObject:
    """Load the machine-readable expected governance state."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceError(f"cannot load policy {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GovernanceError(f"policy {path} must contain one JSON object")
    return payload


def workflow_files(root: Path) -> list[Path]:
    """Return GitHub-supported top-level workflow paths."""
    workflow_dir = root / ".github/workflows"
    return sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))


def nested_workflow_files(root: Path) -> list[Path]:
    """Return unsupported YAML files below workflow subdirectories."""
    workflow_dir = root / ".github/workflows"
    return sorted(
        path
        for path in (*workflow_dir.rglob("*.yml"), *workflow_dir.rglob("*.yaml"))
        if path.parent != workflow_dir
    )


def action_manifest_files(root: Path) -> list[Path]:
    """Return repository-owned action manifests in deterministic order."""
    action_dir = root / ".github/actions"
    return sorted(
        (
            *action_dir.rglob("action.yml"),
            *action_dir.rglob("action.yaml"),
        )
    )


def _nodes_for_mapping_key(node: Node, key: str) -> Iterable[Node]:
    if isinstance(node, MappingNode):
        for candidate, value_node, _ in _mapping_items(node):
            if candidate == key:
                yield value_node
            yield from _nodes_for_mapping_key(value_node, key)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            yield from _nodes_for_mapping_key(item, key)


def workflow_job_names(document: YamlDocument) -> list[str]:
    """Extract job display names from the workflow AST."""
    jobs = _mapping_value(document.root, "jobs")
    if jobs is None:
        return []
    if not isinstance(jobs, MappingNode):
        raise GovernanceError(f"{document.path}: jobs must be a mapping")
    names: list[str] = []
    for job_name, job_node, _ in _mapping_items(jobs):
        if not isinstance(job_node, MappingNode):
            raise GovernanceError(
                f"{document.path}: job {job_name!r} must be a mapping"
            )
        name = _mapping_value(job_node, "name")
        if name is not None:
            names.append(
                _scalar_value(
                    name,
                    context=f"{document.path}: job {job_name!r} name",
                ).strip()
            )
    return names


def workflow_events(document: YamlDocument) -> set[str]:
    """Extract top-level workflow events from the workflow AST."""
    events = _mapping_value(document.root, "on")
    if events is None:
        return set()
    if isinstance(events, ScalarNode):
        return {events.value}
    if isinstance(events, SequenceNode):
        return {
            _scalar_value(item, context=f"{document.path}: workflow event")
            for item in events.value
        }
    if isinstance(events, MappingNode):
        return {key for key, _, _ in _mapping_items(events)}
    raise GovernanceError(f"{document.path}: on must be a scalar, list, or mapping")


def workflow_trigger_config(document: YamlDocument) -> JsonObject:
    """Normalize a required workflow's mapping-form `on` declaration."""
    events = _mapping_value(document.root, "on")
    if not isinstance(events, MappingNode):
        raise GovernanceError(
            f"{document.path}: required workflow on must be a mapping"
        )
    normalized: JsonObject = {}
    for event, options, _ in _mapping_items(events):
        if isinstance(options, (MappingNode, SequenceNode)):
            normalized[event] = _node_to_data(options)
            continue
        if isinstance(options, ScalarNode) and options.value in {
            "",
            "null",
            "Null",
            "NULL",
            "~",
        }:
            normalized[event] = {}
            continue
        raise GovernanceError(
            f"{document.path}: trigger {event!r} options must be an "
            "empty value, mapping, or list"
        )
    return normalized


def _workflow_jobs(document: YamlDocument) -> dict[str, MappingNode]:
    jobs = _mapping_value(document.root, "jobs")
    if not isinstance(jobs, MappingNode):
        raise GovernanceError(f"{document.path}: jobs must be a mapping")
    normalized: dict[str, MappingNode] = {}
    for job_name, job, _ in _mapping_items(jobs):
        if not isinstance(job, MappingNode):
            raise GovernanceError(
                f"{document.path}: job {job_name!r} must be a mapping"
            )
        normalized[job_name] = job
    return normalized


def _job_needs(job: MappingNode, *, context: str) -> list[str]:
    needs = _mapping_value(job, "needs")
    if needs is None:
        return []
    if isinstance(needs, ScalarNode):
        if not needs.value:
            raise GovernanceError(f"{context} needs must not be empty")
        return [needs.value]
    if isinstance(needs, SequenceNode):
        values = [
            _scalar_value(item, context=f"{context} needs") for item in needs.value
        ]
        if not values or len(values) != len(set(values)):
            raise GovernanceError(
                f"{context} needs must be a non-empty unique job list"
            )
        return values
    raise GovernanceError(f"{context} needs must be a job or job list")


def _job_condition(job: MappingNode, *, context: str) -> str | None:
    condition = _mapping_value(job, "if")
    if condition is None:
        return None
    value = _scalar_value(condition, context=f"{context} if").strip()
    if value.startswith("${{") and value.endswith("}}"):
        value = value[3:-2].strip()
    return value


def _simple_shell_words(run: Node, *, context: str) -> tuple[str, ...]:
    script = _scalar_value(run, context=f"{context} run")
    try:
        lexer = shlex.shlex(
            script,
            posix=True,
            punctuation_chars=";&|()<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = "#"
        return tuple(lexer)
    except ValueError as exc:
        raise GovernanceError(
            f"{context} run is not valid shell syntax: {exc}"
        ) from exc


def validate_agent_ci_resolution(document: YamlDocument) -> list[str]:
    """Require one immutable, lock-checked uv resolution in the ci/agent job."""
    errors: list[str] = []
    for inherited_key in ("defaults", "env"):
        if _mapping_value(document.root, inherited_key) is not None:
            errors.append(
                f"{AGENT_CI_WORKFLOW}: workflow-level {inherited_key} is "
                "forbidden because it can change ci/agent command semantics"
            )
    jobs = _workflow_jobs(document)
    agent = jobs.get(AGENT_CI_JOB)
    if agent is None:
        return [f"{AGENT_CI_WORKFLOW}: required job {AGENT_CI_JOB!r} is missing"]

    context = f"{AGENT_CI_WORKFLOW}: job {AGENT_CI_JOB!r}"
    actual_agent_job = _node_to_data(agent)
    if not _json_exact(actual_agent_job, EXPECTED_AGENT_CI_JOB):
        errors.append(
            f"{context} exact job AST differs; "
            f"expected={EXPECTED_AGENT_CI_JOB!r}, actual={actual_agent_job!r}"
        )

    defaults = _mapping_value(agent, "defaults")
    if not isinstance(defaults, MappingNode):
        errors.append(f"{context} defaults must be a mapping")
    elif {key for key, _, _ in _mapping_items(defaults)} != {"run"}:
        errors.append(f"{context} defaults may contain only the run mapping")
    run_defaults = (
        _mapping_value(defaults, "run") if isinstance(defaults, MappingNode) else None
    )
    if not isinstance(run_defaults, MappingNode):
        errors.append(f"{context} defaults.run must be a mapping")
    elif {key for key, _, _ in _mapping_items(run_defaults)} != {"working-directory"}:
        errors.append(
            f"{context} defaults.run may contain only working-directory; "
            "inherited shell changes are forbidden"
        )
    working_directory = (
        _mapping_value(run_defaults, "working-directory")
        if isinstance(run_defaults, MappingNode)
        else None
    )
    actual_working_directory = (
        _scalar_value(
            working_directory,
            context=f"{context} defaults.run.working-directory",
        )
        if working_directory is not None
        else None
    )
    if actual_working_directory != AGENT_CI_WORKING_DIRECTORY:
        errors.append(
            f"{context} defaults.run.working-directory must remain "
            f"{AGENT_CI_WORKING_DIRECTORY!r}, found {actual_working_directory!r}"
        )

    agent_env = _mapping_value(agent, "env")
    actual_agent_env = (
        _node_to_data(agent_env) if isinstance(agent_env, MappingNode) else None
    )
    if actual_agent_env != AGENT_CI_ENV:
        errors.append(
            f"{context} env must remain exactly {AGENT_CI_ENV!r}, "
            f"found {actual_agent_env!r}"
        )

    steps = _mapping_value(agent, "steps")
    if not isinstance(steps, SequenceNode):
        return [*errors, f"{context} steps must be a list"]

    run_step_inventory: list[tuple[str | None, str | None, tuple[str, ...]]] = []
    for index, step in enumerate(steps.value):
        step_context = f"{context} step[{index}]"
        if not isinstance(step, MappingNode):
            errors.append(f"{step_context} must be a mapping")
            continue
        run = _mapping_value(step, "run")
        if run is None:
            continue
        step_keys = {key for key, _, _ in _mapping_items(step)}
        unexpected_step_keys = step_keys - {"name", "if", "run"}
        if unexpected_step_keys:
            errors.append(
                f"{step_context} run step has forbidden execution metadata: "
                f"{sorted(unexpected_step_keys)!r}"
            )
        try:
            words = _simple_shell_words(run, context=step_context)
            name_node = _mapping_value(step, "name")
            name = (
                _scalar_value(name_node, context=f"{step_context} name")
                if name_node is not None
                else None
            )
            condition = _job_condition(step, context=step_context)
        except GovernanceError as exc:
            errors.append(str(exc))
            continue
        run_step_inventory.append((name, condition, words))
    if tuple(run_step_inventory) != AGENT_RUN_STEP_INVENTORY:
        errors.append(
            f"{context} exact run-step inventory differs; "
            f"expected={AGENT_RUN_STEP_INVENTORY!r}, "
            f"actual={tuple(run_step_inventory)!r}"
        )
    return errors


def validate_required_job_graph(
    document: YamlDocument,
    emitter_job: str,
) -> list[str]:
    """Ensure the required emitter and every dependency always create a job."""
    errors: list[str] = []
    jobs = _workflow_jobs(document)
    if emitter_job not in jobs:
        return [f"required emitter job {emitter_job!r} is missing from {document.path}"]
    state: dict[str, str] = {}
    stack: list[str] = []

    def visit(job_name: str) -> None:
        status = state.get(job_name)
        if status == "done":
            return
        if status == "visiting":
            cycle_start = stack.index(job_name)
            errors.append(
                "required-check needs cycle: "
                + " -> ".join([*stack[cycle_start:], job_name])
            )
            return
        job = jobs.get(job_name)
        if job is None:
            errors.append(f"required-check dependency job {job_name!r} is missing")
            return
        state[job_name] = "visiting"
        stack.append(job_name)
        context = f"{document.path}: job {job_name!r}"
        try:
            needs = _job_needs(job, context=context)
            condition = _job_condition(job, context=context)
            if condition not in {None, "always()"}:
                errors.append(
                    f"{context} can skip required-check creation with if: {condition!r}"
                )
            if needs and condition != "always()":
                errors.append(f"{context} has needs and must use if: always()")
            for dependency in needs:
                visit(dependency)
        except GovernanceError as exc:
            errors.append(str(exc))
        finally:
            stack.pop()
            state[job_name] = "done"

    visit(emitter_job)
    return errors


def validate_required_execution_safety(
    root: Path,
    documents: dict[Path, YamlDocument],
    document: YamlDocument,
    emitter_job: str,
) -> list[str]:
    """Forbid false-green execution on every repository-owned required path."""
    repository_root = root.resolve()
    errors: list[str] = []
    inspected_actions: set[Path] = set()
    inspected_workflows: set[Path] = set()
    inspected_required_jobs: set[str] = set()

    def display(path: Path) -> str:
        return _display_path(path.resolve(), repository_root)

    def reject_continue_on_error(node: MappingNode, *, context: str) -> None:
        if _mapping_value(node, "continue-on-error") is not None:
            errors.append(
                f"{context} sets continue-on-error on a required-check execution path"
            )

    def inspect_steps(steps: Node, *, source: Path, context: str) -> None:
        if not isinstance(steps, SequenceNode):
            errors.append(f"{context} steps must be a list")
            return
        for index, step in enumerate(steps.value):
            step_context = f"{context} step[{index}]"
            if not isinstance(step, MappingNode):
                errors.append(f"{step_context} must be a mapping")
                continue
            reject_continue_on_error(step, context=step_context)
            uses = _mapping_value(step, "uses")
            if uses is None:
                continue
            try:
                reference = _scalar_value(uses, context=f"{step_context} uses")
                if not reference.startswith("./"):
                    continue
                target = _resolve_local_action_reference(
                    repository_root,
                    source,
                    uses.start_mark.line + 1,
                    reference,
                )
            except GovernanceError as exc:
                errors.append(str(exc))
                continue
            inspect_action(target)

    def inspect_job(
        job: MappingNode,
        *,
        source: Path,
        job_name: str,
        required_graph: bool,
    ) -> None:
        context = f"{display(source)}: job {job_name!r}"
        reject_continue_on_error(job, context=context)
        uses = _mapping_value(job, "uses")
        if uses is not None:
            try:
                reference = _scalar_value(uses, context=f"{context} uses")
                if required_graph:
                    errors.append(
                        f"{context} uses reusable workflow {reference!r}; "
                        "job-level uses is forbidden on a required-check "
                        "emitter or needs path"
                    )
                if not reference.startswith("./"):
                    return
                target = _resolve_local_workflow_reference(
                    repository_root,
                    source,
                    uses.start_mark.line + 1,
                    reference,
                )
            except GovernanceError as exc:
                errors.append(str(exc))
                return
            inspect_workflow(target)
            return
        steps = _mapping_value(job, "steps")
        if steps is not None:
            inspect_steps(steps, source=source, context=context)

    def inspect_action(path: Path) -> None:
        resolved = path.resolve()
        if resolved in inspected_actions:
            return
        inspected_actions.add(resolved)
        action = documents.get(resolved)
        if action is None:
            errors.append(
                "required-check safety cannot inspect local action "
                f"{display(resolved)!r}"
            )
            return
        runs = _mapping_value(action.root, "runs")
        if not isinstance(runs, MappingNode):
            errors.append(f"{display(resolved)}: action runs must be a mapping")
            return
        steps = _mapping_value(runs, "steps")
        if steps is None:
            errors.append(f"{display(resolved)}: composite action has no steps")
            return
        inspect_steps(
            steps,
            source=resolved,
            context=f"{display(resolved)}: composite action",
        )

    def inspect_workflow(path: Path) -> None:
        resolved = path.resolve()
        if resolved in inspected_workflows:
            return
        inspected_workflows.add(resolved)
        workflow = documents.get(resolved)
        if workflow is None:
            errors.append(
                "required-check safety cannot inspect local reusable workflow "
                f"{display(resolved)!r}"
            )
            return
        try:
            jobs = _workflow_jobs(workflow)
        except GovernanceError as exc:
            errors.append(str(exc))
            return
        for job_name, job in jobs.items():
            inspect_job(
                job,
                source=resolved,
                job_name=job_name,
                required_graph=False,
            )

    try:
        root_jobs = _workflow_jobs(document)
    except GovernanceError as exc:
        return [str(exc)]

    def inspect_required_job(job_name: str) -> None:
        if job_name in inspected_required_jobs:
            return
        inspected_required_jobs.add(job_name)
        job = root_jobs.get(job_name)
        if job is None:
            return
        inspect_job(
            job,
            source=document.path,
            job_name=job_name,
            required_graph=True,
        )
        try:
            needs = _job_needs(
                job,
                context=f"{display(document.path)}: job {job_name!r}",
            )
        except GovernanceError as exc:
            errors.append(str(exc))
            return
        for dependency in needs:
            inspect_required_job(dependency)

    inspected_workflows.add(document.path.resolve())
    inspect_required_job(emitter_job)
    return errors


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _step_action_references(
    steps: Node,
    *,
    context: str,
) -> list[UsesReference]:
    if not isinstance(steps, SequenceNode):
        raise GovernanceError(f"{context} steps must be a list")
    references: list[UsesReference] = []
    for index, step in enumerate(steps.value):
        step_context = f"{context} steps[{index}]"
        if not isinstance(step, MappingNode):
            raise GovernanceError(f"{step_context} must be a mapping")
        uses = _mapping_value(step, "uses")
        run = _mapping_value(step, "run")
        if uses is not None and run is not None:
            raise GovernanceError(f"{step_context} cannot contain both uses and run")
        if uses is None:
            continue
        reference = _scalar_value(uses, context=f"{step_context} uses")
        references.append(
            UsesReference(
                line_number=uses.start_mark.line + 1,
                reference=reference,
                target_kind="action",
            )
        )
    return references


def _workflow_uses_references(document: YamlDocument) -> list[UsesReference]:
    jobs = _mapping_value(document.root, "jobs")
    if not isinstance(jobs, MappingNode):
        raise GovernanceError(f"{document.path}: jobs must be a mapping")
    references: list[UsesReference] = []
    for job_name, job, _ in _mapping_items(jobs):
        if not isinstance(job, MappingNode):
            raise GovernanceError(
                f"{document.path}: job {job_name!r} must be a mapping"
            )
        context = f"{document.path}: job {job_name!r}"
        uses = _mapping_value(job, "uses")
        steps = _mapping_value(job, "steps")
        if uses is not None:
            if steps is not None:
                raise GovernanceError(
                    f"{context} cannot contain both job-level uses and steps"
                )
            reference = _scalar_value(uses, context=f"{context} uses")
            references.append(
                UsesReference(
                    line_number=uses.start_mark.line + 1,
                    reference=reference,
                    target_kind="workflow",
                )
            )
            continue
        if steps is None:
            raise GovernanceError(
                f"{context} must contain either steps or reusable-workflow uses"
            )
        references.extend(_step_action_references(steps, context=context))
    return references


def _action_uses_references(document: YamlDocument) -> list[UsesReference]:
    runs = _mapping_value(document.root, "runs")
    if not isinstance(runs, MappingNode):
        raise GovernanceError(f"{document.path}: action runs must be a mapping")
    using = _mapping_value(runs, "using")
    if (
        using is None
        or _scalar_value(
            using,
            context=f"{document.path}: action runs.using",
        )
        != "composite"
    ):
        raise GovernanceError(
            f"{document.path}: repository-local action runs.using must be 'composite'"
        )
    steps = _mapping_value(runs, "steps")
    if steps is None:
        raise GovernanceError(
            f"{document.path}: composite action runs.steps is required"
        )
    return _step_action_references(
        steps,
        context=f"{document.path}: composite action",
    )


def _workflow_has_call_trigger(document: YamlDocument) -> bool:
    return "workflow_call" in workflow_events(document)


def _resolve_repository_path(
    root: Path,
    source: Path,
    line_number: int,
    reference: str,
) -> Path:
    repository_root = root.resolve()
    relative_target = reference.removeprefix("./")
    if not relative_target:
        raise GovernanceError(
            f"{_display_path(source, repository_root)}:{line_number} "
            "local uses target is empty"
        )
    target = (repository_root / relative_target).resolve()
    if not target.is_relative_to(repository_root):
        raise GovernanceError(
            f"{_display_path(source, repository_root)}:{line_number} "
            f"local uses target escapes the repository: {reference}"
        )
    return target


def _resolve_local_action_reference(
    root: Path,
    source: Path,
    line_number: int,
    reference: str,
) -> Path:
    repository_root = root.resolve()
    if reference.startswith("./.github/workflows/"):
        raise GovernanceError(
            f"{_display_path(source, repository_root)}:{line_number} "
            "step-level uses cannot target a reusable workflow"
        )
    target = _resolve_repository_path(
        repository_root,
        source,
        line_number,
        reference,
    )
    if target.is_dir():
        manifests = [
            candidate
            for candidate in (target / "action.yml", target / "action.yaml")
            if candidate.is_file()
        ]
        if len(manifests) != 1:
            raise GovernanceError(
                f"{_display_path(source, repository_root)}:{line_number} "
                f"local action {reference!r} must contain exactly one of "
                f"action.yml/action.yaml, found {len(manifests)}"
            )
        manifest = manifests[0].resolve()
        if not manifest.is_relative_to(repository_root):
            raise GovernanceError(
                f"{_display_path(source, repository_root)}:{line_number} "
                f"local action manifest escapes the repository: {reference}"
            )
        return manifest

    raise GovernanceError(
        f"{_display_path(source, repository_root)}:{line_number} local action "
        f"target is missing or unsupported: {reference}"
    )


def _resolve_local_workflow_reference(
    root: Path,
    source: Path,
    line_number: int,
    reference: str,
) -> Path:
    repository_root = root.resolve()
    if LOCAL_REUSABLE_WORKFLOW.fullmatch(reference) is None:
        raise GovernanceError(
            f"{_display_path(source, repository_root)}:{line_number} "
            "job-level uses must target "
            "./.github/workflows/<file>.yml|yaml with no subdirectory or ref"
        )
    target = _resolve_repository_path(
        repository_root,
        source,
        line_number,
        reference,
    )
    workflow_root = (repository_root / ".github/workflows").resolve()
    if (
        not target.is_file()
        or target.parent != workflow_root
        or target.suffix not in {".yml", ".yaml"}
    ):
        raise GovernanceError(
            f"{_display_path(source, repository_root)}:{line_number} local "
            f"reusable workflow is missing or unsupported: {reference}"
        )
    return target


def _validate_external_uses(
    source: Path,
    root: Path,
    uses: UsesReference,
) -> str | None:
    display = _display_path(source, root)
    reference = uses.reference
    if uses.target_kind == "workflow":
        if FULL_SHA_REUSABLE_WORKFLOW.fullmatch(reference) is None:
            return (
                f"local: {display}:{uses.line_number} job-level uses must "
                "reference owner/repo/.github/workflows/<file>.yml|yaml at "
                f"a full lowercase commit SHA: {reference}"
            )
        return None
    if "/.github/workflows/" in reference:
        return (
            f"local: {display}:{uses.line_number} step-level uses cannot "
            f"target a reusable workflow: {reference}"
        )
    if FULL_SHA_ACTION.fullmatch(reference) is None:
        return (
            f"local: {display}:{uses.line_number} action is not pinned to "
            f"a full lowercase commit SHA: {reference}"
        )
    return None


def validate_repository_yaml_references(
    root: Path,
) -> tuple[dict[Path, YamlDocument], list[str]]:
    """Parse workflow/action YAML and recursively validate every `uses` edge."""
    repository_root = root.resolve()
    workflow_paths = [path.resolve() for path in workflow_files(repository_root)]
    action_paths = [path.resolve() for path in action_manifest_files(repository_root)]
    errors: list[str] = []
    for nested in nested_workflow_files(repository_root):
        errors.append(
            "local: nested workflow YAML is not supported by GitHub: "
            f"{_display_path(nested, repository_root)}"
        )

    action_manifests_by_directory: dict[Path, list[Path]] = {}
    for path in action_paths:
        action_manifests_by_directory.setdefault(path.parent, []).append(path)
    for directory, manifests in action_manifests_by_directory.items():
        if len(manifests) > 1:
            errors.append(
                "local: repository action directory "
                f"{_display_path(directory, repository_root)!r} contains both "
                "action.yml and action.yaml"
            )

    documents: dict[Path, YamlDocument] = {}
    state: dict[Path, str] = {}
    stack: list[Path] = []

    document_kinds: dict[Path, str] = {
        **dict.fromkeys(workflow_paths, "workflow"),
        **dict.fromkeys(action_paths, "action"),
    }

    def visit(
        path: Path,
        kind: str,
        *,
        require_workflow_call: bool = False,
    ) -> None:
        status = state.get(path)
        if status == "done":
            if (
                require_workflow_call
                and path in documents
                and not _workflow_has_call_trigger(documents[path])
            ):
                errors.append(
                    "local: reusable workflow lacks on.workflow_call: "
                    f"{_display_path(path, repository_root)}"
                )
            return
        if status == "visiting":
            cycle_start = stack.index(path)
            cycle = [*stack[cycle_start:], path]
            errors.append(
                "local: local uses cycle detected: "
                + " -> ".join(_display_path(item, repository_root) for item in cycle)
            )
            return

        state[path] = "visiting"
        existing_kind = document_kinds.setdefault(path, kind)
        if existing_kind != kind:
            errors.append(
                "local: uses target kind changed for "
                f"{_display_path(path, repository_root)}: "
                f"{existing_kind} vs {kind}"
            )
            state[path] = "done"
            return
        stack.append(path)
        try:
            document = load_yaml_document(path)
            documents[path] = document
            if require_workflow_call and not _workflow_has_call_trigger(document):
                errors.append(
                    "local: reusable workflow lacks on.workflow_call: "
                    f"{_display_path(path, repository_root)}"
                )
            references = (
                _workflow_uses_references(document)
                if kind == "workflow"
                else _action_uses_references(document)
            )
            for uses in references:
                reference = uses.reference
                if not reference.startswith("./"):
                    external_error = _validate_external_uses(
                        path,
                        repository_root,
                        uses,
                    )
                    if external_error is not None:
                        errors.append(external_error)
                    continue
                try:
                    if uses.target_kind == "workflow":
                        target = _resolve_local_workflow_reference(
                            repository_root,
                            path,
                            uses.line_number,
                            reference,
                        )
                    else:
                        target = _resolve_local_action_reference(
                            repository_root,
                            path,
                            uses.line_number,
                            reference,
                        )
                except GovernanceError as exc:
                    errors.append(f"local: {exc}")
                    continue
                visit(
                    target,
                    uses.target_kind,
                    require_workflow_call=uses.target_kind == "workflow",
                )
        except GovernanceError as exc:
            errors.append(
                "local: invalid workflow/action YAML "
                f"{_display_path(path, repository_root)}: {exc}"
            )
        finally:
            stack.pop()
            state[path] = "done"

    for path in sorted({*workflow_paths, *action_paths}):
        visit(path, document_kinds[path])
    return documents, errors


def _string_list(value: Any, *, context: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GovernanceError(f"{context} must be a string list")
    return value


def _integer_scalar(value: Any, *, context: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)", value) is None:
        raise GovernanceError(f"{context} must be a non-negative integer")
    return int(value)


def _require_exact_keys(
    value: Any,
    expected: set[str],
    *,
    context: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GovernanceError(f"{context} must be a mapping")
    actual = set(value)
    if actual != expected:
        raise GovernanceError(
            f"{context} keys differ exactly; "
            f"missing={sorted(expected - actual)!r}, "
            f"extra={sorted(actual - expected)!r}"
        )
    return value


def _normalized_dependabot(document: YamlDocument) -> JsonObject:
    """Normalize the complete Dependabot contract while preserving exact sets."""
    payload = _node_to_data(document.root)
    _require_exact_keys(
        payload,
        {"version", "updates"},
        context=str(document.path),
    )
    version = _integer_scalar(
        payload.get("version"),
        context=f"{document.path}: version",
    )
    updates = payload.get("updates")
    if not isinstance(updates, list):
        raise GovernanceError(f"{document.path}: updates must be a list")

    normalized_updates: dict[str, JsonObject] = {}
    for update_index, update in enumerate(updates):
        update_context = f"{document.path}: updates[{update_index}]"
        update = _require_exact_keys(
            update,
            {
                "package-ecosystem",
                "directory",
                "schedule",
                "open-pull-requests-limit",
                "cooldown",
                "groups",
            },
            context=update_context,
        )
        ecosystem = update.get("package-ecosystem")
        directory = update.get("directory")
        if not isinstance(ecosystem, str) or not isinstance(directory, str):
            raise GovernanceError(
                f"{document.path}: update ecosystem and directory must be strings"
            )
        identity = f"{ecosystem}:{directory}"
        if identity in normalized_updates:
            raise GovernanceError(
                f"{document.path}: duplicate Dependabot update {identity!r}"
            )

        schedule = _require_exact_keys(
            update.get("schedule"),
            {"interval", "day", "time", "timezone"},
            context=f"{update_context} schedule",
        )
        if not all(isinstance(value, str) for value in schedule.values()):
            raise GovernanceError(
                f"{update_context} schedule values must all be strings"
            )

        cooldown = update.get("cooldown")
        if not isinstance(cooldown, dict):
            raise GovernanceError(f"{update_context} cooldown must be a mapping")
        allowed_cooldown_keys = {
            "default-days",
            "semver-major-days",
            "semver-minor-days",
            "semver-patch-days",
        }
        unknown_cooldown_keys = set(cooldown) - allowed_cooldown_keys
        if unknown_cooldown_keys:
            raise GovernanceError(
                f"{update_context} cooldown has unsupported keys "
                f"{sorted(unknown_cooldown_keys)!r}"
            )
        normalized_cooldown = {
            key.replace("-", "_"): _integer_scalar(
                value,
                context=f"{update_context} cooldown.{key}",
            )
            for key, value in cooldown.items()
        }

        groups = update.get("groups")
        if not isinstance(groups, dict):
            raise GovernanceError(
                f"{document.path}: groups for {ecosystem}:{directory} must be a mapping"
            )
        normalized_groups: dict[str, JsonObject] = {}
        for group_name, group in groups.items():
            if not isinstance(group_name, str) or not isinstance(group, dict):
                raise GovernanceError(
                    f"{document.path}: Dependabot group must be a named mapping"
                )
            group_key = f"{identity}:{group_name}"
            if group_name in normalized_groups:
                raise GovernanceError(
                    f"{document.path}: duplicate Dependabot group {group_key!r}"
                )
            required_group_keys = {"applies-to", "patterns", "update-types"}
            allowed_group_keys = {*required_group_keys, "exclude-patterns"}
            actual_group_keys = set(group)
            missing_group_keys = required_group_keys - actual_group_keys
            extra_group_keys = actual_group_keys - allowed_group_keys
            if missing_group_keys or extra_group_keys:
                raise GovernanceError(
                    f"{document.path}: {group_key} keys differ; "
                    f"missing={sorted(missing_group_keys)!r}, "
                    f"extra={sorted(extra_group_keys)!r}"
                )
            applies_to = group.get("applies-to")
            if not isinstance(applies_to, str):
                raise GovernanceError(
                    f"{document.path}: {group_key} applies-to must be a string"
                )
            normalized_groups[group_name] = {
                "applies_to": applies_to,
                "patterns": sorted(
                    _string_list(
                        group.get("patterns"),
                        context=f"{document.path}: {group_key} patterns",
                    )
                ),
                "exclude_patterns": sorted(
                    _string_list(
                        group.get("exclude-patterns", []),
                        context=f"{document.path}: {group_key} exclude-patterns",
                    )
                ),
                "update_types": sorted(
                    _string_list(
                        group.get("update-types"),
                        context=f"{document.path}: {group_key} update-types",
                    )
                ),
            }
        normalized_updates[identity] = {
            "package_ecosystem": ecosystem,
            "directory": directory,
            "schedule": schedule,
            "open_pull_requests_limit": _integer_scalar(
                update.get("open-pull-requests-limit"),
                context=f"{update_context} open-pull-requests-limit",
            ),
            "cooldown": normalized_cooldown,
            "groups": normalized_groups,
        }
    return {"version": version, "updates": normalized_updates}


def _canonical_dependabot_policy(policy: JsonObject) -> JsonObject:
    updates = policy["updates"]
    normalized_updates: dict[str, JsonObject] = {}
    for update in updates:
        identity = f"{update['package_ecosystem']}:{update['directory']}"
        normalized_updates[identity] = {
            "package_ecosystem": update["package_ecosystem"],
            "directory": update["directory"],
            "schedule": update["schedule"],
            "open_pull_requests_limit": update["open_pull_requests_limit"],
            "cooldown": update["cooldown"],
            "groups": {
                group["name"]: {
                    "applies_to": group["applies_to"],
                    "patterns": sorted(group["patterns"]),
                    "exclude_patterns": sorted(group["exclude_patterns"]),
                    "update_types": sorted(group["update_types"]),
                }
                for group in update["groups"]
            },
        }
    return {"version": policy["version"], "updates": normalized_updates}


def _normalized_dependabot_groups(document: YamlDocument) -> dict[str, JsonObject]:
    groups: dict[str, JsonObject] = {}
    for identity, update in _normalized_dependabot(document)["updates"].items():
        for name, group in update["groups"].items():
            groups[f"{identity}:{name}"] = group
    return groups


def validate_dependabot_configuration(path: Path, policy: JsonObject) -> list[str]:
    """Compare the complete Dependabot file with the reviewed baseline."""
    policy_dependabot = policy.get("dependabot")
    if not _json_exact(policy_dependabot, EXPECTED_DEPENDABOT):
        return [
            "local: policy.dependabot differs from the complete reviewed "
            f"baseline; actual={policy_dependabot!r}, "
            f"expected={EXPECTED_DEPENDABOT!r}"
        ]
    try:
        actual = _normalized_dependabot(load_yaml_document(path))
    except GovernanceError as exc:
        return [f"local: invalid Dependabot YAML: {exc}"]
    expected = _canonical_dependabot_policy(EXPECTED_DEPENDABOT)
    if _json_exact(actual, expected):
        return []

    errors: list[str] = []
    if actual.get("version") != expected["version"]:
        errors.append(
            f"local: Dependabot version is {actual.get('version')!r}; "
            f"expected {expected['version']!r}"
        )
    actual_updates = actual.get("updates", {})
    expected_updates = expected["updates"]
    missing = sorted(expected_updates.keys() - actual_updates.keys())
    extra = sorted(actual_updates.keys() - expected_updates.keys())
    if missing or extra:
        errors.append(
            "local: Dependabot update identities differ exactly; "
            f"missing={missing!r}, extra={extra!r}"
        )
    for key in sorted(expected_updates.keys() & actual_updates.keys()):
        if not _json_exact(actual_updates[key], expected_updates[key]):
            errors.append(
                f"local: Dependabot update {key!r} is {actual_updates[key]!r}; "
                f"expected {expected_updates[key]!r}"
            )
    return errors


def validate_dependabot_grouping(path: Path, policy: JsonObject) -> list[str]:
    """Backward-compatible name for the complete Dependabot validator."""
    return validate_dependabot_configuration(path, policy)


def _required_check_contracts(main: JsonObject) -> list[RequiredCheckContract]:
    required_checks = main.get("required_checks")
    if not _json_exact(required_checks, EXPECTED_REQUIRED_CHECKS):
        raise GovernanceError(
            "policy.main.required_checks differs from the complete reviewed "
            f"baseline; actual={required_checks!r}, "
            f"expected={EXPECTED_REQUIRED_CHECKS!r}"
        )
    if not isinstance(required_checks, list):
        raise GovernanceError("policy.main.required_checks must be a list")
    contracts: list[RequiredCheckContract] = []
    for index, check in enumerate(required_checks):
        if not isinstance(check, dict) or set(check) != {
            "context",
            "integration_id",
            "workflow",
            "job",
            "triggers",
        }:
            raise GovernanceError(
                f"policy.main.required_checks[{index}] must contain exactly "
                "context, integration_id, workflow, job, and triggers"
            )
        context = check["context"]
        integration_id = check["integration_id"]
        workflow = check["workflow"]
        job = check["job"]
        triggers = check["triggers"]
        if not isinstance(context, str) or not context:
            raise GovernanceError(
                f"policy.main.required_checks[{index}].context must be non-empty"
            )
        if (
            not isinstance(integration_id, int)
            or isinstance(integration_id, bool)
            or integration_id <= 0
        ):
            raise GovernanceError(
                f"policy.main.required_checks[{index}].integration_id "
                "must be a positive integer"
            )
        if (
            not isinstance(workflow, str)
            or Path(workflow).parent != Path(".github/workflows")
            or Path(workflow).suffix not in {".yml", ".yaml"}
        ):
            raise GovernanceError(
                f"policy.main.required_checks[{index}].workflow must be a "
                "top-level .github/workflows YAML path"
            )
        if not isinstance(job, str) or not job:
            raise GovernanceError(
                f"policy.main.required_checks[{index}].job must be non-empty"
            )
        if triggers != REQUIRED_CHECK_TRIGGERS:
            raise GovernanceError(
                f"policy.main.required_checks[{index}].triggers must be "
                f"{REQUIRED_CHECK_TRIGGERS!r}"
            )
        contracts.append(
            RequiredCheckContract(
                context=context,
                integration_id=integration_id,
                workflow=workflow,
                job=job,
                triggers=triggers,
            )
        )
    bindings = [(contract.context, contract.integration_id) for contract in contracts]
    duplicate_bindings = [
        binding for binding, count in Counter(bindings).items() if count > 1
    ]
    duplicate_contexts = [
        context
        for context, count in Counter(context for context, _ in bindings).items()
        if count > 1
    ]
    if duplicate_bindings or duplicate_contexts:
        raise GovernanceError(
            "policy.main.required_checks contains duplicate bindings or "
            f"contexts: bindings={duplicate_bindings!r}, "
            f"contexts={duplicate_contexts!r}"
        )
    emitters = [(contract.workflow, contract.job) for contract in contracts]
    duplicate_emitters = [
        emitter for emitter, count in Counter(emitters).items() if count > 1
    ]
    if duplicate_emitters:
        raise GovernanceError(
            "policy.main.required_checks contains duplicate emitters: "
            f"{duplicate_emitters!r}"
        )
    return contracts


def _required_check_bindings(main: JsonObject) -> list[tuple[str, int]]:
    return [
        (contract.context, contract.integration_id)
        for contract in _required_check_contracts(main)
    ]


def _main_ruleset_contract(policy: JsonObject) -> JsonObject:
    repository = policy.get("repository")
    main = policy.get("main")
    if repository != EXPECTED_REPOSITORY or type(repository) is not str:
        raise GovernanceError(f"policy.repository must remain {EXPECTED_REPOSITORY!r}")
    if not isinstance(main, dict):
        raise GovernanceError("policy.main must be an object")
    ruleset = main.get("ruleset")
    expected = {
        "name": "main",
        "target": "branch",
        "source_type": "Repository",
        "source": EXPECTED_REPOSITORY,
        "enforcement": "active",
        "conditions": MAIN_RULESET_CONDITIONS,
    }
    if not _json_exact(ruleset, expected):
        raise GovernanceError(
            f"policy.main.ruleset is {ruleset!r}; expected {expected!r}"
        )
    return ruleset


def _pull_request_parameters(main: JsonObject) -> JsonObject:
    parameters = main.get("pull_request_parameters")
    if not _json_exact(parameters, SOLO_PULL_REQUEST_PARAMETERS):
        raise GovernanceError(
            "policy.main.pull_request_parameters must keep the complete "
            f"solo-owner contract {SOLO_PULL_REQUEST_PARAMETERS!r}"
        )
    return parameters


def _status_check_parameters(main: JsonObject) -> JsonObject:
    parameters = main.get("required_status_checks_parameters")
    if not _json_exact(parameters, MAIN_STATUS_CHECK_PARAMETERS):
        raise GovernanceError(
            "policy.main.required_status_checks_parameters must be "
            f"{MAIN_STATUS_CHECK_PARAMETERS!r}"
        )
    return parameters


def validate_local(root: Path, policy: JsonObject) -> list[str]:
    """Validate contracts represented in the repository itself."""
    errors: list[str] = []
    workflows = workflow_files(root)
    if not workflows:
        return ["local: no workflow files found"]

    documents, reference_errors = validate_repository_yaml_references(root)
    errors.extend(reference_errors)
    workflow_paths = {path.resolve() for path in workflows}

    repository = policy.get("repository")
    if repository != EXPECTED_REPOSITORY or type(repository) is not str:
        errors.append(f"local: policy.repository must remain {EXPECTED_REPOSITORY!r}")
    api_version = policy.get("api_version")
    if api_version != EXPECTED_API_VERSION or type(api_version) is not str:
        errors.append(f"local: policy.api_version must remain {EXPECTED_API_VERSION!r}")

    main = policy.get("main")
    if not isinstance(main, dict):
        errors.append("local: policy.main must be an object")
        return errors
    main_ref = main.get("ref")
    if main_ref != EXPECTED_MAIN_REF or type(main_ref) is not str:
        errors.append(f"local: policy.main.ref must remain {EXPECTED_MAIN_REF!r}")
    active_ruleset_count = main.get("active_ruleset_count")
    if active_ruleset_count != 1 or type(active_ruleset_count) is not int:
        errors.append(
            "local: policy.main.active_ruleset_count must remain 1 so rules "
            "cannot be distributed"
        )
    if main.get("bypass_actors") != []:
        errors.append("local: policy.main.bypass_actors must remain an empty list")
    if main.get("legacy_branch_protection") != "absent":
        errors.append(
            "local: policy.main.legacy_branch_protection must remain 'absent'"
        )
    rule_types = main.get("rule_types")
    if not _json_exact(rule_types, MAIN_RULE_TYPES):
        errors.append(f"local: policy.main.rule_types must remain {MAIN_RULE_TYPES!r}")
    try:
        _main_ruleset_contract(policy)
        _pull_request_parameters(main)
        _status_check_parameters(main)
        required_contracts = _required_check_contracts(main)
    except GovernanceError as exc:
        errors.append(f"local: {exc}")
        return errors

    names: list[str] = []
    for path, document in documents.items():
        if path not in workflow_paths:
            continue
        try:
            names.extend(workflow_job_names(document))
        except GovernanceError as exc:
            relative = path.relative_to(root.resolve())
            errors.append(f"local: invalid workflow {relative}: {exc}")
    for contract in required_contracts:
        context = contract.context
        occurrences = names.count(context)
        if occurrences != 1:
            errors.append(
                f"local: required check {context!r} must be emitted by exactly "
                f"one job, found {occurrences}"
            )
        emitter_path = (root.resolve() / contract.workflow).resolve()
        document = documents.get(emitter_path)
        if document is None:
            errors.append(
                f"local: required check {context!r} workflow is missing or "
                f"invalid: {contract.workflow}"
            )
            continue
        try:
            jobs = _workflow_jobs(document)
            job = jobs.get(contract.job)
            if job is None:
                errors.append(
                    f"local: required check {context!r} emitter job "
                    f"{contract.job!r} is missing from {contract.workflow}"
                )
                continue
            name = _mapping_value(job, "name")
            actual_name = (
                _scalar_value(
                    name,
                    context=(f"{contract.workflow}: job {contract.job!r} name"),
                )
                if name is not None
                else None
            )
            if actual_name != context:
                errors.append(
                    f"local: required check emitter "
                    f"{contract.workflow}:{contract.job} is named "
                    f"{actual_name!r}; expected {context!r}"
                )
            actual_triggers = workflow_trigger_config(document)
            if actual_triggers != contract.triggers:
                errors.append(
                    f"local: required check {context!r} triggers are "
                    f"{actual_triggers!r}; expected {contract.triggers!r}"
                )
            errors.extend(
                f"local: {error}"
                for error in validate_required_job_graph(
                    document,
                    contract.job,
                )
            )
            errors.extend(
                f"local: {error}"
                for error in validate_required_execution_safety(
                    root,
                    documents,
                    document,
                    contract.job,
                )
            )
        except GovernanceError as exc:
            errors.append(f"local: required check {context!r}: {exc}")

    ci_workflow = (root.resolve() / AGENT_CI_WORKFLOW).resolve()
    if ci_workflow in documents:
        try:
            errors.extend(
                f"local: {error}"
                for error in validate_agent_ci_resolution(documents[ci_workflow])
            )
        except GovernanceError as exc:
            errors.append(f"local: invalid ci/agent resolution contract: {exc}")

    required_files = (
        ".github/CODEOWNERS",
        ".github/dependabot.yml",
        ".github/pull_request_template.md",
    )
    for relative in required_files:
        if not (root / relative).is_file():
            errors.append(f"local: required governance file is missing: {relative}")

    dependency_audit = (root / ".github/workflows/dependency-audit.yml").resolve()
    if dependency_audit in documents:
        try:
            events = workflow_events(documents[dependency_audit])
            expected_events = {"schedule", "workflow_dispatch"}
            if events != expected_events:
                errors.append(
                    "local: dependency audit events must be schedule and "
                    f"workflow_dispatch only, found {sorted(events)!r}"
                )
            if any(
                _nodes_for_mapping_key(
                    documents[dependency_audit].root,
                    "continue-on-error",
                )
            ):
                errors.append(
                    "local: dependency audit must fail honestly; "
                    "continue-on-error is forbidden"
                )
        except GovernanceError as exc:
            errors.append(f"local: invalid dependency audit workflow: {exc}")

    dependabot = root / ".github/dependabot.yml"
    if dependabot.is_file():
        errors.extend(validate_dependabot_configuration(dependabot, policy))

    actions_policy = policy.get("actions")
    if not _json_exact(actions_policy, EXPECTED_ACTIONS):
        errors.append(
            "local: policy.actions differs exactly from the reviewed Actions "
            f"object; actual={actions_policy!r}, expected={EXPECTED_ACTIONS!r}"
        )

    environments_policy = policy.get("environments")
    if not _json_exact(environments_policy, EXPECTED_ENVIRONMENTS):
        errors.append(
            "local: policy.environments differs from the complete reviewed "
            f"Preview/Production payload; actual={environments_policy!r}, "
            f"expected={EXPECTED_ENVIRONMENTS!r}"
        )

    return errors


def _gh_api(repository: str, api_version: str, endpoint: str) -> ApiResponse:
    resource = f"repos/{repository}/{endpoint}" if endpoint else f"repos/{repository}"
    command = [
        "gh",
        "api",
        "--include",
        "--method",
        "GET",
        "-H",
        f"X-GitHub-Api-Version: {api_version}",
        resource,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        normalized = result.stdout.replace("\r\n", "\n")
        if "\n\n" not in normalized:
            detail = result.stderr.strip() or result.stdout.strip()
            raise GovernanceError(
                f"GitHub API GET {endpoint!r} omitted response headers: {detail}"
            )
        header_text, body = normalized.split("\n\n", 1)
        status_line = header_text.splitlines()[0]
        status_match = re.match(r"^HTTP/\S+\s+(\d{3})\b", status_line)
        if status_match is None:
            raise GovernanceError(
                f"GitHub API GET {endpoint!r} returned invalid status line "
                f"{status_line!r}"
            )
        status = int(status_match.group(1))
        headers: dict[str, str] = {}
        for line in header_text.splitlines()[1:]:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            key = name.strip().lower()
            normalized_value = value.strip()
            headers[key] = (
                f"{headers[key]}, {normalized_value}"
                if key in headers
                else normalized_value
            )
        selected_version = headers.get("x-github-api-version-selected")
        if selected_version != api_version:
            raise GovernanceError(
                f"GitHub API GET {endpoint!r} selected version "
                f"{selected_version!r}; expected {api_version!r}"
            )
        stripped_body = body.strip()
        if status == 204:
            if stripped_body:
                raise GovernanceError(
                    f"GitHub API GET {endpoint!r} returned a body for HTTP 204"
                )
            payload = None
        else:
            if not stripped_body:
                raise GovernanceError(
                    f"GitHub API GET {endpoint!r} returned an empty body "
                    f"for HTTP {status}"
                )
            payload = json.loads(body)
        return ApiResponse(
            payload=payload,
            headers=headers,
            status=status,
        )
    except FileNotFoundError as exc:
        raise GovernanceError("gh is required for --live verification") from exc
    except json.JSONDecodeError as exc:
        raise GovernanceError(
            f"GitHub API GET {endpoint!r} returned invalid JSON"
        ) from exc


def _api_response(value: Any) -> ApiResponse:
    if isinstance(value, ApiResponse):
        return value
    return ApiResponse(payload=value, headers={})


def _api_payload(api_get: ApiGet, endpoint: str) -> Any:
    response = _api_response(api_get(endpoint))
    if not 200 <= response.status < 300:
        raise GovernanceError(
            f"GitHub API GET {endpoint!r} returned HTTP {response.status}"
        )
    return response.payload


def _single_page_items(
    api_get: ApiGet,
    endpoint: str,
    *,
    collection_key: str | None = None,
    require_total_count: bool = False,
) -> list[Any]:
    if "per_page=100" not in endpoint or "page=1" not in endpoint:
        raise GovernanceError(
            f"paginated GitHub endpoint lacks explicit first-page bounds: {endpoint}"
        )
    response = _api_response(api_get(endpoint))
    if not 200 <= response.status < 300:
        raise GovernanceError(
            f"GitHub API GET {endpoint!r} returned HTTP {response.status}"
        )
    link = response.headers.get("link", "").strip()
    if link:
        raise GovernanceError(
            f"GitHub API {endpoint!r} requires pagination; expected one exact page"
        )
    payload = response.payload
    if collection_key is None:
        items = payload
    else:
        if not isinstance(payload, dict):
            raise GovernanceError(f"GitHub API {endpoint!r} response must be an object")
        items = payload.get(collection_key)
    if not isinstance(items, list):
        raise GovernanceError(f"GitHub API {endpoint!r} collection must be a list")
    if len(items) > 100:
        raise GovernanceError(
            f"GitHub API {endpoint!r} returned more than per_page=100"
        )
    if require_total_count:
        total_count = payload.get("total_count")
        if (
            not isinstance(total_count, int)
            or isinstance(total_count, bool)
            or total_count != len(items)
        ):
            raise GovernanceError(
                f"GitHub API {endpoint!r} total_count is {total_count!r}, "
                f"but page 1 contains {len(items)} items"
            )
    return items


def _ref_pattern_matches(
    pattern: str,
    candidate_ref: str,
    default_ref: str,
) -> bool:
    if pattern == "~ALL":
        return True
    if pattern == "~DEFAULT_BRANCH":
        return candidate_ref == default_ref
    return fnmatch.fnmatchcase(candidate_ref, pattern)


def _ruleset_targets_main(
    ruleset: JsonObject,
    main_ref: str,
    default_ref: str,
) -> bool:
    if ruleset.get("target") != "branch":
        return False
    conditions = ruleset.get("conditions")
    if not isinstance(conditions, dict):
        raise GovernanceError("branch ruleset conditions must be an object")
    ref_name = conditions.get("ref_name")
    if not isinstance(ref_name, dict):
        raise GovernanceError("branch ruleset ref_name condition must be an object")
    include = ref_name.get("include")
    exclude = ref_name.get("exclude", [])
    if (
        not isinstance(include, list)
        or not include
        or not all(isinstance(item, str) for item in include)
        or not isinstance(exclude, list)
        or not all(isinstance(item, str) for item in exclude)
    ):
        raise GovernanceError(
            "branch ruleset ref_name include/exclude must be string lists "
            "and include must not be empty"
        )
    includes_main = any(
        _ref_pattern_matches(pattern, main_ref, default_ref) for pattern in include
    )
    excludes_main = any(
        _ref_pattern_matches(pattern, main_ref, default_ref) for pattern in exclude
    )
    return includes_main and not excludes_main


def _rules(rulesets: Iterable[JsonObject], rule_type: str) -> list[JsonObject]:
    matches: list[JsonObject] = []
    for ruleset in rulesets:
        rules = ruleset.get("rules")
        if not isinstance(rules, list):
            raise GovernanceError("GitHub ruleset rules must be a list")
        for rule in rules:
            if not isinstance(rule, dict) or not isinstance(rule.get("type"), str):
                raise GovernanceError("GitHub ruleset contains an invalid rule")
            if rule["type"] == rule_type:
                matches.append(rule)
    return matches


def _verify_main_rulesets(
    policy: JsonObject,
    rulesets: list[JsonObject],
    default_ref: str,
) -> list[str]:
    errors: list[str] = []
    main = policy["main"]
    expected_ruleset = _main_ruleset_contract(policy)
    expected_pull_request = _pull_request_parameters(main)
    expected_status_base = _status_check_parameters(main)
    main_ref = EXPECTED_MAIN_REF
    targeting = [
        ruleset
        for ruleset in rulesets
        if _ruleset_targets_main(ruleset, main_ref, default_ref)
    ]
    inactive = [
        ruleset for ruleset in targeting if ruleset.get("enforcement") != "active"
    ]
    if inactive:
        states = [
            {
                "id": ruleset.get("id"),
                "name": ruleset.get("name"),
                "enforcement": ruleset.get("enforcement"),
            }
            for ruleset in inactive
        ]
        errors.append(
            f"external: inactive branch rulesets target {main_ref}: {states!r}"
        )

    applicable = [
        ruleset for ruleset in targeting if ruleset.get("enforcement") == "active"
    ]
    expected_count = main["active_ruleset_count"]
    if len(applicable) != expected_count:
        errors.append(
            f"external: {len(applicable)} active branch rulesets target "
            f"{main_ref}; expected {expected_count} so rules cannot be "
            "disabled or distributed"
        )

    expected_bypass = main["bypass_actors"]
    for ruleset in applicable:
        bypass_actors = ruleset.get("bypass_actors")
        if not isinstance(bypass_actors, list):
            errors.append(
                "external: active main ruleset bypass_actors must be an explicit list"
            )
        elif bypass_actors != expected_bypass:
            errors.append(
                "external: active main ruleset bypass actors are "
                f"{bypass_actors!r}; expected {expected_bypass!r}"
            )

    if len(applicable) != 1:
        return errors

    actual_ruleset = {key: applicable[0].get(key) for key in expected_ruleset}
    if not _json_exact(actual_ruleset, expected_ruleset):
        errors.append(
            "external: active main ruleset identity/target differs exactly; "
            f"actual={actual_ruleset!r}, expected={expected_ruleset!r}"
        )

    rules = applicable[0].get("rules")
    if not isinstance(rules, list) or any(
        not isinstance(rule, dict) or not isinstance(rule.get("type"), str)
        for rule in rules
    ):
        raise GovernanceError("active main ruleset contains invalid rules")
    actual_rule_types = [rule["type"] for rule in rules]
    expected_rule_types = main["rule_types"]
    missing_rule_types = sorted(
        (Counter(expected_rule_types) - Counter(actual_rule_types)).elements()
    )
    extra_rule_types = sorted(
        (Counter(actual_rule_types) - Counter(expected_rule_types)).elements()
    )
    duplicate_rule_types = sorted(
        rule_type
        for rule_type, count in Counter(actual_rule_types).items()
        if count > 1
    )
    if missing_rule_types or extra_rule_types or duplicate_rule_types:
        errors.append(
            "external: main ruleset rule types differ exactly; "
            f"missing={missing_rule_types!r}, extra={extra_rule_types!r}, "
            f"duplicates={duplicate_rule_types!r}"
        )

    pull_request_rules = _rules(applicable, "pull_request")
    expected_reviews = expected_pull_request["required_approving_review_count"]
    for rule in pull_request_rules:
        parameters = rule.get("parameters")
        if not isinstance(parameters, dict):
            errors.append(
                "external: main pull-request rule parameters must be an object"
            )
            continue
        if not _json_exact(parameters, expected_pull_request):
            errors.append(
                "external: main pull-request parameters differ exactly; "
                f"actual={parameters!r}, expected={expected_pull_request!r}"
            )
        actual_reviews = parameters.get("required_approving_review_count")
        if actual_reviews != expected_reviews or type(actual_reviews) is not type(
            expected_reviews
        ):
            errors.append(
                "external: main pull-request rule requires "
                f"{actual_reviews!r} approvals; expected {expected_reviews}"
            )
        if parameters.get("require_code_owner_review") is not False:
            errors.append(
                "external: Code Owner review must be explicitly disabled; "
                "keep CODEOWNERS advisory for this solo repository"
            )
        if parameters.get("require_last_push_approval") is not False:
            errors.append(
                "external: last-push approval must be explicitly disabled "
                "because it can deadlock this solo repository"
            )

    status_rules = _rules(applicable, "required_status_checks")
    expected_bindings = _required_check_bindings(main)
    expected_status_parameters = {
        "do_not_enforce_on_create": expected_status_base["do_not_enforce_on_create"],
        "required_status_checks": [
            {"context": context, "integration_id": integration_id}
            for context, integration_id in expected_bindings
        ],
        "strict_required_status_checks_policy": expected_status_base[
            "strict_required_status_checks_policy"
        ],
    }
    actual_bindings: list[tuple[str, int]] = []
    strict_enabled = False
    for rule in status_rules:
        parameters = rule.get("parameters")
        if not isinstance(parameters, dict):
            errors.append(
                "external: required-status-check parameters must be an object"
            )
            continue
        if not _json_exact(parameters, expected_status_parameters):
            errors.append(
                "external: main required-status-check parameters differ exactly; "
                f"actual={parameters!r}, expected={expected_status_parameters!r}"
            )
        if (
            parameters.get("do_not_enforce_on_create")
            is not expected_status_base["do_not_enforce_on_create"]
        ):
            errors.append(
                "external: required status checks do_not_enforce_on_create "
                f"is {parameters.get('do_not_enforce_on_create')!r}; expected "
                f"{expected_status_base['do_not_enforce_on_create']!r}"
            )
        checks = parameters.get("required_status_checks")
        if not isinstance(checks, list):
            errors.append("external: required_status_checks must be an explicit list")
            continue
        malformed = [
            check
            for check in checks
            if not isinstance(check, dict)
            or not isinstance(check.get("context"), str)
            or not check.get("context")
            or not isinstance(check.get("integration_id"), int)
            or isinstance(check.get("integration_id"), bool)
            or check["integration_id"] <= 0
        ]
        if malformed:
            errors.append(
                "external: required_status_checks contains entries without a "
                "valid context/integration_id binding: "
                f"{malformed!r}"
            )
        actual_bindings.extend(
            (check["context"], check["integration_id"])
            for check in checks
            if check not in malformed
        )
        strict_enabled = (
            parameters.get("strict_required_status_checks_policy")
            is expected_status_base["strict_required_status_checks_policy"]
        )

    missing_bindings = sorted(
        (Counter(expected_bindings) - Counter(actual_bindings)).elements()
    )
    extra_bindings = sorted(
        (Counter(actual_bindings) - Counter(expected_bindings)).elements()
    )
    duplicate_bindings = sorted(
        binding for binding, count in Counter(actual_bindings).items() if count > 1
    )
    duplicate_contexts = sorted(
        context
        for context, count in Counter(context for context, _ in actual_bindings).items()
        if count > 1
    )
    if missing_bindings or extra_bindings or duplicate_bindings or duplicate_contexts:
        errors.append(
            "external: main required check bindings differ exactly; "
            f"missing={missing_bindings!r}, extra={extra_bindings!r}, "
            f"duplicates={duplicate_bindings!r}, "
            f"duplicate_contexts={duplicate_contexts!r}"
        )
    if not strict_enabled:
        errors.append(
            "external: strict required status checks differ from the manifest contract"
        )

    return errors


def _reviewer_identity(reviewer: JsonObject, *, context: str) -> JsonObject:
    reviewer_type = reviewer.get("type")
    if reviewer_type not in {"User", "Team"}:
        raise GovernanceError(f"{context} reviewer type must be 'User' or 'Team'")
    nested = reviewer.get("reviewer")
    source = nested if isinstance(nested, dict) else reviewer
    identity_key = "login" if reviewer_type == "User" else "slug"
    identity = source.get(identity_key)
    if not isinstance(identity, str):
        raise GovernanceError(
            f"{context} {reviewer_type} reviewer needs {identity_key!r}"
        )
    return {"type": reviewer_type, "name": identity}


def _normalize_environment_protection_rules(
    rules: Any,
    *,
    context: str,
) -> list[JsonObject]:
    if not isinstance(rules, list):
        raise GovernanceError(f"{context} protection_rules must be a list")
    normalized: list[JsonObject] = []
    for index, rule in enumerate(rules):
        item_context = f"{context} protection_rules[{index}]"
        if not isinstance(rule, dict) or not isinstance(rule.get("type"), str):
            raise GovernanceError(f"{item_context} must be a typed object")
        rule_type = rule["type"]
        if rule_type == "branch_policy":
            normalized.append({"type": rule_type})
            continue
        if rule_type == "required_reviewers":
            prevent_self_review = rule.get("prevent_self_review")
            if not isinstance(prevent_self_review, bool):
                raise GovernanceError(
                    f"{item_context} prevent_self_review must be explicit"
                )
            reviewers = rule.get("reviewers")
            if not isinstance(reviewers, list):
                raise GovernanceError(
                    f"{item_context} reviewers must be an explicit list"
                )
            identities: list[JsonObject] = []
            for reviewer in reviewers:
                if not isinstance(reviewer, dict):
                    raise GovernanceError(
                        f"{item_context} reviewers must contain objects"
                    )
                identities.append(_reviewer_identity(reviewer, context=item_context))
            normalized.append(
                {
                    "type": rule_type,
                    "prevent_self_review": prevent_self_review,
                    "reviewers": sorted(
                        identities,
                        key=lambda value: (value["type"], value["name"]),
                    ),
                }
            )
            continue
        if rule_type == "wait_timer":
            wait_timer = rule.get("wait_timer")
            if not isinstance(wait_timer, int):
                raise GovernanceError(f"{item_context} wait_timer must be an integer")
            normalized.append({"type": rule_type, "wait_timer": wait_timer})
            continue
        raise GovernanceError(
            f"{item_context} has unsupported protection type {rule_type!r}"
        )
    return sorted(normalized, key=lambda value: json.dumps(value, sort_keys=True))


def _repository_merge_methods(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        raise GovernanceError("GitHub repository response must be an object")
    settings = {
        "merge": payload.get("allow_merge_commit"),
        "squash": payload.get("allow_squash_merge"),
        "rebase": payload.get("allow_rebase_merge"),
    }
    if any(type(value) is not bool for value in settings.values()):
        raise GovernanceError(
            "GitHub repository merge-method settings must be explicit booleans"
        )
    return [method for method in MERGE_METHODS if settings[method]]


def verify_live(policy: JsonObject, api_get: ApiGet) -> list[str]:
    """Read GitHub settings and compare them with the checked-in policy."""
    errors: list[str] = []
    repository_settings = _api_payload(api_get, "")
    if not isinstance(repository_settings, dict):
        raise GovernanceError("GitHub repository response must be an object")
    full_name = repository_settings.get("full_name")
    if full_name != EXPECTED_REPOSITORY or type(full_name) is not str:
        errors.append(
            f"external: repository full_name is {full_name!r}; "
            f"expected {EXPECTED_REPOSITORY!r}"
        )
    default_branch = repository_settings.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        raise GovernanceError(
            "GitHub repository default_branch must be a non-empty string"
        )
    if default_branch != EXPECTED_DEFAULT_BRANCH:
        errors.append(
            f"external: repository default_branch is {default_branch!r}; "
            f"expected {EXPECTED_DEFAULT_BRANCH!r}"
        )
    default_ref = f"refs/heads/{default_branch}"
    actual_merge_methods = _repository_merge_methods(repository_settings)
    expected_merge_methods = _pull_request_parameters(policy["main"])[
        "allowed_merge_methods"
    ]
    if not _json_exact(actual_merge_methods, expected_merge_methods):
        errors.append(
            "external: repository merge methods are "
            f"{actual_merge_methods!r}; expected {expected_merge_methods!r} "
            "to match the main pull-request rule"
        )

    security_and_analysis = repository_settings.get("security_and_analysis")
    if not isinstance(security_and_analysis, dict):
        raise GovernanceError(
            "GitHub repository response is missing security_and_analysis; "
            "the live verifier requires repository-admin read access"
        )
    dependabot_security_updates = security_and_analysis.get(
        "dependabot_security_updates"
    )
    if not isinstance(dependabot_security_updates, dict):
        raise GovernanceError(
            "GitHub repository response is missing "
            "security_and_analysis.dependabot_security_updates; "
            "the live verifier requires repository-admin read access"
        )
    repository_security_updates_status = dependabot_security_updates.get("status")
    if not isinstance(repository_security_updates_status, str):
        raise GovernanceError(
            "GitHub repository response is missing a string "
            "security_and_analysis.dependabot_security_updates.status; "
            "the live verifier requires repository-admin read access"
        )

    vulnerability_alerts = _api_response(api_get("vulnerability-alerts"))
    if vulnerability_alerts.status == 204:
        if vulnerability_alerts.payload is not None:
            raise GovernanceError(
                "Dependabot vulnerability-alerts HTTP 204 response must have no body"
            )
    elif vulnerability_alerts.status == 404:
        if (
            not isinstance(vulnerability_alerts.payload, dict)
            or vulnerability_alerts.payload.get("message")
            != "Vulnerability alerts are disabled."
        ):
            raise GovernanceError(
                "Dependabot vulnerability-alerts 404 did not confirm that "
                "alerts are disabled"
            )
        errors.append(
            "external: Dependabot vulnerability alerts are disabled; expected enabled"
        )
    else:
        raise GovernanceError(
            "Dependabot vulnerability-alerts query returned HTTP "
            f"{vulnerability_alerts.status}"
        )

    automated_security_fixes_response = _api_response(
        api_get("automated-security-fixes")
    )
    if automated_security_fixes_response.status != 200:
        raise GovernanceError(
            "Dependabot automated-security-fixes query returned HTTP "
            f"{automated_security_fixes_response.status}"
        )
    automated_security_fixes = automated_security_fixes_response.payload
    if (
        not _json_exact(
            automated_security_fixes,
            EXPECTED_AUTOMATED_SECURITY_FIXES,
        )
        or repository_security_updates_status
        != EXPECTED_DEPENDABOT_SECURITY_UPDATES_STATUS
    ):
        errors.append(
            "external: Dependabot security updates differ exactly; "
            f"automated_security_fixes={automated_security_fixes!r}, "
            f"repository_status={repository_security_updates_status!r}; "
            "expected automated_security_fixes="
            f"{EXPECTED_AUTOMATED_SECURITY_FIXES!r}, "
            "repository_status="
            f"{EXPECTED_DEPENDABOT_SECURITY_UPDATES_STATUS!r}"
        )

    summaries = _single_page_items(
        api_get,
        "rulesets?includes_parents=true&per_page=100&page=1",
    )
    rulesets: list[JsonObject] = []
    for summary in summaries:
        if not isinstance(summary, dict) or not isinstance(summary.get("id"), int):
            raise GovernanceError("GitHub ruleset summary is missing an integer id")
        detail = _api_payload(api_get, f"rulesets/{summary['id']}")
        if not isinstance(detail, dict):
            raise GovernanceError("GitHub ruleset detail must be an object")
        rulesets.append(detail)
    errors.extend(_verify_main_rulesets(policy, rulesets, default_ref))

    main_ref = EXPECTED_MAIN_REF
    branch_name = main_ref.removeprefix("refs/heads/")
    protection_endpoint = f"branches/{quote(branch_name, safe='')}/protection"
    protection = _api_response(api_get(protection_endpoint))
    if protection.status == 404:
        if (
            not isinstance(protection.payload, dict)
            or protection.payload.get("message") != "Branch not protected"
        ):
            raise GovernanceError(
                "legacy branch protection 404 did not confirm an unprotected branch"
            )
    elif 200 <= protection.status < 300:
        errors.append(
            "external: legacy main branch protection exists; rulesets are "
            "the only allowed main protection surface"
        )
    else:
        raise GovernanceError(
            f"legacy branch protection query returned HTTP {protection.status}"
        )

    actions = _api_payload(api_get, "actions/permissions")
    if not isinstance(actions, dict):
        raise GovernanceError("GitHub Actions permissions response must be an object")
    if not _json_exact(actions, EXPECTED_ACTIONS):
        errors.append(
            "external: GitHub Actions permissions differ exactly; "
            f"actual={actions!r}, expected={EXPECTED_ACTIONS!r}"
        )
        for key, label in (
            ("enabled", "enabled policy"),
            ("allowed_actions", "allowed-actions policy"),
            ("sha_pinning_required", "full-SHA policy"),
        ):
            actual_value = actions.get(key)
            expected_value = EXPECTED_ACTIONS[key]
            if actual_value != expected_value or type(actual_value) is not type(
                expected_value
            ):
                errors.append(
                    f"external: GitHub Actions {label} is "
                    f"{actual_value!r}; expected {expected_value!r}"
                )

    environment_items = _single_page_items(
        api_get,
        "environments?per_page=100&page=1",
        collection_key="environments",
        require_total_count=True,
    )
    if any(
        not isinstance(item, dict) or not isinstance(item.get("name"), str)
        for item in environment_items
    ):
        raise GovernanceError("GitHub environments contain an invalid entry")
    environment_names = [item["name"] for item in environment_items]
    if len(environment_names) != len(set(environment_names)):
        raise GovernanceError("GitHub environments contain duplicate names")
    available = set(environment_names)
    expected_names = set(EXPECTED_ENVIRONMENTS)
    missing_environments = sorted(expected_names - available)
    extra_environments = sorted(available - expected_names)
    if missing_environments or extra_environments:
        errors.append(
            "external: GitHub environments differ exactly; "
            f"missing={missing_environments!r}, extra={extra_environments!r}"
        )
    for name, expected in EXPECTED_ENVIRONMENTS.items():
        if name not in available:
            continue
        encoded_name = quote(name, safe="")
        actual = _api_payload(api_get, f"environments/{encoded_name}")
        if not isinstance(actual, dict):
            raise GovernanceError(f"GitHub environment {name!r} response is invalid")
        expected_admin_bypass = expected["can_admins_bypass"]
        if actual.get("can_admins_bypass") is not expected_admin_bypass:
            errors.append(
                f"external: environment {name!r} can_admins_bypass is "
                f"{actual.get('can_admins_bypass')!r}; "
                f"expected {expected_admin_bypass!r}"
            )
        try:
            actual_protection = _normalize_environment_protection_rules(
                actual.get("protection_rules"),
                context=f"environment {name!r}",
            )
            expected_protection = _normalize_environment_protection_rules(
                expected.get("protection_rules"),
                context=f"policy environment {name!r}",
            )
        except GovernanceError as exc:
            errors.append(f"external: {exc}")
        else:
            if actual_protection != expected_protection:
                errors.append(
                    f"external: environment {name!r} protection rules are "
                    f"{actual_protection!r}; expected {expected_protection!r}"
                )
        expected_deployment = expected["deployment_branch_policy"]
        if actual.get("deployment_branch_policy") != expected_deployment:
            errors.append(
                f"external: environment {name!r} deployment branch policy is "
                f"{actual.get('deployment_branch_policy')!r}; "
                f"expected {expected_deployment!r}"
            )
            continue
        if expected_deployment is None:
            continue
        branch_policy_items = _single_page_items(
            api_get,
            f"environments/{encoded_name}/deployment-branch-policies"
            "?per_page=100&page=1",
            collection_key="branch_policies",
            require_total_count=True,
        )
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("type"), str)
            for item in branch_policy_items
        ):
            raise GovernanceError(
                f"GitHub environment {name!r} branch policies contain an invalid entry"
            )
        actual_policies = {(item["name"], item["type"]) for item in branch_policy_items}
        if len(actual_policies) != len(branch_policy_items):
            raise GovernanceError(
                f"GitHub environment {name!r} branch policies contain duplicates"
            )
        expected_policies = {
            (item["name"], item["type"]) for item in expected["branch_policies"]
        }
        if actual_policies != expected_policies:
            errors.append(
                f"external: environment {name!r} branch policies are "
                f"{sorted(actual_policies)!r}; expected {sorted(expected_policies)!r}"
            )

    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument(
        "--live",
        action="store_true",
        help="also query GitHub read-only through the authenticated gh CLI",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        policy = load_policy(args.policy)
        errors = validate_local(args.root, policy)
        if args.live:
            repository = policy.get("repository")
            api_version = policy.get("api_version")
            if not isinstance(repository, str) or not isinstance(api_version, str):
                raise GovernanceError(
                    "policy repository and api_version must be strings"
                )
            errors.extend(
                verify_live(
                    policy,
                    lambda endpoint: _gh_api(repository, api_version, endpoint),
                )
            )
    except GovernanceError as exc:
        print(f"governance verification failed: {exc}", file=sys.stderr)
        return 1

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    scope = "local and live" if args.live else "local"
    print(f"repository governance ({scope}): OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
