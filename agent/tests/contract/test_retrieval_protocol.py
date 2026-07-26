"""Behavioral contract tests for the dependency-free retrieval boundary."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from agent.retrieval.protocol import (
    Corpus,
    DocId,
    Hit,
    Pipeline,
    Retrieval,
    Retriever,
    Stage,
)


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "/AI/post.md",
        "AI\\post.md",
        "AI/../post.md",
        "AI/./post.md",
        "AI//post.md",
        "AI/post.md/",
        "C:/AI/post.md",
        "C:AI/post.md",
    ],
)
def test_doc_id_when_path_is_not_canonical_content_relative_posix_rejects(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="content-relative POSIX"):
        DocId(value)


def test_hit_when_given_plain_path_coerces_it_to_validated_doc_id() -> None:
    hit = Hit(doc_id="AI/한국어 post.md", rank=1, score=-7.25)

    assert hit == Hit(doc_id=DocId("AI/한국어 post.md"), rank=1, score=-7.25)
    assert isinstance(hit.doc_id, DocId)


@pytest.mark.parametrize("rank", [True, 0, -1, 1.5])
def test_hit_when_rank_is_not_a_positive_integer_rejects(rank: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        Hit(doc_id=DocId("AI/post.md"), rank=rank, score=1.0)  # type: ignore[arg-type]


def test_retrieval_when_scores_disagree_with_rank_uses_rank_without_normalizing() -> (
    None
):
    retrieval = Retrieval(
        query="도커",
        hits=(
            Hit(doc_id=DocId("AI/low-score.md"), rank=1, score=-4.25),
            Hit(doc_id=DocId("AI/high-score.md"), rank=2, score=999.0),
        ),
    )

    assert tuple(hit.doc_id for hit in retrieval.hits) == (
        DocId("AI/low-score.md"),
        DocId("AI/high-score.md"),
    )
    assert tuple(hit.score for hit in retrieval.hits) == (-4.25, 999.0)


def test_retrieval_when_hits_arrive_out_of_order_canonicalizes_by_rank() -> None:
    retrieval = Retrieval(
        query="pipeline",
        hits=(
            Hit(doc_id=DocId("AI/third.md"), rank=3, score=100.0),
            Hit(doc_id=DocId("AI/first.md"), rank=1, score=1.0),
            Hit(doc_id=DocId("AI/second.md"), rank=2, score=50.0),
        ),
    )

    assert tuple(hit.rank for hit in retrieval.hits) == (1, 2, 3)


def test_doc_ids_when_multiple_chunks_hit_same_document_keeps_first_document_rank() -> (
    None
):
    retrieval = Retrieval(
        query="chunking",
        hits=(
            Hit(
                doc_id=DocId("AI/a.md"),
                chunk_id="a#intro",
                rank=1,
                score=0.1,
            ),
            Hit(doc_id=DocId("AI/b.md"), chunk_id="b#one", rank=2, score=50.0),
            Hit(
                doc_id=DocId("AI/a.md"),
                chunk_id="a#details",
                rank=3,
                score=100.0,
            ),
            Hit(doc_id=DocId("AI/c.md"), chunk_id="c#one", rank=4, score=-1.0),
        ),
    )

    assert retrieval.doc_ids() == (
        DocId("AI/a.md"),
        DocId("AI/b.md"),
        DocId("AI/c.md"),
    )
    assert retrieval.doc_ids(limit=2) == (
        DocId("AI/a.md"),
        DocId("AI/b.md"),
    )


def test_retrieval_when_two_hits_claim_same_rank_rejects_ambiguous_order() -> None:
    with pytest.raises(ValueError, match="unique"):
        Retrieval(
            query="ambiguous",
            hits=(
                Hit(doc_id=DocId("AI/a.md"), rank=1, score=1.0),
                Hit(doc_id=DocId("AI/b.md"), rank=1, score=2.0),
            ),
        )


def test_contracts_when_implemented_structurally_need_no_framework_base_class() -> None:
    class MemoryCorpus:
        fingerprint = "sha256:corpus"

        def doc_ids(self) -> tuple[DocId, ...]:
            return (DocId("AI/post.md"),)

        def read(self, doc_id: DocId) -> str:
            return f"content for {doc_id}"

    class StaticRetriever:
        def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
            return Retrieval(
                query=query,
                hits=(Hit(DocId("AI/post.md"), rank=1, score=3.0),)[:limit],
            )

    class FusionStage(StaticRetriever):
        # A stage can have fan-in without a mandatory single-upstream member.
        inputs = (StaticRetriever(), StaticRetriever())

    class RetrievalPipeline(StaticRetriever):
        stages = (StaticRetriever(), FusionStage())

    assert isinstance(MemoryCorpus(), Corpus)
    assert isinstance(StaticRetriever(), Retriever)
    assert isinstance(FusionStage(), Stage)
    assert isinstance(RetrievalPipeline(), Pipeline)


def test_protocol_module_when_imports_are_inspected_uses_only_stdlib() -> None:
    protocol_path = (
        Path(__file__).parents[2] / "src" / "agent" / "retrieval" / "protocol.py"
    )
    tree = ast.parse(protocol_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert imported_roots <= sys.stdlib_module_names | {"__future__"}
