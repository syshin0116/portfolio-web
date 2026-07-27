"""Automatic code, lock, and execution identity for evaluation runs."""

from __future__ import annotations

import hashlib
import platform
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

SOURCE_TREE_DIGEST_SCHEMA = b"blogeval-source-tree-v1\0"
PUBLICATION_PLATFORM = "attested-digest-pinned-linux-x86_64"
PUBLICATION_WORKFLOW = ".github/workflows/eval-publication.yml"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


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

    @property
    def publication_eligible(self) -> bool:
        # A process cannot prove the identity of the container that launched it.
        # Publication is an external, GitHub-attested workflow decision.
        return False

    def require_publication_eligible(self) -> None:
        raise ProvenanceError(
            "local runs are never publication-eligible; publication requires the "
            f"verified GitHub attestation boundary in {PUBLICATION_WORKFLOW}"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "agent_source_tree": self.agent_source_tree,
            "eval_source_tree": self.eval_source_tree,
            "platform": self.runtime.as_dict(),
            "publication": {
                "eligible": False,
                "required_platform": PUBLICATION_PLATFORM,
                "trusted_workflow": PUBLICATION_WORKFLOW,
            },
            "workspace_lock": self.workspace_lock,
        }


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


def collect_run_provenance(
    *,
    workspace_root: Path | None = None,
    runtime: RuntimePlatform | None = None,
) -> RunProvenance:
    """Measure every local input that can change otherwise identical run bytes."""

    root = (
        _discover_workspace_root()
        if workspace_root is None
        else workspace_root.resolve()
    )
    return RunProvenance(
        agent_source_tree=source_tree_digest(root / "agent/src/agent"),
        eval_source_tree=source_tree_digest(root / "eval/src/blogeval"),
        workspace_lock=_sha256_file(root / "uv.lock"),
        runtime=_runtime_platform() if runtime is None else runtime,
    )


def parse_run_provenance(value: object) -> RunProvenance:
    """Parse the exact locally-recordable provenance contract."""

    if not isinstance(value, Mapping) or set(value) != {
        "agent_source_tree",
        "eval_source_tree",
        "platform",
        "publication",
        "workspace_lock",
    }:
        raise ProvenanceError("run provenance has an unexpected object shape")
    raw = cast(Mapping[str, object], value)
    digests: dict[str, str] = {}
    for field in ("agent_source_tree", "eval_source_tree", "workspace_lock"):
        item = raw[field]
        if not isinstance(item, str) or _SHA256.fullmatch(item) is None:
            raise ProvenanceError(f"run provenance {field} must be a sha256 checksum")
        digests[field] = item
    platform_value = raw["platform"]
    if not isinstance(platform_value, Mapping) or set(platform_value) != {
        "machine",
        "python_implementation",
        "python_version",
        "system",
    }:
        raise ProvenanceError("run provenance platform has an unexpected shape")
    platform_values = cast(Mapping[str, object], platform_value)
    if not all(
        isinstance(platform_values[field], str) and platform_values[field]
        for field in platform_values
    ):
        raise ProvenanceError(
            "run provenance platform values must be non-empty strings"
        )
    publication = raw["publication"]
    expected_publication = {
        "eligible": False,
        "required_platform": PUBLICATION_PLATFORM,
        "trusted_workflow": PUBLICATION_WORKFLOW,
    }
    if publication != expected_publication:
        raise ProvenanceError(
            "run provenance cannot claim local publication eligibility"
        )
    return RunProvenance(
        agent_source_tree=digests["agent_source_tree"],
        eval_source_tree=digests["eval_source_tree"],
        workspace_lock=digests["workspace_lock"],
        runtime=RuntimePlatform(
            system=cast(str, platform_values["system"]),
            machine=cast(str, platform_values["machine"]),
            python_implementation=cast(
                str,
                platform_values["python_implementation"],
            ),
            python_version=cast(str, platform_values["python_version"]),
        ),
    )


__all__ = [
    "PUBLICATION_PLATFORM",
    "PUBLICATION_WORKFLOW",
    "ProvenanceError",
    "RunProvenance",
    "RuntimePlatform",
    "collect_run_provenance",
    "parse_run_provenance",
    "source_tree_digest",
]
