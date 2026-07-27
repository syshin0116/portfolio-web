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
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "inspection"
    / "retrieval-v1.json"
)


def _fixture() -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_inspection_v1_fixture_round_trips_as_exact_canonical_payload() -> None:
    fixture = _fixture()

    assert normalize_retrieval_inspection(fixture) == fixture
    assert (
        len(
            json.dumps(
                fixture,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        < MAX_EVENT_BYTES
    )


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
    ],
    ids=[
        "system-prompt",
        "raw-source-text",
        "owner-identity",
        "noncanonical-source",
        "unimplemented-capability-kind",
        "foreign-provenance",
        "false-stage-application",
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
