"""Shared retrieval contract and serving registry."""

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
    "DocId",
    "Hit",
    "Pipeline",
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
