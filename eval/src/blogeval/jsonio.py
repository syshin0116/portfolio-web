"""Strict and canonical JSON helpers used by datasets and result records."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path


class StrictJsonError(ValueError):
    """JSON input is ambiguous, non-portable, or not canonical."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJsonError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise StrictJsonError(f"non-finite JSON constant: {value}")


def load_json_bytes(payload: bytes, *, location: str) -> object:
    """Decode strict UTF-8 JSON while rejecting duplicate keys and NaN values."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StrictJsonError(f"{location} is not valid UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except StrictJsonError:
        raise
    except json.JSONDecodeError as exc:
        raise StrictJsonError(f"{location} is not valid JSON: {exc}") from exc


def _portable(value: object, *, location: str) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise StrictJsonError(f"{location} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise StrictJsonError(f"{location} contains a non-string object key")
            normalized[key] = _portable(item, location=f"{location}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _portable(item, location=f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    raise StrictJsonError(
        f"{location} contains unsupported JSON value {type(value).__name__}"
    )


def canonical_json_bytes(value: object) -> bytes:
    """Return the repository's deterministic human-readable JSON encoding."""

    portable = _portable(value, location="$")
    return (
        json.dumps(
            portable,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def json_checksum(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def load_canonical_json(path: Path) -> tuple[object, bytes]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise StrictJsonError(f"cannot read {path}: {exc}") from exc
    value = load_json_bytes(payload, location=str(path))
    expected = canonical_json_bytes(value)
    if payload != expected:
        raise StrictJsonError(
            f"{path} is not canonical JSON; regenerate it instead of hand-editing"
        )
    return value, payload


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    """Atomically publish bytes, preserving an identical existing record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise OSError(f"cannot inspect existing output {path}: {exc}") from exc
        if existing == payload:
            return

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_bytes_immutable(path: Path, payload: bytes) -> None:
    """Create a record once, or prove an existing record is byte-identical."""

    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise OSError(f"cannot inspect existing record {path}: {exc}") from exc
        if existing != payload:
            raise OSError(f"refusing to replace non-identical evaluation record {path}")
        return
    write_bytes_atomic(path, payload)
