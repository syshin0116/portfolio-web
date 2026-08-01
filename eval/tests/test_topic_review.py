from __future__ import annotations

import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from agent.retrieval.protocol import DocId
from agent.retrieval.registry import RetrieverRegistry

from blogeval.cli import _require_committed_topic_review
from blogeval.datasets import DatasetError, DatasetKind, LabelStatus
from blogeval.jsonio import canonical_json_bytes, json_checksum
from blogeval.runner import run_evaluation
from blogeval.topic_review import (
    CandidateJudgement,
    TopicReviewError,
    TopicReviewStatus,
    finalize_topic_queryset,
    generate_topic_review,
    parse_topic_review,
    parse_topic_seed,
    seal_topic_review,
    verify_topic_review,
    write_topic_review_once,
)
from conftest import MemoryCorpus, RankedRetriever

METHOD_IDS = ("method-a", "method-b")
TEST_REVIEW_REF = "git:" + "a" * 40


def _seed():
    value = {
        "candidate_generation": {
            "candidate_limit_per_method": 1,
            "method_ids": list(METHOD_IDS),
        },
        "dataset_id": "topic-smoke-v1",
        "queries": [
            {"query": "alpha topic", "query_id": "topic-alpha"},
            {"query": "beta topic", "query_id": "topic-beta"},
        ],
        "schema": "blogeval-topic-seed-v1",
    }
    payload = canonical_json_bytes(value)
    return parse_topic_seed(value, checksum=json_checksum(payload))


def _registry(*, drift: bool = False) -> RetrieverRegistry:
    registry = RetrieverRegistry()
    rankings = {
        "alpha topic": ["AI/alpha.md", "AI/beta.md"],
        "beta topic": ["AI/beta.md", "Dev/gamma.md"],
    }
    registry.register(
        "method-a",
        RankedRetriever,
        implementation_id="tests:topic-method-a@2"
        if drift
        else "tests:topic-method-a@1",
        config={"rankings": rankings},
        data_dependencies=("corpus:published-markdown",),
        servable=False,
    )
    registry.register(
        "method-b",
        RankedRetriever,
        implementation_id="tests:topic-method-b@1",
        config={
            "rankings": {
                "alpha topic": ["Dev/gamma.md", "AI/alpha.md"],
                "beta topic": ["AI/alpha.md", "AI/beta.md"],
            }
        },
        data_dependencies=("corpus:published-markdown",),
        servable=False,
    )
    return registry


def _pending_review(memory_corpus: MemoryCorpus):
    return generate_topic_review(
        corpus=memory_corpus,
        seed=_seed(),
        content_tree_sha="a" * 40,
        registry=_registry(),
    )


def _completed_review_value(memory_corpus: MemoryCorpus) -> dict[str, object]:
    value = deepcopy(_pending_review(memory_corpus).as_dict())
    for query in value["queries"]:
        query["candidate_pool_complete"] = True
        for index, candidate in enumerate(query["candidates"]):
            candidate["judgement"] = "relevant" if index == 0 else "not-relevant"

    first_candidates = {item["doc_id"] for item in value["queries"][0]["candidates"]}
    extra = next(
        str(doc_id)
        for doc_id in memory_corpus.doc_ids()
        if str(doc_id) not in first_candidates
    )
    value["queries"][0]["additional_relevant_doc_ids"] = [extra]
    return value


def test_topic_review_generation_is_byte_stable_and_blinds_method_ranks(
    memory_corpus: MemoryCorpus,
) -> None:
    first = _pending_review(memory_corpus)
    second = generate_topic_review(
        corpus=memory_corpus,
        seed=_seed(),
        content_tree_sha="a" * 40,
        registry=_registry(),
    )

    assert canonical_json_bytes(first.as_dict()) == canonical_json_bytes(
        second.as_dict()
    )
    assert first.labels.status is TopicReviewStatus.PENDING
    assert [item.method_id for item in first.candidate_generation.methods] == [
        "method-a",
        "method-b",
    ]
    assert [
        {candidate.doc_id for candidate in query.candidates} for query in first.queries
    ] == [
        {DocId("AI/alpha.md"), DocId("Dev/gamma.md")},
        {DocId("AI/alpha.md"), DocId("AI/beta.md")},
    ]
    assert all(
        candidate.judgement is CandidateJudgement.PENDING
        for query in first.queries
        for candidate in query.candidates
    )
    candidate_keys = set(first.as_dict()["queries"][0]["candidates"][0])
    assert candidate_keys == {"blind_id", "doc_id", "judgement"}


def test_topic_review_generation_never_overwrites_manual_progress(
    memory_corpus: MemoryCorpus,
    tmp_path: Path,
) -> None:
    output = tmp_path / "topic.review.json"
    pending = _pending_review(memory_corpus)
    write_topic_review_once(output, pending)
    write_topic_review_once(output, pending)

    completed_value = _completed_review_value(memory_corpus)
    completed = parse_topic_review(
        completed_value,
        checksum=json_checksum(canonical_json_bytes(completed_value)),
    )
    with pytest.raises(TopicReviewError, match="refusing to overwrite"):
        write_topic_review_once(output, completed)


