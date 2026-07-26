"""Dependency-free contracts shared by retrieval serving and evaluation.

The protocol deliberately does not adapt LangChain document or retriever types.  Both
the deployed chat and the evaluation workspace depend on this boundary, while framework
adapters depend on it from the outside.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Protocol, Self, runtime_checkable

type JSONScalar = None | bool | int | float | str
type JSONValue = (
    JSONScalar | Mapping[str, JSONValue] | list[JSONValue] | tuple[JSONValue, ...]
)
type FrozenJSONValue = (
    JSONScalar | Mapping[str, FrozenJSONValue] | tuple[FrozenJSONValue, ...]
)


def _freeze_json(
    value: object,
    *,
    location: str,
    ancestors: frozenset[int] = frozenset(),
) -> FrozenJSONValue:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return str(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{location} must contain only finite JSON numbers")
        return number

    if isinstance(value, Mapping):
        object_id = id(value)
        if object_id in ancestors:
            raise ValueError(f"{location} cannot contain cyclic JSON values")
        descendants = ancestors | {object_id}
        items = list(value.items())
        for key, _ in items:
            if not isinstance(key, str):
                raise TypeError(f"{location} JSON object keys must be strings")
        frozen: dict[str, FrozenJSONValue] = {}
        for key, item in sorted(items, key=lambda pair: pair[0]):
            frozen[key] = _freeze_json(
                item,
                location=f"{location}.{key}",
                ancestors=descendants,
            )
        return MappingProxyType(frozen)

    if isinstance(value, (list, tuple)):
        object_id = id(value)
        if object_id in ancestors:
            raise ValueError(f"{location} cannot contain cyclic JSON values")
        descendants = ancestors | {object_id}
        return tuple(
            _freeze_json(
                item,
                location=f"{location}[{index}]",
                ancestors=descendants,
            )
            for index, item in enumerate(value)
        )

    raise TypeError(
        f"{location} contains {type(value).__name__}, which is not portable JSON"
    )


def _json_copy(value: FrozenJSONValue) -> JSONScalar | dict | list:
    if isinstance(value, Mapping):
        return {key: _json_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_copy(item) for item in value]
    return value


class DocId(str):
    """A canonical path relative to the corpus's ``content/`` root.

    ``DocId`` stays a string subclass so it remains directly JSON serializable.  It
    rejects absolute, platform-specific, and normalizable paths at construction instead
    of relying on every retriever to remember the path boundary.
    """

    def __new__(cls, value: str) -> Self:
        if not isinstance(value, str):
            raise TypeError("DocId must be a string")

        path = PurePosixPath(value)
        has_windows_drive = bool(PureWindowsPath(value).drive)
        is_canonical = bool(value) and bool(path.parts) and str(path) == value
        has_parent_segment = ".." in path.parts
        if (
            "\x00" in value
            or "\\" in value
            or path.is_absolute()
            or has_windows_drive
            or has_parent_segment
            or not is_canonical
        ):
            raise ValueError(
                f"DocId must be a canonical content-relative POSIX path: {value!r}"
            )

        return super().__new__(cls, value)


@dataclass(frozen=True, slots=True)
class Hit:
    """One ranked document or chunk returned by a retrieval method.

    ``score`` is intentionally opaque and method-native.  Consumers compare ordering by
    ``rank`` and must not infer that scores from two methods share a scale or direction.
    """

    doc_id: DocId
    rank: int
    score: float | None
    chunk_id: str | None = None
    text: str | None = None
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "doc_id", DocId(self.doc_id))

        if (
            isinstance(self.rank, bool)
            or not isinstance(self.rank, int)
            or self.rank < 1
        ):
            raise ValueError("Hit.rank must be a positive integer")

        if self.score is not None:
            if isinstance(self.score, bool):
                raise ValueError("Hit.score must be a finite number or None")
            try:
                score = float(self.score)
            except (TypeError, ValueError) as error:
                raise ValueError("Hit.score must be a finite number or None") from error
            if not math.isfinite(score):
                raise ValueError("Hit.score must be a finite number or None")
            object.__setattr__(self, "score", score)

        if self.chunk_id is not None:
            if not isinstance(self.chunk_id, str):
                raise TypeError("Hit.chunk_id must be a string or None")
            if not self.chunk_id:
                raise ValueError("Hit.chunk_id cannot be empty")
        if self.text is not None and not isinstance(self.text, str):
            raise TypeError("Hit.text must be a string or None")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("Hit.metadata must be a mapping")
        object.__setattr__(
            self,
            "metadata",
            _freeze_json(self.metadata, location="Hit.metadata"),
        )

    def as_dict(self) -> dict[str, object]:
        """Return an independent JSON-serializable representation."""

        metadata = _json_copy(self.metadata)
        if not isinstance(metadata, dict):  # __post_init__ fixes the root as a mapping.
            raise TypeError("Hit.metadata must serialize to a JSON object")
        return {
            "doc_id": str(self.doc_id),
            "rank": self.rank,
            "score": self.score,
            "chunk_id": self.chunk_id,
            "text": self.text,
            "metadata": metadata,
        }


@dataclass(frozen=True, slots=True)
class Retrieval:
    """Canonical ranked output for one query."""

    query: str
    hits: tuple[Hit, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.query, str):
            raise TypeError("Retrieval.query must be a string")

        hits = tuple(self.hits)
        if not all(isinstance(hit, Hit) for hit in hits):
            raise TypeError("Retrieval.hits must contain only Hit values")

        ranks = tuple(hit.rank for hit in hits)
        if len(ranks) != len(set(ranks)):
            raise ValueError("Retrieval hit ranks must be unique")

        # Rank is the cross-method contract.  Input sequence and raw scores are not.
        sorted_hits = tuple(sorted(hits, key=lambda hit: hit.rank))
        sorted_ranks = tuple(hit.rank for hit in sorted_hits)
        if sorted_ranks != tuple(range(1, len(sorted_hits) + 1)):
            raise ValueError("Retrieval hit ranks must be contiguous 1..N")
        object.__setattr__(self, "hits", sorted_hits)

    def doc_ids(self, *, limit: int | None = None) -> tuple[DocId, ...]:
        """Return the deduplicated document ranking represented by chunk hits.

        The first (best-ranked) chunk determines each document's position.  This is the
        only chunk-to-document collapse used by serving and evaluation.
        """

        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        ):
            raise ValueError("limit must be a non-negative integer or None")

        ranked: list[DocId] = []
        seen: set[DocId] = set()
        for hit in self.hits:
            if hit.doc_id in seen:
                continue
            seen.add(hit.doc_id)
            ranked.append(hit.doc_id)
            if limit is not None and len(ranked) >= limit:
                break
        return tuple(ranked[:limit])

    def as_dict(self) -> dict[str, object]:
        """Return an independent JSON-serializable representation."""

        return {
            "query": self.query,
            "hits": [hit.as_dict() for hit in self.hits],
        }


@runtime_checkable
class Corpus(Protocol):
    """Published corpus boundary consumed by every retriever."""

    @property
    def fingerprint(self) -> str:
        """Stable identity of the exact indexed corpus."""

    def doc_ids(self) -> Sequence[DocId]:
        """Return the corpus's canonical document identifiers."""

    def read(self, doc_id: DocId) -> str:
        """Read one document by canonical identifier."""


@runtime_checkable
class Retriever(Protocol):
    """Common serving/evaluation retrieval shape."""

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        """Rank up to ``limit`` hits for ``query``."""


@runtime_checkable
class Stage(Retriever, Protocol):
    """Semantic marker for a retriever-shaped pipeline stage.

    Topology is deliberately not part of this Protocol: rerankers may have one input,
    while fusion and graph expansion may have many.  Concrete stages own those links and
    remain interchangeable because their public call shape is exactly ``Retriever``.
    """


@runtime_checkable
class Pipeline(Retriever, Protocol):
    """A composed retriever whose components remain inspectable."""

    @property
    def stages(self) -> Sequence[Retriever]:
        """Ordered components ending in the retriever used for calls."""


__all__ = [
    "Corpus",
    "DocId",
    "Hit",
    "JSONScalar",
    "JSONValue",
    "Pipeline",
    "Retrieval",
    "Retriever",
    "Stage",
]
