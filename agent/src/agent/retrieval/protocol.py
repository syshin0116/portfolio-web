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
from typing import Protocol, Self, runtime_checkable


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
    metadata: Mapping[str, object] = field(default_factory=dict)

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

        if self.chunk_id is not None and not self.chunk_id:
            raise ValueError("Hit.chunk_id cannot be empty")
        if self.text is not None and not isinstance(self.text, str):
            raise TypeError("Hit.text must be a string or None")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("Hit.metadata must be a mapping")
        # Snapshot caller-owned mappings while keeping normal dataclass/JSON tooling
        # usable.  Metadata is descriptive output, not part of ranking identity.
        object.__setattr__(self, "metadata", dict(self.metadata))


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
        object.__setattr__(self, "hits", tuple(sorted(hits, key=lambda hit: hit.rank)))

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
    "Pipeline",
    "Retrieval",
    "Retriever",
    "Stage",
]
