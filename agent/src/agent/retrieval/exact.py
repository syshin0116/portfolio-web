"""Deterministic exact-substring retrieval over the verified published corpus."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping

from agent.retrieval.fingerprint import canonical_config, retriever_fingerprint
from agent.retrieval.protocol import Corpus, DocId, Hit, Retrieval
from agent.retrieval.registry import registry

EXACT_METHOD_ID = "exact-substring"
EXACT_IMPLEMENTATION_ID = "agent.retrieval.exact:create@1"
EXACT_CONFIG: dict[str, object] = {
    "match": "non-overlapping-substring-count",
    "normalization": "NFC+casefold",
    "query_whitespace": "strip",
    "source": "verified-published-markdown",
}
_SNIPPET_RADIUS = 140


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _normalization_units(text: str) -> tuple[tuple[str, int, int], ...]:
    """Split text only where NFC+casefold cannot interact across the boundary."""

    if not text:
        return ()
    units: list[tuple[str, int, int]] = []
    start = 0
    raw = text[0]
    for index, character in enumerate(text[1:], start=1):
        if _normalize(raw + character) == _normalize(raw) + _normalize(character):
            units.append((_normalize(raw), start, index))
            start = index
            raw = character
        else:
            raw += character
    units.append((_normalize(raw), start, len(text)))
    return tuple(units)


def _snippet(text: str, normalized_text: str, normalized_query: str) -> str:
    normalized_start = normalized_text.find(normalized_query)
    if normalized_start < 0:
        return ""
    normalized_end = normalized_start + len(normalized_query)
    normalized_offset = 0
    match_start: int | None = None
    match_end: int | None = None
    rebuilt: list[str] = []
    for normalized_unit, source_start, source_end in _normalization_units(text):
        rebuilt.append(normalized_unit)
        unit_end = normalized_offset + len(normalized_unit)
        if unit_end > normalized_start and normalized_offset < normalized_end:
            if match_start is None:
                match_start = source_start
            match_end = source_end
        normalized_offset = unit_end
    if "".join(rebuilt) != normalized_text:
        raise RuntimeError("exact-substring normalization alignment failed")
    if match_start is None or match_end is None:
        raise RuntimeError("exact-substring match could not be aligned to source text")
    if normalized_query not in _normalize(text[match_start:match_end]):
        raise RuntimeError("exact-substring source span does not contain the match")

    lower = max(0, match_start - _SNIPPET_RADIUS)
    upper = min(len(text), match_end + _SNIPPET_RADIUS)
    prefix = "..." if lower else ""
    suffix = "..." if upper < len(text) else ""
    return prefix + text[lower:upper].strip() + suffix


class ExactSubstringRetriever:
    """Rank documents by raw literal occurrence count.

    The implementation deliberately does not accept regular expressions. It is a stable
    floor for the evaluation testbed and cannot turn an anonymous query into an
    unbounded regex execution.
    """

    def __init__(self, corpus: Corpus) -> None:
        fingerprint = getattr(corpus, "fingerprint", None)
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("ExactSubstringRetriever requires a fingerprinted Corpus")
        self._corpus = corpus
        self._documents = tuple(
            (
                DocId(doc_id),
                text,
                _normalize(text),
            )
            for doc_id in corpus.doc_ids()
            for text in (corpus.read(DocId(doc_id)),)
        )

    @property
    def identity_config(self) -> dict[str, object]:
        return json.loads(canonical_config(EXACT_CONFIG))

    @property
    def fingerprint(self) -> str:
        return retriever_fingerprint(
            method_id=EXACT_METHOD_ID,
            implementation_id=EXACT_IMPLEMENTATION_ID,
            config=EXACT_CONFIG,
            corpus_fingerprint=self._corpus.fingerprint,
        )

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        normalized_query = _normalize(query.strip())
        if limit == 0 or not normalized_query:
            return Retrieval(query=query)

        matches = sorted(
            (
                (
                    normalized_text.count(normalized_query),
                    doc_id,
                    text,
                    normalized_text,
                )
                for doc_id, text, normalized_text in self._documents
            ),
            key=lambda item: (-item[0], str(item[1])),
        )
        positive = (item for item in matches if item[0] > 0)
        return Retrieval(
            query=query,
            hits=tuple(
                Hit(
                    doc_id=doc_id,
                    rank=rank,
                    score=float(count),
                    text=_snippet(text, normalized_text, normalized_query),
                    metadata={"match_count": count},
                )
                for rank, (count, doc_id, text, normalized_text) in enumerate(
                    positive,
                    start=1,
                )
                if rank <= limit
            ),
        )


def create(
    corpus: Corpus,
    config: Mapping[str, object],
) -> ExactSubstringRetriever:
    """Construct the registered exact-substring implementation."""

    if canonical_config(config) != canonical_config(EXACT_CONFIG):
        raise ValueError(
            "registered exact-substring config does not match implementation"
        )
    return ExactSubstringRetriever(corpus)


registry.register(
    EXACT_METHOD_ID,
    create,
    implementation_id=EXACT_IMPLEMENTATION_ID,
    config=EXACT_CONFIG,
    servable=True,
)

__all__ = [
    "EXACT_CONFIG",
    "EXACT_IMPLEMENTATION_ID",
    "EXACT_METHOD_ID",
    "ExactSubstringRetriever",
    "create",
]
