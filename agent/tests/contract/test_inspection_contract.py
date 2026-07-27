"""Public ``syshin.rag.inspection.v1`` retrieval payload contract."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from agent.inspection import (
    MAX_EVENT_BYTES,
    InspectionContractError,
    normalize_retrieval_inspection,
)

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "protocol"
    / "fixtures"
    / "inspection-events-v1.json"
)


def _fixture_document() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _fixture() -> dict[str, object]:
    fixture = _fixture_document()
    records = fixture["records"]
    assert isinstance(records, list) and len(records) == 1
    event = records[0]["payload"]
    return event["params"]["data"]["payload"]


def _encoded_size(payload: object) -> int:
    return len(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _payload_at_encoded_boundary(target: int) -> dict[str, object]:
    payload = _fixture()
    template = payload["sources"][0]
    payload["hit_count"] = 50
    payload["sources"] = [
        {
            **deepcopy(template),
            "doc_id": f"AI/{rank:02d}-.md",
            "rank": rank,
            "title": "가" * 200,
        }
        for rank in range(1, 51)
    ]
    payload["sources_truncated"] = False
    payload["stages"][0]["application"]["output_count"] = 50

    remaining = target - _encoded_size(payload)
    assert remaining >= 0
    for source in payload["sources"]:
        doc_id = source["doc_id"]
        capacity = 1_000 - len(doc_id)
        added = min(capacity, remaining)
        source["doc_id"] = f"{doc_id[:-3]}{'x' * added}.md"
        remaining -= added
    assert remaining == 0
    assert _encoded_size(payload) == target
    return payload


def test_protocol_fixture_is_one_live_only_retrieval_without_replay_claim() -> None:
    fixture = _fixture_document()

    assert fixture["expectations"]["delivery"] == {
        "durable_replay": False,
        "mode": "live-run-only",
    }
    assert "replay" not in fixture["expectations"]
    assert len(fixture["records"]) == 1
    event = fixture["records"][0]["payload"]
    assert event["method"] == "custom"
    assert event["params"]["data"]["name"] == "syshin.rag.inspection.v1"
    assert event["params"]["data"]["payload"]["kind"] == "retrieval"
    assert event["params"]["data"]["payload"]["delivery"] == "live-run-only"


def test_inspection_v1_fixture_round_trips_as_exact_canonical_payload() -> None:
    fixture = _fixture()

    assert normalize_retrieval_inspection(fixture) == fixture
    assert _encoded_size(fixture) < MAX_EVENT_BYTES


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload.update({"system_prompt": "NEVER_PUBLIC"}),
            "unknown fields",
        ),
        (
            lambda payload: payload["sources"][0].update(
                {"text": "RAW_HIDDEN_CONTENT"}
            ),
            "unknown fields",
        ),
        (
            lambda payload: payload["sources"][0]["provenance"].update(
                {"owner_id": "owner-secret"}
            ),
            "unknown fields",
        ),
        (
            lambda payload: payload["sources"][0].update({"doc_id": "../private.md"}),
            "canonical published DocId",
        ),
        (
            lambda payload: payload.update({"kind": "quickjs"}),
            "kind must be 'retrieval'",
        ),
        (
            lambda payload: payload["sources"][0]["provenance"].update(
                {"corpus_revision": "sha256:" + ("c" * 64)}
            ),
            "must equal corpus_revision",
        ),
        (
            lambda payload: payload["stages"][0]["application"].update(
                {"output_count": 0}
            ),
            "must equal hit_count",
        ),
        (
            lambda payload: payload["stages"].append(deepcopy(payload["stages"][0])),
            "exactly one observed retriever stage",
        ),
        (
            lambda payload: payload.update({"query": "unsafe\ud800"}),
            "Unicode scalar",
        ),
        (
            lambda payload: payload["sources"][0].update({"score": 10**10_000}),
            "finite number",
        ),
    ],
    ids=[
        "system-prompt",
        "raw-source-text",
        "owner-identity",
        "noncanonical-source",
        "unimplemented-capability-kind",
        "foreign-provenance",
        "false-stage-application",
        "multiple-stages",
        "unpaired-surrogate",
        "numeric-overflow",
    ],
)
def test_inspection_v1_rejects_unbounded_hidden_or_untruthful_fields(
    mutate,
    message: str,
) -> None:
    payload = deepcopy(_fixture())
    mutate(payload)

    with pytest.raises(InspectionContractError, match=message):
        normalize_retrieval_inspection(payload)


def test_inspection_v1_caps_ranked_source_prefix_at_fifty() -> None:
    payload = _fixture()
    template = payload["sources"][0]
    payload["hit_count"] = 51
    payload["sources"] = [
        {
            **deepcopy(template),
            "doc_id": f"AI/source-{rank:02d}.md",
            "rank": rank,
        }
        for rank in range(1, 51)
    ]
    payload["sources_truncated"] = True
    payload["stages"][0]["application"]["output_count"] = 51

    normalized = normalize_retrieval_inspection(payload)

    assert len(normalized["sources"]) == 50
    assert normalized["sources_truncated"] is True

    payload["sources"].append(
        {
            **deepcopy(template),
            "doc_id": "AI/source-51.md",
            "rank": 51,
        }
    )
    with pytest.raises(InspectionContractError, match="at most 50"):
        normalize_retrieval_inspection(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"tool_call_id": "call id"}),
        lambda payload: (
            payload.update({"method_id": "unsafe/method"}),
            payload["method_identity"].update({"method_id": "unsafe/method"}),
            payload["stages"][0].update({"stage_id": "unsafe/method"}),
        ),
        lambda payload: (
            payload["method_identity"].update(
                {"implementation_id": "unsafe implementation@1"}
            ),
            payload["stages"][0].update(
                {"implementation_id": "unsafe implementation@1"}
            ),
        ),
        lambda payload: payload["sources"][0].update({"chunk_id": "bad chunk"}),
    ],
    ids=["tool-call", "method", "implementation", "chunk"],
)
def test_inspection_v1_rejects_unsafe_opaque_identifiers(mutate) -> None:
    payload = _fixture()
    mutate(payload)

    with pytest.raises(InspectionContractError, match="safe identifier"):
        normalize_retrieval_inspection(payload)


def test_inspection_v1_accepts_exact_64kib_and_rejects_one_byte_more() -> None:
    payload = _payload_at_encoded_boundary(MAX_EVENT_BYTES)

    normalized = normalize_retrieval_inspection(payload)

    assert _encoded_size(normalized) == MAX_EVENT_BYTES
    overflow = deepcopy(payload)
    source = next(item for item in overflow["sources"] if len(item["doc_id"]) < 1_000)
    source["doc_id"] = f"{source['doc_id'][:-3]}x.md"
    assert _encoded_size(overflow) == MAX_EVENT_BYTES + 1
    with pytest.raises(InspectionContractError, match="at most 65536 bytes"):
        normalize_retrieval_inspection(overflow)
