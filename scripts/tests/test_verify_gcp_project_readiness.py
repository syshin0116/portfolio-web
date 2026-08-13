from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ops_foundation_contract import (
    EXPECTED_ISSUER,
    EXPECTED_LIVE_ATTRIBUTE_MAPPINGS,
    EXPECTED_LIVE_CONDITIONS,
)
from scripts.verify_gcp_project_readiness import (
    BUCKET_DISCOVERY_COMMAND,
    BUILDER_SA,
    CLOUD_RUN_DELIVERY_ROLE,
    CLOUD_RUN_SERVICE_AGENT,
    CLOUD_SCHEDULER_SERVICE_AGENT,
    EXPECTED_GCLOUD_ACCOUNT_SHA256,
    FIXED_GCLOUD_COMMANDS,
    GCLOUD_ACCOUNT_ENV,
    GCloudReader,
    JOB_SPECS,
    LEGACY_REGION,
    MAINTENANCE_SCHEDULER_SA,
    PREVIEW_BUILDER_SA,
    PREVIEW_DEPLOYER_SA,
    PREVIEW_MIGRATOR_SA,
    PREVIEW_RUNTIME_SA,
    PRODUCTION_DEPLOYER_SA,
    PRODUCTION_MIGRATOR_SA,
    PRODUCTION_RUNTIME_ENV,
    PRODUCTION_RUNTIME_SA,
    PROJECT_ID,
    PROJECT_NUMBER,
    REGION,
    REQUIRED_APIS,
    SCHEDULED_MAINTENANCE_DELIVERY_ROLE,
    SERVICE_SPECS,
    STATE_BUCKET,
    STATE_BUCKET_COMMANDS,
    STATE_OBJECT,
    WORKLOAD_SERVICE_ACCOUNTS,
    ReadinessError,
    is_allowed_gcloud_command,
    validate_readiness_source_contract,
    verify_exact_project_readiness,
)

TEST_ACCOUNT = "reviewed-test-account@example.test"
TEST_ACCOUNT_SHA256 = hashlib.sha256(TEST_ACCOUNT.encode()).hexdigest()
EXTRA_AUDIT_SA = f"extra-audit@{PROJECT_ID}.iam.gserviceaccount.com"


def _policy(*pairs: tuple[str, str]) -> dict[str, object]:
    bindings: dict[str, list[str]] = {}
    for role, member in pairs:
        bindings.setdefault(role, []).append(member)
    return {
        "bindings": [
            {"role": role, "members": members}
            for role, members in sorted(bindings.items())
        ]
    }


def _provider(provider_id: str) -> dict[str, object]:
    disabled = provider_id == "github-preview"
    return {
        "name": (
            f"projects/{PROJECT_NUMBER}/locations/global/"
            f"workloadIdentityPools/github/providers/{provider_id}"
        ),
        "state": "ACTIVE",
        "disabled": disabled,
        "attributeCondition": EXPECTED_LIVE_CONDITIONS[provider_id],
        "attributeMapping": EXPECTED_LIVE_ATTRIBUTE_MAPPINGS[provider_id],
        "oidc": {"issuerUri": EXPECTED_ISSUER},
    }


def _environment(
    plain: dict[str, str], secrets: dict[str, str]
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = [
        {"name": name, "value": value} for name, value in plain.items()
    ]
    entries.extend(
        {
            "name": name,
            "valueFrom": {"secretKeyRef": {"name": secret, "key": str(index + 11)}},
        }
        for index, (name, secret) in enumerate(secrets.items())
    )
    return entries


def _service(service: str) -> dict[str, object]:
    spec = SERVICE_SPECS[service]
    return {
        "metadata": {
            "name": service,
            "annotations": {"run.googleapis.com/ingress": "all"},
        },
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "autoscaling.knative.dev/maxScale": "1",
                        "autoscaling.knative.dev/minScale": "0",
                        "run.googleapis.com/execution-environment": "gen2",
                    }
                },
                "spec": {
                    "serviceAccountName": spec["runtime"],
                    "containerConcurrency": 8,
                    "timeoutSeconds": 300,
                    "containers": [
                        {
                            "name": "agent",
                            "image": (
                                f"{REGION}-docker.pkg.dev/{PROJECT_ID}/"
                                f"{spec['repository']}/agent@sha256:" + "a" * 64
                            ),
                            "command": ["uvicorn"],
                            "args": [
                                "aegra_api.main:app",
                                "--host",
                                "0.0.0.0",
                                "--port",
                                "8080",
                                "--workers",
                                "1",
                            ],
                            "env": _environment(
                                spec["plain_env"],  # type: ignore[arg-type]
                                spec["secrets"],  # type: ignore[arg-type]
                            ),
                        }
                    ],
                },
            }
        },
    }


def _job(job: str) -> dict[str, object]:
    spec = JOB_SPECS[job]
    return {
        "metadata": {"name": job},
        "spec": {
            "template": {
                "spec": {
                    "parallelism": 1,
                    "taskCount": 1,
                    "template": {
                        "spec": {
                            "serviceAccountName": spec["service_account"],
                            "maxRetries": 0,
                            "timeoutSeconds": spec["timeout"],
                            "containers": [
                                {
                                    "name": spec["container"],
                                    "image": (
                                        f"{REGION}-docker.pkg.dev/{PROJECT_ID}/"
                                        f"{spec['repository']}/agent@sha256:" + "b" * 64
                                    ),
                                    "command": ["python"],
                                    "args": ["-m", spec["module"]],
                                    "env": _environment(
                                        {
                                            "ENV_MODE": "PRODUCTION",
                                            "RUN_MIGRATIONS_ON_STARTUP": "false",
                                        },
                                        {"DATABASE_URL": spec["secret"]},
                                    ),
                                }
                            ],
                        }
                    },
                }
            }
        },
    }


