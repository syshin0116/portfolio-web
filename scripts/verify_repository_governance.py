#!/usr/bin/env python3
"""Verify repository-local and read-only GitHub governance contracts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = REPO_ROOT / ".github/repository-governance.json"
FULL_SHA_ACTION = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
    r"(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}$"
)
USES_LINE = re.compile(r"""^\s*(?:-\s*)?uses:\s*["']?([^"'#\s]+)["']?\s*(?:#.*)?$""")
JOB_LINE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(?:#.*)?$")
JOB_NAME_LINE = re.compile(r"""^    name:\s*["']?([^"'#]+?)["']?\s*(?:#.*)?$""")

JsonObject = dict[str, Any]
ApiGet = Callable[[str], Any]


class GovernanceError(RuntimeError):
    """A live GitHub governance query could not be completed."""


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


def external_action_references(path: Path) -> Iterable[tuple[int, str]]:
    """Yield non-local action references from one workflow."""
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        match = USES_LINE.match(line)
        if match is None:
            continue
        reference = match.group(1)
        if not reference.startswith("./"):
            yield line_number, reference


def workflow_job_names(path: Path) -> list[str]:
    """Extract job display names from the repository's conventional YAML layout."""
    names: list[str] = []
    in_jobs = False
    current_job: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "jobs:":
            in_jobs = True
            current_job = None
            continue
        if not in_jobs:
            continue
        if line and not line.startswith((" ", "#")):
            break
        job_match = JOB_LINE.match(line)
        if job_match is not None:
            current_job = job_match.group(1)
            continue
        name_match = JOB_NAME_LINE.match(line)
        if current_job is not None and name_match is not None:
            names.append(name_match.group(1).strip())
            current_job = None
    return names


def validate_local(root: Path, policy: JsonObject) -> list[str]:
    """Validate contracts represented in the repository itself."""
    errors: list[str] = []
    workflows = workflow_files(root)
    if not workflows:
        return ["local: no workflow files found"]

    for path in workflows:
        for line_number, reference in external_action_references(path):
            if FULL_SHA_ACTION.fullmatch(reference) is None:
                relative = path.relative_to(root)
                errors.append(
                    f"local: {relative}:{line_number} action is not pinned to a "
                    f"full lowercase commit SHA: {reference}"
                )

    main = policy.get("main")
    if not isinstance(main, dict):
        errors.append("local: policy.main must be an object")
        return errors
    required_checks = main.get("required_checks")
    if not isinstance(required_checks, list) or not all(
        isinstance(value, str) for value in required_checks
    ):
        errors.append("local: policy.main.required_checks must be a string list")
        return errors

    names: list[str] = []
    for path in workflows:
        names.extend(workflow_job_names(path))
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


def _ruleset_applies_to_main(ruleset: JsonObject, main_ref: str) -> bool:
    if ruleset.get("target") != "branch" or ruleset.get("enforcement") != "active":
        return False
    conditions = ruleset.get("conditions")
    if not isinstance(conditions, dict):
        return False
    ref_name = conditions.get("ref_name")
    if not isinstance(ref_name, dict):
        return False
    include = ref_name.get("include", [])
    exclude = ref_name.get("exclude", [])
    if not isinstance(include, list) or not isinstance(exclude, list):
        return False
    includes_main = bool({main_ref, "~DEFAULT_BRANCH", "~ALL"}.intersection(include))
    excludes_main = bool({main_ref, "~DEFAULT_BRANCH", "~ALL"}.intersection(exclude))
    return includes_main and not excludes_main


def _rules(rulesets: Iterable[JsonObject], rule_type: str) -> list[JsonObject]:
    matches: list[JsonObject] = []
    for ruleset in rulesets:
        rules = ruleset.get("rules", [])
        if not isinstance(rules, list):
            continue
        matches.extend(
            rule
            for rule in rules
            if isinstance(rule, dict) and rule.get("type") == rule_type
        )
    return matches


def _verify_main_rulesets(
    policy: JsonObject,
    rulesets: list[JsonObject],
) -> list[str]:
    errors: list[str] = []
    main = policy["main"]
    main_ref = main["ref"]
    applicable = [
        ruleset for ruleset in rulesets if _ruleset_applies_to_main(ruleset, main_ref)
    ]
    if not applicable:
        return [f"external: no active branch ruleset applies to {main_ref}"]

    for rule_type in main["required_rules"]:
        if not _rules(applicable, rule_type):
            errors.append(
                f"external: active main rulesets do not enforce {rule_type!r}"
            )

    pull_request_rules = _rules(applicable, "pull_request")
    expected_reviews = main["required_approving_review_count"]
    for rule in pull_request_rules:
        parameters = rule.get("parameters", {})
        actual_reviews = parameters.get("required_approving_review_count")
        if actual_reviews != expected_reviews:
            errors.append(
                "external: main pull-request rule requires "
                f"{actual_reviews!r} approvals; expected {expected_reviews}"
            )
        if parameters.get("require_code_owner_review", False):
            errors.append(
                "external: Code Owner approval is required; keep CODEOWNERS "
                "advisory for this solo repository"
            )
        if parameters.get("require_last_push_approval", False):
            errors.append(
                "external: last-push approval is required and can deadlock "
                "this solo repository"
            )

    status_rules = _rules(applicable, "required_status_checks")
    actual_checks: set[str] = set()
    strict_values: list[bool] = []
    for rule in status_rules:
        parameters = rule.get("parameters", {})
        checks = parameters.get("required_status_checks", [])
        if isinstance(checks, list):
            actual_checks.update(
                check["context"]
                for check in checks
                if isinstance(check, dict) and isinstance(check.get("context"), str)
            )
        strict_values.append(
            parameters.get("strict_required_status_checks_policy") is True
        )
    expected_checks = set(main["required_checks"])
    missing_checks = sorted(expected_checks - actual_checks)
    if missing_checks:
        errors.append(
            "external: main rulesets are missing required checks: "
            + ", ".join(missing_checks)
        )
    if main["strict_status_checks"] and not any(strict_values):
        errors.append("external: strict required status checks are not enabled")

    return errors


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
    expected_sha_pinning = policy["actions"]["sha_pinning_required"]
    if actions.get("sha_pinning_required") is not expected_sha_pinning:
        errors.append(
            "external: GitHub Actions full-SHA policy is "
            f"{actions.get('sha_pinning_required')!r}; "
            f"expected {expected_sha_pinning!r}"
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
