"""Corrected Korean BM25 baseline contracts."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
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
    collect_dictionary_candidates,
    collect_dictionary_evidence,
    create_bm25,
    load_dictionary_policy,
    select_dictionary_entries,
)
from agent.retrieval.corpus import (
    CorpusManifestError,
    PublishedCorpus,
    content_checksum,
)
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


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _refresh_root_artifacts(index: Path, *artifact_paths: str) -> None:
    manifest_path = index / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_path = {entry["path"]: entry for entry in manifest["artifacts"]}
    for artifact_path in artifact_paths:
        payload = (index / artifact_path).read_bytes()
        by_path[artifact_path]["bytes"] = len(payload)
        by_path[artifact_path]["sha256"] = content_checksum(payload)
    manifest["artifacts"] = [by_path[path] for path in sorted(by_path)]
    _write_json(manifest_path, manifest)


def _mutate_fitted(
    index: Path,
    statement: str,
    *,
    refresh_internal_checksum: bool,
    parameters: tuple[object, ...] = (),
) -> None:
    fitted_path = index / "bm25" / "fitted.sqlite3"
    with sqlite3.connect(fitted_path) as connection:
        connection.execute(statement, parameters)
        connection.commit()
        connection.execute("VACUUM")
    if refresh_internal_checksum:
        _refresh_fitted_chain(index)
    else:
        _refresh_root_artifacts(index, "bm25/fitted.sqlite3")


def _refresh_fitted_chain(index: Path) -> None:
    fitted_path = index / "bm25" / "fitted.sqlite3"
    bm25_manifest_path = index / "bm25" / "manifest.json"
    bm25_manifest = json.loads(bm25_manifest_path.read_text(encoding="utf-8"))
    bm25_manifest["fitted"]["sha256"] = content_checksum(fitted_path.read_bytes())
    _write_json(bm25_manifest_path, bm25_manifest)
    _refresh_root_artifacts(
        index,
        "bm25/fitted.sqlite3",
        "bm25/manifest.json",
    )


def _rewrite_evidence_chain(index: Path, evidence: dict[str, object]) -> None:
    evidence_path = index / "bm25" / "dictionary-evidence.json"
    _write_json(evidence_path, evidence)
    evidence_checksum = content_checksum(evidence_path.read_bytes())
    fitted_path = index / "bm25" / "fitted.sqlite3"
    with sqlite3.connect(fitted_path) as connection:
        connection.execute(
            "UPDATE meta SET value = ? WHERE key = 'evidence_sha256'",
            (evidence_checksum,),
        )
        connection.commit()
        connection.execute("VACUUM")
    bm25_manifest_path = index / "bm25" / "manifest.json"
    bm25_manifest = json.loads(bm25_manifest_path.read_text(encoding="utf-8"))
    bm25_manifest["evidence"]["sha256"] = evidence_checksum
    bm25_manifest["fitted"]["sha256"] = content_checksum(fitted_path.read_bytes())
    _write_json(bm25_manifest_path, bm25_manifest)
    _refresh_root_artifacts(
        index,
        "bm25/dictionary-evidence.json",
        "bm25/fitted.sqlite3",
        "bm25/manifest.json",
    )


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


def test_dictionary_candidates_are_audited_but_only_reviewed_seeds_activate(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    _write_post(
        content,
        "AI/post.md",
        title="Container",
        tags=("Docker", "개발도구"),
        body=("도커(Docker) 그리고(and) 크다(Leverage) 검증하고(verify) 없다(None)"),
    )
    snapshot = scan_corpus(
        content_root=content,
        policy_path=_write_corpus_policy(tmp_path / "corpus-policy.toml"),
    )
    policy = load_dictionary_policy(
        _write_bm25_policy(tmp_path / "bm25-policy.toml", seeds=("도커",))
    )

    candidates = collect_dictionary_candidates(snapshot)
    active = select_dictionary_entries(candidates, policy)

    assert {entry.term for entry in candidates} == {
        "개발도구",
        "검증하고",
        "그리고",
        "도커",
        "없다",
        "크다",
    }
    assert [entry.term for entry in active] == ["도커"]
    assert {source.kind for source in active[0].sources} == {"alias", "seed"}
    assert collect_dictionary_evidence(snapshot, policy) == active


def test_dictionary_policy_deny_wins_over_an_approved_seed(tmp_path: Path) -> None:
    policy = load_dictionary_policy(
        _write_bm25_policy(
            tmp_path / "bm25-policy.toml",
            seeds=("도커", "랭그래프"),
            deny=("도커",),
        )
    )

    assert [entry.term for entry in select_dictionary_entries((), policy)] == [
        "랭그래프"
    ]


def test_build_emits_deterministic_safe_artifacts_and_dictionary_provenance(
    small_index: Path,
    tmp_path: Path,
) -> None:
    manifest = json.loads(
        (small_index / "bm25" / "manifest.json").read_text(encoding="utf-8")
    )
    evidence = json.loads(
        (small_index / "bm25" / "dictionary-evidence.json").read_text(encoding="utf-8")
    )
    dictionary = (small_index / "kiwi-user-dictionary.txt").read_text(encoding="utf-8")
    with sqlite3.connect(small_index / "bm25" / "fitted.sqlite3") as connection:
        fitted_doc_ids = [
            row[0]
            for row in connection.execute(
                "SELECT doc_id FROM documents ORDER BY doc_index"
            )
        ]

    assert manifest["schema"] == "kiwi-bm25-manifest-v2"
    assert manifest["method_id"] == BM25_METHOD_ID
    assert manifest["implementation_id"] == BM25_IMPLEMENTATION_ID
    assert manifest["config"] == BM25_CONFIG
    assert manifest["dictionary"]["sha256"].startswith("sha256:")
    root_manifest = json.loads(
        (small_index / "manifest.json").read_text(encoding="utf-8")
    )
    assert [entry["path"] for entry in root_manifest["artifacts"]] == [
        "bm25/dictionary-evidence.json",
        "bm25/fitted.sqlite3",
        "bm25/manifest.json",
        "catalog.json",
        "kiwi-user-dictionary.txt",
        "wikilinks.json",
    ]
    docker_entry = next(
        entry for entry in manifest["dictionary"]["entries"] if entry["term"] == "도커"
    )
    assert {source["kind"] for source in docker_entry["sources"]} == {
        "alias",
        "seed",
    }
    assert evidence["schema"] == "kiwi-dictionary-evidence-v1"
    assert {entry["term"] for entry in evidence["candidates"]} == {"도커"}
    assert fitted_doc_ids == [
        "AI/a.md",
        "AI/b.md",
        "AI/c.md",
        "AI/d.md",
        "AI/e.md",
        "AI/f.md",
    ]
    assert "도커\tNNP\n" in dictionary
    assert not (small_index / "bm25" / "documents.json").exists()
    assert not any(
        path.suffix in {".pickle", ".pkl"} for path in small_index.rglob("*")
    )
    runtime = Bm25Retriever(PublishedCorpus(small_index))
    assert not hasattr(runtime, "_ranker")
    assert not hasattr(runtime, "_token_documents")

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
        "bm25/dictionary-evidence.json",
        "bm25/fitted.sqlite3",
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
    snapshot = scan_corpus(
        content_root=small_index.parent / "content",
        policy_path=small_index.parent / "corpus-policy.toml",
    )
    token_documents = [
        bm25_module._document_tokens(document, tokenizer=retriever._tokenizer)
        for document in snapshot.documents
    ]
    reference = BM25Okapi(
        token_documents,
        k1=1.5,
        b=0.75,
        epsilon=0.25,
    ).get_scores(retriever.tokenize("도커"))
    reference_by_id = {
        str(document.doc_id): float(score)
        for document, score in zip(snapshot.documents, reference, strict=True)
    }

    assert result.doc_ids() == ("AI/a.md", "AI/b.md")
    assert result.hits[0].score == reference_by_id["AI/a.md"]
    assert result.hits[1].score == reference_by_id["AI/b.md"]
    assert result.hits[0].score == result.hits[1].score
    assert not math.isclose(result.hits[0].score, 1.0)
    duplicate_result = retriever.retrieve("도커 도커", limit=10)
    duplicate_reference = BM25Okapi(
        token_documents,
        k1=1.5,
        b=0.75,
        epsilon=0.25,
    ).get_scores(retriever.tokenize("도커 도커"))
    duplicate_reference_by_id = {
        str(document.doc_id): float(score)
        for document, score in zip(
            snapshot.documents,
            duplicate_reference,
            strict=True,
        )
    }
    assert all(
        hit.score == duplicate_reference_by_id[str(hit.doc_id)]
        for hit in duplicate_result.hits
    )
    assert retriever.retrieve("존재하지않는완전무관질의").hits == ()
    assert retriever.retrieve("도커").doc_ids() == result.doc_ids()


def test_runtime_retains_one_verified_fitted_snapshot_after_file_replacement(
    small_index: Path,
) -> None:
    retriever = Bm25Retriever(PublishedCorpus(small_index))
    before = retriever.retrieve("도커")

    (small_index / "bm25" / "fitted.sqlite3").write_bytes(b"replaced after load")

    assert retriever.retrieve("도커") == before
    with pytest.raises(
        CorpusManifestError, match="fitted.sqlite3.*checksum|byte count"
    ):
        Bm25Retriever(PublishedCorpus(small_index))


def test_runtime_serializes_concurrent_queries_and_has_explicit_lifecycle(
    small_index: Path,
) -> None:
    retriever = Bm25Retriever(PublishedCorpus(small_index))
    expected = retriever.retrieve("도커")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(lambda _: retriever.retrieve("도커"), range(64)))

    assert results == (expected,) * 64
    retriever.close()
    retriever.close()
    with pytest.raises(RuntimeError, match="closed"):
        retriever.retrieve("도커")
    with pytest.raises(RuntimeError, match="closed"):
        retriever.retrieve("도커", limit=0)


def test_outer_manifest_rejects_dictionary_tampering(
    small_index: Path,
) -> None:
    dictionary = small_index / "kiwi-user-dictionary.txt"
    dictionary.write_text(
        dictionary.read_text(encoding="utf-8").replace("도커\tNNP\n", ""),
        encoding="utf-8",
    )
    with pytest.raises(CorpusManifestError, match="artifact checksum"):
        PublishedCorpus(small_index)


def test_loader_rejects_unknown_serialized_fields_and_dictionary_load_failure(
    small_index: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = small_index / "bm25" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["unexpected"] = True
    _write_json(manifest_path, manifest)
    _refresh_root_artifacts(small_index, "bm25/manifest.json")
    with pytest.raises(Bm25ArtifactError, match="unknown keys"):
        Bm25Retriever(PublishedCorpus(small_index))

    manifest.pop("unexpected")
    _write_json(manifest_path, manifest)
    _refresh_root_artifacts(small_index, "bm25/manifest.json")

    class BrokenKiwi:
        def __init__(
            self,
            *,
            num_workers: int,
            model_type: str,
            load_default_dict: bool,
            load_typo_dict: bool,
            load_multi_dict: bool,
        ) -> None:
            assert num_workers == 1
            assert model_type == "cong"
            assert load_default_dict is True
            assert load_typo_dict is False
            assert load_multi_dict is False

        def load_user_dictionary(self, path: str) -> int:
            raise RuntimeError(f"refused {path}")

    monkeypatch.setattr(
        "agent.retrieval.bm25._import_kiwi_class",
        lambda: BrokenKiwi,
    )
    with pytest.raises(Bm25ArtifactError, match="dictionary load failed"):
        Bm25Retriever(PublishedCorpus(small_index))

    class WrongTag:
        form = "도커"
        tag = "NNG"

    class WrongSeedKiwi:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["model_type"] == "cong"

        def load_user_dictionary(self, path: str) -> int:
            return 1

        def tokenize(self, text: str) -> list[WrongTag]:
            return [WrongTag()]

    monkeypatch.setattr(
        "agent.retrieval.bm25._import_kiwi_class",
        lambda: WrongSeedKiwi,
    )
    with pytest.raises(Bm25ArtifactError, match="one exact NNP"):
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
    monkeypatch.setattr(
        "agent.retrieval.bm25.distribution_version",
        lambda name: "999.0" if name == "kiwipiepy-model" else real_version(name),
    )
    with pytest.raises(CorpusBuildError, match="kiwipiepy-model.*version"):
        build_index(
            content_root=content,
            policy_path=corpus_policy,
            bm25_policy_path=bm25_policy,
            output_root=tmp_path / "model-drift",
        )


def test_build_fits_once_and_runtime_never_imports_rank_bm25(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = tmp_path / "content"
    _write_post(content, "AI/a.md", title="A", body="도커")
    real_class = bm25_module._import_bm25_class()
    fits = 0

    class CountedBm25(real_class):
        def __init__(self, *args: object, **kwargs: object) -> None:
            nonlocal fits
            fits += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        bm25_module,
        "_import_bm25_class",
        lambda: CountedBm25,
    )
    index = tmp_path / "index"
    build_index(
        content_root=content,
        policy_path=_write_corpus_policy(tmp_path / "corpus.toml"),
        bm25_policy_path=_write_bm25_policy(tmp_path / "bm25.toml"),
        output_root=index,
    )
    assert fits == 1

    monkeypatch.setattr(
        bm25_module,
        "_import_bm25_class",
        lambda: (_ for _ in ()).throw(AssertionError("runtime refit")),
    )
    assert Bm25Retriever(PublishedCorpus(index)).retrieve("도커").query == "도커"


def test_identity_is_manifest_only_and_registry_constructs_one_tokenizer(
    small_index: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = PublishedCorpus(small_index)
    original_init = bm25_module._KiwiTokenizer.__init__
    constructions = 0

    def counted_init(
        self: object, dictionary_payload: bytes, *args: object, **kwargs: object
    ) -> None:
        nonlocal constructions
        constructions += 1
        original_init(self, dictionary_payload, *args, **kwargs)

    monkeypatch.setattr(bm25_module._KiwiTokenizer, "__init__", counted_init)
    original_snapshot = bm25_module._snapshot_connection
    original_validate_fitted = bm25_module._validate_fitted
    original_import_numpy = bm25_module._import_numpy

    def bomb(*args: object, **kwargs: object) -> object:
        raise AssertionError("identity loaded fitted runtime state")

    monkeypatch.setattr(bm25_module, "_snapshot_connection", bomb)
    monkeypatch.setattr(bm25_module, "_validate_fitted", bomb)
    monkeypatch.setattr(bm25_module, "_import_numpy", bomb)

    fingerprint = registry.servable.fingerprint(BM25_METHOD_ID, corpus)
    assert constructions == 0
    identity = registry.servable[BM25_METHOD_ID].identity_config(corpus)
    assert set(identity) == {
        "bm25_manifest_sha256",
        "config",
        "config_sha256",
        "corpus_fingerprint",
        "dictionary_policy_sha256",
        "dictionary_sha256",
        "evidence_sha256",
        "fitted_sha256",
        "kiwi_model_version",
        "kiwi_version",
        "numpy_version",
        "rank_bm25_version",
        "sqlite_version",
    }
    assert fingerprint.startswith("sha256:")
    monkeypatch.setattr(bm25_module, "_snapshot_connection", original_snapshot)
    monkeypatch.setattr(bm25_module, "_validate_fitted", original_validate_fitted)
    monkeypatch.setattr(bm25_module, "_import_numpy", original_import_numpy)
    registry.servable.create(BM25_METHOD_ID, corpus)
    assert constructions == 1


def test_inner_checksums_and_canonical_dictionary_bytes_reject_coherent_tampering(
    small_index: Path,
) -> None:
    fitted = small_index / "bm25" / "fitted.sqlite3"
    with sqlite3.connect(fitted) as connection:
        connection.execute(
            "UPDATE documents SET doc_len = doc_len + 1 WHERE doc_index = 0"
        )
    _refresh_root_artifacts(small_index, "bm25/fitted.sqlite3")
    with pytest.raises(Bm25ArtifactError, match="fitted.*checksum"):
        Bm25Retriever(PublishedCorpus(small_index))


def test_stale_internal_evidence_checksum_is_rejected(small_index: Path) -> None:
    evidence = small_index / "bm25" / "dictionary-evidence.json"
    evidence.write_bytes(evidence.read_bytes() + b" ")
    _refresh_root_artifacts(small_index, "bm25/dictionary-evidence.json")

    with pytest.raises(Bm25ArtifactError, match="evidence checksum"):
        Bm25Retriever(PublishedCorpus(small_index))


def test_canonical_dictionary_bytes_reject_coherent_manifest_tampering(
    small_index: Path,
) -> None:
    dictionary_path = small_index / "kiwi-user-dictionary.txt"
    dictionary_path.write_text(
        dictionary_path.read_text(encoding="utf-8").replace("도커\tNNP\n", ""),
        encoding="utf-8",
    )
    bm25_manifest_path = small_index / "bm25" / "manifest.json"
    bm25_manifest = json.loads(bm25_manifest_path.read_text(encoding="utf-8"))
    bm25_manifest["dictionary"]["sha256"] = content_checksum(
        dictionary_path.read_bytes()
    )
    _write_json(bm25_manifest_path, bm25_manifest)
    _refresh_root_artifacts(
        small_index,
        "kiwi-user-dictionary.txt",
        "bm25/manifest.json",
    )

    with pytest.raises(Bm25ArtifactError, match="canonical manifest entries"):
        Bm25Retriever(PublishedCorpus(small_index))


def test_active_dictionary_requires_exactly_one_policy_seed_source(
    small_index: Path,
) -> None:
    manifest_path = small_index / "bm25" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = manifest["dictionary"]["entries"][0]["sources"]
    sources.append(
        {
            "evidence": "도커",
            "kind": "seed",
            "source": "forged-policy",
        }
    )
    sources.sort(
        key=lambda source: (
            source["kind"],
            source["source"],
            source["evidence"],
        )
    )
    _write_json(manifest_path, manifest)
    _refresh_root_artifacts(small_index, "bm25/manifest.json")

    with pytest.raises(Bm25ArtifactError, match="exactly one reviewed seed"):
        Bm25Retriever(PublishedCorpus(small_index))


def test_evidence_provenance_must_be_sorted_unique_and_changes_identity(
    small_index: Path,
) -> None:
    corpus = PublishedCorpus(small_index)
    before = registry.servable.fingerprint(BM25_METHOD_ID, corpus)
    evidence_path = small_index / "bm25" / "dictionary-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["candidates"].append(
        {
            "pos": "NNP",
            "sources": [
                {
                    "evidence": "새후보",
                    "kind": "tag",
                    "source": "AI/a.md",
                }
            ],
            "term": "새후보",
        }
    )
    evidence["candidates"].sort(key=lambda entry: entry["term"])
    evidence["candidate_count"] += 1
    _rewrite_evidence_chain(small_index, evidence)

    changed_corpus = PublishedCorpus(small_index)
    assert registry.servable.fingerprint(BM25_METHOD_ID, changed_corpus) != before
    assert Bm25Retriever(changed_corpus).retrieve("도커").hits

    evidence["candidates"][0]["sources"].reverse()
    evidence["candidates"][0]["sources"].append(
        dict(evidence["candidates"][0]["sources"][0])
    )
    _rewrite_evidence_chain(small_index, evidence)
    with pytest.raises(Bm25ArtifactError, match="sorted and unique"):
        Bm25Retriever(PublishedCorpus(small_index))


def test_coherent_fitted_mutation_is_rejected_by_state_validation(
    small_index: Path,
) -> None:
    _mutate_fitted(
        small_index,
        "UPDATE documents SET doc_len = doc_len + 1 WHERE doc_index = 0",
        refresh_internal_checksum=True,
    )
    with pytest.raises(
        Bm25ArtifactError,
        match="document lengths|document length|doc_len",
    ):
        Bm25Retriever(PublishedCorpus(small_index))


def test_strict_manifest_count_and_fitted_token_validation(
    small_index: Path,
) -> None:
    bm25_manifest_path = small_index / "bm25" / "manifest.json"
    bm25_manifest = json.loads(bm25_manifest_path.read_text(encoding="utf-8"))
    bm25_manifest["document_count"] = 6.0
    _write_json(bm25_manifest_path, bm25_manifest)
    _refresh_root_artifacts(small_index, "bm25/manifest.json")
    with pytest.raises(Bm25ArtifactError, match="document_count"):
        Bm25Retriever(PublishedCorpus(small_index))


@pytest.mark.parametrize("token", ["invalid", "s:foo?"])
def test_coherent_fitted_token_mutation_is_rejected(
    small_index: Path,
    token: str,
) -> None:
    _mutate_fitted(
        small_index,
        "UPDATE terms SET token = ? WHERE term_id = 0",
        refresh_internal_checksum=True,
        parameters=(token,),
    )
    with pytest.raises(Bm25ArtifactError, match="token/idf"):
        Bm25Retriever(PublishedCorpus(small_index))


def test_fitted_sqlite_requires_unique_term_and_posting_constraints(
    small_index: Path,
) -> None:
    fitted = small_index / "bm25" / "fitted.sqlite3"
    with sqlite3.connect(fitted) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys=OFF;
            ALTER TABLE postings RENAME TO old_postings;
            ALTER TABLE terms RENAME TO old_terms;
            CREATE TABLE terms (
                term_id INTEGER PRIMARY KEY,
                token TEXT NOT NULL,
                idf REAL NOT NULL
            );
            CREATE TABLE postings (
                term_id INTEGER NOT NULL,
                doc_index INTEGER NOT NULL,
                tf INTEGER NOT NULL,
                PRIMARY KEY (term_id, doc_index),
                FOREIGN KEY (term_id) REFERENCES terms(term_id),
                FOREIGN KEY (doc_index) REFERENCES documents(doc_index)
            ) WITHOUT ROWID;
            INSERT INTO terms SELECT * FROM old_terms;
            INSERT INTO postings SELECT * FROM old_postings;
            DROP TABLE old_postings;
            DROP TABLE old_terms;
            """
        )
        by_frequency: dict[int, list[tuple[int, str]]] = {}
        for term_id, token, frequency in connection.execute(
            "SELECT t.term_id, t.token, COUNT(p.doc_index) "
            "FROM terms AS t JOIN postings AS p USING(term_id) "
            "GROUP BY t.term_id ORDER BY t.term_id"
        ):
            by_frequency.setdefault(frequency, []).append((term_id, token))
        pair = next(values[:2] for values in by_frequency.values() if len(values) >= 2)
        connection.execute(
            "UPDATE terms SET token = ? WHERE term_id = ?",
            (pair[0][1], pair[1][0]),
        )
        connection.commit()
        connection.execute("VACUUM")
    _refresh_fitted_chain(small_index)

    with pytest.raises(Bm25ArtifactError, match="index constraints"):
        Bm25Retriever(PublishedCorpus(small_index))


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("PRAGMA application_id=0", "application_id"),
        ("PRAGMA user_version=99", "user_version"),
        ("PRAGMA page_size=8192", "page_size"),
        (
            "UPDATE meta SET value = '06' WHERE key = 'document_count'",
            "canonical non-negative integer",
        ),
        ("CREATE TABLE unexpected(value TEXT)", "unknown objects"),
    ],
)
def test_fitted_sqlite_rejects_pragma_metadata_and_schema_mutations(
    small_index: Path,
    statement: str,
    message: str,
) -> None:
    _mutate_fitted(
        small_index,
        statement,
        refresh_internal_checksum=True,
    )

    with pytest.raises(Bm25ArtifactError, match=message):
        Bm25Retriever(PublishedCorpus(small_index))


