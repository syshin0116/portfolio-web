from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts/validate_agent_delivery_identity.sh"

IDENTITIES = {
    "Agent Preview": {
        "BUILDER_SERVICE_ACCOUNT": (
            "agent-preview-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
        ),
        "DEPLOYER_SERVICE_ACCOUNT": (
            "agent-preview-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
        ),
        "WORKLOAD_IDENTITY_PROVIDER": (
            "projects/72919926064/locations/global/workloadIdentityPools/"
            "github/providers/github-preview"
        ),
        "repository": (
            "us-east4-docker.pkg.dev/festive-ally-503605-v7/agent-preview/agent"
        ),
    },
    "Agent Production": {
        "BUILDER_SERVICE_ACCOUNT": (
            "agent-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com"
        ),
        "DEPLOYER_SERVICE_ACCOUNT": (
            "agent-prod-deployer@festive-ally-503605-v7.iam.gserviceaccount.com"
        ),
        "WORKLOAD_IDENTITY_PROVIDER": (
            "projects/72919926064/locations/global/workloadIdentityPools/"
            "github/providers/github-production"
        ),
        "repository": ("us-east4-docker.pkg.dev/festive-ally-503605-v7/agent/agent"),
    },
}


def _environment(name: str) -> dict[str, str]:
    values = IDENTITIES[name]
    environment = os.environ.copy()
    environment.update(
        {
            "BUILDER_SERVICE_ACCOUNT": values["BUILDER_SERVICE_ACCOUNT"],
            "DELIVERY_ENVIRONMENT": name,
            "DEPLOYER_SERVICE_ACCOUNT": values["DEPLOYER_SERVICE_ACCOUNT"],
            "WORKLOAD_IDENTITY_PROVIDER": values["WORKLOAD_IDENTITY_PROVIDER"],
        }
    )
    return environment


class AgentDeliveryIdentityTests(unittest.TestCase):
    def test_each_exact_environment_mapping_selects_only_its_repository(self) -> None:
        for name, values in IDENTITIES.items():
            with self.subTest(environment=name):
                result = subprocess.run(
                    [str(VALIDATOR)],
                    cwd=REPO_ROOT,
                    env=_environment(name),
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(
                    f"image_repository={values['repository']}\n",
                    result.stdout,
                )

    def test_every_cross_environment_identity_fails_closed(self) -> None:
        for name in IDENTITIES:
            other = "Agent Production" if name == "Agent Preview" else "Agent Preview"
            for variable in (
                "BUILDER_SERVICE_ACCOUNT",
                "DEPLOYER_SERVICE_ACCOUNT",
                "WORKLOAD_IDENTITY_PROVIDER",
            ):
                with self.subTest(environment=name, variable=variable):
                    environment = _environment(name)
                    environment[variable] = IDENTITIES[other][variable]

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

    def test_unknown_environment_fails_closed(self) -> None:
        environment = _environment("Agent Preview")
        environment["DELIVERY_ENVIRONMENT"] = "Preview"

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
        self.assertIn("unexpected agent delivery environment", result.stderr)


if __name__ == "__main__":
    unittest.main()
