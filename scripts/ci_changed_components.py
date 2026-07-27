#!/usr/bin/env python3
"""Classify changed paths for always-reported Application CI jobs."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

COMPONENTS = ("web", "agent", "eval", "infra")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ALL_ZERO_SHA = "0" * 40
ROOT_AGENT_PATHS = frozenset(
    {
        "Dockerfile",
        "aegra.json",
        "pyproject.toml",
        "uv.lock",
    }
)
PUBLICATION_SEMANTICS_WEB_PATHS = frozenset(
    {
        "web/bun.lock",
        "web/package.json",
        "web/scripts/prebuild.ts",
    }
)
OPS_FOUNDATION_PATHS = frozenset(
    {
        "scripts/ops_foundation_contract.py",
        "scripts/tests/test_ops_foundation_contract.py",
        "scripts/tests/test_verify_ops_foundation.py",
        "scripts/verify_ops_foundation.sh",
    }
)
CHANGE_DETECTION_PATHS = frozenset(
    {
        "scripts/ci_changed_components.py",
        "scripts/tests/test_ci_changed_components.py",
    }
)


class ChangeDetectionError(RuntimeError):
    """The requested git comparison cannot be classified safely."""


def classify_paths(paths: Iterable[str]) -> dict[str, bool]:
    """Map repository-relative changed paths to affected CI components."""
    affected = dict.fromkeys(COMPONENTS, False)
    for raw_path in paths:
        path = raw_path.removeprefix("./")
        if not path:
            continue
        if path.startswith(".github/workflows/") or path in CHANGE_DETECTION_PATHS:
            return dict.fromkeys(COMPONENTS, True)
        if path == ".gitignore":
            affected["infra"] = True
        if path.startswith("protocol/") or path.startswith("content/"):
            affected["web"] = True
            affected["agent"] = True
            affected["eval"] = True
            continue
        if path.startswith("web/"):
            affected["web"] = True
        if path in PUBLICATION_SEMANTICS_WEB_PATHS:
            affected["agent"] = True
            affected["eval"] = True
        if (
            path.startswith("agent/")
            or (path.startswith("scripts/") and path not in OPS_FOUNDATION_PATHS)
            or path in ROOT_AGENT_PATHS
        ):
            affected["agent"] = True
            affected["eval"] = True
        if path.startswith("eval/"):
            affected["eval"] = True
        if path.startswith("infra/") or path in OPS_FOUNDATION_PATHS:
            affected["infra"] = True
    return affected


def changed_paths(
    base: str,
    head: str,
    *,
    cwd: Path | None = None,
) -> list[str]:
    """Return NUL-safe names changed between two exact commits."""
    for label, value in (("base", base), ("head", head)):
        if SHA_PATTERN.fullmatch(value) is None:
            raise ChangeDetectionError(
                f"{label} SHA must be a full lowercase commit SHA, got {value!r}"
            )
    try:
        result = subprocess.run(
            ["git", "diff", "--no-renames", "--name-only", "-z", base, head],
            check=True,
            capture_output=True,
            cwd=cwd,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace").strip()
        raise ChangeDetectionError(
            f"git diff failed for {base}..{head}: {detail}"
        ) from exc
    return [
        entry.decode(errors="surrogateescape")
        for entry in result.stdout.split(b"\0")
        if entry
    ]


def detect(event: str, base: str, head: str) -> dict[str, bool]:
    """Fail open to all work only when an event has no meaningful base."""
    if event == "workflow_dispatch" or not base or base == ALL_ZERO_SHA:
        return dict.fromkeys(COMPONENTS, True)
    return classify_paths(changed_paths(base, head))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        affected = detect(args.event, args.base, args.head)
        with args.output.open("a", encoding="utf-8") as output:
            for component in COMPONENTS:
                value = str(affected[component]).lower()
                output.write(f"{component}={value}\n")
                print(f"{component}={value}")
    except (ChangeDetectionError, OSError) as exc:
        print(f"CI change detection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