def test_fitted_sqlite_rejects_coherent_unposted_term(small_index: Path) -> None:
    fitted_path = small_index / "bm25" / "fitted.sqlite3"
    with sqlite3.connect(fitted_path) as connection:
        document_count = connection.execute(
            "SELECT CAST(value AS INTEGER) FROM meta WHERE key = 'document_count'"
        ).fetchone()[0]
        term_id = connection.execute(
            "SELECT COALESCE(MAX(term_id), -1) + 1 FROM terms"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO terms(term_id, token, idf) VALUES (?, 's:고아용어', 0.0)",
            (term_id,),
        )
        frequencies = connection.execute(
            "SELECT t.term_id, COUNT(p.doc_index) "
            "FROM terms AS t LEFT JOIN postings AS p USING(term_id) "
            "GROUP BY t.term_id ORDER BY t.term_id"
        ).fetchall()
        raw_idfs = [
            math.log(document_count - frequency + 0.5) - math.log(frequency + 0.5)
            for _, frequency in frequencies
        ]
        average_idf = sum(raw_idfs) / len(raw_idfs)
        for (stored_term_id, _), raw_idf in zip(frequencies, raw_idfs, strict=True):
            connection.execute(
                "UPDATE terms SET idf = ? WHERE term_id = ?",
                (
                    bm25_module.EPSILON * average_idf if raw_idf < 0 else raw_idf,
                    stored_term_id,
                ),
            )
        connection.execute(
            "UPDATE meta SET value = ? WHERE key = 'term_count'",
            (str(len(frequencies)),),
        )
        connection.execute(
            "UPDATE meta SET value = ? WHERE key = 'average_idf'",
            (repr(average_idf),),
        )
        connection.commit()
        connection.execute("VACUUM")
    _refresh_fitted_chain(small_index)

    with pytest.raises(Bm25ArtifactError, match="invalid document frequency"):
        Bm25Retriever(PublishedCorpus(small_index))


