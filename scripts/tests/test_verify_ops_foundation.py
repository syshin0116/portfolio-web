from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_FILES = (
    "infra/gcp/.terraform-version",
    "infra/gcp/backend.tf",
    "infra/gcp/iam.tf",
    "infra/gcp/imports.tf",
    "infra/gcp/main.tf",
    "infra/gcp/outputs.tf",
    "infra/gcp/state.tf",
    "infra/gcp/tests/foundation.tftest.hcl",
    "infra/gcp/variables.tf",
    "infra/gcp/versions.tf",
)
PREVIEW_CONDITION_LINE = (
    "  preview_wif_attribute_condition    = "
    "\"assertion.repository_id == '${var.github_repository_id}' && "
    "assertion.repository_owner_id == '${var.github_owner_id}' && "
    "assertion.event_name == 'pull_request' && "
    "assertion.environment == '${var.github_preview_environment}'\"\n"
)
PRODUCTION_CONDITION_LINE = (
    "  production_wif_attribute_condition = "
    "\"assertion.repository_id == '${var.github_repository_id}' && "
    "assertion.repository_owner_id == '${var.github_owner_id}' && "
    "assertion.event_name == 'push' && "
    "assertion.ref == 'refs/heads/main' && "
    "assertion.environment == '${var.github_production_environment}'\"\n"
)


class StaticVerifierMutationTests(unittest.TestCase):
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
        )
        for relative_path in candidates:
            with self.subTest(relative_path=relative_path):
                with tempfile.TemporaryDirectory() as directory:
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
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as directory:
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
            with self.subTest(component=component):
                with tempfile.TemporaryDirectory() as directory:
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
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as directory:
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
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as directory:
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
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as directory:
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
            "discovery must exactly equal one reviewed file/run",
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

    def test_every_previously_unchecked_resource_body_fails_closed(self) -> None:
        mutations = {
            "project_service": (
                "infra/gcp/main.tf",
                "  disable_on_destroy = false",
                "  disable_on_destroy = true",
            ),
            "artifact_registry": (
                "infra/gcp/main.tf",
                "    immutable_tags = true",
                "    immutable_tags = false",
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
                    "    immutable_tags = true", "    immutable_tags = false"
                )
                + "\n# immutable_tags = true\n",
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
                    "--no-project",
                    "--with",
                    "pyyaml==6.0.3",
                    "python",
                    str(governance.resolve()),
                    "--live",
                ],
                args_file.read_text(encoding="utf-8").splitlines(),
            )

    def test_preview_condition_mutations_fail_closed(self) -> None:
        mutations: dict[str, Callable[[str], str]] = {
            "or_true": lambda line: line.replace(
                "'${var.github_preview_environment}'\"",
                "'${var.github_preview_environment}' || true\"",
            ),
            "dropped_event_clause": lambda line: line.replace(
                "assertion.event_name == 'pull_request' && ",
                "",
            ),
            "changed_grouping": lambda line: line.replace(
                "assertion.repository_id == '${var.github_repository_id}' && "
                "assertion.repository_owner_id == '${var.github_owner_id}'",
                "(assertion.repository_id == '${var.github_repository_id}' && "
                "assertion.repository_owner_id == '${var.github_owner_id}')",
            ),
        }

        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self._fixture(directory)
                self._mutate_condition(root, PREVIEW_CONDITION_LINE, mutation)
                result = self._run(root)

                self.assertNotEqual(0, result.returncode)
                self.assertIn(
                    "Terraform locals configuration is not exact",
                    result.stderr,
                )

    def test_production_condition_mutations_fail_closed(self) -> None:
        mutations: dict[str, Callable[[str], str]] = {
            "or_true": lambda line: line.replace(
                "'${var.github_production_environment}'\"",
                "'${var.github_production_environment}' || true\"",
            ),
            "dropped_event_clause": lambda line: line.replace(
                "assertion.event_name == 'push' && ",
                "",
            ),
            "changed_grouping": lambda line: line.replace(
                "assertion.event_name == 'push' && assertion.ref == 'refs/heads/main'",
                "(assertion.event_name == 'push' && "
                "assertion.ref == 'refs/heads/main')",
            ),
        }

        for name, mutation in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = self._fixture(directory)
                self._mutate_condition(root, PRODUCTION_CONDITION_LINE, mutation)
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
            expected = "  attribute_condition = local.preview_wif_attribute_condition\n"
            self.assertEqual(1, original.count(expected))
            main_path.write_text(
                original.replace(
                    expected,
                    "  attribute_condition = "
                    '"(${local.preview_wif_attribute_condition}) || true"\n',
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
            self.assertIn("top-level block inventory is not exact", result.stderr)

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


class StateBucketMetadataTests(unittest.TestCase):
    @staticmethod
    def _metadata(location: str) -> dict[str, object]:
        return {
            "location": location,
            "public_access_prevention": "enforced",
            "uniform_bucket_level_access": True,
            "versioning_enabled": True,
            "soft_delete_policy": {
                "retentionDurationSeconds": "2592000",
            },
        }

    def _run(self, location: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "scripts/verify_ops_foundation.sh", "--state-bucket-metadata"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            input=json.dumps(self._metadata(location)),
        )

    def test_state_bucket_metadata_accepts_exact_us_east4_location(self) -> None:
        result = self._run("us-east4")

        self.assertEqual(0, result.returncode, result.stderr)

    def test_state_bucket_metadata_rejects_asia_location(self) -> None:
        result = self._run("ASIA")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("location must be exactly us-east4", result.stderr)


if __name__ == "__main__":
    unittest.main()
