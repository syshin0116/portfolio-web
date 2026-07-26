"""Runtime manifest-backed Corpus contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.retrieval.corpus import (
    CorpusManifestError,
    PublishedCorpus,
    content_checksum,
)
from agent.retrieval.corpus_build import build_index
from agent.retrieval.protocol import Corpus, DocId


def _fixture_index(tmp_path: Path) -> Path:
    content = tmp_path / "content"
    post = content / "AI" / "한글.md"
    post.parent.mkdir(parents=True)
    post.write_text(
        "---\ntitle: 한글\npublished: 2024-01-02\n---\n본문\n",
        encoding="utf-8",
    )
    policy = tmp_path / "policy.toml"
    policy.write_text(
        "schema_version = 1\nno_frontmatter_allowlist = []\n",
        encoding="utf-8",
    )
    index = tmp_path / "index"
    build_index(content_root=content, policy_path=policy, output_root=index)
    return index


def test_manifest_corpus_implements_shared_protocol_and_reads_exact_doc(
    tmp_path: Path,
) -> None:
    index = _fixture_index(tmp_path)

    corpus = PublishedCorpus(index)

    assert isinstance(corpus, Corpus)
    assert corpus.doc_ids() == (DocId("AI/한글.md"),)
    assert corpus.read(DocId("AI/한글.md")).endswith("본문\n")
    assert corpus.fingerprint.startswith("sha256:")
    with pytest.raises(KeyError, match="not in the published corpus"):
        corpus.read(DocId("AI/not-published.md"))


def test_loader_rejects_a_tampered_or_any_extra_regular_mirror_file(
    tmp_path: Path,
) -> None:
    index = _fixture_index(tmp_path)
    (index / "posts" / "AI" / "한글.md").write_text("tampered", encoding="utf-8")

    with pytest.raises(CorpusManifestError, match="checksum"):
        PublishedCorpus(index)

    index = _fixture_index(tmp_path / "extra")
    extra = index / "posts" / "AI" / "extra.txt"
    extra.write_text("not manifested", encoding="utf-8")
    with pytest.raises(CorpusManifestError, match="unexpected mirror regular file"):
        PublishedCorpus(index)


def test_manifest_protects_every_derived_artifact(tmp_path: Path) -> None:
    index = _fixture_index(tmp_path)
    manifest = json.loads((index / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema"] == "published-corpus-manifest-v2"
    artifact_paths = sorted(
        path.relative_to(index).as_posix()
        for path in index.rglob("*")
        if path.is_file()
        and path != index / "manifest.json"
        and not path.is_relative_to(index / "posts")
    )
    assert manifest["artifacts"] == [
        {
            "bytes": len((index / name).read_bytes()),
            "path": name,
            "sha256": content_checksum((index / name).read_bytes()),
        }
        for name in artifact_paths
    ]
    assert {"catalog.json", "wikilinks.json"} <= set(artifact_paths)


@pytest.mark.parametrize("artifact_name", ["catalog.json", "wikilinks.json"])
def test_loader_rejects_a_tampered_derived_artifact(
    tmp_path: Path,
    artifact_name: str,
) -> None:
    index = _fixture_index(tmp_path)
    artifact = index / artifact_name
    payload = artifact.read_bytes()
    artifact.write_bytes(b"!" + payload[1:])

    with pytest.raises(CorpusManifestError, match=rf"{artifact_name}.*checksum"):
        PublishedCorpus(index)


def test_loader_rejects_any_extra_top_level_entry(tmp_path: Path) -> None:
    index = _fixture_index(tmp_path)
    (index / "unexpected.bin").write_bytes(b"not manifested")

    with pytest.raises(CorpusManifestError, match="unexpected.*artifact"):
        PublishedCorpus(index)


def test_loader_rejects_any_symlink_below_posts(tmp_path: Path) -> None:
    index = _fixture_index(tmp_path)
    target = tmp_path / "not-markdown.txt"
    target.write_text("outside", encoding="utf-8")
    (index / "posts" / "linked.txt").symlink_to(target)

    with pytest.raises(CorpusManifestError, match="must not contain symlinks"):
        PublishedCorpus(index)


@pytest.mark.parametrize("location", ["manifest", "document"])
def test_loader_rejects_unknown_manifest_keys(
    tmp_path: Path,
    location: str,
) -> None:
    index = _fixture_index(tmp_path)
    manifest_path = index / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if location == "manifest":
        manifest["future_field"] = True
    else:
        manifest["documents"][0]["future_field"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CorpusManifestError, match="unknown keys.*future_field"):
        PublishedCorpus(index)


def test_loader_rejects_manifest_fingerprint_and_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    index = _fixture_index(tmp_path)
    manifest_path = index / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["corpus_fingerprint"] = "sha256:" + ("0" * 64)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CorpusManifestError, match="fingerprint"):
        PublishedCorpus(index)

    manifest_path.write_text(
        '{"schema":"published-corpus-manifest-v2",'
        '"schema":"published-corpus-manifest-v2"}',
        encoding="utf-8",
    )
    with pytest.raises(CorpusManifestError, match="duplicate"):
        PublishedCorpus(index)
