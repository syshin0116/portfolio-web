#!/usr/bin/env python3
"""Verify locked protocol artifacts against their immutable upstream commits."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO_ROOT / "protocol/agent-protocol.lock.json"
ALLOWED_REPOSITORIES = frozenset(
    {
        "https://github.com/ibbybuilds/aegra",
        "https://github.com/langchain-ai/agent-protocol",
    }
)
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


class UpstreamVerificationError(RuntimeError):
    """A locked upstream artifact is unavailable or differs from its digest."""


def _raw_url(repository: str, commit: str, upstream_path: str) -> str:
    if repository not in ALLOWED_REPOSITORIES:
        raise UpstreamVerificationError(f"repository is not allowed: {repository!r}")
    if COMMIT_PATTERN.fullmatch(commit) is None:
        raise UpstreamVerificationError(
            f"commit is not a full lowercase SHA: {commit!r}"
        )

    parsed = urlparse(repository)
    path_parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or len(path_parts) != 2
    ):
        raise UpstreamVerificationError(
            f"invalid GitHub repository URL: {repository!r}"
        )

    artifact_path = PurePosixPath(upstream_path)
    if artifact_path.is_absolute() or ".." in artifact_path.parts:
        raise UpstreamVerificationError(f"unsafe upstream path: {upstream_path!r}")
    encoded_path = quote(artifact_path.as_posix(), safe="/")
    return (
        "https://raw.githubusercontent.com/"
        f"{path_parts[0]}/{path_parts[1]}/{commit}/{encoded_path}"
    )


def _fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "syshin0116.dev-protocol-ci/1"})
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            payload = response.read(MAX_ARTIFACT_BYTES + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise UpstreamVerificationError(f"cannot fetch {url}: {exc}") from exc
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise UpstreamVerificationError(
            f"upstream artifact exceeds {MAX_ARTIFACT_BYTES} bytes: {url}"
        )
    return payload


def _artifacts(section: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    artifacts = section.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise UpstreamVerificationError("lock section has no artifacts")
    for name, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            raise UpstreamVerificationError(f"artifact {name!r} is not an object")
        yield name, artifact


def _vendored_path(raw_path: str) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise UpstreamVerificationError(f"unsafe vendored path: {raw_path!r}")
    resolved = (REPO_ROOT / relative).resolve()
    if not resolved.is_relative_to(REPO_ROOT.resolve()):
        raise UpstreamVerificationError(f"vendored path escapes the repo: {raw_path!r}")
    return resolved


def verify_upstream(
    lock: dict[str, Any],
    *,
    fetch: Callable[[str], bytes] = _fetch,
) -> list[str]:
    """Return verified artifact labels or raise on the first mismatch."""
    verified: list[str] = []
    for section_name in ("protocol", "aegra"):
        section = lock.get(section_name)
        if not isinstance(section, dict):
            raise UpstreamVerificationError(f"lock is missing {section_name!r}")
        repository = section.get("repository")
        commit = section.get("commit")
        if not isinstance(repository, str) or not isinstance(commit, str):
            raise UpstreamVerificationError(
                f"{section_name} repository and commit must be strings"
            )

        for artifact_name, artifact in _artifacts(section):
            upstream_path = artifact.get("upstreamPath")
            expected_digest = artifact.get("sha256")
            if not isinstance(upstream_path, str) or not upstream_path:
                raise UpstreamVerificationError(
                    f"{section_name}.{artifact_name} has no upstreamPath"
                )
            if (
                not isinstance(expected_digest, str)
                or SHA256_PATTERN.fullmatch(expected_digest) is None
            ):
                raise UpstreamVerificationError(
                    f"{section_name}.{artifact_name} has an invalid sha256"
                )

            upstream = fetch(_raw_url(repository, commit, upstream_path))
            actual_digest = hashlib.sha256(upstream).hexdigest()
            if actual_digest != expected_digest:
                raise UpstreamVerificationError(
                    f"{section_name}.{artifact_name} digest differs: "
                    f"expected {expected_digest}, got {actual_digest}"
                )

            vendored = artifact.get("vendoredPath")
            if vendored is not None:
                if not isinstance(vendored, str) or not vendored:
                    raise UpstreamVerificationError(
                        f"{section_name}.{artifact_name} has an invalid vendoredPath"
                    )
                path = _vendored_path(vendored)
                try:
                    local = path.read_bytes()
                except OSError as exc:
                    raise UpstreamVerificationError(
                        f"cannot read vendored artifact {vendored}: {exc}"
                    ) from exc
                if local != upstream:
                    raise UpstreamVerificationError(
                        f"{section_name}.{artifact_name} vendored bytes differ "
                        f"from {commit}:{upstream_path}"
                    )
            verified.append(f"{section_name}.{artifact_name}")
    return verified


def main() -> int:
    try:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        if not isinstance(lock, dict):
            raise UpstreamVerificationError("protocol lock must be an object")
        verified = verify_upstream(lock)
    except (
        OSError,
        json.JSONDecodeError,
        UpstreamVerificationError,
    ) as exc:
        print(f"upstream protocol verification failed: {exc}", file=sys.stderr)
        return 1

    print(f"verified {len(verified)} locked upstream artifacts")
    for label in verified:
        print(f"- {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
