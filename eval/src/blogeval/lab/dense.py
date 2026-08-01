"""Offline exact-scan dense retrieval with a pinned multilingual E5 model."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from typing import Protocol

from agent.retrieval.fingerprint import canonical_config, retriever_fingerprint
from agent.retrieval.protocol import Corpus, DocId, Hit, Retrieval

DENSE_METHOD_ID = "dense-multilingual-e5-small"
DENSE_IMPLEMENTATION_ID = "blogeval.lab.dense:create@1"
DENSE_MODEL_ID = "intfloat/multilingual-e5-small"
DENSE_MODEL_REVISION = "d1d99a1efae6779390caba937d92c54b5bc70e51"
EXPECTED_RUNTIME_PACKAGE_VERSIONS = {
    "numpy": ("2.4.4",),
    "sentence-transformers": ("5.6.0",),
    "torch": ("2.13.0", "2.13.0+cpu"),
    "transformers": ("5.14.1",),
}
DENSE_CONFIG: dict[str, object] = {
    "algorithm": "exact-cosine-nearest-neighbours",
    "blank_query_policy": "return-no-hits",
    "document_representation": "raw-published-markdown",
    "embedding": {
        "batch_size": 16,
        "device": "cpu",
        "dimension": 384,
        "document_prefix": "passage: ",
        "local_files_only": True,
        "max_sequence_length": 512,
        "model_id": DENSE_MODEL_ID,
        "normalize_embeddings": True,
        "packages": {
            package: list(versions)
            for package, versions in EXPECTED_RUNTIME_PACKAGE_VERSIONS.items()
        },
        "precision": "float32",
        "query_prefix": "query: ",
        "revision": DENSE_MODEL_REVISION,
        "trust_remote_code": False,
    },
    "index": "in-memory-exact-scan",
    "score": "cosine-similarity",
    "tie_break": "doc-id-ascending",
    "vector_validation": "finite-nonzero-l2-normalized",
}


class DenseModelUnavailableError(RuntimeError):
    """The exact optional model runtime or pinned local snapshot is unavailable."""


type Vector = Sequence[float]


class EmbeddingBackend(Protocol):
    """Small seam that keeps deterministic fakes independent from torch."""

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Vector]: ...

    def embed_query(self, text: str) -> Vector: ...


class _SentenceTransformerModel(Protocol):
    max_seq_length: int

    def get_embedding_dimension(self) -> int | None: ...

    def encode(self, sentences: Sequence[str], **kwargs: object) -> object: ...


type ModelFactory = Callable[..., _SentenceTransformerModel]


def _embedding_config(config: Mapping[str, object]) -> dict[str, object]:
    value = config.get("embedding")
    if not isinstance(value, dict):
        raise ValueError("dense embedding config must be an object")
    return value


def _load_sentence_transformer_factory() -> ModelFactory:
    for package, expected in sorted(EXPECTED_RUNTIME_PACKAGE_VERSIONS.items()):
        try:
            installed = distribution_version(package)
        except PackageNotFoundError as exc:
            raise DenseModelUnavailableError(
                "dense retrieval requires the optional eval dependency; run "
                "`uv sync --frozen --package syshin0116-dev-eval --extra dense "
                "--all-groups`"
            ) from exc
        if installed not in expected:
            raise DenseModelUnavailableError(
                f"dense retrieval requires {package} in {expected}, found {installed}"
            )
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - broken optional installation.
        raise DenseModelUnavailableError(
            "sentence-transformers is installed but cannot be imported"
        ) from exc
    return SentenceTransformer


def _vector_rows(value: object, *, location: str) -> tuple[Vector, ...]:
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        value = tolist()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{location} must be a sequence of vectors")
    return tuple(value)


class SentenceTransformerE5Backend:
    """Load only the exact cached E5 snapshot and apply its asymmetric prompts."""

    def __init__(
        self,
        config: Mapping[str, object] = DENSE_CONFIG,
        *,
        _model_factory: ModelFactory | None = None,
    ) -> None:
        if canonical_config(config) != canonical_config(DENSE_CONFIG):
            raise ValueError("dense backend config does not match the pinned method")
        embedding = _embedding_config(config)
        factory = _model_factory or _load_sentence_transformer_factory()
        try:
            model = factory(
                str(embedding["model_id"]),
                device=str(embedding["device"]),
                local_files_only=bool(embedding["local_files_only"]),
                revision=str(embedding["revision"]),
                trust_remote_code=bool(embedding["trust_remote_code"]),
            )
        except Exception as exc:
            raise DenseModelUnavailableError(
                "the pinned multilingual E5 snapshot is not available in the local "
                "Hugging Face cache; cache intfloat/multilingual-e5-small at revision "
                f"{DENSE_MODEL_REVISION} before opting into the dense sweep"
            ) from exc
        dimension = model.get_embedding_dimension()
        if dimension != embedding["dimension"]:
            raise DenseModelUnavailableError(
                "cached E5 embedding dimension differs from the pinned method"
            )
        if model.max_seq_length != embedding["max_sequence_length"]:
            raise DenseModelUnavailableError(
                "cached E5 maximum sequence length differs from the pinned method"
            )
        self._model = model
        self._embedding = embedding

    def _encode(self, values: Sequence[str], *, prefix: str) -> tuple[Vector, ...]:
        encoded = self._model.encode(
            [prefix + value for value in values],
            batch_size=int(self._embedding["batch_size"]),
            convert_to_numpy=True,
            normalize_embeddings=bool(self._embedding["normalize_embeddings"]),
            precision=str(self._embedding["precision"]),
            show_progress_bar=False,
        )
        return _vector_rows(encoded, location="sentence-transformers output")

    def embed_documents(self, texts: Sequence[str]) -> tuple[Vector, ...]:
        return self._encode(
            texts,
            prefix=str(self._embedding["document_prefix"]),
        )

    def embed_query(self, text: str) -> Vector:
        rows = self._encode(
            (text,),
            prefix=str(self._embedding["query_prefix"]),
        )
        if len(rows) != 1:
            raise ValueError("query embedding backend must return exactly one vector")
        return rows[0]


def _unit_vector(
    value: Vector,
    *,
    dimension: int,
    location: str,
) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{location} must be a numeric vector")
    if len(value) != dimension:
        raise ValueError(f"{location} must contain exactly {dimension} dimensions")
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool):
            raise ValueError(f"{location} must contain only finite numbers")
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{location} must contain only finite numbers") from exc
        if not math.isfinite(number):
            raise ValueError(f"{location} must contain only finite numbers")
        numbers.append(number)
    magnitude = math.sqrt(math.fsum(number * number for number in numbers))
    if not math.isfinite(magnitude) or magnitude == 0.0:
        raise ValueError(f"{location} must be non-zero")
    return tuple(number / magnitude for number in numbers)


class DenseRetriever:
    """Embed the frozen corpus once and rank every document by exact cosine score."""

    def __init__(
        self,
        corpus: Corpus,
        *,
        backend: EmbeddingBackend | None = None,
        config: Mapping[str, object] = DENSE_CONFIG,
    ) -> None:
        if canonical_config(config) != canonical_config(DENSE_CONFIG):
            raise ValueError("dense retriever config does not match the pinned method")
        fingerprint = getattr(corpus, "fingerprint", None)
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("DenseRetriever requires a fingerprinted Corpus")
        self._corpus = corpus
        self._config = json.loads(canonical_config(config))
        self._doc_ids = tuple(
            sorted((DocId(value) for value in corpus.doc_ids()), key=str)
        )
        embedding = _embedding_config(config)
        self._dimension = int(embedding["dimension"])
        self._backend = backend or SentenceTransformerE5Backend(config)
        raw_vectors = tuple(
            self._backend.embed_documents(
                tuple(corpus.read(doc_id) for doc_id in self._doc_ids)
            )
        )
        if len(raw_vectors) != len(self._doc_ids):
            raise ValueError(
                "document embedding count must match the frozen corpus document count"
            )
        self._vectors = tuple(
            _unit_vector(
                vector,
                dimension=self._dimension,
                location=f"document embedding {doc_id}",
            )
            for doc_id, vector in zip(self._doc_ids, raw_vectors, strict=True)
        )

    @property
    def identity_config(self) -> dict[str, object]:
        return json.loads(canonical_config(self._config))

    @property
    def fingerprint(self) -> str:
        return retriever_fingerprint(
            method_id=DENSE_METHOD_ID,
            implementation_id=DENSE_IMPLEMENTATION_ID,
            config=self._config,
            corpus_fingerprint=self._corpus.fingerprint,
        )

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0 or not query.strip() or not self._doc_ids:
            return Retrieval(query=query)
        query_vector = _unit_vector(
            self._backend.embed_query(query),
            dimension=self._dimension,
            location="query embedding",
        )
        ordered = sorted(
            (
                (
                    math.fsum(
                        query_value * document_value
                        for query_value, document_value in zip(
                            query_vector,
                            document_vector,
                            strict=True,
                        )
                    ),
                    doc_id,
                )
                for doc_id, document_vector in zip(
                    self._doc_ids,
                    self._vectors,
                    strict=True,
                )
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
                        "embedding_model": DENSE_MODEL_ID,
                        "embedding_revision": DENSE_MODEL_REVISION,
                    },
                )
                for rank, (score, doc_id) in enumerate(ordered[:limit], start=1)
            ),
        )


def create(corpus: Corpus, config: Mapping[str, object]) -> DenseRetriever:
    if canonical_config(config) != canonical_config(DENSE_CONFIG):
        raise ValueError("registered dense config does not match implementation")
    return DenseRetriever(corpus, config=config)


__all__ = [
    "DENSE_CONFIG",
    "DENSE_IMPLEMENTATION_ID",
    "DENSE_METHOD_ID",
    "DENSE_MODEL_ID",
    "DENSE_MODEL_REVISION",
    "DenseModelUnavailableError",
    "DenseRetriever",
    "EmbeddingBackend",
    "SentenceTransformerE5Backend",
    "create",
]
