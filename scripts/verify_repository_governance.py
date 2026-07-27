#!/usr/bin/env python3
"""Verify repository-local and read-only GitHub governance contracts."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
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
    """Return tracked-style workflow paths in deterministic order."""
    workflow_dir = root / ".github/workflows"
    return sorted((*workflow_dir.rglob("*.yml"), *workflow_dir.rglob("*.yaml")))


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


def action_references(
    document: YamlDocument,
) -> Iterable[tuple[int, str]]:
    """Yield every action or reusable-workflow reference in the AST."""
    for node in _nodes_for_mapping_key(document.root, "uses"):
        reference = _scalar_value(node, context=f"{document.path}: uses")
        yield node.start_mark.line + 1, reference


def external_action_references(
    document: YamlDocument,
) -> Iterable[tuple[int, str]]:
    """Yield every non-local action or reusable-workflow reference."""
    for line_number, reference in action_references(document):
        if not reference.startswith("./"):
            yield line_number, reference


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


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _resolve_local_action_reference(
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

    workflow_root = (repository_root / ".github/workflows").resolve()
    if (
        target.is_file()
        and target.is_relative_to(workflow_root)
        and target.suffix in {".yml", ".yaml"}
    ):
        return target

    raise GovernanceError(
        f"{_display_path(source, repository_root)}:{line_number} local uses "
        f"target is missing or unsupported: {reference}"
    )


def validate_repository_yaml_references(
    root: Path,
) -> tuple[dict[Path, YamlDocument], list[str]]:
    """Parse workflow/action YAML and recursively validate every `uses` edge."""
    repository_root = root.resolve()
    workflow_paths = [path.resolve() for path in workflow_files(repository_root)]
    action_paths = [path.resolve() for path in action_manifest_files(repository_root)]
    errors: list[str] = []

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

    def visit(path: Path) -> None:
        status = state.get(path)
        if status == "done":
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
        stack.append(path)
        try:
            document = load_yaml_document(path)
            documents[path] = document
            for line_number, reference in action_references(document):
                if not reference.startswith("./"):
                    if FULL_SHA_ACTION.fullmatch(reference) is None:
                        errors.append(
                            "local: "
                            f"{_display_path(path, repository_root)}:"
                            f"{line_number} action is not pinned to a full "
                            f"lowercase commit SHA: {reference}"
                        )
                    continue
                try:
                    target = _resolve_local_action_reference(
                        repository_root,
                        path,
                        line_number,
                        reference,
                    )
                except GovernanceError as exc:
                    errors.append(f"local: {exc}")
                    continue
                visit(target)
        except GovernanceError as exc:
            errors.append(
                "local: invalid workflow/action YAML "
                f"{_display_path(path, repository_root)}: {exc}"
            )
        finally:
            stack.pop()
            state[path] = "done"

    for path in sorted({*workflow_paths, *action_paths}):
        visit(path)
    return documents, errors


def _string_list(value: Any, *, context: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GovernanceError(f"{context} must be a string list")
    return value


def _normalized_dependabot_groups(document: YamlDocument) -> dict[str, JsonObject]:
    payload = _node_to_data(document.root)
    updates = payload.get("updates")
    if not isinstance(updates, list):
        raise GovernanceError(f"{document.path}: updates must be a list")

    normalized: dict[str, JsonObject] = {}
    for update_index, update in enumerate(updates):
        if not isinstance(update, dict):
            raise GovernanceError(
                f"{document.path}: updates[{update_index}] must be a mapping"
            )
        ecosystem = update.get("package-ecosystem")
        directory = update.get("directory")
        groups = update.get("groups", {})
        if not isinstance(ecosystem, str) or not isinstance(directory, str):
            raise GovernanceError(
                f"{document.path}: update ecosystem and directory must be strings"
            )
        if not isinstance(groups, dict):
            raise GovernanceError(
                f"{document.path}: groups for {ecosystem}:{directory} must be a mapping"
            )
        for group_name, group in groups.items():
            if not isinstance(group_name, str) or not isinstance(group, dict):
                raise GovernanceError(
                    f"{document.path}: Dependabot group must be a named mapping"
                )
            key = f"{ecosystem}:{directory}:{group_name}"
            if key in normalized:
                raise GovernanceError(
                    f"{document.path}: duplicate Dependabot group {key!r}"
                )
            applies_to = group.get("applies-to")
            if not isinstance(applies_to, str):
                raise GovernanceError(
                    f"{document.path}: {key} applies-to must be a string"
                )
            normalized[key] = {
                "applies_to": applies_to,
                "patterns": sorted(
                    _string_list(
                        group.get("patterns"),
                        context=f"{document.path}: {key} patterns",
                    )
                ),
                "exclude_patterns": sorted(
                    _string_list(
                        group.get("exclude-patterns", []),
                        context=f"{document.path}: {key} exclude-patterns",
                    )
                ),
                "update_types": sorted(
                    _string_list(
                        group.get("update-types"),
                        context=f"{document.path}: {key} update-types",
                    )
                ),
            }
    return normalized


def validate_dependabot_grouping(path: Path, policy: JsonObject) -> list[str]:
    """Compare every routine group with the exact machine-readable contract."""
    expected_groups = policy.get("dependabot", {}).get("routine_groups")
    if not isinstance(expected_groups, list):
        return ["local: policy.dependabot.routine_groups must be a list"]

    expected: dict[str, JsonObject] = {}
    for index, group in enumerate(expected_groups):
        if not isinstance(group, dict):
            return [f"local: policy Dependabot group {index} must be an object"]
        required_strings = (
            "package_ecosystem",
            "directory",
            "name",
            "applies_to",
        )
        if not all(isinstance(group.get(key), str) for key in required_strings):
            return [f"local: policy Dependabot group {index} has invalid identity"]
        key = f"{group['package_ecosystem']}:{group['directory']}:{group['name']}"
        if key in expected:
            return [f"local: policy has duplicate Dependabot group {key!r}"]
        try:
            expected[key] = {
                "applies_to": group["applies_to"],
                "patterns": sorted(
                    _string_list(
                        group.get("patterns"),
                        context=f"policy Dependabot group {key} patterns",
                    )
                ),
                "exclude_patterns": sorted(
                    _string_list(
                        group.get("exclude_patterns", []),
                        context=(f"policy Dependabot group {key} exclude_patterns"),
                    )
                ),
                "update_types": sorted(
                    _string_list(
                        group.get("update_types"),
                        context=f"policy Dependabot group {key} update_types",
                    )
                ),
            }
        except GovernanceError as exc:
            return [f"local: {exc}"]

    try:
        actual = _normalized_dependabot_groups(load_yaml_document(path))
    except GovernanceError as exc:
        return [f"local: invalid Dependabot YAML: {exc}"]
    if actual == expected:
        return []

    errors: list[str] = []
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    if missing or extra:
        errors.append(
            "local: Dependabot group identities differ; "
            f"missing={missing!r}, extra={extra!r}"
        )
    for key in sorted(expected.keys() & actual.keys()):
        if actual[key] != expected[key]:
            errors.append(
                f"local: Dependabot group {key!r} is {actual[key]!r}; "
                f"expected {expected[key]!r}"
            )
    return errors


def _required_check_bindings(main: JsonObject) -> list[tuple[str, int]]:
    required_checks = main.get("required_checks")
    if not isinstance(required_checks, list):
        raise GovernanceError("policy.main.required_checks must be a list")
    bindings: list[tuple[str, int]] = []
    for index, check in enumerate(required_checks):
        if not isinstance(check, dict) or set(check) != {
            "context",
            "integration_id",
        }:
            raise GovernanceError(
                f"policy.main.required_checks[{index}] must contain exactly "
                "context and integration_id"
            )
        context = check["context"]
        integration_id = check["integration_id"]
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
        bindings.append((context, integration_id))
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
    return bindings


def validate_local(root: Path, policy: JsonObject) -> list[str]:
    """Validate contracts represented in the repository itself."""
    errors: list[str] = []
    workflows = workflow_files(root)
    if not workflows:
        return ["local: no workflow files found"]

    documents, reference_errors = validate_repository_yaml_references(root)
    errors.extend(reference_errors)
    workflow_paths = {path.resolve() for path in workflows}

    main = policy.get("main")
    if not isinstance(main, dict):
        errors.append("local: policy.main must be an object")
        return errors
    active_ruleset_count = main.get("active_ruleset_count")
    if active_ruleset_count != 1 or type(active_ruleset_count) is not int:
        errors.append(
            "local: policy.main.active_ruleset_count must remain 1 so rules "
            "cannot be distributed"
        )
    if main.get("bypass_actors") != []:
        errors.append("local: policy.main.bypass_actors must remain an empty list")
    rule_types = main.get("rule_types")
    if (
        not isinstance(rule_types, list)
        or not rule_types
        or not all(isinstance(rule_type, str) for rule_type in rule_types)
        or len(rule_types) != len(set(rule_types))
    ):
        errors.append(
            "local: policy.main.rule_types must be a non-empty unique string allowlist"
        )
    try:
        required_bindings = _required_check_bindings(main)
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
    for context, _ in required_bindings:
        occurrences = names.count(context)
        if occurrences != 1:
            errors.append(
                f"local: required check {context!r} must be emitted by exactly "
                f"one job, found {occurrences}"
            )

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
        errors.extend(validate_dependabot_grouping(dependabot, policy))

    actions_policy = policy.get("actions")
    required_actions_policy = {
        "enabled": True,
        "allowed_actions": "all",
        "sha_pinning_required": True,
    }
    if not isinstance(actions_policy, dict) or any(
        actions_policy.get(key) != value
        or type(actions_policy.get(key)) is not type(value)
        for key, value in required_actions_policy.items()
    ):
        errors.append(
            "local: policy.actions must keep Actions enabled, allow all "
            "actions, and require full-SHA pinning"
        )

    return errors


def _gh_api(repository: str, api_version: str, endpoint: str) -> ApiResponse:
    command = [
        "gh",
        "api",
        "--include",
        "--method",
        "GET",
        "-H",
        f"X-GitHub-Api-Version: {api_version}",
        f"repos/{repository}/{endpoint}",
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        normalized = result.stdout.replace("\r\n", "\n")
        if "\n\n" not in normalized:
            raise GovernanceError(
                f"GitHub API GET {endpoint!r} omitted response headers"
            )
        header_text, body = normalized.split("\n\n", 1)
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
        return ApiResponse(payload=json.loads(body), headers=headers)
    except FileNotFoundError as exc:
        raise GovernanceError("gh is required for --live verification") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise GovernanceError(f"GitHub API GET {endpoint!r} failed: {detail}") from exc
    except json.JSONDecodeError as exc:
        raise GovernanceError(
            f"GitHub API GET {endpoint!r} returned invalid JSON"
        ) from exc


def _api_response(value: Any) -> ApiResponse:
    if isinstance(value, ApiResponse):
        return value
    return ApiResponse(payload=value, headers={})


def _api_payload(api_get: ApiGet, endpoint: str) -> Any:
    return _api_response(api_get(endpoint)).payload


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


def _ref_pattern_matches(pattern: str, main_ref: str) -> bool:
    if pattern in {"~ALL", "~DEFAULT_BRANCH"}:
        return True
    return fnmatch.fnmatchcase(main_ref, pattern)


def _ruleset_targets_main(ruleset: JsonObject, main_ref: str) -> bool:
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
    includes_main = any(_ref_pattern_matches(pattern, main_ref) for pattern in include)
    excludes_main = any(_ref_pattern_matches(pattern, main_ref) for pattern in exclude)
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
) -> list[str]:
    errors: list[str] = []
    main = policy["main"]
    main_ref = main["ref"]
    targeting = [
        ruleset for ruleset in rulesets if _ruleset_targets_main(ruleset, main_ref)
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
    expected_reviews = main["required_approving_review_count"]
    for rule in pull_request_rules:
        parameters = rule.get("parameters")
        if not isinstance(parameters, dict):
            errors.append(
                "external: main pull-request rule parameters must be an object"
            )
            continue
        actual_reviews = parameters.get("required_approving_review_count")
        if actual_reviews != expected_reviews:
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
    actual_bindings: list[tuple[str, int]] = []
    strict_enabled = False
    for rule in status_rules:
        parameters = rule.get("parameters")
        if not isinstance(parameters, dict):
            errors.append(
                "external: required-status-check parameters must be an object"
            )
            continue
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
        strict_enabled = parameters.get("strict_required_status_checks_policy") is True

    expected_bindings = _required_check_bindings(main)
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
    if main["strict_status_checks"] and not strict_enabled:
        errors.append("external: strict required status checks are not enabled")

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


def verify_live(policy: JsonObject, api_get: ApiGet) -> list[str]:
    """Read GitHub settings and compare them with the checked-in policy."""
    errors: list[str] = []
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
    errors.extend(_verify_main_rulesets(policy, rulesets))

    actions = _api_payload(api_get, "actions/permissions")
    if not isinstance(actions, dict):
        raise GovernanceError("GitHub Actions permissions response must be an object")
    for key, label in (
        ("enabled", "enabled policy"),
        ("allowed_actions", "allowed-actions policy"),
        ("sha_pinning_required", "full-SHA policy"),
    ):
        expected_value = policy["actions"][key]
        actual_value = actions.get(key)
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
    expected_names = set(policy["environments"])
    missing_environments = sorted(expected_names - available)
    extra_environments = sorted(available - expected_names)
    if missing_environments or extra_environments:
        errors.append(
            "external: GitHub environments differ exactly; "
            f"missing={missing_environments!r}, extra={extra_environments!r}"
        )
    for name, expected in policy["environments"].items():
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
