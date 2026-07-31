"""Field-weighted BM25 over the verified Korean BM25 vocabulary and IDFs.

The method deliberately reuses the corrected baseline's verified tokenizer,
dictionary, and fitted term IDFs.  Only field-aware term-frequency saturation differs,
so an evaluation compares title/tag/body weighting instead of accidentally comparing a
second tokenizer or another IDF variant.
"""

from __future__ import annotations

import json
import math
import threading
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from agent.retrieval.bm25 import (
    BM25_CONFIG,
    BM25_IMPLEMENTATION_ID,
    BM25_METHOD_ID,
    K1,
    _KiwiTokenizer,
    _load_descriptor,
    _snapshot_connection,
    _validate_evidence,
    _validate_fitted,
)
from agent.retrieval.corpus import CATALOG_SCHEMA, PublishedCorpus, content_checksum
from agent.retrieval.fingerprint import canonical_config, retriever_fingerprint
from agent.retrieval.protocol import Corpus, DocId, Hit, Retrieval
from agent.retrieval.registry import registry

FIELD_WEIGHTED_METHOD_ID = "bm25-field-weighted"
FIELD_WEIGHTED_IMPLEMENTATION_ID = "agent.retrieval.field_weighted:create@1"
FIELD_NAMES = ("body", "tags", "title")
FIELD_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "body": 1.0,
        "tags": 2.0,
        "title": 3.0,
    }
)
FIELD_LENGTH_NORMALIZATION: Mapping[str, float] = MappingProxyType(
    {
        "body": 0.75,
        "tags": 0.0,
        "title": 0.0,
    }
)


def _freeze_config_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_config(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_config_value(item) for item in value)
    return value


def _freeze_config(value: Mapping[str, object]) -> Mapping[str, object]:
    """Detach and recursively freeze a reviewed portable configuration."""

    return MappingProxyType(
        {key: _freeze_config_value(item) for key, item in value.items()}
    )


FIELD_WEIGHTED_CONFIG: Mapping[str, object] = _freeze_config(
    {
        "algorithm": "BM25F",
        "body_sources": ["frontmatter-description", "markdown-body"],
        "field_length_normalization": FIELD_LENGTH_NORMALIZATION,
        "field_statistics": "runtime-derived-from-verified-published-mirror",
        "field_weights": FIELD_WEIGHTS,
        "idf_source": {
            "algorithm": "BM25Okapi",
            "method_id": BM25_METHOD_ID,
            "role": "verified-fitted-term-idf",
        },
        "k1": K1,
        "positive_scores_only": True,
        "query_term_frequency": "linear",
        "tokenizer_source": {
            "config": BM25_CONFIG["tokenizer"],
            "method_id": BM25_METHOD_ID,
        },
    }
)

_CATALOG_KEYS = frozenset(
    {"corpus_fingerprint", "document_count", "documents", "schema"}
)
_CATALOG_ENTRY_KEYS = frozenset(
    {
        "category",
        "date",
        "description",
        "doc_id",
        "metadata",
        "tags",
        "title",
    }
)


class FieldWeightedBm25Error(ValueError):
    """The field-weighted method cannot trust its config or corpus inputs."""


@dataclass(frozen=True, slots=True)
class _FieldDocument:
    doc_id: DocId
    title: str
    tags: tuple[str, ...]
    description: str
    body: str


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FieldWeightedBm25Error(
                f"duplicate JSON key in catalog artifact: {key!r}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise FieldWeightedBm25Error(
        f"non-finite JSON constant in catalog artifact: {value}"
    )


