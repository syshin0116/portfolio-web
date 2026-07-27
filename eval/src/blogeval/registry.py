"""Evaluation registry: the agent registry plus eval-only method extensions."""

from __future__ import annotations

from collections.abc import Mapping

from agent.retrieval import registry as agent_registry
from agent.retrieval.protocol import Corpus
from agent.retrieval.registry import RetrieverRegistry

from blogeval.methods.char_ngram import (
    CHAR_NGRAM_CONFIG,
    CHAR_NGRAM_IMPLEMENTATION_ID,
    CHAR_NGRAM_METHOD_ID,
)
from blogeval.methods.char_ngram import (
    create as create_char_ngram,
)
from blogeval.methods.rrf import (
    RRF_CONFIG,
    RRF_IMPLEMENTATION_ID,
    RRF_METHOD_ID,
    ReciprocalRankFusionRetriever,
)

registry: RetrieverRegistry = agent_registry.copy()

registry.register(
    CHAR_NGRAM_METHOD_ID,
    create_char_ngram,
    implementation_id=CHAR_NGRAM_IMPLEMENTATION_ID,
    config=CHAR_NGRAM_CONFIG,
    servable=False,
)


def _component_ids(config: Mapping[str, object]) -> tuple[str, ...]:
    raw = config.get("components")
    if not isinstance(raw, list) or not all(isinstance(value, str) for value in raw):
        raise ValueError("RRF components must be a string array")
    method_ids = tuple(raw)
    if len(method_ids) < 2 or len(method_ids) != len(set(method_ids)):
        raise ValueError("RRF components must contain at least two unique methods")
    if RRF_METHOD_ID in method_ids:
        raise ValueError("RRF cannot include itself as a component")
    return method_ids


def rrf_identity(
    corpus: Corpus,
    config: Mapping[str, object],
) -> Mapping[str, object]:
    return {
        **config,
        "component_fingerprints": [
            {
                "fingerprint": registry.retrievable.fingerprint(method_id, corpus),
                "method_id": method_id,
            }
            for method_id in _component_ids(config)
        ],
    }


def create_rrf(
    corpus: Corpus,
    config: Mapping[str, object],
) -> ReciprocalRankFusionRetriever:
    components = tuple(
        (
            method_id,
            resolved.fingerprint,
            resolved,
        )
        for method_id in _component_ids(config)
        for resolved in (registry.retrievable.create(method_id, corpus),)
    )
    return ReciprocalRankFusionRetriever(
        corpus=corpus,
        components=components,
        config=config,
    )


registry.register(
    RRF_METHOD_ID,
    create_rrf,
    implementation_id=RRF_IMPLEMENTATION_ID,
    config=RRF_CONFIG,
    servable=False,
    identity_factory=rrf_identity,
)

retrievable = registry.retrievable

__all__ = ["registry", "retrievable"]
