"""Deterministic, fail-closed owner review workflow for topic qrels."""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import cast

from agent.retrieval.protocol import Corpus, DocId
from agent.retrieval.registry import ResolvedRetriever, RetrieverRegistry

from blogeval.datasets import (
    QUERYSET_SCHEMA,
    CorpusIdentity,
    DatasetError,
    DatasetKind,
    Evidence,
    LabelStatus,
    Qrel,
    QuerySet,
    ReviewProvenance,
    parse_queryset,
    qrels_checksum,
    validate_queryset_corpus,
)
from blogeval.jsonio import (
    StrictJsonError,
    canonical_json_bytes,
    json_checksum,
    load_canonical_json,
    load_json_bytes,
    write_bytes_atomic,
)
from blogeval.registry import registry as default_registry

TOPIC_SEED_SCHEMA = "blogeval-topic-seed-v1"
TOPIC_REVIEW_SCHEMA = "blogeval-topic-review-v1"
TOPIC_REVIEW_GENERATOR = "blogeval.topic-review"
TOPIC_REVIEW_GENERATOR_VERSION = 1
TOPIC_REVIEW_OWNER = "@syshin0116"

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_TREE_RE = re.compile(r"^[0-9a-f]{40}$")
_REVIEW_REF_RE = re.compile(r"^git:[0-9a-f]{40}$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_BLIND_ID_RE = re.compile(r"^topic-candidate-[0-9a-f]{24}$")
_MAX_QUERIES = 50
_MAX_METHODS = 16
_MAX_CANDIDATES_PER_METHOD = 100
_MAX_IDENTIFIER_BYTES = 96
_MAX_QUERY_BYTES = 512
_MAX_REVIEW_TEXT_BYTES = 512

_SEED_ROOT_KEYS = frozenset({"candidate_generation", "dataset_id", "queries", "schema"})
_SEED_GENERATION_KEYS = frozenset({"candidate_limit_per_method", "method_ids"})
_SEED_QUERY_KEYS = frozenset({"query", "query_id"})
_REVIEW_ROOT_KEYS = frozenset(
    {
        "candidate_generation",
        "corpus",
        "dataset_id",
        "labels",
        "queries",
        "schema",
        "seed_checksum",
    }
)
_CORPUS_KEYS = frozenset({"document_count", "fingerprint", "git_tree_sha"})
_GENERATION_KEYS = frozenset(
    {
        "candidate_limit_per_method",
        "generator",
        "generator_version",
        "methods",
    }
)
_METHOD_KEYS = frozenset({"fingerprint", "method_id"})
_LABEL_KEYS = frozenset({"review", "reviewed_payload_checksum", "status"})
_REVIEW_KEYS = frozenset({"review_ref", "reviewed_at", "reviewer"})
_QUERY_KEYS = frozenset(
    {
        "additional_relevant_doc_ids",
        "candidate_pool_complete",
        "candidates",
        "query",
        "query_id",
    }
)
_CANDIDATE_KEYS = frozenset({"blind_id", "doc_id", "judgement"})


class TopicReviewError(DatasetError):
    """A topic seed or owner-review manifest violates its exact contract."""


class TopicReviewStatus(StrEnum):
    PENDING = "pending-owner-review"
    OWNER_REVIEWED = "owner-reviewed"


class CandidateJudgement(StrEnum):
    PENDING = "pending"
    RELEVANT = "relevant"
    NOT_RELEVANT = "not-relevant"


@dataclass(frozen=True, slots=True)
class TopicSeedQuery:
    query_id: str
    query: str

    def as_dict(self) -> dict[str, object]:
        return {"query": self.query, "query_id": self.query_id}


@dataclass(frozen=True, slots=True)
class TopicSeed:
    dataset_id: str
    candidate_limit_per_method: int
    method_ids: tuple[str, ...]
    queries: tuple[TopicSeedQuery, ...]
    checksum: str

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_generation": {
                "candidate_limit_per_method": self.candidate_limit_per_method,
                "method_ids": list(self.method_ids),
            },
            "dataset_id": self.dataset_id,
            "queries": [query.as_dict() for query in self.queries],
            "schema": TOPIC_SEED_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class CandidateMethod:
    method_id: str
    fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {"fingerprint": self.fingerprint, "method_id": self.method_id}


@dataclass(frozen=True, slots=True)
class CandidateGeneration:
    candidate_limit_per_method: int
    generator: str
    generator_version: int
    methods: tuple[CandidateMethod, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate_limit_per_method": self.candidate_limit_per_method,
            "generator": self.generator,
            "generator_version": self.generator_version,
            "methods": [method.as_dict() for method in self.methods],
        }


@dataclass(frozen=True, slots=True)
class TopicCandidate:
    blind_id: str
    doc_id: DocId
    judgement: CandidateJudgement

    def as_dict(self) -> dict[str, object]:
        return {
            "blind_id": self.blind_id,
            "doc_id": str(self.doc_id),
            "judgement": self.judgement.value,
        }


