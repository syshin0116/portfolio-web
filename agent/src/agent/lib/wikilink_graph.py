"""Wikilink graph traversal — find related posts via [[link]] connections."""

from __future__ import annotations

import logging
from collections import deque

from agent.lib.config import SearchConfig, get_config
from agent.lib.content_loader import get_cached_docs
from agent.lib.types import SearchResult

logger = logging.getLogger(__name__)

# Module-level graph cache
_graph: dict[str, set[str]] = {}
_title_to_path: dict[str, str] = {}
_graph_doc_count: int = 0


def _build_graph(config: SearchConfig) -> None:
    global _graph, _title_to_path, _graph_doc_count

    docs = get_cached_docs(config)
    graph: dict[str, set[str]] = {}
    title_to_path: dict[str, str] = {}

    # Build title -> path lookup (normalized)
    for doc in docs:
        path = doc.meta.path
        graph.setdefault(path, set())

        # Multiple lookup keys for fuzzy resolution
        title_to_path[doc.meta.title.lower()] = path
        # Also use filename without extension and date prefix
        stem = path.rsplit("/", 1)[-1].replace(".md", "")
        title_to_path[stem.lower()] = path
        # Strip common date prefix patterns: 2024-01-01-title -> title
        stripped = stem
        if len(stem) > 11 and stem[4] == "-" and stem[7] == "-" and stem[10] == "-":
            stripped = stem[11:]
        title_to_path[stripped.lower()] = path

    # Build edges from wikilinks
    for doc in docs:
        src = doc.meta.path
        for link in doc.wikilinks:
            target_path = title_to_path.get(link.lower())
            if target_path and target_path != src:
                graph.setdefault(src, set()).add(target_path)
                graph.setdefault(target_path, set()).add(src)  # bidirectional

    _graph = graph
    _title_to_path = title_to_path
    _graph_doc_count = len(docs)
    logger.info(
        "Wikilink graph built: %d nodes, %d edges",
        len(graph),
        sum(len(v) for v in graph.values()) // 2,
    )


def _resolve_slug(slug: str) -> str | None:
    """Resolve a slug to a content path."""
    # Direct path match
    if slug in _graph:
        return slug
    # Title/stem lookup
    return _title_to_path.get(slug.lower())


def graph_traverse(
    slug: str,
    *,
    depth: int = 1,
    config: SearchConfig | None = None,
) -> list[SearchResult]:
    """BFS traversal from a starting post, returning connected posts."""
    cfg = config or get_config()

    docs = get_cached_docs(cfg)
    if _graph_doc_count != len(docs):
        _build_graph(cfg)

    start = _resolve_slug(slug)
    if not start:
        return []

    # BFS
    visited: dict[str, int] = {start: 0}
    queue: deque[tuple[str, int]] = deque([(start, 0)])

    while queue:
        node, dist = queue.popleft()
        if dist >= depth:
            continue
        for neighbor in _graph.get(node, set()):
            if neighbor not in visited:
                visited[neighbor] = dist + 1
                queue.append((neighbor, dist + 1))

    # Build results (exclude starting node)
    doc_map = {d.meta.path: d for d in docs}
    results: list[SearchResult] = []

    for path, dist in visited.items():
        if path == start:
            continue
        doc = doc_map.get(path)
        if not doc:
            continue

        score = 1.0 / (1.0 + dist)  # closer = higher score
        results.append(
            SearchResult(
                path=path,
                title=doc.meta.title,
                score=round(score, 3),
                snippet=doc.meta.description or f"Connected at depth {dist}",
                source="wikilink",
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results[: cfg.max_results]
