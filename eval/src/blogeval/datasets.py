"""Versioned query-set contract and deterministic alias-qrel generation."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from agent.retrieval.corpus import WIKILINK_SCHEMA, PublishedCorpus
from agent.retrieval.protocol import Corpus, DocId
from agent.retrieval.serving import (
    ServingArtifactError,
    load_validated_wikilink_graph,
)

from blogeval.jsonio import (
    StrictJsonError,
    canonical_json_bytes,
    json_checksum,
    load_canonical_json,
    load_json_bytes,
    write_bytes_atomic,
)

QUERYSET_SCHEMA = "blogeval-queryset-v2"
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
        "labels",
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
        "source_artifacts",
        "source_occurrence_count",
    }
)
_SOURCE_ARTIFACT_KEYS = frozenset({"derived_from", "path", "schema", "sha256"})
_LABEL_KEYS = frozenset({"review", "reviewed_qrels_checksum", "status"})
_REVIEW_KEYS = frozenset({"review_ref", "reviewed_at", "reviewer"})
_QREL_KEYS = frozenset({"evidence", "query", "query_id", "relevant_doc_ids"})
_EVIDENCE_KEYS = frozenset({"kind", "occurrences", "source_doc_id", "target"})
_EXCLUSION_KEYS = frozenset(
    {"candidate_doc_ids", "query", "reason", "source_doc_id", "target"}
)


class DatasetError(ValueError):
    """A query-set manifest violates its versioned contract."""


class DatasetKind(StrEnum):
    KNOWN_ITEM = "known-item"
    TOPIC = "topic"


class LabelStatus(StrEnum):
    GENERATED_OWNER_AUTHORED = "generated-owner-authored"
    OWNER_REVIEWED = "owner-reviewed"
    SYNTHETIC_ONLY = "synthetic-only"


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
class SourceArtifact:
    path: str
    schema: str
    checksum: str
    derived_from: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "derived_from": list(self.derived_from),
            "path": self.path,
            "schema": self.schema,
            "sha256": self.checksum,
        }


@dataclass(frozen=True, slots=True)
class ReviewProvenance:
    reviewer: str
    reviewed_at: date
    review_ref: str

    def as_dict(self) -> dict[str, object]:
        return {
            "review_ref": self.review_ref,
            "reviewed_at": self.reviewed_at.isoformat(),
            "reviewer": self.reviewer,
        }


@dataclass(frozen=True, slots=True)
class LabelContract:
    status: LabelStatus
    reviewed_qrels_checksum: str | None
    review: ReviewProvenance | None

    def as_dict(self) -> dict[str, object]:
        return {
            "review": self.review.as_dict() if self.review is not None else None,
            "reviewed_qrels_checksum": self.reviewed_qrels_checksum,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class Provenance:
    generator: str
    generator_version: int
    included_occurrence_count: int
    source_artifacts: tuple[SourceArtifact, ...]
    source_occurrence_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "generator": self.generator,
            "generator_version": self.generator_version,
            "included_occurrence_count": self.included_occurrence_count,
            "source_artifacts": [
                artifact.as_dict() for artifact in self.source_artifacts
            ],
            "source_occurrence_count": self.source_occurrence_count,
        }


@dataclass(frozen=True, slots=True)
class QuerySet:
    dataset_id: str
    kind: DatasetKind
    corpus: CorpusIdentity
    labels: LabelContract
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
            "labels": self.labels.as_dict(),
            "provenance": self.provenance.as_dict(),
            "qrels": [item.as_dict() for item in self.qrels],
            "schema": QUERYSET_SCHEMA,
        }

    def require_reviewed_labels(self) -> None:
        if self.labels.status is not LabelStatus.OWNER_REVIEWED:
            raise DatasetError(
                "publication requires owner-reviewed qrels; "
                f"dataset status is {self.labels.status.value!r}"
            )
        expected = qrels_checksum(self.qrels)
        if self.labels.reviewed_qrels_checksum != expected:
            raise DatasetError(
                "owner-reviewed qrel checksum does not match the exact qrels"
            )
        if self.labels.review is None:
            raise DatasetError("owner-reviewed labels require review provenance")


class ArtifactCorpus(Corpus, Protocol):
    @property
    def content_git_tree_sha(self) -> str:
        """Return the build-derived content Git tree identity."""

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


def _string_tuple(value: object, *, location: str) -> tuple[str, ...]:
    raw = _array(value, location=location)
    values = tuple(
        _text(item, location=f"{location}[{index}]") for index, item in enumerate(raw)
    )
    if values != tuple(sorted(set(values))):
        raise DatasetError(f"{location} must be sorted and unique")
    return values


def _parse_source_artifact(value: object, *, index: int) -> SourceArtifact:
    location = f"provenance.source_artifacts[{index}]"
    raw = _mapping(value, location=location)
    _exact_keys(raw, _SOURCE_ARTIFACT_KEYS, location=location)
    checksum = _text(raw["sha256"], location=f"{location}.sha256")
    if _SHA256_RE.fullmatch(checksum) is None:
        raise DatasetError(f"{location}.sha256 must be a sha256 checksum")
    path = _text(raw["path"], location=f"{location}.path")
    if (
        path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or any(part in {"", ".", ".."} for part in Path(path).parts)
    ):
        raise DatasetError(f"{location}.path must be a canonical relative path")
    return SourceArtifact(
        path=path,
        schema=_text(raw["schema"], location=f"{location}.schema"),
        checksum=checksum,
        derived_from=_string_tuple(
            raw["derived_from"],
            location=f"{location}.derived_from",
        ),
    )


def _parse_provenance(value: object) -> Provenance:
    raw = _mapping(value, location="provenance")
    _exact_keys(raw, _PROVENANCE_KEYS, location="provenance")
    source_artifacts = tuple(
        _parse_source_artifact(item, index=index)
        for index, item in enumerate(
            _array(
                raw["source_artifacts"],
                location="provenance.source_artifacts",
            )
        )
    )
    if source_artifacts != tuple(
        sorted(source_artifacts, key=lambda artifact: artifact.path)
    ):
        raise DatasetError("provenance.source_artifacts must be sorted by path")
    if len({artifact.path for artifact in source_artifacts}) != len(source_artifacts):
        raise DatasetError("provenance.source_artifacts contains duplicate paths")
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
        source_artifacts=source_artifacts,
        source_occurrence_count=source_count,
    )


def qrels_checksum(qrels: Sequence[Qrel]) -> str:
    return json_checksum(canonical_json_bytes([qrel.as_dict() for qrel in qrels]))


def _parse_review(value: object) -> ReviewProvenance:
    raw = _mapping(value, location="labels.review")
    _exact_keys(raw, _REVIEW_KEYS, location="labels.review")
    reviewed_at_raw = _text(raw["reviewed_at"], location="labels.review.reviewed_at")
    try:
        reviewed_at = date.fromisoformat(reviewed_at_raw)
    except ValueError as exc:
        raise DatasetError(
            "labels.review.reviewed_at must be an ISO calendar date"
        ) from exc
    return ReviewProvenance(
        reviewer=_text(raw["reviewer"], location="labels.review.reviewer"),
        reviewed_at=reviewed_at,
        review_ref=_text(raw["review_ref"], location="labels.review.review_ref"),
    )


def _parse_labels(value: object, *, qrels: Sequence[Qrel]) -> LabelContract:
    raw = _mapping(value, location="labels")
    _exact_keys(raw, _LABEL_KEYS, location="labels")
    try:
        status = LabelStatus(raw["status"])
    except (TypeError, ValueError) as exc:
        raise DatasetError(
            "labels.status must be generated-owner-authored, owner-reviewed, "
            "or synthetic-only"
        ) from exc
    checksum_value = raw["reviewed_qrels_checksum"]
    if checksum_value is not None:
        checksum_value = _text(
            checksum_value,
            location="labels.reviewed_qrels_checksum",
        )
        if _SHA256_RE.fullmatch(checksum_value) is None:
            raise DatasetError(
                "labels.reviewed_qrels_checksum must be a sha256 checksum or null"
            )
    review = None if raw["review"] is None else _parse_review(raw["review"])
    if status is LabelStatus.OWNER_REVIEWED:
        if checksum_value != qrels_checksum(qrels):
            raise DatasetError(
                "owner-reviewed labels must checksum the exact canonical qrels"
            )
        if review is None:
            raise DatasetError("owner-reviewed labels require review provenance")
    elif checksum_value is not None or review is not None:
        raise DatasetError(
            "unreviewed labels cannot carry a reviewed checksum or review provenance"
        )
    return LabelContract(status, checksum_value, review)


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
        labels=_parse_labels(raw["labels"], qrels=qrels),
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
    manifest_tree_sha = getattr(corpus, "content_git_tree_sha", None)
    if (
        not isinstance(manifest_tree_sha, str)
        or _GIT_TREE_RE.fullmatch(manifest_tree_sha) is None
    ):
        raise DatasetError(
            "verified corpus does not expose a build-derived content Git tree SHA"
        )
    if manifest_tree_sha != content_tree_sha:
        raise DatasetError(
            "corpus manifest content tree differs from the requested evaluation tree"
        )
    if dataset.corpus.git_tree_sha != manifest_tree_sha:
        raise DatasetError(
            "query-set content tree differs from the verified corpus manifest"
        )
    if dataset.corpus.fingerprint != corpus.fingerprint:
        raise DatasetError(
            "query-set corpus fingerprint differs from the verified published mirror"
        )
    if dataset.corpus.document_count != len(corpus.doc_ids()):
        raise DatasetError(
            "query-set document count differs from the verified published mirror"
        )
    artifact_reader = getattr(corpus, "read_artifact", None)
    if not callable(artifact_reader):
        raise DatasetError("verified corpus cannot read the query-set source artifacts")
    for artifact in dataset.provenance.source_artifacts:
        try:
            payload = artifact_reader(artifact.path)
        except (KeyError, OSError, ValueError) as exc:
            raise DatasetError(
                f"cannot read query-set source artifact {artifact.path}: {exc}"
            ) from exc
        if not isinstance(payload, bytes):
            raise DatasetError(
                f"query-set source artifact {artifact.path} did not return bytes"
            )
        if json_checksum(payload) != artifact.checksum:
            raise DatasetError(
                f"query-set source artifact checksum differs: {artifact.path}"
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
    manifest_tree_sha = getattr(corpus, "content_git_tree_sha", None)
    if manifest_tree_sha != content_tree_sha:
        raise DatasetError(
            "requested content tree differs from the build-derived corpus manifest"
        )
    try:
        validated_graph = load_validated_wikilink_graph(cast(PublishedCorpus, corpus))
    except (ServingArtifactError, ValueError) as exc:
        raise DatasetError(str(exc)) from exc

    resolved_by_query: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    source_occurrence_count = 0
    for link in validated_graph.links:
        alias = _alias(link.get("alias"))
        if alias is None:
            continue
        source_occurrence_count += 1
        resolved_by_query[alias].append(link)

    exclusions: list[Exclusion] = []
    for collection_name, entries, reason_override in (
        ("unresolved", validated_graph.unresolved, "unresolved-target"),
        ("excluded_links", validated_graph.excluded_links, None),
    ):
        for entry in entries:
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
        "labels": {
            "review": None,
            "reviewed_qrels_checksum": None,
            "status": LabelStatus.GENERATED_OWNER_AUTHORED.value,
        },
        "provenance": {
            "generator": ALIAS_GENERATOR,
            "generator_version": ALIAS_GENERATOR_VERSION,
            "included_occurrence_count": sum(
                evidence.occurrences for qrel in qrels for evidence in qrel.evidence
            ),
            "source_artifacts": [
                {
                    "derived_from": ["corpus:published-markdown"],
                    "path": "wikilinks.json",
                    "schema": WIKILINK_SCHEMA,
                    "sha256": validated_graph.artifact_checksum,
                }
            ],
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
    "LabelContract",
    "LabelStatus",
    "Provenance",
    "Qrel",
    "QUERYSET_SCHEMA",
    "QuerySet",
    "ReviewProvenance",
    "SourceArtifact",
    "generate_known_item_alias_queryset",
    "load_queryset",
    "parse_queryset",
    "qrels_checksum",
    "validate_queryset_corpus",
    "write_queryset",
]
