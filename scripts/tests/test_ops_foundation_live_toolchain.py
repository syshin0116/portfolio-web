from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ops_foundation_live_toolchain import (
    ToolchainError,
    resolve_path_executable,
    trusted_home,
    validate_trusted_executable,
)


class LiveToolchainTests(unittest.TestCase):
    @staticmethod
    def _executable(directory: Path, name: str = "reviewed-tool") -> Path:
        executable = directory / name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o700)
        return executable

    def test_secure_current_user_executable_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            executable = self._executable(Path(directory))

            resolved = validate_trusted_executable(executable, "test tool")

        self.assertEqual(executable.resolve(), resolved)

    def test_group_writable_executable_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            executable = self._executable(Path(directory))
            executable.chmod(0o720)

            with self.assertRaisesRegex(ToolchainError, "group/other writable"):
                validate_trusted_executable(executable, "test tool")

    def test_group_writable_ancestry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            insecure = Path(directory) / "insecure"
            insecure.mkdir(mode=0o700)
            executable = self._executable(insecure)
            insecure.chmod(0o770)

            with self.assertRaisesRegex(ToolchainError, "ancestry"):
                validate_trusted_executable(executable, "test tool")

    def test_relative_or_empty_path_entries_fail_before_lookup(self) -> None:
        for path_value in ("relative:/usr/bin", ":/usr/bin"):
            with (
                self.subTest(path=path_value),
                patch.dict(os.environ, {"PATH": path_value}, clear=True),
            ):
                with self.assertRaisesRegex(ToolchainError, "absolute non-empty"):
                    resolve_path_executable("python3")

    def test_path_resolution_uses_validated_absolute_target(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            root = Path(directory)
            executable = self._executable(root, "bounded-tool")
            with patch.dict(os.environ, {"PATH": str(root)}, clear=True):
                resolved = resolve_path_executable("bounded-tool")

        self.assertEqual(executable.resolve(), resolved)

    def test_home_comes_from_passwd_not_caller_environment(self) -> None:
        with patch.dict(os.environ, {"HOME": "/tmp/forged-home"}, clear=False):
            resolved = trusted_home()

        self.assertNotEqual(Path("/tmp/forged-home"), resolved)
        self.assertTrue(resolved.is_absolute())


if __name__ == "__main__":
    unittest.main()
