from __future__ import annotations

from collections.abc import Mapping

import pytest
from agent.retrieval import registry as agent_registry
from agent.retrieval.protocol import Corpus, DocId, Hit, Retrieval

from blogeval.methods.char_ngram import CharNgramRetriever
from blogeval.methods.rrf import ReciprocalRankFusionRetriever
from blogeval.registry import registry
from conftest import MemoryCorpus


class FixedRetriever:
    def __init__(self, rankings: Mapping[str, tuple[str, ...]]) -> None:
        self._rankings = rankings

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        return Retrieval(
            query=query,
            hits=tuple(
                Hit(doc_id=DocId(doc_id), rank=rank, score=None)
                for rank, doc_id in enumerate(
                    self._rankings.get(query, ())[:limit],
                    start=1,
                )
            ),
        )


def test_char_ngram_mixed_script_query_ranks_matching_document_and_is_stable(
    memory_corpus: MemoryCorpus,
) -> None:
    retriever = CharNgramRetriever(memory_corpus)

    first = retriever.retrieve("Docker container", limit=3)
    second = retriever.retrieve("Docker container", limit=3)

    assert first.doc_ids()[0] == DocId("AI/alpha.md")
    assert first.as_dict() == second.as_dict()
    assert first.hits[0].score is not None
    assert first.hits[0].score > 0
    assert retriever.retrieve("!!!", limit=3).hits == ()


def test_rrf_uses_component_ranks_and_doc_id_for_deterministic_ties(
    memory_corpus: MemoryCorpus,
) -> None:
    left = FixedRetriever({"query": ("AI/alpha.md", "AI/beta.md")})
    right = FixedRetriever({"query": ("AI/beta.md", "AI/alpha.md")})
    retriever = ReciprocalRankFusionRetriever(
        corpus=memory_corpus,
        components=(
            ("left", "sha256:" + "1" * 64, left),
            ("right", "sha256:" + "2" * 64, right),
        ),
        config={
            "candidate_multiplier": 2,
            "components": ["left", "right"],
            "minimum_candidates": 2,
            "rrf_k": 60,
        },
    )

    result = retriever.retrieve("query", limit=2)

    assert result.doc_ids() == (
        DocId("AI/alpha.md"),
        DocId("AI/beta.md"),
    )
    assert result.hits[0].score == result.hits[1].score
    assert result.hits[0].metadata["component_ranks"] == {
        "left": 1,
        "right": 2,
    }


def test_eval_registry_extends_a_copy_without_mutating_agent_serving(
    memory_corpus: MemoryCorpus,
) -> None:
    assert "char-ngram" not in agent_registry.retrievable
    assert "rrf-bm25-char-ngram" not in agent_registry.retrievable
    assert "char-ngram" in registry.retrievable
    assert "rrf-bm25-char-ngram" in registry.retrievable
    assert "char-ngram" not in registry.servable
    assert "rrf-bm25-char-ngram" not in registry.servable

    first = registry.retrievable.fingerprint("char-ngram", memory_corpus)
    second = registry.retrievable.fingerprint("char-ngram", memory_corpus)
    assert first == second
    assert first.startswith("sha256:")


def test_char_ngram_rejects_invalid_limit(memory_corpus: Corpus) -> None:
    retriever = CharNgramRetriever(memory_corpus)
    with pytest.raises(ValueError, match="non-negative integer"):
        retriever.retrieve("query", limit=-1)
