from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from agent.retrieval.protocol import DocId, Hit, Retrieval
from agent.retrieval.registry import RetrieverRegistry

from blogeval.runner import EvaluationError, run_evaluation, write_run_artifacts
from conftest import MemoryCorpus, RankedRetriever


def _registry() -> RetrieverRegistry:
    registry = RetrieverRegistry()
    configurations = {
        "method-a": {
            "rankings": {
                "alpha": ["AI/alpha.md", "AI/beta.md"],
                "beta": ["AI/beta.md"],
            }
        },
        "method-b": {
            "rankings": {
                "alpha": ["AI/beta.md", "AI/alpha.md"],
                "beta": [],
            }
        },
        "method-c": {
            "rankings": {
                "alpha": [],
                "beta": ["AI/alpha.md", "AI/beta.md"],
            }
        },
    }
    for method_id, config in configurations.items():
        registry.register(
            method_id,
            RankedRetriever,
            implementation_id=f"tests:{method_id}@1",
            config=config,
            servable=False,
        )
    return registry


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(path.rglob("*")):
        if file.is_file():
            digest.update(file.relative_to(path).as_posix().encode())
            digest.update(b"\0")
            digest.update(file.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def test_runner_writes_byte_reproducible_json_markdown_and_svg(
    tmp_path: Path,
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    run = run_evaluation(
        corpus=memory_corpus,
        dataset=known_dataset,
        content_tree_sha="a" * 40,
        method_ids=("method-a", "method-b", "method-c"),
        cutoffs=(1, 2),
        registry=_registry(),
    )

    first = write_run_artifacts(run, output_root=tmp_path / "first")
    second = write_run_artifacts(run, output_root=tmp_path / "second")

    assert run.run_id.startswith("sha256:")
    assert _tree_digest(first.directory) == _tree_digest(second.directory)
    assert first.run_json.read_bytes() == second.run_json.read_bytes()
    leaderboard = first.leaderboard_markdown.read_text(encoding="utf-8")
    assert "## Known-item metrics" in leaderboard
    assert "## Topic metrics" in leaderboard
    assert "owner-reviewed" in leaderboard
    assert "nDCG" not in leaderboard
    assert "source of record is run.json" in first.metrics_svg.read_text(
        encoding="utf-8"
    )


def test_runner_records_rankings_and_method_fingerprints(
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    run = run_evaluation(
        corpus=memory_corpus,
        dataset=known_dataset,
        content_tree_sha="a" * 40,
        method_ids=("method-a",),
        cutoffs=(1, 2),
        registry=_registry(),
    )

    method = run.methods[0]
    assert method.method_id == "method-a"
    assert method.fingerprint.startswith("sha256:")
    assert method.implementation_id == "tests:method-a@1"
    assert method.metrics.values == {
        "coverage": 1.0,
        "hit@1": 1.0,
        "hit@2": 1.0,
        "mrr@1": 1.0,
        "mrr@2": 1.0,
    }
    assert [tuple(map(str, item.retrieved_doc_ids)) for item in method.queries] == [
        ("AI/alpha.md", "AI/beta.md"),
        ("AI/beta.md",),
    ]
    assert run.as_dict()["provenance"] == run.provenance.as_dict()


def test_result_store_refuses_to_replace_same_run_id_with_different_bytes(
    tmp_path: Path,
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    run = run_evaluation(
        corpus=memory_corpus,
        dataset=known_dataset,
        content_tree_sha="a" * 40,
        method_ids=("method-a",),
        cutoffs=(1,),
        registry=_registry(),
    )
    artifacts = write_run_artifacts(run, output_root=tmp_path)
    artifacts.leaderboard_markdown.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(OSError, match="refusing to replace non-identical"):
        write_run_artifacts(run, output_root=tmp_path)


def test_run_id_changes_when_registered_method_config_changes(
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    first_registry = RetrieverRegistry()
    second_registry = RetrieverRegistry()
    for registry, ranking in (
        (first_registry, ["AI/alpha.md", "AI/beta.md"]),
        (second_registry, ["AI/beta.md", "AI/alpha.md"]),
    ):
        registry.register(
            "method",
            RankedRetriever,
            implementation_id="tests:method@1",
            config={"rankings": {"alpha": ranking, "beta": ["AI/beta.md"]}},
            servable=False,
        )

    first = run_evaluation(
        corpus=memory_corpus,
        dataset=known_dataset,
        content_tree_sha="a" * 40,
        method_ids=("method",),
        cutoffs=(1,),
        registry=first_registry,
    )
    second = run_evaluation(
        corpus=memory_corpus,
        dataset=known_dataset,
        content_tree_sha="a" * 40,
        method_ids=("method",),
        cutoffs=(1,),
        registry=second_registry,
    )

    assert first.methods[0].fingerprint != second.methods[0].fingerprint
    assert first.run_id != second.run_id


class OutOfCorpusTailRetriever:
    def __init__(self, _corpus, _config) -> None:
        pass

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        del limit
        return Retrieval(
            query=query,
            hits=(
                Hit(doc_id=DocId("AI/alpha.md"), rank=1, score=None),
                Hit(doc_id=DocId("ghost.md"), rank=2, score=None),
            ),
        )


def test_runner_rejects_out_of_corpus_doc_even_beyond_evaluation_cutoff(
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    registry = RetrieverRegistry()
    registry.register(
        "method",
        OutOfCorpusTailRetriever,
        implementation_id="tests:outside-corpus@1",
        servable=False,
    )

    with pytest.raises(EvaluationError, match="outside the verified corpus.*ghost.md"):
        run_evaluation(
            corpus=memory_corpus,
            dataset=known_dataset,
            content_tree_sha="a" * 40,
            method_ids=("method",),
            cutoffs=(1,),
            registry=registry,
        )


class QueryMismatchRetriever:
    def __init__(self, _corpus, _config) -> None:
        pass

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        del limit
        return Retrieval(query=f"{query}-changed")


def test_runner_rejects_retriever_query_mismatch(
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    registry = RetrieverRegistry()
    registry.register(
        "method",
        QueryMismatchRetriever,
        implementation_id="tests:query-mismatch@1",
        servable=False,
    )

    with pytest.raises(EvaluationError, match="returned query.*alpha-changed"):
        run_evaluation(
            corpus=memory_corpus,
            dataset=known_dataset,
            content_tree_sha="a" * 40,
            method_ids=("method",),
            cutoffs=(1,),
            registry=registry,
        )