def test_owner_seal_input_must_match_the_referenced_ancestor_commit(
    memory_corpus: MemoryCorpus,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    review_path = workspace / "eval" / "querysets" / "topic.review.json"
    review_path.parent.mkdir(parents=True)
    completed_value = _completed_review_value(memory_corpus)
    payload = canonical_json_bytes(completed_value)
    review_path.write_bytes(payload)
    commands = (
        ("git", "init", "-q"),
        ("git", "add", "eval/querysets/topic.review.json"),
        (
            "git",
            "-c",
            "user.name=Topic Review Test",
            "-c",
            "user.email=topic-review@example.invalid",
            "commit",
            "-qm",
            "pending review",
        ),
    )
    for command in commands:
        subprocess.run(command, cwd=workspace, check=True)
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    _require_committed_topic_review(
        workspace_root=workspace,
        review_path=review_path,
        review_ref=f"git:{commit}",
        expected_payload=payload,
    )
    with pytest.raises(DatasetError, match="exact pending review payload"):
        _require_committed_topic_review(
            workspace_root=workspace,
            review_path=review_path,
            review_ref=f"git:{commit}",
            expected_payload=payload + b" ",
        )


def test_topic_seed_rejects_an_unstable_candidate_policy() -> None:
    value = _seed().as_dict()
    value["candidate_generation"]["method_ids"] = ["method-b", "method-a"]

    with pytest.raises(TopicReviewError, match="must be sorted and unique"):
        parse_topic_seed(value, checksum="sha256:" + "0" * 64)


def test_topic_review_parser_rejects_forged_or_stale_review_claims(
    memory_corpus: MemoryCorpus,
) -> None:
    value = _pending_review(memory_corpus).as_dict()
    value["labels"]["review"] = {
        "review_ref": TEST_REVIEW_REF,
        "reviewed_at": "2026-08-01",
        "reviewer": "@syshin0116",
    }
    with pytest.raises(TopicReviewError, match="pending.*review provenance"):
        parse_topic_review(value, checksum="sha256:" + "0" * 64)

    completed = _completed_review_value(memory_corpus)
    completed["labels"] = {
        "review": {
            "review_ref": TEST_REVIEW_REF,
            "reviewed_at": "2026-08-01",
            "reviewer": "@syshin0116",
        },
        "reviewed_payload_checksum": "sha256:" + "0" * 64,
        "status": "owner-reviewed",
    }
    with pytest.raises(TopicReviewError, match="checksum the exact review payload"):
        parse_topic_review(completed, checksum="sha256:" + "0" * 64)


def test_topic_review_seal_rejects_pending_judgements_and_incomplete_pool(
    memory_corpus: MemoryCorpus,
) -> None:
    review = _pending_review(memory_corpus)
    with pytest.raises(TopicReviewError, match="pending candidate judgements"):
        seal_topic_review(
            review,
            reviewer="@syshin0116",
            reviewed_at="2026-08-01",
            review_ref=TEST_REVIEW_REF,
        )

    value = _completed_review_value(memory_corpus)
    value["queries"][0]["candidate_pool_complete"] = False
    incomplete = parse_topic_review(
        value,
        checksum=json_checksum(canonical_json_bytes(value)),
    )
    with pytest.raises(TopicReviewError, match="pool completeness"):
        seal_topic_review(
            incomplete,
            reviewer="@syshin0116",
            reviewed_at="2026-08-01",
            review_ref=TEST_REVIEW_REF,
        )

    empty_value = _completed_review_value(memory_corpus)
    for query in empty_value["queries"]:
        query["additional_relevant_doc_ids"] = []
        for candidate in query["candidates"]:
            candidate["judgement"] = "not-relevant"
    empty = parse_topic_review(
        empty_value,
        checksum=json_checksum(canonical_json_bytes(empty_value)),
    )
    with pytest.raises(TopicReviewError, match="at least one relevant document"):
        seal_topic_review(
            empty,
            reviewer="@syshin0116",
            reviewed_at="2026-08-01",
            review_ref=TEST_REVIEW_REF,
        )


def test_reviewed_topic_manifest_finalizes_exact_multi_document_qrels(
    memory_corpus: MemoryCorpus,
) -> None:
    value = _completed_review_value(memory_corpus)
    completed = parse_topic_review(
        value,
        checksum=json_checksum(canonical_json_bytes(value)),
    )
    reviewed = seal_topic_review(
        completed,
        reviewer="@syshin0116",
        reviewed_at="2026-08-01",
        review_ref=TEST_REVIEW_REF,
    )
    verify_topic_review(
        reviewed,
        seed=_seed(),
        corpus=memory_corpus,
        content_tree_sha="a" * 40,
        registry=_registry(),
    )

    dataset = finalize_topic_queryset(
        reviewed,
        seed=_seed(),
        corpus=memory_corpus,
        content_tree_sha="a" * 40,
        registry=_registry(),
    )

    assert dataset.dataset_id == "topic-smoke-v1"
    assert dataset.kind is DatasetKind.TOPIC
    assert dataset.labels.status is LabelStatus.OWNER_REVIEWED
    assert dataset.labels.review is not None
    assert dataset.labels.review.reviewer == "@syshin0116"
    assert dataset.pooling is not None
    assert dataset.pooling.review_manifest_checksum == reviewed.checksum
    assert [method.method_id for method in dataset.pooling.methods] == [
        "method-a",
        "method-b",
    ]
    assert len(dataset.qrels[0].relevant_doc_ids) == 2
    assert dataset.qrels[0].relevant_doc_ids == tuple(
        sorted(dataset.qrels[0].relevant_doc_ids, key=str)
    )
    assert {evidence.source_doc_id for evidence in dataset.qrels[0].evidence} == set(
        dataset.qrels[0].relevant_doc_ids
    )
    dataset.require_reviewed_labels()

    run = run_evaluation(
        corpus=memory_corpus,
        dataset=dataset,
        content_tree_sha="a" * 40,
        method_ids=("method-a",),
        cutoffs=(1,),
        registry=_registry(),
    )
    assert run.methods[0].evaluation_relation == "candidate-pool-overlap"
    assert run.methods[0].overlap_sources == (
        f"retriever:method-a@{run.methods[0].fingerprint}",
    )


@pytest.mark.parametrize(
    ("reviewer", "review_ref", "message"),
    (
        ("@someone-else", TEST_REVIEW_REF, "reviewer must be exactly"),
        ("@syshin0116", "branch:main", "git:<40-hex-commit>"),
    ),
)
def test_topic_review_seal_rejects_unbound_owner_provenance(
    memory_corpus: MemoryCorpus,
    reviewer: str,
    review_ref: str,
    message: str,
) -> None:
    value = _completed_review_value(memory_corpus)
    completed = parse_topic_review(
        value,
        checksum=json_checksum(canonical_json_bytes(value)),
    )

    with pytest.raises(TopicReviewError, match=message):
        seal_topic_review(
            completed,
            reviewer=reviewer,
            reviewed_at="2026-08-01",
            review_ref=review_ref,
        )


def test_topic_review_verification_rejects_method_drift_and_outside_manual_labels(
    memory_corpus: MemoryCorpus,
) -> None:
    review = _pending_review(memory_corpus)
    with pytest.raises(TopicReviewError, match="candidate generation.*differs"):
        verify_topic_review(
            review,
            seed=_seed(),
            corpus=memory_corpus,
            content_tree_sha="a" * 40,
            registry=_registry(drift=True),
        )

    value = _completed_review_value(memory_corpus)
    value["queries"][0]["additional_relevant_doc_ids"] = ["Outside/ghost.md"]
    outside = parse_topic_review(
        value,
        checksum=json_checksum(canonical_json_bytes(value)),
    )
    with pytest.raises(TopicReviewError, match="outside the verified corpus"):
        verify_topic_review(
            outside,
            seed=_seed(),
            corpus=memory_corpus,
            content_tree_sha="a" * 40,
            registry=_registry(),
        )


def test_unreviewed_topic_manifest_cannot_materialize_a_publishable_queryset(
    memory_corpus: MemoryCorpus,
) -> None:
    with pytest.raises(TopicReviewError, match="owner-reviewed topic manifest"):
        finalize_topic_queryset(
            _pending_review(memory_corpus),
            seed=_seed(),
            corpus=memory_corpus,
            content_tree_sha="a" * 40,
            registry=_registry(),
        )


def test_committed_topic_seed_contains_queries_but_no_relevance_labels() -> None:
    from blogeval.topic_review import load_topic_seed

    seed = load_topic_seed(
        Path(__file__).parents[1] / "querysets" / "topic-smoke-v1.seed.json"
    )

    assert seed.dataset_id == "topic-smoke-v1"
    assert [query.query_id for query in seed.queries] == [
        "topic-llm-agent-architecture",
        "topic-pdf-text-extraction",
        "topic-rag-pipeline",
        "topic-agent-build",
        "topic-embedding-model-comparison",
        "topic-vector-db-performance",
    ]
    assert seed.candidate_limit_per_method == 20
    assert seed.method_ids == (
        "bm25",
        "bm25-field-weighted",
        "char-ngram",
        "dense-multilingual-e5-small",
        "rrf-bm25-char-ngram",
        "rrf-bm25-dense-multilingual-e5-small",
    )
    serialized = seed.as_dict()
    assert set(serialized) == {
        "candidate_generation",
        "dataset_id",
        "queries",
        "schema",
    }
    assert "labels" not in serialized
