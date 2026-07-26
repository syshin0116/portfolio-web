#!/usr/bin/env python3
"""Regenerate locked Agent Protocol bindings with a pinned toolchain.

The ``prepare`` phase is the only networked phase: it downloads exact-commit
artifacts, verifies their SHA-256 digests, and installs the upstream pnpm lock
with lifecycle scripts disabled. The ``verify`` phase uses only that prepared
workspace, validates every input again, regenerates both bindings, and compares
them byte-for-byte with upstream and vendored copies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import verify_protocol_upstream as upstream

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPO_ROOT / "protocol/agent-protocol.lock.json"
COMMAND_TIMEOUT_SECONDS = 120
INSTALL_TIMEOUT_SECONDS = 300
MAX_DIAGNOSTIC_BYTES = 8 * 1024
PROTOCOL_ARTIFACT_NAMES = frozenset(
    {
        "openapi",
        "cddl",
        "packageManifest",
        "pnpmLock",
        "pnpmWorkspace",
        "pythonFixup",
        "pythonBinding",
        "typescriptBinding",
    }
)
UPSTREAM_PACKAGE_CONTRACT = {
    "packageManager": "pnpm@10.33.0",
    "dependencies": {
        "cddl2py": "^0.2.2",
        "cddl2ts": "^0.9.1",
    },
    "devDependencies": {
        "cddl": "^0.20.1",
    },
    "scripts": {
        "validate:cddl": "cddl validate protocol.cddl",
        "compile:py": (
            "cddl2py protocol.cddl | python3 scripts/fixup.py "
            "> ./py/langchain_protocol/protocol.py"
        ),
        "compile:ts": ("cddl2ts protocol.cddl --field-case snake > ./js/protocol.ts"),
    },
}


class CodegenVerificationError(RuntimeError):
    """The locked generator environment or its output drifted."""


@dataclass(frozen=True)
class CodegenReport:
    repeats: int
    python_sha256: str
    typescript_sha256: str


def _diagnostic(payload: bytes) -> str:
    return payload[-MAX_DIAGNOSTIC_BYTES:].decode("utf-8", errors="replace").strip()


def _run(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    input_bytes: bytes | None = None,
) -> bytes:
    if not argv or not Path(argv[0]).is_absolute():
        raise CodegenVerificationError(
            f"subprocess executable must be an absolute path: {list(argv)!r}"
        )
    try:
        result = subprocess.run(
            list(argv),
            cwd=cwd,
            env=env,
            input=input_bytes,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CodegenVerificationError(
            f"subprocess failed before completion: {list(argv)!r}: {exc}"
        ) from exc
    if result.returncode != 0:
        raise CodegenVerificationError(
            f"subprocess exited {result.returncode}: {list(argv)!r}; "
            f"stderr={_diagnostic(result.stderr)!r}; "
            f"stdout={_diagnostic(result.stdout)!r}"
        )
    return result.stdout


def _resolve_executable(name: str) -> Path:
    raw_path = shutil.which(name)
    if raw_path is None:
        raise CodegenVerificationError(f"required executable is unavailable: {name}")
    path = Path(raw_path).resolve()
    if not path.is_file():
        raise CodegenVerificationError(
            f"resolved executable is not a file: {name} -> {path}"
        )
    if path == REPO_ROOT or path.is_relative_to(REPO_ROOT):
        raise CodegenVerificationError(
            f"refusing repository-controlled executable: {name} -> {path}"
        )
    return path


def require_version(
    label: str,
    *,
    actual: str,
    expected: str,
    prefix: str = "",
) -> None:
    """Require an exact single-line version after one explicit prefix."""
    normalized = actual.strip()
    required = f"{prefix}{expected}"
    if normalized != required:
        raise CodegenVerificationError(
            f"{label} version differs: expected {required!r}, got {normalized!r}"
        )


def _require_python_minor(actual: str, expected: str) -> None:
    normalized = actual.strip()
    prefix = f"Python {expected}."
    patch = normalized.removeprefix(prefix)
    if (
        not normalized.startswith(prefix)
        or not patch
        or not all(part.isdigit() for part in patch.split("."))
    ):
        raise CodegenVerificationError(
            f"python version differs: expected {expected}.x, got {normalized!r}"
        )


def _safe_workspace(path: Path, *, create: bool) -> Path:
    if not path.is_absolute():
        raise CodegenVerificationError("workspace must be an absolute path")
    if path.is_symlink():
        raise CodegenVerificationError(f"workspace must not be a symlink: {path}")
    resolved = path.resolve()
    if resolved == REPO_ROOT or resolved.is_relative_to(REPO_ROOT):
        raise CodegenVerificationError(
            f"workspace must be outside the repository: {resolved}"
        )
    if create:
        if resolved.exists():
            if not resolved.is_dir() or any(resolved.iterdir()):
                raise CodegenVerificationError(
                    f"prepare workspace must be absent or empty: {resolved}"
                )
        else:
            try:
                resolved.mkdir()
            except OSError as exc:
                raise CodegenVerificationError(
                    f"cannot create prepare workspace {resolved}: {exc}"
                ) from exc
    elif not resolved.is_dir():
        raise CodegenVerificationError(f"prepared workspace does not exist: {resolved}")
    return resolved


def _clean_environment(workspace: Path) -> dict[str, str]:
    env = os.environ.copy()
    blocked_prefixes = ("COREPACK_", "NPM_CONFIG_", "PNPM_")
    for key in list(env):
        normalized_key = key.upper()
        if (
            normalized_key.startswith(blocked_prefixes)
            or normalized_key == "NODE_OPTIONS"
        ):
            del env[key]

    npmrc = workspace / "empty.npmrc"
    if not npmrc.exists():
        npmrc.write_text("", encoding="utf-8")
    env.update(
        {
            "CI": "true",
            "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
            "COREPACK_HOME": str(workspace / "corepack"),
            "NPM_CONFIG_IGNORE_SCRIPTS": "true",
            "NPM_CONFIG_GLOBALCONFIG": str(npmrc),
            "NPM_CONFIG_REGISTRY": "https://registry.npmjs.org/",
            "NPM_CONFIG_USERCONFIG": str(npmrc),
            "PNPM_HOME": str(workspace / "pnpm-home"),
            "PNPM_IGNORE_SCRIPTS": "true",
            "XDG_CACHE_HOME": str(workspace / "cache"),
        }
    )
    return env


def _protocol_artifacts(
    lock: dict[str, Any],
) -> dict[str, upstream.LockedArtifact]:
    artifacts = {
        artifact.name: artifact
        for artifact in upstream.locked_artifacts(lock)
        if artifact.section == "protocol"
    }
    missing = sorted(PROTOCOL_ARTIFACT_NAMES - artifacts.keys())
    if missing:
        raise CodegenVerificationError(
            f"codegen lock is missing protocol artifacts: {missing}"
        )
    return artifacts


def _artifact_target(workspace: Path, artifact: upstream.LockedArtifact) -> Path:
    source_root = workspace / "upstream"
    target = source_root.joinpath(*artifact.upstream_path.split("/"))
    resolved = target.resolve()
    if not resolved.is_relative_to(source_root.resolve()):
        raise CodegenVerificationError(
            f"artifact path escapes prepared workspace: {artifact.upstream_path!r}"
        )
    return target


def prepare_workspace(
    lock: dict[str, Any],
    workspace: Path,
    *,
    fetch: Callable[[str], bytes] = upstream._fetch,
) -> int:
    """Download locked inputs and install the frozen generator toolchain."""
    root = _safe_workspace(workspace, create=True)
    artifacts = _protocol_artifacts(lock)
    for artifact in artifacts.values():
        payload = fetch(
            upstream._raw_url(
                artifact.repository,
                artifact.commit,
                artifact.upstream_path,
            )
        )
        digest = hashlib.sha256(payload).hexdigest()
        if digest != artifact.sha256:
            raise CodegenVerificationError(
                f"{artifact.label} digest differs during prepare: "
                f"expected {artifact.sha256}, got {digest}"
            )
        target = _artifact_target(root, artifact)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    package_root = root / "upstream/streaming"
    codegen = lock["protocol"]["codegen"]
    _verify_package_manifest(package_root / "package.json", codegen)
    env = _clean_environment(root)
    node = _resolve_executable("node")
    corepack = _resolve_executable("corepack")
    python = Path(sys.executable).resolve()
    require_version(
        "node",
        actual=_run(
            [str(node), "--version"],
            cwd=package_root,
            env=env,
            timeout=COMMAND_TIMEOUT_SECONDS,
        ).decode(),
        expected=codegen["nodeVersion"],
        prefix="v",
    )
    require_version(
        "corepack",
        actual=_run(
            [str(corepack), "--version"],
            cwd=package_root,
            env=env,
            timeout=COMMAND_TIMEOUT_SECONDS,
        ).decode(),
        expected=codegen["corepackVersion"],
    )
    _require_python_minor(
        _run(
            [str(python), "--version"],
            cwd=package_root,
            env=env,
            timeout=COMMAND_TIMEOUT_SECONDS,
        ).decode(),
        codegen["pythonVersion"],
    )
    package_manager = codegen["packageManager"]
    pnpm_version = package_manager.removeprefix("pnpm@")
    require_version(
        "pnpm",
        actual=_run(
            [str(corepack), package_manager, "--version"],
            cwd=package_root,
            env=env,
            timeout=COMMAND_TIMEOUT_SECONDS,
        ).decode(),
        expected=pnpm_version,
    )
    _run(
        [
            str(corepack),
            package_manager,
            "install",
            "--frozen-lockfile",
            "--ignore-scripts",
            "--store-dir",
            str(root / "pnpm-store"),
        ],
        cwd=package_root,
        env=env,
        timeout=INSTALL_TIMEOUT_SECONDS,
    )
    verify_installed_package_versions(package_root, codegen["packages"])
    return len(artifacts)


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodegenVerificationError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CodegenVerificationError(f"{label} must be a JSON object: {path}")
    return payload


def _verify_package_manifest(path: Path, codegen: dict[str, Any]) -> None:
    manifest = _read_json_object(path, label="upstream package manifest")
    for field, expected in UPSTREAM_PACKAGE_CONTRACT.items():
        actual = manifest.get(field)
        if field in {"dependencies", "devDependencies", "scripts"}:
            if not isinstance(actual, dict):
                raise CodegenVerificationError(
                    f"upstream package manifest {field} must be an object"
                )
            for name, value in expected.items():
                if actual.get(name) != value:
                    raise CodegenVerificationError(
                        f"upstream package manifest {field}.{name} differs: "
                        f"expected {value!r}, got {actual.get(name)!r}"
                    )
        elif actual != expected:
            raise CodegenVerificationError(
                f"upstream package manifest {field} differs: "
                f"expected {expected!r}, got {actual!r}"
            )
    if manifest.get("packageManager") != codegen["packageManager"]:
        raise CodegenVerificationError(
            "upstream packageManager differs from the strict codegen lock"
        )


def verify_installed_package_versions(
    package_root: Path,
    expected: dict[str, str],
) -> None:
    """Validate resolved generator package names and exact versions."""
    for name, expected_version in expected.items():
        manifest_path = package_root / "node_modules" / name / "package.json"
        manifest = _read_json_object(
            manifest_path,
            label=f"{name} installed package manifest",
        )
        if manifest.get("name") != name:
            raise CodegenVerificationError(
                f"{name} installed package name differs: {manifest.get('name')!r}"
            )
        actual_version = manifest.get("version")
        if actual_version != expected_version:
            raise CodegenVerificationError(
                f"{name} package version differs: "
                f"expected {expected_version!r}, got {actual_version!r}"
            )


def _verify_prepared_artifacts(
    lock: dict[str, Any],
    workspace: Path,
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for name, artifact in _protocol_artifacts(lock).items():
        path = _artifact_target(workspace, artifact)
        if path.is_symlink() or not path.is_file():
            raise CodegenVerificationError(
                f"prepared artifact is missing or is a symlink: {path}"
            )
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise CodegenVerificationError(
                f"cannot read prepared artifact {path}: {exc}"
            ) from exc
        digest = hashlib.sha256(payload).hexdigest()
        if digest != artifact.sha256:
            raise CodegenVerificationError(
                f"{artifact.label} prepared digest differs: "
                f"expected {artifact.sha256}, got {digest}"
            )
        payloads[name] = payload
    return payloads


def _locked_binary(package_root: Path, name: str, workspace: Path) -> Path:
    path = package_root / "node_modules/.bin" / name
    if not path.exists():
        raise CodegenVerificationError(f"locked generator binary is missing: {path}")
    resolved = path.resolve()
    if not resolved.is_file() or not resolved.is_relative_to(workspace.resolve()):
        raise CodegenVerificationError(
            f"locked generator binary escapes the prepared workspace: {path}"
        )
    return resolved


def verify_binding_bytes(
    language: str,
    *,
    generated: bytes,
    upstream: bytes,
    vendored: bytes,
) -> str:
    """Require generated, upstream, and vendored binding bytes to be identical."""
    if generated != upstream:
        raise CodegenVerificationError(
            f"{language} generated bytes differ from locked upstream"
        )
    if vendored != upstream:
        raise CodegenVerificationError(
            f"{language} vendored bytes differ from locked upstream"
        )
    return hashlib.sha256(generated).hexdigest()


def _read_vendored(artifact: upstream.LockedArtifact) -> bytes:
    if artifact.vendored_path is None:
        raise CodegenVerificationError(f"{artifact.label} has no strict vendored path")
    path = (REPO_ROOT / artifact.vendored_path).resolve()
    if not path.is_relative_to(REPO_ROOT) or not path.is_file():
        raise CodegenVerificationError(
            f"vendored binding path is invalid: {artifact.vendored_path}"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CodegenVerificationError(
            f"cannot read vendored binding {path}: {exc}"
        ) from exc


def verify_workspace(
    lock: dict[str, Any],
    workspace: Path,
    *,
    repeats: int,
) -> CodegenReport:
    """Regenerate and compare bindings without package or source downloads."""
    if not 1 <= repeats <= 10:
        raise CodegenVerificationError("repeat count must be between 1 and 10")
    root = _safe_workspace(workspace, create=False)
    payloads = _verify_prepared_artifacts(lock, root)
    package_root = root / "upstream/streaming"
    codegen = lock["protocol"]["codegen"]
    _verify_package_manifest(package_root / "package.json", codegen)
    verify_installed_package_versions(package_root, codegen["packages"])
    env = _clean_environment(root)
    env["COREPACK_ENABLE_NETWORK"] = "0"
    env["NPM_CONFIG_OFFLINE"] = "true"
    node = _resolve_executable("node")
    python = Path(sys.executable).resolve()
    require_version(
        "node",
        actual=_run(
            [str(node), "--version"],
            cwd=package_root,
            env=env,
            timeout=COMMAND_TIMEOUT_SECONDS,
        ).decode(),
        expected=codegen["nodeVersion"],
        prefix="v",
    )
    _require_python_minor(
        _run(
            [str(python), "--version"],
            cwd=package_root,
            env=env,
            timeout=COMMAND_TIMEOUT_SECONDS,
        ).decode(),
        codegen["pythonVersion"],
    )
    cddl = _locked_binary(package_root, "cddl", root)
    cddl2py = _locked_binary(package_root, "cddl2py", root)
    cddl2ts = _locked_binary(package_root, "cddl2ts", root)
    _run(
        [str(cddl), "validate", "protocol.cddl"],
        cwd=package_root,
        env=env,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )

    python_outputs: list[bytes] = []
    typescript_outputs: list[bytes] = []
    fixup = package_root / "scripts/fixup.py"
    for _ in range(repeats):
        raw_python = _run(
            [str(cddl2py), "protocol.cddl"],
            cwd=package_root,
            env=env,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        python_outputs.append(
            _run(
                [str(python), str(fixup)],
                cwd=package_root,
                env=env,
                timeout=COMMAND_TIMEOUT_SECONDS,
                input_bytes=raw_python,
            )
        )
        typescript_outputs.append(
            _run(
                [str(cddl2ts), "protocol.cddl", "--field-case", "snake"],
                cwd=package_root,
                env=env,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        )

    if len(set(python_outputs)) != 1:
        raise CodegenVerificationError(
            f"python generation is nondeterministic across {repeats} runs"
        )
    if len(set(typescript_outputs)) != 1:
        raise CodegenVerificationError(
            f"typescript generation is nondeterministic across {repeats} runs"
        )
    artifacts = _protocol_artifacts(lock)
    python_digest = verify_binding_bytes(
        "python",
        generated=python_outputs[0],
        upstream=payloads["pythonBinding"],
        vendored=_read_vendored(artifacts["pythonBinding"]),
    )
    typescript_digest = verify_binding_bytes(
        "typescript",
        generated=typescript_outputs[0],
        upstream=payloads["typescriptBinding"],
        vendored=_read_vendored(artifacts["typescriptBinding"]),
    )
    return CodegenReport(
        repeats=repeats,
        python_sha256=python_digest,
        typescript_sha256=typescript_digest,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="phase", required=True)
    prepare = subparsers.add_parser(
        "prepare",
        help="network: fetch locked sources and frozen-install generators",
    )
    prepare.add_argument("--workspace", required=True, type=Path)
    verify = subparsers.add_parser(
        "verify",
        help="offline: validate CDDL, regenerate, and compare bindings",
    )
    verify.add_argument("--workspace", required=True, type=Path)
    verify.add_argument("--repeat", type=int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        lock = upstream.load_lock(LOCK_PATH)
        if args.phase == "prepare":
            count = prepare_workspace(lock, args.workspace)
            print(
                f"prepared {count} locked protocol codegen artifacts; "
                "network phase complete"
            )
        else:
            report = verify_workspace(
                lock,
                args.workspace,
                repeats=args.repeat,
            )
            print(
                "offline protocol codegen verified: "
                f"{report.repeats} deterministic run(s)"
            )
            print(f"- python sha256: {report.python_sha256}")
            print(f"- typescript sha256: {report.typescript_sha256}")
    except (CodegenVerificationError, upstream.UpstreamVerificationError) as exc:
        print(f"protocol codegen verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
