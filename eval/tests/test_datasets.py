from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent.retrieval.corpus import WIKILINK_SCHEMA
from agent.retrieval.protocol import DocId

from blogeval.datasets import (
    ALIAS_GENERATOR,
    DatasetError,
    DatasetKind,
    generate_known_item_alias_queryset,
    load_queryset,
    parse_queryset,
    validate_queryset_corpus,
)
from blogeval.jsonio import canonical_json_bytes
from conftest import MemoryCorpus


class ArtifactMemoryCorpus(MemoryCorpus):
    def __init__(self, documents, graph):
        super().__init__(documents)
        object.__setattr__(self, "_graph", graph)

    def read_artifact(self, path: str) -> bytes:
        if path != "wikilinks.json":
            raise KeyError(path)
        return canonical_json_bytes(self._graph)


def _graph(corpus: MemoryCorpus) -> dict[str, object]:
    return {
        "adjacency": {},
        "ambiguous_names": [],
        "corpus_fingerprint": corpus.fingerprint,
        "edge_count": 4,
        "excluded_links": [
            {
                "alias": "ambiguous",
                "candidates": ["AI/alpha.md", "AI/beta.md"],
                "reason": "ambiguous-target",
                "source_doc_id": "Dev/gamma.md",
                "target": "ambiguous",
            }
        ],
        "isolated_node_count": 0,
        "links": [
            {
                "alias": "Alpha",
                "source_doc_id": "AI/beta.md",
                "target": "alpha",
                "target_doc_id": "AI/alpha.md",
            },
            {
                "alias": "Alpha",
                "source_doc_id": "Dev/gamma.md",
                "target": "alpha",
                "target_doc_id": "AI/alpha.md",
            },
            {
                "alias": "conflict",
                "source_doc_id": "AI/alpha.md",
                "target": "beta",
                "target_doc_id": "AI/beta.md",
            },
            {
                "alias": "conflict",
                "source_doc_id": "AI/beta.md",
                "target": "gamma",
                "target_doc_id": "Dev/gamma.md",
            },
        ],
        "node_count": 3,
        "nodes_with_edges": 3,
        "schema": WIKILINK_SCHEMA,
        "unresolved": [
            {
                "alias": "missing",
                "source_doc_id": "AI/alpha.md",
                "target": "not-here",
            }
        ],
    }


def test_alias_generator_deduplicates_evidence_and_excludes_every_unsafe_occurrence(
    memory_corpus: MemoryCorpus,
) -> None:
    corpus = ArtifactMemoryCorpus(memory_corpus.documents, {})
    object.__setattr__(corpus, "_graph", _graph(corpus))

    dataset = generate_known_item_alias_queryset(
        corpus,
        content_tree_sha="b" * 40,
    )

    assert dataset.dataset_id == "known-item-alias-v1"
    assert dataset.kind is DatasetKind.KNOWN_ITEM
    assert dataset.provenance.generator == ALIAS_GENERATOR
    assert dataset.provenance.source_occurrence_count == 6
    assert dataset.provenance.included_occurrence_count == 2
    assert [(qrel.query, qrel.relevant_doc_ids) for qrel in dataset.qrels] == [
        ("Alpha", (DocId("AI/alpha.md"),))
    ]
    assert [
        (item.query, item.reason, tuple(map(str, item.candidate_doc_ids)))
        for item in dataset.exclusions
    ] == [
        (
            "ambiguous",
            "ambiguous-target",
            ("AI/alpha.md", "AI/beta.md"),
        ),
        (
            "conflict",
            "conflicting-alias-target",
            ("AI/beta.md", "Dev/gamma.md"),
        ),
        (
            "conflict",
            "conflicting-alias-target",
            ("AI/beta.md", "Dev/gamma.md"),
        ),
        ("missing", "unresolved-target", ()),
    ]


def test_queryset_parser_rejects_unknown_keys_and_known_item_multi_qrels(
    known_dataset,
) -> None:
    value = known_dataset.as_dict()
    value["unexpected"] = True
    with pytest.raises(DatasetError, match="unknown keys"):
        parse_queryset(value, checksum="sha256:" + "0" * 64)

    value = known_dataset.as_dict()
    value["qrels"][0]["relevant_doc_ids"] = [
        "AI/alpha.md",
        "AI/beta.md",
    ]
    with pytest.raises(DatasetError, match="exactly one"):
        parse_queryset(value, checksum="sha256:" + "0" * 64)


def test_queryset_loader_rejects_noncanonical_and_duplicate_json(
    tmp_path: Path,
    known_dataset,
) -> None:
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(known_dataset.as_dict()), encoding="utf-8")
    with pytest.raises(DatasetError, match="not canonical JSON"):
        load_queryset(path)

    path.write_text('{"schema":"a","schema":"b"}\n', encoding="utf-8")
    with pytest.raises(DatasetError, match="duplicate JSON key"):
        load_queryset(path)


def test_queryset_corpus_validation_rejects_tree_and_fingerprint_drift(
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    validate_queryset_corpus(
        known_dataset,
        memory_corpus,
        content_tree_sha="a" * 40,
    )
    with pytest.raises(DatasetError, match="content tree differs"):
        validate_queryset_corpus(
            known_dataset,
            memory_corpus,
            content_tree_sha="b" * 40,
        )

    changed = MemoryCorpus(
        {
            **memory_corpus.documents,
            DocId("AI/alpha.md"): "changed",
        }
    )
    with pytest.raises(DatasetError, match="corpus fingerprint differs"):
        validate_queryset_corpus(
            known_dataset,
            changed,
            content_tree_sha="a" * 40,
        )


def test_queryset_corpus_validation_rejects_evidence_outside_published_mirror(
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    value = known_dataset.as_dict()
    value["qrels"][0]["evidence"][0]["source_doc_id"] = "Private/hidden.md"
    dataset = parse_queryset(value, checksum="sha256:" + "0" * 64)

    with pytest.raises(DatasetError, match="outside the published mirror"):
        validate_queryset_corpus(
            dataset,
            memory_corpus,
            content_tree_sha="a" * 40,
        )


def test_committed_known_item_queryset_accounts_for_all_alias_occurrences() -> None:
    dataset = load_queryset(
        Path(__file__).parents[1] / "querysets" / "known-item-alias-v1.json"
    )
    assert dataset.kind is DatasetKind.KNOWN_ITEM
    assert len(dataset.qrels) == 90
    assert len(dataset.exclusions) == 24
    assert dataset.provenance.source_occurrence_count == 164
    assert dataset.provenance.included_occurrence_count == 140


def test_topic_contract_fixture_is_multi_document_and_not_claimed_as_gold() -> None:
    dataset = load_queryset(
        Path(__file__).parent / "fixtures" / "topic-contract-v1.json"
    )
    assert dataset.kind is DatasetKind.TOPIC
    assert dataset.dataset_id == "topic-contract-fixture-v1"
    assert dataset.provenance.generator == "synthetic-contract-fixture"
    assert len(dataset.qrels[0].relevant_doc_ids) == 2
