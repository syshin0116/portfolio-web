"""Published-corpus build boundary contracts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.retrieval import corpus_build
from agent.retrieval.corpus import PublishedCorpus
from agent.retrieval.corpus_build import (
    CorpusBuildError,
    build_index,
    validate_portable_doc_ids,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_CONTENT = REPO_ROOT / "content"
REAL_POLICY = REPO_ROOT / "agent" / "corpus-policy.toml"


def _write_policy(path: Path, *doc_ids: str) -> Path:
    values = ",\n  ".join(json.dumps(doc_id, ensure_ascii=False) for doc_id in doc_ids)
    path.write_text(
        f"schema_version = 1\nno_frontmatter_allowlist = [\n  {values}\n]\n",
        encoding="utf-8",
    )
    return path


def _write_post(
    content: Path, doc_id: str, frontmatter: str, body: str = "body"
) -> Path:
    path = content / doc_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\n{frontmatter.rstrip()}\n---\n{body}\n",
        encoding="utf-8",
    )
    return path


def _write_raw(content: Path, doc_id: str, raw: str) -> Path:
    path = content / doc_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    return path


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_doc_ids(index: Path) -> tuple[set[str], set[str], set[str], set[str]]:
    mirrored = {
        path.relative_to(index / "posts").as_posix()
        for path in (index / "posts").rglob("*.md")
    }
    manifest = _read_json(index / "manifest.json")
    catalog = _read_json(index / "catalog.json")
    wikilinks = _read_json(index / "wikilinks.json")
    return (
        mirrored,
        {entry["doc_id"] for entry in manifest["documents"]},
        {entry["doc_id"] for entry in catalog["documents"]},
        set(wikilinks["adjacency"]),
    )


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode()
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def test_build_uses_one_scan_and_identical_published_set_for_every_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = tmp_path / "content"
    _write_post(content, "AI/public.md", "title: Public\ndraft: false")
    _write_post(
        content,
        "AI/legacy-date.md",
        'title: Legacy\npublished: "2024-04-09 22:44 +0900"',
    )
    _write_post(content, "AI/published-true.md", "published: true")
    _write_post(content, "AI/draft.md", "draft: true\npublished: true")
    _write_post(content, "AI/private.md", "private: true")
    _write_post(content, "AI/unpublished.md", "published: false")
    _write_raw(content, "AI/_hidden.md", "hidden without frontmatter\n")
    _write_raw(content, "wiki/legacy.md", "# Legacy public note\n")
    policy = _write_policy(tmp_path / "policy.toml", "wiki/legacy.md")
    index = tmp_path / "index"

    scans = 0
    real_scan = corpus_build.scan_corpus

    def counted_scan(*args: object, **kwargs: object) -> object:
        nonlocal scans
        scans += 1
        return real_scan(*args, **kwargs)

    monkeypatch.setattr(corpus_build, "scan_corpus", counted_scan)

    report = build_index(content_root=content, policy_path=policy, output_root=index)

    expected = {
        "AI/legacy-date.md",
        "AI/public.md",
        "AI/published-true.md",
        "wiki/legacy.md",
    }
    assert scans == 1
    assert report.document_count == len(expected)
    assert _artifact_doc_ids(index) == (expected, expected, expected, expected)
    assert not (index / "posts" / "AI" / "_hidden.md").exists()
    assert not (index / "posts" / "AI" / "draft.md").exists()

    manifest = _read_json(index / "manifest.json")
    assert manifest["source_markdown_count"] == 8
    assert manifest["excluded_documents"] == [
        {"doc_id": "AI/_hidden.md", "reason": "basename-leading-underscore"},
        {"doc_id": "AI/draft.md", "reason": "draft"},
        {"doc_id": "AI/private.md", "reason": "private"},
        {"doc_id": "AI/unpublished.md", "reason": "published-false"},
    ]
    catalog = _read_json(index / "catalog.json")
    legacy = next(
        entry
        for entry in catalog["documents"]
        if entry["doc_id"] == "AI/legacy-date.md"
    )
    assert legacy["metadata"]["published"] == "2024-04-09 22:44 +0900"


@pytest.mark.parametrize("field", ["draft", "private"])
@pytest.mark.parametrize("value", ['"false"', "0", "null", "[]"])
def test_draft_and_private_when_present_require_strict_booleans(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    content = tmp_path / "content"
    _write_post(content, "AI/post.md", f"{field}: {value}")
    policy = _write_policy(tmp_path / "policy.toml")

    with pytest.raises(CorpusBuildError, match=rf"{field}.*boolean"):
        build_index(
            content_root=content,
            policy_path=policy,
            output_root=tmp_path / "index",
        )


@pytest.mark.parametrize(
    "value",
    [
        "null",
        "0",
        "42",
        "[]",
        "{date: 2024-01-01}",
        '"2024-01-01 12:00 +9999"',
    ],
)
def test_published_rejects_values_other_than_boolean_or_date_like(
    tmp_path: Path,
    value: str,
) -> None:
    content = tmp_path / "content"
    _write_post(content, "AI/post.md", f"published: {value}")
    policy = _write_policy(tmp_path / "policy.toml")

    with pytest.raises(
        CorpusBuildError,
        match=r"published.*(boolean or date|date-like)",
    ):
        build_index(
            content_root=content,
            policy_path=policy,
            output_root=tmp_path / "index",
        )


def test_published_rejects_a_non_date_string(tmp_path: Path) -> None:
    content = tmp_path / "content"
    _write_post(content, "AI/post.md", 'published: "sometime later"')
    policy = _write_policy(tmp_path / "policy.toml")

    with pytest.raises(CorpusBuildError, match="published.*date-like"):
        build_index(
            content_root=content,
            policy_path=policy,
            output_root=tmp_path / "index",
        )


def test_any_unlisted_key_fails_until_semantics_are_decided(tmp_path: Path) -> None:
    content = tmp_path / "content"
    _write_post(content, "AI/post.md", "unlisted: false")
    policy = _write_policy(tmp_path / "policy.toml")

    with pytest.raises(CorpusBuildError, match="unlisted"):
        build_index(
            content_root=content,
            policy_path=policy,
            output_root=tmp_path / "index",
        )


@pytest.mark.parametrize(
    ("frontmatter", "message"),
    [
        ("title: [unterminated", "YAML"),
        ("title: One\ntitle: Two", "duplicate"),
        ("nested:\n  value: one\n  value: two", "duplicate"),
        ("- one\n- two", "mapping"),
        ("", "mapping"),
    ],
)
def test_malformed_duplicate_and_nonmapping_frontmatter_fail_closed(
    tmp_path: Path,
    frontmatter: str,
    message: str,
) -> None:
    content = tmp_path / "content"
    _write_post(content, "AI/post.md", frontmatter)
    policy = _write_policy(tmp_path / "policy.toml")

    with pytest.raises(CorpusBuildError, match=message):
        build_index(
            content_root=content,
            policy_path=policy,
            output_root=tmp_path / "index",
        )


def test_no_frontmatter_requires_exact_nonstale_allowlist(tmp_path: Path) -> None:
    content = tmp_path / "content"
    _write_raw(content, "wiki/legacy.md", "# legacy\n")

    with pytest.raises(CorpusBuildError, match="not allowlisted"):
        build_index(
            content_root=content,
            policy_path=_write_policy(tmp_path / "missing.toml"),
            output_root=tmp_path / "missing-index",
        )

    _write_post(content, "wiki/now-modern.md", "title: Modern")
    with pytest.raises(CorpusBuildError, match="stale"):
        build_index(
            content_root=content,
            policy_path=_write_policy(
                tmp_path / "stale.toml",
                "wiki/legacy.md",
                "wiki/now-modern.md",
            ),
            output_root=tmp_path / "stale-index",
        )


def test_frontmatter_after_a_leading_blank_is_an_allowlisted_legacy_document(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    raw = "\n---\ntitle: Legacy shape\ndraft: true\n---\nbody\n"
    _write_raw(content, "Projects/legacy.md", raw)
    policy = _write_policy(tmp_path / "policy.toml", "Projects/legacy.md")
    index = tmp_path / "index"

    build_index(content_root=content, policy_path=policy, output_root=index)

    assert (index / "posts" / "Projects" / "legacy.md").read_text() == raw


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
@pytest.mark.parametrize("kind", ["broken", "out-of-tree"])
def test_broken_and_out_of_tree_symlinks_fail(
    tmp_path: Path,
    kind: str,
) -> None:
    content = tmp_path / "content"
    content.mkdir()
    link = content / "AI" / "linked.md"
    link.parent.mkdir()
    if kind == "broken":
        link.symlink_to(tmp_path / "does-not-exist.md")
    else:
        outside = _write_raw(tmp_path, "outside.md", "# secret\n")
        link.symlink_to(outside)
    policy = _write_policy(tmp_path / "policy.toml")

    with pytest.raises(CorpusBuildError, match=kind.replace("-", ".*")):
        build_index(
            content_root=content,
            policy_path=policy,
            output_root=tmp_path / "index",
        )


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_in_tree_symlink_is_copied_as_a_regular_mirror_document(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    original = _write_post(content, "AI/original.md", "title: Original")
    linked = content / "AI" / "linked.md"
    linked.symlink_to(original)
    policy = _write_policy(tmp_path / "policy.toml")
    index = tmp_path / "index"

    build_index(content_root=content, policy_path=policy, output_root=index)

    mirrored = index / "posts" / "AI" / "linked.md"
    assert mirrored.read_bytes() == original.read_bytes()
    assert not mirrored.is_symlink()


def test_portable_path_validation_rejects_nfc_and_casefold_collisions() -> None:
    with pytest.raises(CorpusBuildError, match="NFC/case-fold collision"):
        validate_portable_doc_ids(("AI/Café.md", "AI/Cafe\u0301.md"))
    with pytest.raises(CorpusBuildError, match="NFC/case-fold collision"):
        validate_portable_doc_ids(("AI/straße.md", "AI/strasse.md"))


def test_unicode_paths_and_raw_bytes_are_preserved(tmp_path: Path) -> None:
    content = tmp_path / "content"
    doc_id = "Events/2024-07-24-\u200bMLOps 한글.md"
    raw = "---\ntitle: 한글\npublished: 2024-07-24\n---\n본문 🌱\n"
    _write_raw(content, doc_id, raw)
    policy = _write_policy(tmp_path / "policy.toml")
    index = tmp_path / "index"

    build_index(content_root=content, policy_path=policy, output_root=index)

    assert (index / "posts" / doc_id).read_bytes() == raw.encode()
    assert doc_id in _artifact_doc_ids(index)[0]


def test_failed_build_keeps_previous_index_intact(tmp_path: Path) -> None:
    content = tmp_path / "content"
    _write_post(content, "AI/post.md", "draft: false")
    policy = _write_policy(tmp_path / "policy.toml")
    index = tmp_path / "index"
    build_index(content_root=content, policy_path=policy, output_root=index)
    before = _tree_digest(index)
    _write_post(content, "AI/bad.md", 'draft: "false"')

    with pytest.raises(CorpusBuildError):
        build_index(content_root=content, policy_path=policy, output_root=index)

    assert _tree_digest(index) == before
    assert not (index / "posts" / "AI" / "bad.md").exists()


def test_build_is_byte_deterministic_and_runtime_loadable(tmp_path: Path) -> None:
    content = tmp_path / "content"
    _write_post(content, "AI/a.md", "title: A\ntags: [rag, 한국어]", "[[B]]")
    _write_post(content, "AI/b.md", "title: B\npublished: 2024-01-02")
    policy = _write_policy(tmp_path / "policy.toml")
    first = tmp_path / "first"
    second = tmp_path / "second"

    one = build_index(content_root=content, policy_path=policy, output_root=first)
    two = build_index(content_root=content, policy_path=policy, output_root=second)

    assert one.fingerprint == two.fingerprint
    assert _tree_digest(first) == _tree_digest(second)
    assert PublishedCorpus(first).fingerprint == one.fingerprint


def test_wikilinks_emit_resolved_deterministic_bidirectional_graph(
    tmp_path: Path,
) -> None:
    content = tmp_path / "content"
    _write_post(
        content,
        "AI/a.md",
        "title: A",
        "[[B|Bee]]\n[[Projects/C#section]]\n[[missing]]\n"
        "```md\n[[B|ignored in code]]\n```\n",
    )
    _write_post(content, "AI/b.md", "title: B")
    _write_post(content, "Projects/C.md", "title: C")
    policy = _write_policy(tmp_path / "policy.toml")
    index = tmp_path / "index"

    build_index(content_root=content, policy_path=policy, output_root=index)

    graph = _read_json(index / "wikilinks.json")
    assert graph["node_count"] == 3
    assert graph["edge_count"] == 2
    assert graph["nodes_with_edges"] == 3
    assert graph["isolated_node_count"] == 0
    assert graph["adjacency"] == {
        "AI/a.md": ["AI/b.md", "Projects/C.md"],
        "AI/b.md": ["AI/a.md"],
        "Projects/C.md": ["AI/a.md"],
    }
    assert graph["links"] == [
        {
            "alias": "Bee",
            "source_doc_id": "AI/a.md",
            "target": "B",
            "target_doc_id": "AI/b.md",
        },
        {
            "alias": None,
            "source_doc_id": "AI/a.md",
            "target": "Projects/C",
            "target_doc_id": "Projects/C.md",
        },
    ]
    assert graph["unresolved"] == [
        {
            "alias": None,
            "source_doc_id": "AI/a.md",
            "target": "missing",
        }
    ]


def test_cli_builds_to_an_explicit_output_and_reports_json(tmp_path: Path) -> None:
    content = tmp_path / "content"
    _write_post(content, "AI/public.md", "draft: false")
    policy = _write_policy(tmp_path / "policy.toml")
    index = tmp_path / "index"

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_index.py"),
            "--content-root",
            str(content),
            "--policy",
            str(policy),
            "--output",
            str(index),
            "--expect-document-count",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    report = json.loads(completed.stdout)
    assert report["document_count"] == 1
    assert report["source_markdown_count"] == 1
    assert Path(report["output"]) == index
    assert (index / "posts" / "AI" / "public.md").is_file()

    mismatch = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_index.py"),
            "--content-root",
            str(content),
            "--policy",
            str(policy),
            "--output",
            str(index),
            "--expect-document-count",
            "2",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert mismatch.returncode == 1
    assert "expected 2 published documents, built 1" in mismatch.stderr


def test_real_corpus_build_is_exactly_the_nuartz_published_335(
    tmp_path: Path,
) -> None:
    index = tmp_path / "index"

    report = build_index(
        content_root=REAL_CONTENT,
        policy_path=REAL_POLICY,
        output_root=index,
    )

    sets = _artifact_doc_ids(index)
    assert report.document_count == 335
    assert all(len(doc_ids) == 335 for doc_ids in sets)
    assert sets[0] == sets[1] == sets[2] == sets[3]
    assert "AI/pdf-parser/_index.md" not in sets[0]
    assert "Events/2024-07-24-\u200bMLOps Now - LLM in Production.md" in sets[0]

    manifest = _read_json(index / "manifest.json")
    assert manifest["source_markdown_count"] == 336
    assert manifest["excluded_documents"] == [
        {
            "doc_id": "AI/pdf-parser/_index.md",
            "reason": "basename-leading-underscore",
        }
    ]
    graph = _read_json(index / "wikilinks.json")
    assert graph["edge_count"] == 226
    assert graph["nodes_with_edges"] == 122
    assert graph["isolated_node_count"] == 213
    alias_occurrences = [
        occurrence
        for field in ("links", "unresolved", "excluded_links")
        for occurrence in graph[field]
        if occurrence["alias"] is not None
    ]
    assert len(alias_occurrences) == 164
