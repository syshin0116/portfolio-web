from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Callable
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


class StaticVerifierMutationTests(unittest.TestCase):
    def test_cloud_runtime_contract_has_no_openai_credential(self) -> None:
        reviewed_paths = (
            REPO_ROOT / ".github/workflows/ci.yml",
            REPO_ROOT / "infra/gcp/cloud_run.tf",
            REPO_ROOT / "infra/gcp/main.tf",
            REPO_ROOT / "infra/gcp/variables.tf",
            REPO_ROOT / "scripts/deploy_cloud_run.sh",
            REPO_ROOT / "scripts/verify_ops_foundation.sh",
        )

        for path in reviewed_paths:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(REPO_ROOT)):
                self.assertNotIn("OPENAI_API_KEY", source)
                self.assertNotIn("openai-api-key", source)

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
            ["git", "add", "infra/gcp"],
            cwd=root,
            check=True,
        )
        return root

    def _run(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "scripts/verify_ops_foundation.sh", "--static"],
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
                    ["bash", "scripts/verify_ops_foundation.sh", "--static"],
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
                        "bash",
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
                    ["bash", "scripts/verify_ops_foundation.sh", mode],
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
  '{"type":"version","terraform":"1.13.5"}' \
  '{"type":"test_abstract","test_abstract":{}}' \
  '{"type":"test_summary","test_summary":{"status":"pass","passed":0,"failed":0,"errored":0,"skipped":0}}'
