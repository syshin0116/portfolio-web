from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "scripts/deploy_cloud_run.sh"
SOURCE_SHA = "1" * 40
DELIVERY_RUN_ID = "9876543210"
DELIVERY_RUN_ATTEMPT = "1"
IMAGE_DIGEST = (
    "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent@sha256:" + "2" * 64
)


class CloudRunDeliveryTests(unittest.TestCase):
    def _fixture(
        self, directory: str, *, fail_protocol: bool = False
    ) -> dict[str, str]:
        root = Path(directory)
        binary = root / "bin"
        binary.mkdir()
        state = root / "state.json"
        state.write_text(
            json.dumps(
                {
                    "latest_created": "agent-old",
                    "latest_ready": "agent-old",
                    "serving": "agent-old",
                    "smoke": False,
                }
            ),
            encoding="utf-8",
        )
        log = root / "operations.log"

        gcloud = binary / "gcloud"
        gcloud.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                state_path = Path(os.environ["FAKE_STATE"])
                log_path = Path(os.environ["FAKE_LOG"])
                args = sys.argv[1:]
                with log_path.open("a", encoding="utf-8") as stream:
                    stream.write("gcloud " + " ".join(args) + "\\n")
                state = json.loads(state_path.read_text(encoding="utf-8"))

                if args[:3] == ["run", "services", "describe"]:
                    traffic = [{
                        "percent": 100,
                        "revisionName": state["serving"],
                    }]
                    if state["smoke"]:
                        traffic.append({
                            "tag": "smoke",
                            "url": "https://smoke.example.invalid",
                        })
                    print(json.dumps({
                        "metadata": {"name": "agent"},
                        "spec": {
                            "template": {
                                "metadata": {
                                    "annotations": {
                                        "autoscaling.knative.dev/maxScale": "1"
                                    }
                                },
                                "spec": {
                                    "containerConcurrency": 8,
                                    "containers": [{
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
                                        "env": [
                                            {
                                                "name": "AGENT_AUTH_SECRET",
                                                "valueFrom": {
                                                    "secretKeyRef": {
                                                        "name": "agent-auth-secret",
                                                        "key": os.environ[
                                                            "FAKE_SECRET_VERSION"
                                                        ],
                                                    }
                                                },
                                            },
                                            {
                                                "name": "ANTHROPIC_API_KEY",
                                                "valueFrom": {
                                                    "secretKeyRef": {
                                                        "name": "anthropic-api-key",
                                                        "key": "12",
                                                    }
                                                },
                                            },
                                            {
                                                "name": "DATABASE_URL",
                                                "valueFrom": {
                                                    "secretKeyRef": {
                                                        "name": "agent-database-url",
                                                        "key": "13",
                                                    }
                                                },
                                            },
                                            {
                                                "name": "LANGCHAIN_API_KEY",
                                                "valueFrom": {
                                                    "secretKeyRef": {
                                                        "name": "langsmith-api-key",
                                                        "key": "14",
                                                    }
                                                },
                                            },
                                            {
                                                "name": "OPENAI_API_KEY",
                                                "valueFrom": {
                                                    "secretKeyRef": {
                                                        "name": "openai-api-key",
                                                        "key": "15",
                                                    }
                                                },
                                            },
                                        ],
                                    }],
                                },
                            }
                        },
                        "status": {
                            "latestCreatedRevisionName": state["latest_created"],
                            "latestReadyRevisionName": state["latest_ready"],
                            "traffic": traffic,
                            "url": "https://agent.example.invalid",
                        },
                    }))
                elif args[:3] == ["run", "revisions", "describe"]:
                    print(json.dumps({
                        "metadata": {
                            "name": args[3],
                            "labels": {
                                "serving.knative.dev/service": os.environ[
                                    "FAKE_REVISION_SERVICE"
                                ],
                            },
                            "annotations": {
                                "autoscaling.knative.dev/maxScale": "1",
                            },
                        },
                        "spec": {
                            "serviceAccountName": os.environ[
                                "FAKE_REVISION_SERVICE_ACCOUNT"
                            ],
                            "containerConcurrency": 8,
                            "containers": [{
                                "image": os.environ["FAKE_REVISION_IMAGE"],
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
                                "env": [
                                    {
                                        "name": "AGENT_AUTH_SECRET",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "agent-auth-secret",
                                                "key": os.environ[
                                                    "FAKE_REVISION_SECRET_VERSION"
                                                ],
                                            }
                                        },
                                    },
                                    {
                                        "name": "ANTHROPIC_API_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "anthropic-api-key",
                                                "key": "12",
                                            }
                                        },
                                    },
                                    {
                                        "name": "DATABASE_URL",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "agent-database-url",
                                                "key": "13",
                                            }
                                        },
                                    },
                                    {
                                        "name": "LANGCHAIN_API_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "langsmith-api-key",
                                                "key": "14",
                                            }
                                        },
                                    },
                                    {
                                        "name": "OPENAI_API_KEY",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "openai-api-key",
                                                "key": "15",
                                            }
                                        },
                                    },
                                ],
                            }],
                        },
                        "status": {
                            "conditions": [{
                                "type": "Ready",
                                "status": os.environ["FAKE_REVISION_READY"],
                            }],
                            "imageDigest": os.environ["FAKE_REVISION_IMAGE"],
                        },
                    }))
                elif args[:3] == ["run", "services", "update"]:
                    state["latest_created"] = (
                        "agent-g"
                        + os.environ["SOURCE_SHA"][:8]
                        + "-r"
                        + os.environ["DELIVERY_RUN_ID"]
                        + "-a"
                        + os.environ["DELIVERY_RUN_ATTEMPT"]
                    )
                    state["latest_ready"] = state["latest_created"]
                    state_path.write_text(json.dumps(state), encoding="utf-8")
                elif args[:3] == ["run", "services", "update-traffic"]:
                    joined = " ".join(args)
                    if "--set-tags" in args:
                        state["smoke"] = True
                    elif "--remove-tags" in args:
                        if os.environ.get("FAIL_SMOKE_TAG_REMOVAL") == "true":
                            raise SystemExit("injected smoke tag cleanup failure")
                        state["smoke"] = False
                    elif "--to-revisions" in args:
                        target = args[args.index("--to-revisions") + 1].split("=", 1)[0]
                        state["serving"] = target
                    state_path.write_text(json.dumps(state), encoding="utf-8")
                elif args[:3] in (
                    ["run", "jobs", "update"],
                    ["run", "jobs", "execute"],
                ):
                    pass
                else:
                    raise SystemExit("unexpected fake gcloud argv: " + repr(args))
                """
            ),
            encoding="utf-8",
        )
        gcloud.chmod(0o755)

        curl = binary / "curl"
        curl.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as stream:
                    stream.write("curl " + " ".join(args) + "\\n")
                if "--write-out" in args:
                    print("401", end="")
                elif args[-1].endswith("/live"):
                    print('{"status":"alive"}')
                elif args[-1].endswith("/ready"):
                    print('{"status":"ready"}')
                else:
                    raise SystemExit("unexpected fake curl argv")
                """
            ),
            encoding="utf-8",
        )
        curl.chmod(0o755)

        uv = binary / "uv"
        uv.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/sh
                printf '%s\\n' "uv $*" >>"$FAKE_LOG"
                exit {1 if fail_protocol else 0}
                """
            ),
            encoding="utf-8",
        )
        uv.chmod(0o755)

        environment = os.environ.copy()
        environment.update(
            {
                "CLOUD_RUN_SERVICE": "agent",
                "DELIVERY_RUN_ID": DELIVERY_RUN_ID,
                "DELIVERY_RUN_ATTEMPT": DELIVERY_RUN_ATTEMPT,
                "FAKE_LOG": str(log),
                "FAKE_REVISION_IMAGE": IMAGE_DIGEST,
                "FAKE_REVISION_READY": "True",
                "FAKE_REVISION_SECRET_VERSION": "11",
                "FAKE_REVISION_SERVICE": "agent",
                "FAKE_REVISION_SERVICE_ACCOUNT": (
                    "agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
                ),
                "FAKE_SECRET_VERSION": "11",
                "FAKE_STATE": str(state),
                "GCP_PROJECT_ID": "festive-ally-503605-v7",
                "GCP_REGION": "us-east4",
                "GRANT_PROBE_JOB": "agent-grants",
                "IMAGE_DIGEST": IMAGE_DIGEST,
                "MIGRATION_JOB": "agent-migrate",
                "PATH": f"{binary}:{environment['PATH']}",
                "SMOKE_BEARER_TOKEN": "opaque-test-token",
                "SOURCE_SHA": SOURCE_SHA,
            }
        )
        return environment

    def test_deploy_orders_migration_grant_probe_revision_and_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            result = subprocess.run(
                [str(DEPLOY_SCRIPT), "deploy"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )

        self.assertEqual(0, result.returncode, result.stderr)
        ordered = [
            "gcloud run jobs update agent-migrate",
            "gcloud run jobs execute agent-migrate",
            "gcloud run jobs update agent-grants",
            "gcloud run jobs execute agent-grants",
            "gcloud run services update agent",
            "gcloud run services update-traffic agent",
            "uv run --no-project --with httpx==0.28.1",
        ]
        cursor = -1
        for marker in ordered:
            next_cursor = operations.find(marker, cursor + 1)
            self.assertGreater(next_cursor, cursor, marker)
            cursor = next_cursor
        self.assertEqual(
            f"agent-g{SOURCE_SHA[:8]}-r{DELIVERY_RUN_ID}-a{DELIVERY_RUN_ATTEMPT}",
            state["serving"],
        )
        self.assertFalse(state["smoke"])

    def test_failed_post_traffic_protocol_smoke_restores_previous_revision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory, fail_protocol=True)
            result = subprocess.run(
                [str(DEPLOY_SCRIPT), "deploy"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("restoring traffic to agent-old", result.stderr)
        self.assertEqual("agent-old", state["serving"])
        self.assertFalse(state["smoke"])

    def test_failed_manual_rollback_restores_the_serving_not_latest_revision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory, fail_protocol=True)
            state_path = Path(directory) / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["latest_ready"] = "agent-unused-no-traffic"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            result = subprocess.run(
                [str(DEPLOY_SCRIPT), "rollback", "agent-target"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("restoring traffic to agent-old", result.stderr)
        self.assertEqual("agent-old", state["serving"])

    def test_manual_rollback_rejects_unsafe_target_revision_before_traffic(
        self,
    ) -> None:
        mutations = {
            "wrong_repository": {
                "FAKE_REVISION_IMAGE": (
                    "us-east4-docker.pkg.dev/festive-ally-503605-v7/"
                    "agent-preview/agent@sha256:" + "3" * 64
                ),
            },
            "secret_alias": {"FAKE_REVISION_SECRET_VERSION": "latest"},
            "wrong_runtime_identity": {
                "FAKE_REVISION_SERVICE_ACCOUNT": (
                    "agent-preview-runtime@festive-ally-503605-v7."
                    "iam.gserviceaccount.com"
                ),
            },
            "not_ready": {"FAKE_REVISION_READY": "False"},
            "wrong_service": {"FAKE_REVISION_SERVICE": "agent-preview"},
        }
        for name, mutation in mutations.items():
            with (
                self.subTest(mutation=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                environment = self._fixture(directory)
                environment.update(mutation)

                result = subprocess.run(
                    [str(DEPLOY_SCRIPT), "rollback", "agent-target"],
                    cwd=REPO_ROOT,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                operations = (Path(directory) / "operations.log").read_text(
                    encoding="utf-8"
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "ready, environment-matched immutable runtime contract",
                    result.stderr,
                )
                self.assertNotIn("--to-revisions", operations)

    def test_wrong_project_fails_before_gcloud_is_called(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["GCP_PROJECT_ID"] = "wrong-project"
            result = subprocess.run(
                [str(DEPLOY_SCRIPT), "deploy"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            log = Path(directory) / "operations.log"

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unexpected GCP project", result.stderr)
        self.assertFalse(log.exists())

    def test_cross_environment_job_fails_before_gcloud_is_called(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["MIGRATION_JOB"] = "agent-preview-migrate"
            result = subprocess.run(
                [str(DEPLOY_SCRIPT), "deploy"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            log = Path(directory) / "operations.log"

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "production service must use only production one-shot jobs",
            result.stderr,
        )
        self.assertFalse(log.exists())

    def test_invalid_delivery_run_id_fails_before_gcloud_is_called(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["DELIVERY_RUN_ID"] = "latest"
            result = subprocess.run(
                [str(DEPLOY_SCRIPT), "deploy"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            log = Path(directory) / "operations.log"

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "DELIVERY_RUN_ID must be a positive numeric GitHub run ID",
            result.stderr,
        )
        self.assertFalse(log.exists())

    def test_run_attempt_is_unique_and_length_bounded_for_reruns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["DELIVERY_RUN_ID"] = "9" * 20
            environment["DELIVERY_RUN_ATTEMPT"] = "8" * 16
            first = subprocess.run(
                [str(DEPLOY_SCRIPT), "deploy"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            state_path = Path(directory) / "state.json"
            first_revision = json.loads(state_path.read_text(encoding="utf-8"))[
                "serving"
            ]

            environment["DELIVERY_RUN_ATTEMPT"] = "7" * 16
            second = subprocess.run(
                [str(DEPLOY_SCRIPT), "deploy"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            second_revision = json.loads(state_path.read_text(encoding="utf-8"))[
                "serving"
            ]

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertNotEqual(first_revision, second_revision)
        self.assertLessEqual(len(first_revision), 63)
        self.assertLessEqual(len(second_revision), 63)
        preview_boundary = f"agent-preview-g{SOURCE_SHA[:8]}-r{'9' * 20}-a{'8' * 16}"
        self.assertEqual(63, len(preview_boundary))

    def test_overlong_run_attempt_fails_before_gcloud_is_called(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["DELIVERY_RUN_ATTEMPT"] = "1" * 17
            result = subprocess.run(
                [str(DEPLOY_SCRIPT), "deploy"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            log = Path(directory) / "operations.log"

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "DELIVERY_RUN_ATTEMPT must be a positive numeric GitHub run attempt",
            result.stderr,
        )
        self.assertFalse(log.exists())

    def test_mutable_service_secret_alias_fails_before_jobs_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["FAKE_SECRET_VERSION"] = "latest"
            result = subprocess.run(
                [str(DEPLOY_SCRIPT), "deploy"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("numeric secret pins", result.stderr)
        self.assertNotIn("gcloud run jobs update", operations)

    def test_smoke_tag_cleanup_failure_still_restores_previous_traffic(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["FAIL_SMOKE_TAG_REMOVAL"] = "true"
            result = subprocess.run(
                [str(DEPLOY_SCRIPT), "deploy"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "public smoke tag could not be removed",
            result.stderr,
        )
        self.assertIn("restoring traffic to agent-old", result.stderr)
        self.assertEqual("agent-old", state["serving"])
        self.assertTrue(state["smoke"])

    def test_manual_rollback_removes_a_stale_smoke_tag_before_shift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            state_path = Path(directory) / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["smoke"] = True
            state_path.write_text(json.dumps(state), encoding="utf-8")

            result = subprocess.run(
                [str(DEPLOY_SCRIPT), "rollback", "agent-target"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, result.stderr)
        cleanup = operations.index("--remove-tags smoke")
        shift = operations.index("--to-revisions agent-target=100")
        self.assertLess(cleanup, shift)
        self.assertEqual("agent-target", state["serving"])
        self.assertFalse(state["smoke"])


if __name__ == "__main__":
    unittest.main()