class FakeRead:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.validated_accounts: frozenset[str] = frozenset()
        self.state_bucket_trusted = False
        self.responses = self._responses()
        self.user_key_output = ""
        self.user_key_outputs: dict[str, str] = {}

    @staticmethod
    def _artifact(repository: str, *, region: str = REGION) -> dict[str, object]:
        if repository == "agent":
            delete_id, age, keep_id, count = (
                "delete-after-90-days",
                "7776000s",
                "keep-last-30",
                30,
            )
        else:
            delete_id, age, keep_id, count = (
                "delete-after-14-days",
                "1209600s",
                "keep-last-20",
                20,
            )
        return {
            "name": (
                f"projects/{PROJECT_ID}/locations/{region}/repositories/{repository}"
            ),
            "format": "DOCKER",
            "mode": "STANDARD_REPOSITORY",
            "dockerConfig": {"immutableTags": False},
            "cleanupPolicyDryRun": False,
            "cleanupPolicies": {
                delete_id: {
                    "id": delete_id,
                    "action": "DELETE",
                    "condition": {"tagState": "ANY", "olderThan": age},
                },
                keep_id: {
                    "id": keep_id,
                    "action": "KEEP",
                    "mostRecentVersions": {"keepCount": count},
                },
            },
        }

    @staticmethod
    def _service_account_policy(account: str) -> dict[str, object]:
        act_as = {
            PRODUCTION_RUNTIME_SA: PRODUCTION_DEPLOYER_SA,
            PREVIEW_RUNTIME_SA: PREVIEW_DEPLOYER_SA,
            PRODUCTION_MIGRATOR_SA: PRODUCTION_DEPLOYER_SA,
            PREVIEW_MIGRATOR_SA: PREVIEW_DEPLOYER_SA,
        }
        federation = {
            PREVIEW_DEPLOYER_SA: "preview-deployer",
            PRODUCTION_DEPLOYER_SA: "production-deployer",
            BUILDER_SA: "production-builder",
            PREVIEW_BUILDER_SA: "preview-builder",
        }
        if account in act_as:
            return _policy(
                (
                    "roles/iam.serviceAccountUser",
                    f"serviceAccount:{act_as[account]}",
                )
            )
        if account in federation:
            role = federation[account]
            return _policy(
                (
                    "roles/iam.workloadIdentityUser",
                    "principalSet://iam.googleapis.com/projects/"
                    f"{PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/"
                    f"attribute.delivery_role/{role}",
                )
            )
        return _policy()

    def _responses(self) -> dict[tuple[str, ...], str]:
        responses: dict[tuple[str, ...], object] = {
            ("projects", "describe", PROJECT_ID, "--format=json"): {
                "projectId": PROJECT_ID,
                "projectNumber": PROJECT_NUMBER,
                "lifecycleState": "ACTIVE",
            },
            ("projects", "get-iam-policy", PROJECT_ID, "--format=json"): _policy(
                (
                    "roles/cloudscheduler.serviceAgent",
                    f"serviceAccount:{CLOUD_SCHEDULER_SERVICE_AGENT}",
                ),
            ),
            (
                "iam",
                "roles",
                "describe",
                "cloudRunAgentDelivery",
                "--format=json",
            ): {
                "name": CLOUD_RUN_DELIVERY_ROLE,
                "stage": "GA",
                "includedPermissions": [
                    "run.jobs.get",
                    "run.jobs.run",
                    "run.jobs.update",
                    "run.operations.get",
                    "run.revisions.get",
                    "run.services.get",
                    "run.services.update",
                ],
            },
            (
                "iam",
                "roles",
                "describe",
                "cloudRunScheduledMaintenanceDelivery",
                "--format=json",
            ): {
                "name": SCHEDULED_MAINTENANCE_DELIVERY_ROLE,
                "stage": "GA",
                "includedPermissions": [
                    "run.jobs.get",
                    "run.jobs.update",
                    "run.operations.get",
                ],
            },
            ("services", "list", "--enabled", "--format=value(config.name)"): (
                "\n".join(sorted(REQUIRED_APIS)) + "\n"
            ),
            (
                "storage",
                "buckets",
                "list",
                f"--filter=name={STATE_BUCKET}",
                "--format=json(name,projectNumber)",
            ): [{"name": STATE_BUCKET, "projectNumber": PROJECT_NUMBER}],
            (
                "storage",
                "buckets",
                "describe",
                f"gs://{STATE_BUCKET}",
                "--format=json",
            ): {
                "name": STATE_BUCKET,
                "projectNumber": PROJECT_NUMBER,
                "location": LEGACY_REGION.upper(),
                "iamConfiguration": {
                    "publicAccessPrevention": "enforced",
                    "uniformBucketLevelAccess": {"enabled": True},
                },
                "versioning": {"enabled": True},
                "softDeletePolicy": {"retentionDurationSeconds": "2592000"},
            },
            (
                "storage",
                "buckets",
                "get-iam-policy",
                f"gs://{STATE_BUCKET}",
                "--format=json",
            ): _policy(("roles/storage.admin", "user:owner@example.test")),
            (
                "storage",
                "objects",
                "describe",
                f"gs://{STATE_BUCKET}/{STATE_OBJECT}",
                "--format=json",
            ): {
                "bucket": STATE_BUCKET,
                "name": STATE_OBJECT,
                "generation": "1",
                "size": "1024",
            },
            ("iam", "service-accounts", "list", "--format=json"): [
                {
                    "email": account,
                    "name": f"projects/{PROJECT_ID}/serviceAccounts/{account}",
                    "disabled": False,
                }
                for account in sorted(WORKLOAD_SERVICE_ACCOUNTS | {EXTRA_AUDIT_SA})
            ],
            (
                "iam",
                "workload-identity-pools",
                "describe",
                "github",
                "--location",
                "global",
                "--format=json",
            ): {
                "name": (
                    f"projects/{PROJECT_NUMBER}/locations/global/"
                    "workloadIdentityPools/github"
                ),
                "state": "ACTIVE",
                "disabled": False,
            },
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
            ): [_provider("github-preview"), _provider("github-production")],
            (
                "scheduler",
                "jobs",
                "describe",
                "agent-guest-maintenance",
                "--location",
                REGION,
                "--format=json",
            ): {
                "name": (
                    f"projects/{PROJECT_ID}/locations/{REGION}/"
                    "jobs/agent-guest-maintenance"
                ),
                "schedule": "*/15 * * * *",
                "timeZone": "Etc/UTC",
                "attemptDeadline": "60s",
                "state": "ENABLED",
                "retryConfig": {"retryCount": 0},
                "httpTarget": {
                    "httpMethod": "POST",
                    "uri": (
                        "https://run.googleapis.com/v2/projects/"
                        f"{PROJECT_ID}/locations/{REGION}/"
                        "jobs/agent-scheduled-maintenance:run"
                    ),
                    "body": "e30=",
                    "headers": {"Content-Type": "application/json"},
                    "oauthToken": {
                        "serviceAccountEmail": MAINTENANCE_SCHEDULER_SA,
                        "scope": "https://www.googleapis.com/auth/cloud-platform",
                    },
                },
            },
        }
        for repository, expected in {
            "agent": _policy(
                (
                    "roles/artifactregistry.reader",
                    f"serviceAccount:{CLOUD_RUN_SERVICE_AGENT}",
                ),
                (
                    "roles/artifactregistry.reader",
                    f"serviceAccount:{PRODUCTION_DEPLOYER_SA}",
                ),
                (
                    "roles/artifactregistry.writer",
                    f"serviceAccount:{BUILDER_SA}",
                ),
            ),
            "agent-preview": _policy(
                (
                    "roles/artifactregistry.reader",
                    f"serviceAccount:{CLOUD_RUN_SERVICE_AGENT}",
                ),
                (
                    "roles/artifactregistry.reader",
                    f"serviceAccount:{PREVIEW_DEPLOYER_SA}",
                ),
                (
                    "roles/artifactregistry.writer",
                    f"serviceAccount:{PREVIEW_BUILDER_SA}",
                ),
            ),
        }.items():
            suffix = (repository, "--location", REGION, "--format=json")
            responses[("artifacts", "repositories", "describe", *suffix)] = (
                self._artifact(repository)
            )
            responses[("artifacts", "repositories", "get-iam-policy", *suffix)] = (
                expected
            )
            legacy_suffix = (
                repository,
                "--location",
                LEGACY_REGION,
                "--format=json",
            )
            responses[("artifacts", "repositories", "describe", *legacy_suffix)] = (
                self._artifact(repository, region=LEGACY_REGION)
            )
            responses[
                ("artifacts", "repositories", "get-iam-policy", *legacy_suffix)
            ] = expected
        for account in WORKLOAD_SERVICE_ACCOUNTS:
            responses[
                (
                    "iam",
                    "service-accounts",
                    "get-iam-policy",
                    account,
                    "--format=json",
                )
            ] = self._service_account_policy(account)
        secret_accounts = {
            "agent-auth-secret": PRODUCTION_RUNTIME_SA,
            "agent-database-url": PRODUCTION_RUNTIME_SA,
            "anthropic-api-key": None,
            "langsmith-api-key": None,
            "openai-api-key": PRODUCTION_RUNTIME_SA,
            "agent-migration-database-url": PRODUCTION_MIGRATOR_SA,
            "agent-preview-anthropic-api-key": PREVIEW_RUNTIME_SA,
            "agent-preview-auth-secret": PREVIEW_RUNTIME_SA,
            "agent-preview-database-url": PREVIEW_RUNTIME_SA,
            "agent-preview-langsmith-api-key": PREVIEW_RUNTIME_SA,
            "agent-preview-migration-database-url": PREVIEW_MIGRATOR_SA,
        }
        for secret, account in secret_accounts.items():
            responses[("secrets", "describe", secret, "--format=json")] = {
                "name": f"projects/{PROJECT_NUMBER}/secrets/{secret}",
                "replication": {"automatic": {}},
            }
            responses[("secrets", "get-iam-policy", secret, "--format=json")] = (
                _policy()
                if account is None
                else _policy(
                    (
                        "roles/secretmanager.secretAccessor",
                        f"serviceAccount:{account}",
                    )
                )
            )
        for provider in ("github-preview", "github-production"):
            responses[
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
            ] = _provider(provider)
        for service, spec in SERVICE_SPECS.items():
            suffix = (service, "--region", REGION, "--format=json")
            responses[("run", "services", "describe", *suffix)] = _service(service)
            responses[("run", "services", "get-iam-policy", *suffix)] = _policy(
                (
                    CLOUD_RUN_DELIVERY_ROLE,
                    f"serviceAccount:{spec['deployer']}",
                ),
                ("roles/run.invoker", "allUsers"),
            )
        for job, spec in JOB_SPECS.items():
            suffix = (job, "--region", REGION, "--format=json")
            responses[("run", "jobs", "describe", *suffix)] = _job(job)
            pairs = [
                (
                    spec["delivery_role"],
                    f"serviceAccount:{spec['deployer']}",
                )
            ]
            if spec["scheduler"] is not None:
                pairs.append(
                    (
                        "roles/run.invoker",
                        f"serviceAccount:{spec['scheduler']}",
                    )
                )
            responses[("run", "jobs", "get-iam-policy", *suffix)] = _policy(*pairs)
        return {
            command: response
            if isinstance(response, str)
            else json.dumps(response, separators=(",", ":"))
            for command, response in responses.items()
        }

    def trust(self, accounts: object) -> None:
        self.validated_accounts = frozenset(accounts)  # type: ignore[arg-type]

    def trust_bucket(self) -> None:
        self.state_bucket_trusted = True

    def __call__(self, command: tuple[str, ...]) -> str:
        self.calls.append(command)
        if command[:4] == (
            "iam",
            "service-accounts",
            "keys",
            "list",
        ):
            return self.user_key_outputs.get(command[5], self.user_key_output)
        try:
            return self.responses[command]
        except KeyError as exc:
            raise AssertionError(f"unexpected exact-project read: {command!r}") from exc