@dataclass(frozen=True, slots=True)
class TopicReviewQuery:
    query_id: str
    query: str
    candidates: tuple[TopicCandidate, ...]
    additional_relevant_doc_ids: tuple[DocId, ...]
    candidate_pool_complete: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "additional_relevant_doc_ids": [
                str(doc_id) for doc_id in self.additional_relevant_doc_ids
            ],
            "candidate_pool_complete": self.candidate_pool_complete,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "query": self.query,
            "query_id": self.query_id,
        }

    @property
    def relevant_doc_ids(self) -> tuple[DocId, ...]:
        values = {
            candidate.doc_id
            for candidate in self.candidates
            if candidate.judgement is CandidateJudgement.RELEVANT
        }
        values.update(self.additional_relevant_doc_ids)
        return tuple(sorted(values, key=str))


@dataclass(frozen=True, slots=True)
class TopicReviewLabels:
    status: TopicReviewStatus
    reviewed_payload_checksum: str | None
    review: ReviewProvenance | None

    def as_dict(self) -> dict[str, object]:
        return {
            "review": self.review.as_dict() if self.review is not None else None,
            "reviewed_payload_checksum": self.reviewed_payload_checksum,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class TopicReview:
    dataset_id: str
    seed_checksum: str
    corpus: CorpusIdentity
    candidate_generation: CandidateGeneration
    labels: TopicReviewLabels
    queries: tuple[TopicReviewQuery, ...]
    checksum: str

    def review_payload_dict(self) -> dict[str, object]:
        return {
            "candidate_generation": self.candidate_generation.as_dict(),
            "corpus": self.corpus.as_dict(),
            "dataset_id": self.dataset_id,
            "queries": [query.as_dict() for query in self.queries],
            "schema": TOPIC_REVIEW_SCHEMA,
            "seed_checksum": self.seed_checksum,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            **self.review_payload_dict(),
            "labels": self.labels.as_dict(),
        }


def _exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    location: str,
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise TopicReviewError(f"{location} is missing keys: {', '.join(missing)}")
    if unknown:
        raise TopicReviewError(
            f"{location} contains unknown keys: {', '.join(unknown)}"
        )


def _mapping(value: object, *, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TopicReviewError(f"{location} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise TopicReviewError(f"{location} object keys must be strings")
    return cast(Mapping[str, object], value)


def _array(value: object, *, location: str) -> list[object]:
    if not isinstance(value, list):
        raise TopicReviewError(f"{location} must be an array")
    return value


def _text(
    value: object,
    *,
    location: str,
    max_bytes: int,
    normalized: bool = False,
) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise TopicReviewError(f"{location} must be a non-empty trimmed string")
    if len(value.encode("utf-8")) > max_bytes:
        raise TopicReviewError(f"{location} exceeds its byte limit")
    if normalized and unicodedata.normalize("NFC", value) != value:
        raise TopicReviewError(f"{location} must use NFC normalization")
    return value


def _identifier(value: object, *, location: str) -> str:
    identifier = _text(
        value,
        location=location,
        max_bytes=_MAX_IDENTIFIER_BYTES,
    )
    if _IDENTIFIER_RE.fullmatch(identifier) is None:
        raise TopicReviewError(f"{location} must be lower kebab-case")
    return identifier


def _checksum(value: object, *, location: str) -> str:
    checksum = _text(value, location=location, max_bytes=71)
    if _SHA256_RE.fullmatch(checksum) is None:
        raise TopicReviewError(f"{location} must be a sha256 checksum")
    return checksum


def _positive_bounded_integer(
    value: object,
    *,
    location: str,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= maximum
    ):
        raise TopicReviewError(
            f"{location} must be an integer from 1 through {maximum}"
        )
    return value


def _doc_id(value: object, *, location: str) -> DocId:
    try:
        return DocId(value)
    except (TypeError, ValueError) as exc:
        raise TopicReviewError(f"{location} is not a valid DocId") from exc


def _doc_ids(value: object, *, location: str) -> tuple[DocId, ...]:
    values = tuple(
        _doc_id(item, location=f"{location}[{index}]")
        for index, item in enumerate(_array(value, location=location))
    )
    if values != tuple(sorted(set(values), key=str)):
        raise TopicReviewError(f"{location} must be sorted and unique")
    return values


def _parse_corpus(value: object) -> CorpusIdentity:
    raw = _mapping(value, location="corpus")
    _exact_keys(raw, _CORPUS_KEYS, location="corpus")
    count = raw["document_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise TopicReviewError("corpus.document_count must be a non-negative integer")
    fingerprint = _checksum(raw["fingerprint"], location="corpus.fingerprint")
    tree = _text(raw["git_tree_sha"], location="corpus.git_tree_sha", max_bytes=40)
    if _GIT_TREE_RE.fullmatch(tree) is None:
        raise TopicReviewError(
            "corpus.git_tree_sha must be a full lowercase git tree SHA"
        )
    return CorpusIdentity(count, fingerprint, tree)


def _parse_seed_query(value: object, *, index: int) -> TopicSeedQuery:
    location = f"queries[{index}]"
    raw = _mapping(value, location=location)
    _exact_keys(raw, _SEED_QUERY_KEYS, location=location)
    return TopicSeedQuery(
        query_id=_identifier(raw["query_id"], location=f"{location}.query_id"),
        query=_text(
            raw["query"],
            location=f"{location}.query",
            max_bytes=_MAX_QUERY_BYTES,
            normalized=True,
        ),
    )


def _parse_seed_generation(value: object) -> tuple[int, tuple[str, ...]]:
    raw = _mapping(value, location="candidate_generation")
    _exact_keys(raw, _SEED_GENERATION_KEYS, location="candidate_generation")
    limit = _positive_bounded_integer(
        raw["candidate_limit_per_method"],
        location="candidate_generation.candidate_limit_per_method",
        maximum=_MAX_CANDIDATES_PER_METHOD,
    )
    raw_method_ids = _array(
        raw["method_ids"], location="candidate_generation.method_ids"
    )
    if not raw_method_ids or len(raw_method_ids) > _MAX_METHODS:
        raise TopicReviewError(
            "candidate_generation.method_ids must contain "
            f"1 through {_MAX_METHODS} values"
        )
    method_ids = tuple(
        _identifier(
            method_id,
            location=f"candidate_generation.method_ids[{index}]",
        )
        for index, method_id in enumerate(raw_method_ids)
    )
    if method_ids != tuple(sorted(set(method_ids))):
        raise TopicReviewError(
            "candidate_generation.method_ids must be sorted and unique"
        )
    return limit, method_ids


def parse_topic_seed(value: object, *, checksum: str) -> TopicSeed:
    raw = _mapping(value, location="$")
    _exact_keys(raw, _SEED_ROOT_KEYS, location="$")
    if raw["schema"] != TOPIC_SEED_SCHEMA:
        raise TopicReviewError(f"unsupported topic seed schema: {raw['schema']!r}")
    parsed_checksum = _checksum(checksum, location="topic seed checksum")
    candidate_limit_per_method, method_ids = _parse_seed_generation(
        raw["candidate_generation"]
    )
    queries = tuple(
        _parse_seed_query(item, index=index)
        for index, item in enumerate(_array(raw["queries"], location="queries"))
    )
    if not queries or len(queries) > _MAX_QUERIES:
        raise TopicReviewError(
            f"topic seed must contain 1 through {_MAX_QUERIES} queries"
        )
    if queries != tuple(sorted(queries, key=lambda item: (item.query, item.query_id))):
        raise TopicReviewError(
            "topic seed queries must be sorted by query and query_id"
        )
    if len({item.query_id for item in queries}) != len(queries):
        raise TopicReviewError("topic seed contains duplicate query_id values")
    if len({item.query for item in queries}) != len(queries):
        raise TopicReviewError("topic seed contains duplicate query values")
    return TopicSeed(
        dataset_id=_identifier(raw["dataset_id"], location="dataset_id"),
        candidate_limit_per_method=candidate_limit_per_method,
        method_ids=method_ids,
        queries=queries,
        checksum=parsed_checksum,
    )


def load_topic_seed(path: Path) -> TopicSeed:
    try:
        value, payload = load_canonical_json(path)
        return parse_topic_seed(value, checksum=json_checksum(payload))
    except StrictJsonError as exc:
        raise TopicReviewError(str(exc)) from exc


def _parse_method(value: object, *, index: int) -> CandidateMethod:
    location = f"candidate_generation.methods[{index}]"
    raw = _mapping(value, location=location)
    _exact_keys(raw, _METHOD_KEYS, location=location)
    return CandidateMethod(
        method_id=_identifier(raw["method_id"], location=f"{location}.method_id"),
        fingerprint=_checksum(
            raw["fingerprint"],
            location=f"{location}.fingerprint",
        ),
    )


def _parse_generation(value: object) -> CandidateGeneration:
    raw = _mapping(value, location="candidate_generation")
    _exact_keys(raw, _GENERATION_KEYS, location="candidate_generation")
    methods = tuple(
        _parse_method(item, index=index)
        for index, item in enumerate(
            _array(raw["methods"], location="candidate_generation.methods")
        )
    )
    if not methods or len(methods) > _MAX_METHODS:
        raise TopicReviewError(
            f"candidate_generation.methods must contain 1 through {_MAX_METHODS} methods"
        )
    if methods != tuple(sorted(methods, key=lambda item: item.method_id)):
        raise TopicReviewError(
            "candidate_generation.methods must be sorted by method_id"
        )
    if len({item.method_id for item in methods}) != len(methods):
        raise TopicReviewError("candidate_generation.methods contains duplicates")
    generator = _text(
        raw["generator"],
        location="candidate_generation.generator",
        max_bytes=128,
    )
    version = _positive_bounded_integer(
        raw["generator_version"],
        location="candidate_generation.generator_version",
        maximum=1_000_000,
    )
    if generator != TOPIC_REVIEW_GENERATOR or version != TOPIC_REVIEW_GENERATOR_VERSION:
        raise TopicReviewError("unsupported topic candidate generator identity")
    return CandidateGeneration(
        candidate_limit_per_method=_positive_bounded_integer(
            raw["candidate_limit_per_method"],
            location="candidate_generation.candidate_limit_per_method",
            maximum=_MAX_CANDIDATES_PER_METHOD,
        ),
        generator=generator,
        generator_version=version,
        methods=methods,
    )


def _blind_id(dataset_id: str, query_id: str, doc_id: DocId) -> str:
    payload = f"{dataset_id}\0{query_id}\0{doc_id!s}".encode()
    return f"topic-candidate-{hashlib.sha256(payload).hexdigest()[:24]}"


def _parse_candidate(
    value: object,
    *,
    dataset_id: str,
    query_id: str,
    query_index: int,
    candidate_index: int,
) -> TopicCandidate:
    location = f"queries[{query_index}].candidates[{candidate_index}]"
    raw = _mapping(value, location=location)
    _exact_keys(raw, _CANDIDATE_KEYS, location=location)
    blind_id = _text(raw["blind_id"], location=f"{location}.blind_id", max_bytes=40)
    if _BLIND_ID_RE.fullmatch(blind_id) is None:
        raise TopicReviewError(f"{location}.blind_id is malformed")
    doc_id = _doc_id(raw["doc_id"], location=f"{location}.doc_id")
    if blind_id != _blind_id(dataset_id, query_id, doc_id):
        raise TopicReviewError(f"{location}.blind_id does not match its DocId")
    try:
        judgement = CandidateJudgement(raw["judgement"])
    except (TypeError, ValueError) as exc:
        raise TopicReviewError(
            f"{location}.judgement must be pending, relevant, or not-relevant"
        ) from exc
    return TopicCandidate(blind_id, doc_id, judgement)


def _parse_review_query(
    value: object,
    *,
    dataset_id: str,
    index: int,
    maximum_candidates: int,
) -> TopicReviewQuery:
    location = f"queries[{index}]"
    raw = _mapping(value, location=location)
    _exact_keys(raw, _QUERY_KEYS, location=location)
    query_id = _identifier(raw["query_id"], location=f"{location}.query_id")
    candidates = tuple(
        _parse_candidate(
            item,
            dataset_id=dataset_id,
            query_id=query_id,
            query_index=index,
            candidate_index=candidate_index,
        )
        for candidate_index, item in enumerate(
            _array(raw["candidates"], location=f"{location}.candidates")
        )
    )
    if len(candidates) > maximum_candidates:
        raise TopicReviewError(
            f"{location}.candidates exceeds the declared method pool bound"
        )
    if candidates != tuple(sorted(candidates, key=lambda item: item.blind_id)):
        raise TopicReviewError(f"{location}.candidates must be sorted by blind_id")
    if len({candidate.blind_id for candidate in candidates}) != len(candidates):
        raise TopicReviewError(f"{location}.candidates contains duplicate blind IDs")
    if len({candidate.doc_id for candidate in candidates}) != len(candidates):
        raise TopicReviewError(f"{location}.candidates contains duplicate DocIds")
    additional = _doc_ids(
        raw["additional_relevant_doc_ids"],
        location=f"{location}.additional_relevant_doc_ids",
    )
    overlap = set(additional) & {candidate.doc_id for candidate in candidates}
    if overlap:
        raise TopicReviewError(
            f"{location}.additional_relevant_doc_ids duplicates a pooled candidate"
        )
    complete = raw["candidate_pool_complete"]
    if not isinstance(complete, bool):
        raise TopicReviewError(f"{location}.candidate_pool_complete must be a boolean")
    return TopicReviewQuery(
        query_id=query_id,
        query=_text(
            raw["query"],
            location=f"{location}.query",
            max_bytes=_MAX_QUERY_BYTES,
            normalized=True,
        ),
        candidates=candidates,
        additional_relevant_doc_ids=additional,
        candidate_pool_complete=complete,
    )


def _parse_review_provenance(value: object) -> ReviewProvenance:
    raw = _mapping(value, location="labels.review")
    _exact_keys(raw, _REVIEW_KEYS, location="labels.review")
    reviewed_at_raw = _text(
        raw["reviewed_at"],
        location="labels.review.reviewed_at",
        max_bytes=10,
    )
    try:
        reviewed_at = date.fromisoformat(reviewed_at_raw)
    except ValueError as exc:
        raise TopicReviewError(
            "labels.review.reviewed_at must be an ISO calendar date"
        ) from exc
    reviewer = _text(
        raw["reviewer"],
        location="labels.review.reviewer",
        max_bytes=_MAX_REVIEW_TEXT_BYTES,
    )
    review_ref = _text(
        raw["review_ref"],
        location="labels.review.review_ref",
        max_bytes=_MAX_REVIEW_TEXT_BYTES,
    )
    if reviewer != TOPIC_REVIEW_OWNER:
        raise TopicReviewError(
            f"labels.review.reviewer must be exactly {TOPIC_REVIEW_OWNER}"
        )
    if _REVIEW_REF_RE.fullmatch(review_ref) is None:
        raise TopicReviewError(
            "labels.review.review_ref must be an exact git:<40-hex-commit> reference"
        )
    return ReviewProvenance(
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        review_ref=review_ref,
    )


def _review_payload_dict(
    *,
    candidate_generation: CandidateGeneration,
    corpus: CorpusIdentity,
    dataset_id: str,
    queries: Sequence[TopicReviewQuery],
    seed_checksum: str,
) -> dict[str, object]:
    return {
        "candidate_generation": candidate_generation.as_dict(),
        "corpus": corpus.as_dict(),
        "dataset_id": dataset_id,
        "queries": [query.as_dict() for query in queries],
        "schema": TOPIC_REVIEW_SCHEMA,
        "seed_checksum": seed_checksum,
    }


def _review_payload_checksum(
    *,
    candidate_generation: CandidateGeneration,
    corpus: CorpusIdentity,
    dataset_id: str,
    queries: Sequence[TopicReviewQuery],
    seed_checksum: str,
) -> str:
    return json_checksum(
        canonical_json_bytes(
            _review_payload_dict(
                candidate_generation=candidate_generation,
                corpus=corpus,
                dataset_id=dataset_id,
                queries=queries,
                seed_checksum=seed_checksum,
            )
        )
    )


def review_payload_checksum(review: TopicReview) -> str:
    """Checksum the exact owner-reviewed decisions and candidate provenance."""

    return _review_payload_checksum(
        candidate_generation=review.candidate_generation,
        corpus=review.corpus,
        dataset_id=review.dataset_id,
        queries=review.queries,
        seed_checksum=review.seed_checksum,
    )


def _require_ready_queries(queries: Sequence[TopicReviewQuery]) -> None:
    pending = [
        (query.query_id, candidate.blind_id)
        for query in queries
        for candidate in query.candidates
        if candidate.judgement is CandidateJudgement.PENDING
    ]
    if pending:
        raise TopicReviewError(
            f"topic review still has {len(pending)} pending candidate judgements"
        )
    incomplete = [
        query.query_id for query in queries if not query.candidate_pool_complete
    ]
    if incomplete:
        raise TopicReviewError(
            "owner must attest candidate pool completeness for every query: "
            + ", ".join(incomplete)
        )
    empty = [query.query_id for query in queries if not query.relevant_doc_ids]
    if empty:
        raise TopicReviewError(
            "every topic query requires at least one relevant document: "
            + ", ".join(empty)
        )


def _parse_labels(
    value: object,
    *,
    candidate_generation: CandidateGeneration,
    corpus: CorpusIdentity,
    dataset_id: str,
    queries: Sequence[TopicReviewQuery],
    seed_checksum: str,
) -> TopicReviewLabels:
    raw = _mapping(value, location="labels")
    _exact_keys(raw, _LABEL_KEYS, location="labels")
    try:
        status = TopicReviewStatus(raw["status"])
    except (TypeError, ValueError) as exc:
        raise TopicReviewError(
            "labels.status must be pending-owner-review or owner-reviewed"
        ) from exc
    review = None if raw["review"] is None else _parse_review_provenance(raw["review"])
    raw_checksum = raw["reviewed_payload_checksum"]
    reviewed_checksum = (
        None
        if raw_checksum is None
        else _checksum(raw_checksum, location="labels.reviewed_payload_checksum")
    )
    if status is TopicReviewStatus.PENDING:
        if review is not None or reviewed_checksum is not None:
            raise TopicReviewError(
                "pending topic review cannot carry review provenance or a reviewed checksum"
            )
    else:
        _require_ready_queries(queries)
        if review is None:
            raise TopicReviewError(
                "owner-reviewed topic labels require review provenance"
            )
        expected = _review_payload_checksum(
            candidate_generation=candidate_generation,
            corpus=corpus,
            dataset_id=dataset_id,
            queries=queries,
            seed_checksum=seed_checksum,
        )
        if reviewed_checksum != expected:
            raise TopicReviewError(
                "owner-reviewed topic labels must checksum the exact review payload"
            )
    return TopicReviewLabels(status, reviewed_checksum, review)


def parse_topic_review(value: object, *, checksum: str) -> TopicReview:
    raw = _mapping(value, location="$")
    _exact_keys(raw, _REVIEW_ROOT_KEYS, location="$")
    if raw["schema"] != TOPIC_REVIEW_SCHEMA:
        raise TopicReviewError(f"unsupported topic review schema: {raw['schema']!r}")
    parsed_checksum = _checksum(checksum, location="topic review checksum")
    dataset_id = _identifier(raw["dataset_id"], location="dataset_id")
    seed_checksum = _checksum(raw["seed_checksum"], location="seed_checksum")
    corpus = _parse_corpus(raw["corpus"])
    generation = _parse_generation(raw["candidate_generation"])
    queries = tuple(
        _parse_review_query(
            item,
            dataset_id=dataset_id,
            index=index,
            maximum_candidates=(
                generation.candidate_limit_per_method * len(generation.methods)
            ),
        )
        for index, item in enumerate(_array(raw["queries"], location="queries"))
    )
    if not queries or len(queries) > _MAX_QUERIES:
        raise TopicReviewError(
            f"topic review must contain 1 through {_MAX_QUERIES} queries"
        )
    if queries != tuple(sorted(queries, key=lambda item: (item.query, item.query_id))):
        raise TopicReviewError(
            "topic review queries must be sorted by query and query_id"
        )
    if len({item.query_id for item in queries}) != len(queries):
        raise TopicReviewError("topic review contains duplicate query_id values")
    if len({item.query for item in queries}) != len(queries):
        raise TopicReviewError("topic review contains duplicate query values")
    if any(
        len(query.additional_relevant_doc_ids) > corpus.document_count
        for query in queries
    ):
        raise TopicReviewError(
            "topic review manual relevant labels exceed the corpus document count"
        )
    labels = _parse_labels(
        raw["labels"],
        candidate_generation=generation,
        corpus=corpus,
        dataset_id=dataset_id,
        queries=queries,
        seed_checksum=seed_checksum,
    )
    return TopicReview(
        dataset_id=dataset_id,
        seed_checksum=seed_checksum,
        corpus=corpus,
        candidate_generation=generation,
        labels=labels,
        queries=queries,
        checksum=parsed_checksum,
    )


def load_topic_review(path: Path) -> TopicReview:
    try:
        value, payload = load_canonical_json(path)
        return parse_topic_review(value, checksum=json_checksum(payload))
    except StrictJsonError as exc:
        raise TopicReviewError(str(exc)) from exc


def _corpus_identity(corpus: Corpus, *, content_tree_sha: str) -> CorpusIdentity:
    if _GIT_TREE_RE.fullmatch(content_tree_sha) is None:
        raise TopicReviewError("content_tree_sha must be a full lowercase git tree SHA")
    manifest_tree = getattr(corpus, "content_git_tree_sha", None)
    if manifest_tree != content_tree_sha:
        raise TopicReviewError(
            "requested content tree differs from the verified corpus manifest"
        )
    fingerprint = getattr(corpus, "fingerprint", None)
    if not isinstance(fingerprint, str) or _SHA256_RE.fullmatch(fingerprint) is None:
        raise TopicReviewError("verified corpus must expose a sha256 fingerprint")
    doc_ids = tuple(DocId(value) for value in corpus.doc_ids())
    if doc_ids != tuple(sorted(set(doc_ids), key=str)):
        raise TopicReviewError("verified corpus DocIds must be sorted and unique")
    return CorpusIdentity(len(doc_ids), fingerprint, content_tree_sha)


def _close_resolved(resolved: ResolvedRetriever, *, method_id: str) -> None:
    try:
        close = getattr(resolved.implementation, "close", None)
        if callable(close):
            close()
    except Exception as exc:
        raise TopicReviewError(
            f"cannot close candidate retriever {method_id!r}: {exc}"
        ) from exc


def _candidate_ranking(
    resolved: ResolvedRetriever,
    *,
    query: TopicSeedQuery,
    limit: int,
    available: frozenset[DocId],
) -> tuple[DocId, ...]:
    try:
        retrieval = resolved.retrieve(query.query, limit=limit)
        ranking = retrieval.doc_ids()
    except Exception as exc:
        raise TopicReviewError(
            f"candidate retriever {resolved.method_id!r} failed for "
            f"{query.query_id!r}: {exc}"
        ) from exc
    if retrieval.query != query.query:
        raise TopicReviewError(
            f"candidate retriever {resolved.method_id!r} changed the query text"
        )
    if not isinstance(ranking, tuple) or not all(
        isinstance(doc_id, DocId) for doc_id in ranking
    ):
        raise TopicReviewError(
            f"candidate retriever {resolved.method_id!r} returned an invalid ranking"
        )
    if len(ranking) > limit or len(ranking) != len(set(ranking)):
        raise TopicReviewError(
            f"candidate retriever {resolved.method_id!r} violated the ranking limit"
        )
    outside = sorted(set(ranking) - available, key=str)
    if outside:
        raise TopicReviewError(
            f"candidate retriever {resolved.method_id!r} returned documents outside "
            "the verified corpus: " + ", ".join(map(str, outside))
        )
    return ranking


def generate_topic_review(
    *,
    corpus: Corpus,
    seed: TopicSeed,
    content_tree_sha: str,
    registry: RetrieverRegistry = default_registry,
) -> TopicReview:
    """Pool the seed-pinned rankings without converting retrieval output into qrels."""

    identity = _corpus_identity(corpus, content_tree_sha=content_tree_sha)
    limit = seed.candidate_limit_per_method

    available = frozenset(DocId(value) for value in corpus.doc_ids())
    pools: dict[str, set[DocId]] = {query.query_id: set() for query in seed.queries}
    methods: list[CandidateMethod] = []
    for method_id in seed.method_ids:
        try:
            resolved = registry.retrievable.create(method_id, corpus)
        except Exception as exc:
            raise TopicReviewError(
                f"cannot create candidate retriever {method_id!r}: {exc}"
            ) from exc
        try:
            methods.append(CandidateMethod(method_id, resolved.fingerprint))
            for query in seed.queries:
                pools[query.query_id].update(
                    _candidate_ranking(
                        resolved,
                        query=query,
                        limit=limit,
                        available=available,
                    )
                )
        finally:
            _close_resolved(resolved, method_id=method_id)

    generation = CandidateGeneration(
        candidate_limit_per_method=limit,
        generator=TOPIC_REVIEW_GENERATOR,
        generator_version=TOPIC_REVIEW_GENERATOR_VERSION,
        methods=tuple(methods),
    )
    queries = tuple(
        TopicReviewQuery(
            query_id=query.query_id,
            query=query.query,
            candidates=tuple(
                sorted(
                    (
                        TopicCandidate(
                            blind_id=_blind_id(seed.dataset_id, query.query_id, doc_id),
                            doc_id=doc_id,
                            judgement=CandidateJudgement.PENDING,
                        )
                        for doc_id in pools[query.query_id]
                    ),
                    key=lambda item: item.blind_id,
                )
            ),
            additional_relevant_doc_ids=(),
            candidate_pool_complete=False,
        )
        for query in seed.queries
    )
    value = {
        **_review_payload_dict(
            candidate_generation=generation,
            corpus=identity,
            dataset_id=seed.dataset_id,
            queries=queries,
            seed_checksum=seed.checksum,
        ),
        "labels": {
            "review": None,
            "reviewed_payload_checksum": None,
            "status": TopicReviewStatus.PENDING.value,
        },
    }
    payload = canonical_json_bytes(value)
    return parse_topic_review(
        load_json_bytes(payload, location="generated topic review"),
        checksum=json_checksum(payload),
    )


def verify_topic_review(
    review: TopicReview,
    *,
    seed: TopicSeed,
    corpus: Corpus,
    content_tree_sha: str,
    registry: RetrieverRegistry = default_registry,
) -> None:
    """Replay the blind pool and reject corpus, seed, or method identity drift."""

    if review.dataset_id != seed.dataset_id or review.seed_checksum != seed.checksum:
        raise TopicReviewError("topic review differs from the exact topic seed")
    expected_identity = _corpus_identity(corpus, content_tree_sha=content_tree_sha)
    if review.corpus != expected_identity:
        raise TopicReviewError("topic review differs from the verified corpus identity")
    expected = generate_topic_review(
        corpus=corpus,
        seed=seed,
        content_tree_sha=content_tree_sha,
        registry=registry,
    )
    if review.candidate_generation != expected.candidate_generation:
        raise TopicReviewError(
            "topic review candidate generation differs from the reviewed registry"
        )
    actual_pool = tuple(
        (
            query.query_id,
            query.query,
            tuple(
                (candidate.blind_id, candidate.doc_id) for candidate in query.candidates
            ),
        )
        for query in review.queries
    )
    expected_pool = tuple(
        (
            query.query_id,
            query.query,
            tuple(
                (candidate.blind_id, candidate.doc_id) for candidate in query.candidates
            ),
        )
        for query in expected.queries
    )
    if actual_pool != expected_pool:
        raise TopicReviewError(
            "topic review candidate pool differs from deterministic generation"
        )
    available = frozenset(DocId(value) for value in corpus.doc_ids())
    manual = {
        doc_id
        for query in review.queries
        for doc_id in query.additional_relevant_doc_ids
    }
    outside = tuple(sorted(manual - available, key=str))
    if outside:
        raise TopicReviewError(
            "manual topic labels reference documents outside the verified corpus: "
            + ", ".join(map(str, outside))
        )


def seal_topic_review(
    review: TopicReview,
    *,
    reviewer: str,
    reviewed_at: str,
    review_ref: str,
) -> TopicReview:
    """Bind explicit owner provenance to a complete set of manual judgements."""

    if review.labels.status is not TopicReviewStatus.PENDING:
        raise TopicReviewError("only a pending topic review can be sealed")
    _require_ready_queries(review.queries)
    provenance = _parse_review_provenance(
        {
            "review_ref": review_ref,
            "reviewed_at": reviewed_at,
            "reviewer": reviewer,
        }
    )
    value = review.as_dict()
    value["labels"] = {
        "review": provenance.as_dict(),
        "reviewed_payload_checksum": review_payload_checksum(review),
        "status": TopicReviewStatus.OWNER_REVIEWED.value,
    }
    payload = canonical_json_bytes(value)
    return parse_topic_review(
        load_json_bytes(payload, location="sealed topic review"),
        checksum=json_checksum(payload),
    )


def finalize_topic_queryset(
    review: TopicReview,
    *,
    seed: TopicSeed,
    corpus: Corpus,
    content_tree_sha: str,
    registry: RetrieverRegistry = default_registry,
) -> QuerySet:
    """Materialize owner-reviewed topic qrels; pending manifests always fail."""

    if review.labels.status is not TopicReviewStatus.OWNER_REVIEWED:
        raise TopicReviewError("finalization requires an owner-reviewed topic manifest")
    verify_topic_review(
        review,
        seed=seed,
        corpus=corpus,
        content_tree_sha=content_tree_sha,
        registry=registry,
    )
    provenance = review.labels.review
    if provenance is None:  # The parser already enforces this; retain a typed guard.
        raise TopicReviewError("owner-reviewed topic manifest lacks review provenance")
    qrels = tuple(
        Qrel(
            query_id=query.query_id,
            query=query.query,
            relevant_doc_ids=query.relevant_doc_ids,
            evidence=tuple(
                Evidence(
                    kind="owner-topic-review",
                    source_doc_id=doc_id,
                    target=f"{review.dataset_id}:{query.query_id}",
                    occurrences=1,
                )
                for doc_id in query.relevant_doc_ids
            ),
        )
        for query in review.queries
    )
    reviewed_candidates = sum(
        len(query.candidates) + len(query.additional_relevant_doc_ids)
        for query in review.queries
    )
    relevant_count = sum(len(qrel.relevant_doc_ids) for qrel in qrels)
    value = {
        "corpus": review.corpus.as_dict(),
        "dataset_id": review.dataset_id,
        "dataset_kind": DatasetKind.TOPIC.value,
        "exclusions": [],
        "labels": {
            "review": provenance.as_dict(),
            "reviewed_qrels_checksum": qrels_checksum(qrels),
            "status": LabelStatus.OWNER_REVIEWED.value,
        },
        "pooling": {
            "candidate_limit_per_method": (
                review.candidate_generation.candidate_limit_per_method
            ),
            "methods": [
                method.as_dict() for method in review.candidate_generation.methods
            ],
            "review_manifest_checksum": review.checksum,
            "seed_checksum": review.seed_checksum,
        },
        "provenance": {
            "generator": TOPIC_REVIEW_GENERATOR,
            "generator_version": TOPIC_REVIEW_GENERATOR_VERSION,
            "included_occurrence_count": relevant_count,
            "source_artifacts": [],
            "source_occurrence_count": reviewed_candidates,
        },
        "qrels": [qrel.as_dict() for qrel in qrels],
        "schema": QUERYSET_SCHEMA,
    }
    payload = canonical_json_bytes(value)
    dataset = parse_queryset(
        load_json_bytes(payload, location="finalized topic queryset"),
        checksum=json_checksum(payload),
    )
    validate_queryset_corpus(
        dataset,
        corpus,
        content_tree_sha=content_tree_sha,
    )
    return dataset


def write_topic_seed(path: Path, seed: TopicSeed) -> None:
    write_bytes_atomic(path, canonical_json_bytes(seed.as_dict()))


def write_topic_review(path: Path, review: TopicReview) -> None:
    write_bytes_atomic(path, canonical_json_bytes(review.as_dict()))


def write_topic_review_once(path: Path, review: TopicReview) -> None:
    """Create a generated review once; preserve identical bytes and reject overwrite."""

    payload = canonical_json_bytes(review.as_dict())
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise TopicReviewError(
                f"cannot inspect existing topic review {path}"
            ) from exc
        if existing != payload:
            raise TopicReviewError(
                "refusing to overwrite an existing topic review; use --check"
            ) from None


__all__ = [
    "CandidateGeneration",
    "CandidateJudgement",
    "CandidateMethod",
    "TOPIC_REVIEW_GENERATOR",
    "TOPIC_REVIEW_GENERATOR_VERSION",
    "TOPIC_REVIEW_OWNER",
    "TOPIC_REVIEW_SCHEMA",
    "TOPIC_SEED_SCHEMA",
    "TopicCandidate",
    "TopicReview",
    "TopicReviewError",
    "TopicReviewLabels",
    "TopicReviewQuery",
    "TopicReviewStatus",
    "TopicSeed",
    "TopicSeedQuery",
    "finalize_topic_queryset",
    "generate_topic_review",
    "load_topic_review",
    "load_topic_seed",
    "parse_topic_review",
    "parse_topic_seed",
    "review_payload_checksum",
    "seal_topic_review",
    "verify_topic_review",
    "write_topic_review",
    "write_topic_review_once",
    "write_topic_seed",
]
