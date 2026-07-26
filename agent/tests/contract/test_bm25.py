"""Corrected Korean BM25 baseline contracts."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from kiwipiepy import Kiwi
from rank_bm25 import BM25Okapi

from agent.retrieval import bm25 as bm25_module
from agent.retrieval.bm25 import (
    BM25_CONFIG,
    BM25_IMPLEMENTATION_ID,
    BM25_METHOD_ID,
    Bm25ArtifactError,
    Bm25Retriever,
    collect_dictionary_evidence,
    create_bm25,
    load_dictionary_policy,
)
from agent.retrieval.corpus import PublishedCorpus, corpus_fingerprint
from agent.retrieval.corpus_build import CorpusBuildError, build_index, scan_corpus
from agent.retrieval.registry import registry

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_CONTENT = REPO_ROOT / "content"
REAL_CORPUS_POLICY = REPO_ROOT / "agent" / "corpus-policy.toml"
BM25_POLICY = REPO_ROOT / "agent" / "bm25-policy.toml"
DOCKER_QREL = (
    REPO_ROOT / "agent" / "tests" / "fixtures" / "retrieval" / "docker-literal-v1.json"
)


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
    lines = [
        "---",
        *[
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in frontmatter.items()
        ],
        "---",
        body,
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_corpus_policy(path: Path) -> Path:
    path.write_text(
        "schema_version = 1\nno_frontmatter_allowlist = []\n",
        encoding="utf-8",
    )
    return path


def _write_bm25_policy(
    path: Path,
    *,
    seeds: tuple[str, ...] = ("도커",),
    deny: tuple[str, ...] = (),
) -> Path:
    seed_values = ", ".join(json.dumps(item, ensure_ascii=False) for item in seeds)
    deny_values = ", ".join(json.dumps(item, ensure_ascii=False) for item in deny)
    path.write_text(
        "\n".join(
            (
                "schema_version = 1",
                'policy_id = "test-bm25-policy-v1"',
                f"seeds = [{seed_values}]",
                f"deny = [{deny_values}]",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def _legacy_text(document: object) -> str:
    metadata = document.metadata
    title = metadata.get("title")
    if not isinstance(title, str):
        title = Path(str(document.doc_id)).stem
    description = metadata.get("summary", metadata.get("description", ""))
    if not isinstance(description, str):
        description = ""
    tags = metadata.get("tags")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        tags = []
    return f"{title}\n{description}\n{' '.join(tags)}\n{document.body}"


def _legacy_tokens(kiwi: Kiwi, text: str) -> list[str]:
    tokens = [
        token.form
        for token in kiwi.tokenize(text)
        if token.tag.startswith(("NN", "VV", "VA", "SL"))
    ]
    # This fallback is preserved only in the test helper to reproduce current behavior.
    return tokens or text.lower().split()


@pytest.fixture
def small_index(tmp_path: Path) -> Path:
    content = tmp_path / "content"
    _write_post(
        content,
        "AI/a.md",
        title="도커 안내",
        tags=("Docker",),
        description="Docker container",
        body="도커(Docker) 컨테이너",
    )
    _write_post(
        content,
        "AI/b.md",
        title="도커 안내",
        tags=("Docker",),
        description="Docker container",
        body="도커(Docker) 컨테이너",
    )
    for doc_id, body in (
        ("AI/c.md", "크다 달린다 unrelated"),
        ("AI/d.md", "파이썬 테스트"),
        ("AI/e.md", "검색 평가"),
        ("AI/f.md", "에이전트 프로토콜"),
    ):
        _write_post(content, doc_id, title=doc_id, body=body)
    output = tmp_path / "index"
    build_index(
        content_root=content,
        policy_path=_write_corpus_policy(tmp_path / "corpus-policy.toml"),
        bm25_policy_path=_write_bm25_policy(tmp_path / "bm25-policy.toml"),
        output_root=output,
    )
    return output


@pytest.fixture(scope="module")
def real_index(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("bm25-real") / "index"
    build_index(
        content_root=REAL_CONTENT,
        policy_path=REAL_CORPUS_POLICY,
        bm25_policy_path=BM25_POLICY,
        output_root=output,
    )
    return output


def test_dictionary_uses_only_high_precision_evidence_and_tags_alone_do_not_yield_docker(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    _write_post(
        content,
        "AI/post.md",
        title="Container",
        tags=("Docker", "검색"),
        body="No bilingual alias here.",
    )
    snapshot = scan_corpus(
        content_root=content,
        policy_path=_write_corpus_policy(tmp_path / "corpus-policy.toml"),
    )
    policy = load_dictionary_policy(
        _write_bm25_policy(tmp_path / "bm25-policy.toml", seeds=())
    )

    entries = collect_dictionary_evidence(snapshot, policy)

    assert {entry.term for entry in entries} == {"검색"}
    assert "도커" not in {entry.term for entry in entries}


def test_build_emits_deterministic_safe_artifacts_and_dictionary_provenance(
    small_index: Path,
    tmp_path: Path,
) -> None:
    manifest = json.loads(
        (small_index / "bm25" / "manifest.json").read_text(encoding="utf-8")
    )
    tokens = json.loads(
        (small_index / "bm25" / "documents.json").read_text(encoding="utf-8")
    )
    dictionary = (small_index / "kiwi-user-dictionary.txt").read_text(encoding="utf-8")

    assert manifest["schema"] == "kiwi-bm25-manifest-v1"
    assert manifest["method_id"] == BM25_METHOD_ID
    assert manifest["implementation_id"] == BM25_IMPLEMENTATION_ID
    assert manifest["config"] == BM25_CONFIG
    assert manifest["dictionary"]["sha256"].startswith("sha256:")
    docker_entry = next(
        entry for entry in manifest["dictionary"]["entries"] if entry["term"] == "도커"
    )
    assert {source["kind"] for source in docker_entry["sources"]} == {
        "alias",
        "seed",
    }
    assert tokens["schema"] == "bm25-token-corpus-v1"
    assert [document["doc_id"] for document in tokens["documents"]] == [
        "AI/a.md",
        "AI/b.md",
        "AI/c.md",
        "AI/d.md",
        "AI/e.md",
        "AI/f.md",
    ]
    assert "도커\tNNP\n" in dictionary
    assert not any(
        path.suffix in {".pickle", ".pkl"} for path in small_index.rglob("*")
    )

    second = tmp_path / "second"
    source = small_index.parent / "content"
    # The fixture source is immutable during both builds.
    build_index(
        content_root=source,
        policy_path=small_index.parent / "corpus-policy.toml",
        bm25_policy_path=small_index.parent / "bm25-policy.toml",
        output_root=second,
    )
    for relative in (
        "kiwi-user-dictionary.txt",
        "bm25/documents.json",
        "bm25/manifest.json",
    ):
        assert (small_index / relative).read_bytes() == (second / relative).read_bytes()
    assert Bm25Retriever(PublishedCorpus(small_index)).retrieve(
        "도커"
    ) == Bm25Retriever(PublishedCorpus(second)).retrieve("도커")


def test_tokenizer_keeps_only_nouns_and_sl_and_namespaces_surface_forms(
    small_index: Path,
) -> None:
    retriever = Bm25Retriever(PublishedCorpus(small_index))

    tokens = retriever.tokenize("도커 API 달린다 크다 미등록신조어")

    morphemes = {token for token in tokens if token.startswith("m:")}
    surfaces = {token for token in tokens if token.startswith("s:")}
    assert "m:도커" in morphemes
    assert "m:api" in morphemes
    assert "m:달리" not in morphemes
    assert "m:크" not in morphemes
    assert "s:도커" in surfaces
    assert "s:api" in surfaces
    assert "s:미등록신조어" in surfaces
    assert morphemes.isdisjoint(surfaces)


def test_raw_scores_match_rank_bm25_ties_use_doc_id_and_nonsense_has_no_hits(
    small_index: Path,
) -> None:
    corpus = PublishedCorpus(small_index)
    retriever = Bm25Retriever(corpus)
    result = retriever.retrieve("도커", limit=10)
    token_artifact = json.loads(
        (small_index / "bm25" / "documents.json").read_text(encoding="utf-8")
    )
    reference = BM25Okapi(
        [document["tokens"] for document in token_artifact["documents"]],
        k1=1.5,
        b=0.75,
        epsilon=0.25,
    ).get_scores(retriever.tokenize("도커"))
    reference_by_id = {
        document["doc_id"]: float(score)
        for document, score in zip(token_artifact["documents"], reference, strict=True)
    }

    assert result.doc_ids() == ("AI/a.md", "AI/b.md")
    assert result.hits[0].score == reference_by_id["AI/a.md"]
    assert result.hits[1].score == reference_by_id["AI/b.md"]
    assert result.hits[0].score == result.hits[1].score
    assert not math.isclose(result.hits[0].score, 1.0)
    assert retriever.retrieve("존재하지않는완전무관질의").hits == ()
    assert retriever.retrieve("도커").doc_ids() == result.doc_ids()


def test_loader_rejects_dictionary_or_json_tampering(
    small_index: Path,
) -> None:
    dictionary = small_index / "kiwi-user-dictionary.txt"
    dictionary.write_text(
        dictionary.read_text(encoding="utf-8").replace("도커\tNNP\n", ""),
        encoding="utf-8",
    )
    with pytest.raises(Bm25ArtifactError, match="dictionary.*checksum"):
        Bm25Retriever(PublishedCorpus(small_index))


def test_loader_rejects_unknown_serialized_fields_and_dictionary_load_failure(
    small_index: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = small_index / "bm25" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["unexpected"] = True
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(Bm25ArtifactError, match="unknown keys"):
        Bm25Retriever(PublishedCorpus(small_index))

    manifest.pop("unexpected")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    class BrokenKiwi:
        def __init__(self, *, num_workers: int) -> None:
            assert num_workers == 1

        def load_user_dictionary(self, path: str) -> int:
            raise RuntimeError(f"refused {path}")

    monkeypatch.setattr(
        "agent.retrieval.bm25._import_kiwi_class",
        lambda: BrokenKiwi,
    )
    with pytest.raises(Bm25ArtifactError, match="dictionary load failed"):
        Bm25Retriever(PublishedCorpus(small_index))


def test_build_fails_when_kiwi_is_unavailable_or_version_drifts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = tmp_path / "content"
    _write_post(content, "AI/a.md", title="A", body="도커")
    corpus_policy = _write_corpus_policy(tmp_path / "corpus.toml")
    bm25_policy = _write_bm25_policy(tmp_path / "bm25.toml")

    monkeypatch.setattr(
        "agent.retrieval.bm25._import_kiwi_class",
        lambda: (_ for _ in ()).throw(
            Bm25ArtifactError("Kiwi tokenizer is unavailable")
        ),
    )
    with pytest.raises(CorpusBuildError, match="Kiwi.*unavailable"):
        build_index(
            content_root=content,
            policy_path=corpus_policy,
            bm25_policy_path=bm25_policy,
            output_root=tmp_path / "missing",
        )

    monkeypatch.undo()
    real_version = bm25_module.distribution_version
    monkeypatch.setattr(
        "agent.retrieval.bm25.distribution_version",
        lambda name: "999.0" if name == "kiwipiepy" else real_version(name),
    )
    with pytest.raises(CorpusBuildError, match="kiwipiepy.*version"):
        build_index(
            content_root=content,
            policy_path=corpus_policy,
            bm25_policy_path=bm25_policy,
            output_root=tmp_path / "drift",
        )


def test_registered_factory_uses_artifact_identity_in_fingerprint(
    small_index: Path,
    tmp_path: Path,
) -> None:
    corpus = PublishedCorpus(small_index)
    assert registry.servable[BM25_METHOD_ID].implementation_id == BM25_IMPLEMENTATION_ID

    resolved = registry.servable.create(BM25_METHOD_ID, corpus)
    implementation = create_bm25(corpus, BM25_CONFIG)

    assert resolved.retrieve("도커") == implementation.retrieve("도커")
    assert resolved.identity_config["dictionary_sha256"].startswith("sha256:")
    assert resolved.identity_config["kiwi_version"] == "0.23.2"
    assert resolved.identity_config["corpus_fingerprint"] == corpus.fingerprint
    assert (
        registry.servable.fingerprint(BM25_METHOD_ID, corpus)
        == resolved.fingerprint
        == implementation.fingerprint
    )
    with pytest.raises(ValueError, match="requires a Corpus"):
        registry.servable.fingerprint(BM25_METHOD_ID, corpus.fingerprint)

    changed_policy = _write_bm25_policy(
        tmp_path / "changed-bm25-policy.toml",
        seeds=("도커", "랭그래프"),
    )
    changed_index = tmp_path / "changed-index"
    build_index(
        content_root=small_index.parent / "content",
        policy_path=small_index.parent / "corpus-policy.toml",
        bm25_policy_path=changed_policy,
        output_root=changed_index,
    )
    changed_corpus = PublishedCorpus(changed_index)
    assert changed_corpus.fingerprint == corpus.fingerprint
    changed = registry.servable.create(BM25_METHOD_ID, changed_corpus)
    assert (
        changed.identity_config["dictionary_policy_sha256"]
        != resolved.identity_config["dictionary_policy_sha256"]
    )
    assert (
        changed.identity_config["dictionary_sha256"]
        != resolved.identity_config["dictionary_sha256"]
    )
    assert registry.servable.fingerprint(
        BM25_METHOD_ID, changed_corpus
    ) != registry.servable.fingerprint(BM25_METHOD_ID, corpus)


def test_real_docker_qrel_pins_tree_and_reproduces_baseline_then_fix(
    real_index: Path,
) -> None:
    qrel = json.loads(DOCKER_QREL.read_text(encoding="utf-8"))
    corpus = PublishedCorpus(real_index)
    relevant = set(qrel["qrels"])
    actual_literal = {
        str(doc_id)
        for doc_id in corpus.doc_ids()
        if qrel["query"] in corpus.read(doc_id)
    }

    assert qrel["schema"] == "literal-term-qrels-v1"
    assert qrel["content_tree_sha"] == "71c5bbda097cc20be0cb15ca4666fd6917f89d5f"
    assert qrel["corpus_fingerprint"] == corpus.fingerprint
    assert relevant == actual_literal
    assert len(relevant) == 13

    snapshot = scan_corpus(
        content_root=REAL_CONTENT,
        policy_path=REAL_CORPUS_POLICY,
    )
    assert (
        corpus_fingerprint(
            (document.doc_id, document.checksum) for document in snapshot.documents
        )
        == qrel["corpus_fingerprint"]
    )
    legacy_kiwi = Kiwi(num_workers=1)
    legacy_documents = [
        _legacy_tokens(legacy_kiwi, _legacy_text(document))
        for document in snapshot.documents
    ]
    legacy_ranker = BM25Okapi(legacy_documents)
    legacy_scores = legacy_ranker.get_scores(_legacy_tokens(legacy_kiwi, qrel["query"]))
    legacy_ranking = sorted(
        (
            (float(score), str(document.doc_id))
            for document, score in zip(
                snapshot.documents,
                legacy_scores,
                strict=True,
            )
            if float(score) > 0.0
        ),
        key=lambda item: (-item[0], item[1]),
    )[:13]
    legacy_recall = len(relevant & {doc_id for _, doc_id in legacy_ranking})
    assert legacy_recall == qrel["behavioral_baseline"]["expected_recall_at_13"]
    assert legacy_recall == 3
    assert legacy_ranking[0][0] == pytest.approx(
        qrel["behavioral_baseline"]["raw_top_score"]
    )
    assert legacy_ranking[0][0] == pytest.approx(0.9698229744875738)

    retriever = Bm25Retriever(corpus)
    result = retriever.retrieve(qrel["query"], limit=13)

    assert set(map(str, result.doc_ids())) == relevant
    assert result.hits[0].score is not None
    assert result.hits[0].score > 1.0
