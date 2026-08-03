from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.ops_foundation_contract import (
    EXPECTED_ISSUER,
    EXPECTED_LIVE_ATTRIBUTE_MAPPINGS,
    EXPECTED_LIVE_CONDITIONS,
    OFFLINE_ADMIN_EVIDENCE_SCHEMA,
    ContractError,
    _json_digest,
    _permission_digest,
    validate_live_wif,
    validate_offline_admin_evidence,
    validate_offline_admin_evidence_file,
    validate_policy_audit,
    validate_secret_policy,
    validate_terraform_test_result,
)

SYNTHETIC_PROJECT_ID = "boundary-test-project"
SYNTHETIC_PROJECT_NUMBER = "123456789012"
SYNTHETIC_WORKLOAD_ACCOUNT = f"runtime@{SYNTHETIC_PROJECT_ID}.iam.gserviceaccount.com"
SYNTHETIC_CAPTURED_AT = datetime(2026, 7, 29, 0, 0, tzinfo=UTC)


def _live_provider(provider_id: str) -> dict[str, object]:
    disabled = provider_id == "github-preview"
    return {
        "name": (
            "projects/72919926064/locations/global/"
            f"workloadIdentityPools/github/providers/{provider_id}"
        ),
        "state": "ACTIVE",
        "disabled": disabled,
        "attributeCondition": EXPECTED_LIVE_CONDITIONS[provider_id],
        "attributeMapping": copy.deepcopy(
            EXPECTED_LIVE_ATTRIBUTE_MAPPINGS[provider_id]
        ),
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


def _offline_admin_evidence() -> dict[str, object]:
    scope = "organizations/987654321"
    role = "roles/logging.viewer"
    member = "user:reviewer@example.invalid"
    permissions = ["logging.logEntries.list"]
    return {
        "schemaVersion": OFFLINE_ADMIN_EVIDENCE_SCHEMA,
        "capturedAt": SYNTHETIC_CAPTURED_AT.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": {
            "id": SYNTHETIC_PROJECT_ID,
            "number": SYNTHETIC_PROJECT_NUMBER,
        },
        "ancestors": [
            {
                "scope": scope,
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
        ],
        "reviewedBindings": [
            _reviewed_binding(
                scope=scope,
                role=role,
                member=member,
            )
        ],
    }


def _terraform_test_records() -> list[dict[str, object]]:
    return [
        {
            "type": "version",
            "terraform": "1.13.5",
        },
        {
            "type": "test_abstract",
            "test_abstract": {
                "tests/foundation.tftest.hcl": [
                    "foundation_security_contract",
                    "foundation_bootstrap_contract",
                    "jobs_bootstrap_contract",
                    "services_bootstrap_contract",
                ]
            },
        },
        {
            "type": "test_run",
            "test_run": {
                "path": "tests/foundation.tftest.hcl",
                "run": "foundation_security_contract",
                "progress": "complete",
                "status": "pass",
            },
        },
        {
            "type": "test_run",
            "test_run": {
                "path": "tests/foundation.tftest.hcl",
                "run": "foundation_bootstrap_contract",
                "progress": "complete",
                "status": "pass",
            },
        },
        {
            "type": "test_run",
            "test_run": {
                "path": "tests/foundation.tftest.hcl",
                "run": "jobs_bootstrap_contract",
                "progress": "complete",
                "status": "pass",
            },
        },
        {
            "type": "test_run",
            "test_run": {
                "path": "tests/foundation.tftest.hcl",
                "run": "services_bootstrap_contract",
                "progress": "complete",
                "status": "pass",
            },
        },
        {
            "type": "test_summary",
            "test_summary": {
                "status": "pass",
                "passed": 4,
                "failed": 0,
                "errored": 0,
                "skipped": 0,
            },
        },
    ]


class TerraformTestResultContractTests(unittest.TestCase):
    def test_exact_reviewed_run_inventory_passes(self) -> None:
        validate_terraform_test_result(_terraform_test_records())

    def test_zero_discovered_tests_fails_closed(self) -> None:
        records = _terraform_test_records()
        records[1]["test_abstract"] = {}
        del records[2:6]
        records[2]["test_summary"] = {
            "status": "pass",
            "passed": 0,
            "failed": 0,
            "errored": 0,
            "skipped": 0,
        }

        with self.assertRaisesRegex(
            ContractError,
            "discovery must exactly equal the reviewed file/run inventory",
        ):
            validate_terraform_test_result(records)


class LiveWifContractTests(unittest.TestCase):
    def test_exact_single_active_and_managed_disabled_provider_set_passes(self) -> None:
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

    def test_active_provider_disabled_fails_closed(self) -> None:
        document = _live_wif()
        document["described"][1]["disabled"] = True  # type: ignore[index]

        with self.assertRaisesRegex(ContractError, "must be enabled"):
            validate_live_wif(document)

    def test_legacy_provider_reenabled_fails_closed(self) -> None:
        document = _live_wif()
        document["described"][0]["disabled"] = False  # type: ignore[index]

        with self.assertRaisesRegex(ContractError, "must remain disabled"):
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

    def test_unmapped_active_condition_field_fails_closed(self) -> None:
        document = _live_wif()
        provider = document["described"][1]  # type: ignore[index]
        provider["attributeCondition"] = (  # type: ignore[index]
            EXPECTED_LIVE_CONDITIONS["github-production"].replace(
                "attribute.repository_id",
                "assertion.repository_id",
                1,
            )
        )

        with self.assertRaisesRegex(ContractError, "attributeCondition is not exact"):
            validate_live_wif(document)

    def test_missing_or_optional_claim_mapping_fails_closed(self) -> None:
        for mutation in ("missing_repository_id", "direct_environment"):
            with self.subTest(mutation=mutation):
                document = _live_wif()
                mapping = document["described"][1]["attributeMapping"]  # type: ignore[index]
                if mutation == "missing_repository_id":
                    del mapping["attribute.repository_id"]
                else:
                    mapping["attribute.environment"] = "assertion.environment"

                with self.assertRaisesRegex(
                    ContractError,
                    "attributeMapping is not exact",
                ):
                    validate_live_wif(document)


class OfflineAdminEvidenceContractTests(unittest.TestCase):
    def _validate(self, document: dict[str, object]) -> None:
        validate_offline_admin_evidence(
            document,
            expected_project_id=SYNTHETIC_PROJECT_ID,
            expected_project_number=SYNTHETIC_PROJECT_NUMBER,
            workload_service_accounts=[SYNTHETIC_WORKLOAD_ACCOUNT],
            now=SYNTHETIC_CAPTURED_AT + timedelta(hours=1),
        )

    def _write_private_evidence(self, directory: str, content: str) -> Path:
        evidence_path = Path(directory) / "admin-evidence.json"
        evidence_path.write_text(content, encoding="utf-8")
        evidence_path.chmod(0o600)
        return evidence_path

    def test_fresh_exact_synthetic_bundle_passes(self) -> None:
        self._validate(_offline_admin_evidence())

    def test_private_absolute_bundle_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_path = self._write_private_evidence(
                directory,
                json.dumps(_offline_admin_evidence()),
            )

            validate_offline_admin_evidence_file(
                evidence_path,
                expected_project_id=SYNTHETIC_PROJECT_ID,
                expected_project_number=SYNTHETIC_PROJECT_NUMBER,
                workload_service_accounts=[SYNTHETIC_WORKLOAD_ACCOUNT],
                now=SYNTHETIC_CAPTURED_AT + timedelta(hours=1),
            )

    def test_missing_bundle_fails_before_schema_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing_path = Path(directory) / "missing.json"
            with self.assertRaisesRegex(
                ContractError,
                "missing or unreadable",
            ):
                validate_offline_admin_evidence_file(
                    missing_path,
                    expected_project_id=SYNTHETIC_PROJECT_ID,
                    expected_project_number=SYNTHETIC_PROJECT_NUMBER,
                    workload_service_accounts=[SYNTHETIC_WORKLOAD_ACCOUNT],
                )

    def test_relative_bundle_path_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractError, "path must be absolute"):
            validate_offline_admin_evidence_file(
                Path("admin-evidence.json"),
                expected_project_id=SYNTHETIC_PROJECT_ID,
                expected_project_number=SYNTHETIC_PROJECT_NUMBER,
                workload_service_accounts=[SYNTHETIC_WORKLOAD_ACCOUNT],
            )

    def test_malformed_bundle_is_rejected_without_echoing_contents(self) -> None:
        marker = "DO-NOT-ECHO-SYNTHETIC-EVIDENCE"
        with tempfile.TemporaryDirectory() as directory:
            evidence_path = self._write_private_evidence(
                directory,
                f'{{"{marker}":',
            )
            with self.assertRaises(ContractError) as caught:
                validate_offline_admin_evidence_file(
                    evidence_path,
                    expected_project_id=SYNTHETIC_PROJECT_ID,
                    expected_project_number=SYNTHETIC_PROJECT_NUMBER,
                    workload_service_accounts=[SYNTHETIC_WORKLOAD_ACCOUNT],
                )

        self.assertIn("valid UTF-8 JSON", str(caught.exception))
        self.assertNotIn(marker, str(caught.exception))

    def test_bundle_permissions_reject_group_or_other_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_path = self._write_private_evidence(
                directory,
                json.dumps(_offline_admin_evidence()),
            )
            evidence_path.chmod(0o640)

            with self.assertRaisesRegex(
                ContractError,
                "no group or other permissions",
            ):
                validate_offline_admin_evidence_file(
                    evidence_path,
                    expected_project_id=SYNTHETIC_PROJECT_ID,
                    expected_project_number=SYNTHETIC_PROJECT_NUMBER,
                    workload_service_accounts=[SYNTHETIC_WORKLOAD_ACCOUNT],
                )

    def test_bundle_symlink_is_rejected_even_when_target_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self._write_private_evidence(
                directory,
                json.dumps(_offline_admin_evidence()),
            )
            link = Path(directory) / "evidence-link.json"
            os.symlink(target, link)

            with self.assertRaisesRegex(
                ContractError,
                "regular non-symlink",
            ):
                validate_offline_admin_evidence_file(
                    link,
                    expected_project_id=SYNTHETIC_PROJECT_ID,
                    expected_project_number=SYNTHETIC_PROJECT_NUMBER,
                    workload_service_accounts=[SYNTHETIC_WORKLOAD_ACCOUNT],
                )

    def test_bundle_stale_or_future_capture_time_is_rejected(self) -> None:
        cases = {
            "stale": SYNTHETIC_CAPTURED_AT + timedelta(hours=24, seconds=1),
            "future": SYNTHETIC_CAPTURED_AT - timedelta(seconds=1),
        }
        for name, observed_at in cases.items():
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    ContractError,
                    "stale|future",
                ),
            ):
                validate_offline_admin_evidence(
                    _offline_admin_evidence(),
                    expected_project_id=SYNTHETIC_PROJECT_ID,
                    expected_project_number=SYNTHETIC_PROJECT_NUMBER,
                    workload_service_accounts=[SYNTHETIC_WORKLOAD_ACCOUNT],
                    now=observed_at,
                )

    def test_bundle_rejects_duplicate_and_unrelated_scopes(self) -> None:
        duplicate = _offline_admin_evidence()
        duplicate["ancestors"].append(copy.deepcopy(duplicate["ancestors"][0]))
        unrelated = _offline_admin_evidence()
        unrelated["reviewedBindings"][0]["scope"] = "organizations/123123123"

        for name, document in (
            ("duplicate", duplicate),
            ("unrelated", unrelated),
        ):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    ContractError,
                    "duplicate|unrelated",
                ),
            ):
                self._validate(document)

    def test_bundle_rejects_public_group_and_domain_members(self) -> None:
        for member in (
            "allUsers",
            "group:admins@example.invalid",
            "domain:example.invalid",
        ):
            with self.subTest(member=member):
                document = _offline_admin_evidence()
                document["ancestors"][0]["policy"]["bindings"][0]["members"] = [member]
                document["reviewedBindings"][0]["member"] = member

                with self.assertRaisesRegex(
                    ContractError,
                    "public|group/domain|reviewed binding inventory",
                ):
                    self._validate(document)

    def test_bundle_rejects_every_unreviewed_binding(self) -> None:
        document = _offline_admin_evidence()
        document["reviewedBindings"] = []

        with self.assertRaisesRegex(
            ContractError,
            "inherited-IAM audit failed",
        ):
            self._validate(document)

    def test_bundle_v1_accepts_only_one_declared_organization(self) -> None:
        document = _offline_admin_evidence()
        document["ancestors"].insert(
            0,
            {
                "scope": "folders/123456789",
                "policy": {"bindings": []},
                "rolePermissions": {},
            },
        )

        with self.assertRaisesRegex(
            ContractError,
            "exactly one declared organization",
        ):
            self._validate(document)

    def test_bundle_rejects_broad_or_direct_workload_principals(self) -> None:
        members = (
            (
                "principalSet://cloudresourcemanager.googleapis.com/"
                "organizations/987654321/type/ServiceAccount"
            ),
            f"serviceAccount:{SYNTHETIC_WORKLOAD_ACCOUNT}",
        )
        for member in members:
            with self.subTest(member=member):
                document = _offline_admin_evidence()
                document["ancestors"][0]["policy"]["bindings"][0]["members"] = [member]
                document["reviewedBindings"][0]["member"] = member

                with self.assertRaisesRegex(
                    ContractError,
                    "federated, deleted, or opaque principals|workload accounts",
                ):
                    self._validate(document)

    def test_bundle_rejects_all_federated_and_deleted_principal_variants(
        self,
    ) -> None:
        members = (
            (
                "principalSet://iam.googleapis.com/projects/72919926064/"
                "locations/global/workloadIdentityPools/github/*"
            ),
            (
                "deleted:principalSet://iam.googleapis.com/projects/72919926064/"
                "locations/global/workloadIdentityPools/github/*?uid=123"
            ),
            (
                "principal://iam.googleapis.com/projects/72919926064/"
                "locations/global/workloadIdentityPools/github/subject/example"
            ),
            "deleted:user:former@example.invalid?uid=123",
            (
                "deleted:serviceAccount:former@festive-ally-503605-v7."
                "iam.gserviceaccount.com?uid=123"
            ),
        )
        for member in members:
            with self.subTest(member=member):
                document = _offline_admin_evidence()
                document["ancestors"][0]["policy"]["bindings"][0]["members"] = [member]
                document["reviewedBindings"][0]["member"] = member

                with self.assertRaisesRegex(
                    ContractError,
                    "federated, deleted, or opaque principals",
                ):
                    self._validate(document)

    def test_bundle_rejects_custom_role_from_another_project(self) -> None:
        document = _offline_admin_evidence()
        unrelated_role = "projects/unrelated-project/roles/operator"
        binding = document["ancestors"][0]["policy"]["bindings"][0]
        binding["role"] = unrelated_role
        document["ancestors"][0]["rolePermissions"] = {
            unrelated_role: ["iam.serviceAccounts.actAs"]
        }
        document["reviewedBindings"][0] = _reviewed_binding(
            scope="organizations/987654321",
            role=unrelated_role,
            member="user:reviewer@example.invalid",
            permissions=["iam.serviceAccounts.actAs"],
        )

        with self.assertRaisesRegex(
            ContractError,
            "project custom roles are forbidden",
        ):
            self._validate(document)

    def test_bundle_rejects_target_project_custom_role_in_ancestor(self) -> None:
        document = _offline_admin_evidence()
        target_role = f"projects/{SYNTHETIC_PROJECT_ID}/roles/operator"
        binding = document["ancestors"][0]["policy"]["bindings"][0]
        binding["role"] = target_role
        document["ancestors"][0]["rolePermissions"] = {
            target_role: ["logging.logEntries.list"]
        }
        document["reviewedBindings"][0] = _reviewed_binding(
            scope="organizations/987654321",
            role=target_role,
            member="user:reviewer@example.invalid",
            permissions=["logging.logEntries.list"],
        )

        with self.assertRaisesRegex(
            ContractError,
            "project custom roles are forbidden",
        ):
            self._validate(document)

    def test_bundle_rejects_dangerous_or_unknown_permission_when_reviewed(
        self,
    ) -> None:
        for permission in (
            "iam.serviceAccounts.actAs",
            "resourcemanager.projects.delete",
        ):
            with self.subTest(permission=permission):
                document = _offline_admin_evidence()
                role = "roles/syntheticOperator"
                document["ancestors"][0]["policy"]["bindings"][0]["role"] = role
                document["ancestors"][0]["rolePermissions"] = {role: [permission]}
                document["reviewedBindings"][0] = _reviewed_binding(
                    scope="organizations/987654321",
                    role=role,
                    member="user:reviewer@example.invalid",
                )

                with self.assertRaisesRegex(
                    ContractError,
                    "dangerous inherited permission",
                ):
                    self._validate(document)

    def test_bundle_rejects_duplicate_json_keys(self) -> None:
        serialized = json.dumps(_offline_admin_evidence())
        duplicated = serialized.replace(
            '"schemaVersion":',
            '"schemaVersion":"duplicate.invalid","schemaVersion":',
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            evidence_path = self._write_private_evidence(directory, duplicated)

            with self.assertRaisesRegex(ContractError, "duplicate JSON key"):
                validate_offline_admin_evidence_file(
                    evidence_path,
                    expected_project_id=SYNTHETIC_PROJECT_ID,
                    expected_project_number=SYNTHETIC_PROJECT_NUMBER,
                    workload_service_accounts=[SYNTHETIC_WORKLOAD_ACCOUNT],
                    now=SYNTHETIC_CAPTURED_AT + timedelta(hours=1),
                )

    def test_bundle_rejects_git_worktree_location(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            git_root = Path(directory)
            (git_root / ".git").mkdir()
            evidence_path = self._write_private_evidence(
                directory,
                json.dumps(_offline_admin_evidence()),
            )

            with self.assertRaisesRegex(
                ContractError,
                "outside every Git worktree",
            ):
                validate_offline_admin_evidence_file(
                    evidence_path,
                    expected_project_id=SYNTHETIC_PROJECT_ID,
                    expected_project_number=SYNTHETIC_PROJECT_NUMBER,
                    workload_service_accounts=[SYNTHETIC_WORKLOAD_ACCOUNT],
                    now=SYNTHETIC_CAPTURED_AT + timedelta(hours=1),
                )


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
