from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLICATION_DOCKERFILE = Path("eval/Dockerfile.publication")
PUBLICATION_DOCKERIGNORE = Path("eval/Dockerfile.publication.dockerignore")
AGENT_DOCKERFILE = Path("Dockerfile")
AGENT_DOCKERIGNORE = Path("Dockerfile.dockerignore")

PUBLICATION_ALLOWED_FILES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "agent/pyproject.toml",
        "agent/src/agent/retrieval/protocol.py",
        "agent/src/agent/retrieval/nested/probe.py",
        "agent/corpus-policy.toml",
        "agent/bm25-policy.toml",
        "eval/pyproject.toml",
        "eval/src/blogeval/runner.py",
        "eval/src/blogeval/nested/probe.py",
        "eval/querysets/probe.json",
        "scripts/build_index.py",
        "content/AI/probe.md",
        "content/Dev/nested/probe.md",
    }
)
AGENT_ALLOWED_FILES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "aegra.json",
        "agent/pyproject.toml",
        "agent/bm25-policy.toml",
        "agent/corpus-policy.toml",
        "agent/src/agent/api.py",
        "agent/src/agent/nested/retriever.py",
        "agent/skills/blog-retrieval/SKILL.md",
        "eval/pyproject.toml",
        "scripts/build_index.py",
        "content/AI/probe.md",
        "content/Dev/nested/probe.md",
    }
)
PUBLICATION_EXPECTED_FILES = PUBLICATION_ALLOWED_FILES | frozenset(
    {
        "agent/src/agent/api.py",
        "agent/src/agent/nested/retriever.py",
        "eval/src/blogeval/private.py",
        "content/AI/diagram.png",
        "content/Dev/nested/archive.json",
    }
)
AGENT_EXPECTED_FILES = AGENT_ALLOWED_FILES | frozenset(
    {
        "agent/src/agent/retrieval/protocol.py",
        "agent/src/agent/retrieval/nested/probe.py",
    }
)
UNRELATED_FILES = frozenset(
    {
        "agent/README.md",
        "agent/skills/blog-retrieval/SKILL.md",
        "agent/tests/conftest.py",
        "docs/rag-restack-plan.md",
        "eval/README.md",
        "eval/tests/conftest.py",
        "eval/src/blogeval/private.py",
        "content/AI/diagram.png",
        "content/Dev/nested/archive.json",
        "scripts/tests/test_unrelated.py",
        "scripts/verify_repository_governance.py",
        "web/package.json",
    }
)
SENSITIVE_AND_ARTIFACT_FILES = frozenset(
    {
        ".env",
        "agent/.env",
        "agent/src/.npmrc",
        "agent/src/.aws/credentials",
        "agent/src/.config/gcloud/application_default_credentials.json",
        "agent/src/.docker/config.json",
        "agent/src/.ssh/id_ed25519",
        "agent/src/generated/artifacts/result.json",
        "agent/src/private/credentials-production.json",
        "agent/src/private/server.key",
        "agent/src/private/server.pem",
        "agent/src/private/service-account-eval.json",
        "agent/src/private/terraform.tfstate.backup",
        "agent/src/private/production.tfvars",
        "agent/src/agent/__pycache__/protocol.cpython-312.pyc",
        "content/node_modules/package/index.js",
        "eval/src/coverage/lcov.info",
    }
)


class DockerBuildContextContractTests(unittest.TestCase):
    def setUp(self) -> None:
        if shutil.which("docker") is None:
            if os.environ.get("CI"):
                self.fail("Docker is required for the CI build-context contract")
            self.skipTest("Docker is not installed")

    def _write_candidates(self, context: Path) -> None:
        for relative in (
            *PUBLICATION_ALLOWED_FILES,
            *AGENT_ALLOWED_FILES,
            *UNRELATED_FILES,
            *SENSITIVE_AND_ARTIFACT_FILES,
        ):
            path = context / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"docker-context-probe:{relative}\n", encoding="utf-8")

    def _buildkit_inventory(self, context: Path, dockerfile: Path) -> frozenset[str]:
        output = context.parent / f"{context.name}-output"
        result = subprocess.run(
            [
                "docker",
                "buildx",
                "build",
                "--file",
                str(dockerfile),
                "--output",
                f"type=local,dest={output}",
                "--provenance=false",
                ".",
            ],
            cwd=context,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            0,
            result.returncode,
            f"BuildKit context probe failed:\n{result.stdout}\n{result.stderr}",
        )
        copied = output / "context"
        self.assertTrue(copied.is_dir(), result.stdout + result.stderr)
        return frozenset(
            path.relative_to(copied).as_posix()
            for path in copied.rglob("*")
            if path.is_file()
        )

    def test_publication_specific_ignore_has_exact_real_buildkit_inventory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = root / "publication-context"
            context.mkdir()
            self._write_candidates(context)

            root_ignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
            (context / ".dockerignore").write_text(
                root_ignore + "\npyproject.toml\n",
                encoding="utf-8",
            )
            dockerfile = context / PUBLICATION_DOCKERFILE
            dockerfile.parent.mkdir(parents=True, exist_ok=True)
            dockerfile.write_text("FROM scratch\nCOPY . /context\n", encoding="utf-8")
            shutil.copy2(
                REPO_ROOT / PUBLICATION_DOCKERIGNORE,
                context / PUBLICATION_DOCKERIGNORE,
            )

            inventory = self._buildkit_inventory(context, dockerfile)

        self.assertEqual(PUBLICATION_EXPECTED_FILES, inventory)

    def test_root_ignore_excludes_sensitive_and_artifact_real_buildkit_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = root / "root-context"
            context.mkdir()
            self._write_candidates(context)
            shutil.copy2(REPO_ROOT / ".dockerignore", context / ".dockerignore")
            dockerfile = context / "Dockerfile"
            dockerfile.write_text("FROM scratch\nCOPY . /context\n", encoding="utf-8")

            inventory = self._buildkit_inventory(context, dockerfile)

        self.assertEqual(
            PUBLICATION_ALLOWED_FILES | AGENT_ALLOWED_FILES | UNRELATED_FILES,
            inventory,
        )

    def test_agent_specific_ignore_has_exact_real_buildkit_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = root / "agent-context"
            context.mkdir()
            self._write_candidates(context)

            shutil.copy2(REPO_ROOT / ".dockerignore", context / ".dockerignore")
            dockerfile = context / AGENT_DOCKERFILE
            dockerfile.write_text("FROM scratch\nCOPY . /context\n", encoding="utf-8")
            shutil.copy2(
                REPO_ROOT / AGENT_DOCKERIGNORE,
                context / AGENT_DOCKERIGNORE,
            )

            inventory = self._buildkit_inventory(context, dockerfile)

        self.assertEqual(AGENT_EXPECTED_FILES, inventory)


if __name__ == "__main__":
    unittest.main()
