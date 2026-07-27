"""Deterministic evaluation runner and local JSON system of record."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import cast

from agent.retrieval.fingerprint import retriever_fingerprint
from agent.retrieval.protocol import Corpus, DocId
from agent.retrieval.registry import ResolvedRetriever, RetrieverRegistry

from blogeval.datasets import DatasetError, QuerySet, validate_queryset_corpus
from blogeval.jsonio import (
    StrictJsonError,
    canonical_json_bytes,
    json_checksum,
    load_canonical_json,
)
from blogeval.metrics import MetricSummary, summarize_metrics, validate_cutoffs
from blogeval.provenance import (
    ProvenanceError,
    RunProvenance,
    collect_run_provenance,
    parse_run_provenance,
)
from blogeval.registry import registry as default_registry
from blogeval.report import render_leaderboard, render_metrics_svg, render_per_query

RUN_SCHEMA = "blogeval-run-v3"
RUNNER_ID = "blogeval.runner@3"
RESULT_MANIFEST_SCHEMA = "blogeval-result-manifest-v1"
RESULT_DIGEST_SCHEMA = "blogeval-result-digest-v1"
_RESULT_FILES = ("leaderboard.md", "metrics.svg", "per-query.md", "run.json")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class EvaluationError(ValueError):
    """Evaluation inputs are inconsistent or unsafe to compare."""


@dataclass(frozen=True, slots=True)
class QueryResult:
    query_id: str
    query: str
    relevant_doc_ids: tuple[DocId, ...]
    retrieved_doc_ids: tuple[DocId, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "query_id": self.query_id,
            "relevant_doc_ids": [str(value) for value in self.relevant_doc_ids],
            "retrieved_doc_ids": [str(value) for value in self.retrieved_doc_ids],
        }


@dataclass(frozen=True, slots=True)
class MethodResult:
    method_id: str
    implementation_id: str
    fingerprint: str
    identity_config: Mapping[str, object]
    data_dependencies: tuple[str, ...]
    evaluation_relation: str
    overlap_sources: tuple[str, ...]
    metrics: MetricSummary
    queries: tuple[QueryResult, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "fingerprint": self.fingerprint,
            "data_lineage": {
                "dependencies": list(self.data_dependencies),
                "evaluation_relation": self.evaluation_relation,
                "overlap_sources": list(self.overlap_sources),
            },
            "identity_config": dict(self.identity_config),
            "implementation_id": self.implementation_id,
            "method_id": self.method_id,
            "metrics": self.metrics.as_dict(),
            "queries": [item.as_dict() for item in self.queries],
        }


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    run_id: str
    dataset: QuerySet
    cutoffs: tuple[int, ...]
    methods: tuple[MethodResult, ...]
    provenance: RunProvenance

    def as_dict(self) -> dict[str, object]:
        return {
            "corpus": self.dataset.corpus.as_dict(),
            "cutoffs": list(self.cutoffs),
            "dataset": {
                "checksum": self.dataset.checksum,
                "dataset_id": self.dataset.dataset_id,
                "dataset_kind": self.dataset.kind.value,
                "label_status": self.dataset.labels.status.value,
            },
            "methods": [method.as_dict() for method in self.methods],
            "provenance": self.provenance.as_dict(),
            "run_id": self.run_id,
            "runner": RUNNER_ID,
            "schema": RUN_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class RunArtifacts:
    directory: Path
    run_json: Path
    leaderboard_markdown: Path
    per_query_markdown: Path
    metrics_svg: Path
    result_manifest: Path
    result_digest: str


@dataclass(frozen=True, slots=True)
class VerifiedRun:
    run: EvaluationRun
    result_digest: str


def _method_ids(
    values: Sequence[str],
    *,
    registry: RetrieverRegistry,
) -> tuple[str, ...]:
    method_ids = tuple(values)
    if len(method_ids) < 1:
        raise EvaluationError("at least one retrieval method is required")
    if method_ids != tuple(sorted(set(method_ids))):
        raise EvaluationError("method IDs must be sorted and unique")
    unknown = [value for value in method_ids if value not in registry.retrievable]
    if unknown:
        raise EvaluationError(f"unregistered evaluation methods: {', '.join(unknown)}")
    return method_ids


def _run_id(
    *,
    dataset: QuerySet,
    cutoffs: Sequence[int],
    identities: Sequence[Mapping[str, object]],
    provenance: RunProvenance,
) -> str:
    payload = {
        "corpus": dataset.corpus.as_dict(),
        "cutoffs": list(cutoffs),
        "dataset_checksum": dataset.checksum,
        "methods": list(identities),
        "provenance": provenance.as_dict(),
        "runner": RUNNER_ID,
        "schema": RUN_SCHEMA,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"sha256:{digest}"


def _data_relation(
    dependencies: tuple[str, ...],
    dataset: QuerySet,
) -> tuple[str, tuple[str, ...]]:
    if not dependencies:
        raise EvaluationError(
            "evaluation methods must declare data_dependencies before comparison"
        )
    source_artifacts = dataset.provenance.source_artifacts
    direct_sources = {f"artifact:{artifact.path}" for artifact in source_artifacts}
    oracle_overlap = tuple(sorted(set(dependencies) & direct_sources))
    if oracle_overlap:
        return "oracle-overlap", oracle_overlap
    ancestors = {
        value for artifact in source_artifacts for value in artifact.derived_from
    }
    in_sample_overlap = tuple(sorted(set(dependencies) & ancestors))
    if in_sample_overlap:
        return "in-sample-overlap", in_sample_overlap
    return "clean-holdout", ()


def _create_registered_retriever(
    *,
    corpus: Corpus,
    method_id: str,
    registry: RetrieverRegistry,
) -> ResolvedRetriever:
    try:
        return registry.retrievable.create(method_id, corpus)
    except Exception as exc:
        raise EvaluationError(
            f"cannot create reviewed retriever {method_id!r}: {exc}"
        ) from exc


def _close_registered_retriever(
    resolved: ResolvedRetriever,
    *,
    method_id: str,
) -> None:
    try:
        close = getattr(resolved.implementation, "close", None)
        if callable(close):
            close()
    except Exception as exc:
        raise EvaluationError(
            f"cannot close reviewed retriever {method_id!r}: {exc}"
        ) from exc


def _validated_retrieval_ranking(
    resolved: ResolvedRetriever,
    *,
    corpus_doc_ids: frozenset[DocId],
    limit: int,
    method_id: str,
    query: str,
    query_id: str,
) -> tuple[DocId, ...]:
    try:
        retrieval = resolved.retrieve(query, limit=limit)
        returned = retrieval.doc_ids()
    except Exception as exc:
        raise EvaluationError(
            f"reviewed retriever {method_id!r} failed for query {query_id!r}: {exc}"
        ) from exc
    if retrieval.query != query:
        raise EvaluationError(
            f"retriever {method_id!r} returned query {retrieval.query!r} "
            f"for expected query {query!r}"
        )
    if not isinstance(returned, tuple) or not all(
        isinstance(doc_id, DocId) for doc_id in returned
    ):
        raise EvaluationError(
            f"retriever {method_id!r} returned an invalid DocId ranking "
            f"for query {query_id!r}"
        )
    if len(returned) != len(set(returned)):
        raise EvaluationError(
            f"retriever {method_id!r} returned duplicate DocIds for query {query_id!r}"
        )
    outside_corpus = tuple(
        sorted(
            (doc_id for doc_id in returned if doc_id not in corpus_doc_ids),
            key=str,
        )
    )
    if outside_corpus:
        values = ", ".join(str(value) for value in outside_corpus)
        raise EvaluationError(
            f"retriever {method_id!r} returned DocIds outside the verified "
            f"corpus for query {query_id!r}: {values}"
        )
    if len(returned) > limit:
        raise EvaluationError(
            f"retriever {method_id!r} returned {len(returned)} documents for "
            f"limit {limit} on query {query_id!r}"
        )
    return returned


def run_evaluation(
    *,
    corpus: Corpus,
    dataset: QuerySet,
    content_tree_sha: str,
    method_ids: Sequence[str],
    cutoffs: Sequence[int] = (1, 5, 10),
    registry: RetrieverRegistry = default_registry,
    require_publishable: bool = False,
) -> EvaluationRun:
    """Run every method against the same qrels and verified corpus snapshot."""

    validate_queryset_corpus(
        dataset,
        corpus,
        content_tree_sha=content_tree_sha,
    )
    normalized_cutoffs = validate_cutoffs(cutoffs)
    normalized_method_ids = _method_ids(method_ids, registry=registry)
    retrieval_limit = normalized_cutoffs[-1]
    provenance = collect_run_provenance()
    if require_publishable:
        dataset.require_reviewed_labels()
        provenance.require_publication_eligible()
    corpus_doc_ids = frozenset(DocId(value) for value in corpus.doc_ids())

    methods: list[MethodResult] = []
    identities: list[Mapping[str, object]] = []
    for method_id in normalized_method_ids:
        resolved = _create_registered_retriever(
            corpus=corpus,
            method_id=method_id,
            registry=registry,
        )
        dependencies = resolved.registration.data_dependencies
        evaluation_relation, overlap_sources = _data_relation(
            dependencies,
            dataset,
        )
        identities.append(
            {
                "data_dependencies": list(dependencies),
                "evaluation_relation": evaluation_relation,
                "fingerprint": resolved.fingerprint,
                "method_id": method_id,
                "overlap_sources": list(overlap_sources),
            }
        )
        try:
            query_results: list[QueryResult] = []
            rankings: dict[str, tuple[DocId, ...]] = {}
            for qrel in dataset.qrels:
                ranking = _validated_retrieval_ranking(
                    resolved,
                    corpus_doc_ids=corpus_doc_ids,
                    limit=retrieval_limit,
                    method_id=method_id,
                    query=qrel.query,
                    query_id=qrel.query_id,
                )
                rankings[qrel.query_id] = ranking
                query_results.append(
                    QueryResult(
                        query_id=qrel.query_id,
                        query=qrel.query,
                        relevant_doc_ids=qrel.relevant_doc_ids,
                        retrieved_doc_ids=ranking,
                    )
                )
            metrics = summarize_metrics(
                kind=dataset.kind,
                qrels=dataset.qrels,
                rankings=rankings,
                cutoffs=normalized_cutoffs,
            )
            methods.append(
                MethodResult(
                    method_id=method_id,
                    implementation_id=resolved.registration.implementation_id,
                    fingerprint=resolved.fingerprint,
                    identity_config=resolved.identity_config,
                    data_dependencies=dependencies,
                    evaluation_relation=evaluation_relation,
                    overlap_sources=overlap_sources,
                    metrics=metrics,
                    queries=tuple(query_results),
                )
            )
        finally:
            _close_registered_retriever(resolved, method_id=method_id)

    return EvaluationRun(
        run_id=_run_id(
            dataset=dataset,
            cutoffs=normalized_cutoffs,
            identities=identities,
            provenance=provenance,
        ),
        dataset=dataset,
        cutoffs=normalized_cutoffs,
        methods=tuple(methods),
        provenance=provenance,
    )


def _mapping(
    value: object,
    *,
    location: str,
    keys: frozenset[str] | None = None,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise EvaluationError(f"{location} must be a JSON object")
    result = cast(Mapping[str, object], value)
    if keys is not None and set(result) != keys:
        raise EvaluationError(f"{location} has an unexpected object shape")
    return result


def _array(value: object, *, location: str) -> list[object]:
    if not isinstance(value, list):
        raise EvaluationError(f"{location} must be an array")
    return value


def _text(value: object, *, location: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise EvaluationError(f"{location} must be a non-empty trimmed string")
    return value


def _doc_ids(value: object, *, location: str) -> tuple[DocId, ...]:
    result: list[DocId] = []
    for index, item in enumerate(_array(value, location=location)):
        try:
            result.append(DocId(item))
        except (TypeError, ValueError) as exc:
            raise EvaluationError(f"{location}[{index}] is not a valid DocId") from exc
    if len(result) != len(set(result)):
        raise EvaluationError(f"{location} must contain unique DocIds")
    return tuple(result)


def _parse_recorded_run(
    value: object,
    *,
    corpus: Corpus,
    dataset: QuerySet,
    registry: RetrieverRegistry,
) -> EvaluationRun:
    raw = _mapping(
        value,
        location="run",
        keys=frozenset(
            {
                "corpus",
                "cutoffs",
                "dataset",
                "methods",
                "provenance",
                "run_id",
                "runner",
                "schema",
            }
        ),
    )
    if raw["schema"] != RUN_SCHEMA or raw["runner"] != RUNNER_ID:
        raise EvaluationError("run schema/runner is unsupported")
    if raw["corpus"] != dataset.corpus.as_dict():
        raise EvaluationError("run corpus identity differs from the dataset")
    expected_dataset = {
        "checksum": dataset.checksum,
        "dataset_id": dataset.dataset_id,
        "dataset_kind": dataset.kind.value,
        "label_status": dataset.labels.status.value,
    }
    if raw["dataset"] != expected_dataset:
        raise EvaluationError("run dataset identity differs from the supplied dataset")
    cutoffs = validate_cutoffs(tuple(_array(raw["cutoffs"], location="run.cutoffs")))
    corpus_doc_ids = frozenset(DocId(value) for value in corpus.doc_ids())
    qrels_by_id = {qrel.query_id: qrel for qrel in dataset.qrels}
    methods: list[MethodResult] = []
    identities: list[Mapping[str, object]] = []
    previous_method_id: str | None = None
    for method_index, method_value in enumerate(
        _array(raw["methods"], location="run.methods")
    ):
        location = f"run.methods[{method_index}]"
        method = _mapping(
            method_value,
            location=location,
            keys=frozenset(
                {
                    "data_lineage",
                    "fingerprint",
                    "identity_config",
                    "implementation_id",
                    "method_id",
                    "metrics",
                    "queries",
                }
            ),
        )
        method_id = _text(method["method_id"], location=f"{location}.method_id")
        if previous_method_id is not None and method_id <= previous_method_id:
            raise EvaluationError("run method IDs must be sorted and unique")
        previous_method_id = method_id
        try:
            registration = registry.retrievable[method_id]
        except KeyError as exc:
            raise EvaluationError(
                f"{location}.method_id is not registered in the reviewed registry"
            ) from exc
        fingerprint = _text(
            method["fingerprint"],
            location=f"{location}.fingerprint",
        )
        if _SHA256_RE.fullmatch(fingerprint) is None:
            raise EvaluationError(f"{location}.fingerprint must be a sha256 checksum")
        lineage = _mapping(
            method["data_lineage"],
            location=f"{location}.data_lineage",
            keys=frozenset({"dependencies", "evaluation_relation", "overlap_sources"}),
        )
        dependencies = tuple(
            _text(item, location=f"{location}.data_lineage.dependencies")
            for item in _array(
                lineage["dependencies"],
                location=f"{location}.data_lineage.dependencies",
            )
        )
        if (
            not dependencies
            or dependencies != tuple(sorted(set(dependencies)))
            or any(":" not in item for item in dependencies)
        ):
            raise EvaluationError(
                f"{location}.data_lineage.dependencies must be sorted, unique, "
                "and namespaced"
            )
        if dependencies != registration.data_dependencies:
            raise EvaluationError(
                f"{location}.data_lineage.dependencies differ from the "
                "reviewed registration"
            )
        relation, overlap = _data_relation(dependencies, dataset)
        if lineage["evaluation_relation"] != relation:
            raise EvaluationError(f"{location}.data_lineage relation is incorrect")
        if lineage["overlap_sources"] != list(overlap):
            raise EvaluationError(
                f"{location}.data_lineage overlap_sources is incorrect"
            )
        raw_queries = _array(method["queries"], location=f"{location}.queries")
        if len(raw_queries) != len(dataset.qrels):
            raise EvaluationError(f"{location}.queries must match every dataset qrel")
        query_results: list[QueryResult] = []
        rankings: dict[str, tuple[DocId, ...]] = {}
        for query_index, query_value in enumerate(raw_queries):
            query_location = f"{location}.queries[{query_index}]"
            query = _mapping(
                query_value,
                location=query_location,
                keys=frozenset(
                    {
                        "query",
                        "query_id",
                        "relevant_doc_ids",
                        "retrieved_doc_ids",
                    }
                ),
            )
            query_id = _text(query["query_id"], location=f"{query_location}.query_id")
            expected_qrel = qrels_by_id.get(query_id)
            if expected_qrel is None or expected_qrel != dataset.qrels[query_index]:
                raise EvaluationError(
                    f"{query_location} does not preserve canonical qrel order"
                )
            if query["query"] != expected_qrel.query:
                raise EvaluationError(f"{query_location}.query differs from the qrel")
            relevant = _doc_ids(
                query["relevant_doc_ids"],
                location=f"{query_location}.relevant_doc_ids",
            )
            if relevant != expected_qrel.relevant_doc_ids:
                raise EvaluationError(
                    f"{query_location}.relevant_doc_ids differ from the qrel"
                )
            retrieved = _doc_ids(
                query["retrieved_doc_ids"],
                location=f"{query_location}.retrieved_doc_ids",
            )
            if len(retrieved) > cutoffs[-1]:
                raise EvaluationError(
                    f"{query_location}.retrieved_doc_ids exceed the largest cutoff"
                )
            outside_corpus = tuple(
                sorted(
                    (doc_id for doc_id in retrieved if doc_id not in corpus_doc_ids),
                    key=str,
                )
            )
            if outside_corpus:
                values = ", ".join(str(value) for value in outside_corpus)
                raise EvaluationError(
                    f"{query_location}.retrieved_doc_ids are outside the "
                    f"verified corpus: {values}"
                )
            rankings[query_id] = retrieved
            query_results.append(
                QueryResult(
                    query_id=query_id,
                    query=expected_qrel.query,
                    relevant_doc_ids=relevant,
                    retrieved_doc_ids=retrieved,
                )
            )
        metrics = summarize_metrics(
            kind=dataset.kind,
            qrels=dataset.qrels,
            rankings=rankings,
            cutoffs=cutoffs,
        )
        if method["metrics"] != metrics.as_dict():
            raise EvaluationError(
                f"{location}.metrics do not regenerate from recorded rankings"
            )
        identity_config = _mapping(
            method["identity_config"],
            location=f"{location}.identity_config",
        )
        implementation_id = _text(
            method["implementation_id"],
            location=f"{location}.implementation_id",
        )
        if implementation_id != registration.implementation_id:
            raise EvaluationError(
                f"{location}.implementation_id differs from the reviewed registration"
            )
        try:
            expected_identity_config = registration.identity_config(corpus)
        except Exception as exc:
            raise EvaluationError(
                f"cannot resolve the reviewed identity for {method_id!r}: {exc}"
            ) from exc
        if identity_config != expected_identity_config:
            raise EvaluationError(
                f"{location}.identity_config differs from the reviewed registration"
            )
        expected_fingerprint = retriever_fingerprint(
            method_id=method_id,
            implementation_id=registration.implementation_id,
            config=expected_identity_config,
            corpus_fingerprint=dataset.corpus.fingerprint,
        )
        if fingerprint != expected_fingerprint:
            raise EvaluationError(
                f"{location}.fingerprint differs from the reviewed registration"
            )
        resolved = _create_registered_retriever(
            corpus=corpus,
            method_id=method_id,
            registry=registry,
        )
        try:
            if resolved.fingerprint != expected_fingerprint:
                raise EvaluationError(
                    f"{location}.fingerprint differs from the resolved "
                    "reviewed retriever"
                )
            for query_index, (qrel, recorded_query) in enumerate(
                zip(dataset.qrels, query_results, strict=True)
            ):
                replayed = _validated_retrieval_ranking(
                    resolved,
                    corpus_doc_ids=corpus_doc_ids,
                    limit=cutoffs[-1],
                    method_id=method_id,
                    query=qrel.query,
                    query_id=qrel.query_id,
                )
                if replayed != recorded_query.retrieved_doc_ids:
                    raise EvaluationError(
                        f"{location}.queries[{query_index}].retrieved_doc_ids "
                        "differ from the reviewed retriever replay"
                    )
        finally:
            _close_registered_retriever(resolved, method_id=method_id)
        methods.append(
            MethodResult(
                method_id=method_id,
                implementation_id=implementation_id,
                fingerprint=expected_fingerprint,
                identity_config=expected_identity_config,
                data_dependencies=dependencies,
                evaluation_relation=relation,
                overlap_sources=overlap,
                metrics=metrics,
                queries=tuple(query_results),
            )
        )
        identities.append(
            {
                "data_dependencies": list(dependencies),
                "evaluation_relation": relation,
                "fingerprint": expected_fingerprint,
                "method_id": method_id,
                "overlap_sources": list(overlap),
            }
        )
    if not methods:
        raise EvaluationError("run must contain at least one method")
    try:
        provenance = parse_run_provenance(raw["provenance"])
    except ProvenanceError as exc:
        raise EvaluationError(str(exc)) from exc
    expected_run_id = _run_id(
        dataset=dataset,
        cutoffs=cutoffs,
        identities=identities,
        provenance=provenance,
    )
    if raw["run_id"] != expected_run_id:
        raise EvaluationError("run_id does not match the recorded execution inputs")
    return EvaluationRun(
        run_id=expected_run_id,
        dataset=dataset,
        cutoffs=cutoffs,
        methods=tuple(methods),
        provenance=provenance,
    )


def _result_inventory(payloads: Mapping[str, bytes]) -> list[dict[str, object]]:
    return [
        {
            "bytes": len(payloads[path]),
            "path": path,
            "sha256": json_checksum(payloads[path]),
        }
        for path in _RESULT_FILES
    ]


def _result_digest(files: Sequence[Mapping[str, object]]) -> str:
    return json_checksum(
        canonical_json_bytes(
            {
                "files": list(files),
                "schema": RESULT_DIGEST_SCHEMA,
            }
        )
    )


def _artifact_payloads(run: EvaluationRun) -> tuple[dict[str, bytes], bytes, str]:
    payloads = {
        "leaderboard.md": render_leaderboard(run).encode("utf-8"),
        "metrics.svg": render_metrics_svg(run).encode("utf-8"),
        "per-query.md": render_per_query(run).encode("utf-8"),
        "run.json": canonical_json_bytes(run.as_dict()),
    }
    files = _result_inventory(payloads)
    result_digest = _result_digest(files)
    manifest = canonical_json_bytes(
        {
            "files": files,
            "result_digest": result_digest,
            "schema": RESULT_MANIFEST_SCHEMA,
        }
    )
    return payloads, manifest, result_digest


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(
        directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_fsynced_file(path: Path, payload: bytes) -> None:
    flags = (
        os.O_CREAT
        | os.O_EXCL
        | os.O_WRONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def _inventory_run_directory(directory: Path) -> tuple[str, ...]:
    if directory.is_symlink() or not directory.is_dir():
        raise EvaluationError("result directory must be a real directory")
    entries: list[str] = []
    for entry in directory.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise EvaluationError(
                f"result directory contains an unsupported entry: {entry.name}"
            )
        entries.append(entry.name)
    return tuple(sorted(entries))


def verify_run_directory(
    directory: Path,
    *,
    corpus: Corpus,
    dataset: QuerySet,
    registry: RetrieverRegistry = default_registry,
) -> VerifiedRun:
    """Verify registry identity, corpus, files, metrics, and projections."""

    try:
        validate_queryset_corpus(
            dataset,
            corpus,
            content_tree_sha=dataset.corpus.git_tree_sha,
        )
    except DatasetError as exc:
        raise EvaluationError(str(exc)) from exc
    expected_entries = tuple(sorted((*_RESULT_FILES, "manifest.json")))
    actual_entries = _inventory_run_directory(directory)
    if actual_entries != expected_entries:
        raise EvaluationError(
            "result directory file inventory mismatch; "
            f"expected={expected_entries}, actual={actual_entries}"
        )
    try:
        manifest_value, _ = load_canonical_json(directory / "manifest.json")
    except StrictJsonError as exc:
        raise EvaluationError(str(exc)) from exc
    manifest = _mapping(
        manifest_value,
        location="result manifest",
        keys=frozenset({"files", "result_digest", "schema"}),
    )
    if manifest["schema"] != RESULT_MANIFEST_SCHEMA:
        raise EvaluationError("unsupported result manifest schema")
    raw_files = _array(manifest["files"], location="result manifest.files")
    if len(raw_files) != len(_RESULT_FILES):
        raise EvaluationError("result manifest files are not the exact expected set")
    files: list[Mapping[str, object]] = []
    payloads: dict[str, bytes] = {}
    for index, raw_file in enumerate(raw_files):
        location = f"result manifest.files[{index}]"
        record = _mapping(
            raw_file,
            location=location,
            keys=frozenset({"bytes", "path", "sha256"}),
        )
        path = record["path"]
        byte_count = record["bytes"]
        checksum = record["sha256"]
        if path != _RESULT_FILES[index]:
            raise EvaluationError(
                "result manifest files are not the exact expected set"
            )
        if (
            isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or byte_count < 0
        ):
            raise EvaluationError(f"{location}.bytes must be non-negative")
        if not isinstance(checksum, str) or _SHA256_RE.fullmatch(checksum) is None:
            raise EvaluationError(f"{location}.sha256 must be a checksum")
        try:
            payload = (directory / path).read_bytes()
        except OSError as exc:
            raise EvaluationError(f"cannot read result file {path}: {exc}") from exc
        if len(payload) != byte_count or json_checksum(payload) != checksum:
            raise EvaluationError(f"result file checksum/size mismatch: {path}")
        files.append(record)
        payloads[path] = payload
    expected_digest = _result_digest(files)
    if manifest["result_digest"] != expected_digest:
        raise EvaluationError("result digest does not match its exact file manifest")
    try:
        run_value, run_payload = load_canonical_json(directory / "run.json")
    except StrictJsonError as exc:
        raise EvaluationError(str(exc)) from exc
    if run_payload != payloads["run.json"]:
        raise EvaluationError("run.json changed during result verification")
    run = _parse_recorded_run(
        run_value,
        corpus=corpus,
        dataset=dataset,
        registry=registry,
    )
    regenerated, _, regenerated_digest = _artifact_payloads(run)
    if regenerated_digest != expected_digest:
        raise EvaluationError("result digest differs from regenerated run projections")
    for path in _RESULT_FILES:
        if payloads[path] != regenerated[path]:
            raise EvaluationError(f"result projection does not regenerate: {path}")
    return VerifiedRun(run=run, result_digest=expected_digest)


@contextmanager
def _exclusive_result_lock(output_root: Path):
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / ".blogeval-write.lock"
    if lock_path.is_symlink():
        raise EvaluationError("result lock must not be a symlink")
    descriptor = os.open(
        lock_path,
        os.O_CREAT
        | os.O_RDWR
        | os.O_NONBLOCK
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise EvaluationError("result lock must be a regular file")
        flock(descriptor, LOCK_EX)
        yield
    finally:
        flock(descriptor, LOCK_UN)
        os.close(descriptor)


def write_run_artifacts(
    run: EvaluationRun,
    *,
    corpus: Corpus,
    output_root: Path,
    registry: RetrieverRegistry = default_registry,
) -> RunArtifacts:
    """Stage and atomically commit one complete, immutable result directory."""

    try:
        validate_queryset_corpus(
            run.dataset,
            corpus,
            content_tree_sha=run.dataset.corpus.git_tree_sha,
        )
    except DatasetError as exc:
        raise EvaluationError(str(exc)) from exc
    run = _parse_recorded_run(
        run.as_dict(),
        corpus=corpus,
        dataset=run.dataset,
        registry=registry,
    )
    tree_directory = output_root / run.dataset.corpus.git_tree_sha
    run_slug = run.run_id.removeprefix("sha256:")
    directory = tree_directory / run_slug
    artifacts = RunArtifacts(
        directory=directory,
        run_json=directory / "run.json",
        leaderboard_markdown=directory / "leaderboard.md",
        per_query_markdown=directory / "per-query.md",
        metrics_svg=directory / "metrics.svg",
        result_manifest=directory / "manifest.json",
        result_digest="",
    )
    payloads, manifest_payload, result_digest = _artifact_payloads(run)
    if output_root.is_symlink():
        raise EvaluationError("result output root must not be a symlink")
    output_root.mkdir(parents=True, exist_ok=True)
    if tree_directory.is_symlink():
        raise EvaluationError("result content tree directory must not be a symlink")
    tree_directory.mkdir(parents=True, exist_ok=True)
    staged = Path(
        tempfile.mkdtemp(
            prefix=f".{run_slug}.staged-",
            dir=tree_directory,
        )
    )
    try:
        for path, payload in payloads.items():
            _write_fsynced_file(staged / path, payload)
        _write_fsynced_file(staged / "manifest.json", manifest_payload)
        _fsync_directory(staged)
        with _exclusive_result_lock(output_root):
            if os.path.lexists(directory):
                verified = verify_run_directory(
                    directory,
                    corpus=corpus,
                    dataset=run.dataset,
                    registry=registry,
                )
                if verified.result_digest != result_digest:
                    raise EvaluationError(
                        "refusing to replace a non-identical evaluation result"
                    )
            else:
                try:
                    os.rename(staged, directory)
                except OSError as exc:
                    raise EvaluationError(
                        f"cannot atomically commit result directory: {exc}"
                    ) from exc
                _fsync_directory(tree_directory)
        return RunArtifacts(
            directory=directory,
            run_json=artifacts.run_json,
            leaderboard_markdown=artifacts.leaderboard_markdown,
            per_query_markdown=artifacts.per_query_markdown,
            metrics_svg=artifacts.metrics_svg,
            result_manifest=artifacts.result_manifest,
            result_digest=result_digest,
        )
    finally:
        if staged.exists():
            shutil.rmtree(staged)


__all__ = [
    "EvaluationError",
    "EvaluationRun",
    "MethodResult",
    "QueryResult",
    "RUNNER_ID",
    "RUN_SCHEMA",
    "RESULT_MANIFEST_SCHEMA",
    "RunArtifacts",
    "RunProvenance",
    "VerifiedRun",
    "run_evaluation",
    "verify_run_directory",
    "write_run_artifacts",
]
