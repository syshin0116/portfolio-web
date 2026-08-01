"""Reciprocal-rank fusion over same-Protocol registered retrievers."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence

from agent.retrieval.fingerprint import canonical_config, retriever_fingerprint
from agent.retrieval.protocol import Corpus, DocId, Hit, Retrieval, Retriever
from agent.retrieval.registry import ResolvedRetriever

RRF_METHOD_ID = "rrf-bm25-char-ngram"
RRF_IMPLEMENTATION_ID = "blogeval.methods.rrf:create@1"
RRF_CONFIG: dict[str, object] = {
    "candidate_multiplier": 4,
    "components": ["bm25", "char-ngram"],
    "minimum_candidates": 50,
    "rrf_k": 60,
}
DENSE_RRF_METHOD_ID = "rrf-bm25-dense-multilingual-e5-small"
DENSE_RRF_IMPLEMENTATION_ID = "blogeval.methods.rrf:create_bm25_dense_rrf@1"
DENSE_RRF_CONFIG: dict[str, object] = {
    "candidate_multiplier": 4,
    "components": ["bm25", "dense-multilingual-e5-small"],
    "minimum_candidates": 50,
    "rrf_k": 60,
}


class ReciprocalRankFusionRetriever:
    """Fuse component document ranks without comparing method-native scores."""

    def __init__(
        self,
        *,
        corpus: Corpus,
        components: Sequence[tuple[str, str, Retriever]],
        config: Mapping[str, object],
        method_id: str = RRF_METHOD_ID,
        implementation_id: str = RRF_IMPLEMENTATION_ID,
    ) -> None:
        if len(components) < 2:
            raise ValueError("RRF requires at least two component retrievers")
        method_ids = tuple(method_id for method_id, _, _ in components)
        if len(method_ids) != len(set(method_ids)):
            raise ValueError("RRF component method IDs must be unique")
        self._corpus = corpus
        self._method_id = method_id
        self._implementation_id = implementation_id
        self._components = tuple(components)
        self._config = json.loads(canonical_config(config))
        self._identity = {
            **self._config,
            "component_fingerprints": [
                {"fingerprint": fingerprint, "method_id": method_id}
                for method_id, fingerprint, _ in components
            ],
        }

    @property
    def identity_config(self) -> dict[str, object]:
        return json.loads(canonical_config(self._identity))

    @property
    def fingerprint(self) -> str:
        return retriever_fingerprint(
            method_id=self._method_id,
            implementation_id=self._implementation_id,
            config=self._identity,
            corpus_fingerprint=self._corpus.fingerprint,
        )

    def close(self) -> None:
        for _, _, retriever in self._components:
            implementation = (
                retriever.implementation
                if isinstance(retriever, ResolvedRetriever)
                else retriever
            )
            close = getattr(implementation, "close", None)
            if callable(close):
                close()

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0:
            return Retrieval(query=query)
        candidate_limit = max(
            int(self._config["minimum_candidates"]),
            limit * int(self._config["candidate_multiplier"]),
        )
        rrf_k = int(self._config["rrf_k"])
        scores: dict[DocId, float] = defaultdict(float)
        component_ranks: dict[DocId, dict[str, int]] = defaultdict(dict)
        for method_id, _, retriever in self._components:
            ranking = retriever.retrieve(query, limit=candidate_limit).doc_ids()
            for rank, doc_id in enumerate(ranking, start=1):
                scores[doc_id] += 1.0 / (rrf_k + rank)
                component_ranks[doc_id][method_id] = rank
        ordered = sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))
        return Retrieval(
            query=query,
            hits=tuple(
                Hit(
                    doc_id=doc_id,
                    rank=rank,
                    score=score,
                    metadata={
                        "component_ranks": component_ranks[doc_id],
                        "rrf_k": rrf_k,
                    },
                )
                for rank, (doc_id, score) in enumerate(ordered[:limit], start=1)
            ),
        )


__all__ = [
    "DENSE_RRF_CONFIG",
    "DENSE_RRF_IMPLEMENTATION_ID",
    "DENSE_RRF_METHOD_ID",
    "RRF_CONFIG",
    "RRF_IMPLEMENTATION_ID",
    "RRF_METHOD_ID",
    "ReciprocalRankFusionRetriever",
]
