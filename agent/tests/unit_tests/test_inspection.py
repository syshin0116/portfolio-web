"""Unit coverage for bounded inspection building and stream promotion."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langgraph.prebuilt import ToolRuntime

from agent.inspection import (
    INSPECTION_EVENT_NAME,
    MAX_EVENT_BYTES,
    InspectionContractError,
    InspectionEventTransformer,
    build_retrieval_inspection,
    emit_retrieval_inspection,
    normalize_retrieval_inspection,
)
from agent.retrieval.protocol import DocId, Hit, Retrieval

CORPUS_REVISION = "sha256:" + ("a" * 64)
METHOD_FINGERPRINT = "sha256:" + ("b" * 64)


class _Corpus:
    fingerprint = CORPUS_REVISION

    def doc_ids(self) -> tuple[DocId, ...]:
        return (
            DocId("AI/docker.md"),
            DocId("AI/langgraph.md"),
        )


class _Runtime:
    corpus = _Corpus()

    def entry(self, doc_id: DocId) -> SimpleNamespace:
        titles = {
            DocId("AI/docker.md"): "Docker Guide",
            DocId("AI/langgraph.md"): "L" * 350,
        }
        return SimpleNamespace(title=titles[doc_id])


class _Retriever:
    method_id = "bm25"
    fingerprint = METHOD_FINGERPRINT
    registration = SimpleNamespace(implementation_id="agent.retrieval.bm25:create@2")


def _payload() -> dict[str, object]:
    return build_retrieval_inspection(
        runtime=_Runtime(),
        retriever=_Retriever(),
        retrieval=Retrieval(
            query=("도커" * 600),
            hits=(
                Hit(
                    doc_id=DocId("AI/docker.md"),
                    rank=1,
                    score=4.25,
                    text="RAW_DOCUMENT_TEXT_MUST_NOT_STREAM",
                    metadata={
                        "prompt": "SYSTEM_PROMPT_MUST_NOT_STREAM",
                        "secret": "SECRET_MUST_NOT_STREAM",
                    },
                ),
                Hit(
                    doc_id=DocId("AI/langgraph.md"),
                    rank=2,
                    score=None,
                    chunk_id="header-1",
                    text="SECOND_RAW_DOCUMENT_TEXT",
                ),
            ),
        ),
        tool_call_id="call-search-001",
        elapsed_ms=4.125,
    )


def test_build_retrieval_inspection_exposes_only_bounded_public_provenance() -> None:
    payload = _payload()

    assert payload["schema_version"] == 1
    assert payload["delivery"] == "live-run-only"
    assert payload["query"] == ("도커" * 500)
    assert payload["query_truncated"] is True
    assert payload["method_identity"] == {
        "method_id": "bm25",
        "implementation_id": "agent.retrieval.bm25:create@2",
        "fingerprint": METHOD_FINGERPRINT,
    }
    assert payload["corpus_revision"] == CORPUS_REVISION
    assert payload["corpus_document_count"] == 2
    assert payload["hit_count"] == 2
    assert payload["sources"] == [
        {
            "doc_id": "AI/docker.md",
            "title": "Docker Guide",
            "rank": 1,
            "provenance": {
                "kind": "published-corpus",
                "corpus_revision": CORPUS_REVISION,
                "retriever_fingerprint": METHOD_FINGERPRINT,
            },
            "score": 4.25,
        },
        {
            "doc_id": "AI/langgraph.md",
            "title": "L" * 300,
            "rank": 2,
            "provenance": {
                "kind": "published-corpus",
                "corpus_revision": CORPUS_REVISION,
                "retriever_fingerprint": METHOD_FINGERPRINT,
            },
            "chunk_id": "header-1",
        },
    ]
    assert payload["stages"] == [
        {
            "stage_id": "bm25",
            "implementation_id": "agent.retrieval.bm25:create@2",
            "fingerprint": METHOD_FINGERPRINT,
            "elapsed_ms": 4.125,
            "application": {
                "status": "applied",
                "input_count": 1,
                "output_count": 2,
            },
        }
    ]
    serialized = repr(payload)
    for forbidden in (
        "RAW_DOCUMENT_TEXT",
        "SYSTEM_PROMPT",
        "SECRET_MUST_NOT_STREAM",
        "metadata",
        "quickjs",
        "subagent",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("query", "expected", "truncated"),
    [
        ("  도커\t검색\n", "  도커\t검색\n", False),
        ("가" * 1_001, "가" * 1_000, True),
    ],
    ids=["outer-whitespace-is-executed-input", "explicit-prefix-truncation"],
)
def test_build_retrieval_inspection_preserves_executed_query_prefix_exactly(
    query: str,
    expected: str,
    truncated: bool,
) -> None:
    payload = build_retrieval_inspection(
        runtime=_Runtime(),
        retriever=_Retriever(),
        retrieval=Retrieval(query=query),
        tool_call_id="call-query-001",
        elapsed_ms=0.0,
    )

    assert payload["query"] == expected
    assert payload["query_truncated"] is truncated


def test_build_retrieval_inspection_keeps_maximal_multibyte_source_prefix_under_64kib() -> (
    None
):
    doc_ids = tuple(DocId(f"AI/{rank:02d}-{'x' * 950}.md") for rank in range(1, 51))

    class _LargeCorpus:
        fingerprint = CORPUS_REVISION

        def doc_ids(self) -> tuple[DocId, ...]:
            return doc_ids

    class _LargeRuntime:
        corpus = _LargeCorpus()

        def entry(self, _doc_id: DocId) -> SimpleNamespace:
            return SimpleNamespace(title="가" * 300)

    retrieval = Retrieval(
        query="다국어 검색",
        hits=tuple(
            Hit(doc_id=doc_id, rank=rank, score=float(rank))
            for rank, doc_id in enumerate(doc_ids, start=1)
        ),
    )
    payload = build_retrieval_inspection(
        runtime=_LargeRuntime(),
        retriever=_Retriever(),
        retrieval=retrieval,
        tool_call_id="call-byte-budget-001",
        elapsed_ms=1.0,
    )

    sources = payload["sources"]
    assert 0 < len(sources) < 50
    assert [source["rank"] for source in sources] == list(range(1, len(sources) + 1))
    assert payload["sources_truncated"] is True
    assert (
        len(
            json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        <= MAX_EVENT_BYTES
    )

    next_hit = retrieval.hits[len(sources)]
    candidate = deepcopy(payload)
    candidate["sources"].append(
        {
            "doc_id": str(next_hit.doc_id),
            "title": "가" * 300,
            "rank": next_hit.rank,
            "score": next_hit.score,
            "provenance": {
                "kind": "published-corpus",
                "corpus_revision": CORPUS_REVISION,
                "retriever_fingerprint": METHOD_FINGERPRINT,
            },
        }
    )
    with pytest.raises(InspectionContractError, match="at most 65536 bytes"):
        normalize_retrieval_inspection(candidate)


def test_emit_retrieval_inspection_writer_failure_is_content_free_and_fail_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken_writer(_value: object) -> None:
        raise RuntimeError("SECRET writer detail must not be logged")

    runtime = ToolRuntime(
        state={},
        context=None,
        config={},
        stream_writer=broken_writer,
        tool_call_id="call-writer-001",
        store=None,
    )
    retrieval = Retrieval(
        query="PRIVATE QUERY",
        hits=(Hit(doc_id=DocId("AI/docker.md"), rank=1, score=1.0),),
    )

    with caplog.at_level(logging.WARNING, logger="agent.inspection"):
        emitted = emit_retrieval_inspection(
            runtime,
            runtime=_Runtime(),
            retriever=_Retriever(),
            retrieval=retrieval,
            elapsed_ms=1.0,
        )

    assert emitted is False
    record = caplog.records[-1]
    assert record.getMessage() == "rag_inspection_suppressed"
    assert record.inspection_suppression_reason == "writer-failed"
    assert record.inspection_suppression_count == 1
    public_log = repr(
        {
            "message": record.getMessage(),
            "reason": record.inspection_suppression_reason,
            "count": record.inspection_suppression_count,
        }
    )
    for forbidden in (
        "PRIVATE QUERY",
        "Docker Guide",
        "bm25",
        "SECRET writer detail",
    ):
        assert forbidden not in public_log


def test_inspection_transformer_promotes_exact_envelope_and_preserves_namespace() -> (
    None
):
    transformer = InspectionEventTransformer(("retrieval-researcher",))
    event = {
        "type": "event",
        "method": "custom",
        "params": {
            "namespace": ["retrieval-researcher:task-123"],
            "timestamp": 1,
            "data": {
                "name": INSPECTION_EVENT_NAME,
                "payload": _payload(),
            },
        },
    }

    assert transformer.process(event)
    assert event["method"] == f"custom:{INSPECTION_EVENT_NAME}"
    assert event["params"]["namespace"] == ["retrieval-researcher:task-123"]
    assert event["params"]["data"] == _payload()


def test_inspection_transformer_suppresses_marked_payload_with_unknown_secret() -> None:
    transformer = InspectionEventTransformer()
    payload = _payload()
    payload["chain_of_thought"] = "NEVER_STREAM"
    event = {
        "type": "event",
        "method": "custom",
        "params": {
            "namespace": [],
            "timestamp": 1,
            "data": {
                "name": INSPECTION_EVENT_NAME,
                "payload": payload,
            },
        },
    }

    assert transformer.process(event) is False
    assert event["method"] == "custom"


def test_inspection_transformer_leaves_unrelated_custom_event_untouched() -> None:
    transformer = InspectionEventTransformer()
    event = {
        "type": "event",
        "method": "custom",
        "params": {
            "namespace": [],
            "timestamp": 1,
            "data": {"name": "another.extension.v1", "payload": {"ok": True}},
        },
    }
    original = deepcopy(event)

    assert transformer.process(event)
    assert event == original
