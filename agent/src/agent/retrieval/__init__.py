"""Shared retrieval contract and serving registry."""

# Importing registers the built-in method. Heavy Kiwi/rank_bm25 imports remain lazy.
from agent.retrieval.bm25 import Bm25Retriever  # noqa: E402
from agent.retrieval.corpus import CorpusManifestError, PublishedCorpus
from agent.retrieval.fingerprint import retriever_fingerprint
from agent.retrieval.protocol import (
    Corpus,
    DocId,
    Hit,
    Pipeline,
    Retrieval,
    Retriever,
    Stage,
)
from agent.retrieval.registry import (
    ResolvedRetriever,
    RetrieverRegistry,
    registry,
    retrievable,
    servable,
)

__all__ = [
    "Corpus",
    "CorpusManifestError",
    "DocId",
    "Bm25Retriever",
    "Hit",
    "Pipeline",
    "PublishedCorpus",
    "ResolvedRetriever",
    "Retrieval",
    "Retriever",
    "RetrieverRegistry",
    "Stage",
    "registry",
    "retrievable",
    "retriever_fingerprint",
    "servable",
]
