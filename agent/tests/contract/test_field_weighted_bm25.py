"""Shared serving/evaluation contracts for the field-weighted BM25 arm."""

from __future__ import annotations

import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

import agent.retrieval.field_weighted as field_weighted_module
from agent.retrieval.bm25 import Bm25Retriever
from agent.retrieval.corpus import PublishedCorpus, content_checksum
from agent.retrieval.corpus_build import build_index
from agent.retrieval.field_weighted import (
    FIELD_LENGTH_NORMALIZATION,
    FIELD_WEIGHTED_CONFIG,
    FIELD_WEIGHTED_IMPLEMENTATION_ID,
    FIELD_WEIGHTED_METHOD_ID,
    FIELD_WEIGHTS,
    FieldWeightedBm25Error,
    FieldWeightedBm25Retriever,
)
from agent.retrieval.fingerprint import canonical_config
from agent.retrieval.protocol import Retriever
from agent.retrieval.registry import registry


@dataclass(frozen=True, slots=True)
class _FixtureIndex:
    content: Path
    corpus_policy: Path
    bm25_policy: Path
    index: Path


def _write_post(
    content: Path,
    doc_id: str,
    *,
    title: str,
    body: str,
    tags: tuple[str, ...] = (),
    description: str = "",
) -> None:
    path = content / doc_id
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "description": description,
        "tags": list(tags),
        "title": title,
    }
    path.write_text(
        "\n".join(
            (
                "---",
                *(
                    f"{key}: {json.dumps(value, ensure_ascii=False)}"
                    for key, value in frontmatter.items()
                ),
                "---",
                body,
                "",
            )
        ),
        encoding="utf-8",
    )


def _write_corpus_policy(path: Path) -> Path:
    path.write_text(
        "schema_version = 1\nno_frontmatter_allowlist = []\n",
        encoding="utf-8",
    )
    return path


