"""Behavioral contract tests for the dependency-free retrieval boundary."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections.abc import Mapping
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


def test_hit_when_chunk_id_is_not_a_string_rejects_before_serialization() -> None:
    with pytest.raises(TypeError, match="chunk_id.*string"):
        Hit(
            doc_id=DocId("AI/post.md"),
            chunk_id=object(),  # type: ignore[arg-type]
            rank=1,
            score=1.0,
        )


def test_hit_metadata_when_nested_sources_mutate_keeps_immutable_snapshot() -> None:
    tags: list[object] = ["rag", {"language": "ko"}]
    metrics: dict[str, object] = {"coverage": 0.5}
    hit = Hit(
        doc_id=DocId("AI/post.md"),
        rank=1,
        score=4.25,
        metadata={"tags": tags, "metrics": metrics},
    )

    tags.append("changed")
    metrics["coverage"] = 1.0

    frozen_tags = hit.metadata["tags"]
    frozen_metrics = hit.metadata["metrics"]
    assert frozen_tags == ("rag", {"language": "ko"})
    assert isinstance(frozen_metrics, Mapping)
    assert frozen_metrics == {"coverage": 0.5}
    with pytest.raises(TypeError):
        frozen_tags[0] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        frozen_metrics["coverage"] = 1.0  # type: ignore[index]


@pytest.mark.parametrize(
    "metadata",
    [
        {"bad": float("nan")},
        {"bad": float("inf")},
        {"bad": object()},
        {"bad": {"set-value"}},
        {1: "non-string key"},
        {"nested": {1: "non-string key"}},
    ],
)
def test_hit_metadata_when_value_is_not_portable_json_rejects(
    metadata: object,
) -> None:
    with pytest.raises((TypeError, ValueError), match="JSON|finite|string"):
        Hit(
            doc_id=DocId("AI/post.md"),
            rank=1,
            score=1.0,
            metadata=metadata,  # type: ignore[arg-type]
        )


def test_hit_metadata_when_value_is_cyclic_rejects() -> None:
    metadata: dict[str, object] = {}
    metadata["self"] = metadata

    with pytest.raises(ValueError, match="cyclic JSON"):
        Hit(
            doc_id=DocId("AI/post.md"),
            rank=1,
            score=1.0,
            metadata=metadata,
        )


def test_retrieval_as_dict_when_metadata_is_nested_returns_independent_json_copy() -> (
    None
):
    hit = Hit(
        doc_id=DocId("AI/한국어.md"),
        chunk_id="intro",
        rank=1,
        score=-3.5,
        text="본문",
        metadata={
            "tags": ["rag", "한국어"],
            "details": {"published": True, "aliases": None},
        },
    )
    retrieval = Retrieval(query="검색", hits=(hit,))

    payload = retrieval.as_dict()

    assert payload == {
        "query": "검색",
        "hits": [
            {
                "doc_id": "AI/한국어.md",
                "rank": 1,
                "score": -3.5,
                "chunk_id": "intro",
                "text": "본문",
                "metadata": {
                    "tags": ["rag", "한국어"],
                    "details": {"published": True, "aliases": None},
                },
            }
        ],
    }
    assert (
        json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False)) == payload
    )

    payload["hits"][0]["metadata"]["tags"].append("mutated")
    assert hit.as_dict()["metadata"]["tags"] == ["rag", "한국어"]


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


@pytest.mark.parametrize("ranks", [(1, 3), (2, 3)])
def test_retrieval_when_sorted_ranks_have_a_gap_or_do_not_start_at_one_rejects(
    ranks: tuple[int, int],
) -> None:
    with pytest.raises(ValueError, match=r"contiguous.*1\.\.N"):
        Retrieval(
            query="gap",
            hits=tuple(
                Hit(
                    doc_id=DocId(f"AI/{rank}.md"),
                    rank=rank,
                    score=float(rank),
                )
                for rank in ranks
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


def test_protocol_import_when_site_packages_are_disabled_stays_runtime_independent() -> (
    None
):
    source_root = Path(__file__).parents[2] / "src"
    script = "\n".join(
        (
            "import sys",
            f"sys.path.insert(0, {str(source_root)!r})",
            "from agent.retrieval.protocol import DocId",
            "assert DocId('AI/post.md') == 'AI/post.md'",
            "assert 'agent.graph' not in sys.modules",
            "assert 'deepagents' not in sys.modules",
            "assert 'rank_bm25' not in sys.modules",
        )
    )

    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
