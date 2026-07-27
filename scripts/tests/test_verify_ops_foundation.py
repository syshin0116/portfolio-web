from __future__ import annotations

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
    "infra/gcp/main.tf",
    "infra/gcp/state.tf",
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
            "preview provider must use only the reviewed CEL condition",
            result.stderr,
        )

    def test_unreviewed_secret_accessor_resource_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._fixture(directory)
            iam_path = root / "infra/gcp/iam.tf"
            iam_path.write_text(
                iam_path.read_text(encoding="utf-8")
                + """

resource "google_secret_manager_secret_iam_member" "unreviewed_accessor" {
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
            "Terraform IAM resources must exactly match",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
