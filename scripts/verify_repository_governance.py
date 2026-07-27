#!/usr/bin/env python3
"""Verify repository-local and read-only GitHub governance contracts."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
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
    return sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))


def _nodes_for_mapping_key(node: Node, key: str) -> Iterable[Node]:
    if isinstance(node, MappingNode):
        for candidate, value_node, _ in _mapping_items(node):
            if candidate == key:
                yield value_node
            yield from _nodes_for_mapping_key(value_node, key)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            yield from _nodes_for_mapping_key(item, key)


def external_action_references(
    document: YamlDocument,
) -> Iterable[tuple[int, str]]:
    """Yield every non-local action or reusable-workflow reference in the AST."""
    for node in _nodes_for_mapping_key(document.root, "uses"):
        reference = _scalar_value(node, context=f"{document.path}: uses")
        if not reference.startswith("./"):
            yield node.start_mark.line + 1, reference


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


def validate_local(root: Path, policy: JsonObject) -> list[str]:
    """Validate contracts represented in the repository itself."""
    errors: list[str] = []
    workflows = workflow_files(root)
    if not workflows:
        return ["local: no workflow files found"]

    documents: dict[Path, YamlDocument] = {}
    for path in workflows:
        try:
            document = load_yaml_document(path)
            documents[path] = document
            for line_number, reference in external_action_references(document):
                if FULL_SHA_ACTION.fullmatch(reference) is None:
                    relative = path.relative_to(root)
                    errors.append(
                        f"local: {relative}:{line_number} action is not pinned "
                        f"to a full lowercase commit SHA: {reference}"
                    )
        except GovernanceError as exc:
            relative = path.relative_to(root)
            errors.append(f"local: invalid workflow {relative}: {exc}")

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
    required_checks = main.get("required_checks")
    if not isinstance(required_checks, list) or not all(
        isinstance(value, str) for value in required_checks
    ):
        errors.append("local: policy.main.required_checks must be a string list")
        return errors

    names: list[str] = []
    for path, document in documents.items():
        try:
            names.extend(workflow_job_names(document))
        except GovernanceError as exc:
            relative = path.relative_to(root)
            errors.append(f"local: invalid workflow {relative}: {exc}")
    for required in required_checks:
        occurrences = names.count(required)
        if occurrences != 1:
            errors.append(
                f"local: required check {required!r} must be emitted by exactly "
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

    dependency_audit = root / ".github/workflows/dependency-audit.yml"
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


def _gh_api(repository: str, api_version: str, endpoint: str) -> Any:
    command = [
        "gh",
        "api",
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
        return json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise GovernanceError("gh is required for --live verification") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise GovernanceError(f"GitHub API GET {endpoint!r} failed: {detail}") from exc
    except json.JSONDecodeError as exc:
        raise GovernanceError(
            f"GitHub API GET {endpoint!r} returned invalid JSON"
        ) from exc


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

    for rule_type in main["required_rules"]:
        occurrences = len(_rules(applicable, rule_type))
        if occurrences != 1:
            errors.append(
                f"external: active main ruleset must enforce exactly one "
                f"{rule_type!r} rule, found {occurrences}"
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
    actual_checks: list[str] = []
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
            if not isinstance(check, dict) or not isinstance(check.get("context"), str)
        ]
        if malformed:
            errors.append(
                "external: required_status_checks contains malformed entries: "
                f"{malformed!r}"
            )
            continue
        actual_checks.extend(check["context"] for check in checks)
        strict_enabled = parameters.get("strict_required_status_checks_policy") is True

    expected_checks = set(main["required_checks"])
    actual_check_set = set(actual_checks)
    missing_checks = sorted(expected_checks - actual_check_set)
    extra_checks = sorted(actual_check_set - expected_checks)
    duplicate_checks = sorted(
        check for check in actual_check_set if actual_checks.count(check) > 1
    )
    if missing_checks or extra_checks or duplicate_checks:
        errors.append(
            "external: main required checks differ exactly; "
            f"missing={missing_checks!r}, extra={extra_checks!r}, "
            f"duplicates={duplicate_checks!r}"
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
    summaries = api_get("rulesets?includes_parents=true")
    if not isinstance(summaries, list):
        raise GovernanceError("GitHub rulesets response must be a list")
    rulesets: list[JsonObject] = []
    for summary in summaries:
        if not isinstance(summary, dict) or not isinstance(summary.get("id"), int):
            raise GovernanceError("GitHub ruleset summary is missing an integer id")
        detail = api_get(f"rulesets/{summary['id']}")
        if not isinstance(detail, dict):
            raise GovernanceError("GitHub ruleset detail must be an object")
        rulesets.append(detail)
    errors.extend(_verify_main_rulesets(policy, rulesets))

    actions = api_get("actions/permissions")
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

    environments = api_get("environments?per_page=100")
    if not isinstance(environments, dict) or not isinstance(
        environments.get("environments"), list
    ):
        raise GovernanceError("GitHub environments response is invalid")
    available = {
        item["name"]
        for item in environments["environments"]
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    for name, expected in policy["environments"].items():
        if name not in available:
            errors.append(f"external: required environment {name!r} does not exist")
            continue
        encoded_name = quote(name, safe="")
        actual = api_get(f"environments/{encoded_name}")
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
        policies = api_get(
            f"environments/{encoded_name}/deployment-branch-policies?per_page=100"
        )
        if not isinstance(policies, dict) or not isinstance(
            policies.get("branch_policies"), list
        ):
            raise GovernanceError(
                f"GitHub environment {name!r} branch policies response is invalid"
            )
        actual_policies = {
            (item["name"], item["type"])
            for item in policies["branch_policies"]
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("type"), str)
        }
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
