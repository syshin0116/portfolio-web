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


def _ordered_nfd_atoms(text: str) -> tuple[tuple[str, int], ...]:
    """Return canonically ordered NFD atoms with their input-character owner.

    Normalizing one source character at a time is not enough: combining marks can
    reorder across character boundaries. Carrying the owner through canonical ordering
    gives both the source and NFC forms the same atom stream without guessing where a
    normalization boundary might be.
    """

    decomposed = [
        (atom, owner)
        for owner, character in enumerate(text)
        for atom in unicodedata.normalize("NFD", character)
    ]
    ordered: list[tuple[str, int]] = []
    segment: list[tuple[str, int]] = []

    def flush_segment() -> None:
        if not segment:
            return
        if unicodedata.combining(segment[0][0]) == 0:
            ordered.append(segment[0])
            ordered.extend(
                sorted(segment[1:], key=lambda item: unicodedata.combining(item[0]))
            )
        else:
            ordered.extend(
                sorted(segment, key=lambda item: unicodedata.combining(item[0]))
            )
        segment.clear()

    for atom in decomposed:
        if unicodedata.combining(atom[0]) == 0:
            flush_segment()
        segment.append(atom)
    flush_segment()

    if "".join(atom for atom, _ in ordered) != unicodedata.normalize("NFD", text):
        raise RuntimeError("exact-substring canonical decomposition alignment failed")
    return tuple(ordered)


def _normalized_source_spans(
    text: str,
    normalized_text: str,
) -> tuple[tuple[int, int], ...]:
    """Map every NFC+casefold output character to a conservative source span."""

    nfc_text = unicodedata.normalize("NFC", text)
    if nfc_text == text:
        folded_parts = [character.casefold() for character in text]
        if "".join(folded_parts) != normalized_text:
            raise RuntimeError("exact-substring casefold alignment failed")
        return tuple(
            (source_index, source_index + 1)
            for source_index, folded in enumerate(folded_parts)
            for _ in folded
        )

    source_atoms = _ordered_nfd_atoms(text)
    nfc_atoms = _ordered_nfd_atoms(nfc_text)
    if tuple(atom for atom, _ in source_atoms) != tuple(atom for atom, _ in nfc_atoms):
        raise RuntimeError("exact-substring source and NFC decompositions differ")

    source_count = len(text)
    parents = list(range(source_count + len(nfc_text)))

    def find(owner: int) -> int:
        while parents[owner] != owner:
            parents[owner] = parents[parents[owner]]
            owner = parents[owner]
        return owner

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for (_, source_owner), (_, nfc_owner) in zip(
        source_atoms,
        nfc_atoms,
        strict=True,
    ):
        union(source_owner, source_count + nfc_owner)

    source_owners_by_component: dict[int, list[int]] = {}
    for source_owner in range(source_count):
        source_owners_by_component.setdefault(find(source_owner), []).append(
            source_owner
        )

    nfc_spans: list[tuple[int, int]] = []
    for nfc_owner in range(len(nfc_text)):
        owners = source_owners_by_component.get(find(source_count + nfc_owner), [])
        if not owners:
            raise RuntimeError("exact-substring NFC character has no source provenance")
        nfc_spans.append((min(owners), max(owners) + 1))

    folded_parts = [character.casefold() for character in nfc_text]
    if "".join(folded_parts) != normalized_text:
        raise RuntimeError("exact-substring casefold alignment failed")
    spans = tuple(
        span
        for folded, span in zip(folded_parts, nfc_spans, strict=True)
        for _ in folded
    )
    if len(spans) != len(normalized_text):
        raise RuntimeError("exact-substring normalized span count mismatch")
    return spans


def _snippet(text: str, normalized_text: str, normalized_query: str) -> str:
    normalized_start = normalized_text.find(normalized_query)
    if normalized_start < 0:
        return ""
    normalized_end = normalized_start + len(normalized_query)
    spans = _normalized_source_spans(text, normalized_text)[
        normalized_start:normalized_end
    ]
    if not spans:
        raise RuntimeError("exact-substring match could not be aligned to source text")
    match_start = min(start for start, _ in spans)
    match_end = max(end for _, end in spans)
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
