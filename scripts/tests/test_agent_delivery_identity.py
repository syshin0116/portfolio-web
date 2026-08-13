from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts/validate_agent_delivery_identity.sh"

TARGETS = {
    "preview": {
        "environment": "Agent Preview",
        "builder": (
            "agent-preview-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
        ),
        "deployer": (
            "agent-preview-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
        ),
        "repository": (
            "asia-southeast1-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent"
        ),
        "service": "agent-preview",
    },
    "production": {
        "environment": "Agent Production",
        "builder": (
            "agent-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
        ),
        "deployer": (
            "agent-prod-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
        ),
        "repository": (
            "asia-southeast1-docker.pkg.dev/festive-ally-503605-v7/agent/agent"
        ),
        "service": "agent",
    },
}
PROVIDER = (
    "projects/72919926064/locations/global/workloadIdentityPools/"
    "github/providers/github-production"
)


def _environment(target: str, role: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "DELIVERY_ROLE": role,
            "DELIVERY_TARGET": target,
        }
    )
    environment.pop("DELIVERY_ENVIRONMENT", None)
    if role == "deployer":
        environment["DELIVERY_ENVIRONMENT"] = TARGETS[target]["environment"]
    return environment


class AgentDeliveryIdentityTests(unittest.TestCase):
    def test_builder_pushes_one_linux_runtime_digest(self) -> None:
        builder = (REPO_ROOT / ".github/workflows/agent-image-build.yml").read_text(
            encoding="utf-8"
        )

        setup = builder.index(
            "docker/setup-buildx-action@bb05f3f5519dd87d3ba754cc423b652a5edd6d2c"
        )
        auth = builder.index("google-github-actions/auth@")
        build = builder.index("docker buildx build")

        self.assertIn("driver: docker-container", builder)
        self.assertIn("--platform linux/amd64", builder)
        self.assertIn("--provenance=false", builder)
        self.assertIn("--sbom=false", builder)
        self.assertNotIn("resolve_agent_runtime_image.py", builder)
        self.assertLess(setup, auth)
        self.assertLess(auth, build)

    def test_preview_has_an_independent_fail_closed_gate(self) -> None:
        preview = (REPO_ROOT / ".github/workflows/preview-agent.yml").read_text(
            encoding="utf-8"
        )
        production = (REPO_ROOT / ".github/workflows/deploy-agent.yml").read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            1,
            preview.count("vars.AGENT_CLOUD_RUN_PREVIEW_ENABLED == 'true'"),
        )
        self.assertIn("vars.AGENT_CLOUD_RUN_ENABLED == 'true'", preview)
        self.assertNotIn("AGENT_CLOUD_RUN_PREVIEW_ENABLED", production)
        self.assertEqual(1, production.count("vars.AGENT_CLOUD_RUN_ENABLED == 'true'"))

    def test_preview_build_and_release_pin_pr_head_not_synthetic_merge_sha(
        self,
    ) -> None:
        preview = (REPO_ROOT / ".github/workflows/preview-agent.yml").read_text(
            encoding="utf-8"
        )
        builder = (REPO_ROOT / ".github/workflows/agent-image-build.yml").read_text(
            encoding="utf-8"
        )
        release = (REPO_ROOT / ".github/workflows/agent-release.yml").read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            2,
            preview.count("source_sha: ${{ github.event.pull_request.head.sha }}"),
        )
        self.assertNotIn("source_sha: ${{ github.sha }}", preview)
        self.assertIn("ref: ${{ inputs.source_sha }}", builder)
        self.assertIn("SOURCE_SHA: ${{ inputs.source_sha }}", builder)
        self.assertIn("ref: ${{ inputs.source_sha }}", release)
        self.assertIn("SOURCE_SHA: ${{ inputs.source_sha }}", release)
        self.assertNotIn("gcloud run jobs", release)

    def test_caller_only_concurrency_never_cancels_an_approved_release(self) -> None:
        preview = (REPO_ROOT / ".github/workflows/preview-agent.yml").read_text(
            encoding="utf-8"
        )
        production = (REPO_ROOT / ".github/workflows/deploy-agent.yml").read_text(
            encoding="utf-8"
        )
        release = (REPO_ROOT / ".github/workflows/agent-release.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "concurrency:\n  group: agent-preview\n  cancel-in-progress: false",
            preview,
        )
        self.assertIn(
            "concurrency:\n  group: agent-production\n  cancel-in-progress: false",
            production,
        )
        self.assertNotIn("\n    concurrency:\n", release)

    def test_release_uses_native_cloud_run_candidate_promotion(self) -> None:
        release = (REPO_ROOT / ".github/workflows/agent-release.yml").read_text(
            encoding="utf-8"
        )

        gate = release.index("Verify exact production revision passed CI")
        auth = release.index("google-github-actions/auth@")
        deploy = release.index("gcloud run services update")
        smoke = release.index('unauthenticated_status="$(')
        promote = release.index('--to-revisions "${revision}=100"')
        self.assertLess(gate, auth)
        self.assertLess(deploy, smoke)
        self.assertLess(smoke, promote)
        self.assertIn("ci/check protocol/compat wiki/verify", release)
        self.assertIn(".app.id == 15368", release)
        self.assertIn('select(.tag == "smoke") | .url', release)
        self.assertIn("trap cleanup_smoke_tag EXIT", release)
        self.assertIn('[[ "$unauthenticated_status" == "401" ]]', release)
        self.assertIn("--no-traffic", release)
        self.assertNotIn("AGENT_SMOKE_BEARER_TOKEN", release)
        self.assertNotIn("GCP_PROJECT_NUMBER", release)
        self.assertNotIn("astral-sh/setup-uv@", release)
        self.assertNotIn("scripts/deploy_cloud_run.sh", release)
        self.assertNotIn("gcloud run jobs", release)
        self.assertNotIn("runtime_env_args", release)
        self.assertIn("preview)\n              expected_repository=", release)
        self.assertIn("              set --\n              ;;", release)
        self.assertIn('            "$@" \\\n            --quiet', release)

    def test_each_builder_is_secretless_and_selects_only_its_repository(self) -> None:
        for target, values in TARGETS.items():
            with self.subTest(target=target):
                result = subprocess.run(
                    [str(VALIDATOR)],
                    cwd=REPO_ROOT,
                    env=_environment(target, "builder"),
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(f"workload_identity_provider={PROVIDER}\n", result.stdout)
                self.assertIn(f"service_account={values['builder']}\n", result.stdout)
                self.assertIn(
                    f"image_repository={values['repository']}\n", result.stdout
                )
                self.assertNotIn("cloud_run_service=", result.stdout)

    def test_each_deployer_selects_exact_runtime_resources(self) -> None:
        for target, values in TARGETS.items():
            with self.subTest(target=target):
                result = subprocess.run(
                    [str(VALIDATOR)],
                    cwd=REPO_ROOT,
                    env=_environment(target, "deployer"),
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(f"workload_identity_provider={PROVIDER}\n", result.stdout)
                self.assertIn(f"service_account={values['deployer']}\n", result.stdout)
                self.assertIn(f"cloud_run_service={values['service']}\n", result.stdout)
                self.assertNotIn("image_repository=", result.stdout)

    def test_builder_rejects_any_release_environment(self) -> None:
        environment = _environment("preview", "builder")
        environment["DELIVERY_ENVIRONMENT"] = "Agent Preview"

        result = subprocess.run(
            [str(VALIDATOR)],
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("must not receive", result.stderr)

    def test_every_cross_environment_deployer_fails_closed(self) -> None:
        for target in TARGETS:
            other = "production" if target == "preview" else "preview"
            with self.subTest(target=target):
                environment = _environment(target, "deployer")
                environment["DELIVERY_ENVIRONMENT"] = TARGETS[other]["environment"]
                result = subprocess.run(
                    [str(VALIDATOR)],
                    cwd=REPO_ROOT,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertIn("does not match", result.stderr)

    def test_unknown_target_or_role_fails_closed(self) -> None:
        for mutation in (
            {"DELIVERY_TARGET": "staging"},
            {"DELIVERY_ROLE": "operator"},
        ):
            with self.subTest(mutation=mutation):
                environment = _environment("preview", "builder")
                environment.update(mutation)
                result = subprocess.run(
                    [str(VALIDATOR)],
                    cwd=REPO_ROOT,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertIn("unexpected agent delivery", result.stderr)


if __name__ == "__main__":
    unittest.main()
