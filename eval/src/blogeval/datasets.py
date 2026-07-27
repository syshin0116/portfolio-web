"""Versioned query-set contract and deterministic alias-qrel generation."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from agent.retrieval.corpus import WIKILINK_SCHEMA
from agent.retrieval.protocol import Corpus, DocId

from blogeval.jsonio import (
    StrictJsonError,
    canonical_json_bytes,
    json_checksum,
    load_canonical_json,
    load_json_bytes,
    write_bytes_atomic,
)

QUERYSET_SCHEMA = "blogeval-queryset-v1"
ALIAS_GENERATOR = "blogeval.wikilink-aliases"
ALIAS_GENERATOR_VERSION = 1
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_TREE_RE = re.compile(r"^[0-9a-f]{40}$")

_ROOT_KEYS = frozenset(
    {
        "corpus",
        "dataset_id",
        "dataset_kind",
        "exclusions",
        "provenance",
        "qrels",
        "schema",
    }
)
_CORPUS_KEYS = frozenset({"document_count", "fingerprint", "git_tree_sha"})
_PROVENANCE_KEYS = frozenset(
    {
        "generator",
        "generator_version",
        "included_occurrence_count",
        "source_artifact_schema",
        "source_occurrence_count",
    }
)
_QREL_KEYS = frozenset({"evidence", "query", "query_id", "relevant_doc_ids"})
_EVIDENCE_KEYS = frozenset({"kind", "occurrences", "source_doc_id", "target"})
_EXCLUSION_KEYS = frozenset(
    {"candidate_doc_ids", "query", "reason", "source_doc_id", "target"}
)
_GRAPH_KEYS = frozenset(
    {
        "adjacency",
        "ambiguous_names",
        "corpus_fingerprint",
        "edge_count",
        "excluded_links",
        "isolated_node_count",
        "links",
        "node_count",
        "nodes_with_edges",
        "schema",
        "unresolved",
    }
)


class DatasetError(ValueError):
    """A query-set manifest violates its versioned contract."""


class DatasetKind(StrEnum):
    KNOWN_ITEM = "known-item"
    TOPIC = "topic"


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    source_doc_id: DocId | None
    target: str
    occurrences: int

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "occurrences": self.occurrences,
            "source_doc_id": (
                str(self.source_doc_id) if self.source_doc_id is not None else None
            ),
            "target": self.target,
        }


@dataclass(frozen=True, slots=True)
class Qrel:
    query_id: str
    query: str
    relevant_doc_ids: tuple[DocId, ...]
    evidence: tuple[Evidence, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence": [item.as_dict() for item in self.evidence],
            "query": self.query,
            "query_id": self.query_id,
            "relevant_doc_ids": [str(doc_id) for doc_id in self.relevant_doc_ids],
        }


@dataclass(frozen=True, slots=True)
class Exclusion:
    candidate_doc_ids: tuple[DocId, ...]
    query: str
    reason: str
    source_doc_id: DocId
    target: str

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_doc_ids": [str(doc_id) for doc_id in self.candidate_doc_ids],
            "query": self.query,
            "reason": self.reason,
            "source_doc_id": str(self.source_doc_id),
            "target": self.target,
        }


@dataclass(frozen=True, slots=True)
class CorpusIdentity:
    document_count: int
    fingerprint: str
    git_tree_sha: str

    def as_dict(self) -> dict[str, object]:
        return {
            "document_count": self.document_count,
            "fingerprint": self.fingerprint,
            "git_tree_sha": self.git_tree_sha,
        }


@dataclass(frozen=True, slots=True)
class Provenance:
    generator: str
    generator_version: int
    included_occurrence_count: int
    source_artifact_schema: str | None
    source_occurrence_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "generator": self.generator,
            "generator_version": self.generator_version,
            "included_occurrence_count": self.included_occurrence_count,
            "source_artifact_schema": self.source_artifact_schema,
            "source_occurrence_count": self.source_occurrence_count,
        }


@dataclass(frozen=True, slots=True)
class QuerySet:
    dataset_id: str
    kind: DatasetKind
    corpus: CorpusIdentity
    provenance: Provenance
    qrels: tuple[Qrel, ...]
    exclusions: tuple[Exclusion, ...]
    checksum: str

    def as_dict(self) -> dict[str, object]:
        return {
            "corpus": self.corpus.as_dict(),
            "dataset_id": self.dataset_id,
            "dataset_kind": self.kind.value,
            "exclusions": [item.as_dict() for item in self.exclusions],
            "provenance": self.provenance.as_dict(),
            "qrels": [item.as_dict() for item in self.qrels],
            "schema": QUERYSET_SCHEMA,
        }


class ArtifactCorpus(Corpus, Protocol):
    def read_artifact(self, path: str) -> bytes:
        """Read a verified generated corpus artifact."""


def _exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    location: str,
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise DatasetError(f"{location} is missing keys: {', '.join(missing)}")
    if unknown:
        raise DatasetError(f"{location} contains unknown keys: {', '.join(unknown)}")


def _mapping(value: object, *, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DatasetError(f"{location} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise DatasetError(f"{location} object keys must be strings")
    return cast(Mapping[str, object], value)


def _array(value: object, *, location: str) -> list[object]:
    if not isinstance(value, list):
        raise DatasetError(f"{location} must be an array")
    return value


def _text(
    value: object,
    *,
    location: str,
    normalized: bool = False,
) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DatasetError(f"{location} must be a non-empty trimmed string")
    if normalized and unicodedata.normalize("NFC", value) != value:
        raise DatasetError(f"{location} must use NFC normalization")
    return value


def _count(value: object, *, location: str, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        label = "positive" if positive else "non-negative"
        raise DatasetError(f"{location} must be a {label} integer")
    return value


def _doc_id(value: object, *, location: str) -> DocId:
    try:
        return DocId(value)
    except (TypeError, ValueError) as exc:
        raise DatasetError(f"{location} is not a valid DocId") from exc


def _doc_ids(
    value: object,
    *,
    location: str,
    non_empty: bool,
) -> tuple[DocId, ...]:
    raw = _array(value, location=location)
    values = tuple(
        _doc_id(item, location=f"{location}[{index}]") for index, item in enumerate(raw)
    )
    if non_empty and not values:
        raise DatasetError(f"{location} must not be empty")
    if values != tuple(sorted(set(values), key=str)):
        raise DatasetError(f"{location} must be sorted and unique")
    return values


def _parse_corpus(value: object) -> CorpusIdentity:
    raw = _mapping(value, location="corpus")
    _exact_keys(raw, _CORPUS_KEYS, location="corpus")
    document_count = _count(raw["document_count"], location="corpus.document_count")
    fingerprint = _text(raw["fingerprint"], location="corpus.fingerprint")
    if _SHA256_RE.fullmatch(fingerprint) is None:
        raise DatasetError("corpus.fingerprint must be a sha256 checksum")
    git_tree_sha = _text(raw["git_tree_sha"], location="corpus.git_tree_sha")
    if _GIT_TREE_RE.fullmatch(git_tree_sha) is None:
        raise DatasetError("corpus.git_tree_sha must be a full lowercase git tree SHA")
    return CorpusIdentity(document_count, fingerprint, git_tree_sha)


def _parse_provenance(value: object) -> Provenance:
    raw = _mapping(value, location="provenance")
    _exact_keys(raw, _PROVENANCE_KEYS, location="provenance")
    source_schema = raw["source_artifact_schema"]
    if source_schema is not None:
        source_schema = _text(
            source_schema,
            location="provenance.source_artifact_schema",
        )
    source_count = _count(
        raw["source_occurrence_count"],
        location="provenance.source_occurrence_count",
    )
    included_count = _count(
        raw["included_occurrence_count"],
        location="provenance.included_occurrence_count",
    )
    if included_count > source_count:
        raise DatasetError(
            "provenance.included_occurrence_count cannot exceed source count"
        )
    return Provenance(
        generator=_text(raw["generator"], location="provenance.generator"),
        generator_version=_count(
            raw["generator_version"],
            location="provenance.generator_version",
            positive=True,
        ),
        included_occurrence_count=included_count,
        source_artifact_schema=source_schema,
        source_occurrence_count=source_count,
    )


def _parse_evidence(value: object, *, location: str) -> Evidence:
    raw = _mapping(value, location=location)
    _exact_keys(raw, _EVIDENCE_KEYS, location=location)
    raw_source = raw["source_doc_id"]
    source = (
        None
        if raw_source is None
        else _doc_id(raw_source, location=f"{location}.source_doc_id")
    )
    return Evidence(
        kind=_text(raw["kind"], location=f"{location}.kind"),
        source_doc_id=source,
        target=_text(raw["target"], location=f"{location}.target"),
        occurrences=_count(
            raw["occurrences"],
            location=f"{location}.occurrences",
            positive=True,
        ),
    )


def _parse_qrel(
    value: object,
    *,
    index: int,
    kind: DatasetKind,
) -> Qrel:
    location = f"qrels[{index}]"
    raw = _mapping(value, location=location)
    _exact_keys(raw, _QREL_KEYS, location=location)
    evidence = tuple(
        _parse_evidence(item, location=f"{location}.evidence[{evidence_index}]")
        for evidence_index, item in enumerate(
            _array(raw["evidence"], location=f"{location}.evidence")
        )
    )
    if not evidence:
        raise DatasetError(f"{location}.evidence must not be empty")
    relevant = _doc_ids(
        raw["relevant_doc_ids"],
        location=f"{location}.relevant_doc_ids",
        non_empty=True,
    )
    if kind is DatasetKind.KNOWN_ITEM and len(relevant) != 1:
        raise DatasetError(
            f"{location} known-item qrel must have exactly one relevant DocId"
        )
    return Qrel(
        query_id=_text(raw["query_id"], location=f"{location}.query_id"),
        query=_text(
            raw["query"],
            location=f"{location}.query",
            normalized=True,
        ),
        relevant_doc_ids=relevant,
        evidence=evidence,
    )


def _parse_exclusion(value: object, *, index: int) -> Exclusion:
    location = f"exclusions[{index}]"
    raw = _mapping(value, location=location)
    _exact_keys(raw, _EXCLUSION_KEYS, location=location)
    return Exclusion(
        candidate_doc_ids=_doc_ids(
            raw["candidate_doc_ids"],
            location=f"{location}.candidate_doc_ids",
            non_empty=False,
        ),
        query=_text(
            raw["query"],
            location=f"{location}.query",
            normalized=True,
        ),
        reason=_text(raw["reason"], location=f"{location}.reason"),
        source_doc_id=_doc_id(
            raw["source_doc_id"],
            location=f"{location}.source_doc_id",
        ),
        target=_text(raw["target"], location=f"{location}.target"),
    )


def parse_queryset(value: object, *, checksum: str) -> QuerySet:
    raw = _mapping(value, location="$")
    _exact_keys(raw, _ROOT_KEYS, location="$")
    if raw["schema"] != QUERYSET_SCHEMA:
        raise DatasetError(f"unsupported query-set schema: {raw['schema']!r}")
    try:
        kind = DatasetKind(raw["dataset_kind"])
    except (TypeError, ValueError) as exc:
        raise DatasetError("dataset_kind must be 'known-item' or 'topic'") from exc
    qrels = tuple(
        _parse_qrel(item, index=index, kind=kind)
        for index, item in enumerate(_array(raw["qrels"], location="qrels"))
    )
    if not qrels:
        raise DatasetError("qrels must not be empty")
    if qrels != tuple(sorted(qrels, key=lambda item: (item.query, item.query_id))):
        raise DatasetError("qrels must be sorted by query and query_id")
    query_ids = tuple(item.query_id for item in qrels)
    queries = tuple(item.query for item in qrels)
    if len(query_ids) != len(set(query_ids)):
        raise DatasetError("qrels contain duplicate query_id values")
    if len(queries) != len(set(queries)):
        raise DatasetError("qrels contain duplicate query values")
    exclusions = tuple(
        _parse_exclusion(item, index=index)
        for index, item in enumerate(_array(raw["exclusions"], location="exclusions"))
    )
    if exclusions != tuple(
        sorted(
            exclusions,
            key=lambda item: (
                item.query,
                item.reason,
                str(item.source_doc_id),
                item.target,
                tuple(map(str, item.candidate_doc_ids)),
            ),
        )
    ):
        raise DatasetError("exclusions are not in canonical sort order")
    corpus = _parse_corpus(raw["corpus"])
    known_doc_ids = {item for qrel in qrels for item in qrel.relevant_doc_ids}
    if len(known_doc_ids) > corpus.document_count:
        raise DatasetError("qrels reference more documents than the corpus contains")
    provenance = _parse_provenance(raw["provenance"])
    included_occurrences = sum(
        evidence.occurrences for qrel in qrels for evidence in qrel.evidence
    )
    if kind is DatasetKind.KNOWN_ITEM:
        if included_occurrences != provenance.included_occurrence_count:
            raise DatasetError("known-item evidence occurrences differ from provenance")
        if provenance.source_occurrence_count != (
            provenance.included_occurrence_count + len(exclusions)
        ):
            raise DatasetError(
                "known-item source occurrences must equal included evidence plus "
                "recorded exclusions"
            )
    return QuerySet(
        dataset_id=_text(raw["dataset_id"], location="dataset_id"),
        kind=kind,
        corpus=corpus,
        provenance=provenance,
        qrels=qrels,
        exclusions=exclusions,
        checksum=checksum,
    )


def load_queryset(path: Path) -> QuerySet:
    try:
        value, payload = load_canonical_json(path)
        return parse_queryset(value, checksum=json_checksum(payload))
    except StrictJsonError as exc:
        raise DatasetError(str(exc)) from exc


def validate_queryset_corpus(
    dataset: QuerySet,
    corpus: Corpus,
    *,
    content_tree_sha: str,
) -> None:
    """Require exact manifest, mirror, and external git-tree identity agreement."""

    if _GIT_TREE_RE.fullmatch(content_tree_sha) is None:
        raise DatasetError("content_tree_sha must be a full lowercase git tree SHA")
    if dataset.corpus.git_tree_sha != content_tree_sha:
        raise DatasetError(
            "query-set content tree differs from the requested evaluation tree"
        )
    if dataset.corpus.fingerprint != corpus.fingerprint:
        raise DatasetError(
            "query-set corpus fingerprint differs from the verified published mirror"
        )
    if dataset.corpus.document_count != len(corpus.doc_ids()):
        raise DatasetError(
            "query-set document count differs from the verified published mirror"
        )
    available = set(corpus.doc_ids())
    referenced = {doc_id for qrel in dataset.qrels for doc_id in qrel.relevant_doc_ids}
    referenced.update(
        evidence.source_doc_id
        for qrel in dataset.qrels
        for evidence in qrel.evidence
        if evidence.source_doc_id is not None
    )
    referenced.update(exclusion.source_doc_id for exclusion in dataset.exclusions)
    referenced.update(
        doc_id
        for exclusion in dataset.exclusions
        for doc_id in exclusion.candidate_doc_ids
    )
    missing = sorted(referenced - available, key=str)
    if missing:
        raise DatasetError(
            "query-set qrels reference documents outside the published mirror: "
            + ", ".join(map(str, missing))
        )


def _query_id(query: str) -> str:
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    return f"alias-{digest}"


def _alias(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DatasetError("wikilink alias must be a string or null")
    normalized = unicodedata.normalize("NFC", value.strip())
    return normalized or None


def _graph_entries(value: object, *, location: str) -> Sequence[Mapping[str, object]]:
    entries = _array(value, location=location)
    result: list[Mapping[str, object]] = []
    for index, item in enumerate(entries):
        result.append(_mapping(item, location=f"{location}[{index}]"))
    return result


def generate_known_item_alias_queryset(
    corpus: ArtifactCorpus,
    *,
    content_tree_sha: str,
    dataset_id: str = "known-item-alias-v1",
) -> QuerySet:
    """Build single-target known-item qrels from verified alias wikilinks only."""

    if _GIT_TREE_RE.fullmatch(content_tree_sha) is None:
        raise DatasetError("content_tree_sha must be a full lowercase git tree SHA")
    try:
        graph_value = load_json_bytes(
            corpus.read_artifact("wikilinks.json"),
            location="wikilinks.json",
        )
    except StrictJsonError as exc:
        raise DatasetError(str(exc)) from exc
    graph = _mapping(graph_value, location="wikilinks")
    _exact_keys(graph, _GRAPH_KEYS, location="wikilinks")
    if graph["schema"] != WIKILINK_SCHEMA:
        raise DatasetError("wikilinks.json has an unsupported schema")
    if graph["corpus_fingerprint"] != corpus.fingerprint:
        raise DatasetError("wikilinks.json corpus fingerprint mismatch")

    resolved_by_query: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    source_occurrence_count = 0
    for link in _graph_entries(graph["links"], location="wikilinks.links"):
        alias = _alias(link.get("alias"))
        if alias is None:
            continue
        source_occurrence_count += 1
        resolved_by_query[alias].append(link)

    exclusions: list[Exclusion] = []
    for collection_name, reason_override in (
        ("unresolved", "unresolved-target"),
        ("excluded_links", None),
    ):
        for entry in _graph_entries(
            graph[collection_name],
            location=f"wikilinks.{collection_name}",
        ):
            alias = _alias(entry.get("alias"))
            if alias is None:
                continue
            source_occurrence_count += 1
            raw_candidates = entry.get("candidates", [])
            candidates = _doc_ids(
                raw_candidates,
                location=f"wikilinks.{collection_name}.candidates",
                non_empty=False,
            )
            if not candidates and entry.get("target_doc_id") is not None:
                candidates = (
                    _doc_id(
                        entry["target_doc_id"],
                        location=f"wikilinks.{collection_name}.target_doc_id",
                    ),
                )
            reason_value = reason_override or entry.get("reason")
            exclusions.append(
                Exclusion(
                    candidate_doc_ids=candidates,
                    query=alias,
                    reason=_text(
                        reason_value,
                        location=f"wikilinks.{collection_name}.reason",
                    ),
                    source_doc_id=_doc_id(
                        entry.get("source_doc_id"),
                        location=f"wikilinks.{collection_name}.source_doc_id",
                    ),
                    target=_text(
                        entry.get("target"),
                        location=f"wikilinks.{collection_name}.target",
                    ),
                )
            )

    qrels: list[Qrel] = []
    for query, entries in resolved_by_query.items():
        target_doc_ids = tuple(
            sorted(
                {
                    _doc_id(
                        entry.get("target_doc_id"),
                        location="wikilinks.links.target_doc_id",
                    )
                    for entry in entries
                },
                key=str,
            )
        )
        if len(target_doc_ids) != 1:
            for entry in entries:
                exclusions.append(
                    Exclusion(
                        candidate_doc_ids=target_doc_ids,
                        query=query,
                        reason="conflicting-alias-target",
                        source_doc_id=_doc_id(
                            entry.get("source_doc_id"),
                            location="wikilinks.links.source_doc_id",
                        ),
                        target=_text(
                            entry.get("target"),
                            location="wikilinks.links.target",
                        ),
                    )
                )
            continue

        evidence_counts: Counter[tuple[DocId, str]] = Counter()
        for entry in entries:
            source_doc_id = _doc_id(
                entry.get("source_doc_id"),
                location="wikilinks.links.source_doc_id",
            )
            target = _text(
                entry.get("target"),
                location="wikilinks.links.target",
            )
            evidence_counts[(source_doc_id, target)] += 1
        evidence = tuple(
            Evidence(
                kind="wikilink-alias",
                source_doc_id=source_doc_id,
                target=target,
                occurrences=count,
            )
            for (source_doc_id, target), count in sorted(
                evidence_counts.items(),
                key=lambda item: (str(item[0][0]), item[0][1]),
            )
        )
        qrels.append(
            Qrel(
                query_id=_query_id(query),
                query=query,
                relevant_doc_ids=target_doc_ids,
                evidence=evidence,
            )
        )

    qrels.sort(key=lambda item: (item.query, item.query_id))
    exclusions.sort(
        key=lambda item: (
            item.query,
            item.reason,
            str(item.source_doc_id),
            item.target,
            tuple(map(str, item.candidate_doc_ids)),
        )
    )
    if source_occurrence_count != sum(
        evidence.occurrences for qrel in qrels for evidence in qrel.evidence
    ) + len(exclusions):
        raise DatasetError(
            "alias occurrence accounting differs from qrels plus exclusions"
        )
    payload = {
        "corpus": {
            "document_count": len(corpus.doc_ids()),
            "fingerprint": corpus.fingerprint,
            "git_tree_sha": content_tree_sha,
        },
        "dataset_id": dataset_id,
        "dataset_kind": DatasetKind.KNOWN_ITEM.value,
        "exclusions": [item.as_dict() for item in exclusions],
        "provenance": {
            "generator": ALIAS_GENERATOR,
            "generator_version": ALIAS_GENERATOR_VERSION,
            "included_occurrence_count": sum(
                evidence.occurrences for qrel in qrels for evidence in qrel.evidence
            ),
            "source_artifact_schema": WIKILINK_SCHEMA,
            "source_occurrence_count": source_occurrence_count,
        },
        "qrels": [item.as_dict() for item in qrels],
        "schema": QUERYSET_SCHEMA,
    }
    encoded = canonical_json_bytes(payload)
    return parse_queryset(
        load_json_bytes(encoded, location="generated known-item queryset"),
        checksum=json_checksum(encoded),
    )


def write_queryset(path: Path, dataset: QuerySet) -> None:
    write_bytes_atomic(path, canonical_json_bytes(dataset.as_dict()))


__all__ = [
    "ALIAS_GENERATOR",
    "ALIAS_GENERATOR_VERSION",
    "ArtifactCorpus",
    "CorpusIdentity",
    "DatasetError",
    "DatasetKind",
    "Evidence",
    "Exclusion",
    "Provenance",
    "Qrel",
    "QUERYSET_SCHEMA",
    "QuerySet",
    "generate_known_item_alias_queryset",
    "load_queryset",
    "parse_queryset",
    "validate_queryset_corpus",
    "write_queryset",
]