class ExactProjectCommandBoundaryTests(unittest.TestCase):
    def test_pinned_literal_oracle_matches_source_and_command_catalogue(self) -> None:
        validate_readiness_source_contract()

    def test_literal_oracle_rejects_identity_and_inventory_mutations(self) -> None:
        mutations = (
            ("PROJECT_ID", "another-project", "project"),
            ("PROJECT_NUMBER", "999", "project"),
            ("REGION", "us-central1", "project"),
            (
                "REQUIRED_APIS",
                REQUIRED_APIS - {"cloudscheduler.googleapis.com"},
                "inventory",
            ),
            (
                "WORKLOAD_SERVICE_ACCOUNTS",
                WORKLOAD_SERVICE_ACCOUNTS - {MAINTENANCE_SCHEDULER_SA},
                "inventory",
            ),
            (
                "SERVICE_SPECS",
                {key: value for key, value in SERVICE_SPECS.items() if key != "agent"},
                "inventory",
            ),
            (
                "JOB_SPECS",
                {
                    key: value
                    for key, value in JOB_SPECS.items()
                    if key != "agent-scheduled-maintenance"
                },
                "inventory",
            ),
        )
        for name, value, message in mutations:
            with (
                self.subTest(name=name),
                patch(f"scripts.verify_gcp_project_readiness.{name}", value),
            ):
                with self.assertRaisesRegex(ReadinessError, message):
                    validate_readiness_source_contract()

    def test_literal_oracle_rejects_removed_secret_and_added_command(self) -> None:
        from scripts import verify_gcp_project_readiness as readiness

        with patch.object(
            readiness,
            "SECRET_POLICIES",
            {
                key: value
                for key, value in readiness.SECRET_POLICIES.items()
                if key != "openai-api-key"
            },
        ):
            with self.assertRaisesRegex(ReadinessError, "inventory"):
                validate_readiness_source_contract()
        with patch.object(
            readiness,
            "FIXED_GCLOUD_COMMANDS",
            readiness.FIXED_GCLOUD_COMMANDS
            | {
                (
                    "scheduler",
                    "jobs",
                    "run",
                    "agent-guest-maintenance",
                    "--location",
                    REGION,
                )
            },
        ):
            with self.assertRaisesRegex(ReadinessError, "literal oracle"):
                validate_readiness_source_contract()

    def test_literal_oracle_rejects_old_production_guest_reservation(self) -> None:
        from scripts import verify_gcp_project_readiness as readiness

        self.assertEqual(
            "51892", PRODUCTION_RUNTIME_ENV["GUEST_RUN_RESERVATION_MICRO_USD"]
        )
        with patch.object(
            readiness,
            "PRODUCTION_RUNTIME_ENV",
            readiness.PRODUCTION_RUNTIME_ENV
            | {"GUEST_RUN_RESERVATION_MICRO_USD": "6892"},
        ):
            with self.assertRaisesRegex(ReadinessError, "anonymous runtime"):
                validate_readiness_source_contract()

    def test_catalog_accepts_only_the_exact_project_read(self) -> None:
        self.assertTrue(
            is_allowed_gcloud_command(
                ("projects", "describe", PROJECT_ID, "--format=json"),
                validated_service_accounts=frozenset(),
            )
        )
        for command in (
            ("projects", "describe", "jinjoo", "--format=json"),
            ("projects", "list", "--format=json"),
            ("organizations", "get-iam-policy", "123", "--format=json"),
            ("folders", "get-iam-policy", "123", "--format=json"),
            ("services", "enable", "run.googleapis.com"),
        ):
            with self.subTest(command=command):
                self.assertFalse(
                    is_allowed_gcloud_command(
                        command,
                        validated_service_accounts=frozenset(),
                    )
                )

    def test_fixed_catalog_contains_only_read_verbs_and_exact_targets(self) -> None:
        for command in FIXED_GCLOUD_COMMANDS:
            with self.subTest(command=command):
                self.assertNotIn(command[0], {"organizations", "folders"})
                self.assertFalse(
                    any(
                        token
                        in {
                            "add-iam-policy-binding",
                            "apply",
                            "create",
                            "delete",
                            "disable",
                            "enable",
                            "execute",
                            "remove-iam-policy-binding",
                            "run-job",
                            "set-iam-policy",
                            "update",
                        }
                        for token in command
                    )
                )
                if command[0] == "projects":
                    self.assertEqual(PROJECT_ID, command[2])

    def test_global_bucket_name_reads_require_exact_project_discovery(self) -> None:
        self.assertTrue(
            is_allowed_gcloud_command(
                BUCKET_DISCOVERY_COMMAND,
                validated_service_accounts=frozenset(),
            )
        )
        for command in STATE_BUCKET_COMMANDS:
            with self.subTest(command=command):
                self.assertFalse(
                    is_allowed_gcloud_command(
                        command,
                        validated_service_accounts=frozenset(),
                    )
                )
                self.assertTrue(
                    is_allowed_gcloud_command(
                        command,
                        validated_service_accounts=frozenset(),
                        trusted_state_bucket=True,
                    )
                )

    def test_full_verification_requests_only_catalogued_commands(self) -> None:
        reader = FakeRead()

        verify_exact_project_readiness(
            reader,
            trust_service_accounts=reader.trust,
            trust_state_bucket=reader.trust_bucket,
        )

        key_reads = {
            command
            for command in reader.calls
            if command[:4] == ("iam", "service-accounts", "keys", "list")
        }
        fixed_reads = set(reader.calls) - key_reads
        self.assertEqual(FIXED_GCLOUD_COMMANDS, fixed_reads)
        self.assertEqual(len(reader.validated_accounts), len(key_reads))
        self.assertEqual(
            reader.validated_accounts,
            frozenset(command[5] for command in key_reads),
        )
        for command in key_reads:
            self.assertEqual(1, reader.calls.count(command))
        for command in reader.calls:
            with self.subTest(command=command):
                self.assertTrue(
                    is_allowed_gcloud_command(
                        command,
                        validated_service_accounts=reader.validated_accounts,
                        trusted_state_bucket=reader.state_bucket_trusted,
                    )
                )


