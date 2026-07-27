from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pytest
from agent.retrieval.corpus import corpus_fingerprint
from agent.retrieval.protocol import Corpus, DocId, Hit, Retrieval

from blogeval.datasets import parse_queryset
from blogeval.jsonio import canonical_json_bytes, json_checksum


@dataclass(frozen=True)
class MemoryCorpus(Corpus):
    documents: Mapping[DocId, str]

    @property
    def fingerprint(self) -> str:
        import hashlib

        return corpus_fingerprint(
            (
                doc_id,
                f"sha256:{hashlib.sha256(text.encode()).hexdigest()}",
            )
            for doc_id, text in self.documents.items()
        )

    def doc_ids(self) -> Sequence[DocId]:
        return tuple(sorted(self.documents, key=str))

    def read(self, doc_id: DocId) -> str:
        return self.documents[DocId(doc_id)]


class RankedRetriever:
    def __init__(
        self,
        corpus: Corpus,
        config: Mapping[str, object],
    ) -> None:
        self._corpus = corpus
        self.identity_config = dict(config)

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        raw = self.identity_config["rankings"]
        if not isinstance(raw, dict):
            raise TypeError("rankings config must be an object")
        ranking = raw.get(query, [])
        if not isinstance(ranking, list):
            raise TypeError("query ranking must be an array")
        return Retrieval(
            query=query,
            hits=tuple(
                Hit(doc_id=DocId(doc_id), rank=rank, score=None)
                for rank, doc_id in enumerate(ranking[:limit], start=1)
            ),
        )


@pytest.fixture
def memory_corpus() -> MemoryCorpus:
    return MemoryCorpus(
        {
            DocId("AI/alpha.md"): "Alpha Docker container guide",
            DocId("AI/beta.md"): "Beta Kubernetes cluster guide",
            DocId("Dev/gamma.md"): "Gamma deployment notes",
        }
    )


@pytest.fixture
def known_dataset(memory_corpus: MemoryCorpus):
    value = {
        "corpus": {
            "document_count": 3,
            "fingerprint": memory_corpus.fingerprint,
            "git_tree_sha": "a" * 40,
        },
        "dataset_id": "known-contract-v1",
        "dataset_kind": "known-item",
        "exclusions": [],
        "provenance": {
            "generator": "contract-fixture",
            "generator_version": 1,
            "included_occurrence_count": 2,
            "source_artifact_schema": "fixture-v1",
            "source_occurrence_count": 2,
        },
        "qrels": [
            {
                "evidence": [
                    {
                        "kind": "synthetic-contract",
                        "occurrences": 1,
                        "source_doc_id": "AI/beta.md",
                        "target": "alpha",
                    }
                ],
                "query": "alpha",
                "query_id": "known-alpha",
                "relevant_doc_ids": ["AI/alpha.md"],
            },
            {
                "evidence": [
                    {
                        "kind": "synthetic-contract",
                        "occurrences": 1,
                        "source_doc_id": "AI/alpha.md",
                        "target": "beta",
                    }
                ],
                "query": "beta",
                "query_id": "known-beta",
                "relevant_doc_ids": ["AI/beta.md"],
            },
        ],
        "schema": "blogeval-queryset-v1",
    }
    payload = canonical_json_bytes(value)
    return parse_queryset(value, checksum=json_checksum(payload))


__all__ = ["MemoryCorpus", "RankedRetriever"]
