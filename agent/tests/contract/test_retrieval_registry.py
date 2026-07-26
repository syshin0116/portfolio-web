"""Registry-view and shared method identity contract tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from agent.retrieval.protocol import Corpus, DocId, Hit, Retrieval
from agent.retrieval.registry import RetrieverRegistry


@dataclass
class MemoryCorpus:
    fingerprint: str = "sha256:corpus-a"

    def doc_ids(self) -> tuple[DocId, ...]:
        return (DocId("AI/post.md"),)

    def read(self, doc_id: DocId) -> str:
        return f"body:{doc_id}"


class EchoRetriever:
    def __init__(self, corpus: Corpus, config: Mapping[str, object]) -> None:
        self._corpus = corpus
        self._score = float(config["score"])

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        hits = (
            Hit(
                doc_id=self._corpus.doc_ids()[0],
                rank=1,
                score=self._score,
                text=self._corpus.read(self._corpus.doc_ids()[0]),
            ),
        )
        return Retrieval(query=query, hits=hits[:limit])


def create_echo(
    corpus: Corpus,
    config: Mapping[str, object],
) -> EchoRetriever:
    return EchoRetriever(corpus, config)


def create_different_echo(
    corpus: Corpus,
    config: Mapping[str, object],
) -> EchoRetriever:
    return EchoRetriever(corpus, config)


def test_registry_views_when_lab_method_is_not_servable_exposes_it_only_for_eval() -> (
    None
):
    registry = RetrieverRegistry()
    registry.register(
        "bm25",
        create_echo,
        config={"score": 2.5},
        servable=True,
    )
    registry.register(
        "colbert-lab",
        create_echo,
        config={"score": 9.0},
        servable=False,
    )

    assert tuple(registry.retrievable) == ("bm25", "colbert-lab")
    assert tuple(registry.servable) == ("bm25",)
    assert "colbert-lab" in registry.retrievable
    assert "colbert-lab" not in registry.servable
    with pytest.raises(KeyError, match="colbert-lab"):
        registry.servable.create("colbert-lab", MemoryCorpus())


def test_registry_create_when_method_is_allowed_binds_identity_and_delegates() -> None:
    registry = RetrieverRegistry()
    registration = registry.register(
        "bm25",
        create_echo,
        config={"score": 2.5},
        servable=True,
        implementation_id="tests:create_echo@1",
    )

    resolved = registry.servable.create("bm25", MemoryCorpus())

    assert resolved.method_id == "bm25"
    assert resolved.config == {"score": 2.5}
    assert resolved.fingerprint == registration.fingerprint("sha256:corpus-a")
    assert resolved.retrieve("도커", limit=1) == Retrieval(
        query="도커",
        hits=(
            Hit(
                doc_id=DocId("AI/post.md"),
                rank=1,
                score=2.5,
                text="body:AI/post.md",
            ),
        ),
    )


def test_registry_fingerprint_when_shared_registration_is_imported_matches() -> None:
    agent_registry = RetrieverRegistry()
    registration = agent_registry.register(
        "bm25",
        create_echo,
        config={"score": 2.5},
        servable=True,
        implementation_id="agent.retrieval.bm25:create@1",
    )
    eval_registry = agent_registry.copy()
    eval_registry.register(
        "colbert-lab",
        create_echo,
        config={"score": 4.0},
        servable=False,
    )

    corpus_fingerprint = "sha256:corpus-a"
    assert (
        agent_registry.servable.fingerprint("bm25", corpus_fingerprint)
        == eval_registry.retrievable.fingerprint("bm25", corpus_fingerprint)
        == registration.fingerprint(corpus_fingerprint)
    )


def test_registry_fingerprint_when_same_method_id_points_to_other_factory_differs() -> (
    None
):
    left = RetrieverRegistry()
    right = RetrieverRegistry()
    left.register("bm25", create_echo, config={"score": 2.5})
    right.register("bm25", create_different_echo, config={"score": 2.5})

    assert left.retrievable.fingerprint(
        "bm25", "sha256:corpus-a"
    ) != right.retrievable.fingerprint("bm25", "sha256:corpus-a")


def test_registry_when_method_id_is_registered_twice_rejects_ambiguous_factory() -> (
    None
):
    registry = RetrieverRegistry()
    registry.register("bm25", create_echo, config={"score": 2.5})

    with pytest.raises(ValueError, match="already registered"):
        registry.register("bm25", create_different_echo, config={"score": 2.5})


def test_registration_when_caller_mutates_original_config_keeps_identity_unchanged() -> (
    None
):
    config = {"score": 2.5, "fields": ["title"]}
    registry = RetrieverRegistry()
    registration = registry.register("bm25", create_echo, config=config)
    before = registration.fingerprint("sha256:corpus-a")

    config["score"] = 999.0
    config["fields"].append("body")

    assert registration.config == {"score": 2.5, "fields": ["title"]}
    assert registration.fingerprint("sha256:corpus-a") == before


def test_registration_when_falsey_config_is_not_a_mapping_rejects() -> None:
    registry = RetrieverRegistry()

    with pytest.raises(TypeError, match="mapping"):
        registry.register("bm25", create_echo, config=[])  # type: ignore[arg-type]