class GCloudReaderTests(unittest.TestCase):
    def test_account_digest_is_pinned_without_storing_the_account(self) -> None:
        self.assertEqual(
            EXPECTED_GCLOUD_ACCOUNT_SHA256,
            "8d855626e841898add1ba4e401a4c7789a97b0f30d1ca837a3c6af90b1d48695",
        )

    def test_google_environment_override_fails_before_binary_resolution(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    GCLOUD_ACCOUNT_ENV: TEST_ACCOUNT,
                    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/forbidden.json",
                },
                clear=True,
            ),
            patch(
                "scripts.verify_gcp_project_readiness.validate_trusted_executable"
            ) as validate,
        ):
            with self.assertRaisesRegex(ReadinessError, "overrides are forbidden"):
                GCloudReader(Path("/missing/gcloud"))
        validate.assert_not_called()

    def test_wrong_account_fails_before_binary_resolution(self) -> None:
        with (
            patch.dict(
                os.environ,
                {GCLOUD_ACCOUNT_ENV: "owner@example.test"},
                clear=True,
            ),
            patch(
                "scripts.verify_gcp_project_readiness.validate_trusted_executable"
            ) as validate,
        ):
            with self.assertRaisesRegex(ReadinessError, "pinned identity"):
                GCloudReader(Path("/missing/gcloud"))
        validate.assert_not_called()

    def test_reader_injects_exact_globals_and_rejects_uncatalogued_request(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            binary = Path(directory) / "gcloud"
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o700)
            python = Path(directory) / "python3"
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o700)
            python_path = str(python.resolve())
            completed = subprocess.CompletedProcess(
                args=(), returncode=0, stdout="{}\n", stderr=""
            )
            with (
                patch.dict(
                    os.environ,
                    {
                        GCLOUD_ACCOUNT_ENV: TEST_ACCOUNT,
                        "HOME": "/tmp/forged-home",
                        "HTTPS_PROXY": "http://127.0.0.1:9",
                        "LD_PRELOAD": "/tmp/forged-loader.so",
                        "PATH": os.environ["PATH"],
                        "PYTHONPATH": "/tmp/forged-python",
                        "REQUESTS_CA_BUNDLE": "/tmp/forged-ca.pem",
                        "VIRTUAL_ENV": "/tmp/forged-venv",
                    },
                    clear=True,
                ),
                patch(
                    "scripts.verify_gcp_project_readiness."
                    "EXPECTED_GCLOUD_ACCOUNT_SHA256",
                    TEST_ACCOUNT_SHA256,
                ),
                patch(
                    "scripts.verify_gcp_project_readiness.sys.executable",
                    python_path,
                ),
                patch(
                    "scripts.verify_gcp_project_readiness.subprocess.run",
                    return_value=completed,
                ) as run,
            ):
                reader = GCloudReader(binary)
                reader(("projects", "describe", PROJECT_ID, "--format=json"))
                with self.assertRaisesRegex(ReadinessError, "not allowlisted"):
                    reader(("projects", "describe", "jinjoo", "--format=json"))

        run.assert_called_once()
        argv = run.call_args.args[0]
        self.assertEqual(
            (
                "--configuration=NONE",
                f"--account={TEST_ACCOUNT}",
                f"--project={PROJECT_ID}",
                "--quiet",
                "projects",
                "describe",
                PROJECT_ID,
                "--format=json",
            ),
            argv[1:],
        )
        self.assertNotIn("--billing-project", argv)
        self.assertIs(subprocess.DEVNULL, run.call_args.kwargs["stdin"])
        child_environment = run.call_args.kwargs["env"]
        self.assertEqual(
            {
                "CLOUDSDK_CORE_DISABLE_PROMPTS": "1",
                "CLOUDSDK_ENCODING": "UTF-8",
                "CLOUDSDK_PYTHON": python_path,
                "CLOUDSDK_PYTHON_ARGS": "-I -S",
                "HOME": str(Path.home().resolve()),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            },
            child_environment,
        )
        for hostile in (
            "CLOUDSDK_CONFIG",
            "HTTPS_PROXY",
            "LD_PRELOAD",
            "PYTHONPATH",
            "REQUESTS_CA_BUNDLE",
            "VIRTUAL_ENV",
        ):
            self.assertNotIn(hostile, child_environment)


