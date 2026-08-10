from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from scripts.ops_foundation_contract import (
    EXPECTED_SOURCE_CONDITIONS,
    EXPECTED_SOURCE_DELIVERY_ROLE_MAPPING,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_FILES = (
    "pyproject.toml",
    "uv.lock",
    "agent/pyproject.toml",
    "agent/src/agent/__init__.py",
    "eval/pyproject.toml",
    "infra/gcp/.terraform-version",
    "infra/gcp/backend.tf",
    "infra/gcp/cloud_run.tf",
    "infra/gcp/iam.tf",
    "infra/gcp/imports.tf",
    "infra/gcp/main.tf",
    "infra/gcp/outputs.tf",
    "infra/gcp/state.tf",
    "infra/gcp/tests/foundation.tftest.hcl",
    "infra/gcp/variables.tf",
    "infra/gcp/versions.tf",
    "scripts/gcp_project_readiness_contract.json",
    "scripts/ops_foundation_live_toolchain.py",
    "scripts/verify_gcp_project_readiness.py",
)
DISABLED_PREVIEW_CONDITION_LINE = (
    "  disabled_preview_wif_attribute_condition = "
    f'"{EXPECTED_SOURCE_CONDITIONS["disabled_preview"]}"\n'
)
DELIVERY_CONDITION_LINE = (
    "  delivery_wif_attribute_condition         = "
    f'"{EXPECTED_SOURCE_CONDITIONS["delivery"]}"\n'
)
DELIVERY_ROLE_MAPPING_LINE = (
    "  delivery_role_mapping                    = "
    f'"{EXPECTED_SOURCE_DELIVERY_ROLE_MAPPING}"\n'
)


def _foundation_fixture(directory: str | Path) -> Path:
    root = Path(directory)
    for relative_path in FIXTURE_FILES:
        source = REPO_ROOT / relative_path
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    verifier = root / "scripts/verify_ops_foundation.sh"
    verifier.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        REPO_ROOT / "scripts/verify_ops_foundation.sh",
        verifier,
    )
    verifier.chmod(0o755)
    shutil.copyfile(
        REPO_ROOT / "scripts/ops_foundation_contract.py",
        root / "scripts/ops_foundation_contract.py",
    )
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "add", "infra/gcp", "scripts/gcp_project_readiness_contract.json"],
        cwd=root,
        check=True,
    )
    return root


def _write_secure_python_wrapper(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o700)


