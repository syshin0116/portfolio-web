"""Deterministic evaluation runner and local JSON system of record."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent.retrieval.protocol import Corpus, DocId
from agent.retrieval.registry import RetrieverRegistry

from blogeval.datasets import QuerySet, validate_queryset_corpus
from blogeval.jsonio import canonical_json_bytes, write_bytes_immutable
from blogeval.metrics import MetricSummary, summarize_metrics, validate_cutoffs
from blogeval.registry import registry as default_registry
from blogeval.report import render_leaderboard, render_metrics_svg, render_per_query

RUN_SCHEMA = "blogeval-run-v1"
RUNNER_ID = "blogeval.runner@1"


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
    metrics: MetricSummary
    queries: tuple[QueryResult, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "fingerprint": self.fingerprint,
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

    def as_dict(self) -> dict[str, object]:
        return {
            "corpus": self.dataset.corpus.as_dict(),
            "cutoffs": list(self.cutoffs),
            "dataset": {
                "checksum": self.dataset.checksum,
                "dataset_id": self.dataset.dataset_id,
                "dataset_kind": self.dataset.kind.value,
            },
            "methods": [method.as_dict() for method in self.methods],
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
    identities: Sequence[tuple[str, str]],
) -> str:
    payload = {
        "corpus": dataset.corpus.as_dict(),
        "cutoffs": list(cutoffs),
        "dataset_checksum": dataset.checksum,
        "methods": [
            {"fingerprint": fingerprint, "method_id": method_id}
            for method_id, fingerprint in identities
        ],
        "runner": RUNNER_ID,
        "schema": RUN_SCHEMA,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return f"sha256:{digest}"


def run_evaluation(
    *,
    corpus: Corpus,
    dataset: QuerySet,
    content_tree_sha: str,
    method_ids: Sequence[str],
    cutoffs: Sequence[int] = (1, 5, 10),
    registry: RetrieverRegistry = default_registry,
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

    methods: list[MethodResult] = []
    identities: list[tuple[str, str]] = []
    for method_id in normalized_method_ids:
        resolved = registry.retrievable.create(method_id, corpus)
        identities.append((method_id, resolved.fingerprint))
        try:
            query_results: list[QueryResult] = []
            rankings: dict[str, tuple[DocId, ...]] = {}
            for qrel in dataset.qrels:
                ranking = resolved.retrieve(
                    qrel.query,
                    limit=retrieval_limit,
                ).doc_ids(limit=retrieval_limit)
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
                    metrics=metrics,
                    queries=tuple(query_results),
                )
            )
        finally:
            close = getattr(resolved.implementation, "close", None)
            if callable(close):
                close()

    return EvaluationRun(
        run_id=_run_id(
            dataset=dataset,
            cutoffs=normalized_cutoffs,
            identities=identities,
        ),
        dataset=dataset,
        cutoffs=normalized_cutoffs,
        methods=tuple(methods),
    )


def write_run_artifacts(
    run: EvaluationRun,
    *,
    output_root: Path,
) -> RunArtifacts:
    """Write one immutable-shape local record plus deterministic derived reports."""

    tree_directory = output_root / run.dataset.corpus.git_tree_sha
    run_slug = run.run_id.removeprefix("sha256:")
    directory = tree_directory / run_slug
    artifacts = RunArtifacts(
        directory=directory,
        run_json=directory / "run.json",
        leaderboard_markdown=directory / "leaderboard.md",
        per_query_markdown=directory / "per-query.md",
        metrics_svg=directory / "metrics.svg",
    )
    write_bytes_immutable(artifacts.run_json, canonical_json_bytes(run.as_dict()))
    write_bytes_immutable(
        artifacts.leaderboard_markdown,
        render_leaderboard(run).encode("utf-8"),
    )
    write_bytes_immutable(
        artifacts.per_query_markdown,
        render_per_query(run).encode("utf-8"),
    )
    write_bytes_immutable(
        artifacts.metrics_svg,
        render_metrics_svg(run).encode("utf-8"),
    )
    return artifacts


__all__ = [
    "EvaluationError",
    "EvaluationRun",
    "MethodResult",
    "QueryResult",
    "RUNNER_ID",
    "RUN_SCHEMA",
    "RunArtifacts",
    "run_evaluation",
    "write_run_artifacts",
]
