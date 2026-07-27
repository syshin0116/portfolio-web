from __future__ import annotations

import copy
import unittest

from scripts.ops_foundation_contract import (
    EXPECTED_ATTRIBUTE_MAPPING,
    EXPECTED_ISSUER,
    EXPECTED_LIVE_CONDITIONS,
    ContractError,
    _json_digest,
    _permission_digest,
    validate_live_wif,
    validate_policy_audit,
    validate_secret_policy,
)


def _live_provider(provider_id: str) -> dict[str, object]:
    return {
        "name": (
            "projects/72919926064/locations/global/"
            f"workloadIdentityPools/github/providers/{provider_id}"
        ),
        "state": "ACTIVE",
        "disabled": False,
        "attributeCondition": EXPECTED_LIVE_CONDITIONS[provider_id],
        "attributeMapping": EXPECTED_ATTRIBUTE_MAPPING,
        "oidc": {"issuerUri": EXPECTED_ISSUER},
    }


def _live_wif() -> dict[str, object]:
    providers = [
        _live_provider("github-preview"),
        _live_provider("github-production"),
    ]
    return {
        "pool": {
            "name": (
                "projects/72919926064/locations/global/workloadIdentityPools/github"
            ),
            "state": "ACTIVE",
            "disabled": False,
        },
        "listed": copy.deepcopy(providers),
        "described": providers,
    }


def _policy_document(
    *,
    role: str,
    member: str,
    permissions: list[str],
) -> dict[str, object]:
    return {
        "policy": {
            "bindings": [
                {
                    "role": role,
                    "members": [member],
                }
            ]
        },
        "rolePermissions": {role: permissions},
    }


def _reviewed_binding(
    *,
    scope: str,
    role: str,
    member: str,
    permissions: list[str] | None = None,
    condition: dict[str, object] | None = None,
) -> dict[str, str]:
    binding = {
        "scope": scope,
        "role": role,
        "member": member,
    }
    if permissions is not None:
        binding["permissions_sha256"] = _permission_digest(permissions)
    if condition is not None:
        binding["condition_sha256"] = _json_digest(condition)
    return binding


class LiveWifContractTests(unittest.TestCase):
    def test_exact_enabled_provider_set_passes(self) -> None:
        validate_live_wif(_live_wif())

    def test_third_provider_fails_closed(self) -> None:
        document = _live_wif()
        weak = _live_provider("github-preview")
        weak["name"] = (
            "projects/72919926064/locations/global/"
            "workloadIdentityPools/github/providers/github-weak"
        )
        document["listed"].append(weak)  # type: ignore[union-attr]

        with self.assertRaisesRegex(
            ContractError,
            "live WIF provider set must exactly equal",
        ):
            validate_live_wif(document)

    def test_disabled_provider_fails_closed(self) -> None:
        document = _live_wif()
        document["described"][0]["disabled"] = True  # type: ignore[index]

        with self.assertRaisesRegex(ContractError, "must be enabled"):
            validate_live_wif(document)

    def test_custom_audience_fails_closed(self) -> None:
        document = _live_wif()
        document["described"][0]["oidc"]["allowedAudiences"] = [  # type: ignore[index]
            "rogue"
        ]

        with self.assertRaisesRegex(
            ContractError,
            "allowedAudiences must be absent or empty",
        ):
            validate_live_wif(document)