class ExactProjectReadinessTests(unittest.TestCase):
    def _verify(self, fixture: FakeRead) -> None:
        verify_exact_project_readiness(
            fixture,
            trust_service_accounts=fixture.trust,
            trust_state_bucket=fixture.trust_bucket,
        )

    def test_cloud_run_service_omits_reserved_port_environment(self) -> None:
        self.assertNotIn("PORT", PRODUCTION_RUNTIME_ENV)
        for service, spec in SERVICE_SPECS.items():
            with self.subTest(service=service):
                self.assertNotIn("PORT", spec["plain_env"])

    def test_complete_exact_project_contract_passes(self) -> None:
        fixture = FakeRead()

        self._verify(fixture)

        self.assertTrue(fixture.calls)
        self.assertEqual(
            WORKLOAD_SERVICE_ACCOUNTS | {EXTRA_AUDIT_SA},
            fixture.validated_accounts,
        )
        for command in fixture.calls:
            with self.subTest(command=command):
                self.assertTrue(
                    is_allowed_gcloud_command(
                        command,
                        validated_service_accounts=fixture.validated_accounts,
                        trusted_state_bucket=fixture.state_bucket_trusted,
                    )
                )

    def test_scheduled_maintenance_delivery_role_rejects_execution_permission(
        self,
    ) -> None:
        fixture = FakeRead()
        command = (
            "iam",
            "roles",
            "describe",
            "cloudRunScheduledMaintenanceDelivery",
            "--format=json",
        )
        document = json.loads(fixture.responses[command])
        document["includedPermissions"].append("run.jobs.run")
        fixture.responses[command] = json.dumps(document)

        with self.assertRaisesRegex(ReadinessError, "non-executing role"):
            self._verify(fixture)

    def test_scheduled_maintenance_rejects_the_general_delivery_role(self) -> None:
        fixture = FakeRead()
        suffix = (
            "agent-scheduled-maintenance",
            "--region",
            REGION,
            "--format=json",
        )
        command = ("run", "jobs", "get-iam-policy", *suffix)
        fixture.responses[command] = json.dumps(
            _policy(
                (
                    CLOUD_RUN_DELIVERY_ROLE,
                    f"serviceAccount:{PRODUCTION_DEPLOYER_SA}",
                ),
                (
                    "roles/run.invoker",
                    f"serviceAccount:{MAINTENANCE_SCHEDULER_SA}",
                ),
            )
        )

        with self.assertRaisesRegex(ReadinessError, "IAM does not match"):
            self._verify(fixture)

    def test_project_describe_parent_field_is_ignored_without_scope_reads(self) -> None:
        fixture = FakeRead()
        command = ("projects", "describe", PROJECT_ID, "--format=json")
        project = json.loads(fixture.responses[command])
        project["parent"] = {"type": "organization", "id": "123456789"}
        fixture.responses[command] = json.dumps(project)

        self._verify(fixture)

        self.assertFalse(
            any(call[0] in {"organizations", "folders"} for call in fixture.calls)
        )

    def test_wrong_project_identity_fails_before_follow_up_reads(self) -> None:
        fixture = FakeRead()
        command = ("projects", "describe", PROJECT_ID, "--format=json")
        fixture.responses[command] = json.dumps(
            {
                "projectId": "jinjoo",
                "projectNumber": PROJECT_NUMBER,
                "lifecycleState": "ACTIVE",
            }
        )

        with self.assertRaisesRegex(ReadinessError, "exact target"):
            self._verify(fixture)

        self.assertEqual([command], fixture.calls)

    def test_wrong_bucket_owner_fails_before_state_object_read(self) -> None:
        fixture = FakeRead()
        command = (
            "storage",
            "buckets",
            "describe",
            f"gs://{STATE_BUCKET}",
            "--format=json",
        )
        document = json.loads(fixture.responses[command])
        document["projectNumber"] = "999"
        fixture.responses[command] = json.dumps(document)

        with self.assertRaisesRegex(ReadinessError, "bucket owner"):
            self._verify(fixture)

        self.assertNotIn(
            (
                "storage",
                "objects",
                "describe",
                f"gs://{STATE_BUCKET}/{STATE_OBJECT}",
                "--format=json",
            ),
            fixture.calls,
        )

    def test_state_bucket_foreign_kms_fails_before_state_object_read(self) -> None:
        fixture = FakeRead()
        command = (
            "storage",
            "buckets",
            "describe",
            f"gs://{STATE_BUCKET}",
            "--format=json",
        )
        document = json.loads(fixture.responses[command])
        document["encryption"] = {
            "defaultKmsKeyName": (
                "projects/jinjoo/locations/us-east4/keyRings/foreign/cryptoKeys/state"
            )
        }
        fixture.responses[command] = json.dumps(document)

        with self.assertRaisesRegex(ReadinessError, "Google-managed encryption"):
            self._verify(fixture)

        self.assertNotIn(
            (
                "storage",
                "objects",
                "describe",
                f"gs://{STATE_BUCKET}/{STATE_OBJECT}",
                "--format=json",
            ),
            fixture.calls,
        )

    def test_state_object_foreign_kms_key_fails(self) -> None:
        fixture = FakeRead()
        command = (
            "storage",
            "objects",
            "describe",
            f"gs://{STATE_BUCKET}/{STATE_OBJECT}",
            "--format=json",
        )
        document = json.loads(fixture.responses[command])
        document["kmsKeyName"] = (
            "projects/jinjoo/locations/us-east4/keyRings/foreign/cryptoKeys/state"
        )
        fixture.responses[command] = json.dumps(document)

        with self.assertRaisesRegex(ReadinessError, "Google-managed encryption"):
            self._verify(fixture)

    def test_bucket_ownership_is_discovered_before_global_name_reads(self) -> None:
        fixture = FakeRead()
        discovery = (
            "storage",
            "buckets",
            "list",
            f"--filter=name={STATE_BUCKET}",
            "--format=json(name,projectNumber)",
        )
        describe = (
            "storage",
            "buckets",
            "describe",
            f"gs://{STATE_BUCKET}",
            "--format=json",
        )

        self._verify(fixture)

        self.assertLess(fixture.calls.index(discovery), fixture.calls.index(describe))

    def test_foreign_bucket_discovery_fails_before_global_name_read(self) -> None:
        fixture = FakeRead()
        discovery = (
            "storage",
            "buckets",
            "list",
            f"--filter=name={STATE_BUCKET}",
            "--format=json(name,projectNumber)",
        )
        describe = (
            "storage",
            "buckets",
            "describe",
            f"gs://{STATE_BUCKET}",
            "--format=json",
        )
        fixture.responses[discovery] = json.dumps(
            [{"name": STATE_BUCKET, "projectNumber": "999"}]
        )

        with self.assertRaisesRegex(ReadinessError, "under the exact project"):
            self._verify(fixture)

        self.assertNotIn(describe, fixture.calls)

    def test_project_role_on_workload_identity_fails(self) -> None:
        fixture = FakeRead()
        command = ("projects", "get-iam-policy", PROJECT_ID, "--format=json")
        fixture.responses[command] = json.dumps(
            _policy(
                (
                    "roles/cloudscheduler.serviceAgent",
                    f"serviceAccount:{CLOUD_SCHEDULER_SERVICE_AGENT}",
                ),
                ("roles/viewer", f"serviceAccount:{PRODUCTION_RUNTIME_SA}"),
            )
        )

        with self.assertRaisesRegex(ReadinessError, "project-wide roles"):
            self._verify(fixture)

    def test_scheduler_service_agent_binding_must_be_unconditional(self) -> None:
        fixture = FakeRead()
        command = ("projects", "get-iam-policy", PROJECT_ID, "--format=json")
        policy = json.loads(fixture.responses[command])
        binding = next(
            item
            for item in policy["bindings"]
            if item["role"] == "roles/cloudscheduler.serviceAgent"
        )
        binding["condition"] = {
            "title": "never",
            "expression": "false",
        }
        fixture.responses[command] = json.dumps(policy)

        with self.assertRaisesRegex(ReadinessError, "must be unconditional"):
            self._verify(fixture)

    def test_user_managed_service_account_key_fails(self) -> None:
        fixture = FakeRead()
        fixture.user_key_output = "projects/x/serviceAccounts/y/keys/123\n"

        with self.assertRaisesRegex(ReadinessError, "user-managed key"):
            self._verify(fixture)

    def test_extra_inventory_account_user_managed_key_fails(self) -> None:
        fixture = FakeRead()
        fixture.user_key_outputs[EXTRA_AUDIT_SA] = (
            f"projects/{PROJECT_ID}/serviceAccounts/{EXTRA_AUDIT_SA}/keys/123\n"
        )

        with self.assertRaisesRegex(ReadinessError, "user-managed key"):
            self._verify(fixture)

        extra_key_read = (
            "iam",
            "service-accounts",
            "keys",
            "list",
            "--iam-account",
            EXTRA_AUDIT_SA,
            "--managed-by=user",
            "--format=value(name)",
        )
        self.assertEqual(1, fixture.calls.count(extra_key_read))

    def test_duplicate_service_account_inventory_fails_before_key_reads(self) -> None:
        fixture = FakeRead()
        command = ("iam", "service-accounts", "list", "--format=json")
        accounts = json.loads(fixture.responses[command])
        accounts.append(accounts[0])
        fixture.responses[command] = json.dumps(accounts)

        with self.assertRaisesRegex(ReadinessError, "escaped"):
            self._verify(fixture)

        self.assertFalse(
            any(
                call[:4] == ("iam", "service-accounts", "keys", "list")
                for call in fixture.calls
            )
        )

    def test_disabled_workload_service_account_fails_before_key_reads(self) -> None:
        fixture = FakeRead()
        command = ("iam", "service-accounts", "list", "--format=json")
        accounts = json.loads(fixture.responses[command])
        target = next(
            account for account in accounts if account["email"] == PRODUCTION_RUNTIME_SA
        )
        target["disabled"] = True
        fixture.responses[command] = json.dumps(accounts)

        with self.assertRaisesRegex(
            ReadinessError, "workload service account is disabled"
        ):
            self._verify(fixture)

        self.assertFalse(
            any(
                call[:4] == ("iam", "service-accounts", "keys", "list")
                for call in fixture.calls
            )
        )

    def test_unrelated_service_account_inventory_fails_before_key_reads(self) -> None:
        fixture = FakeRead()
        command = ("iam", "service-accounts", "list", "--format=json")
        accounts = json.loads(fixture.responses[command])
        accounts.append(
            {
                "email": "escaped@jinjoo.iam.gserviceaccount.com",
                "name": "projects/jinjoo/serviceAccounts/escaped@jinjoo.iam.gserviceaccount.com",
            }
        )
        fixture.responses[command] = json.dumps(accounts)

        with self.assertRaisesRegex(ReadinessError, "escaped"):
            self._verify(fixture)

        self.assertFalse(
            any(
                call[:4] == ("iam", "service-accounts", "keys", "list")
                for call in fixture.calls
            )
        )

    def test_extra_secret_accessor_fails(self) -> None:
        fixture = FakeRead()
        command = (
            "secrets",
            "get-iam-policy",
            "openai-api-key",
            "--format=json",
        )
        fixture.responses[command] = json.dumps(
            _policy(
                (
                    "roles/secretmanager.secretAccessor",
                    f"serviceAccount:{PRODUCTION_RUNTIME_SA}",
                ),
                (
                    "roles/secretmanager.secretAccessor",
                    f"serviceAccount:{PREVIEW_RUNTIME_SA}",
                ),
            )
        )

        with self.assertRaisesRegex(ReadinessError, "exact repository-owned"):
            self._verify(fixture)

    def test_dormant_production_secret_accessor_fails(self) -> None:
        fixture = FakeRead()
        command = (
            "secrets",
            "get-iam-policy",
            "anthropic-api-key",
            "--format=json",
        )
        fixture.responses[command] = json.dumps(
            _policy(
                (
                    "roles/secretmanager.secretAccessor",
                    f"serviceAccount:{PRODUCTION_RUNTIME_SA}",
                )
            )
        )

        with self.assertRaisesRegex(ReadinessError, "exact repository-owned"):
            self._verify(fixture)

    def test_active_and_legacy_artifact_iam_require_mirrored_bindings(self) -> None:
        for region in (REGION, LEGACY_REGION):
            with self.subTest(region=region):
                fixture = FakeRead()
                if region == REGION:
                    command = (
                        "artifacts",
                        "repositories",
                        "get-iam-policy",
                        "agent",
                        "--location",
                        region,
                        "--format=json",
                    )
                    fixture.responses[command] = json.dumps(
                        _policy(
                            (
                                "roles/artifactregistry.reader",
                                f"serviceAccount:{CLOUD_RUN_SERVICE_AGENT}",
                            ),
                            (
                                "roles/artifactregistry.reader",
                                f"serviceAccount:{PRODUCTION_DEPLOYER_SA}",
                            ),
                        )
                    )
                else:
                    for repository in ("agent", "agent-preview"):
                        command = (
                            "artifacts",
                            "repositories",
                            "get-iam-policy",
                            repository,
                            "--location",
                            region,
                            "--format=json",
                        )
                        fixture.responses[command] = json.dumps(_policy())

                with self.assertRaisesRegex(
                    ReadinessError,
                    "exact repository-owned bindings",
                ):
                    self._verify(fixture)

    def test_active_and_legacy_artifact_immutable_tags_true_fails(self) -> None:
        for region in (REGION, LEGACY_REGION):
            with self.subTest(region=region):
                fixture = FakeRead()
                command = (
                    "artifacts",
                    "repositories",
                    "describe",
                    "agent-preview",
                    "--location",
                    region,
                    "--format=json",
                )
                repository = json.loads(fixture.responses[command])
                repository["dockerConfig"]["immutableTags"] = True
                fixture.responses[command] = json.dumps(repository)

                with self.assertRaisesRegex(
                    ReadinessError,
                    "metadata or retention drifted",
                ):
                    self._verify(fixture)

    def test_artifact_cleanup_prefix_or_unknown_selector_fails(self) -> None:
        cases: dict[str, tuple[str, object]] = {
            "newerThan": ("condition", "3600s"),
            "tagPrefixes": ("condition", ["release-"]),
            "versionNamePrefixes": ("condition", ["agent-"]),
            "packageNamePrefixes": ("condition", ["agent"]),
            "keepPackageNamePrefixes": ("mostRecentVersions", ["agent"]),
            "unknown": ("condition", []),
        }
        for name, (target, value) in cases.items():
            with self.subTest(name=name):
                fixture = FakeRead()
                command = (
                    "artifacts",
                    "repositories",
                    "describe",
                    "agent",
                    "--location",
                    REGION,
                    "--format=json",
                )
                document = json.loads(fixture.responses[command])
                if name == "keepPackageNamePrefixes":
                    document["cleanupPolicies"]["keep-last-30"][target][
                        "packageNamePrefixes"
                    ] = value
                else:
                    key = "unexpectedSelector" if name == "unknown" else name
                    document["cleanupPolicies"]["delete-after-90-days"][target][key] = (
                        value
                    )
                fixture.responses[command] = json.dumps(document)

                with self.assertRaisesRegex(ReadinessError, "cleanup selector"):
                    self._verify(fixture)

    def test_artifact_repository_format_or_mode_drift_fails(self) -> None:
        for field, value in {
            "format": "MAVEN",
            "mode": "REMOTE_REPOSITORY",
        }.items():
            with self.subTest(field=field):
                fixture = FakeRead()
                command = (
                    "artifacts",
                    "repositories",
                    "describe",
                    "agent",
                    "--location",
                    REGION,
                    "--format=json",
                )
                document = json.loads(fixture.responses[command])
                document[field] = value
                fixture.responses[command] = json.dumps(document)

                with self.assertRaisesRegex(
                    ReadinessError, "identity, format, or mode"
                ):
                    self._verify(fixture)

    def test_artifact_repository_foreign_kms_key_fails(self) -> None:
        fixture = FakeRead()
        command = (
            "artifacts",
            "repositories",
            "describe",
            "agent",
            "--location",
            REGION,
            "--format=json",
        )
        document = json.loads(fixture.responses[command])
        document["kmsKeyName"] = (
            "projects/jinjoo/locations/us-east4/keyRings/foreign/cryptoKeys/agent"
        )
        fixture.responses[command] = json.dumps(document)

        with self.assertRaisesRegex(ReadinessError, "Google-managed encryption"):
            self._verify(fixture)

    def test_artifact_cleanup_missing_tag_state_fails(self) -> None:
        fixture = FakeRead()
        command = (
            "artifacts",
            "repositories",
            "describe",
            "agent",
            "--location",
            REGION,
            "--format=json",
        )
        document = json.loads(fixture.responses[command])
        del document["cleanupPolicies"]["delete-after-90-days"]["condition"]["tagState"]
        fixture.responses[command] = json.dumps(document)

        with self.assertRaisesRegex(ReadinessError, "metadata or retention"):
            self._verify(fixture)

    def test_artifact_cleanup_policy_ids_must_match_map_keys(self) -> None:
        cases = {
            "delete_mismatch": ("delete-after-90-days", "keep-last-30"),
            "keep_mismatch": ("keep-last-30", "delete-after-90-days"),
            "delete_missing": ("delete-after-90-days", None),
            "keep_missing": ("keep-last-30", None),
        }
        for name, (policy_key, policy_id) in cases.items():
            with self.subTest(name=name):
                fixture = FakeRead()
                command = (
                    "artifacts",
                    "repositories",
                    "describe",
                    "agent",
                    "--location",
                    REGION,
                    "--format=json",
                )
                document = json.loads(fixture.responses[command])
                policy = document["cleanupPolicies"][policy_key]
                if policy_id is None:
                    policy.pop("id")
                else:
                    policy["id"] = policy_id
                fixture.responses[command] = json.dumps(document)

                with self.assertRaisesRegex(
                    ReadinessError, "cleanup policy fields or IDs"
                ):
                    self._verify(fixture)

    def test_secret_foreign_cmek_or_expiration_fails(self) -> None:
        command = ("secrets", "describe", "openai-api-key", "--format=json")
        for name in ("foreign_cmek", "expiration"):
            with self.subTest(name=name):
                fixture = FakeRead()
                document = json.loads(fixture.responses[command])
                if name == "foreign_cmek":
                    document["replication"]["automatic"][
                        "customerManagedEncryption"
                    ] = {
                        "kmsKeyName": (
                            "projects/jinjoo/locations/us-east4/keyRings/foreign/"
                            "cryptoKeys/secrets"
                        )
                    }
                else:
                    document["expireTime"] = "2026-08-04T00:00:00Z"
                fixture.responses[command] = json.dumps(document)

                with self.assertRaisesRegex(ReadinessError, "encryption or expiration"):
                    self._verify(fixture)

    def test_cloud_run_service_nonzero_min_scale_fails(self) -> None:
        command = (
            "run",
            "services",
            "describe",
            "agent",
            "--region",
            REGION,
            "--format=json",
        )
        for name in ("revision", "service"):
            with self.subTest(name=name):
                fixture = FakeRead()
                service = json.loads(fixture.responses[command])
                if name == "revision":
                    annotations = service["spec"]["template"]["metadata"]["annotations"]
                    annotations["autoscaling.knative.dev/minScale"] = "1"
                else:
                    service["metadata"]["annotations"][
                        "run.googleapis.com/minScale"
                    ] = "1"
                fixture.responses[command] = json.dumps(service)

                with self.assertRaisesRegex(ReadinessError, "scaling boundary"):
                    self._verify(fixture)

    def test_cloud_run_job_task_fanout_fails(self) -> None:
        command = (
            "run",
            "jobs",
            "describe",
            "agent-maintenance",
            "--region",
            REGION,
            "--format=json",
        )
        for field in ("taskCount", "parallelism"):
            with self.subTest(field=field):
                fixture = FakeRead()
                job = json.loads(fixture.responses[command])
                job["spec"]["template"]["spec"][field] = 100
                fixture.responses[command] = json.dumps(job)

                with self.assertRaisesRegex(ReadinessError, "task fan-out"):
                    self._verify(fixture)

    def test_production_luna_spend_control_drift_fails(self) -> None:
        fixture = FakeRead()
        command = (
            "run",
            "services",
            "describe",
            "agent",
            "--region",
            REGION,
            "--format=json",
        )
        service = json.loads(fixture.responses[command])
        entries = service["spec"]["template"]["spec"]["containers"][0]["env"]
        next(
            entry
            for entry in entries
            if entry["name"] == "GUEST_DAILY_BUDGET_MICRO_USD"
        )["value"] = "500001"
        fixture.responses[command] = json.dumps(service)

        with self.assertRaisesRegex(ReadinessError, "guest boundary"):
            self._verify(fixture)

    def test_production_openai_secret_reference_is_required(self) -> None:
        fixture = FakeRead()
        command = (
            "run",
            "services",
            "describe",
            "agent",
            "--region",
            REGION,
            "--format=json",
        )
        service = json.loads(fixture.responses[command])
        entries = service["spec"]["template"]["spec"]["containers"][0]["env"]
        entries[:] = [entry for entry in entries if entry["name"] != "OPENAI_API_KEY"]
        fixture.responses[command] = json.dumps(service)

        with self.assertRaisesRegex(ReadinessError, "secret environment inventory"):
            self._verify(fixture)

    def test_preview_foundation_is_dormant_without_runtime_reads(self) -> None:
        self.assertEqual({"agent"}, set(SERVICE_SPECS))
        self.assertEqual(
            {
                "agent-migrate",
                "agent-grants",
                "agent-maintenance",
                "agent-scheduled-maintenance",
            },
            set(JOB_SPECS),
        )
        self.assertFalse(
            any(
                "agent-preview" in token
                for command in FIXED_GCLOUD_COMMANDS
                for token in command
                if command[:2] == ("run", "services")
            )
        )
        self.assertIn(PREVIEW_RUNTIME_SA, WORKLOAD_SERVICE_ACCOUNTS)

    def test_scheduler_must_be_enabled_after_launch_approval(self) -> None:
        fixture = FakeRead()
        command = (
            "scheduler",
            "jobs",
            "describe",
            "agent-guest-maintenance",
            "--location",
            REGION,
            "--format=json",
        )
        scheduler = json.loads(fixture.responses[command])
        scheduler["state"] = "PAUSED"
        fixture.responses[command] = json.dumps(scheduler)

        with self.assertRaisesRegex(ReadinessError, "Scheduler"):
            self._verify(fixture)

    def test_scheduler_rejects_the_release_validation_maintenance_job(self) -> None:
        fixture = FakeRead()
        command = (
            "scheduler",
            "jobs",
            "describe",
            "agent-guest-maintenance",
            "--location",
            REGION,
            "--format=json",
        )
        scheduler = json.loads(fixture.responses[command])
        scheduler["httpTarget"]["uri"] = (
            f"https://run.googleapis.com/v2/projects/{PROJECT_ID}/locations/"
            f"{REGION}/jobs/agent-maintenance:run"
        )
        fixture.responses[command] = json.dumps(scheduler)

        with self.assertRaisesRegex(ReadinessError, "Scheduler"):
            self._verify(fixture)

    def test_duplicate_json_keys_fail_closed(self) -> None:
        fixture = FakeRead()
        fixture.responses[("projects", "describe", PROJECT_ID, "--format=json")] = (
            '{"projectId":"festive-ally-503605-v7",'
            '"projectId":"jinjoo","projectNumber":"72919926064",'
            '"lifecycleState":"ACTIVE"}'
        )

        with self.assertRaisesRegex(ReadinessError, "duplicate key"):
            self._verify(fixture)


if __name__ == "__main__":
    unittest.main()
