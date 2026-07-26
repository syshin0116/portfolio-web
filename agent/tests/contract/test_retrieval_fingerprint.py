"""Stable identity tests shared by chat and evaluation registries."""

from __future__ import annotations

import pytest

from agent.retrieval.fingerprint import (
    canonical_config,
    retriever_fingerprint,
)


def test_canonical_config_when_mapping_order_differs_produces_same_json() -> None:
    left = canonical_config(
        {"weights": {"body": 1, "title": 3}, "fields": ["title", "body"]}
    )
    right = canonical_config(
        {"fields": ["title", "body"], "weights": {"title": 3, "body": 1}}
    )

    assert left == right
    assert left == '{"fields":["title","body"],"weights":{"body":1,"title":3}}'


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"method_id": "bm25-ngram"}, "method"),
        ({"implementation_id": "agent.retrieval.bm25:create@2"}, "implementation"),
        ({"config": {"k1": 2.0, "b": 0.75}}, "config"),
        ({"corpus_fingerprint": "sha256:corpus-b"}, "corpus"),
    ],
)
def test_retriever_fingerprint_when_identity_component_changes_is_different(
    overrides: dict[str, object],
    reason: str,
) -> None:
    base: dict[str, object] = {
        "method_id": "bm25-kiwi",
        "implementation_id": "agent.retrieval.bm25:create@1",
        "config": {"b": 0.75, "k1": 1.5},
        "corpus_fingerprint": "sha256:corpus-a",
    }
    changed = base | overrides

    assert retriever_fingerprint(**base) != retriever_fingerprint(**changed), reason


def test_retriever_fingerprint_when_inputs_match_is_stable_known_digest() -> None:
    fingerprint = retriever_fingerprint(
        method_id="bm25-kiwi",
        implementation_id="agent.retrieval.bm25:create@1",
        config={"k1": 1.5, "b": 0.75},
        corpus_fingerprint="sha256:corpus-a",
    )

    assert (
        fingerprint
        == "sha256:811ef6a099f92d55a78bd2db08fe02409238b9f45084e789ae80f335c4402940"
    )


@pytest.mark.parametrize(
    "implementation_id",
    [
        "",
        "agent.retrieval.bm25:create",
        "@1",
        "agent.retrieval.bm25:create@",
        "agent.retrieval.bm25:create@1@dirty",
        " agent.retrieval.bm25:create@1",
        "agent.retrieval.bm25:create@1 ",
    ],
)
def test_retriever_fingerprint_when_implementation_id_is_not_versioned_rejects(
    implementation_id: str,
) -> None:
    with pytest.raises(ValueError, match="implementation_id|versioned"):
        retriever_fingerprint(
            method_id="bm25-kiwi",
            implementation_id=implementation_id,
            config={"k1": 1.5, "b": 0.75},
            corpus_fingerprint="sha256:corpus-a",
        )


@pytest.mark.parametrize(
    "config",
    [
        {"bad": float("nan")},
        {"bad": float("inf")},
        {"bad": object()},
        {1: "non-string key"},
    ],
)
def test_canonical_config_when_value_is_not_portable_json_rejects(
    config: object,
) -> None:
    with pytest.raises((TypeError, ValueError), match="JSON|finite|string"):
        canonical_config(config)  # type: ignore[arg-type]