class StaticVerifierMutationTests(unittest.TestCase):
    def test_legacy_preview_docker_config_ignore_is_narrowly_scoped(self) -> None:
        main_source = (REPO_ROOT / "infra/gcp/main.tf").read_text(encoding="utf-8")

        def repository_block(name: str) -> str:
            marker = f'resource "google_artifact_registry_repository" "{name}" {{'
            return main_source.split(marker, 1)[1].split('\nresource "', 1)[0]

        ignored_attribute = "ignore_changes  = [docker_config]"
        self.assertEqual(1, main_source.count(ignored_attribute))
        self.assertIn(ignored_attribute, repository_block("preview_agent"))
        for managed_repository in ("agent", "active_agent", "active_preview_agent"):
            with self.subTest(repository=managed_repository):
                self.assertNotIn(
                    ignored_attribute,
                    repository_block(managed_repository),
                )

    def test_artifact_iam_preserves_legacy_addresses_and_adds_active_mirrors(
        self,
    ) -> None:
        iam_source = (REPO_ROOT / "infra/gcp/iam.tf").read_text(encoding="utf-8")

        def resource_block(name: str) -> str:
            marker = (
                f'resource "google_artifact_registry_repository_iam_member" "{name}" {{'
            )
            return iam_source.split(marker, 1)[1].split("\n}", 1)[0]

        resource_pairs = {
            "builder_writer": "active_builder_writer",
            "preview_builder_writer": "active_preview_builder_writer",
            "deployer_reader": "active_deployer_reader",
            "preview_deployer_reader": "active_preview_deployer_reader",
            "cloud_run_reader": "active_cloud_run_reader",
            "preview_cloud_run_reader": "active_preview_cloud_run_reader",
        }
        for legacy_name, active_name in resource_pairs.items():
            with self.subTest(legacy=legacy_name, active=active_name):
                repository_name = (
                    "preview_agent" if "preview" in legacy_name else "agent"
                )
                self.assertIn(
                    "location   = local.legacy_artifact_registry_region",
                    resource_block(legacy_name),
                )
                self.assertIn(
                    "google_artifact_registry_repository."
                    f"{repository_name}.repository_id",
                    resource_block(legacy_name),
                )
                self.assertIn(
                    "location   = var.region",
                    resource_block(active_name),
                )
                self.assertIn(
                    "google_artifact_registry_repository."
                    f"active_{repository_name}.repository_id",
                    resource_block(active_name),
                )

        cloud_run_source = (REPO_ROOT / "infra/gcp/cloud_run.tf").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            5,
            cloud_run_source.count(
                "google_artifact_registry_repository_iam_member."
                "active_cloud_run_reader,"
            ),
        )
        self.assertNotIn(
            "    google_artifact_registry_repository_iam_member.cloud_run_reader,",
            cloud_run_source,
        )

    def test_cloud_runtime_contract_has_production_only_openai_credential(self) -> None:
        cloud_run_source = (REPO_ROOT / "infra/gcp/cloud_run.tf").read_text(
            encoding="utf-8"
        )
        preview, production = cloud_run_source.split("    production = {", 1)
        production_definition = production.split(
            "\n  production_cloud_run_environments = {", 1
        )[0]

        self.assertNotIn("OPENAI_API_KEY", preview)
        self.assertNotIn("agent-preview-openai-api-key", preview)
        self.assertEqual(1, production.count("OPENAI_API_KEY"))
        self.assertEqual(2, production.count('"openai-api-key"'))
        self.assertNotIn("ANTHROPIC_API_KEY", production_definition)
        self.assertNotIn("LANGCHAIN_API_KEY", production_definition)
        self.assertEqual(1, production_definition.count("AGENT_AUTH_SECRET"))
        self.assertEqual(1, production_definition.count("DATABASE_URL"))
        self.assertEqual(1, production_definition.count("OPENAI_API_KEY"))
        self.assertEqual(
            5,
            cloud_run_source.count("local.production_cloud_run_environments"),
        )
        self.assertIn('MODEL                     = "openai:gpt-5.6-luna"', production)

    def test_delivery_versions_are_four_production_numeric_pins(self) -> None:
        variables = (REPO_ROOT / "infra/gcp/variables.tf").read_text(encoding="utf-8")
        version_contract = variables.split('variable "agent_secret_versions" {', 1)[1]
        for secret in (
            "agent-auth-secret",
            "agent-database-url",
            "agent-migration-database-url",
            "openai-api-key",
        ):
            self.assertEqual(1, version_contract.count(f'"{secret}"'))
        for dormant_secret in (
            "agent-preview-auth-secret",
            "anthropic-api-key",
            "langsmith-api-key",
        ):
            self.assertNotIn(dormant_secret, version_contract)
        self.assertIn('can(regex("^[1-9][0-9]*$", version))', version_contract)

    def test_ci_container_uses_the_production_luna_secret_contract(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        model_position = workflow.index("--env MODEL=openai:gpt-5.6-luna")
        docker_start = workflow.rindex(
            "          docker run",
            0,
            model_position,
        )
        docker_end = workflow.index('            "$image_tag"', model_position)
        docker_runtime = workflow[docker_start:docker_end]

        self.assertIn("--env MODEL=openai:gpt-5.6-luna", docker_runtime)
        self.assertIn(
            "--env OPENAI_API_KEY=ci-only-not-a-real-openai-key",
            docker_runtime,
        )
        self.assertNotIn("ANTHROPIC_API_KEY", docker_runtime)
        self.assertNotIn("LANGCHAIN_API_KEY", docker_runtime)

    def test_broad_cloud_run_developer_role_is_absent(self) -> None:
        reviewed_paths = (
            REPO_ROOT / "DECISIONS.md",
            REPO_ROOT / "infra/gcp/README.md",
            REPO_ROOT / "docs/runbooks/cloud-run-delivery.md",
            REPO_ROOT / "docs/runbooks/gcp-neon-foundation.md",
            *(REPO_ROOT / "infra/gcp").glob("*.tf"),
        )

        for path in reviewed_paths:
            with self.subTest(path=path.relative_to(REPO_ROOT)):
                self.assertNotIn(
                    "roles/run" + ".developer",
                    path.read_text(encoding="utf-8"),
                )

    def _fixture(self, directory: str) -> Path:
        return _foundation_fixture(directory)

    def _run(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["scripts/verify_ops_foundation.sh", "--static"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

    def _mutate_condition(
        self,
        root: Path,
        expected_line: str,
        mutation: Callable[[str], str],
    ) -> None:
        main_path = root / "infra/gcp/main.tf"
        original = main_path.read_text(encoding="utf-8")
        self.assertEqual(1, original.count(expected_line))
        mutated = original.replace(
            expected_line,
            mutation(expected_line),
            1,
        )
        main_path.write_text(mutated, encoding="utf-8")

    def test_reviewed_contract_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(self._fixture(directory))

        self.assertEqual(0, result.returncode, result.stderr)

    def test_static_rejects_readiness_oracle_digest_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            oracle = root / "scripts/gcp_project_readiness_contract.json"
            oracle.write_text(
                oracle.read_text(encoding="utf-8").replace(
                    '"region": "asia-southeast1"',
                    '"region": "us-central1"',
                    1,
                ),
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("readiness oracle content digest is not exact", result.stderr)

    def test_static_rejects_untracked_readiness_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            subprocess.run(
                [
                    "git",
                    "rm",
                    "--cached",
                    "--quiet",
                    "scripts/gcp_project_readiness_contract.json",
                ],
                cwd=root,
                check=True,
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("pinned readiness oracle must be tracked", result.stderr)

    def test_builder_role_arms_are_lazy_before_optional_environment_claims(
        self,
    ) -> None:
        self.assertIn(
            "assertion.workflow_ref == "
            "'syshin0116/syshin0116.dev/.github/workflows/preview-agent.yml@' + "
            "assertion.ref ? (assertion.job_workflow_ref == "
            "'syshin0116/syshin0116.dev/.github/workflows/agent-image-build.yml@' + "
            "assertion.ref ? 'preview-builder' : assertion.environment == ",
            EXPECTED_SOURCE_DELIVERY_ROLE_MAPPING,
        )
        self.assertIn(
            "assertion.workflow_ref == "
            "'syshin0116/syshin0116.dev/.github/workflows/deploy-agent.yml@"
            "refs/heads/main' ? (assertion.job_workflow_ref == "
            "'syshin0116/syshin0116.dev/.github/workflows/agent-image-build.yml@"
            "refs/heads/main' ? 'production-builder' : assertion.environment == ",
            EXPECTED_SOURCE_DELIVERY_ROLE_MAPPING,
        )
        self.assertNotIn("environment", EXPECTED_SOURCE_CONDITIONS["delivery"])
        self.assertNotIn("assertion.", EXPECTED_SOURCE_CONDITIONS["delivery"])

    def test_static_rejects_ignored_destructive_override_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            (root / ".gitignore").write_text("*_override.tf\n", encoding="utf-8")
            override = root / "infra/gcp/local_override.tf"
            override.write_text(
                """
resource "google_project_service" "required" {
  for_each = toset([])

  disable_on_destroy = true
}
""",
                encoding="utf-8",
            )
            ignored = subprocess.run(
                ["git", "check-ignore", "--quiet", str(override.relative_to(root))],
                cwd=root,
                check=False,
            )
            self.assertEqual(0, ignored.returncode)

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("on-disk Terraform loadable inventory mismatch", result.stderr)
        self.assertIn("infra/gcp/local_override.tf", result.stderr)

    def test_disk_inventory_rejects_every_loadable_filename_family(self) -> None:
        candidates = (
            "infra/gcp/unreviewed.tf",
            "infra/gcp/unreviewed.tf.json",
            "infra/gcp/override.tf",
            "infra/gcp/override.tf.json",
            "infra/gcp/local_override.tf",
            "infra/gcp/local_override.tf.json",
            "infra/gcp/terraform.tfvars",
            "infra/gcp/terraform.tfvars.json",
            "infra/gcp/unreviewed.tfvars",
            "infra/gcp/unreviewed.tfvars.json",
            "infra/gcp/unreviewed.auto.tfvars",
            "infra/gcp/unreviewed.auto.tfvars.json",
            "infra/gcp/unreviewed.tftest.hcl",
            "infra/gcp/tests/unreviewed.tftest.json",
            "infra/gcp/unreviewed.tfmock.hcl",
            "infra/gcp/unreviewed.tfmock.json",
        )
        for relative_path in candidates:
            with (
                self.subTest(relative_path=relative_path),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = self._fixture(directory)
                candidate = root / relative_path
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text(
                    "malformed and must not be read\n", encoding="utf-8"
                )

                result = self._run(root)

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "on-disk Terraform loadable inventory mismatch",
                    result.stderr,
                )
                self.assertIn(relative_path, result.stderr)

    def test_disk_inventory_rejects_allowlisted_path_when_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            subprocess.run(
                ["git", "rm", "--cached", "--quiet", "infra/gcp/main.tf"],
                cwd=root,
                check=True,
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("tracked Terraform loadable inventory mismatch", result.stderr)
        self.assertIn("infra/gcp/main.tf", result.stderr)

    def test_disk_inventory_allows_only_ignored_untracked_real_terraform_dir(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            (root / ".gitignore").write_text("**/.terraform/\n", encoding="utf-8")
            internal = root / "infra/gcp/.terraform"
            internal.mkdir()
            os.mkfifo(internal / "must-not-be-inspected.tf")

            result = self._run(root)

        self.assertEqual(0, result.returncode, result.stderr)

    def test_disk_inventory_rejects_unignored_real_terraform_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            (root / "infra/gcp/.terraform").mkdir()

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("infra/gcp/.terraform must be gitignored", result.stderr)

    def test_disk_inventory_rejects_invalid_terraform_entry_kinds(self) -> None:
        mutations = ("regular", "symlink", "fifo")
        for mutation in mutations:
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = self._fixture(directory)
                internal = root / "infra/gcp/.terraform"
                if mutation == "regular":
                    internal.write_text("must not be read\n", encoding="utf-8")
                elif mutation == "symlink":
                    internal.symlink_to(
                        root / "does-not-exist",
                        target_is_directory=True,
                    )
                    subprocess.run(
                        ["git", "add", "--force", "infra/gcp/.terraform"],
                        cwd=root,
                        check=True,
                    )
                else:
                    os.mkfifo(internal)

                result = self._run(root)

                self.assertNotEqual(0, result.returncode)
                self.assertIn("infra/gcp/.terraform", result.stderr)
                self.assertIn(mutation, result.stderr)

    def test_disk_inventory_rejects_tracked_terraform_subtree_without_reading(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            (root / ".gitignore").write_text("**/.terraform/\n", encoding="utf-8")
            internal = root / "infra/gcp/.terraform"
            internal.mkdir()
            sentinel = internal / "must-not-be-read"
            sentinel.write_text("opaque internal data\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "--force", str(sentinel.relative_to(root))],
                cwd=root,
                check=True,
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("tracked .terraform paths are forbidden", result.stderr)
        self.assertIn(str(sentinel.relative_to(root)), result.stderr)

    def test_disk_inventory_rejects_symlinked_infra_path_components(self) -> None:
        for component in ("infra", "infra/gcp"):
            with (
                self.subTest(component=component),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = self._fixture(directory)
                original = root / component
                relocated = root / f"{component.replace('/', '-')}-real"
                original.rename(relocated)
                original.symlink_to(relocated, target_is_directory=True)

                result = self._run(root)

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    f"{component} must be a real directory",
                    result.stderr,
                )

    def test_disk_inventory_rejects_untracked_symlink_and_non_regular_candidates(
        self,
    ) -> None:
        mutations = ("regular", "symlink", "fifo")
        for mutation in mutations:
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = self._fixture(directory)
                candidate = root / f"infra/gcp/unreviewed-{mutation}.tf"
                if mutation == "regular":
                    candidate.write_text("# must not be read\n", encoding="utf-8")
                elif mutation == "symlink":
                    candidate.symlink_to(root / "does-not-exist")
                else:
                    os.mkfifo(candidate)

                result = subprocess.run(
                    ["scripts/verify_ops_foundation.sh", "--static"],
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "on-disk Terraform loadable inventory mismatch",
                    result.stderr,
                )
                self.assertIn(str(candidate.relative_to(root)), result.stderr)
                self.assertIn(mutation, result.stderr)

    def test_new_fmt_candidate_kinds_preflight_before_invoking_terraform(self) -> None:
        mutations = {
            "regular": "infra/gcp/unreviewed-regular.tfvars",
            "symlink": "infra/gcp/unreviewed-symlink.tfmock.hcl",
            "fifo": "infra/gcp/unreviewed-fifo.tfvars",
        }
        for mutation, relative_path in mutations.items():
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = self._fixture(directory)
                candidate = root / relative_path
                if mutation == "regular":
                    candidate.write_text("must not be read\n", encoding="utf-8")
                elif mutation == "symlink":
                    candidate.symlink_to(root / "does-not-exist")
                else:
                    os.mkfifo(candidate)

                fake_bin = root / "fake-bin"
                fake_bin.mkdir()
                marker = root / "terraform-was-invoked"
                fake_terraform = fake_bin / "terraform"
                fake_terraform.write_text(
                    '#!/bin/bash\n: > "$TERRAFORM_MARKER"\nexit 0\n',
                    encoding="utf-8",
                )
                fake_terraform.chmod(0o755)
                environment = os.environ.copy()
                environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
                environment["TERRAFORM_MARKER"] = str(marker)

                result = subprocess.run(
                    [
                        "scripts/verify_ops_foundation.sh",
                        "--terraform-fmt",
                    ],
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                    timeout=20,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn(relative_path, result.stderr)
                self.assertIn(mutation, result.stderr)
                self.assertFalse(marker.exists())

    def test_terraform_wrapper_modes_preflight_before_invoking_terraform(self) -> None:
        modes = (
            "--terraform-fmt",
            "--terraform-init",
            "--terraform-validate",
            "--terraform-test",
        )
        for mode in modes:
            with (
                self.subTest(mode=mode),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = self._fixture(directory)
                (root / "infra/gcp/rogue.tf.json").write_text(
                    "{}\n",
                    encoding="utf-8",
                )
                fake_bin = root / "fake-bin"
                fake_bin.mkdir()
                marker = root / "terraform-was-invoked"
                fake_terraform = fake_bin / "terraform"
                fake_terraform.write_text(
                    '#!/bin/bash\n: > "$TERRAFORM_MARKER"\nexit 0\n',
                    encoding="utf-8",
                )
                fake_terraform.chmod(0o755)
                environment = os.environ.copy()
                environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
                environment["TERRAFORM_MARKER"] = str(marker)

                result = subprocess.run(
                    ["scripts/verify_ops_foundation.sh", mode],
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "on-disk Terraform loadable inventory mismatch",
                    result.stderr,
                )
                self.assertFalse(marker.exists())

    def test_terraform_test_runner_rejects_zero_discovered_tests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            fake_terraform = fake_bin / "terraform"
            fake_terraform.write_text(
                """#!/bin/bash
printf '%s\n' \
  '{"type":"version","terraform":"1.15.8"}' \
  '{"type":"test_abstract","test_abstract":{}}' \
  '{"type":"test_summary","test_summary":{"status":"pass","passed":0,"failed":0,"errored":0,"skipped":0}}'
""",
                encoding="utf-8",
            )
            fake_terraform.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"

            result = subprocess.run(
                ["scripts/verify_ops_foundation.sh", "--terraform-test"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "discovery must exactly equal the reviewed file/run inventory",
            result.stderr,
        )

    def test_terraform_test_file_removal_and_drift_fail_closed(self) -> None:
        mutations = ("removed", "changed")
        for mutation in mutations:
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = self._fixture(directory)
                test_path = root / "infra/gcp/tests/foundation.tftest.hcl"
                if mutation == "removed":
                    subprocess.run(
                        [
                            "git",
                            "rm",
                            "--cached",
                            "--force",
                            "--quiet",
                            str(test_path.relative_to(root)),
                        ],
                        cwd=root,
                        check=True,
                    )
                    test_path.unlink()
                else:
                    test_path.write_text(
                        test_path.read_text(encoding="utf-8")
                        + "\n# unreviewed test drift\n",
                        encoding="utf-8",
                    )

                result = self._run(root)

            self.assertNotEqual(0, result.returncode)
            expected = (
                "on-disk Terraform loadable inventory mismatch"
                if mutation == "removed"
                else "Terraform test content digest is not exact"
            )
            self.assertIn(expected, result.stderr)

    def test_cloud_run_source_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            cloud_run_path = root / "infra/gcp/cloud_run.tf"
            original = cloud_run_path.read_text(encoding="utf-8")
            expected = "      max_instance_count = 1"
            self.assertEqual(1, original.count(expected))
            cloud_run_path.write_text(
                original.replace(expected, "      max_instance_count = 2", 1),
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Terraform source content digest is not exact", result.stderr)

    def test_guest_maintenance_scheduler_pause_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            cloud_run_path = root / "infra/gcp/cloud_run.tf"
            original = cloud_run_path.read_text(encoding="utf-8")
            expected = "  paused = false"
            self.assertEqual(1, original.count(expected))
            cloud_run_path.write_text(
                original.replace(expected, "  paused = true", 1),
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Terraform source content digest is not exact", result.stderr)

    def test_every_previously_unchecked_resource_body_fails_closed(self) -> None:
        mutations = {
            "project_service": (
                "infra/gcp/main.tf",
                "  disable_on_destroy = false",
                "  disable_on_destroy = true",
            ),
            "artifact_registry": (
                "infra/gcp/main.tf",
                (
                    '  description   = "Production agent images with bounded rollback retention"\n'
                    '  format        = "DOCKER"\n\n'
                    "  docker_config {\n"
                    "    # Each delivery writes a never-reused run/attempt tag and deploys the\n"
                    "    # resolved digest. Tags must remain mutable so cleanup policies can remove\n"
                    "    # expired tagged versions.\n"
                    "    immutable_tags = false"
                ),
                (
                    '  description   = "Production agent images with bounded rollback retention"\n'
                    '  format        = "DOCKER"\n\n'
                    "  docker_config {\n"
                    "    # Each delivery writes a never-reused run/attempt tag and deploys the\n"
                    "    # resolved digest. Tags must remain mutable so cleanup policies can remove\n"
                    "    # expired tagged versions.\n"
                    "    immutable_tags = true"
                ),
            ),
            "production_runtime": (
                "infra/gcp/main.tf",
                '  account_id   = "agent-runtime"',
                '  account_id   = "agent-runtime-changed"',
            ),
            "preview_runtime": (
                "infra/gcp/main.tf",
                '  account_id   = "agent-preview-runtime"',
                '  account_id   = "agent-preview-runtime-changed"',
            ),
            "deployers": (
                "infra/gcp/main.tf",
                "  for_each = local.deployers",
                "  for_each = {}",
            ),
            "cloud_run_delivery_role_extra_permission": (
                "infra/gcp/iam.tf",
                '    "run.jobs.run",',
                '    "run.jobs.run",\n    "run.jobs.runWithOverrides",',
            ),
            "production_secrets": (
                "infra/gcp/main.tf",
                "  for_each = local.production_secret_names",
                "  for_each = local.preview_secret_names",
            ),
            "preview_secrets": (
                "infra/gcp/main.tf",
                "  for_each = local.preview_secret_names",
                "  for_each = local.production_secret_names",
            ),
            "state_bucket": (
                "infra/gcp/state.tf",
                "  force_destroy               = false",
                "  force_destroy               = true",
            ),
        }
        for name, (relative_path, expected, replacement) in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self._fixture(directory)
                path = root / relative_path
                original = path.read_text(encoding="utf-8")
                self.assertEqual(1, original.count(expected))
                path.write_text(
                    original.replace(expected, replacement, 1),
                    encoding="utf-8",
                )

                result = self._run(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "Terraform resource configuration is not exact",
                result.stderr,
            )

    def test_locals_check_and_outputs_are_exact(self) -> None:
        mutations = {
            "main_locals": (
                "infra/gcp/main.tf",
                '    "storage.googleapis.com",',
                '    "storage.googleapis.com.disabled",',
                "Terraform locals configuration is not exact",
            ),
            "iam_locals": (
                "infra/gcp/iam.tf",
                "    preview    = google_service_account.preview_runtime.name",
                "    preview    = google_service_account.runtime.name",
                "Terraform locals configuration is not exact",
            ),
            "check": (
                "infra/gcp/main.tf",
                "condition     = length(setintersection(local.production_secret_names, local.preview_secret_names)) == 0",
                "condition     = length(setintersection(local.production_secret_names, local.preview_secret_names)) >= 0",
                "Terraform check configuration is not exact",
            ),
            "output": (
                "infra/gcp/outputs.tf",
                "",
                """

output "unreviewed_sensitive_value" {
  value = local.production_secret_names
}
""",
                "Terraform output inventory and bodies must exactly match",
            ),
        }
        for name, (relative_path, expected, replacement, error) in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self._fixture(directory)
                path = root / relative_path
                original = path.read_text(encoding="utf-8")
                if expected:
                    self.assertEqual(1, original.count(expected))
                    mutated = original.replace(expected, replacement, 1)
                else:
                    mutated = original + replacement
                path.write_text(mutated, encoding="utf-8")

                result = self._run(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(error, result.stderr)

    def test_full_comment_and_zero_test_bypass_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            main_path = root / "infra/gcp/main.tf"
            main_source = main_path.read_text(encoding="utf-8")
            main_path.write_text(
                main_source.replace(
                    "  cleanup_policy_dry_run = false",
                    "  cleanup_policy_dry_run = true",
                    1,
                )
                + "\n# cleanup_policy_dry_run = false\n",
                encoding="utf-8",
            )
            state_path = root / "infra/gcp/state.tf"
            state_source = state_path.read_text(encoding="utf-8")
            insecure_state = (
                state_source.replace(
                    "  force_destroy               = false",
                    "  force_destroy               = true",
                )
                .replace(
                    '  public_access_prevention    = "enforced"',
                    '  public_access_prevention    = "inherited"',
                )
                .replace(
                    "  uniform_bucket_level_access = true",
                    "  uniform_bucket_level_access = false",
                )
                .replace("    enabled = true", "    enabled = false")
                .replace(
                    "retention_duration_seconds = 2592000",
                    "retention_duration_seconds = 604800",
                )
                .replace("    prevent_destroy = true", "    prevent_destroy = false")
            )
            state_path.write_text(
                insecure_state
                + """

# force_destroy = false
# public_access_prevention = "enforced"
# uniform_bucket_level_access = true
# enabled = true
# retention_duration_seconds = 2592000
# prevent_destroy = true
""",
                encoding="utf-8",
            )
            test_path = root / "infra/gcp/tests/foundation.tftest.hcl"
            subprocess.run(
                [
                    "git",
                    "rm",
                    "--cached",
                    "--force",
                    "--quiet",
                    str(test_path.relative_to(root)),
                ],
                cwd=root,
                check=True,
            )
            test_path.unlink()

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("on-disk Terraform loadable inventory mismatch", result.stderr)

    def test_governance_delegation_syncs_then_uses_validated_python(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            root = self._fixture(directory)
            manifest = root / ".github/repository-governance.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}\n", encoding="utf-8")
            governance = root / "scripts/verify_repository_governance.py"
            governance_args = root / "governance-args.txt"
            governance.write_text(
                "import pathlib, sys\n"
                f"pathlib.Path({str(governance_args)!r}).write_text("
                "'\\n'.join(sys.argv[1:]) + '\\n', encoding='utf-8')\n",
                encoding="utf-8",
            )
            workspace_bin = root / ".venv/bin"
            workspace_bin.mkdir(parents=True)
            workspace_python = workspace_bin / "python3"
            _write_secure_python_wrapper(workspace_python)

            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            args_file = root / "uv-args.txt"
            fake_uv = fake_bin / "uv"
            fake_uv.write_text(
                "#!/bin/bash\n"
                "set -eu\n"
                f"/usr/bin/printf '%s\\n' \"$@\" > {shlex.quote(str(args_file))}\n",
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)
            fake_gh = fake_bin / "gh"
            fake_gh.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
            fake_gh.chmod(0o755)

            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            result = subprocess.run(
                ["scripts/verify_ops_foundation.sh", "--governance-live"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [
                    "sync",
                    "--project",
                    str(root.resolve()),
                    "--python",
                    str(workspace_python),
                    "--no-config",
                    "--no-python-downloads",
                    "--frozen",
                    "--package",
                    "syshin0116-dev-agent",
                    "--all-extras",
                    "--dev",
                ],
                args_file.read_text(encoding="utf-8").splitlines(),
            )
            self.assertEqual(
                [
                    "--live",
                    "--gh-bin",
                    str(fake_gh.resolve()),
                ],
                governance_args.read_text(encoding="utf-8").splitlines(),
            )

    def test_live_modes_reject_workspace_python_before_execution(self) -> None:
        for mode in ("--live", "--governance-live"):
            with (
                self.subTest(mode=mode),
                tempfile.TemporaryDirectory(dir=Path.home()) as directory,
            ):
                root = self._fixture(directory)
                manifest = root / ".github/repository-governance.json"
                manifest.parent.mkdir(parents=True)
                manifest.write_text("{}\n", encoding="utf-8")
                governance = root / "scripts/verify_repository_governance.py"
                governance.write_text("raise SystemExit(0)\n", encoding="utf-8")

                marker = root / "untrusted-python-ran"
                workspace_bin = root / ".venv/bin"
                workspace_bin.mkdir(parents=True)
                workspace_python = workspace_bin / "python3"
                workspace_python.write_text(
                    "#!/bin/sh\n"
                    f"/usr/bin/printf '%s\\n' CALLED > {shlex.quote(str(marker))}\n",
                    encoding="utf-8",
                )
                workspace_python.chmod(0o770)

                fake_bin = root / "fake-bin"
                fake_bin.mkdir()
                uv_marker = root / "uv-ran"
                fake_uv = fake_bin / "uv"
                fake_uv.write_text(
                    "#!/bin/sh\n"
                    f"/usr/bin/printf '%s\\n' CALLED > {shlex.quote(str(uv_marker))}\n"
                    f"exec {shlex.quote(str(workspace_python))}\n",
                    encoding="utf-8",
                )
                fake_uv.chmod(0o755)
                for tool in ("gh", "gcloud"):
                    executable = fake_bin / tool
                    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                    executable.chmod(0o755)

                environment = os.environ.copy()
                environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
                result = subprocess.run(
                    ["scripts/verify_ops_foundation.sh", mode],
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                    env=environment,
                )

                self.assertNotEqual(0, result.returncode)
                self.assertIn("group/other writable", result.stderr)
                self.assertFalse(uv_marker.exists())
                self.assertFalse(marker.exists())

    def test_live_revalidates_workspace_python_after_sync(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            root = self._fixture(directory)
            manifest = root / ".github/repository-governance.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}\n", encoding="utf-8")
            governance = root / "scripts/verify_repository_governance.py"
            governance.write_text("raise SystemExit(0)\n", encoding="utf-8")

            marker = root / "replacement-python-ran"
            workspace_bin = root / ".venv/bin"
            workspace_bin.mkdir(parents=True)
            workspace_python = workspace_bin / "python3"
            _write_secure_python_wrapper(workspace_python)
            replacement = root / "replacement-python"
            replacement.write_text(
                "#!/bin/sh\n"
                f"/usr/bin/printf '%s\\n' CALLED > {shlex.quote(str(marker))}\n",
                encoding="utf-8",
            )
            replacement.chmod(0o770)

            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            uv_marker = root / "uv-ran"
            fake_uv = fake_bin / "uv"
            fake_uv.write_text(
                "#!/bin/sh\n"
                f"/usr/bin/printf '%s\\n' CALLED > {shlex.quote(str(uv_marker))}\n"
                f"exec /bin/mv {shlex.quote(str(replacement))} "
                f"{shlex.quote(str(workspace_python))}\n",
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)
            fake_gh = fake_bin / "gh"
            fake_gh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_gh.chmod(0o755)

            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            result = subprocess.run(
                ["scripts/verify_ops_foundation.sh", "--governance-live"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("group/other writable", result.stderr)
            self.assertTrue(uv_marker.exists())
            self.assertFalse(marker.exists())

    def test_governance_live_missing_workspace_python_stops_before_sync(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            root = self._fixture(directory)
            manifest = root / ".github/repository-governance.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}\n", encoding="utf-8")
            governance = root / "scripts/verify_repository_governance.py"
            governance.write_text("raise SystemExit(0)\n", encoding="utf-8")

            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            uv_marker = root / "uv-ran"
            fake_uv = fake_bin / "uv"
            fake_uv.write_text(
                "#!/bin/sh\n"
                f"/usr/bin/printf '%s\\n' CALLED > {shlex.quote(str(uv_marker))}\n",
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)
            fake_gh = fake_bin / "gh"
            fake_gh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_gh.chmod(0o755)

            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            result = subprocess.run(
                ["scripts/verify_ops_foundation.sh", "--governance-live"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("must exist before live sync", result.stderr)
            self.assertFalse(uv_marker.exists())

    def test_preview_condition_mutations_fail_closed(self) -> None:
        mutations: dict[str, Callable[[str], str]] = {
            "or_true": lambda line: line.replace(
                "assertion.environment == '${var.github_preview_environment}' && ",
                "(assertion.environment == '${var.github_preview_environment}' || "
                "true) && ",
            ),
            "dropped_event_clause": lambda line: line.replace(
                "assertion.event_name == 'pull_request' && ",
                "",
            ),
            "builder_requires_environment": lambda line: line.replace(
                "(assertion.job_workflow_ref == "
                "'syshin0116/syshin0116.dev/.github/workflows/"
                "agent-image-build.yml@' + assertion.ref ? 'preview-builder'",
                "(assertion.environment == '${var.github_preview_environment}' && "
                "assertion.job_workflow_ref == "
                "'syshin0116/syshin0116.dev/.github/workflows/"
                "agent-image-build.yml@' + assertion.ref ? 'preview-builder'",
            ),
        }

        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self._fixture(directory)
                self._mutate_condition(root, DELIVERY_ROLE_MAPPING_LINE, mutation)
                result = self._run(root)

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "Terraform locals configuration is not exact",
                    result.stderr,
                )

    def test_production_condition_mutations_fail_closed(self) -> None:
        mutations: dict[str, Callable[[str], str]] = {
            "or_true": lambda line: line.replace(
                "assertion.environment == '${var.github_production_environment}' && ",
                "(assertion.environment == '${var.github_production_environment}' || "
                "true) && ",
            ),
            "dropped_event_clause": lambda line: line.replace(
                "assertion.event_name in ['push', 'workflow_dispatch'] && ",
                "",
            ),
            "changed_grouping": lambda line: line.replace(
                "assertion.event_name in ['push', 'workflow_dispatch'] && "
                "assertion.ref == 'refs/heads/main'",
                "(assertion.event_name in ['push', 'workflow_dispatch'] && "
                "assertion.ref == 'refs/heads/main')",
            ),
            "builder_requires_environment": lambda line: line.replace(
                "(assertion.job_workflow_ref == "
                "'syshin0116/syshin0116.dev/.github/workflows/"
                "agent-image-build.yml@refs/heads/main' ? 'production-builder'",
                "(assertion.environment == '${var.github_production_environment}' && "
                "assertion.job_workflow_ref == "
                "'syshin0116/syshin0116.dev/.github/workflows/"
                "agent-image-build.yml@refs/heads/main' ? 'production-builder'",
            ),
        }

        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self._fixture(directory)
                self._mutate_condition(root, DELIVERY_ROLE_MAPPING_LINE, mutation)
                result = self._run(root)

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "Terraform locals configuration is not exact",
                    result.stderr,
                )

    def test_provider_condition_raw_or_unmapped_fields_fail_closed(self) -> None:
        mutations: dict[str, Callable[[str], str]] = {
            "raw_repository_id": lambda line: line.replace(
                "attribute.repository_id",
                "assertion.repository_id",
                1,
            ),
            "raw_owner_id": lambda line: line.replace(
                "attribute.repository_owner_id",
                "assertion.repository_owner_id",
                1,
            ),
            "raw_environment": lambda line: line.replace(
                "attribute.delivery_role in ",
                "assertion.environment == '${var.github_production_environment}' && "
                "attribute.delivery_role in ",
                1,
            ),
        }

        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self._fixture(directory)
                self._mutate_condition(root, DELIVERY_CONDITION_LINE, mutation)
                result = self._run(root)

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "Terraform locals configuration is not exact",
                    result.stderr,
                )

    def test_provider_cannot_wrap_reviewed_condition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            main_path = root / "infra/gcp/main.tf"
            original = main_path.read_text(encoding="utf-8")
            expected = (
                "  attribute_condition = "
                "local.disabled_preview_wif_attribute_condition\n"
            )
            self.assertEqual(1, original.count(expected))
            main_path.write_text(
                original.replace(
                    expected,
                    "  attribute_condition = "
                    '"(${local.disabled_preview_wif_attribute_condition}) || true"\n',
                    1,
                ),
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "resource configuration is not exact",
            result.stderr,
        )

    def test_unreviewed_secret_accessor_resource_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            iam_path = root / "infra/gcp/iam.tf"
            iam_path.write_text(
                iam_path.read_text(encoding="utf-8")
                + """

resource "google_secret_manager_secret_iam_member" "unreviewed_accessor" # parser-bypass
{
  project   = var.project_id
  secret_id = google_secret_manager_secret.runtime["agent-auth-secret"].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:unreviewed@example.invalid"
}
""",
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "Terraform resource declarations must exactly match",
            result.stderr,
        )

    def test_tracked_nested_terraform_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            rogue_path = root / "infra/gcp/nested/rogue.tf"
            rogue_path.parent.mkdir(parents=True)
            rogue_path.write_text(
                """
resource "google_project_iam_member" "rogue" {
  project = var.project_id
  role    = "roles/owner"
  member  = "allUsers"
}
""",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "add", "infra/gcp/nested/rogue.tf"],
                cwd=root,
                check=True,
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("on-disk Terraform loadable inventory mismatch", result.stderr)

    def test_tracked_json_terraform_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            rogue_path = root / "infra/gcp/rogue.tf.json"
            rogue_path.write_text(
                """
{
  "resource": {
    "google_project_iam_member": {
      "rogue": {
        "project": "${var.project_id}",
        "role": "roles/owner",
        "member": "allUsers"
      }
    }
  }
}
""",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "add", "infra/gcp/rogue.tf.json"],
                cwd=root,
                check=True,
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("on-disk Terraform loadable inventory mismatch", result.stderr)

    def test_module_block_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            main_path = root / "infra/gcp/main.tf"
            main_path.write_text(
                main_path.read_text(encoding="utf-8")
                + """

module "rogue" # parser-bypass
{
  source = "./nested"
}
""",
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("Terraform module blocks are prohibited", result.stderr)

    def test_third_weak_provider_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            main_path = root / "infra/gcp/main.tf"
            main_path.write_text(
                main_path.read_text(encoding="utf-8")
                + """

resource "google_iam_workload_identity_pool_provider" "weak" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-weak"

  attribute_mapping = {
    "google.subject" = "assertion.sub"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}
""",
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "Terraform resource declarations must exactly match",
            result.stderr,
        )

    def test_custom_provider_audience_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            main_path = root / "infra/gcp/main.tf"
            original = main_path.read_text(encoding="utf-8")
            expected = (
                "  oidc {\n"
                '    issuer_uri = "https://token.actions.githubusercontent.com"\n'
                "  }\n"
            )
            self.assertEqual(2, original.count(expected))
            main_path.write_text(
                original.replace(
                    expected,
                    "  oidc {\n"
                    '    issuer_uri       = "https://token.actions.githubusercontent.com"\n'
                    '    allowed_audiences = ["rogue"]\n'
                    "  }\n",
                    1,
                ),
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "resource configuration is not exact",
            result.stderr,
        )

    def test_changed_import_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            imports_path = root / "infra/gcp/imports.tf"
            original = imports_path.read_text(encoding="utf-8")
            expected = '"${var.project_id}-tfstate"'
            self.assertEqual(1, original.count(expected))
            imports_path.write_text(
                original.replace(expected, '"unreviewed-tfstate"', 1),
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("import targets and live object IDs", result.stderr)

    def test_changed_import_target_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            imports_path = root / "infra/gcp/imports.tf"
            original = imports_path.read_text(encoding="utf-8")
            expected = "to = google_service_account.runtime"
            self.assertEqual(1, original.count(expected))
            imports_path.write_text(
                original.replace(
                    expected,
                    "to = google_service_account.preview_runtime",
                    1,
                ),
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("import targets and live object IDs", result.stderr)

    def test_extra_import_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            imports_path = root / "infra/gcp/imports.tf"
            imports_path.write_text(
                imports_path.read_text(encoding="utf-8")
                + """

import # parser-bypass
{
  to = google_service_account.preview_runtime
  id = "projects/${var.project_id}/serviceAccounts/agent-preview-runtime@${var.project_id}.iam.gserviceaccount.com"
}
""",
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("import targets and live object IDs", result.stderr)

    def test_state_moving_blocks_fail_closed(self) -> None:
        mutations = {
            "moved": """

moved {
  from = google_service_account.runtime
  to   = google_service_account.preview_runtime
}
""",
            "removed": """

removed {
  from = google_service_account.runtime

  lifecycle {
    destroy = false
  }
}
""",
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self._fixture(directory)
                imports_path = root / "infra/gcp/imports.tf"
                imports_path.write_text(
                    imports_path.read_text(encoding="utf-8") + mutation,
                    encoding="utf-8",
                )

                result = self._run(root)

            self.assertNotEqual(0, result.returncode)
            expected_error = (
                "moved targets"
                if name == "moved"
                else "removed targets and state-only retention policy"
            )
            self.assertIn(expected_error, result.stderr)

    def test_retired_preview_openai_secret_cannot_be_destroyed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            imports_path = root / "infra/gcp/imports.tf"
            source = imports_path.read_text(encoding="utf-8")
            self.assertEqual(1, source.count("    destroy = false"))
            imports_path.write_text(
                source.replace("    destroy = false", "    destroy = true", 1),
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "removed targets and state-only retention policy",
            result.stderr,
        )

    def test_terraform_data_local_exec_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            main_path = root / "infra/gcp/main.tf"
            main_path.write_text(
                main_path.read_text(encoding="utf-8")
                + """

resource "terraform_data" "escape" # parser-bypass
{
  provisioner "local-exec" # parser-bypass
  {
    command = "true"
  }
}
""",
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("executable escape hatch", result.stderr)

    def test_extra_google_provider_alias_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            versions_path = root / "infra/gcp/versions.tf"
            versions_path.write_text(
                versions_path.read_text(encoding="utf-8")
                + """

provider "google" # parser-bypass
{
  alias   = "unreviewed"
  project = var.project_id
  region  = var.region
}
""",
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("provider configuration and aliases", result.stderr)

    def test_external_provider_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            versions_path = root / "infra/gcp/versions.tf"
            versions_path.write_text(
                versions_path.read_text(encoding="utf-8")
                + """

provider "external" # parser-bypass
{}
""",
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("provider configuration and aliases", result.stderr)

    def test_external_and_remote_state_data_fail_closed(self) -> None:
        mutations = {
            "external": """

data "external" "escape" # parser-bypass
{
  program = ["sh", "-c", "echo '{}'" ]
}
""",
            "remote_state": """

data "terraform_remote_state" "escape" # parser-bypass
{
  backend = "local"
  config = {
    path = "/tmp/escape.tfstate"
  }
}
""",
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self._fixture(directory)
                versions_path = root / "infra/gcp/versions.tf"
                versions_path.write_text(
                    versions_path.read_text(encoding="utf-8") + mutation,
                    encoding="utf-8",
                )

                result = self._run(root)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("data declarations must exactly match", result.stderr)

    def test_weakened_wif_variable_validation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            variables_path = root / "infra/gcp/variables.tf"
            original = variables_path.read_text(encoding="utf-8")
            exact = 'condition     = var.github_repository_id == "1102380057"'
            self.assertEqual(1, original.count(exact))
            variables_path.write_text(
                original.replace(
                    exact,
                    'condition     = var.github_repository_id != ""',
                    1,
                ),
                encoding="utf-8",
            )

            result = self._run(root)

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "variable github_repository_id body must exactly match",
            result.stderr,
        )


class LiveShellGuardTests(unittest.TestCase):
    @staticmethod
    def _unsigned_live_structure() -> dict[str, object]:
        return {
            "schemaVersion": "syshin0116.gcp-admin-iam-evidence/v1",
            "capturedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "project": {
                "id": "festive-ally-503605-v7",
                "number": "72919926064",
            },
            "ancestors": [
                {
                    "scope": "organizations/987654321",
                    "policy": {"bindings": []},
                    "rolePermissions": {},
                }
            ],
            "reviewedBindings": [],
        }

    def _write_unsigned_live_structure(self, directory: str) -> Path:
        evidence = Path(directory) / "unsigned-structure.json"
        evidence.write_text(
            json.dumps(self._unsigned_live_structure()),
            encoding="utf-8",
        )
        evidence.chmod(0o600)
        return evidence

    def _run_with_fake_gcloud_marker(
        self,
        *arguments: str,
        extra_env: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            live_mode = arguments == ("--live",)
            root = _foundation_fixture(directory) if live_mode else Path(directory)
            if live_mode:
                _write_secure_python_wrapper(root / ".venv/bin/python3")
            binary_dir = root / "bin"
            binary_dir.mkdir()
            log_path = root / "gcloud.log"
            fake_gcloud = binary_dir / "gcloud"
            fake_gcloud.write_text(
                "#!/bin/sh\nprintf '%s\\n' CALLED >>"
                f"{shlex.quote(str(log_path))}\nexit 99\n",
                encoding="utf-8",
            )
            fake_gcloud.chmod(0o755)
            fake_gh = binary_dir / "gh"
            fake_gh.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            fake_gh.chmod(0o755)
            if live_mode:
                fake_uv = binary_dir / "uv"
                fake_uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                fake_uv.chmod(0o755)
            environment = {
                key: value
                for key, value in os.environ.items()
                if key != "BASH_ENV"
                and not key.startswith(
                    ("BASH_FUNC_", "CLOUDSDK_", "GOOGLE_", "OPS_FOUNDATION_")
                )
            }
            environment.update(
                {
                    "FAKE_GCLOUD_LOG": str(log_path),
                    "PATH": f"{binary_dir}:{environment['PATH']}",
                }
            )
            if extra_env:
                environment.update(extra_env)
            result = subprocess.run(
                ["scripts/verify_ops_foundation.sh", *arguments],
                cwd=root if live_mode else REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        return result, log

    def test_operational_sourcing_is_rejected(self) -> None:
        environment = os.environ.copy()
        environment.pop("OPS_FOUNDATION_TEST_ONLY_SOURCE", None)
        verifier = shlex.quote(str(REPO_ROOT / "scripts/verify_ops_foundation.sh"))

        result = subprocess.run(
            [
                "/bin/bash",
                "--noprofile",
                "--norc",
                "-c",
                f"source {verifier} --help",
            ],
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("sourcing this verifier is unsupported", result.stderr)

    def test_test_only_source_override_cannot_activate_the_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            log_path = root / "gcloud.log"
            hostile_marker = root / "sourced-verifier-became-operational"
            fake_gcloud = binary_dir / "gcloud"
            fake_gcloud.write_text(
                """#!/bin/sh
printf '%s\n' CALLED >>"$FAKE_GCLOUD_LOG"
exit 99
""",
                encoding="utf-8",
            )
            fake_gcloud.chmod(0o755)
            fake_gh = binary_dir / "gh"
            fake_gh.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            fake_gh.chmod(0o755)
            environment = {
                key: value
                for key, value in os.environ.items()
                if key != "BASH_ENV"
                and not key.startswith(
                    ("BASH_FUNC_", "CLOUDSDK_", "GOOGLE_", "OPS_FOUNDATION_")
                )
            }
            environment.update(
                {
                    "FAKE_GCLOUD_LOG": str(log_path),
                    "HOSTILE_MARKER": str(hostile_marker),
                    "OPS_FOUNDATION_TEST_ONLY_SOURCE": "1",
                    "PATH": f"{binary_dir}:{environment['PATH']}",
                    "VERIFIER": str(REPO_ROOT / "scripts/verify_ops_foundation.sh"),
                }
            )
            result = subprocess.run(
                [
                    "/bin/bash",
                    "--noprofile",
                    "--norc",
                    "-c",
                    """
source "$VERIFIER" --help
source_status=$?
if declare -F verify_static_contract >/dev/null ||
  declare -F verify_live_contract >/dev/null ||
  declare -p PROJECT_ID >/dev/null 2>&1; then
  /usr/bin/printf '%s\n' OPERATIONAL >>"$HOSTILE_MARKER"
fi
exit "$source_status"
""",
                ],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            hostile_marker_was_written = hostile_marker.exists()

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", log)
        self.assertFalse(hostile_marker_was_written)
        self.assertNotIn("Usage:", result.stdout + result.stderr)
        self.assertNotIn("OK:", result.stdout + result.stderr)
        self.assertIn("sourcing this verifier is unsupported", result.stderr)

    def test_explicit_bash_interpreter_invocation_is_rejected(self) -> None:
        result = subprocess.run(
            [
                "/bin/bash",
                "scripts/verify_ops_foundation.sh",
                "--static",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "'bash script' is not a supported security boundary",
            result.stderr,
        )

    def test_live_dispatch_preserves_shell_boundary_and_order(self) -> None:
        verifier = (REPO_ROOT / "scripts/verify_ops_foundation.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("\n  gcloud ", verifier.casefold())
        self.assertNotIn("OPS_FOUNDATION_TEST_ONLY_SOURCE", verifier)
        self.assertNotIn("resolve_gcloud_binary", verifier)
        self.assertNotIn("is_allowed_gcloud_command", verifier)
        self.assertEqual(
            1,
            verifier.count(
                "prepare_live_python() {\n"
                "  validate_live_python\n"
                "  sync_live_python_environment\n"
                "  validate_live_python\n"
                "}\n"
            ),
        )
        self.assertEqual(
            1,
            verifier.count(
                "run_live_python() {\n"
                "  /usr/bin/env -i \\\n"
                '    HOME="$LIVE_TRUSTED_HOME" \\\n'
                '    PATH="$LIVE_CHILD_PATH" \\\n'
                '    "$LIVE_PYTHON_BIN" -I -s "$@"\n'
                "}\n"
            ),
        )
        self.assertEqual(
            1,
            verifier.count(
                "verify_static_contract_live() {\n"
                '  run_live_python "$CONTRACT_SCRIPT" static --repo-root '
                '"$REPO_ROOT"\n'
            ),
        )
        self.assertEqual(
            1,
            verifier.count(
                '      run_live_python "$GOVERNANCE_VERIFIER" --live --gh-bin '
                '"$LIVE_GH_BIN"\n'
            ),
        )
        self.assertEqual(
            1,
            verifier.count(
                "verify_live_contract() {\n"
                "  prepare_live_toolchain\n"
                "  prepare_live_python\n"
                "  verify_static_contract_live\n"
                "  /usr/bin/env -i \\\n"
                '    HOME="$LIVE_TRUSTED_HOME" \\\n'
                '    OPS_FOUNDATION_GCLOUD_ACCOUNT="${OPS_FOUNDATION_GCLOUD_ACCOUNT:-}" '
                "\\\n"
                '    PATH="$LIVE_CHILD_PATH" \\\n'
                '    "$LIVE_PYTHON_BIN" -E -s "$LIVE_GCP_VERIFIER" \\\n'
                '    --gcloud-bin "$LIVE_GCLOUD_BIN"\n'
                "  verify_canonical_repository_governance true\n"
                "  printf '%s\\n' \\\n"
                '    "OK: exact GCP-project direct state and canonical GitHub '
                "governance verified; public launch, spend safety, project parent, "
                'and inherited IAM are not claimed."\n'
                "}\n"
            ),
        )

    def test_no_argument_mode_defaults_to_static_without_gcloud(self) -> None:
        result, log = self._run_with_fake_gcloud_marker()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", log)
        self.assertIn(
            "credential-free Terraform security contract verified",
            result.stdout,
        )

    def test_multiple_mode_arguments_fail_before_dispatch(self) -> None:
        for arguments in (("--help", "--live"), ("--static", "--live")):
            with self.subTest(arguments=arguments):
                result, log = self._run_with_fake_gcloud_marker(*arguments)

                self.assertNotEqual(0, result.returncode)
                self.assertEqual("", log)
                self.assertNotIn("OK:", result.stdout + result.stderr)
                self.assertIn("at most one mode argument", result.stderr)

    def test_direct_live_ignores_exported_functions_and_bash_env(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            root = _foundation_fixture(directory)
            _write_secure_python_wrapper(root / ".venv/bin/python3")
            binary_dir = root / "bin"
            binary_dir.mkdir()
            log_path = root / "gcloud.log"
            hostile_marker = root / "hostile-environment-was-used"
            fake_gcloud = binary_dir / "gcloud"
            fake_gcloud.write_text(
                "#!/bin/sh\nprintf '%s\\n' CALLED >>"
                f"{shlex.quote(str(log_path))}\nexit 99\n",
                encoding="utf-8",
            )
            fake_gcloud.chmod(0o755)
            fake_gh = binary_dir / "gh"
            fake_gh.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            fake_gh.chmod(0o755)
            fake_uv = binary_dir / "uv"
            fake_uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_uv.chmod(0o755)
            hostile_bash_env = root / "hostile-bash-env"
            hostile_bash_env.write_text(
                ("/usr/bin/printf '%s\\n' BASH_ENV_LOADED >>\"$HOSTILE_MARKER\"\n"),
                encoding="utf-8",
            )
            evidence = self._write_unsigned_live_structure(directory)
            environment = {
                key: value
                for key, value in os.environ.items()
                if key != "BASH_ENV"
                and not key.startswith(
                    ("BASH_FUNC_", "CLOUDSDK_", "GOOGLE_", "OPS_FOUNDATION_")
                )
            }
            environment.update(
                {
                    "FAKE_GCLOUD_LOG": str(log_path),
                    "HOSTILE_BASH_ENV": str(hostile_bash_env),
                    "HOSTILE_MARKER": str(hostile_marker),
                    "OPS_FOUNDATION_ADMIN_EVIDENCE_FILE": str(evidence),
                    "PATH": f"{binary_dir}:{environment['PATH']}",
                    "VERIFIER": str(root / "scripts/verify_ops_foundation.sh"),
                }
            )
            result = subprocess.run(
                [
                    "/bin/bash",
                    "--noprofile",
                    "--norc",
                    "-c",
                    """
builtin() {
  /usr/bin/printf '%s\n' BUILTIN_CALLED >>"$HOSTILE_MARKER"
  return 0
}
exit() {
  /usr/bin/printf '%s\n' EXIT_CALLED >>"$HOSTILE_MARKER"
  return 0
}
type() {
  /usr/bin/printf '%s\n' TYPE_CALLED >>"$HOSTILE_MARKER"
  return 0
}
compgen() {
  /usr/bin/printf '%s\n' COMPGEN_CALLED >>"$HOSTILE_MARKER"
  return 0
}
export -f builtin exit type compgen
export BASH_ENV="$HOSTILE_BASH_ENV"
exec "$VERIFIER" --live
""",
                ],
                cwd=root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", log)
        self.assertFalse(hostile_marker.exists())
        self.assertNotIn("STRUCTURE ONLY / NOT AUTHENTICATED", result.stdout)
        self.assertIn("repository-pinned identity", result.stderr)

    def test_explicit_live_no_longer_requires_unsigned_evidence(
        self,
    ) -> None:
        result, log = self._run_with_fake_gcloud_marker(
            "--live",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", log)
        self.assertNotIn("ADMIN_EVIDENCE_FILE", result.stderr)
        self.assertIn("repository-pinned identity", result.stderr)

    def test_structure_only_mode_never_claims_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = self._write_unsigned_live_structure(directory)
            result, log = self._run_with_fake_gcloud_marker(
                "--offline-admin-evidence-structure",
                extra_env={"OPS_FOUNDATION_ADMIN_EVIDENCE_FILE": str(evidence)},
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", log)
        self.assertNotIn("OK:", result.stdout + result.stderr)
        self.assertIn("STRUCTURE ONLY / NOT AUTHENTICATED", result.stdout)

    def test_live_missing_pinned_account_blocks_before_any_gcloud_marker(self) -> None:
        result, log = self._run_with_fake_gcloud_marker("--live")

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", log)
        self.assertIn("repository-pinned identity", result.stderr)

    def test_live_rejects_caller_google_overrides_before_external_reads(self) -> None:
        for name in ("CLOUDSDK_CONFIG", "GOOGLE_APPLICATION_CREDENTIALS"):
            with self.subTest(name=name):
                result, log = self._run_with_fake_gcloud_marker(
                    "--live", extra_env={name: "/tmp/forbidden"}
                )

                self.assertNotEqual(0, result.returncode)
                self.assertEqual("", log)
                self.assertIn("environment overrides are forbidden", result.stderr)

    def test_live_rejects_insecure_path_before_hostile_tools_or_env_can_run(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            root = Path(directory)
            hostile_bin = root / "hostile-bin"
            hostile_bin.mkdir(mode=0o700)
            marker = root / "hostile-tool-ran"
            for name in ("gcloud", "gh", "uv"):
                executable = hostile_bin / name
                executable.write_text(
                    "#!/bin/sh\nprintf '%s\\n' CALLED >>"
                    f"{shlex.quote(str(marker))}\nexit 0\n",
                    encoding="utf-8",
                )
                executable.chmod(0o700)
            hostile_bin.chmod(0o777)
            environment = os.environ.copy()
            environment.update(
                {
                    "HOME": str(root / "forged-home"),
                    "HTTPS_PROXY": "http://127.0.0.1:9",
                    "LD_PRELOAD": "/definitely/missing/forged-loader.so",
                    "PATH": f"{hostile_bin}:{environment['PATH']}",
                    "PYTHONPATH": str(root / "forged-python"),
                    "REQUESTS_CA_BUNDLE": str(root / "forged-ca.pem"),
                    "VIRTUAL_ENV": str(root / "forged-venv"),
                }
            )

            result = subprocess.run(
                ["scripts/verify_ops_foundation.sh", "--live"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            marker_was_written = marker.exists()

        self.assertNotEqual(0, result.returncode)
        self.assertFalse(marker_was_written)
        self.assertIn("group/other writable", result.stderr)

    def test_live_does_not_treat_unsigned_structure_as_approval_or_prerequisite(
        self,
    ) -> None:
        for name, (content, mode) in {
            "malformed": ('{"schemaVersion":', 0o600),
            "public_mode": ("{}", 0o644),
        }.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                evidence = Path(directory) / "admin-evidence.json"
                evidence.write_text(content, encoding="utf-8")
                evidence.chmod(mode)
                result, log = self._run_with_fake_gcloud_marker(
                    "--live",
                    extra_env={"OPS_FOUNDATION_ADMIN_EVIDENCE_FILE": str(evidence)},
                )

                self.assertNotEqual(0, result.returncode)
                self.assertEqual("", log)
                self.assertNotIn("ADMIN_EVIDENCE_FILE", result.stderr)
                self.assertIn("repository-pinned identity", result.stderr)


class StateBucketMetadataTests(unittest.TestCase):
    @staticmethod
    def _metadata(location: object) -> dict[str, object]:
        return {
            "location": location,
            "public_access_prevention": "enforced",
            "uniform_bucket_level_access": True,
            "versioning_enabled": True,
            "soft_delete_policy": {
                "retentionDurationSeconds": "2592000",
            },
        }

    @staticmethod
    def _run_metadata(
        metadata: dict[str, object],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["scripts/verify_ops_foundation.sh", "--state-bucket-metadata"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            input=json.dumps(metadata),
        )

    def _run(self, location: object) -> subprocess.CompletedProcess[str]:
        return self._run_metadata(self._metadata(location))

    def test_state_bucket_metadata_accepts_configured_and_canonical_casing(
        self,
    ) -> None:
        for location in ("us-east4", "US-EAST4"):
            with self.subTest(location=location):
                result = self._run(location)

                self.assertEqual(0, result.returncode, result.stderr)

    def test_state_bucket_metadata_rejects_other_regions(self) -> None:
        for location in ("ASIA", "US-EAST5"):
            with self.subTest(location=location):
                result = self._run(location)

                self.assertNotEqual(0, result.returncode)
                self.assertIn("location must be exactly us-east4", result.stderr)

    def test_state_bucket_metadata_rejects_missing_and_non_string_location(
        self,
    ) -> None:
        invalid_locations = {
            "missing": None,
            "null": None,
            "number": 123,
            "array": ["US-EAST4"],
        }
        for case, location in invalid_locations.items():
            with self.subTest(case=case):
                metadata = self._metadata(location)
                if case == "missing":
                    del metadata["location"]

                result = self._run_metadata(metadata)

                self.assertNotEqual(0, result.returncode)
                self.assertIn("location must be exactly us-east4", result.stderr)


if __name__ == "__main__":
    unittest.main()