class PolicyAuditContractTests(unittest.TestCase):
    def test_reviewed_sensitive_operator_passes(self) -> None:
        scope = "projects/example"
        role = "projects/example/roles/operator"
        member = "user:owner@example.com"
        permissions = ["iam.serviceAccounts.actAs"]
        document = _policy_document(
            role=role,
            member=member,
            permissions=permissions,
        )

        validate_policy_audit(
            document,
            scope=scope,
            reviewed_bindings=[
                _reviewed_binding(
                    scope=scope,
                    role=role,
                    member=member,
                    permissions=permissions,
                )
            ],
        )

    def test_each_sensitive_permission_rejects_unreviewed_member(self) -> None:
        permissions = {
            "impersonation": "iam.serviceAccounts.getAccessToken",
            "delegation": "iam.serviceAccounts.implicitDelegation",
            "secret_access": "secretmanager.versions.access",
            "secret_mutation": "secretmanager.secrets.update",
            "artifact_write": "artifactregistry.repositories.uploadArtifacts",
            "artifact_file_download": "artifactregistry.files.download",
            "artifact_export": "artifactregistry.repositories.exportArtifacts",
            "artifact_virtual_read": (
                "artifactregistry.repositories.readViaVirtualRepository"
            ),
            "artifact_create_on_push": ("artifactregistry.repositories.createOnPush"),
            "artifact_delete": "artifactregistry.repositories.deleteArtifacts",
            "artifact_future_power": "artifactregistry.repositories.promote",
            "state_read": "storage.objects.get",
            "state_write": "storage.objects.create",
            "multipart_state_write": "storage.multipartUploads.create",
        }
        for name, permission in permissions.items():
            with self.subTest(name=name):
                scope = "projects/example"
                role = f"projects/example/roles/{name}"
                document = _policy_document(
                    role=role,
                    member="user:unreviewed@example.com",
                    permissions=[permission],
                )
                with self.assertRaisesRegex(
                    ContractError,
                    "unreviewed exact IAM binding",
                ):
                    validate_policy_audit(
                        document,
                        scope=scope,
                        reviewed_bindings=[
                            _reviewed_binding(
                                scope=scope,
                                role=role,
                                member="user:owner@example.com",
                                permissions=[permission],
                            )
                        ],
                    )

    def test_group_and_domain_require_explicit_review(self) -> None:
        for member in ("group:admins@example.com", "domain:example.com"):
            with self.subTest(member=member):
                scope = "organizations/123"
                role = "roles/logging.viewer"
                document = _policy_document(
                    role=role,
                    member=member,
                    permissions=["logging.logEntries.list"],
                )
                with self.assertRaisesRegex(
                    ContractError,
                    "unreviewed exact IAM binding",
                ):
                    validate_policy_audit(
                        document,
                        scope=scope,
                        reviewed_bindings=[
                            _reviewed_binding(
                                scope="organizations/other",
                                role=role,
                                member="user:owner@example.com",
                            )
                        ],
                    )

                validate_policy_audit(
                    document,
                    scope=scope,
                    reviewed_bindings=[
                        _reviewed_binding(
                            scope=scope,
                            role=role,
                            member=member,
                        )
                    ],
                )

    def test_public_member_cannot_be_reviewed(self) -> None:
        scope = "projects/example"
        role = "roles/logging.viewer"
        document = _policy_document(
            role=role,
            member="allUsers",
            permissions=["logging.logEntries.list"],
        )

        with self.assertRaisesRegex(
            ContractError,
            "public members cannot be present",
        ):
            validate_policy_audit(
                document,
                scope=scope,
                reviewed_bindings=[
                    _reviewed_binding(
                        scope=scope,
                        role=role,
                        member="allUsers",
                    )
                ],
            )

    def test_missing_custom_role_permissions_fails_closed(self) -> None:
        scope = "projects/example"
        role = "projects/example/roles/operator"
        member = "user:owner@example.com"
        permissions = ["secretmanager.versions.access"]
        document = _policy_document(
            role=role,
            member=member,
            permissions=permissions,
        )
        document["rolePermissions"] = {}

        with self.assertRaisesRegex(
            ContractError,
            "role permission inventory must exactly match",
        ):
            validate_policy_audit(
                document,
                scope=scope,
                reviewed_bindings=[
                    _reviewed_binding(
                        scope=scope,
                        role=role,
                        member=member,
                        permissions=permissions,
                    )
                ],
            )

    def test_state_bucket_requires_every_exact_direct_binding(self) -> None:
        scope = "buckets/example-tfstate"
        role = "roles/storage.legacyBucketReader"
        document = _policy_document(
            role=role,
            member="serviceAccount:service-agent@example.invalid",
            permissions=["storage.buckets.get"],
        )

        with self.assertRaisesRegex(
            ContractError,
            "unreviewed exact IAM binding",
        ):
            validate_policy_audit(
                document,
                scope=scope,
                reviewed_bindings=[
                    _reviewed_binding(
                        scope=scope,
                        role=role,
                        member="user:owner@example.com",
                    )
                ],
                require_all_bindings=True,
            )

    def test_custom_role_permission_digest_drift_fails_closed(self) -> None:
        scope = "projects/example"
        role = "projects/example/roles/operator"
        member = "user:owner@example.com"
        document = _policy_document(
            role=role,
            member=member,
            permissions=["secretmanager.versions.access"],
        )

        with self.assertRaisesRegex(ContractError, "digest drift"):
            validate_policy_audit(
                document,
                scope=scope,
                reviewed_bindings=[
                    _reviewed_binding(
                        scope=scope,
                        role=role,
                        member=member,
                        permissions=["logging.logEntries.list"],
                    )
                ],
            )

    def test_custom_role_is_reviewed_even_when_currently_non_sensitive(self) -> None:
        scope = "projects/example"
        role = "projects/example/roles/metadataReader"
        member = "user:owner@example.com"
        permissions = ["logging.logEntries.list"]
        document = _policy_document(
            role=role,
            member=member,
            permissions=permissions,
        )

        with self.assertRaisesRegex(ContractError, "unreviewed exact IAM binding"):
            validate_policy_audit(
                document,
                scope=scope,
                reviewed_bindings=[
                    _reviewed_binding(
                        scope="projects/other",
                        role=role,
                        member=member,
                        permissions=permissions,
                    )
                ],
            )

    def test_scope_role_and_member_are_one_exact_review_key(self) -> None:
        role = "roles/secretmanager.secretAccessor"
        member = "user:owner@example.com"
        document = _policy_document(
            role=role,
            member=member,
            permissions=["secretmanager.versions.access"],
        )
        mutations = {
            "scope": ("projects/other", role, member),
            "role": ("projects/example", "roles/owner", member),
            "member": (
                "projects/example",
                role,
                "user:other@example.com",
            ),
        }
        for name, (scope, reviewed_role, reviewed_member) in mutations.items():
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    ContractError,
                    "unreviewed exact IAM binding",
                ),
            ):
                validate_policy_audit(
                    document,
                    scope="projects/example",
                    reviewed_bindings=[
                        _reviewed_binding(
                            scope=scope,
                            role=reviewed_role,
                            member=reviewed_member,
                        )
                    ],
                )

    def test_binding_condition_digest_drift_fails_closed(self) -> None:
        scope = "projects/example"
        role = "roles/secretmanager.secretAccessor"
        member = "user:owner@example.com"
        condition = {
            "expression": "request.time < timestamp('2030-01-01T00:00:00Z')",
            "title": "expires",
        }
        document = _policy_document(
            role=role,
            member=member,
            permissions=["secretmanager.versions.access"],
        )
        document["policy"]["bindings"][0]["condition"] = condition  # type: ignore[index]

        with self.assertRaisesRegex(ContractError, "digest drift"):
            validate_policy_audit(
                document,
                scope=scope,
                reviewed_bindings=[
                    _reviewed_binding(
                        scope=scope,
                        role=role,
                        member=member,
                        condition={"expression": "true", "title": "expires"},
                    )
                ],
            )


class SecretPolicyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.member = "serviceAccount:agent-runtime@example.invalid"
        self.policy: dict[str, object] = {
            "bindings": [
                {
                    "role": "roles/secretmanager.secretAccessor",
                    "members": [self.member],
                }
            ]
        }

    def test_exact_runtime_accessor_passes(self) -> None:
        validate_secret_policy(self.policy, expected_member=self.member)

    def test_extra_role_fails_closed(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["bindings"].append(  # type: ignore[union-attr]
            {
                "role": "roles/secretmanager.viewer",
                "members": [self.member],
            }
        )

        with self.assertRaisesRegex(ContractError, "exactly one role binding"):
            validate_secret_policy(policy, expected_member=self.member)

    def test_extra_accessor_fails_closed(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["bindings"][0]["members"].append(  # type: ignore[index]
            "user:other@example.com"
        )

        with self.assertRaisesRegex(ContractError, "matching runtime"):
            validate_secret_policy(policy, expected_member=self.member)

    def test_condition_fails_closed(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["bindings"][0]["condition"] = {"expression": "true"}  # type: ignore[index]

        with self.assertRaisesRegex(ContractError, "unreviewed condition"):
            validate_secret_policy(policy, expected_member=self.member)


if __name__ == "__main__":
    unittest.main()
