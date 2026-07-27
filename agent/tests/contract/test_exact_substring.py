"""Exact-substring baseline contracts."""

from __future__ import annotations

from agent.retrieval.exact import (
    EXACT_IMPLEMENTATION_ID,
    EXACT_METHOD_ID,
    ExactSubstringRetriever,
)
from agent.retrieval.protocol import DocId
from agent.retrieval.registry import registry


class MemoryCorpus:
    fingerprint = "sha256:" + "a" * 64

    def __init__(self, documents: dict[str, str]) -> None:
        self._documents = {
            DocId(doc_id): text for doc_id, text in sorted(documents.items())
        }

    def doc_ids(self) -> tuple[DocId, ...]:
        return tuple(self._documents)

    def read(self, doc_id: DocId) -> str:
        return self._documents[doc_id]


def test_exact_substring_uses_raw_counts_and_stable_doc_id_ties() -> None:
    retriever = ExactSubstringRetriever(
        MemoryCorpus(
            {
                "AI/z.md": "Docker docker",
                "AI/a.md": "DOCKER docker",
                "AI/none.md": "unrelated",
            }
        )
    )

    result = retriever.retrieve("docker")

    assert [str(hit.doc_id) for hit in result.hits] == ["AI/a.md", "AI/z.md"]
    assert [hit.score for hit in result.hits] == [2.0, 2.0]
    assert [hit.rank for hit in result.hits] == [1, 2]


def test_exact_substring_normalizes_unicode_and_treats_regex_as_literal() -> None:
    retriever = ExactSubstringRetriever(
        MemoryCorpus(
            {
                "AI/unicode.md": "Cafe\u0301 CAFÉ",
                "AI/regex.md": "axb and a.*b",
            }
        )
    )

    assert retriever.retrieve("café").hits[0].score == 2.0
    literal = retriever.retrieve("a.*b")
    assert [str(hit.doc_id) for hit in literal.hits] == ["AI/regex.md"]
    assert literal.hits[0].score == 1.0


def test_unicode_expansion_and_composition_snippets_use_original_offsets() -> None:
    decomposed = "prefix " + ("x" * 160) + " Cafe\u0301 finish"
    retriever = ExactSubstringRetriever(
        MemoryCorpus(
            {
                "AI/eszett.md": "Die Straße führt zum Ziel.",
                "AI/combining.md": decomposed,
            }
        )
    )

    eszett = retriever.retrieve("STRASSE").hits[0]
    combining = retriever.retrieve("café").hits[0]

    assert eszett.text is not None and "Straße" in eszett.text
    assert combining.text is not None and "Cafe\u0301" in combining.text
    assert combining.text.startswith("...")
    assert "finish" in combining.text


def test_exact_substring_empty_absent_and_zero_limit_have_no_hits() -> None:
    retriever = ExactSubstringRetriever(MemoryCorpus({"AI/a.md": "alpha"}))

    assert retriever.retrieve("").hits == ()
    assert retriever.retrieve("   ").hits == ()
    assert retriever.retrieve("absent").hits == ()
    assert retriever.retrieve("alpha", limit=0).hits == ()


def test_exact_substring_registry_identity_is_shared_with_serving() -> None:
    corpus = MemoryCorpus({"AI/a.md": "alpha"})
    resolved = registry.servable.create(EXACT_METHOD_ID, corpus)

    assert resolved.method_id == EXACT_METHOD_ID
    assert resolved.registration.implementation_id == EXACT_IMPLEMENTATION_ID
    assert resolved.fingerprint == resolved.implementation.fingerprint
