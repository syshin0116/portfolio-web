"""Evaluation registry: the agent registry plus eval-only method extensions."""

from __future__ import annotations

from collections.abc import Mapping

from agent.retrieval import registry as agent_registry
from agent.retrieval.protocol import Corpus
from agent.retrieval.registry import ResolvedRetriever, RetrieverRegistry

from blogeval.lab.dense import (
    DENSE_CONFIG,
    DENSE_IMPLEMENTATION_ID,
    DENSE_METHOD_ID,
    DENSE_MODEL_ID,
    DENSE_MODEL_REVISION,
)
from blogeval.lab.dense import create as create_dense
from blogeval.methods.char_ngram import (
    CHAR_NGRAM_CONFIG,
    CHAR_NGRAM_IMPLEMENTATION_ID,
    CHAR_NGRAM_METHOD_ID,
)
from blogeval.methods.char_ngram import (
    create as create_char_ngram,
)
from blogeval.methods.rrf import (
    DENSE_RRF_CONFIG,
    DENSE_RRF_IMPLEMENTATION_ID,
    DENSE_RRF_METHOD_ID,
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
    data_dependencies=("corpus:published-markdown",),
    servable=False,
)

registry.register(
    DENSE_METHOD_ID,
    create_dense,
    implementation_id=DENSE_IMPLEMENTATION_ID,
    config=DENSE_CONFIG,
    data_dependencies=(
        "corpus:published-markdown",
        f"model:huggingface/{DENSE_MODEL_ID}@{DENSE_MODEL_REVISION}",
    ),
    servable=False,
)


def _component_ids(
    config: Mapping[str, object],
    *,
    fusion_method_id: str,
) -> tuple[str, ...]:
    raw = config.get("components")
    if not isinstance(raw, list) or not all(isinstance(value, str) for value in raw):
        raise ValueError("RRF components must be a string array")
    method_ids = tuple(raw)
    if len(method_ids) < 2 or len(method_ids) != len(set(method_ids)):
        raise ValueError("RRF components must contain at least two unique methods")
    if fusion_method_id in method_ids:
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
            for method_id in _component_ids(
                config,
                fusion_method_id=RRF_METHOD_ID,
            )
        ],
    }


def create_rrf(
    corpus: Corpus,
    config: Mapping[str, object],
) -> ReciprocalRankFusionRetriever:
    components = _resolve_components(
        corpus,
        _component_ids(
            config,
            fusion_method_id=RRF_METHOD_ID,
        ),
    )
    return ReciprocalRankFusionRetriever(
        corpus=corpus,
        components=components,
        config=config,
        method_id=RRF_METHOD_ID,
        implementation_id=RRF_IMPLEMENTATION_ID,
    )


def dense_rrf_identity(
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
            for method_id in _component_ids(
                config,
                fusion_method_id=DENSE_RRF_METHOD_ID,
            )
        ],
    }


def create_bm25_dense_rrf(
    corpus: Corpus,
    config: Mapping[str, object],
) -> ReciprocalRankFusionRetriever:
    components = _resolve_components(
        corpus,
        _component_ids(
            config,
            fusion_method_id=DENSE_RRF_METHOD_ID,
        ),
    )
    return ReciprocalRankFusionRetriever(
        corpus=corpus,
        components=components,
        config=config,
        method_id=DENSE_RRF_METHOD_ID,
        implementation_id=DENSE_RRF_IMPLEMENTATION_ID,
    )


def _resolve_components(
    corpus: Corpus,
    method_ids: tuple[str, ...],
) -> tuple[tuple[str, str, ResolvedRetriever], ...]:
    created: list[tuple[str, ResolvedRetriever]] = []
    try:
        for method_id in method_ids:
            resolved = registry.retrievable.create(method_id, corpus)
            created.append((method_id, resolved))
        return tuple(
            (method_id, resolved.fingerprint, resolved)
            for method_id, resolved in created
        )
    except BaseException:
        for _, resolved in reversed(created):
            close = getattr(resolved.implementation, "close", None)
            if callable(close):
                close()
        raise


registry.register(
    RRF_METHOD_ID,
    create_rrf,
    implementation_id=RRF_IMPLEMENTATION_ID,
    config=RRF_CONFIG,
    data_dependencies=("artifact:bm25", "corpus:published-markdown"),
    servable=False,
    identity_factory=rrf_identity,
)

registry.register(
    DENSE_RRF_METHOD_ID,
    create_bm25_dense_rrf,
    implementation_id=DENSE_RRF_IMPLEMENTATION_ID,
    config=DENSE_RRF_CONFIG,
    data_dependencies=(
        "artifact:bm25",
        "corpus:published-markdown",
        f"model:huggingface/{DENSE_MODEL_ID}@{DENSE_MODEL_REVISION}",
    ),
    servable=False,
    identity_factory=dense_rrf_identity,
)

retrievable = registry.retrievable

__all__ = ["registry", "retrievable"]
