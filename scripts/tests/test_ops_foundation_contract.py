from __future__ import annotations

import copy
import unittest

from scripts.ops_foundation_contract import (
    EXPECTED_ATTRIBUTE_MAPPING,
    EXPECTED_ISSUER,
    EXPECTED_LIVE_CONDITIONS,
    ContractError,
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
        document = _policy_document(
            role="projects/example/roles/operator",
            member="user:owner@example.com",
            permissions=["iam.serviceAccounts.actAs"],
        )

        validate_policy_audit(
            document,
            scope="project/example",
            allowed_sensitive_members=["user:owner@example.com"],
        )

    def test_each_sensitive_permission_rejects_unreviewed_member(self) -> None:
        permissions = {
            "impersonation": "iam.serviceAccounts.getAccessToken",
            "delegation": "iam.serviceAccounts.implicitDelegation",
            "secret_access": "secretmanager.versions.access",
            "secret_mutation": "secretmanager.secrets.update",
            "artifact_write": "artifactregistry.repositories.uploadArtifacts",
            "state_read": "storage.objects.get",
            "state_write": "storage.objects.create",
            "multipart_state_write": "storage.multipartUploads.create",
        }
        for name, permission in permissions.items():
            with self.subTest(name=name):
                document = _policy_document(
                    role=f"projects/example/roles/{name}",
                    member="user:unreviewed@example.com",
                    permissions=[permission],
                )
                with self.assertRaisesRegex(
                    ContractError,
                    "unreviewed member",
                ):
                    validate_policy_audit(
                        document,
                        scope="project/example",
                        allowed_sensitive_members=["user:owner@example.com"],
                    )

    def test_group_and_domain_require_explicit_review(self) -> None:
        for member in ("group:admins@example.com", "domain:example.com"):
            with self.subTest(member=member):
                document = _policy_document(
                    role="roles/logging.viewer",
                    member=member,
                    permissions=["logging.logEntries.list"],
                )
                with self.assertRaisesRegex(
                    ContractError,
                    "critical principal",
                ):
                    validate_policy_audit(
                        document,
                        scope="organization/123",
                        allowed_sensitive_members=["user:owner@example.com"],
                    )

                validate_policy_audit(
                    document,
                    scope="organization/123",
                    allowed_sensitive_members=[member],
                )

    def test_public_member_cannot_be_allowlisted(self) -> None:
        document = _policy_document(
            role="roles/logging.viewer",
            member="allUsers",
            permissions=["logging.logEntries.list"],
        )

        with self.assertRaisesRegex(
            ContractError,
            "public members cannot be allowlisted",
        ):
            validate_policy_audit(
                document,
                scope="project/example",
                allowed_sensitive_members=["allUsers"],
            )

    def test_missing_custom_role_permissions_fails_closed(self) -> None:
        document = _policy_document(
            role="projects/example/roles/operator",
            member="user:owner@example.com",
            permissions=["secretmanager.versions.access"],
        )
        document["rolePermissions"] = {}

        with self.assertRaisesRegex(
            ContractError,
            "role permission inventory must exactly match",
        ):
            validate_policy_audit(
                document,
                scope="project/example",
                allowed_sensitive_members=["user:owner@example.com"],
            )

    def test_state_bucket_requires_every_direct_member_in_allowlist(self) -> None:
        document = _policy_document(
            role="roles/storage.legacyBucketReader",
            member="serviceAccount:service-agent@example.invalid",
            permissions=["storage.buckets.get"],
        )

        with self.assertRaisesRegex(
            ContractError,
            "direct IAM member",
        ):
            validate_policy_audit(
                document,
                scope="state-bucket",
                allowed_sensitive_members=["user:owner@example.com"],
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
