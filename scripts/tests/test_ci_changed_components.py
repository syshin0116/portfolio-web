from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ci_changed_components as changes  # noqa: E402


class PathClassificationTests(unittest.TestCase):
    def test_component_paths_are_selective(self) -> None:
        self.assertEqual(
            {"web": True, "agent": False, "eval": False},
            changes.classify_paths(["web/app/page.tsx"]),
        )
        self.assertEqual(
            {"web": False, "agent": True, "eval": True},
            changes.classify_paths(["agent/src/agent/graph.py"]),
        )
        self.assertEqual(
            {"web": False, "agent": False, "eval": True},
            changes.classify_paths(["eval/src/blogeval/runner.py"]),
        )

    def test_shared_contract_paths_run_every_component(self) -> None:
        for path in (
            ".github/workflows/ci.yml",
            "content/AI/example.md",
            "protocol/fixtures/content-tool-run.json",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    {"web": True, "agent": True, "eval": True},
                    changes.classify_paths([path]),
                )

    def test_root_runtime_and_scripts_run_agent_and_eval(self) -> None:
        for path in ("aegra.json", "Dockerfile", "scripts/build_index.py"):
            with self.subTest(path=path):
                self.assertEqual(
                    {"web": False, "agent": True, "eval": True},
                    changes.classify_paths([path]),
                )

    def test_unrelated_docs_do_not_rebuild_components(self) -> None:
        self.assertEqual(
            {"web": False, "agent": False, "eval": False},
            changes.classify_paths(["docs/plans/rag-restack.md"]),
        )


class DetectionTests(unittest.TestCase):
    def test_manual_and_missing_base_runs_every_component(self) -> None:
        expected = {"web": True, "agent": True, "eval": True}
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
            {"web": True, "agent": False, "eval": False},
            result,
        )

    def test_bad_sha_fails_closed(self) -> None:
        with self.assertRaisesRegex(changes.ChangeDetectionError, "full lowercase"):
            changes.changed_paths("main", "b" * 40)


if __name__ == "__main__":
    unittest.main()
