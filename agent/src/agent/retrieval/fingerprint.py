"""Portable retrieval method/config/corpus identity."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping

type JSONScalar = None | bool | int | float | str
type JSONValue = (
    JSONScalar | Mapping[str, JSONValue] | list[JSONValue] | tuple[JSONValue, ...]
)

_FINGERPRINT_SCHEMA = "retriever-fingerprint-v1"


def _portable_json(value: object, *, location: str) -> JSONScalar | dict | list:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{location} must contain only finite JSON numbers")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{location} JSON object keys must be strings")
            normalized[key] = _portable_json(
                item,
                location=f"{location}.{key}",
            )
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _portable_json(item, location=f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    raise TypeError(
        f"{location} contains {type(value).__name__}, which is not portable JSON"
    )


def canonical_config(config: Mapping[str, object]) -> str:
    """Serialize method configuration without ordering or platform ambiguity."""

    if not isinstance(config, Mapping):
        raise TypeError("config must be a JSON object mapping")
    normalized = _portable_json(config, location="config")
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _require_identity(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{field} cannot contain leading or trailing whitespace")
    return value


def validate_implementation_id(value: str) -> str:
    """Require a caller-owned identity revision such as ``module:create@2``."""

    implementation_id = _require_identity(value, field="implementation_id")
    parts = implementation_id.split("@")
    if (
        len(parts) != 2
        or not parts[0]
        or not parts[1]
        or any(character.isspace() for character in implementation_id)
    ):
        raise ValueError(
            "implementation_id must be versioned as '<identity>@<version-or-sha>'"
        )
    return implementation_id


def retriever_fingerprint(
    *,
    method_id: str,
    implementation_id: str,
    config: Mapping[str, object],
    corpus_fingerprint: str,
) -> str:
    """Hash every component that must agree between chat and eval registries."""

    payload = {
        "schema": _FINGERPRINT_SCHEMA,
        "method_id": _require_identity(method_id, field="method_id"),
        "implementation_id": validate_implementation_id(implementation_id),
        "config": json.loads(canonical_config(config)),
        "corpus_fingerprint": _require_identity(
            corpus_fingerprint,
            field="corpus_fingerprint",
        ),
    }
    canonical_payload = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


__all__ = [
    "JSONScalar",
    "JSONValue",
    "canonical_config",
    "retriever_fingerprint",
    "validate_implementation_id",
]