def _write_bm25_policy(path: Path, *, policy_id: str) -> Path:
    path.write_text(
        "\n".join(
            (
                "schema_version = 1",
                f'policy_id = "{policy_id}"',
                'seeds = ["도커", "동률"]',
                "deny = []",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="module")
def field_index(tmp_path_factory: pytest.TempPathFactory) -> _FixtureIndex:
    root = tmp_path_factory.mktemp("field-weighted")
    content = root / "content"
    _write_post(
        content,
        "AI/a-title.md",
        title="도커",
        body="컨테이너 안내",
    )
    _write_post(
        content,
        "AI/b-tag.md",
        title="태그 글",
        tags=("도커",),
        body="컨테이너 안내",
    )
    _write_post(
        content,
        "AI/c-body.md",
        title="본문 글",
        body="도커",
    )
    _write_post(
        content,
        "AI/d-tie.md",
        title="동률 글",
        body="동률",
    )
    _write_post(
        content,
        "AI/e-tie.md",
        title="동률 글",
        body="동률",
    )
    for doc_id, title, body in (
        ("AI/f.md", "파이썬", "테스트 자동화"),
        ("AI/g.md", "쿠버네티스", "클러스터 운영"),
        ("AI/h.md", "에이전트", "프로토콜 스트리밍"),
    ):
        _write_post(content, doc_id, title=title, body=body)
    corpus_policy = _write_corpus_policy(root / "corpus-policy.toml")
    bm25_policy = _write_bm25_policy(
        root / "bm25-policy.toml",
        policy_id="field-weighted-test-a",
    )
    index = root / "index"
    build_index(
        content_root=content,
        policy_path=corpus_policy,
        bm25_policy_path=bm25_policy,
        output_root=index,
    )
    return _FixtureIndex(content, corpus_policy, bm25_policy, index)


@pytest.fixture(scope="module")
def numeric_field_index(tmp_path_factory: pytest.TempPathFactory) -> _FixtureIndex:
    """Build a tiny corpus whose BM25F scores have a tractable numeric oracle."""

    root = tmp_path_factory.mktemp("field-weighted-numeric")
    content = root / "content"
    _write_post(
        content,
        "AI/a-multi.md",
        title="도커",
        tags=("도커",),
        description="도커",
        body="",
    )
    _write_post(
        content,
        "AI/b-short-body.md",
        title="",
        body="도커",
    )
    _write_post(
        content,
        "AI/c-long-body.md",
        title="",
        body="도커 도커 도커",
    )
    for suffix in ("d", "e", "f", "g", "h"):
        _write_post(
            content,
            f"AI/{suffix}-empty.md",
            title="",
            body="",
        )
    corpus_policy = _write_corpus_policy(root / "corpus-policy.toml")
    bm25_policy = _write_bm25_policy(
        root / "bm25-policy.toml",
        policy_id="field-weighted-numeric-oracle",
    )
    index = root / "index"
    build_index(
        content_root=content,
        policy_path=corpus_policy,
        bm25_policy_path=bm25_policy,
        output_root=index,
    )
    return _FixtureIndex(content, corpus_policy, bm25_policy, index)


def test_field_weights_change_only_field_frequency_and_rank_title_tag_body(
    field_index: _FixtureIndex,
) -> None:
    corpus = PublishedCorpus(field_index.index)
    retriever = FieldWeightedBm25Retriever(corpus)

    first = retriever.retrieve("도커", limit=8)
    second = retriever.retrieve("도커", limit=8)

    assert first.doc_ids()[:3] == (
        "AI/a-title.md",
        "AI/b-tag.md",
        "AI/c-body.md",
    )
    assert first == second
    assert [hit.metadata["matched_fields"] for hit in first.hits[:3]] == [
        ("title",),
        ("tags",),
        ("body",),
    ]
    assert first.hits[0].score > first.hits[1].score > first.hits[2].score
    assert FIELD_WEIGHTS == {"body": 1.0, "tags": 2.0, "title": 3.0}
    assert FIELD_LENGTH_NORMALIZATION == {
        "body": 0.75,
        "tags": 0.0,
        "title": 0.0,
    }


def _assert_mapping_item_is_read_only(
    value: Mapping[str, object],
    key: str,
    replacement: object,
) -> None:
    original = value[key]
    try:
        with pytest.raises(TypeError):
            value[key] = replacement  # type: ignore[index]
    finally:
        # Keep the make-it-fail run isolated when the old implementation still
        # exposes a dict.  The fixed mapping rejects the assignment above.
        if isinstance(value, dict):
            value[key] = original


def test_field_weighted_constants_and_nested_config_are_read_only() -> None:
    _assert_mapping_item_is_read_only(FIELD_WEIGHTS, "title", 0.01)
    _assert_mapping_item_is_read_only(FIELD_LENGTH_NORMALIZATION, "body", 0.0)
    _assert_mapping_item_is_read_only(FIELD_WEIGHTED_CONFIG, "k1", 9.0)
    nested_weights = FIELD_WEIGHTED_CONFIG["field_weights"]
    assert isinstance(nested_weights, Mapping)
    _assert_mapping_item_is_read_only(nested_weights, "title", 0.01)


def test_runtime_and_identity_use_the_same_constructor_snapshot(
    field_index: _FixtureIndex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = PublishedCorpus(field_index.index)
    mutable_config = registry.servable[FIELD_WEIGHTED_METHOD_ID].config
    retriever = FieldWeightedBm25Retriever(corpus, mutable_config)
    before_result = retriever.retrieve("도커", limit=8)
    before_identity = retriever.identity_config
    before_fingerprint = retriever.fingerprint

    caller_weights = mutable_config["field_weights"]
    assert isinstance(caller_weights, dict)
    caller_weights["title"] = 0.01
    monkeypatch.setattr(
        field_weighted_module,
        "FIELD_WEIGHTS",
        {"body": 9.0, "tags": 0.01, "title": 0.001},
    )
    monkeypatch.setattr(
        field_weighted_module,
        "FIELD_LENGTH_NORMALIZATION",
        {"body": 0.0, "tags": 0.0, "title": 0.0},
    )

    assert retriever.retrieve("도커", limit=8) == before_result
    assert retriever.identity_config == before_identity
    assert retriever.fingerprint == before_fingerprint


def test_bm25f_scores_match_hand_calculated_multi_field_and_body_length_oracle(
    numeric_field_index: _FixtureIndex,
) -> None:
    retriever = FieldWeightedBm25Retriever(PublishedCorpus(numeric_field_index.index))

    result = retriever.retrieve("도커", limit=8)
    hits = {str(hit.doc_id): hit for hit in result.hits}

    assert result.doc_ids() == (
        "AI/a-multi.md",
        "AI/c-long-body.md",
        "AI/b-short-body.md",
    )
    # Each occurrence produces m:도커 and s:도커.  With N=8 and df=3,
    # idf=ln(5.5/3.5).  Average body length is (2+2+6)/8=1.25.
    #
    # a-multi pseudo-TF per token:
    #   3*1(title) + 2*1(tag) + 1/(.25 + .75*(2/1.25))
    # b-short pseudo-TF: 1/(.25 + .75*(2/1.25))
    # c-long pseudo-TF:  3/(.25 + .75*(6/1.25))
    #
    # The literal scores below independently apply the BM25 saturation once to each
    # summed pseudo-TF, then sum the two token channels.
    assert hits["AI/a-multi.md"].score == pytest.approx(
        1.7884303457459099,
        rel=1e-12,
    )
    assert hits["AI/b-short-body.md"].score == pytest.approx(
        0.7117875964457593,
        rel=1e-12,
    )
    assert hits["AI/c-long-body.md"].score == pytest.approx(
        0.7726241431505252,
        rel=1e-12,
    )
    # The Markdown body of a-multi is empty, so "body" can only come from description.
    assert hits["AI/a-multi.md"].metadata["matched_fields"] == (
        "body",
        "tags",
        "title",
    )


def test_repeated_query_terms_scale_hand_calculated_scores_linearly(
    numeric_field_index: _FixtureIndex,
) -> None:
    retriever = FieldWeightedBm25Retriever(PublishedCorpus(numeric_field_index.index))

    once = retriever.retrieve("도커", limit=8)
    twice = retriever.retrieve("도커 도커", limit=8)

    assert twice.doc_ids() == once.doc_ids()
    assert [hit.score for hit in twice.hits] == pytest.approx(
        [3.5768606914918197, 1.5452482863010504, 1.4235751928915186],
        rel=1e-12,
    )
    assert [hit.score for hit in twice.hits] == pytest.approx(
        [2.0 * hit.score for hit in once.hits],
        rel=1e-12,
    )


def test_field_weighted_method_reuses_verified_tokenizer_and_baseline_identity(
    field_index: _FixtureIndex,
) -> None:
    corpus = PublishedCorpus(field_index.index)
    baseline = Bm25Retriever(corpus)
    retriever = FieldWeightedBm25Retriever(corpus)

    assert retriever.tokenize("도커 API") == tuple(baseline.tokenize("도커 API"))
    identity = retriever.identity_config
    dependency = identity["bm25_dependency"]
    assert dependency["method_id"] == "bm25"
    assert dependency["fingerprint"] == baseline.fingerprint
    assert identity["idf_source"]["role"] == "verified-fitted-term-idf"
    assert identity["body_sources"] == [
        "frontmatter-description",
        "markdown-body",
    ]
    assert identity["catalog_sha256"] == content_checksum(
        corpus.read_artifact("catalog.json")
    )


def test_field_weighted_registry_is_shared_and_servable(
    field_index: _FixtureIndex,
) -> None:
    corpus = PublishedCorpus(field_index.index)
    registration = registry.servable[FIELD_WEIGHTED_METHOD_ID]
    resolved = registry.servable.create(FIELD_WEIGHTED_METHOD_ID, corpus)

    assert isinstance(resolved.implementation, Retriever)
    assert registration.implementation_id == FIELD_WEIGHTED_IMPLEMENTATION_ID
    assert canonical_config(registration.config) == canonical_config(
        FIELD_WEIGHTED_CONFIG
    )
    assert registration.data_dependencies == (
        "artifact:bm25",
        "artifact:catalog.json",
        "corpus:published-markdown",
    )
    assert resolved.fingerprint == resolved.implementation.fingerprint
    assert resolved.retrieve("도커", limit=1).doc_ids() == ("AI/a-title.md",)


def test_field_weighted_ties_limits_nonsense_and_concurrency_are_deterministic(
    field_index: _FixtureIndex,
) -> None:
    retriever = FieldWeightedBm25Retriever(PublishedCorpus(field_index.index))
    expected = retriever.retrieve("동률", limit=8)

    assert expected.doc_ids()[:2] == ("AI/d-tie.md", "AI/e-tie.md")
    assert expected.hits[0].score == expected.hits[1].score
    assert retriever.retrieve("동률", limit=1).doc_ids() == ("AI/d-tie.md",)
    assert retriever.retrieve("존재하지않는완전무관질의").hits == ()
    assert retriever.retrieve("도커", limit=0).hits == ()
    with pytest.raises(ValueError, match="non-negative integer"):
        retriever.retrieve("도커", limit=-1)
    with pytest.raises(TypeError, match="query must be a string"):
        retriever.retrieve(123)  # type: ignore[arg-type]

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(lambda _: retriever.retrieve("동률"), range(32)))
    assert results == (expected,) * 32


def test_field_weighted_fingerprint_binds_bm25_artifact_policy(
    field_index: _FixtureIndex,
    tmp_path: Path,
) -> None:
    second_index = tmp_path / "second-index"
    second_policy = _write_bm25_policy(
        tmp_path / "bm25-policy.toml",
        policy_id="field-weighted-test-b",
    )
    build_index(
        content_root=field_index.content,
        policy_path=field_index.corpus_policy,
        bm25_policy_path=second_policy,
        output_root=second_index,
    )
    first_corpus = PublishedCorpus(field_index.index)
    second_corpus = PublishedCorpus(second_index)
    first = FieldWeightedBm25Retriever(first_corpus)
    second = FieldWeightedBm25Retriever(second_corpus)

    assert first_corpus.fingerprint == second_corpus.fingerprint
    assert (
        first.identity_config["bm25_dependency"]["fingerprint"]
        != second.identity_config["bm25_dependency"]["fingerprint"]
    )
    assert first.fingerprint != second.fingerprint
    assert first.retrieve("도커") == second.retrieve("도커")


def test_field_weighted_rejects_unreviewed_runtime_config(
    field_index: _FixtureIndex,
) -> None:
    with pytest.raises(FieldWeightedBm25Error, match="config"):
        FieldWeightedBm25Retriever(
            PublishedCorpus(field_index.index),
            {**FIELD_WEIGHTED_CONFIG, "k1": 9.0},
        )
