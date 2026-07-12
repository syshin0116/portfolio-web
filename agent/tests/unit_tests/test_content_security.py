"""Security and cache-integrity tests for blog content access."""

from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace

import pytest

from agent import tools
from agent.graph import _build_backend
from agent.lib import bm25_search as bm25_module
from agent.lib.config import SearchConfig
from agent.lib.content_loader import load_one
from agent.lib.read_only_backend import ReadOnlyFilesystemBackend
from agent.lib.ripgrep_search import ripgrep_search
from agent.lib.types import ContentDoc, PostMeta


def _post(path: str, title: str, body: str, published: date) -> ContentDoc:
    return ContentDoc(
        meta=PostMeta(
            path=path,
            title=title,
            date=published,
            category=path.split("/", 1)[0],
        ),
        body=body,
    )


def test_ripgrep_treats_dash_prefixed_query_as_pattern(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout="", returncode=1)

    monkeypatch.setattr("agent.lib.ripgrep_search.subprocess.run", fake_run)
    monkeypatch.setattr("agent.lib.ripgrep_search.get_cached_docs", lambda config: [])
    config = SearchConfig(content_dir=tmp_path)

    assert ripgrep_search("--pre=/tmp/attacker", config=config) == []

    command = captured["command"]
    assert command[1] == "--no-config"
    assert command[-4:] == ["-e", "--pre=/tmp/attacker", "--", str(tmp_path)]
    assert captured["kwargs"] == {
        "capture_output": True,
        "text": True,
        "timeout": 10,
    }


def test_load_one_accepts_only_contained_markdown(tmp_path):
    content_dir = tmp_path / "content"
    post = content_dir / "AI" / "post.md"
    post.parent.mkdir(parents=True)
    post.write_text("---\ntitle: Safe post\n---\nBody", encoding="utf-8")
    outside = tmp_path / "secret.md"
    outside.write_text("secret", encoding="utf-8")
    (content_dir / "AI" / "outside.md").symlink_to(outside)
    (content_dir / "AI" / "note.txt").write_text("not markdown", encoding="utf-8")
    config = SearchConfig(content_dir=content_dir)

    loaded = load_one("AI/post.md", config)
    assert loaded is not None
    assert loaded.meta.title == "Safe post"
    assert load_one("../secret.md", config) is None
    assert load_one(str(post), config) is None
    assert load_one(str(outside), config) is None
    assert load_one("AI/outside.md", config) is None
    assert load_one("AI/note.txt", config) is None


@pytest.mark.asyncio
async def test_blog_backend_rejects_all_mutation_apis(tmp_path):
    post = tmp_path / "post.md"
    post.write_text("original", encoding="utf-8")
    backend = ReadOnlyFilesystemBackend(root_dir=tmp_path, virtual_mode=True)

    read_result = backend.read("/post.md")
    content = (
        read_result
        if isinstance(read_result, str)
        else read_result.file_data["content"]
    )

    assert "original" in content
    assert backend.write("/new.md", "new").error == "Blog content is read-only"
    assert backend.edit("/post.md", "original", "changed").error == (
        "Blog content is read-only"
    )
    assert (await backend.awrite("/async.md", "new")).error == (
        "Blog content is read-only"
    )
    assert (await backend.aedit("/post.md", "original", "changed")).error == (
        "Blog content is read-only"
    )
    assert backend.upload_files([("/upload.md", b"new")])[0].error == (
        "permission_denied"
    )
    assert (await backend.aupload_files([("/async-upload.md", b"new")]))[
        0
    ].error == "permission_denied"
    assert post.read_text(encoding="utf-8") == "original"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["post.md"]


def test_blog_composite_route_uses_read_only_backend():
    backend = _build_backend()(SimpleNamespace(state={}))
    blog_backend = backend.routes["/blog/"]

    assert isinstance(blog_backend, ReadOnlyFilesystemBackend)
    assert backend.write("/blog/new.md", "new").error == "Blog content is read-only"
    assert backend.edit("/blog/post.md", "old", "new").error == (
        "Blog content is read-only"
    )


def test_listing_does_not_reorder_bm25_document_mapping(monkeypatch):
    older_alpha = _post("AI/alpha.md", "Alpha", "alpha topic", date(2024, 1, 1))
    newer_beta = _post("AI/beta.md", "Beta", "beta topic", date(2025, 1, 1))
    oldest_gamma = _post("AI/gamma.md", "Gamma", "gamma topic", date(2023, 1, 1))
    cached_docs = [older_alpha, newer_beta, oldest_gamma]

    monkeypatch.setattr(tools, "get_cached_docs", lambda: cached_docs)
    monkeypatch.setattr(bm25_module, "get_cached_docs", lambda config: cached_docs)
    monkeypatch.setattr(
        bm25_module,
        "_tokenize",
        lambda text: re.findall(r"[a-z]+", text.lower()),
    )
    monkeypatch.setattr(bm25_module, "_bm25", None)
    monkeypatch.setattr(bm25_module, "_bm25_docs", [])

    first = bm25_module.bm25_search("alpha", config=SearchConfig())
    assert first[0].path == "AI/alpha.md"

    listing = tools.list_posts.invoke({})
    assert listing.index("AI/beta.md") < listing.index("AI/alpha.md")
    assert cached_docs == [older_alpha, newer_beta, oldest_gamma]

    second = bm25_module.bm25_search("alpha", config=SearchConfig())
    assert second[0].path == "AI/alpha.md"
