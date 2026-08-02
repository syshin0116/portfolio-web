#!/usr/bin/env python3
"""Resolve the trusted local executables used by foundation live verification.

This protects child-process construction from ambient PATH/HOME drift.  It assumes the
current user's non-group/other-writable files are trusted local code; it does not claim
resistance to a malicious same-user workstation or loader activity before bash starts.
"""

from __future__ import annotations

import argparse
import os
import pwd
import re
import stat
import sys
from pathlib import Path
from typing import List, Optional, Union


class ToolchainError(RuntimeError):
    """The selected local executable or home directory is not trustworthy."""


def _fail(message: str) -> None:
    raise ToolchainError(message)


def _validate_secure_ancestry(path: Path, label: str) -> None:
    allowed_owners = {0, os.getuid()}
    current = path
    while True:
        try:
            metadata = current.stat()
        except OSError as exc:
            raise ToolchainError(f"cannot stat {label} ancestry") from exc
        if metadata.st_uid not in allowed_owners:
            _fail(f"{label} ancestry has an untrusted owner")
        if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            _fail(f"{label} ancestry is group/other writable")
        if current.parent == current:
            return
        current = current.parent


def validate_trusted_executable(value: Union[str, Path], label: str) -> Path:
    """Resolve one absolute executable and validate its file and path boundary."""
    candidate = Path(value)
    if not candidate.is_absolute():
        _fail(f"{label} path must be absolute")
    if "\n" in str(candidate) or "\r" in str(candidate):
        _fail(f"{label} path contains a line break")
    _validate_secure_ancestry(candidate.parent, f"{label} selected path")
    try:
        resolved = candidate.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise ToolchainError(f"cannot resolve {label}") from exc
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        _fail(f"{label} must resolve to an executable regular file")
    if metadata.st_uid not in {0, os.getuid()}:
        _fail(f"{label} executable has an untrusted owner")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        _fail(f"{label} executable is group/other writable")
    _validate_secure_ancestry(resolved.parent, f"{label} resolved path")
    return resolved


def resolve_path_executable(name: str) -> Path:
    """Resolve the first PATH match after excluding relative/current-directory entries."""
    if re.fullmatch(r"[A-Za-z0-9_.+-]+", name) is None:
        _fail("tool name is invalid")
    path_value = os.environ.get("PATH")
    if not path_value:
        _fail("PATH is required to select the local live toolchain")
    entries = path_value.split(os.pathsep)
    if any(not entry or not Path(entry).is_absolute() for entry in entries):
        _fail("PATH must contain absolute non-empty entries only")
    for entry in entries:
        candidate = Path(entry) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return validate_trusted_executable(candidate, name)
    _fail(f"trusted executable is missing: {name}")


def trusted_home() -> Path:
    """Return the passwd-derived home after validating its local trust boundary."""
    try:
        home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
        metadata = home.stat()
    except (KeyError, OSError) as exc:
        raise ToolchainError("cannot resolve the passwd-derived home") from exc
    if not home.is_absolute() or not stat.S_ISDIR(metadata.st_mode):
        _fail("passwd-derived home is not an absolute directory")
    if metadata.st_uid != os.getuid():
        _fail("passwd-derived home is not owned by the current user")
    _validate_secure_ancestry(home, "passwd-derived home")
    return home


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    resolve = subparsers.add_parser("resolve")
    resolve.add_argument("tool")
    validate = subparsers.add_parser("validate")
    validate.add_argument("path", type=Path)
    subparsers.add_parser("home")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "resolve":
            result = resolve_path_executable(args.tool)
        elif args.command == "validate":
            result = validate_trusted_executable(args.path, "explicit tool")
        else:
            result = trusted_home()
    except ToolchainError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
