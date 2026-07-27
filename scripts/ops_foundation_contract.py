#!/usr/bin/env python3
"""Credential-free static and JSON policy contracts for the GCP foundation."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

EXPECTED_TERRAFORM_FILES = frozenset(
    {
        "infra/gcp/backend.tf",
        "infra/gcp/iam.tf",
        "infra/gcp/imports.tf",
        "infra/gcp/main.tf",
        "infra/gcp/outputs.tf",
        "infra/gcp/state.tf",
        "infra/gcp/variables.tf",
        "infra/gcp/versions.tf",
    }
)
EXPECTED_SECURITY_RESOURCES = frozenset(
    {
        ("google_iam_workload_identity_pool", "github"),
        ("google_iam_workload_identity_pool_provider", "preview"),
        ("google_iam_workload_identity_pool_provider", "production"),
        ("google_secret_manager_secret_iam_member", "preview_runtime_accessor"),
        ("google_secret_manager_secret_iam_member", "runtime_accessor"),
        ("google_service_account_iam_member", "deployer_uses_runtime"),
        ("google_service_account_iam_member", "github_preview"),
        ("google_service_account_iam_member", "github_production"),
    }
)
EXPECTED_ATTRIBUTE_MAPPING = {
    "attribute.environment": "assertion.environment",
    "attribute.event_name": "assertion.event_name",
    "attribute.ref": "assertion.ref",
    "attribute.repository_id": "assertion.repository_id",
    "attribute.repository_owner_id": "assertion.repository_owner_id",
    "google.subject": "assertion.sub",
}
EXPECTED_SOURCE_CONDITIONS = {
    "preview": (
        "assertion.repository_id == '${var.github_repository_id}' && "
        "assertion.repository_owner_id == '${var.github_owner_id}' && "
        "assertion.event_name == 'pull_request' && "
        "assertion.environment == '${var.github_preview_environment}'"
    ),
    "production": (
        "assertion.repository_id == '${var.github_repository_id}' && "
        "assertion.repository_owner_id == '${var.github_owner_id}' && "
        "assertion.event_name == 'push' && "
        "assertion.ref == 'refs/heads/main' && "
        "assertion.environment == '${var.github_production_environment}'"
    ),
}
EXPECTED_LIVE_CONDITIONS = {
    "github-preview": (
        "assertion.repository_id == '1102380057' && "
        "assertion.repository_owner_id == '99532836' && "
        "assertion.event_name == 'pull_request' && "
        "assertion.environment == 'Preview'"
    ),
    "github-production": (
        "assertion.repository_id == '1102380057' && "
        "assertion.repository_owner_id == '99532836' && "
        "assertion.event_name == 'push' && "
        "assertion.ref == 'refs/heads/main' && "
        "assertion.environment == 'Production'"
    ),
}
EXPECTED_PROVIDER_IDS = {
    "preview": "github-preview",
    "production": "github-production",
}
EXPECTED_ISSUER = "https://token.actions.githubusercontent.com"

BLOCK_HEADER = re.compile(r'(?m)^[ \t]*(resource|data)\s+"([^"]+)"\s+"([^"]+)"\s*\{')
MODULE_HEADER = re.compile(r'(?m)^[ \t]*module\s+"([^"]+)"\s*\{')
MAPPING_ENTRY = re.compile(r'^\s*"([^"]+)"\s*=\s*"([^"]+)"\s*$')

FORBIDDEN_TERRAFORM_PATTERNS = {
    r"roles/run\.admin": (
        "foundation deployers must not receive project-wide roles/run.admin"
    ),
    r"roles/artifactregistry\.writer": (
        "foundation deployers must not build or push images"
    ),
    r'resource\s+"google_service_account_key"': (
        "user-managed service-account keys are forbidden"
    ),
    r'resource\s+"google_secret_manager_secret_version"': (
        "Terraform must not manage secret payload versions"
    ),
    r"private_key|private_key_data|service_account_key": (
        "credential material must not enter Terraform configuration"
    ),
    r'variable\s+"project_number"|var\.project_number': (
        "the project number must not be independently overridden"
    ),
}

PUBLIC_MEMBERS = frozenset({"allAuthenticatedUsers", "allUsers"})
REVIEW_REQUIRED_MEMBER_PREFIXES = (
    "group:",
    "domain:",
    "deleted:group:",
    "deleted:domain:",
    "principal:",
    "principalSet:",
)


class ContractError(ValueError):
    """The foundation contract is incomplete or unsafe."""


def _fail(message: str) -> None:
    raise ContractError(message)


def _json_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{label} must be a JSON object")
    return value


def _json_array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{label} must be a JSON array")
    return value


def _read_stdin_json() -> dict[str, Any]:
    try:
        return _json_object(json.load(sys.stdin), "input")
    except (json.JSONDecodeError, OSError) as exc:
        raise ContractError(f"input must be valid JSON: {exc}") from exc


def _tracked_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "infra/gcp"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        _fail(f"cannot enumerate tracked Terraform files: {detail}")
    try:
        return [raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw]
    except UnicodeDecodeError as exc:
        raise ContractError("tracked infra/gcp paths must be UTF-8") from exc


def _find_block_end(source: str, opening_brace: int) -> int:
    depth = 0
    quote = False
    escaped = False
    line_comment = False
    block_comment = False
    index = opening_brace

    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""

        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == "#":
            line_comment = True
            index += 1
            continue
        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char == '"':
            quote = True
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1

    _fail("unterminated Terraform block")


def _resource_blocks(
    sources: Mapping[str, str],
) -> dict[tuple[str, str], str]:
    blocks: dict[tuple[str, str], str] = {}
    for source in sources.values():
        for match in BLOCK_HEADER.finditer(source):
            kind, resource_type, resource_name = match.groups()
            if kind != "resource":
                continue
            key = (resource_type, resource_name)
            if key in blocks:
                _fail(
                    "duplicate Terraform resource declaration: "
                    f"{resource_type}.{resource_name}"
                )
            opening_brace = source.find("{", match.start(), match.end())
            end = _find_block_end(source, opening_brace)
            blocks[key] = source[match.start() : end]
    return blocks


def _require_string_assignment(block: str, key: str, expected: str) -> None:
    pattern = re.compile(
        rf'(?m)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*"{re.escape(expected)}"[ \t]*$'
    )
    if len(pattern.findall(block)) != 1:
        _fail(f"{key} must exactly equal {expected!r}")


def _require_literal_assignment(block: str, key: str, expected: str) -> None:
    pattern = re.compile(
        rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*{re.escape(expected)}[ \t]*$"
    )
    if len(pattern.findall(block)) != 1:
        _fail(f"{key} must exactly equal {expected}")


def _extract_mapping(block: str) -> dict[str, str]:
    header = re.search(r"(?m)^[ \t]*attribute_mapping[ \t]*=[ \t]*\{", block)
    if header is None:
        _fail("WIF provider must declare attribute_mapping")
    opening_brace = block.find("{", header.start(), header.end())
    end = _find_block_end(block, opening_brace)
    body = block[opening_brace + 1 : end - 1]
    mapping: dict[str, str] = {}
    for line in body.splitlines():
        if not line.strip():
            continue
        match = MAPPING_ENTRY.fullmatch(line)
        if match is None:
            _fail("WIF attribute_mapping must contain only exact string mappings")
        key, value = match.groups()
        if key in mapping:
            _fail(f"duplicate WIF attribute mapping: {key}")
        mapping[key] = value
    return mapping


def validate_static_contract(repo_root: Path) -> None:
    tracked_paths = _tracked_paths(repo_root)
    tracked_tf = frozenset(
        path for path in tracked_paths if path.endswith((".tf", ".tf.json"))
    )
    if tracked_tf != EXPECTED_TERRAFORM_FILES:
        missing = sorted(EXPECTED_TERRAFORM_FILES - tracked_tf)
        unexpected = sorted(tracked_tf - EXPECTED_TERRAFORM_FILES)
        _fail(
            "tracked Terraform inventory mismatch; "
            f"missing={missing}, unexpected={unexpected}. "
            "Nested Terraform modules are prohibited in this foundation."
        )

    sources: dict[str, str] = {}
    for relative_path in sorted(tracked_tf):
        path = repo_root / relative_path
        if path.is_symlink():
            _fail(f"tracked Terraform file must not be a symlink: {relative_path}")
        try:
            sources[relative_path] = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ContractError(
                f"cannot read tracked Terraform file {relative_path}: {exc}"
            ) from exc

    combined = "\n".join(sources.values())
    modules = MODULE_HEADER.findall(combined)
    if modules:
        _fail(
            "Terraform module blocks are prohibited in this foundation: "
            f"{sorted(set(modules))}"
        )

    resources = _resource_blocks(sources)
    security_resources = frozenset(
        key
        for key in resources
        if "_iam_" in key[0]
        or key[0]
        in {
            "google_iam_workload_identity_pool",
            "google_iam_workload_identity_pool_provider",
        }
    )
    if security_resources != EXPECTED_SECURITY_RESOURCES:
        missing = sorted(EXPECTED_SECURITY_RESOURCES - security_resources)
        unexpected = sorted(security_resources - EXPECTED_SECURITY_RESOURCES)
        _fail(
            "Terraform IAM/WIF declarations must exactly match the reviewed "
            f"allowlist; missing={missing}, unexpected={unexpected}"
        )

    for pattern, message in FORBIDDEN_TERRAFORM_PATTERNS.items():
        if re.search(pattern, combined):
            _fail(message)

    pool = resources[("google_iam_workload_identity_pool", "github")]
    _require_string_assignment(pool, "workload_identity_pool_id", "github")
    _require_literal_assignment(pool, "disabled", "false")

    for resource_name, provider_id in EXPECTED_PROVIDER_IDS.items():
        provider = resources[
            ("google_iam_workload_identity_pool_provider", resource_name)
        ]
        _require_string_assignment(
            provider,
            "workload_identity_pool_provider_id",
            provider_id,
        )
        _require_literal_assignment(provider, "disabled", "false")
        _require_literal_assignment(
            provider,
            "attribute_condition",
            f"local.{resource_name}_wif_attribute_condition",
        )
        _require_string_assignment(provider, "issuer_uri", EXPECTED_ISSUER)
        if re.search(r"(?m)^[ \t]*allowed_audiences[ \t]*=", provider):
            _fail(
                f"{provider_id} must use Google's default audience; "
                "allowed_audiences must be absent"
            )
        if _extract_mapping(provider) != EXPECTED_ATTRIBUTE_MAPPING:
            _fail(f"{provider_id} attribute_mapping must exactly match the contract")

        condition_pattern = re.compile(
            rf"(?m)^[ \t]*{re.escape(resource_name)}_wif_attribute_condition"
            rf'[ \t]*=[ \t]*"{re.escape(EXPECTED_SOURCE_CONDITIONS[resource_name])}"'
            r"[ \t]*$"
        )
        if len(condition_pattern.findall(combined)) != 1:
            _fail(
                f"{resource_name} WIF CEL condition must exactly match "
                "the fail-closed contract"
            )


def _provider_id(provider: Mapping[str, Any]) -> str:
    name = provider.get("name")
    if not isinstance(name, str):
        _fail("WIF provider name must be a string")
    match = re.fullmatch(
        r"projects/[^/]+/locations/global/workloadIdentityPools/github/"
        r"providers/([^/]+)",
        name,
    )
    if match is None:
        _fail(f"WIF provider is outside the canonical github pool: {name!r}")
    return match.group(1)


def _validate_enabled(resource: Mapping[str, Any], label: str) -> None:
    if resource.get("state") != "ACTIVE":
        _fail(f"{label} must be ACTIVE")
    if resource.get("disabled", False) is not False:
        _fail(f"{label} must be enabled")


def validate_live_wif(document: Mapping[str, Any]) -> None:
    pool = _json_object(document.get("pool"), "pool")
    pool_name = pool.get("name")
    if not isinstance(pool_name, str) or not pool_name.endswith(
        "/locations/global/workloadIdentityPools/github"
    ):
        _fail("live WIF pool ID must exactly equal github")
    _validate_enabled(pool, "github WIF pool")

    listed = [
        _json_object(value, "listed provider")
        for value in _json_array(document.get("listed"), "listed")
    ]
    described = [
        _json_object(value, "described provider")
        for value in _json_array(document.get("described"), "described")
    ]

    expected_ids = frozenset(EXPECTED_LIVE_CONDITIONS)
    listed_by_id = {_provider_id(provider): provider for provider in listed}
    described_by_id = {_provider_id(provider): provider for provider in described}
    if len(listed_by_id) != len(listed):
        _fail("live WIF provider list contains duplicate IDs")
    if len(described_by_id) != len(described):
        _fail("described WIF provider set contains duplicate IDs")
    if frozenset(listed_by_id) != expected_ids:
        _fail(
            "live WIF provider set must exactly equal "
            f"{sorted(expected_ids)}, got {sorted(listed_by_id)}"
        )
    if frozenset(described_by_id) != expected_ids:
        _fail("described WIF provider set does not match the exact live list")

    for provider_id in sorted(expected_ids):
        _validate_enabled(listed_by_id[provider_id], provider_id)
        provider = described_by_id[provider_id]
        _validate_enabled(provider, provider_id)
        if provider.get("attributeCondition") != EXPECTED_LIVE_CONDITIONS[provider_id]:
            _fail(f"{provider_id} attributeCondition is not exact")
        if provider.get("attributeMapping") != EXPECTED_ATTRIBUTE_MAPPING:
            _fail(f"{provider_id} attributeMapping is not exact")
        oidc = _json_object(provider.get("oidc"), f"{provider_id}.oidc")
        if oidc.get("issuerUri") != EXPECTED_ISSUER:
            _fail(f"{provider_id} issuerUri is not exact")
        audiences = oidc.get("allowedAudiences", [])
        if not isinstance(audiences, list) or audiences:
            _fail(f"{provider_id} allowedAudiences must be absent or empty")


def _policy_bindings(policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_bindings = policy.get("bindings", [])
    bindings = [
        _json_object(value, "IAM binding")
        for value in _json_array(raw_bindings, "policy.bindings")
    ]
    for binding in bindings:
        role = binding.get("role")
        members = binding.get("members")
        if not isinstance(role, str) or not role:
            _fail("IAM binding role must be a non-empty string")
        member_values = _json_array(members, f"{role}.members")
        if not member_values or not all(
            isinstance(member, str) and member for member in member_values
        ):
            _fail(f"{role}.members must contain non-empty strings")
        if len(set(member_values)) != len(member_values):
            _fail(f"{role}.members must not contain duplicates")
    return bindings


def _critical_member(member: str) -> bool:
    return member.startswith(REVIEW_REQUIRED_MEMBER_PREFIXES)


def _permission_categories(permission: str) -> frozenset[str]:
    categories: set[str] = set()
    if permission in {
        "iam.serviceAccounts.actAs",
        "iam.serviceAccounts.getAccessToken",
        "iam.serviceAccounts.getOpenIdToken",
        "iam.serviceAccounts.implicitDelegation",
        "iam.serviceAccounts.signBlob",
        "iam.serviceAccounts.signJwt",
        "iam.serviceAccounts.setIamPolicy",
    } or (
        permission.startswith("iam.serviceAccountKeys.")
        and not permission.endswith((".get", ".list"))
    ):
        categories.add("service-account-impersonation")

    if permission.startswith("secretmanager."):
        safe_secret_suffixes = (
            ".get",
            ".list",
            ".listEffectiveTags",
            ".listTagBindings",
        )
        if permission == "secretmanager.versions.access" or not permission.endswith(
            safe_secret_suffixes
        ):
            categories.add("secret-read-or-mutation")

    if permission.startswith("artifactregistry."):
        write_verbs = {
            "create",
            "delete",
            "import",
            "setIamPolicy",
            "update",
            "upload",
            "uploadArtifacts",
        }
        if permission.rsplit(".", 1)[-1] in write_verbs:
            categories.add("artifact-registry-write")
        if permission.endswith("downloadArtifacts"):
            categories.add("artifact-registry-read")

    if permission.startswith(
        ("storage.objects.", "storage.multipartUploads.")
    ) or permission in {
        "storage.buckets.delete",
        "storage.buckets.setIamPolicy",
        "storage.buckets.update",
    }:
        categories.add("terraform-state-read-or-write")

    if permission.endswith(".setIamPolicy") or permission in {
        "iam.roles.create",
        "iam.roles.delete",
        "iam.roles.update",
        "resourcemanager.projects.setIamPolicy",
    }:
        categories.add("iam-policy-escalation")
    return frozenset(categories)


def validate_policy_audit(
    document: Mapping[str, Any],
    *,
    scope: str,
    allowed_sensitive_members: Iterable[str],
) -> None:
    policy = _json_object(document.get("policy"), "policy")
    bindings = _policy_bindings(policy)
    role_permissions_raw = _json_object(
        document.get("rolePermissions"),
        "rolePermissions",
    )
    allowed = frozenset(allowed_sensitive_members)
    if not allowed:
        _fail(f"{scope} audit requires a non-empty reviewed member allowlist")
    if PUBLIC_MEMBERS & allowed:
        _fail("public members cannot be allowlisted")

    roles = {binding["role"] for binding in bindings}
    if set(role_permissions_raw) != roles:
        missing = sorted(roles - set(role_permissions_raw))
        unexpected = sorted(set(role_permissions_raw) - roles)
        _fail(
            "role permission inventory must exactly match policy roles; "
            f"missing={missing}, unexpected={unexpected}"
        )

    role_permissions: dict[str, tuple[str, ...]] = {}
    for role, raw_permissions in role_permissions_raw.items():
        permissions = _json_array(raw_permissions, f"{role}.includedPermissions")
        if not all(
            isinstance(permission, str) and permission for permission in permissions
        ):
            _fail(f"{role}.includedPermissions must contain non-empty strings")
        role_permissions[role] = tuple(permissions)

    errors: list[str] = []
    for binding in bindings:
        role = binding["role"]
        members = binding["members"]
        categories = sorted(
            {
                category
                for permission in role_permissions[role]
                for category in _permission_categories(permission)
            }
        )
        binding_is_sensitive = bool(categories)
        for member in members:
            if member in PUBLIC_MEMBERS:
                errors.append(f"{scope}: public principal {member!r} is forbidden")
            elif _critical_member(member) and member not in allowed:
                errors.append(
                    f"{scope}: critical principal {member!r} is not in the "
                    "reviewed member allowlist"
                )
            elif binding_is_sensitive and member not in allowed:
                errors.append(
                    f"{scope}: unreviewed member {member!r} has sensitive role "
                    f"{role!r} ({','.join(categories)})"
                )
            if scope == "state-bucket" and member not in allowed:
                errors.append(
                    f"state-bucket: direct IAM member {member!r} is not in the "
                    "reviewed bucket allowlist"
                )
    if errors:
        _fail("; ".join(sorted(set(errors))))


def validate_secret_policy(
    policy: Mapping[str, Any],
    *,
    expected_member: str,
) -> None:
    bindings = _policy_bindings(policy)
    if len(bindings) != 1:
        _fail("secret IAM policy must contain exactly one role binding")
    binding = bindings[0]
    if binding.get("role") != "roles/secretmanager.secretAccessor":
        _fail(
            "secret IAM role set must exactly equal "
            "{roles/secretmanager.secretAccessor}"
        )
    if binding.get("members") != [expected_member]:
        _fail("secret accessor member must exactly equal the matching runtime")
    if "condition" in binding:
        _fail("secret accessor binding must not contain an unreviewed condition")


def _members_from_env(variable_name: str) -> list[str]:
    raw = os.environ.get(variable_name, "")
    members = [line.strip() for line in raw.splitlines() if line.strip()]
    if not members:
        _fail(
            f"{variable_name} must contain newline-separated members from a "
            "reviewed live IAM inventory"
        )
    if len(set(members)) != len(members):
        _fail(f"{variable_name} must not contain duplicate members")
    return members


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    static = subparsers.add_parser("static")
    static.add_argument("--repo-root", type=Path, required=True)

    subparsers.add_parser("wif-live")

    audit = subparsers.add_parser("audit-policy")
    audit.add_argument("--scope", required=True)
    audit.add_argument("--allowed-members-env", required=True)

    secret = subparsers.add_parser("secret-policy")
    secret.add_argument("--expected-member", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "static":
            validate_static_contract(args.repo_root.resolve())
        elif args.command == "wif-live":
            validate_live_wif(_read_stdin_json())
        elif args.command == "audit-policy":
            validate_policy_audit(
                _read_stdin_json(),
                scope=args.scope,
                allowed_sensitive_members=_members_from_env(args.allowed_members_env),
            )
        elif args.command == "secret-policy":
            validate_secret_policy(
                _read_stdin_json(),
                expected_member=args.expected_member,
            )
        else:  # pragma: no cover - argparse owns this branch.
            raise AssertionError(args.command)
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {args.command} foundation contract verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