""",
                encoding="utf-8",
            )
            fake_terraform.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"

            result = subprocess.run(
                ["bash", "scripts/verify_ops_foundation.sh", "--terraform-test"],
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

    def test_guest_maintenance_scheduler_unpause_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            cloud_run_path = root / "infra/gcp/cloud_run.tf"
            original = cloud_run_path.read_text(encoding="utf-8")
            expected = "  paused = true"
            self.assertEqual(1, original.count(expected))
            cloud_run_path.write_text(
                original.replace(expected, "  paused = false", 1),
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

    def test_governance_delegation_uses_exact_pinned_uv_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            manifest = root / ".github/repository-governance.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}\n", encoding="utf-8")
            governance = root / "scripts/verify_repository_governance.py"
            governance.write_text("raise SystemExit(0)\n", encoding="utf-8")

            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            args_file = root / "uv-args.txt"
            fake_uv = fake_bin / "uv"
            fake_uv.write_text(
                '#!/bin/bash\nprintf \'%s\\n\' "$@" > "$UV_ARGS_FILE"\n',
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)
            fake_gh = fake_bin / "gh"
            fake_gh.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
            fake_gh.chmod(0o755)

            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            environment["UV_ARGS_FILE"] = str(args_file)
            result = subprocess.run(
                ["bash", "scripts/verify_ops_foundation.sh", "--governance-live"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [
                    "run",
                    "--frozen",
                    "--package",
                    "syshin0116-dev-agent",
                    "python",
                    str(governance.resolve()),
                    "--live",
                ],
                args_file.read_text(encoding="utf-8").splitlines(),
            )

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

    def test_retired_openai_secrets_cannot_be_destroyed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            imports_path = root / "infra/gcp/imports.tf"
            source = imports_path.read_text(encoding="utf-8")
            self.assertEqual(2, source.count("    destroy = false"))
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
    def _run_helper(self, body: str) -> subprocess.CompletedProcess[str]:
        verifier = shlex.quote(str(REPO_ROOT / "scripts/verify_ops_foundation.sh"))
        return subprocess.run(
            [
                "bash",
                "-c",
                f"source {verifier} --help >/dev/null\n{body}",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    @staticmethod
    def _artifact_metadata() -> dict[str, object]:
        return {
            "name": (
                "projects/festive-ally-503605-v7/locations/us-east4/repositories/agent"
            ),
            "dockerConfig": {"immutableTags": False},
            "cleanupPolicyDryRun": False,
            "cleanupPolicies": {
                "delete-after-90-days": {
                    "id": "delete-after-90-days",
                    "action": "DELETE",
                    "condition": {
                        "tagState": "ANY",
                        "olderThan": "7776000s",
                    },
                },
                "keep-last-30": {
                    "id": "keep-last-30",
                    "action": "KEEP",
                    "mostRecentVersions": {"keepCount": 30},
                },
            },
        }

    def _run_artifact_metadata(
        self,
        metadata: dict[str, object],
    ) -> subprocess.CompletedProcess[str]:
        payload = shlex.quote(json.dumps(metadata, separators=(",", ":")))
        return self._run_helper(
            f"printf '%s\\n' {payload} | "
            "verify_artifact_repository_metadata "
            "agent delete-after-90-days 7776000s keep-last-30 30"
        )

    def test_artifact_metadata_accepts_exact_active_retention(self) -> None:
        result = self._run_artifact_metadata(self._artifact_metadata())

        self.assertEqual(0, result.returncode, result.stderr)

    def test_artifact_metadata_rejects_cleanup_and_mutability_drift(self) -> None:
        mutations: dict[str, Callable[[dict[str, object]], None]] = {
            "immutable_tags": lambda metadata: metadata["dockerConfig"].__setitem__(
                "immutableTags", True
            ),
            "dry_run": lambda metadata: metadata.__setitem__(
                "cleanupPolicyDryRun", True
            ),
            "delete_age": lambda metadata: metadata["cleanupPolicies"][
                "delete-after-90-days"
            ]["condition"].__setitem__("olderThan", "86400s"),
            "delete_scope": lambda metadata: metadata["cleanupPolicies"][
                "delete-after-90-days"
            ]["condition"].__setitem__("tagPrefixes", ["temporary-"]),
            "keep_count": lambda metadata: metadata["cleanupPolicies"]["keep-last-30"][
                "mostRecentVersions"
            ].__setitem__("keepCount", 3),
            "extra_policy": lambda metadata: metadata["cleanupPolicies"].__setitem__(
                "unreviewed", {"action": "KEEP"}
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                metadata = self._artifact_metadata()
                mutate(metadata)
                result = self._run_artifact_metadata(metadata)

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "active cleanup retention policy drifted",
                    result.stderr,
                )

    def test_guest_maintenance_schedule_requires_paused_oauth_contract(self) -> None:
        scheduler = {
            "name": (
                "projects/festive-ally-503605-v7/locations/us-east4/"
                "jobs/agent-guest-maintenance"
            ),
            "schedule": "*/15 * * * *",
            "timeZone": "Etc/UTC",
            "attemptDeadline": "60s",
            "state": "PAUSED",
            "retryConfig": {"retryCount": 0},
            "httpTarget": {
                "httpMethod": "POST",
                "uri": (
                    "https://run.googleapis.com/v2/projects/"
                    "festive-ally-503605-v7/locations/us-east4/"
                    "jobs/agent-maintenance:run"
                ),
                "body": "e30=",
                "headers": {
                    "Content-Type": "application/json",
                    "User-Agent": "Google-Cloud-Scheduler",
                },
                "oauthToken": {
                    "serviceAccountEmail": (
                        "agent-maintenance-scheduler@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    ),
                    "scope": "https://www.googleapis.com/auth/cloud-platform",
                },
            },
        }

        def run(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
            schedule_json = shlex.quote(json.dumps(payload, separators=(",", ":")))
            return self._run_helper(
                f"""