def _exact_keys(
    value: Mapping[str, object],
    *,
    expected: frozenset[str],
    location: str,
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise FieldWeightedBm25Error(
            f"{location} is missing required keys: {', '.join(missing)}"
        )
    if unknown:
        raise FieldWeightedBm25Error(
            f"{location} contains unknown keys: {', '.join(unknown)}"
        )


def _published_body(text: str, *, doc_id: DocId) -> str:
    """Recover the build-validated Markdown body without reparsing YAML.

    This mirrors the delimiter handling in ``corpus_build._split_frontmatter``.
    Frontmatter semantics remain owned by the build; retrieval only removes the already
    validated block so title/tags are not counted twice through raw YAML.
    """

    parsed = text.removeprefix("\ufeff")
    lines = parsed.splitlines(keepends=True)
    if not lines:
        return text
    opener = lines[0].rstrip("\r\n")
    if not opener.startswith("---") or opener.startswith("----"):
        return text
    language = opener[3:].strip()
    if language not in {"", "yaml"}:
        raise FieldWeightedBm25Error(
            f"{doc_id}: published frontmatter language drifted after the corpus build"
        )
    for index, line in enumerate(lines[1:], start=1):
        delimiter = line.rstrip("\r\n")
        if delimiter.startswith("---"):
            if delimiter[3:].strip():
                raise FieldWeightedBm25Error(
                    f"{doc_id}: published frontmatter delimiter drifted after the build"
                )
            return "".join(lines[index + 1 :])
    raise FieldWeightedBm25Error(
        f"{doc_id}: published frontmatter lost its closing delimiter"
    )


def _load_field_documents(corpus: PublishedCorpus) -> tuple[_FieldDocument, ...]:
    try:
        payload = json.loads(
            corpus.read_artifact("catalog.json"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except FieldWeightedBm25Error:
        raise
    except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise FieldWeightedBm25Error(f"cannot read catalog artifact: {exc}") from exc
    if not isinstance(payload, dict):
        raise FieldWeightedBm25Error("catalog artifact root must be an object")
    _exact_keys(payload, expected=_CATALOG_KEYS, location="catalog")
    if payload["schema"] != CATALOG_SCHEMA:
        raise FieldWeightedBm25Error("unsupported catalog schema")
    if payload["corpus_fingerprint"] != corpus.fingerprint:
        raise FieldWeightedBm25Error("catalog corpus fingerprint mismatch")
    raw_documents = payload["documents"]
    if not isinstance(raw_documents, list):
        raise FieldWeightedBm25Error("catalog.documents must be an array")
    if type(payload["document_count"]) is not int or payload["document_count"] != len(
        raw_documents
    ):
        raise FieldWeightedBm25Error("catalog document_count mismatch")

    documents: list[_FieldDocument] = []
    for index, raw in enumerate(raw_documents):
        location = f"catalog.documents[{index}]"
        if not isinstance(raw, dict):
            raise FieldWeightedBm25Error(f"{location} must be an object")
        _exact_keys(raw, expected=_CATALOG_ENTRY_KEYS, location=location)
        try:
            doc_id = DocId(raw["doc_id"])
        except (TypeError, ValueError) as exc:
            raise FieldWeightedBm25Error(f"{location}.doc_id is invalid") from exc
        title = raw["title"]
        description = raw["description"]
        tags = raw["tags"]
        if not isinstance(title, str):
            raise FieldWeightedBm25Error(f"{location}.title must be a string")
        if not isinstance(description, str):
            raise FieldWeightedBm25Error(f"{location}.description must be a string")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise FieldWeightedBm25Error(f"{location}.tags must be a string array")
        documents.append(
            _FieldDocument(
                doc_id=doc_id,
                title=title,
                tags=tuple(tags),
                description=description,
                body=_published_body(corpus.read(doc_id), doc_id=doc_id),
            )
        )

    doc_ids = tuple(document.doc_id for document in documents)
    if doc_ids != tuple(corpus.doc_ids()):
        raise FieldWeightedBm25Error(
            "catalog DocIds do not exactly match the published corpus"
        )
    return tuple(documents)


def _baseline_fingerprint(
    *,
    corpus: Corpus,
    baseline_identity: Mapping[str, object],
) -> str:
    return retriever_fingerprint(
        method_id=BM25_METHOD_ID,
        implementation_id=BM25_IMPLEMENTATION_ID,
        config=baseline_identity,
        corpus_fingerprint=corpus.fingerprint,
    )


def _identity_config(
    *,
    corpus: Corpus,
    method_config: Mapping[str, object],
    baseline_identity: Mapping[str, object],
    catalog_checksum: str,
) -> dict[str, object]:
    return {
        **json.loads(canonical_config(method_config)),
        "bm25_dependency": {
            "fingerprint": _baseline_fingerprint(
                corpus=corpus,
                baseline_identity=baseline_identity,
            ),
            "implementation_id": BM25_IMPLEMENTATION_ID,
            "method_id": BM25_METHOD_ID,
        },
        "catalog_sha256": catalog_checksum,
    }


class FieldWeightedBm25Retriever:
    """BM25F arm using title=3, tags=2, and body=1 fixed reviewed boosts."""

    def __init__(
        self,
        corpus: Corpus,
        config: Mapping[str, object] = FIELD_WEIGHTED_CONFIG,
    ) -> None:
        config_json = canonical_config(config)
        if config_json != canonical_config(FIELD_WEIGHTED_CONFIG):
            raise FieldWeightedBm25Error(
                "registered field-weighted config does not match implementation"
            )
        method_config = _freeze_config(json.loads(config_json))
        if not isinstance(corpus, PublishedCorpus):
            raise TypeError("FieldWeightedBm25Retriever requires a PublishedCorpus")

        descriptor = _load_descriptor(corpus)
        _validate_evidence(descriptor, corpus=corpus)
        connection = _snapshot_connection(descriptor.fitted_payload)
        try:
            _validate_fitted(descriptor, corpus=corpus, connection=connection)
            idf_by_token = {
                token: float(idf)
                for token, idf in connection.execute(
                    "SELECT token, idf FROM terms ORDER BY term_id"
                )
            }
        finally:
            connection.close()
        tokenizer = _KiwiTokenizer(
            descriptor.dictionary_payload,
            descriptor.entries,
        )
        documents = _load_field_documents(corpus)

        field_lengths: dict[str, list[int]] = {field: [] for field in FIELD_NAMES}
        postings: dict[str, list[tuple[int, str, int]]] = defaultdict(list)
        for doc_index, document in enumerate(documents):
            field_tokens: dict[str, list[str]] = {
                "body": [
                    *tokenizer.tokenize(document.description),
                    *tokenizer.tokenize(document.body),
                ],
                "tags": [
                    token for tag in document.tags for token in tokenizer.tokenize(tag)
                ],
                "title": tokenizer.tokenize(document.title),
            }
            for field in FIELD_NAMES:
                tokens = field_tokens[field]
                field_lengths[field].append(len(tokens))
                for token, frequency in sorted(Counter(tokens).items()):
                    postings[token].append((doc_index, field, frequency))

        self._lock = threading.RLock()
        self._tokenizer = tokenizer
        self._corpus = corpus
        self._doc_ids = tuple(document.doc_id for document in documents)
        self._idf_by_token = idf_by_token
        self._postings = {
            token: tuple(values) for token, values in sorted(postings.items())
        }
        self._field_lengths = {
            field: tuple(values) for field, values in field_lengths.items()
        }
        self._average_field_lengths = {
            field: (sum(lengths) / len(lengths) if lengths else 0.0)
            for field, lengths in self._field_lengths.items()
        }
        configured_weights = method_config["field_weights"]
        configured_normalization = method_config["field_length_normalization"]
        if not isinstance(configured_weights, Mapping) or not isinstance(
            configured_normalization,
            Mapping,
        ):
            raise FieldWeightedBm25Error("field config must be an object")
        self._field_weights = MappingProxyType(
            {field: float(configured_weights[field]) for field in FIELD_NAMES}
        )
        self._field_length_normalization = MappingProxyType(
            {field: float(configured_normalization[field]) for field in FIELD_NAMES}
        )
        self._identity = _identity_config(
            corpus=corpus,
            method_config=method_config,
            baseline_identity=descriptor.identity,
            catalog_checksum=content_checksum(corpus.read_artifact("catalog.json")),
        )

    @property
    def identity_config(self) -> dict[str, object]:
        return json.loads(canonical_config(self._identity))

    @property
    def fingerprint(self) -> str:
        return retriever_fingerprint(
            method_id=FIELD_WEIGHTED_METHOD_ID,
            implementation_id=FIELD_WEIGHTED_IMPLEMENTATION_ID,
            config=self._identity,
            corpus_fingerprint=self._corpus.fingerprint,
        )

    def tokenize(self, text: str) -> tuple[str, ...]:
        """Expose the shared verified tokenizer for contract tests."""

        with self._lock:
            return tuple(self._tokenizer.tokenize(text))

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0 or not self._doc_ids:
            return Retrieval(query=query)
        with self._lock:
            query_tokens = tuple(self._tokenizer.tokenize(query))
        if not query_tokens:
            return Retrieval(query=query)

        scores: dict[int, float] = defaultdict(float)
        matched_fields: dict[int, set[str]] = defaultdict(set)
        for token, query_frequency in sorted(Counter(query_tokens).items()):
            idf = self._idf_by_token.get(token)
            if idf is None:
                continue
            weighted_frequencies: dict[int, float] = defaultdict(float)
            for doc_index, field, term_frequency in self._postings.get(token, ()):
                average_length = self._average_field_lengths[field]
                length_ratio = (
                    self._field_lengths[field][doc_index] / average_length
                    if average_length
                    else 0.0
                )
                b = self._field_length_normalization[field]
                normalization = 1.0 - b + b * length_ratio
                weighted_frequencies[doc_index] += (
                    self._field_weights[field] * term_frequency / normalization
                )
                matched_fields[doc_index].add(field)
            for doc_index, weighted_frequency in weighted_frequencies.items():
                scores[doc_index] += (
                    query_frequency
                    * idf
                    * (weighted_frequency * (K1 + 1.0) / (weighted_frequency + K1))
                )

        ordered = sorted(
            (
                (score, self._doc_ids[doc_index], doc_index)
                for doc_index, score in scores.items()
                if math.isfinite(score) and score > 0.0
            ),
            key=lambda item: (-item[0], str(item[1])),
        )
        return Retrieval(
            query=query,
            hits=tuple(
                Hit(
                    doc_id=doc_id,
                    rank=rank,
                    score=score,
                    metadata={
                        "matched_fields": sorted(matched_fields[doc_index]),
                    },
                )
                for rank, (score, doc_id, doc_index) in enumerate(
                    ordered[:limit],
                    start=1,
                )
            ),
        )


def create(
    corpus: Corpus,
    config: Mapping[str, object],
) -> FieldWeightedBm25Retriever:
    """Construct the exact shared serving/evaluation implementation."""

    return FieldWeightedBm25Retriever(corpus, config)


def field_weighted_identity(
    corpus: Corpus,
    config: Mapping[str, object],
) -> Mapping[str, object]:
    """Bind the arm to the exact verified BM25 dictionary and fitted IDF artifact."""

    config_json = canonical_config(config)
    if config_json != canonical_config(FIELD_WEIGHTED_CONFIG):
        raise FieldWeightedBm25Error(
            "registered field-weighted config does not match implementation"
        )
    method_config = _freeze_config(json.loads(config_json))
    descriptor = _load_descriptor(corpus)
    return _identity_config(
        corpus=corpus,
        method_config=method_config,
        baseline_identity=descriptor.identity,
        catalog_checksum=content_checksum(corpus.read_artifact("catalog.json")),
    )


registry.register(
    FIELD_WEIGHTED_METHOD_ID,
    create,
    implementation_id=FIELD_WEIGHTED_IMPLEMENTATION_ID,
    config=FIELD_WEIGHTED_CONFIG,
    data_dependencies=(
        "artifact:bm25",
        "artifact:catalog.json",
        "corpus:published-markdown",
    ),
    servable=True,
    identity_factory=field_weighted_identity,
)

__all__ = [
    "FIELD_LENGTH_NORMALIZATION",
    "FIELD_NAMES",
    "FIELD_WEIGHTED_CONFIG",
    "FIELD_WEIGHTED_IMPLEMENTATION_ID",
    "FIELD_WEIGHTED_METHOD_ID",
    "FIELD_WEIGHTS",
    "FieldWeightedBm25Error",
    "FieldWeightedBm25Retriever",
    "create",
    "field_weighted_identity",
]