def test_positive_score_only_semantics_cover_negative_zero_and_absent(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    _write_post(
        content,
        "AI/a.md",
        title="동일",
        body="공통용어 절반용어",
    )
    _write_post(content, "AI/b.md", title="동일", body="공통용어")
    index = tmp_path / "index"
    build_index(
        content_root=content,
        policy_path=_write_corpus_policy(tmp_path / "corpus.toml"),
        bm25_policy_path=_write_bm25_policy(
            tmp_path / "bm25.toml",
            seeds=(),
        ),
        output_root=index,
    )
    retriever = Bm25Retriever(PublishedCorpus(index))
    with sqlite3.connect(index / "bm25" / "fitted.sqlite3") as connection:
        idfs = dict(
            connection.execute(
                "SELECT token, idf FROM terms "
                "WHERE token IN ('s:공통용어', 's:절반용어')"
            )
        )

    assert idfs["s:공통용어"] < 0
    assert idfs["s:절반용어"] == 0
    assert retriever.retrieve("공통용어").hits == ()
    assert retriever.retrieve("절반용어").hits == ()
    assert retriever.retrieve("완전부재").hits == ()


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
    assert resolved.identity_config["evidence_sha256"].startswith("sha256:")
    assert resolved.identity_config["fitted_sha256"].startswith("sha256:")
    assert resolved.identity_config["kiwi_model_version"] == "0.23.0"
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

    assert set(qrel) == {
        "behavioral_baseline",
        "corrected_baseline",
        "generator",
        "qrels",
        "query",
        "schema",
    }
    assert qrel["schema"] == "literal-term-qrels-v1"
    assert set(qrel["behavioral_baseline"]) == {
        "expected_recall_at_13",
        "implementation",
        "top_doc_id",
    }
    assert set(qrel["corrected_baseline"]) == {
        "expected_recall_at_13",
        "implementation",
        "load_multi_dict",
        "load_typo_dict",
        "model_type",
    }
    assert relevant == actual_literal
    assert len(relevant) == 13

    snapshot = scan_corpus(
        content_root=REAL_CONTENT,
        policy_path=REAL_CORPUS_POLICY,
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
    assert legacy_ranking[0][1] == qrel["behavioral_baseline"]["top_doc_id"]
    assert legacy_ranking[0][0] > 0.0

    retriever = Bm25Retriever(corpus)
    result = retriever.retrieve(qrel["query"], limit=13)

    assert set(map(str, result.doc_ids())) == relevant
    assert (
        len(relevant & set(map(str, result.doc_ids())))
        == qrel["corrected_baseline"]["expected_recall_at_13"]
    )
    assert qrel["corrected_baseline"]["implementation"] == BM25_IMPLEMENTATION_ID
    manifest = json.loads(
        (real_index / "bm25" / "manifest.json").read_text(encoding="utf-8")
    )
    assert {entry["term"] for entry in manifest["dictionary"]["entries"]} == {
        "도커",
        "랭그래프",
    }
    assert manifest["config"]["tokenizer"] == BM25_CONFIG["tokenizer"]
    assert manifest["config"]["tokenizer"]["model_type"] == "cong"
    assert manifest["config"]["tokenizer"]["load_default_dict"] is True
    assert manifest["config"]["tokenizer"]["load_typo_dict"] is False
    assert manifest["config"]["tokenizer"]["load_multi_dict"] is False
    assert retriever.tokenize("크다") == ["s:크다"]
    assert retriever.tokenize("검증하고") == ["m:검증", "s:검증하고"]
    assert retriever.tokenize("개발도구") == [
        "m:개발",
        "m:도구",
        "s:개발도구",
    ]
    assert result.hits[0].score is not None
    assert result.hits[0].score > 1.0


def test_real_fitted_sqlite_stays_below_cloud_run_memory_gate(
    real_index: Path,
) -> None:
    fitted = real_index / "bm25" / "fitted.sqlite3"
    assert fitted.stat().st_size < 8 * 1024 * 1024
    measurement = textwrap.dedent(
        f"""
        import json
        import os
        import sys
        from pathlib import Path

        from agent.retrieval.corpus import PublishedCorpus
        from agent.retrieval.registry import registry
        import agent.retrieval.bm25

        corpus = PublishedCorpus(Path({str(real_index)!r}))
        retriever = registry.servable.create("bm25", corpus)
        assert retriever.retrieve("도커", limit=13).hits
        if sys.platform.startswith("linux"):
            status = dict()
            for line in Path("/proc/self/status").read_text().splitlines():
                key, separator, rest = line.partition(":")
                if separator and key in {{"VmHWM", "VmRSS"}}:
                    value, unit = rest.split()
                    if unit != "kB":
                        raise RuntimeError(f"unexpected Linux memory unit: {{unit}}")
                    status[key] = int(value) / 1024
            peak_mib = status["VmHWM"]
            steady_mib = status["VmRSS"]
        elif sys.platform == "darwin":
            import resource
            import subprocess

            # Read current RSS first. Parsing the ``ps`` response can itself move
            # the process high-water mark by one macOS page (16 KiB), so sampling
            # ru_maxrss first creates an internally inconsistent pair.
            steady_mib = int(
                subprocess.check_output(
                    ["ps", "-o", "rss=", "-p", str(os.getpid())],
                    text=True,
                ).strip()
            ) / 1024
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            peak_mib = peak / 1024 / 1024
        else:
            raise RuntimeError(f"unsupported memory-metric platform: {{sys.platform}}")
        print(json.dumps(dict(peak_mib=peak_mib, steady_mib=steady_mib)))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", measurement],
        check=True,
        capture_output=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
        text=True,
        timeout=60,
    )
    memory = json.loads(completed.stdout)
    assert memory["steady_mib"] <= memory["peak_mib"], memory
    assert memory["steady_mib"] < 500.0, memory
    assert memory["peak_mib"] < 550.0, memory
