#!/usr/bin/env python3
"""Verify locked protocol artifacts against their immutable upstream commits."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO_ROOT / "protocol/agent-protocol.lock.json"
LOCK_V1_REPOSITORIES = {
    "protocol": "https://github.com/langchain-ai/agent-protocol",
    "aegra": "https://github.com/ibbybuilds/aegra",
}
LOCK_V1_CODEGEN: dict[str, Any] = {
    "nodeVersion": "24.14.0",
    "corepackVersion": "0.34.6",
    "pythonVersion": "3.12",
    "packageManager": "pnpm@10.33.0",
    "packages": {
        "cddl": "0.20.1",
        "cddl2py": "0.2.2",
        "cddl2ts": "0.9.1",
    },
}
LOCK_V1_ARTIFACTS: dict[
    str,
    dict[str, tuple[str, str | None, dict[str, str]]],
] = {
    "protocol": {
        "openapi": ("openapi.json", None, {}),
        "cddl": ("streaming/protocol.cddl", None, {}),
        "packageManifest": ("streaming/package.json", None, {}),
        "pnpmLock": ("streaming/pnpm-lock.yaml", None, {}),
        "pnpmWorkspace": ("streaming/pnpm-workspace.yaml", None, {}),
        "pythonFixup": ("streaming/scripts/fixup.py", None, {}),
        "pythonBinding": (
            "streaming/py/langchain_protocol/protocol.py",
            "protocol/generated/python/protocol.py",
            {"package": "langchain-protocol==0.0.18"},
        ),
        "typescriptBinding": (
            "streaming/js/protocol.ts",
            "protocol/generated/typescript/protocol.ts",
            {"package": "@langchain/protocol@0.0.18"},
        ),
    },
    "aegra": {
        "openapi": ("docs/openapi.json", None, {}),
        "route": (
            "libs/aegra-api/src/aegra_api/api/event_streaming.py",
            None,
            {},
        ),
        "wireBuilders": (
            "libs/aegra-api/src/aegra_api/services/event_streaming/protocol.py",
            None,
            {},
        ),
        "commands": (
            "libs/aegra-api/src/aegra_api/services/event_streaming/commands.py",
            None,
            {},
        ),
    },
}
ALLOWED_REPOSITORIES = frozenset(LOCK_V1_REPOSITORIES.values())
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


class UpstreamVerificationError(RuntimeError):
    """A locked upstream artifact is unavailable or differs from its digest."""


@dataclass(frozen=True)
class LockedArtifact:
    """One fully schema-validated immutable upstream artifact."""

    section: str
    name: str
    repository: str
    commit: str
    upstream_path: str
    sha256: str
    vendored_path: str | None

    @property
    def label(self) -> str:
        return f"{self.section}.{self.name}"


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
        with urlopen(request, timeout=30) as response:
            payload = response.read(MAX_ARTIFACT_BYTES + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise UpstreamVerificationError(f"cannot fetch {url}: {exc}") from exc
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise UpstreamVerificationError(
            f"upstream artifact exceeds {MAX_ARTIFACT_BYTES} bytes: {url}"
        )
    return payload


def _artifacts(
    section_name: str,
    section: dict[str, Any],
) -> Iterator[tuple[str, dict[str, Any], str | None]]:
    artifacts = section.get("artifacts")
    if not isinstance(artifacts, dict):
        raise UpstreamVerificationError(f"{section_name} artifacts must be an object")

    expected = LOCK_V1_ARTIFACTS[section_name]
    actual_names = set(artifacts)
    expected_names = set(expected)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise UpstreamVerificationError(
            f"{section_name} artifacts must exactly match lockVersion 1; "
            f"missing={missing}, extra={extra}"
        )

    for name, (
        required_upstream_path,
        required_vendored_path,
        required_metadata,
    ) in expected.items():
        artifact = artifacts[name]
        if not isinstance(artifact, dict):
            raise UpstreamVerificationError(
                f"{section_name}.{name} artifact is not an object"
            )
        upstream_path = artifact.get("upstreamPath")
        if upstream_path != required_upstream_path:
            raise UpstreamVerificationError(
                f"{section_name}.{name} must use upstreamPath "
                f"{required_upstream_path!r}, got {upstream_path!r}"
            )
        if required_vendored_path is not None:
            vendored_path = artifact.get("vendoredPath")
            if vendored_path != required_vendored_path:
                raise UpstreamVerificationError(
                    f"{section_name}.{name} must use vendoredPath "
                    f"{required_vendored_path!r}, got {vendored_path!r}"
                )
        for field, required_value in required_metadata.items():
            actual_value = artifact.get(field)
            if actual_value != required_value:
                raise UpstreamVerificationError(
                    f"{section_name}.{name} must use {field} "
                    f"{required_value!r}, got {actual_value!r}"
                )
        required_fields = {"upstreamPath", "sha256", *required_metadata}
        if required_vendored_path is not None:
            required_fields.add("vendoredPath")
        actual_fields = set(artifact)
        if actual_fields != required_fields:
            missing_fields = sorted(required_fields - actual_fields)
            extra_fields = sorted(actual_fields - required_fields)
            raise UpstreamVerificationError(
                f"{section_name}.{name} fields must exactly match lockVersion 1; "
                f"missing={missing_fields}, extra={extra_fields}"
            )
        yield name, artifact, required_vendored_path


def _vendored_path(raw_path: str) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise UpstreamVerificationError(f"unsafe vendored path: {raw_path!r}")
    resolved = (REPO_ROOT / relative).resolve()
    if not resolved.is_relative_to(REPO_ROOT.resolve()):
        raise UpstreamVerificationError(f"vendored path escapes the repo: {raw_path!r}")
    return resolved


def locked_artifacts(lock: dict[str, Any]) -> list[LockedArtifact]:
    """Validate the complete lock schema before any artifact is fetched."""
    lock_version = lock.get("lockVersion")
    if (
        not isinstance(lock_version, int)
        or isinstance(lock_version, bool)
        or lock_version != 1
    ):
        raise UpstreamVerificationError(
            f"lockVersion must be the integer 1, got {lock_version!r}"
        )

    locked: list[LockedArtifact] = []
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
        required_repository = LOCK_V1_REPOSITORIES[section_name]
        if repository != required_repository:
            raise UpstreamVerificationError(
                f"{section_name} must use repository {required_repository!r}, "
                f"got {repository!r}"
            )
        if section_name == "protocol" and section.get("codegen") != LOCK_V1_CODEGEN:
            raise UpstreamVerificationError(
                "protocol codegen must exactly match lockVersion 1; "
                f"expected {LOCK_V1_CODEGEN!r}, got {section.get('codegen')!r}"
            )

        for artifact_name, artifact, required_vendored_path in _artifacts(
            section_name,
            section,
        ):
            upstream_path = artifact.get("upstreamPath")
            expected_digest = artifact.get("sha256")
            if (
                not isinstance(expected_digest, str)
                or SHA256_PATTERN.fullmatch(expected_digest) is None
            ):
                raise UpstreamVerificationError(
                    f"{section_name}.{artifact_name} has an invalid sha256"
                )
            locked.append(
                LockedArtifact(
                    section=section_name,
                    name=artifact_name,
                    repository=repository,
                    commit=commit,
                    upstream_path=upstream_path,
                    sha256=expected_digest,
                    vendored_path=required_vendored_path,
                )
            )
    return locked


def load_lock(path: Path = LOCK_PATH) -> dict[str, Any]:
    """Load a protocol lock object without weakening JSON type checks."""
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpstreamVerificationError(
            f"cannot read protocol lock {path}: {exc}"
        ) from exc
    if not isinstance(lock, dict):
        raise UpstreamVerificationError("protocol lock must be an object")
    return lock


def verify_upstream(
    lock: dict[str, Any],
    *,
    fetch: Callable[[str], bytes] = _fetch,
) -> list[str]:
    """Return verified artifact labels or raise on the first mismatch."""
    artifacts = locked_artifacts(lock)
    verified: list[str] = []
    for artifact in artifacts:
        upstream = fetch(
            _raw_url(
                artifact.repository,
                artifact.commit,
                artifact.upstream_path,
            )
        )
        actual_digest = hashlib.sha256(upstream).hexdigest()
        if actual_digest != artifact.sha256:
            raise UpstreamVerificationError(
                f"{artifact.label} digest differs: "
                f"expected {artifact.sha256}, got {actual_digest}"
            )

        if artifact.vendored_path is not None:
            path = _vendored_path(artifact.vendored_path)
            try:
                local = path.read_bytes()
            except OSError as exc:
                raise UpstreamVerificationError(
                    f"cannot read vendored artifact {artifact.vendored_path}: {exc}"
                ) from exc
            if local != upstream:
                raise UpstreamVerificationError(
                    f"{artifact.label} vendored bytes differ "
                    f"from {artifact.commit}:{artifact.upstream_path}"
                )
        verified.append(artifact.label)
    return verified


def main() -> int:
    try:
        lock = load_lock()
        verified = verify_upstream(lock)
    except UpstreamVerificationError as exc:
        print(f"upstream protocol verification failed: {exc}", file=sys.stderr)
        return 1

    print(f"verified {len(verified)} locked upstream artifacts")
    for label in verified:
        print(f"- {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