gcloud() {{
  case "$*" in
    "scheduler jobs describe agent-guest-maintenance --project $PROJECT_ID --location $REGION --format=json")
      printf '%s\\n' {schedule_json}
      ;;
    "iam service-accounts get-iam-policy $MAINTENANCE_SCHEDULER_SA --project $PROJECT_ID --format=json")
      printf '%s\\n' '{{"bindings":[]}}'
      ;;
    *)
      printf 'unexpected gcloud call: %s\\n' "$*" >&2
      return 99
      ;;
  esac
}}
verify_guest_maintenance_schedule
"""
            )

        accepted = run(scheduler)
        self.assertEqual(0, accepted.returncode, accepted.stderr)

        for field, value in (
            ("schedule", "*/5 * * * *"),
            ("attemptDeadline", "600s"),
            ("state", "ENABLED"),
        ):
            with self.subTest(field=field):
                mutated = json.loads(json.dumps(scheduler))
                mutated[field] = value
                rejected = run(mutated)
                self.assertNotEqual(0, rejected.returncode)
                self.assertIn("trigger drifted", rejected.stderr)

    def test_every_workload_account_is_forbidden_on_ancestor_policies(self) -> None:
        accounts = (
            "agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com",
            "agent-preview-runtime@festive-ally-503605-v7.iam.gserviceaccount.com",
            "agent-preview-deployer@festive-ally-503605-v7.iam.gserviceaccount.com",
            "agent-prod-deployer@festive-ally-503605-v7.iam.gserviceaccount.com",
            "agent-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com",
            "agent-preview-image-builder@festive-ally-503605-v7.iam.gserviceaccount.com",
            "agent-preview-migrator@festive-ally-503605-v7.iam.gserviceaccount.com",
            "agent-prod-migrator@festive-ally-503605-v7.iam.gserviceaccount.com",
            "agent-maintenance-scheduler@festive-ally-503605-v7.iam.gserviceaccount.com",
        )
        ancestors = json.dumps(
            [
                {"type": "project", "id": "festive-ally-503605-v7"},
                {"type": "folder", "id": "123"},
                {"type": "organization", "id": "456"},
            ],
            separators=(",", ":"),
        )
        for account in accounts:
            with self.subTest(account=account):
                policy = json.dumps(
                    {
                        "bindings": [
                            {
                                "role": "roles/run.admin",
                                "members": [f"serviceAccount:{account}"],
                            }
                        ]
                    },
                    separators=(",", ":"),
                )
                result = self._run_helper(
                    "assert_workload_accounts_have_no_direct_roles "
                    f"{shlex.quote(policy)} folders/123 {shlex.quote(ancestors)}"
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn(account, result.stderr)
                self.assertIn("folders/123", result.stderr)
        accepted = self._run_helper(
            "assert_workload_accounts_have_no_direct_roles "
            f"{shlex.quote(json.dumps({'bindings': []}))} organizations/456 "
            f"{shlex.quote(ancestors)}"
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)

    def test_encompassing_service_account_principal_sets_are_forbidden(self) -> None:
        ancestors = json.dumps(
            [
                {"type": "project", "id": "festive-ally-503605-v7"},
                {"type": "folder", "id": "123"},
                {"type": "organization", "id": "456"},
            ],
            separators=(",", ":"),
        )
        dangerous_members = (
            "principalSet://cloudresourcemanager.googleapis.com/"
            "projects/72919926064/type/ServiceAccount",
            "principalSet://cloudresourcemanager.googleapis.com/"
            "folders/123/type/ServiceAccount",
            "principalSet://cloudresourcemanager.googleapis.com/"
            "organizations/456/type/ServiceAccount",
        )
        for member in dangerous_members:
            with self.subTest(member=member):
                policy = json.dumps(
                    {
                        "bindings": [
                            {
                                "role": "roles/logging.viewer",
                                "members": [member],
                            }
                        ]
                    },
                    separators=(",", ":"),
                )
                result = self._run_helper(
                    "assert_workload_accounts_have_no_direct_roles "
                    f"{shlex.quote(policy)} folders/123 {shlex.quote(ancestors)}"
                )
                self.assertNotEqual(0, result.returncode)
                self.assertIn(member, result.stderr)
                self.assertIn("folders/123", result.stderr)

    def test_unrelated_service_account_principal_sets_remain_reviewable(self) -> None:
        ancestors = json.dumps(
            [
                {"type": "project", "id": "festive-ally-503605-v7"},
                {"type": "folder", "id": "123"},
                {"type": "organization", "id": "456"},
            ],
            separators=(",", ":"),
        )
        unrelated_members = (
            "principalSet://cloudresourcemanager.googleapis.com/"
            "projects/999/type/ServiceAccount",
            "principalSet://cloudresourcemanager.googleapis.com/"
            "folders/999/type/ServiceAccount",
            "principalSet://cloudresourcemanager.googleapis.com/"
            "organizations/999/type/ServiceAccount",
        )
        for member in unrelated_members:
            with self.subTest(member=member):
                policy = json.dumps(
                    {
                        "bindings": [
                            {
                                "role": "roles/logging.viewer",
                                "members": [member],
                            }
                        ]
                    },
                    separators=(",", ":"),
                )
                result = self._run_helper(
                    "assert_workload_accounts_have_no_direct_roles "
                    f"{shlex.quote(policy)} folders/123 {shlex.quote(ancestors)}"
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_workload_role_guard_is_wired_to_every_broad_policy_scope(self) -> None:
        verifier = (REPO_ROOT / "scripts/verify_ops_foundation.sh").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            2,
            verifier.count("assert_workload_accounts_have_no_direct_roles \\"),
        )
        self.assertIn(
            '"projects/${PROJECT_ID}" \\\n    "$ancestors_json"',
            verifier,
        )
        self.assertIn("assert_policy_binding_pairs_exactly \\", verifier)
        self.assertIn(
            '"${ancestor_type}s/${ancestor_id}" \\\n      "$ancestors_json"',
            verifier,
        )

    def test_project_key_scan_checks_accounts_outside_the_managed_nine(self) -> None:
        legacy_account = "legacy@festive-ally-503605-v7.iam.gserviceaccount.com"
        inventory = json.dumps(
            [
                {
                    "email": "agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
                },
                {
                    "email": (
                        "agent-preview-runtime@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-preview-deployer@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-prod-deployer@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-image-builder@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-preview-image-builder@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-preview-migrator@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-prod-migrator@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-maintenance-scheduler@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {"email": legacy_account},
            ],
            separators=(",", ":"),
        )
        result = self._run_helper(
            f"""
