from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from agent.retrieval.fingerprint import retriever_fingerprint
from agent.retrieval.protocol import DocId, Hit, Retrieval
from agent.retrieval.registry import RetrieverRegistry

import blogeval.runner as runner_module
from blogeval.jsonio import canonical_json_bytes, json_checksum
from blogeval.runner import (
    EvaluationError,
    run_evaluation,
    verify_run_directory,
    write_run_artifacts,
)
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
            data_dependencies=("fixture:rankings",),
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


def _replace_complete_artifacts(artifacts, run) -> None:
    payloads, manifest_payload, _ = runner_module._artifact_payloads(run)
    for path, payload in payloads.items():
        (artifacts.directory / path).write_bytes(payload)
    artifacts.result_manifest.write_bytes(manifest_payload)


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

    first = write_run_artifacts(
        run,
        corpus=memory_corpus,
        output_root=tmp_path / "first",
        registry=_registry(),
    )
    second = write_run_artifacts(
        run,
        corpus=memory_corpus,
        output_root=tmp_path / "second",
        registry=_registry(),
    )

    assert run.run_id.startswith("sha256:")
    assert _tree_digest(first.directory) == _tree_digest(second.directory)
    assert first.run_json.read_bytes() == second.run_json.read_bytes()
    assert first.result_manifest.is_file()
    assert (
        verify_run_directory(
            first.directory,
            corpus=memory_corpus,
            dataset=known_dataset,
            registry=_registry(),
        ).result_digest
        == first.result_digest
    )
    leaderboard = first.leaderboard_markdown.read_text(encoding="utf-8")
    assert "## Known-item metrics" in leaderboard
    assert "## Topic metrics" in leaderboard
    assert "- Label status: **synthetic-only**" in leaderboard
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


