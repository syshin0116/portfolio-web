from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import textwrap
import time
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
ACCESS_TOKEN = "test-token-that-must-never-enter-the-operation-log"


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
                    "service_image": IMAGE_DIGEST,
                    "job_images": {},
                    "job_etags": {},
                    "run_requests": [],
                    "traffic_updates": 0,
                }
            ),
            encoding="utf-8",
        )
        log = root / "operations.log"

        gcloud = binary / "gcloud"
        gcloud.write_text(
            textwrap.dedent(
                f"""\
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

                if args == ["auth", "print-access-token", "--quiet"]:
                    print({ACCESS_TOKEN!r})
                    raise SystemExit(0)

                state = json.loads(state_path.read_text(encoding="utf-8"))
                if args[:3] == ["run", "jobs", "update"]:
                    job = args[3]
                    state["job_images"][job] = args[args.index("--image") + 1]
                    state["job_etags"][job] = "etag-" + job + "-9"
                elif args[:3] == ["run", "services", "update"]:
                    state["service_image"] = args[args.index("--image") + 1]
                    state["latest_created"] = (
                        "agent-g"
                        + os.environ["SOURCE_SHA"][:8]
                        + "-r"
                        + os.environ["DELIVERY_RUN_ID"]
                        + "-a"
                        + os.environ["DELIVERY_RUN_ATTEMPT"]
                    )
                    state["latest_ready"] = state["latest_created"]
                elif args[:3] == ["run", "services", "update-traffic"]:
                    if "--set-tags" in args:
                        state["smoke"] = True
                    elif "--remove-tags" in args:
                        if os.environ.get("FAIL_SMOKE_TAG_REMOVAL") == "true":
                            raise SystemExit("injected smoke tag cleanup failure")
                        state["smoke"] = False
                    elif "--to-revisions" in args:
                        target = args[args.index("--to-revisions") + 1].split("=", 1)[0]
                        state["traffic_updates"] += 1
                        if (
                            os.environ.get("FAKE_FIRST_TRAFFIC_TARGET_OVERRIDE")
                            and state["traffic_updates"] == 1
                        ):
                            state["serving"] = os.environ[
                                "FAKE_FIRST_TRAFFIC_TARGET_OVERRIDE"
                            ]
                        else:
                            state["serving"] = target
                else:
                    raise SystemExit("unexpected fake gcloud argv: " + repr(args))
                state_path.write_text(json.dumps(state), encoding="utf-8")
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
                import json
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                log_path = Path(os.environ["FAKE_LOG"])
                state_path = Path(os.environ["FAKE_STATE"])
                with log_path.open("a", encoding="utf-8") as stream:
                    stream.write("curl " + " ".join(args) + "\\n")

                url = args[-1]
                if not url.startswith("https://run.googleapis.com/"):
                    if "--write-out" in args:
                        print("401", end="")
                    elif url.endswith("/live"):
                        print('{"status":"alive"}')
                    elif url.endswith("/ready"):
                        print('{"status":"ready"}')
                    else:
                        raise SystemExit("unexpected public fake curl argv")
                    raise SystemExit(0)

                method = args[args.index("--request") + 1]
                output_path = Path(args[args.index("--output") + 1])
                state = json.loads(state_path.read_text(encoding="utf-8"))
                project = "festive-ally-503605-v7"
                region = "us-east4"
                service_name = "agent"
                service_path = f"projects/{project}/locations/{region}/services/agent"

                plain_env = {
                    "AEGRA_CONFIG": "/app/aegra.json",
                    "BG_JOB_MAX_RETRIES": os.environ.get(
                        "FAKE_BG_JOB_MAX_RETRIES", "0"
                    ),
                    "ENV_MODE": os.environ.get("FAKE_ENV_MODE", "PRODUCTION"),
                    "FF_V2_EVENT_STREAMING": "true",
                    "HOST": "0.0.0.0",
                    "LANGGRAPH_MAX_POOL_SIZE": "4",
                    "LANGGRAPH_MIN_POOL_SIZE": "1",
                    "MODEL": "anthropic:claude-sonnet-4-6",
                    "PORT": "8080",
                    "REDIS_BROKER_ENABLED": os.environ.get(
                        "FAKE_REDIS_BROKER_ENABLED", "false"
                    ),
                    "RUN_MIGRATIONS_ON_STARTUP": "false",
                    "SQLALCHEMY_MAX_OVERFLOW": "0",
                    "SQLALCHEMY_POOL_SIZE": "2",
                }
                secrets = [
                    ("AGENT_AUTH_SECRET", "agent-auth-secret", os.environ.get(
                        "FAKE_RUNTIME_SECRET_VERSION", "11"
                    )),
                    ("ANTHROPIC_API_KEY", "anthropic-api-key", "12"),
                    ("DATABASE_URL", "agent-database-url", "13"),
                    ("LANGCHAIN_API_KEY", "langsmith-api-key", "14"),
                    ("OPENAI_API_KEY", "openai-api-key", "15"),
                ]

                def runtime_template(image):
                    env = [
                        {"name": name, "value": value}
                        for name, value in plain_env.items()
                    ]
                    env.extend(
                        {
                            "name": name,
                            "valueSource": {
                                "secretKeyRef": {
                                    "secret": secret,
                                    "version": version,
                                }
                            },
                        }
                        for name, secret, version in secrets
                    )
                    template = {
                        "serviceAccount": os.environ.get(
                            "FAKE_RUNTIME_SERVICE_ACCOUNT",
                            "agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com",
                        ),
                        "timeout": os.environ.get("FAKE_RUNTIME_TIMEOUT", "300s"),
                        "executionEnvironment": "EXECUTION_ENVIRONMENT_GEN2",
                        "maxInstanceRequestConcurrency": 8,
                        "scaling": {"minInstanceCount": 0, "maxInstanceCount": 1},
                        "containers": [{
                            "name": "agent",
                            "image": os.environ.get("FAKE_RUNTIME_IMAGE", image),
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
                            "ports": [{
                                "name": "http1",
                                "containerPort": int(
                                    os.environ.get("FAKE_RUNTIME_PORT", "8080")
                                ),
                            }],
                            "resources": {
                                "limits": {
                                    "cpu": os.environ.get("FAKE_RUNTIME_CPU", "1"),
                                    "memory": "1Gi",
                                },
                                "cpuIdle": True,
                                "startupCpuBoost": True,
                            },
                            "env": env,
                            "startupProbe": {
                                "initialDelaySeconds": 0,
                                "timeoutSeconds": 5,
                                "periodSeconds": 5,
                                "failureThreshold": int(
                                    os.environ.get(
                                        "FAKE_STARTUP_FAILURE_THRESHOLD", "24"
                                    )
                                ),
                                "httpGet": {"path": "/ready", "port": 8080},
                            },
                            "livenessProbe": {
                                "initialDelaySeconds": 0,
                                "timeoutSeconds": 5,
                                "periodSeconds": 30,
                                "failureThreshold": 3,
                                "httpGet": {"path": "/live", "port": 8080},
                            },
                        }],
                    }
                    if os.environ.get("FAKE_RUNTIME_VOLUMES") == "true":
                        template["volumes"] = [{
                            "name": "drift",
                            "emptyDir": {"medium": "MEMORY"},
                        }]
                    if os.environ.get("FAKE_RUNTIME_VPC") == "true":
                        template["vpcAccess"] = {
                            "networkInterfaces": [{"network": "default"}]
                        }
                    if os.environ.get("FAKE_RUNTIME_HEALTH_DISABLED") == "true":
                        template["healthCheckDisabled"] = True
                    container = template["containers"][0]
                    if os.environ.get("FAKE_RUNTIME_VOLUME_MOUNT") == "true":
                        container["volumeMounts"] = [{
                            "name": "drift",
                            "mountPath": "/drift",
                        }]
                    if "FAKE_RUNTIME_WORKING_DIR" in os.environ:
                        container["workingDir"] = os.environ["FAKE_RUNTIME_WORKING_DIR"]
                    if "FAKE_RUNTIME_BASE_IMAGE" in os.environ:
                        container["baseImageUri"] = os.environ[
                            "FAKE_RUNTIME_BASE_IMAGE"
                        ]
                    if os.environ.get("FAKE_RUNTIME_SANDBOX") == "true":
                        container["sandboxLauncher"] = True
                    return template

                def service_document():
                    traffic = [{
                        "percent": 100,
                        "revision": f"{service_path}/revisions/{state['serving']}",
                    }]
                    if state["smoke"]:
                        smoke_revision = os.environ.get(
                            "FAKE_SMOKE_REVISION", state["latest_created"]
                        )
                        traffic.append({
                            "tag": "smoke",
                            "revision": (
                                f"{service_path}/revisions/"
                                f"{smoke_revision}"
                            ),
                            "uri": "https://smoke.example.invalid",
                            "percent": int(
                                os.environ.get("FAKE_SMOKE_PERCENT", "0")
                            ),
                        })
                    if (
                        os.environ.get("FAKE_EXTRA_TRAFFIC_TAG") == "true"
                        or (
                            os.environ.get("FAKE_EXTRA_SMOKE_STAGE_TAG") == "true"
                            and state["smoke"]
                        )
                    ):
                        traffic.append({
                            "tag": "backdoor",
                            "revision": f"{service_path}/revisions/agent-backdoor",
                            "uri": "https://backdoor.example.invalid",
                            "percent": 0,
                        })
                    document = {
                        "name": service_path,
                        "ingress": "INGRESS_TRAFFIC_ALL",
                        "reconciling": False,
                        "terminalCondition": {
                            "state": os.environ.get(
                                "FAKE_SERVICE_STATE", "CONDITION_SUCCEEDED"
                            )
                        },
                        "generation": "7",
                        "observedGeneration": "7",
                        "template": runtime_template(state["service_image"]),
                        "latestCreatedRevision": (
                            f"{service_path}/revisions/{state['latest_created']}"
                        ),
                        "latestReadyRevision": (
                            f"{service_path}/revisions/{state['latest_ready']}"
                        ),
                        "trafficStatuses": traffic,
                        "uri": "https://agent.example.invalid",
                    }
                    if os.environ.get("FAKE_SERVICE_BUILD_CONFIG") == "true":
                        document["buildConfig"] = {
                            "baseImage": "us-docker.pkg.dev/serverless-runtimes/x"
                        }
                    if os.environ.get("FAKE_SERVICE_CUSTOM_AUDIENCE") == "true":
                        document["customAudiences"] = ["https://attacker.invalid"]
                    if os.environ.get("FAKE_SERVICE_SCALING") == "true":
                        document["scaling"] = {"manualInstanceCount": 10}
                    if os.environ.get("FAKE_SERVICE_IAP") == "true":
                        document["iapEnabled"] = True
                    return document

                def revision_document(revision):
                    result = runtime_template(state["service_image"])
                    result.update({
                        "name": f"{service_path}/revisions/{revision}",
                        "service": os.environ.get(
                            "FAKE_REVISION_SERVICE", service_path
                        ),
                        "reconciling": False,
                        "conditions": [{
                            "type": "Ready",
                            "state": os.environ.get(
                                "FAKE_REVISION_STATE", "CONDITION_SUCCEEDED"
                            ),
                        }],
                    })
                    return result

                def job_document(job):
                    migration = job.endswith("-migrate")
                    expected_secret = (
                        "agent-migration-database-url"
                        if migration else "agent-database-url"
                    )
                    expected_sa = (
                        "agent-prod-migrator@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                        if migration else
                        "agent-runtime@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                    module = "agent.migrate" if migration else "agent.neon_grant_probe"
                    container_name = "migration" if migration else "grant-probe"
                    timeout = "900s" if migration else "600s"
                    document = {
                        "name": (
                            f"projects/{project}/locations/{region}/jobs/{job}"
                        ),
                        "reconciling": False,
                        "terminalCondition": {
                            "state": os.environ.get(
                                "FAKE_JOB_STATE", "CONDITION_SUCCEEDED"
                            )
                        },
                        "generation": "9",
                        "observedGeneration": "9",
                        "etag": state["job_etags"].get(job, "etag-" + job + "-9"),
                        "template": {
                            "taskCount": 1,
                            "parallelism": 1,
                            "template": {
                                "serviceAccount": os.environ.get(
                                    "FAKE_JOB_SERVICE_ACCOUNT", expected_sa
                                ),
                                "timeout": os.environ.get(
                                    "FAKE_JOB_TIMEOUT", timeout
                                ),
                                "executionEnvironment": (
                                    "EXECUTION_ENVIRONMENT_GEN2"
                                ),
                                "maxRetries": int(
                                    os.environ.get("FAKE_JOB_MAX_RETRIES", "0")
                                ),
                                "containers": [{
                                    "name": container_name,
                                    "image": os.environ.get(
                                        "FAKE_JOB_IMAGE",
                                        state["job_images"].get(job, ""),
                                    ),
                                    "command": [
                                        os.environ.get("FAKE_JOB_COMMAND", "python")
                                    ],
                                    "args": ["-m", module],
                                    "resources": {
                                        "limits": {
                                            "cpu": os.environ.get(
                                                "FAKE_JOB_CPU", "1"
                                            ),
                                            "memory": "1Gi",
                                        }
                                    },
                                    "env": [
                                        {
                                            "name": "ENV_MODE",
                                            "value": "PRODUCTION",
                                        },
                                        {
                                            "name": "RUN_MIGRATIONS_ON_STARTUP",
                                            "value": "false",
                                        },
                                        {
                                            "name": "DATABASE_URL",
                                            "valueSource": {
                                                "secretKeyRef": {
                                                    "secret": os.environ.get(
                                                        "FAKE_JOB_SECRET",
                                                        expected_secret,
                                                    ),
                                                    "version": os.environ.get(
                                                        "FAKE_JOB_SECRET_VERSION",
                                                        "31",
                                                    ),
                                                }
                                            },
                                        },
                                    ],
                                }],
                            },
                        },
                    }
                    task_template = document["template"]["template"]
                    if os.environ.get("FAKE_JOB_VOLUMES") == "true":
                        task_template["volumes"] = [{
                            "name": "drift",
                            "emptyDir": {"medium": "MEMORY"},
                        }]
                    if os.environ.get("FAKE_JOB_VPC") == "true":
                        task_template["vpcAccess"] = {
                            "networkInterfaces": [{"network": "default"}]
                        }
                    container = task_template["containers"][0]
                    if os.environ.get("FAKE_JOB_VOLUME_MOUNT") == "true":
                        container["volumeMounts"] = [{
                            "name": "drift",
                            "mountPath": "/drift",
                        }]
                    if "FAKE_JOB_WORKING_DIR" in os.environ:
                        container["workingDir"] = os.environ["FAKE_JOB_WORKING_DIR"]
                    if "FAKE_JOB_BASE_IMAGE" in os.environ:
                        container["baseImageUri"] = os.environ["FAKE_JOB_BASE_IMAGE"]
                    if os.environ.get("FAKE_JOB_SANDBOX") == "true":
                        container["sandboxLauncher"] = True
                    return document

                def operation_document(job):
                    job_state = job_document(job)
                    execution_template = json.loads(json.dumps(job_state["template"]))
                    if "FAKE_EXECUTION_IMAGE" in os.environ:
                        execution_template["template"]["containers"][0]["image"] = (
                            os.environ["FAKE_EXECUTION_IMAGE"]
                        )
                    job_path = (
                        f"projects/{project}/locations/{region}/jobs/{job}"
                    )
                    operation_name = os.environ.get(
                        "FAKE_OPERATION_NAME",
                        (
                            f"projects/{project}/locations/{region}/"
                            f"operations/op-{job}"
                        ),
                    )
                    if os.environ.get("FAKE_OPERATION_ERROR") == "true":
                        return {
                            "name": operation_name,
                            "done": True,
                            "error": {"code": 13, "message": "injected failure"},
                        }
                    return {
                        "name": operation_name,
                        "done": True,
                        "response": {
                            "@type": (
                                "type.googleapis.com/"
                                "google.cloud.run.v2.Execution"
                            ),
                            "name": f"{job_path}/executions/{job}-abcde",
                            "job": job_path,
                            "reconciling": False,
                            "generation": "1",
                            "observedGeneration": "1",
                            "etag": "execution-etag-" + job,
                            "completionTime": "2026-07-28T00:00:00Z",
                            "taskCount": execution_template["taskCount"],
                            "parallelism": execution_template["parallelism"],
                            "template": execution_template["template"],
                            "succeededCount": int(
                                os.environ.get("FAKE_SUCCEEDED_COUNT", "1")
                            ),
                            "failedCount": int(
                                os.environ.get("FAKE_FAILED_COUNT", "0")
                            ),
                            "cancelledCount": int(
                                os.environ.get("FAKE_CANCELLED_COUNT", "0")
                            ),
                            "runningCount": 0,
                            "retriedCount": int(
                                os.environ.get("FAKE_RETRIED_COUNT", "0")
                            ),
                            "conditions": [{
                                "type": "Completed",
                                "state": "CONDITION_SUCCEEDED",
                            }],
                        },
                    }

                response_status = os.environ.get("FAKE_API_STATUS", "200")
                if os.environ.get("FAKE_API_SHAPE") == "v1":
                    document = {
                        "metadata": {"name": service_name},
                        "spec": {"template": {"spec": {"containers": []}}},
                        "status": {"url": "https://agent.example.invalid"},
                    }
                elif "/revisions/" in url:
                    document = revision_document(url.rsplit("/", 1)[-1])
                elif method == "POST" and url.endswith(":run"):
                    job = url.rsplit("/", 1)[-1].removesuffix(":run")
                    data_argument = args[args.index("--data-binary") + 1]
                    if not data_argument.startswith("@"):
                        raise SystemExit("jobs.run body was not file-backed")
                    request = json.loads(
                        Path(data_argument[1:]).read_text(encoding="utf-8")
                    )
                    state["run_requests"].append({"job": job, "body": request})
                    expected_etag = state["job_etags"].get(
                        job, "etag-" + job + "-9"
                    )
                    if os.environ.get("FAKE_JOB_ETAG_DRIFT_BEFORE_RUN") == "true":
                        expected_etag += "-drifted"
                    if request != {"etag": expected_etag}:
                        response_status = "412"
                        document = {
                            "error": {
                                "code": 412,
                                "message": "etag precondition failed",
                            }
                        }
                    else:
                        document = operation_document(job)
                        if os.environ.get("FAKE_OPERATION_PENDING_JOB") == job:
                            document = {
                                "name": document["name"],
                                "done": False,
                            }
                    state_path.write_text(json.dumps(state), encoding="utf-8")
                elif "/operations/" in url:
                    operation = url.rsplit("/", 1)[-1]
                    if not operation.startswith("op-"):
                        raise SystemExit("unexpected operation id")
                    document = operation_document(operation.removeprefix("op-"))
                elif "/jobs/" in url:
                    document = job_document(url.rsplit("/", 1)[-1])
                else:
                    document = service_document()

                body = json.dumps(document, separators=(",", ":"))
                output_path.write_text(body, encoding="utf-8")
                print(response_status)
                print(os.environ.get("FAKE_API_CONTENT_TYPE", "application/json"))
                print(os.environ.get("FAKE_API_SIZE", str(len(body.encode("utf-8")))))
                print(os.environ.get("FAKE_API_REDIRECTS", "0"), end="")
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
                if [ "${{FAKE_PROTOCOL_BLOCK:-false}}" = "true" ]; then
                  printf 'ready\\n' >"$FAKE_PROTOCOL_MARKER"
                  trap 'exit 143' TERM INT
                  while :; do
                    sleep 1
                  done
                fi
                exit {1 if fail_protocol else 0}
                """
            ),
            encoding="utf-8",
        )
        uv.chmod(0o755)

        sleep = binary / "sleep"
        sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        sleep.chmod(0o755)

        environment = os.environ.copy()
        environment.update(
            {
                "CLOUD_RUN_SERVICE": "agent",
                "DELIVERY_RUN_ID": DELIVERY_RUN_ID,
                "DELIVERY_RUN_ATTEMPT": DELIVERY_RUN_ATTEMPT,
                "FAKE_LOG": str(log),
                "FAKE_STATE": str(state),
                "GCP_PROJECT_ID": "festive-ally-503605-v7",
                "GCP_REGION": "us-east4",
                "GRANT_PROBE_JOB": "agent-grants",
                "IMAGE_DIGEST": IMAGE_DIGEST,
                "MIGRATION_JOB": "agent-migrate",
                "PATH": f"{binary}:{environment['PATH']}",
                "RUNNER_TEMP": str(root),
                "SMOKE_BEARER_TOKEN": "opaque-test-token",
                "SOURCE_SHA": SOURCE_SHA,
            }
        )
        return environment

    def _run(
        self,
        directory: str,
        environment: dict[str, str],
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(DEPLOY_SCRIPT), *arguments],
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_deploy_binds_each_verified_job_etag_to_immutable_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            result = self._run(directory, environment, "deploy")
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )

        self.assertEqual(0, result.returncode, result.stderr)
        ordered = [
            "gcloud run jobs update agent-migrate",
            "/jobs/agent-migrate",
            "/jobs/agent-migrate:run",
            "gcloud run jobs update agent-grants",
            "/jobs/agent-grants",
            "/jobs/agent-grants:run",
            "gcloud run services update agent",
            "/revisions/agent-g",
            "gcloud run services update-traffic agent",
            "uv run --frozen --package syshin0116-dev-agent",
        ]
        cursor = -1
        for marker in ordered:
            next_cursor = operations.find(marker, cursor + 1)
            self.assertGreater(next_cursor, cursor, marker)
            cursor = next_cursor
        protocol_smoke = operations.index(
            "uv run --frozen --package syshin0116-dev-agent"
        )
        promotion = operations.index(
            f"--to-revisions agent-g{SOURCE_SHA[:8]}-r{DELIVERY_RUN_ID}"
            f"-a{DELIVERY_RUN_ATTEMPT}=100"
        )
        self.assertLess(protocol_smoke, promotion)
        self.assertEqual(
            f"agent-g{SOURCE_SHA[:8]}-r{DELIVERY_RUN_ID}-a{DELIVERY_RUN_ATTEMPT}",
            state["serving"],
        )
        self.assertFalse(state["smoke"])
        self.assertEqual(
            [
                {
                    "job": "agent-migrate",
                    "body": {"etag": "etag-agent-migrate-9"},
                },
                {
                    "job": "agent-grants",
                    "body": {"etag": "etag-agent-grants-9"},
                },
            ],
            state["run_requests"],
        )
        self.assertNotIn(ACCESS_TOKEN, operations)

    def test_official_v2_service_without_terraform_only_field_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            result = self._run(directory, environment, "rollback", "agent-target")
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("agent-target", state["serving"])

    def test_failed_pretraffic_protocol_smoke_never_promotes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory, fail_protocol=True)
            result = self._run(directory, environment, "deploy")
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )

        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("--to-revisions", operations)
        self.assertNotIn("restoring traffic", result.stderr)
        self.assertEqual("agent-old", state["serving"])
        self.assertFalse(state["smoke"])

    def test_termination_during_pretraffic_protocol_cleans_without_promotion(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            marker = Path(directory) / "protocol-ready"
            environment["FAKE_PROTOCOL_BLOCK"] = "true"
            environment["FAKE_PROTOCOL_MARKER"] = str(marker)
            process = subprocess.Popen(
                [str(DEPLOY_SCRIPT), "deploy"],
                cwd=REPO_ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            deadline = time.monotonic() + 15
            while not marker.exists() and time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            if not marker.exists():
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate(timeout=5)
                self.fail(
                    "protocol smoke did not reach the cancellation boundary: "
                    f"stdout={stdout!r} stderr={stderr!r}"
                )
            os.killpg(process.pid, signal.SIGTERM)
            _stdout, stderr = process.communicate(timeout=15)
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )

        self.assertNotEqual(0, process.returncode)
        self.assertNotIn("--to-revisions", operations)
        self.assertNotIn("restoring traffic", stderr)
        self.assertEqual("agent-old", state["serving"])
        self.assertFalse(state["smoke"])

    def test_failed_manual_rollback_restores_actual_serving_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory, fail_protocol=True)
            state_path = Path(directory) / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["latest_ready"] = "agent-unused-no-traffic"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            result = self._run(directory, environment, "rollback", "agent-target")
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("restoring traffic to agent-old", result.stderr)
        self.assertEqual("agent-old", state["serving"])

    def test_manual_rollback_rejects_every_material_revision_drift(self) -> None:
        mutations = {
            "wrong_repository": {
                "FAKE_RUNTIME_IMAGE": (
                    "us-east4-docker.pkg.dev/festive-ally-503605-v7/"
                    "agent-preview/agent@sha256:" + "3" * 64
                )
            },
            "secret_alias": {"FAKE_RUNTIME_SECRET_VERSION": "latest"},
            "wrong_runtime_identity": {
                "FAKE_RUNTIME_SERVICE_ACCOUNT": (
                    "agent-preview-runtime@festive-ally-503605-v7."
                    "iam.gserviceaccount.com"
                )
            },
            "not_ready": {"FAKE_REVISION_STATE": "CONDITION_FAILED"},
            "wrong_service": {
                "FAKE_REVISION_SERVICE": (
                    "projects/festive-ally-503605-v7/locations/us-east4/"
                    "services/agent-preview"
                )
            },
            "startup_probe": {"FAKE_STARTUP_FAILURE_THRESHOLD": "23"},
            "cpu": {"FAKE_RUNTIME_CPU": "2"},
            "port": {"FAKE_RUNTIME_PORT": "9090"},
            "timeout": {"FAKE_RUNTIME_TIMEOUT": "301s"},
            "plain_environment": {"FAKE_ENV_MODE": "PREVIEW"},
            "background_retry_budget": {"FAKE_BG_JOB_MAX_RETRIES": "3"},
            "redis_broker": {"FAKE_REDIS_BROKER_ENABLED": "true"},
            "volumes": {"FAKE_RUNTIME_VOLUMES": "true"},
            "volume_mount": {"FAKE_RUNTIME_VOLUME_MOUNT": "true"},
            "working_directory": {"FAKE_RUNTIME_WORKING_DIR": "/drift"},
            "vpc": {"FAKE_RUNTIME_VPC": "true"},
            "health_disabled": {"FAKE_RUNTIME_HEALTH_DISABLED": "true"},
            "base_image": {
                "FAKE_RUNTIME_BASE_IMAGE": "us-docker.pkg.dev/serverless-runtimes/x"
            },
            "sandbox_launcher": {"FAKE_RUNTIME_SANDBOX": "true"},
        }
        for name, mutation in mutations.items():
            with (
                self.subTest(mutation=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                environment = self._fixture(directory)
                environment.update(mutation)
                result = self._run(directory, environment, "rollback", "agent-target")
                operations = (Path(directory) / "operations.log").read_text(
                    encoding="utf-8"
                )

                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("--to-revisions", operations)

    def test_each_job_drift_stops_after_update_and_before_run(self) -> None:
        mutations = {
            "command": {"FAKE_JOB_COMMAND": "bash"},
            "identity": {
                "FAKE_JOB_SERVICE_ACCOUNT": (
                    "agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
                )
            },
            "secret": {"FAKE_JOB_SECRET": "agent-database-url"},
            "secret_alias": {"FAKE_JOB_SECRET_VERSION": "latest"},
            "retries": {"FAKE_JOB_MAX_RETRIES": "1"},
            "timeout": {"FAKE_JOB_TIMEOUT": "600s"},
            "resources": {"FAKE_JOB_CPU": "2"},
            "image": {
                "FAKE_JOB_IMAGE": (
                    "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/"
                    "agent@sha256:" + "4" * 64
                )
            },
            "volumes": {"FAKE_JOB_VOLUMES": "true"},
            "volume_mount": {"FAKE_JOB_VOLUME_MOUNT": "true"},
            "working_directory": {"FAKE_JOB_WORKING_DIR": "/drift"},
            "vpc": {"FAKE_JOB_VPC": "true"},
            "base_image": {
                "FAKE_JOB_BASE_IMAGE": "us-docker.pkg.dev/serverless-runtimes/x"
            },
            "sandbox_launcher": {"FAKE_JOB_SANDBOX": "true"},
        }
        for name, mutation in mutations.items():
            with (
                self.subTest(mutation=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                environment = self._fixture(directory)
                environment.update(mutation)
                result = self._run(directory, environment, "deploy")
                operations = (Path(directory) / "operations.log").read_text(
                    encoding="utf-8"
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn("gcloud run jobs update agent-migrate", operations)
                self.assertIn("/jobs/agent-migrate", operations)
                self.assertNotIn("/jobs/agent-migrate:run", operations)
                self.assertNotIn("gcloud run services update agent", operations)

    def test_job_etag_drift_fails_closed_before_execution_or_service_update(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["FAKE_JOB_ETAG_DRIFT_BEFORE_RUN"] = "true"
            result = self._run(directory, environment, "deploy")
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("/jobs/agent-migrate:run", operations)
        self.assertNotIn("gcloud run services update agent", operations)
        self.assertEqual(
            [
                {
                    "job": "agent-migrate",
                    "body": {"etag": "etag-agent-migrate-9"},
                }
            ],
            state["run_requests"],
        )

    def test_immutable_execution_template_drift_fails_before_service_update(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["FAKE_EXECUTION_IMAGE"] = (
                "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/"
                "agent@sha256:" + "5" * 64
            )
            result = self._run(directory, environment, "deploy")
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("immutable execution drifted", result.stderr)
        self.assertNotIn("gcloud run services update agent", operations)

    def test_pending_job_operation_is_polled_to_verified_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["FAKE_OPERATION_PENDING_JOB"] = "agent-migrate"
            result = self._run(directory, environment, "deploy")
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("/operations/op-agent-migrate", operations)

    def test_job_operation_error_or_nonzero_failure_counts_stop_delivery(
        self,
    ) -> None:
        mutations = {
            "operation_error": {"FAKE_OPERATION_ERROR": "true"},
            "failed": {"FAKE_FAILED_COUNT": "1", "FAKE_SUCCEEDED_COUNT": "0"},
            "cancelled": {
                "FAKE_CANCELLED_COUNT": "1",
                "FAKE_SUCCEEDED_COUNT": "0",
            },
            "retried": {"FAKE_RETRIED_COUNT": "1"},
        }
        for name, mutation in mutations.items():
            with (
                self.subTest(mutation=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                environment = self._fixture(directory)
                environment.update(mutation)
                result = self._run(directory, environment, "deploy")
                operations = (Path(directory) / "operations.log").read_text(
                    encoding="utf-8"
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn("successful immutable execution", result.stderr)
                self.assertNotIn("gcloud run services update agent", operations)

    def test_noncanonical_job_operation_name_stops_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["FAKE_OPERATION_NAME"] = (
                "projects/festive-ally-503605-v7/locations/europe-west1/"
                "operations/op-agent-migrate"
            )
            result = self._run(directory, environment, "deploy")
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("non-canonical operation name", result.stderr)
        self.assertNotIn("gcloud run services update agent", operations)

    def test_v1_or_hybrid_shape_is_rejected_before_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["FAKE_API_SHAPE"] = "v1"
            result = self._run(directory, environment, "deploy")
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("canonical REST v2", result.stderr)
        self.assertNotIn("gcloud run jobs update", operations)

    def test_rest_transport_metadata_fails_closed_before_jobs(self) -> None:
        mutations = {
            "status": {"FAKE_API_STATUS": "206"},
            "content_type": {"FAKE_API_CONTENT_TYPE": "text/html"},
            "empty": {"FAKE_API_SIZE": "0"},
            "oversize": {"FAKE_API_SIZE": "1048577"},
            "redirect": {"FAKE_API_REDIRECTS": "1"},
        }
        for name, mutation in mutations.items():
            with (
                self.subTest(mutation=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                environment = self._fixture(directory)
                environment.update(mutation)
                result = self._run(directory, environment, "deploy")
                operations = (Path(directory) / "operations.log").read_text(
                    encoding="utf-8"
                )

                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("gcloud run jobs update", operations)

    def test_wrong_project_fails_before_any_external_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["GCP_PROJECT_ID"] = "wrong-project"
            result = self._run(directory, environment, "deploy")
            log = Path(directory) / "operations.log"

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unexpected GCP project", result.stderr)
        self.assertFalse(log.exists())

    def test_cross_environment_job_fails_before_any_external_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["MIGRATION_JOB"] = "agent-preview-migrate"
            result = self._run(directory, environment, "deploy")
            log = Path(directory) / "operations.log"

        self.assertNotEqual(0, result.returncode)
        self.assertIn("exact migration job", result.stderr)
        self.assertFalse(log.exists())

    def test_invalid_delivery_run_id_fails_before_any_external_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["DELIVERY_RUN_ID"] = "latest"
            result = self._run(directory, environment, "deploy")
            log = Path(directory) / "operations.log"

        self.assertNotEqual(0, result.returncode)
        self.assertIn("positive numeric GitHub run ID", result.stderr)
        self.assertFalse(log.exists())

    def test_run_attempt_is_unique_and_length_bounded_for_reruns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["DELIVERY_RUN_ID"] = "9" * 20
            environment["DELIVERY_RUN_ATTEMPT"] = "8" * 16
            first = self._run(directory, environment, "deploy")
            state_path = Path(directory) / "state.json"
            first_revision = json.loads(state_path.read_text(encoding="utf-8"))[
                "serving"
            ]

            environment["DELIVERY_RUN_ATTEMPT"] = "7" * 16
            second = self._run(directory, environment, "deploy")
            second_revision = json.loads(state_path.read_text(encoding="utf-8"))[
                "serving"
            ]

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertNotEqual(first_revision, second_revision)
        self.assertLessEqual(len(first_revision), 63)
        self.assertLessEqual(len(second_revision), 63)

    def test_mutable_service_secret_alias_fails_before_jobs_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["FAKE_RUNTIME_SECRET_VERSION"] = "latest"
            result = self._run(directory, environment, "deploy")
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("runtime contract drifted", result.stderr)
        self.assertNotIn("gcloud run jobs update", operations)

    def test_unexpected_public_revision_tag_fails_before_jobs_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["FAKE_EXTRA_TRAFFIC_TAG"] = "true"
            result = self._run(directory, environment, "deploy")
            operations = (Path(directory) / "operations.log").read_text(
                encoding="utf-8"
            )

        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("gcloud run jobs update", operations)

    def test_unmanaged_service_input_drift_fails_before_jobs_run(self) -> None:
        mutations = {
            "build_config": {"FAKE_SERVICE_BUILD_CONFIG": "true"},
            "custom_audience": {"FAKE_SERVICE_CUSTOM_AUDIENCE": "true"},
            "manual_scaling": {"FAKE_SERVICE_SCALING": "true"},
            "iap": {"FAKE_SERVICE_IAP": "true"},
        }
        for name, mutation in mutations.items():
            with (
                self.subTest(mutation=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                environment = self._fixture(directory)
                environment.update(mutation)
                result = self._run(directory, environment, "deploy")
                operations = (Path(directory) / "operations.log").read_text(
                    encoding="utf-8"
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn("canonical REST v2", result.stderr)
                self.assertNotIn("gcloud run jobs update", operations)

    def test_smoke_tag_wrong_revision_or_percent_never_promotes(self) -> None:
        mutations = {
            "wrong_revision": {"FAKE_SMOKE_REVISION": "agent-unreviewed"},
            "nonzero_percent": {"FAKE_SMOKE_PERCENT": "1"},
            "extra_tag": {"FAKE_EXTRA_SMOKE_STAGE_TAG": "true"},
        }
        for name, mutation in mutations.items():
            with (
                self.subTest(mutation=name),
                tempfile.TemporaryDirectory() as directory,
            ):
                environment = self._fixture(directory)
                environment.update(mutation)
                result = self._run(directory, environment, "deploy")
                state = json.loads(
                    (Path(directory) / "state.json").read_text(encoding="utf-8")
                )

                self.assertNotEqual(0, result.returncode)
                self.assertEqual("agent-old", state["serving"])
                self.assertNotEqual(
                    f"agent-g{SOURCE_SHA[:8]}-r{DELIVERY_RUN_ID}"
                    f"-a{DELIVERY_RUN_ATTEMPT}",
                    state["serving"],
                )

    def test_reported_traffic_target_mismatch_restores_previous_revision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["FAKE_FIRST_TRAFFIC_TARGET_OVERRIDE"] = "agent-unreviewed"
            result = self._run(directory, environment, "deploy")
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("instead of", result.stderr)
        self.assertIn("restoring traffic to agent-old", result.stderr)
        self.assertEqual("agent-old", state["serving"])

    def test_smoke_tag_cleanup_failure_still_restores_previous_traffic(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            environment["FAIL_SMOKE_TAG_REMOVAL"] = "true"
            result = self._run(directory, environment, "deploy")
            state = json.loads(
                (Path(directory) / "state.json").read_text(encoding="utf-8")
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("public smoke tag could not be removed", result.stderr)
        self.assertIn("restoring traffic to agent-old", result.stderr)
        self.assertEqual("agent-old", state["serving"])
        self.assertTrue(state["smoke"])

    def test_manual_rollback_removes_stale_smoke_tag_before_shift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = self._fixture(directory)
            state_path = Path(directory) / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["smoke"] = True
            state_path.write_text(json.dumps(state), encoding="utf-8")

            result = self._run(directory, environment, "rollback", "agent-target")
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
