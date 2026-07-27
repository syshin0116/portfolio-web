from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from agent.retrieval.corpus import WIKILINK_SCHEMA
from agent.retrieval.protocol import DocId

from blogeval.datasets import (
    ALIAS_GENERATOR,
    DatasetError,
    DatasetKind,
    LabelStatus,
    generate_known_item_alias_queryset,
    load_queryset,
    parse_queryset,
    qrels_checksum,
    validate_queryset_corpus,
)
from blogeval.jsonio import canonical_json_bytes, json_checksum
from conftest import MemoryCorpus


class ArtifactMemoryCorpus(MemoryCorpus):
    def __init__(self, documents, graph):
        super().__init__(documents, "b" * 40)
        object.__setattr__(self, "_graph", graph)

    def read_artifact(self, path: str) -> bytes:
        if path == "wikilinks.json":
            return canonical_json_bytes(self._graph)
        if path == "catalog.json":
            documents = []
            for doc_id in self.doc_ids():
                stem = Path(str(doc_id)).stem
                metadata = (
                    {"title": "ambiguous"}
                    if str(doc_id) in {"AI/alpha.md", "AI/beta.md"}
                    else {}
                )
                documents.append(
                    {
                        "category": Path(str(doc_id)).parts[0],
                        "date": None,
                        "description": "",
                        "doc_id": str(doc_id),
                        "metadata": metadata,
                        "tags": [],
                        "title": metadata.get("title", stem),
                    }
                )
            return canonical_json_bytes(
                {
                    "corpus_fingerprint": self.fingerprint,
                    "document_count": len(documents),
                    "documents": documents,
                    "schema": "published-corpus-catalog-v1",
                }
            )
        raise KeyError(path)


def _graph(corpus: MemoryCorpus) -> dict[str, object]:
    return {
        "adjacency": {
            "AI/alpha.md": ["AI/beta.md", "Dev/gamma.md"],
            "AI/beta.md": ["AI/alpha.md", "Dev/gamma.md"],
            "Dev/gamma.md": ["AI/alpha.md", "AI/beta.md"],
        },
        "ambiguous_names": [
            {
                "candidates": ["AI/alpha.md", "AI/beta.md"],
                "name": "ambiguous",
            }
        ],
        "corpus_fingerprint": corpus.fingerprint,
        "edge_count": 3,
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
    assert dataset.labels.status is LabelStatus.GENERATED_OWNER_AUTHORED
    assert dataset.labels.reviewed_qrels_checksum is None
    assert dataset.provenance.generator == ALIAS_GENERATOR
    assert dataset.provenance.source_occurrence_count == 6
    assert dataset.provenance.included_occurrence_count == 2
    assert dataset.provenance.source_artifacts[0].path == "wikilinks.json"
    assert dataset.provenance.source_artifacts[0].checksum == json_checksum(
        canonical_json_bytes(_graph(corpus))
    )
    assert dataset.provenance.source_artifacts[0].derived_from == (
        "corpus:published-markdown",
    )
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


def test_alias_generator_rejects_caller_tree_sha_that_differs_from_manifest(
    memory_corpus: MemoryCorpus,
) -> None:
    corpus = ArtifactMemoryCorpus(memory_corpus.documents, {})
    object.__setattr__(corpus, "_graph", _graph(corpus))

    with pytest.raises(DatasetError, match="build-derived corpus manifest"):
        generate_known_item_alias_queryset(
            corpus,
            content_tree_sha="f" * 40,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "root-extra",
        "nested-extra",
        "count",
        "adjacency",
        "membership",
        "self-link",
    ),
)
def test_alias_generator_uses_serving_strength_graph_validation(
    memory_corpus: MemoryCorpus,
    mutation: str,
) -> None:
    corpus = ArtifactMemoryCorpus(memory_corpus.documents, {})
    graph = deepcopy(_graph(corpus))
    if mutation == "root-extra":
        graph["future_field"] = True
    elif mutation == "nested-extra":
        graph["links"][0]["future_field"] = True
    elif mutation == "count":
        graph["edge_count"] = 4
    elif mutation == "adjacency":
        graph["adjacency"]["AI/alpha.md"].remove("AI/beta.md")
    elif mutation == "membership":
        graph["links"][0]["source_doc_id"] = "Outside/ghost.md"
    else:
        graph["links"][0]["target_doc_id"] = graph["links"][0]["source_doc_id"]
    object.__setattr__(corpus, "_graph", graph)

    with pytest.raises(DatasetError):
        generate_known_item_alias_queryset(
            corpus,
            content_tree_sha="b" * 40,
        )


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

    manifest_drift = MemoryCorpus(memory_corpus.documents, "b" * 40)
    with pytest.raises(DatasetError, match="corpus manifest content tree differs"):
        validate_queryset_corpus(
            known_dataset,
            manifest_drift,
            content_tree_sha="a" * 40,
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


def test_queryset_corpus_validation_rejects_source_artifact_checksum_drift(
    memory_corpus: MemoryCorpus,
    known_dataset,
) -> None:
    class ChangedArtifactCorpus(MemoryCorpus):
        def read_artifact(self, path: str) -> bytes:
            assert path == "fixture.json"
            return b"changed artifact\n"

    changed = ChangedArtifactCorpus(memory_corpus.documents)
    with pytest.raises(DatasetError, match="source artifact checksum differs"):
        validate_queryset_corpus(
            known_dataset,
            changed,
            content_tree_sha="a" * 40,
        )


def test_owner_review_status_binds_exact_qrels_and_review_provenance(
    known_dataset,
) -> None:
    value = known_dataset.as_dict()
    value["labels"] = {
        "review": {
            "review_ref": "owner-review:known-contract-v1",
            "reviewed_at": "2026-07-28",
            "reviewer": "@owner",
        },
        "reviewed_qrels_checksum": qrels_checksum(known_dataset.qrels),
        "status": "owner-reviewed",
    }
    reviewed = parse_queryset(value, checksum=known_dataset.checksum)
    reviewed.require_reviewed_labels()

    value["qrels"][0]["evidence"][0]["target"] = "changed-after-review"
    with pytest.raises(DatasetError, match="checksum the exact canonical qrels"):
        parse_queryset(value, checksum=known_dataset.checksum)


def test_unreviewed_status_rejects_review_claims(known_dataset) -> None:
    value = known_dataset.as_dict()
    value["labels"]["reviewed_qrels_checksum"] = qrels_checksum(known_dataset.qrels)

    with pytest.raises(DatasetError, match="unreviewed labels cannot carry"):
        parse_queryset(value, checksum=known_dataset.checksum)


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
    assert dataset.labels.status is LabelStatus.GENERATED_OWNER_AUTHORED
    assert len(dataset.qrels) == 90
    assert len(dataset.exclusions) == 24
    assert dataset.provenance.source_occurrence_count == 164
    assert dataset.provenance.included_occurrence_count == 140


def test_topic_contract_fixture_is_multi_document_and_not_claimed_as_gold() -> None:
    dataset = load_queryset(
        Path(__file__).parent / "fixtures" / "topic-contract-v1.json"
    )
    assert dataset.kind is DatasetKind.TOPIC
    assert dataset.labels.status is LabelStatus.SYNTHETIC_ONLY
    assert dataset.dataset_id == "topic-contract-fixture-v1"
    assert dataset.provenance.generator == "synthetic-contract-fixture"
    assert len(dataset.qrels[0].relevant_doc_ids) == 2