def test_runner_classifies_oracle_in_sample_and_clean_data_dependencies(
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    registry = RetrieverRegistry()
    dependencies = {
        "clean": ("corpus:unrelated-holdout",),
        "in-sample": ("fixture:synthetic",),
        "oracle": ("artifact:fixture.json",),
    }
    for method_id, data_dependencies in dependencies.items():
        registry.register(
            method_id,
            RankedRetriever,
            implementation_id=f"tests:{method_id}@1",
            config={
                "rankings": {
                    "alpha": ["AI/alpha.md"],
                    "beta": ["AI/beta.md"],
                }
            },
            data_dependencies=data_dependencies,
            servable=False,
        )

    run = run_evaluation(
        corpus=memory_corpus,
        dataset=known_dataset,
        content_tree_sha="a" * 40,
        method_ids=("clean", "in-sample", "oracle"),
        cutoffs=(1,),
        registry=registry,
    )

    by_method = {method.method_id: method for method in run.methods}
    assert by_method["oracle"].evaluation_relation == "oracle-overlap"
    assert by_method["oracle"].overlap_sources == ("artifact:fixture.json",)
    assert by_method["in-sample"].evaluation_relation == "in-sample-overlap"
    assert by_method["in-sample"].overlap_sources == ("fixture:synthetic",)
    assert by_method["clean"].evaluation_relation == "clean-holdout"
    assert by_method["clean"].overlap_sources == ()


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
    artifacts = write_run_artifacts(
        run,
        corpus=memory_corpus,
        output_root=tmp_path,
        registry=_registry(),
    )
    artifacts.leaderboard_markdown.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(EvaluationError, match="checksum/size mismatch"):
        write_run_artifacts(
            run,
            corpus=memory_corpus,
            output_root=tmp_path,
            registry=_registry(),
        )


def test_verify_run_rejects_extra_and_partial_result_directories(
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
    artifacts = write_run_artifacts(
        run,
        corpus=memory_corpus,
        output_root=tmp_path,
        registry=_registry(),
    )
    extra = artifacts.directory / "extra.txt"
    extra.write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(EvaluationError, match="file inventory mismatch"):
        verify_run_directory(
            artifacts.directory,
            corpus=memory_corpus,
            dataset=known_dataset,
            registry=_registry(),
        )
    extra.unlink()
    artifacts.metrics_svg.unlink()
    with pytest.raises(EvaluationError, match="file inventory mismatch"):
        verify_run_directory(
            artifacts.directory,
            corpus=memory_corpus,
            dataset=known_dataset,
            registry=_registry(),
        )


def test_verify_run_recomputes_metrics_even_when_tamper_manifest_is_resealed(
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
    artifacts = write_run_artifacts(
        run,
        corpus=memory_corpus,
        output_root=tmp_path,
        registry=_registry(),
    )
    record = json.loads(artifacts.run_json.read_text(encoding="utf-8"))
    record["methods"][0]["metrics"]["metrics"]["mrr@1"] = 0.0
    artifacts.run_json.write_bytes(canonical_json_bytes(record))

    manifest = json.loads(artifacts.result_manifest.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        payload = (artifacts.directory / item["path"]).read_bytes()
        item["bytes"] = len(payload)
        item["sha256"] = json_checksum(payload)
    manifest["result_digest"] = json_checksum(
        canonical_json_bytes(
            {
                "files": manifest["files"],
                "schema": "blogeval-result-digest-v1",
            }
        )
    )
    artifacts.result_manifest.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(
        EvaluationError, match="do not regenerate from recorded rankings"
    ):
        verify_run_directory(
            artifacts.directory,
            corpus=memory_corpus,
            dataset=known_dataset,
            registry=_registry(),
        )


def test_verify_run_rejects_registration_identity_drift_with_old_fingerprint(
    tmp_path: Path,
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    registry = _registry()
    run = run_evaluation(
        corpus=memory_corpus,
        dataset=known_dataset,
        content_tree_sha="a" * 40,
        method_ids=("method-a",),
        cutoffs=(1,),
        registry=registry,
    )
    artifacts = write_run_artifacts(
        run,
        corpus=memory_corpus,
        output_root=tmp_path,
        registry=registry,
    )
    method = run.methods[0]
    forged_method = replace(
        method,
        implementation_id="attacker:replacement@1",
        identity_config={"rankings": {"alpha": [], "beta": []}},
    )
    forged_run = replace(run, methods=(forged_method,))
    assert forged_run.run_id == run.run_id
    assert forged_method.fingerprint == method.fingerprint
    _replace_complete_artifacts(artifacts, forged_run)

    with pytest.raises(EvaluationError, match="implementation_id.*registration"):
        verify_run_directory(
            artifacts.directory,
            corpus=memory_corpus,
            dataset=known_dataset,
            registry=registry,
        )


def test_verify_run_rejects_self_consistent_unregistered_method_identity(
    tmp_path: Path,
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    registry = _registry()
    run = run_evaluation(
        corpus=memory_corpus,
        dataset=known_dataset,
        content_tree_sha="a" * 40,
        method_ids=("method-a",),
        cutoffs=(1,),
        registry=registry,
    )
    artifacts = write_run_artifacts(
        run,
        corpus=memory_corpus,
        output_root=tmp_path,
        registry=registry,
    )
    method = run.methods[0]
    forged_method_id = "attacker-method"
    forged_implementation_id = "attacker:method@1"
    forged_config = {"rankings": {"alpha": [], "beta": []}}
    forged_fingerprint = retriever_fingerprint(
        method_id=forged_method_id,
        implementation_id=forged_implementation_id,
        config=forged_config,
        corpus_fingerprint=known_dataset.corpus.fingerprint,
    )
    forged_method = replace(
        method,
        method_id=forged_method_id,
        implementation_id=forged_implementation_id,
        identity_config=forged_config,
        fingerprint=forged_fingerprint,
    )
    forged_run_id = runner_module._run_id(
        dataset=known_dataset,
        cutoffs=run.cutoffs,
        identities=(
            {
                "data_dependencies": list(forged_method.data_dependencies),
                "evaluation_relation": forged_method.evaluation_relation,
                "fingerprint": forged_fingerprint,
                "method_id": forged_method_id,
                "overlap_sources": list(forged_method.overlap_sources),
            },
        ),
        provenance=run.provenance,
    )
    forged_run = replace(
        run,
        run_id=forged_run_id,
        methods=(forged_method,),
    )
    assert forged_run.run_id != run.run_id
    _replace_complete_artifacts(artifacts, forged_run)

    with pytest.raises(EvaluationError, match="not registered"):
        verify_run_directory(
            artifacts.directory,
            corpus=memory_corpus,
            dataset=known_dataset,
            registry=registry,
        )


def test_concurrent_identical_writers_commit_one_complete_directory(
    tmp_path: Path,
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
    with ThreadPoolExecutor(max_workers=8) as executor:
        artifacts = tuple(
            executor.map(
                lambda _: write_run_artifacts(
                    run,
                    corpus=memory_corpus,
                    output_root=tmp_path,
                    registry=_registry(),
                ),
                range(16),
            )
        )

    assert len({item.result_digest for item in artifacts}) == 1
    assert len({item.directory for item in artifacts}) == 1
    verified = verify_run_directory(
        artifacts[0].directory,
        corpus=memory_corpus,
        dataset=known_dataset,
        registry=_registry(),
    )
    assert verified.result_digest == artifacts[0].result_digest
    assert sorted(path.name for path in artifacts[0].directory.iterdir()) == [
        "leaderboard.md",
        "manifest.json",
        "metrics.svg",
        "per-query.md",
        "run.json",
    ]


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
            data_dependencies=("fixture:rankings",),
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
        data_dependencies=("fixture:rankings",),
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
        data_dependencies=("fixture:rankings",),
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
