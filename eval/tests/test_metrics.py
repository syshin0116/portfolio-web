from __future__ import annotations

import pytest
from agent.retrieval.protocol import DocId

from blogeval.datasets import DatasetKind, Evidence, Qrel
from blogeval.metrics import MetricError, summarize_metrics


def _qrel(
    query_id: str,
    relevant: tuple[str, ...],
) -> Qrel:
    return Qrel(
        query_id=query_id,
        query=query_id,
        relevant_doc_ids=tuple(DocId(value) for value in relevant),
        evidence=(Evidence("fixture", None, "fixture", 1),),
    )


def test_known_item_metrics_report_hit_mrr_and_answer_coverage_separately() -> None:
    qrels = (
        _qrel("first", ("a.md",)),
        _qrel("third", ("c.md",)),
        _qrel("miss", ("z.md",)),
        _qrel("decline", ("d.md",)),
    )
    summary = summarize_metrics(
        kind=DatasetKind.KNOWN_ITEM,
        qrels=qrels,
        rankings={
            "first": ("a.md", "b.md"),
            "third": ("a.md", "b.md", "c.md"),
            "miss": ("a.md",),
            "decline": (),
        },
        cutoffs=(1, 3),
    )

    assert summary.values == {
        "coverage": 0.75,
        "hit@1": 0.25,
        "hit@3": 0.5,
        "mrr@1": 0.25,
        "mrr@3": 0.333333333333,
    }
    assert [item.first_relevant_rank for item in summary.per_query] == [
        1,
        3,
        None,
        None,
    ]


def test_topic_metrics_report_macro_recall_and_answer_coverage() -> None:
    qrels = (
        _qrel("partial", ("a.md", "b.md")),
        _qrel("complete", ("c.md", "d.md")),
    )
    summary = summarize_metrics(
        kind=DatasetKind.TOPIC,
        qrels=qrels,
        rankings={
            "partial": ("a.md", "x.md"),
            "complete": ("c.md", "d.md"),
        },
        cutoffs=(1, 2),
    )

    assert summary.values == {
        "coverage": 1.0,
        "recall@1": 0.5,
        "recall@2": 0.75,
    }
    assert "hit@1" not in summary.values
    assert "mrr@1" not in summary.values


def test_metrics_reject_missing_rankings_and_unsorted_cutoffs() -> None:
    qrels = (_qrel("one", ("a.md",)),)
    with pytest.raises(MetricError, match="match qrels exactly"):
        summarize_metrics(
            kind=DatasetKind.KNOWN_ITEM,
            qrels=qrels,
            rankings={},
            cutoffs=(1,),
        )
    with pytest.raises(MetricError, match="sorted and unique"):
        summarize_metrics(
            kind=DatasetKind.KNOWN_ITEM,
            qrels=qrels,
            rankings={"one": ()},
            cutoffs=(5, 1),
        )
