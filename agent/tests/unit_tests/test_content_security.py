"""Security contracts for the published-only serving path."""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import date
from pathlib import Path
from threading import Barrier, BrokenBarrierError, Lock
from types import SimpleNamespace

import pytest
from deepagents.backends import FilesystemBackend
from langgraph.prebuilt import ToolRuntime

from agent import tools
from agent.graph import _build_backend
from agent.inspection import INSPECTION_EVENT_NAME, InspectionContractError
from agent.retrieval import serving
from agent.retrieval.corpus import CorpusManifestError, content_checksum
from agent.retrieval.corpus_build import build_index
from agent.retrieval.protocol import DocId
from agent.retrieval.serving import (
    ServingArtifactError,
    ServingRuntime,
    get_serving_runtime,
    reset_serving_runtime_cache,
)

_NONCANONICAL_TOOL_DATES = (
    "20250102",
    "2025-W01-1",
    "2025-01-02T00:00:00",
    " 2025-01-02",
    "2025-01-02 ",
    "２０２５-０１-０２",
)


def _post(root: Path, doc_id: str, frontmatter: str, body: str) -> Path:
    path = root / doc_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\n{frontmatter.rstrip()}\n---\n{body}\n",
        encoding="utf-8",
    )
    return path


def _rewrite_json_artifact(
    index: Path,
    artifact_name: str,
    payload: dict[str, object],
) -> None:
    artifact = index / artifact_name
    artifact.write_text(
        json.dumps(
            payload,
            allow_nan=True,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = index / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptor = next(
        item for item in manifest["artifacts"] if item["path"] == artifact_name
    )
    raw = artifact.read_bytes()
    descriptor["bytes"] = len(raw)
    descriptor["sha256"] = content_checksum(raw)
    manifest_path.write_text(
        json.dumps(
            manifest,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def serving_tree(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("serving")
    content = root / "content"
    policy = root / "corpus-policy.toml"
    policy.write_text(
        "schema_version = 1\nno_frontmatter_allowlist = []\n",
        encoding="utf-8",
    )
    _post(
        content,
        "AI/docker.md",
        "title: Docker Guide\n"
        "date: 2025-01-02\n"
        "tags: [Docker, AI]\n"
        "description: A published Docker guide.",
        "도커 Docker public-marker.\n\n[[Graph Guide]]",
    )
    _post(
        content,
        "AI/graph.md",
        'title: Graph Guide\ndate: "2024-12-01"\ntags: [LangGraph]',
        "LangGraph public graph notes.\n\n[[Docker Guide]]",
    )
    _post(
        content,
        "Dev/other.md",
        "title: Other\npublished: true",
        "Another published document.",
    )
    _post(
        content,
        "AI/draft.md",
        "title: Draft\ndraft: true",
        "draft-only-marker",
    )
    _post(
        content,
        "AI/private.md",
        "title: Private\nprivate: true",
        "private-only-marker",
    )
    _post(
        content,
        "AI/_hidden.md",
        "title: Hidden",
        "hidden-only-marker",
    )
    index = root / "index"
    build_index(content_root=content, policy_path=policy, output_root=index)
    return content, index


@pytest.fixture()
def configured_runtime(
    serving_tree: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> ServingRuntime:
    _, index = serving_tree
    monkeypatch.setenv("BLOG_INDEX_PATH", str(index))
    monkeypatch.setenv("RAG_RETRIEVER_METHOD", "bm25")
    reset_serving_runtime_cache()
    runtime = get_serving_runtime()
    yield runtime
    reset_serving_runtime_cache()


def test_generic_filesystem_has_no_blog_content_route() -> None:
    backend = _build_backend()

    assert set(backend.routes) == {"/memories/", "/skills/"}
    assert isinstance(backend.routes["/skills/"], FilesystemBackend)
    assert "/blog/" not in backend.routes


def test_serving_runtime_cold_start_is_single_flight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    constructor_barrier = Barrier(2)
    constructor_lock = Lock()
    constructor_calls = 0

    class FakeRuntime:
        def __init__(self, index_root: Path, *, method_id: str) -> None:
            del index_root, method_id
            nonlocal constructor_calls
            with constructor_lock:
                constructor_calls += 1
            with suppress(BrokenBarrierError):
                constructor_barrier.wait(timeout=0.1)

    monkeypatch.setattr(serving, "ServingRuntime", FakeRuntime)
    monkeypatch.setenv("BLOG_INDEX_PATH", str(tmp_path))
    monkeypatch.setenv("RAG_RETRIEVER_METHOD", "bm25")
    reset_serving_runtime_cache()
    with ThreadPoolExecutor(max_workers=2) as executor:
        runtimes = tuple(executor.map(lambda _: get_serving_runtime(), range(2)))

    assert runtimes[0] is runtimes[1]
    assert constructor_calls == 1
    assert serving._cached_runtime.cache_info().misses == 1
    reset_serving_runtime_cache()


def test_every_curated_tool_excludes_non_published_sources(
    configured_runtime: ServingRuntime,
) -> None:
    excluded_markers = {
        "draft-only-marker": "AI/draft.md",
        "private-only-marker": "AI/private.md",
        "hidden-only-marker": "AI/_hidden.md",
    }
    for marker, excluded_path in excluded_markers.items():
        assert "No results found" in tools.keyword_search.invoke({"query": marker})
        semantic = tools.semantic_search.invoke({"query": marker})
        assert excluded_path not in semantic
        graph = tools.graph_traverse.invoke({"slug": excluded_path, "depth": 3})
        assert "No results found" in graph

    listing = tools.list_posts.invoke({"limit": 50})
    metadata = tools.metadata_filter.invoke({})
    assert "AI/docker.md" in listing
    assert "AI/graph.md" in metadata
    for excluded in excluded_markers.values():
        assert excluded not in listing
        assert excluded not in metadata
        assert "Published file not found" in tools.read_post.invoke({"path": excluded})


@pytest.mark.parametrize(
    ("tool_name", "query", "method_id"),
    [
        ("keyword_search", "Docker", "exact-substring"),
        ("semantic_search", "도커", "bm25"),
    ],
)
def test_ranked_tool_emits_measured_native_inspection_from_trusted_runtime(
    configured_runtime: ServingRuntime,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    query: str,
    method_id: str,
) -> None:
    del configured_runtime
    emitted: list[object] = []
    runtime = ToolRuntime(
        state={},
        context=None,
        config={},
        stream_writer=emitted.append,
        tool_call_id=f"call-{tool_name}",
        store=None,
    )
    ticks = iter((1_000_000_000, 1_012_500_000))
    monkeypatch.setattr(tools.time, "perf_counter_ns", lambda: next(ticks))

    output = getattr(tools, tool_name).func(
        query=query,
        top_k=1,
        runtime=runtime,
    )

    assert "Found 1 result(s)" in output
    assert len(emitted) == 1
    envelope = emitted[0]
    assert isinstance(envelope, dict)
    assert envelope["name"] == INSPECTION_EVENT_NAME
    payload = envelope["payload"]
    assert payload["tool_call_id"] == f"call-{tool_name}"
    assert payload["delivery"] == "live-run-only"
    assert payload["query"] == query
    assert payload["method_id"] == method_id
    assert payload["method_identity"]["method_id"] == method_id
    assert payload["method_identity"]["implementation_id"].endswith(
        ("create@1", "create@2")
    )
    assert payload["method_identity"]["fingerprint"].startswith("sha256:")
    assert payload["corpus_revision"].startswith("sha256:")
    assert payload["corpus_document_count"] == 3
    assert payload["hit_count"] == 1
    assert payload["sources"][0]["rank"] == 1
    assert payload["sources"][0]["provenance"] == {
        "kind": "published-corpus",
        "corpus_revision": payload["corpus_revision"],
        "retriever_fingerprint": payload["method_identity"]["fingerprint"],
    }
    assert payload["stages"][0]["elapsed_ms"] == 12.5
    assert payload["stages"][0]["application"] == {
        "status": "applied",
        "input_count": 1,
        "output_count": 1,
    }


@pytest.mark.parametrize("tool_name", ["keyword_search", "semantic_search"])
@pytest.mark.parametrize(
    "query",
    ["unsafe\x00query", "unsafe\ud800query"],
    ids=["null-byte", "unpaired-surrogate"],
)
def test_ranked_tool_rejects_unsafe_query_before_retrieval(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    query: str,
) -> None:
    retrieval_calls = 0

    class _NeverRetrieve:
        def exact(self, _query: str, *, limit: int):
            del limit
            nonlocal retrieval_calls
            retrieval_calls += 1
            raise AssertionError("unsafe query reached retrieval")

        def retrieve(self, _query: str, *, limit: int):
            del limit
            nonlocal retrieval_calls
            retrieval_calls += 1
            raise AssertionError("unsafe query reached retrieval")

    monkeypatch.setattr(tools, "get_serving_runtime", _NeverRetrieve)

    with pytest.raises(InspectionContractError, match="null|Unicode scalar"):
        getattr(tools, tool_name).func(query=query, top_k=1, runtime=None)

    assert retrieval_calls == 0


def test_raw_source_changes_after_build_cannot_change_serving(
    configured_runtime: ServingRuntime,
    serving_tree: tuple[Path, Path],
) -> None:
    content, _ = serving_tree
    source = content / "AI/docker.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\npost-build-source-only\n",
        encoding="utf-8",
    )
    reset_serving_runtime_cache()

    assert "No results found" in tools.keyword_search.invoke(
        {"query": "post-build-source-only"}
    )
    assert "post-build-source-only" not in tools.read_post.invoke(
        {"path": "AI/docker.md"}
    )


def test_fitted_artifact_loss_fails_closed_without_legacy_fallback(
    serving_tree: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    _, index = serving_tree
    broken = tmp_path / "index"
    shutil.copytree(index, broken)
    (broken / "bm25" / "fitted.sqlite3").unlink()

    with pytest.raises(ValueError, match="missing|artifact"):
        ServingRuntime(broken, method_id="bm25")


def test_serving_runtime_retains_one_verified_bm25_snapshot(
    serving_tree: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    _, source_index = serving_tree
    index = tmp_path / "snapshot-index"
    shutil.copytree(source_index, index)
    runtime = ServingRuntime(index, method_id="bm25")
    before = runtime.retrieve("Docker")

    (index / "bm25" / "fitted.sqlite3").write_bytes(b"replaced after construction")

    assert runtime.retrieve("Docker") == before
    with pytest.raises(
        CorpusManifestError, match="fitted.sqlite3.*checksum|byte count"
    ):
        ServingRuntime(index, method_id="bm25")
    runtime.close()
    with pytest.raises(RuntimeError, match="closed"):
        runtime.retrieve("Docker")


def test_registry_method_selection_is_explicit_and_unknown_methods_fail(
    serving_tree: tuple[Path, Path],
) -> None:
    _, index = serving_tree

    exact = ServingRuntime(index, method_id="exact-substring")
    assert exact.retriever.method_id == "exact-substring"
    assert exact.retrieve("Docker").hits[0].score > 1.0

    with pytest.raises(KeyError, match="not registered"):
        ServingRuntime(index, method_id="does-not-exist")


def test_graph_and_metadata_use_the_same_published_snapshot(
    configured_runtime: ServingRuntime,
) -> None:
    graph = tools.graph_traverse.invoke({"slug": "Docker Guide", "depth": 1})
    filtered = tools.metadata_filter.invoke(
        {
            "tags": ["Docker"],
            "category": "ai",
            "date_from": "2025-01-01",
            "date_to": "2025-12-31",
        }
    )

    assert "AI/graph.md" in graph
    assert "AI/docker.md" in filtered
    assert "AI/graph.md" not in filtered


@pytest.mark.parametrize("value", _NONCANONICAL_TOOL_DATES)
def test_date_helper_rejects_noncanonical_or_non_ascii_dates(value: str) -> None:
    with pytest.raises(ValueError, match="date_from must be YYYY-MM-DD"):
        tools._date(value, field="date_from")


@pytest.mark.parametrize("value", _NONCANONICAL_TOOL_DATES)
def test_metadata_filter_rejects_noncanonical_or_non_ascii_dates(
    configured_runtime: ServingRuntime,
    value: str,
) -> None:
    with pytest.raises(ValueError, match="date_from must be YYYY-MM-DD"):
        tools.metadata_filter.invoke({"date_from": value})


def test_date_helper_and_metadata_filter_enforce_calendar_and_leap_day_rules(
    configured_runtime: ServingRuntime,
) -> None:
    assert tools._date(None, field="date_from") is None
    assert tools._date("2025-01-02", field="date_from") == date(2025, 1, 2)
    assert tools._date("2024-02-29", field="date_from") == date(2024, 2, 29)
    with pytest.raises(ValueError, match="date_from must be YYYY-MM-DD"):
        tools._date("2025-02-29", field="date_from")
    with pytest.raises(ValueError, match="date_from must be YYYY-MM-DD"):
        tools.metadata_filter.invoke({"date_from": "2025-02-29"})

    exact_day = tools.metadata_filter.invoke(
        {"date_from": "2025-01-02", "date_to": "2025-01-02"}
    )
    leap_day = tools.metadata_filter.invoke(
        {"date_from": "2024-02-29", "date_to": "2024-02-29"}
    )

    assert "AI/docker.md" in exact_day
    assert "AI/graph.md" not in exact_day
    assert "No results found" in leap_day


def test_catalog_preserves_yaml_dates_for_recent_post_order(
    configured_runtime: ServingRuntime,
) -> None:
    listing = tools.list_posts.invoke({"category": "AI", "limit": 10})

    assert "(2025-01-02)" in listing
    assert listing.index("AI/docker.md") < listing.index("AI/graph.md")


def test_read_post_rejects_noncanonical_and_out_of_corpus_paths(
    configured_runtime: ServingRuntime,
) -> None:
    for path in ("../secret.md", "/etc/passwd", "AI/docker.md/../draft.md"):
        assert "Published file not found" in tools.read_post.invoke({"path": path})


def test_read_post_caps_an_oversized_not_found_response(
    configured_runtime: ServingRuntime,
) -> None:
    del configured_runtime

    output = tools.read_post.invoke({"path": "x" * 20_000})

    assert tools.READ_POST_MAX_OUTPUT_BYTES == 16_384
    assert output.startswith("[read_post] Published file not found:")
    assert output.endswith(tools.READ_POST_TRUNCATION_MARKER)
    assert len(output.encode("utf-8")) == 16_384


def test_read_post_cap_uses_the_literal_16_kib_boundary() -> None:
    exact = "x" * 16_384
    oversized = "x" * 16_385

    assert tools._cap_read_post_output(exact) == exact
    truncated = tools._cap_read_post_output(oversized)
    assert truncated.endswith(tools.READ_POST_TRUNCATION_MARKER)
    assert len(truncated.encode("utf-8")) == 16_384


def test_read_post_caps_total_utf8_output_with_an_explicit_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = SimpleNamespace(
        doc_id="AI/large.md",
        title="큰 문서",
        published_label="2026-07-28",
        category="AI",
        tags=("한국어", "RAG"),
    )

    class LargeRuntime:
        def entry(self, path: str):
            assert path == entry.doc_id
            return entry

        def body(self, doc_id: str):
            assert doc_id == entry.doc_id
            return "가나다라마바사" * 2_000

    monkeypatch.setattr(tools, "get_serving_runtime", LargeRuntime)

    first = tools.read_post.invoke({"path": entry.doc_id})
    second = tools.read_post.invoke({"path": entry.doc_id})

    assert first == second
    assert first.endswith(tools.READ_POST_TRUNCATION_MARKER)
    assert first.count(tools.READ_POST_TRUNCATION_MARKER) == 1
    assert len(first.encode("utf-8")) <= tools.READ_POST_MAX_OUTPUT_BYTES
    assert "\ufffd" not in first


def test_read_post_preserves_short_output_without_a_truncation_marker(
    configured_runtime: ServingRuntime,
) -> None:
    output = tools.read_post.invoke({"path": "AI/docker.md"})

    assert "도커 Docker public-marker." in output
    assert tools.READ_POST_TRUNCATION_MARKER not in output
    assert len(output.encode("utf-8")) < tools.READ_POST_MAX_OUTPUT_BYTES


@pytest.mark.parametrize(
    "case",
    [
        "catalog-count-bool",
        "catalog-count-float",
        "catalog-count-nan",
        "catalog-count-infinity",
        "catalog-date-trailing-junk",
        "catalog-derived-title-mismatch",
        "graph-count-bool",
        "graph-count-float",
        "graph-link-shape",
        "graph-link-resolution-mismatch",
        "graph-unresolved-outside-corpus",
        "graph-unresolved-but-resolvable",
        "graph-excluded-variant-mismatch",
        "graph-ambiguous-name-shape",
        "graph-adjacency-outside-corpus",
    ],
)
def test_serving_schemas_reject_coherently_rechecksummed_mutations(
    serving_tree: tuple[Path, Path],
    tmp_path: Path,
    case: str,
) -> None:
    _, source_index = serving_tree
    index = tmp_path / case
    shutil.copytree(source_index, index)
    artifact_name = "catalog.json" if case.startswith("catalog-") else "wikilinks.json"
    payload = json.loads((index / artifact_name).read_text(encoding="utf-8"))

    if case == "catalog-count-bool":
        payload["document_count"] = True
    elif case == "catalog-count-float":
        payload["document_count"] = float(payload["document_count"])
    elif case == "catalog-count-nan":
        payload["document_count"] = float("nan")
    elif case == "catalog-count-infinity":
        payload["document_count"] = float("inf")
    elif case == "catalog-date-trailing-junk":
        payload["documents"][0]["date"] = "2025-01-02junk"
    elif case == "catalog-derived-title-mismatch":
        payload["documents"][0]["title"] = "forged but well-typed"
    elif case == "graph-count-bool":
        payload["edge_count"] = True
    elif case == "graph-count-float":
        payload["edge_count"] = float(payload["edge_count"])
    elif case == "graph-link-shape":
        payload["links"][0].pop("target_doc_id")
    elif case == "graph-link-resolution-mismatch":
        payload["links"][0]["target"] = "Docker Guide"
    elif case == "graph-unresolved-outside-corpus":
        payload["unresolved"].append(
            {
                "alias": None,
                "source_doc_id": "AI/draft.md",
                "target": "missing",
            }
        )
    elif case == "graph-unresolved-but-resolvable":
        payload["unresolved"].append(
            {
                "alias": None,
                "source_doc_id": "AI/docker.md",
                "target": "Graph Guide",
            }
        )
    elif case == "graph-excluded-variant-mismatch":
        payload["excluded_links"].append(
            {
                "alias": None,
                "candidates": ["AI/docker.md", "AI/graph.md"],
                "reason": "ambiguous-target",
                "source_doc_id": "AI/docker.md",
                "target": "not-an-ambiguous-name",
            }
        )
    elif case == "graph-ambiguous-name-shape":
        payload["ambiguous_names"].append(
            {"candidates": ["AI/docker.md"], "name": "one-candidate"}
        )
    elif case == "graph-adjacency-outside-corpus":
        payload["adjacency"]["AI/docker.md"].append("AI/draft.md")
        payload["adjacency"]["AI/docker.md"].sort()
    else:
        raise AssertionError(f"unhandled mutation case: {case}")

    _rewrite_json_artifact(index, artifact_name, payload)

    with pytest.raises(ServingArtifactError):
        ServingRuntime(index)


def test_graph_traversal_has_a_deterministic_fifty_result_cap() -> None:
    runtime = ServingRuntime.__new__(ServingRuntime)
    start = DocId("AI/root.md")
    neighbors = tuple(DocId(f"AI/node-{index:03d}.md") for index in range(75))
    runtime._lookup = {"root": (start,)}
    runtime.adjacency = {
        start: tuple(reversed(neighbors)),
        **dict.fromkeys(neighbors, (start,)),
    }

    results = runtime.traverse("root", depth=1)

    assert len(results) == 50
    assert results == tuple((doc_id, 1) for doc_id in neighbors[:50])
