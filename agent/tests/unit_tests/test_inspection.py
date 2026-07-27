"""Unit coverage for bounded inspection building and stream promotion."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from agent.inspection import (
    INSPECTION_EVENT_NAME,
    InspectionEventTransformer,
    build_retrieval_inspection,
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
    registration = SimpleNamespace(
        implementation_id="agent.retrieval.bm25:create@2"
    )


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


def test_inspection_transformer_promotes_exact_envelope_and_preserves_namespace() -> None:
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
