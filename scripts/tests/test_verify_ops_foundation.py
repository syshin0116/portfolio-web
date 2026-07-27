from __future__ import annotations

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
                    "preview WIF CEL condition must exactly match",
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
                    "production WIF CEL condition must exactly match",
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
            "critical resource configuration is not exact",
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
        self.assertIn("tracked Terraform inventory mismatch", result.stderr)

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
        self.assertIn("tracked Terraform inventory mismatch", result.stderr)

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
            "critical resource configuration is not exact",
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
            "variable github_repository_id validation must exactly match",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
