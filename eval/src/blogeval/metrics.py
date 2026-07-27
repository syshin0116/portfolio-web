"""Deterministic, ungraded metrics kept separate by query-set semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from agent.retrieval.protocol import DocId

from blogeval.datasets import DatasetKind, Qrel


class MetricError(ValueError):
    """Metric inputs do not satisfy the query-set contract."""


def _ratio(numerator: int | Fraction, denominator: int) -> Fraction:
    if denominator <= 0:
        raise MetricError("metric denominator must be positive")
    return Fraction(numerator, denominator)


def serialize_metric(value: Fraction) -> float:
    """Round an exact metric once, only at the JSON/report boundary."""

    return round(value.numerator / value.denominator, 12)


def validate_cutoffs(cutoffs: Sequence[int]) -> tuple[int, ...]:
    values = tuple(cutoffs)
    if not values:
        raise MetricError("at least one cutoff is required")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in values
    ):
        raise MetricError("cutoffs must be positive integers")
    if values != tuple(sorted(set(values))):
        raise MetricError("cutoffs must be sorted and unique")
    return values


@dataclass(frozen=True, slots=True)
class QueryMetrics:
    query_id: str
    coverage: Fraction
    first_relevant_rank: int | None
    values: Mapping[str, Fraction]

    def as_dict(self) -> dict[str, object]:
        return {
            "coverage": serialize_metric(self.coverage),
            "first_relevant_rank": self.first_relevant_rank,
            "metrics": {
                name: serialize_metric(value)
                for name, value in sorted(self.values.items())
            },
            "query_id": self.query_id,
        }


@dataclass(frozen=True, slots=True)
class MetricSummary:
    dataset_kind: DatasetKind
    query_count: int
    values: Mapping[str, Fraction]
    per_query: tuple[QueryMetrics, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset_kind": self.dataset_kind.value,
            "metrics": {
                name: serialize_metric(value)
                for name, value in sorted(self.values.items())
            },
            "per_query": [item.as_dict() for item in self.per_query],
            "query_count": self.query_count,
        }


def _deduplicated_ranking(values: Sequence[DocId | str]) -> tuple[DocId, ...]:
    ranking: list[DocId] = []
    seen: set[DocId] = set()
    for value in values:
        doc_id = DocId(value)
        if doc_id in seen:
            continue
        seen.add(doc_id)
        ranking.append(doc_id)
    return tuple(ranking)


def summarize_metrics(
    *,
    kind: DatasetKind,
    qrels: Sequence[Qrel],
    rankings: Mapping[str, Sequence[DocId | str]],
    cutoffs: Sequence[int],
) -> MetricSummary:
    """Summarize rankings without mixing known-item and topic metrics."""

    normalized_cutoffs = validate_cutoffs(cutoffs)
    if not qrels:
        raise MetricError("qrels must not be empty")
    expected_ids = {qrel.query_id for qrel in qrels}
    if set(rankings) != expected_ids:
        missing = sorted(expected_ids - set(rankings))
        unknown = sorted(set(rankings) - expected_ids)
        raise MetricError(
            f"rankings must match qrels exactly; missing={missing}, unknown={unknown}"
        )

    per_query: list[QueryMetrics] = []
    totals: dict[str, Fraction] = {"coverage": Fraction()}
    for cutoff in normalized_cutoffs:
        if kind is DatasetKind.KNOWN_ITEM:
            totals[f"hit@{cutoff}"] = Fraction()
            totals[f"mrr@{cutoff}"] = Fraction()
        else:
            totals[f"recall@{cutoff}"] = Fraction()

    for qrel in qrels:
        ranking = _deduplicated_ranking(rankings[qrel.query_id])
        relevant = set(qrel.relevant_doc_ids)
        first_relevant_rank = next(
            (
                rank
                for rank, doc_id in enumerate(ranking, start=1)
                if doc_id in relevant
            ),
            None,
        )
        coverage = Fraction(bool(ranking))
        totals["coverage"] += coverage
        query_values: dict[str, Fraction] = {}
        for cutoff in normalized_cutoffs:
            top = ranking[:cutoff]
            if kind is DatasetKind.KNOWN_ITEM:
                if len(relevant) != 1:
                    raise MetricError(
                        "known-item qrels must contain exactly one relevant DocId"
                    )
                hit = Fraction(any(doc_id in relevant for doc_id in top))
                reciprocal_rank = (
                    Fraction(1, first_relevant_rank)
                    if first_relevant_rank is not None and first_relevant_rank <= cutoff
                    else Fraction()
                )
                query_values[f"hit@{cutoff}"] = hit
                query_values[f"mrr@{cutoff}"] = reciprocal_rank
                totals[f"hit@{cutoff}"] += hit
                totals[f"mrr@{cutoff}"] += reciprocal_rank
            else:
                retrieved_relevant = len(relevant.intersection(top))
                recall = _ratio(retrieved_relevant, len(relevant))
                query_values[f"recall@{cutoff}"] = recall
                totals[f"recall@{cutoff}"] += recall
        per_query.append(
            QueryMetrics(
                query_id=qrel.query_id,
                coverage=coverage,
                first_relevant_rank=first_relevant_rank,
                values=query_values,
            )
        )

    query_count = len(qrels)
    summary = {name: _ratio(total, query_count) for name, total in totals.items()}
    return MetricSummary(
        dataset_kind=kind,
        query_count=query_count,
        values=summary,
        per_query=tuple(per_query),
    )


__all__ = [
    "MetricError",
    "MetricSummary",
    "QueryMetrics",
    "serialize_metric",
    "summarize_metrics",
    "validate_cutoffs",
]