gcloud() {{
  case "$*" in
    "iam service-accounts list --project $PROJECT_ID --format=json")
      printf '%s\\n' {shlex.quote(inventory)}
      ;;
    iam\\ service-accounts\\ describe\\ *)
      return 0
      ;;
    *"iam service-accounts keys list"*"{legacy_account}"*)
      printf '%s\\n' projects/example/serviceAccounts/legacy/keys/user-key
      ;;
    iam\\ service-accounts\\ keys\\ list\\ *)
      return 0
      ;;
    *)
      printf 'unexpected gcloud call: %s\\n' "$*" >&2
      return 99
      ;;
  esac
}}
verify_project_has_no_user_managed_service_account_keys
"""
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn(f"user-managed key exists for {legacy_account}", result.stderr)

    def test_project_key_scan_requires_all_managed_accounts(self) -> None:
        incomplete_inventory = json.dumps(
            [{"email": "agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"}],
            separators=(",", ":"),
        )
        result = self._run_helper(
            f"""
gcloud() {{
  case "$*" in
    "iam service-accounts list --project $PROJECT_ID --format=json")
      printf '%s\\n' {shlex.quote(incomplete_inventory)}
      ;;
    *)
      return 99
      ;;
  esac
}}
verify_project_has_no_user_managed_service_account_keys
"""
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "managed workload service account is absent from project inventory",
            result.stderr,
        )

    def test_project_key_scan_accepts_complete_keyless_inventory(self) -> None:
        inventory = json.dumps(
            [
                {
                    "email": "agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com"
                },
                {
                    "email": (
                        "agent-preview-runtime@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-preview-deployer@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-prod-deployer@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-image-builder@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-preview-image-builder@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-preview-migrator@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-prod-migrator@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
                {
                    "email": (
                        "agent-maintenance-scheduler@festive-ally-503605-v7."
                        "iam.gserviceaccount.com"
                    )
                },
            ],
            separators=(",", ":"),
        )
        result = self._run_helper(
            f"""
gcloud() {{
  case "$*" in
    "iam service-accounts list --project $PROJECT_ID --format=json")
      printf '%s\\n' {shlex.quote(inventory)}
      ;;
    iam\\ service-accounts\\ describe\\ *|iam\\ service-accounts\\ keys\\ list\\ *)
      return 0
      ;;
    *)
      return 99
      ;;
  esac
}}
verify_project_has_no_user_managed_service_account_keys
"""
        )
        self.assertEqual(0, result.returncode, result.stderr)


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
            ["bash", "scripts/verify_ops_foundation.sh", "--state-bucket-metadata"],
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
