from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ci_changed_components as changes  # noqa: E402


class PathClassificationTests(unittest.TestCase):
    def test_component_paths_are_selective(self) -> None:
        self.assertEqual(
            {"web": True, "agent": False, "eval": False, "infra": False},
            changes.classify_paths(["web/app/page.tsx"]),
        )
        self.assertEqual(
            {"web": False, "agent": True, "eval": True, "infra": False},
            changes.classify_paths(["agent/src/agent/graph.py"]),
        )
        self.assertEqual(
            {"web": False, "agent": False, "eval": True, "infra": False},
            changes.classify_paths(["eval/src/blogeval/runner.py"]),
        )
        self.assertEqual(
            {"web": False, "agent": False, "eval": False, "infra": True},
            changes.classify_paths(["infra/gcp/main.tf"]),
        )

    def test_application_ci_workflow_runs_every_component(self) -> None:
        self.assertEqual(
            {"web": True, "agent": True, "eval": True, "infra": True},
            changes.classify_paths([".github/workflows/ci.yml"]),
        )

    def test_other_workflows_run_infrastructure_checks(self) -> None:
        for path in (
            ".github/workflows/protocol-compat.yml",
            ".github/workflows/preview-agent.yml",
            ".github/workflows/deploy-agent.yml",
            ".github/workflows/smoke-production.yml",
            ".github/workflows/dependency-audit.yml",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    {"web": False, "agent": False, "eval": False, "infra": True},
                    changes.classify_paths([path]),
                )

    def test_corpus_and_protocol_contracts_do_not_run_infra(self) -> None:
        for path in (
            "content/AI/example.md",
            "protocol/fixtures/content-tool-run.json",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    {"web": True, "agent": True, "eval": True, "infra": False},
                    changes.classify_paths([path]),
                )

    def test_multiple_paths_union_component_work(self) -> None:
        self.assertEqual(
            {"web": True, "agent": True, "eval": True, "infra": True},
            changes.classify_paths(["content/AI/example.md", "infra/gcp/main.tf"]),
        )

    def test_nuartz_publication_semantics_paths_run_every_component(self) -> None:
        for path in (
            "web/package.json",
            "web/bun.lock",
            "web/scripts/prebuild.ts",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    {"web": True, "agent": True, "eval": True, "infra": False},
                    changes.classify_paths([path]),
                )

    def test_root_runtime_and_scripts_run_agent_and_eval(self) -> None:
        for path in ("aegra.json", "Dockerfile", "scripts/build_index.py"):
            with self.subTest(path=path):
                self.assertEqual(
                    {"web": False, "agent": True, "eval": True, "infra": False},
                    changes.classify_paths([path]),
                )

    def test_ops_verifier_runs_only_infrastructure_ci(self) -> None:
        for path in (
            "scripts/verify_ops_foundation.sh",
            "scripts/tests/test_verify_ops_foundation.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    {"web": False, "agent": False, "eval": False, "infra": True},
                    changes.classify_paths([path]),
                )

    def test_unrelated_docs_do_not_rebuild_components(self) -> None:
        self.assertEqual(
            {"web": False, "agent": False, "eval": False, "infra": False},
            changes.classify_paths(["docs/plans/rag-restack.md"]),
        )


class DetectionTests(unittest.TestCase):
    def test_manual_and_missing_base_runs_every_component(self) -> None:
        expected = {"web": True, "agent": True, "eval": True, "infra": True}
        self.assertEqual(expected, changes.detect("workflow_dispatch", "", "a" * 40))
        self.assertEqual(expected, changes.detect("push", "0" * 40, "a" * 40))

    def test_exact_base_and_head_are_forwarded_to_git_diff(self) -> None:
        with patch.object(
            changes,
            "changed_paths",
            return_value=["web/package.json"],
        ) as changed_paths:
            result = changes.detect("pull_request", "a" * 40, "b" * 40)
        changed_paths.assert_called_once_with("a" * 40, "b" * 40)
        self.assertEqual(
            {"web": True, "agent": True, "eval": True, "infra": False},
            result,
        )

    def test_bad_sha_fails_closed(self) -> None:
        with self.assertRaisesRegex(changes.ChangeDetectionError, "full lowercase"):
            changes.changed_paths("main", "b" * 40)

    def test_cross_component_rename_reports_source_and_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)

            def git(*args: str) -> str:
                result = subprocess.run(
                    ["git", *args],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return result.stdout.strip()

            git("init", "--quiet")
            git("config", "user.name", "CI Test")
            git("config", "user.email", "ci-test@example.invalid")
            git("config", "diff.renames", "true")
            source = repository / "agent/retriever.py"
            source.parent.mkdir()
            source.write_text("METHOD = 'bm25'\n", encoding="utf-8")
            git("add", "agent/retriever.py")
            git("commit", "--quiet", "-m", "add agent file")
            base = git("rev-parse", "HEAD")

            destination = repository / "web/retriever.py"
            destination.parent.mkdir()
            source.rename(destination)
            git("add", "--all")
            git("commit", "--quiet", "-m", "move agent file to web")
            head = git("rev-parse", "HEAD")

            rename_detected_paths = git(
                "diff",
                "--name-only",
                base,
                head,
            ).splitlines()
            paths = changes.changed_paths(base, head, cwd=repository)

        self.assertEqual(["web/retriever.py"], rename_detected_paths)
        self.assertEqual(
            {"agent/retriever.py", "web/retriever.py"},
            set(paths),
        )
        self.assertEqual(
            {"web": True, "agent": True, "eval": True, "infra": False},
            changes.classify_paths(paths),
        )


if __name__ == "__main__":
    unittest.main()
