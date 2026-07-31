"""Evaluation-harness integration for the shared field-weighted BM25 method."""

from __future__ import annotations

import json
from pathlib import Path

from agent.retrieval import registry as agent_registry
from agent.retrieval.corpus import PublishedCorpus
from agent.retrieval.corpus_build import build_index
from agent.retrieval.field_weighted import (
    FIELD_WEIGHTED_IMPLEMENTATION_ID,
    FIELD_WEIGHTED_METHOD_ID,
)

from blogeval.cli import DEFAULT_METHODS
from blogeval.datasets import parse_queryset
from blogeval.jsonio import canonical_json_bytes, json_checksum
from blogeval.registry import registry as eval_registry
from blogeval.runner import run_evaluation


def _write_post(
    content: Path,
    doc_id: str,
    *,
    title: str,
    body: str,
) -> None:
    path = content / doc_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            (
                "---",
                f"title: {json.dumps(title, ensure_ascii=False)}",
                "tags: []",
                'description: ""',
                "---",
                body,
                "",
            )
        ),
        encoding="utf-8",
    )


def _build_index(tmp_path: Path) -> PublishedCorpus:
    content = tmp_path / "content"
    _write_post(content, "AI/a-title.md", title="도커", body="컨테이너 안내")
    _write_post(content, "AI/b-body.md", title="본문", body="도커")
    for doc_id, title, body in (
        ("AI/c.md", "파이썬", "테스트"),
        ("AI/d.md", "쿠버네티스", "클러스터"),
        ("AI/e.md", "랭그래프", "에이전트"),
        ("AI/f.md", "검색", "평가"),
    ):
        _write_post(content, doc_id, title=title, body=body)
    corpus_policy = tmp_path / "corpus-policy.toml"
    corpus_policy.write_text(
        "schema_version = 1\nno_frontmatter_allowlist = []\n",
        encoding="utf-8",
    )
    bm25_policy = tmp_path / "bm25-policy.toml"
    bm25_policy.write_text(
        "\n".join(
            (
                "schema_version = 1",
                'policy_id = "field-harness-test"',
                'seeds = ["도커"]',
                "deny = []",
                "",
            )
        ),
        encoding="utf-8",
    )
    output = tmp_path / "index"
    build_index(
        content_root=content,
        policy_path=corpus_policy,
        bm25_policy_path=bm25_policy,
        output_root=output,
    )
    return PublishedCorpus(output)


def _dataset(corpus: PublishedCorpus):
    value = {
        "corpus": {
            "document_count": len(corpus.doc_ids()),
            "fingerprint": corpus.fingerprint,
            "git_tree_sha": corpus.content_git_tree_sha,
        },
        "dataset_id": "field-weighted-contract-v1",
        "dataset_kind": "known-item",
        "exclusions": [],
        "labels": {
            "review": None,
            "reviewed_qrels_checksum": None,
            "status": "synthetic-only",
        },
        "provenance": {
            "generator": "field-weighted-contract",
            "generator_version": 1,
            "included_occurrence_count": 1,
            "source_artifacts": [],
            "source_occurrence_count": 1,
        },
        "qrels": [
            {
                "evidence": [
                    {
                        "kind": "synthetic-contract",
                        "occurrences": 1,
                        "source_doc_id": "AI/b-body.md",
                        "target": "a-title",
                    }
                ],
                "query": "도커",
                "query_id": "known-docker-title",
                "relevant_doc_ids": ["AI/a-title.md"],
            }
        ],
        "schema": "blogeval-queryset-v2",
    }
    payload = canonical_json_bytes(value)
    return parse_queryset(value, checksum=json_checksum(payload))


def test_eval_registry_and_runner_use_the_exact_agent_registration(
    tmp_path: Path,
) -> None:
    corpus = _build_index(tmp_path)
    agent_registration = agent_registry.servable[FIELD_WEIGHTED_METHOD_ID]
    eval_registration = eval_registry.retrievable[FIELD_WEIGHTED_METHOD_ID]

    assert eval_registration is agent_registration
    assert eval_registration.implementation_id == FIELD_WEIGHTED_IMPLEMENTATION_ID
    assert FIELD_WEIGHTED_METHOD_ID in eval_registry.servable
    assert FIELD_WEIGHTED_METHOD_ID in DEFAULT_METHODS

    run = run_evaluation(
        corpus=corpus,
        dataset=_dataset(corpus),
        content_tree_sha=corpus.content_git_tree_sha,
        method_ids=(FIELD_WEIGHTED_METHOD_ID,),
        cutoffs=(1, 3),
        registry=eval_registry,
    )

    method = run.methods[0]
    assert method.method_id == FIELD_WEIGHTED_METHOD_ID
    assert method.implementation_id == agent_registration.implementation_id
    assert method.queries[0].retrieved_doc_ids[0] == "AI/a-title.md"
    assert method.metrics.as_dict()["metrics"]["hit@1"] == 1.0
    assert method.evaluation_relation == "clean-holdout"
    assert method.identity_config["bm25_dependency"]["fingerprint"].startswith(
        "sha256:"
    )
