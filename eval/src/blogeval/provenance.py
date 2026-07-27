"""Automatic code, lock, and execution identity for evaluation runs."""

from __future__ import annotations

import hashlib
import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path

SOURCE_TREE_DIGEST_SCHEMA = b"blogeval-source-tree-v1\0"
PUBLICATION_PLATFORM = "digest-pinned-linux-x86_64"
IMAGE_DIGEST_ENV = "BLOGEVAL_IMAGE_DIGEST"
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ProvenanceError(ValueError):
    """Execution provenance is missing, malformed, or cannot be measured."""


@dataclass(frozen=True, slots=True)
class RuntimePlatform:
    system: str
    machine: str
    python_implementation: str
    python_version: str

    def as_dict(self) -> dict[str, str]:
        return {
            "machine": self.machine,
            "python_implementation": self.python_implementation,
            "python_version": self.python_version,
            "system": self.system,
        }


@dataclass(frozen=True, slots=True)
class RunProvenance:
    agent_source_tree: str
    eval_source_tree: str
    workspace_lock: str
    runtime: RuntimePlatform
    image_digest: str | None

    @property
    def publication_eligible(self) -> bool:
        return (
            self.runtime.system == "Linux"
            and self.runtime.machine.casefold() in {"amd64", "x86_64"}
            and self.image_digest is not None
            and _IMAGE_DIGEST.fullmatch(self.image_digest) is not None
        )

    def require_publication_eligible(self) -> None:
        if not self.publication_eligible:
            raise ProvenanceError(
                "published evaluation results require execution inside a "
                "digest-pinned Linux x86_64 image; set BLOGEVAL_IMAGE_DIGEST "
                "to that running image's sha256 digest"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "agent_source_tree": self.agent_source_tree,
            "eval_source_tree": self.eval_source_tree,
            "image": {
                "digest": self.image_digest,
            },
            "platform": self.runtime.as_dict(),
            "publication": {
                "eligible": self.publication_eligible,
                "required_platform": PUBLICATION_PLATFORM,
            },
            "workspace_lock": self.workspace_lock,
        }


class _AutomaticImageDigest:
    pass


_AUTOMATIC_IMAGE_DIGEST = _AutomaticImageDigest()


def _sha256_file(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ProvenanceError(f"cannot read provenance input {path}: {exc}") from exc
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def source_tree_digest(root: Path) -> str:
    """Hash canonical relative paths and bytes, excluding interpreter caches."""

    if not root.is_dir():
        raise ProvenanceError(f"source tree is missing or not a directory: {root}")
    files: list[Path] = []
    for candidate in sorted(root.rglob("*")):
        relative = candidate.relative_to(root)
        if "__pycache__" in relative.parts or candidate.suffix in {".pyc", ".pyo"}:
            continue
        if candidate.is_symlink():
            raise ProvenanceError(f"source tree cannot contain symlinks: {candidate}")
        if candidate.is_file():
            files.append(candidate)
    if not files:
        raise ProvenanceError(f"source tree contains no files: {root}")

    digest = hashlib.sha256()
    digest.update(SOURCE_TREE_DIGEST_SCHEMA)
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ProvenanceError(f"cannot read source file {path}: {exc}") from exc
        digest.update(len(relative).to_bytes(8, byteorder="big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, byteorder="big"))
        digest.update(payload)
    return f"sha256:{digest.hexdigest()}"


def _discover_workspace_root() -> Path:
    module = Path(__file__).resolve()
    for candidate in module.parents:
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "uv.lock").is_file()
            and (candidate / "agent/src/agent").is_dir()
            and (candidate / "eval/src/blogeval").is_dir()
        ):
            return candidate
    raise ProvenanceError(
        "cannot discover the uv workspace containing agent/src, eval/src, and uv.lock"
    )


def _runtime_platform() -> RuntimePlatform:
    return RuntimePlatform(
        system=platform.system(),
        machine=platform.machine(),
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
    )


def _validated_image_digest(value: str | None) -> str | None:
    if value is None:
        return None
    if _IMAGE_DIGEST.fullmatch(value) is None:
        raise ProvenanceError(
            f"{IMAGE_DIGEST_ENV} must be sha256 followed by 64 lowercase hex digits"
        )
    return value


def collect_run_provenance(
    *,
    workspace_root: Path | None = None,
    runtime: RuntimePlatform | None = None,
    image_digest: str | None | _AutomaticImageDigest = _AUTOMATIC_IMAGE_DIGEST,
) -> RunProvenance:
    """Measure every local input that can change otherwise identical run bytes."""

    root = (
        _discover_workspace_root()
        if workspace_root is None
        else workspace_root.resolve()
    )
    resolved_image_digest = (
        os.environ.get(IMAGE_DIGEST_ENV)
        if isinstance(image_digest, _AutomaticImageDigest)
        else image_digest
    )
    return RunProvenance(
        agent_source_tree=source_tree_digest(root / "agent/src/agent"),
        eval_source_tree=source_tree_digest(root / "eval/src/blogeval"),
        workspace_lock=_sha256_file(root / "uv.lock"),
        runtime=_runtime_platform() if runtime is None else runtime,
        image_digest=_validated_image_digest(resolved_image_digest),
    )


__all__ = [
    "IMAGE_DIGEST_ENV",
    "PUBLICATION_PLATFORM",
    "ProvenanceError",
    "RunProvenance",
    "RuntimePlatform",
    "collect_run_provenance",
    "source_tree_digest",
]
