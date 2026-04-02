"""Metadata filtering — tag, category, date range filtering over frontmatter."""

from __future__ import annotations

from datetime import date, datetime

from agent.lib.config import SearchConfig, get_config
from agent.lib.content_loader import get_cached_docs
from agent.lib.types import SearchResult


def metadata_filter(
    *,
    tags: list[str] | None = None,
    category: str | None = None,
    date_from: str | date | None = None,
    date_to: str | date | None = None,
    config: SearchConfig | None = None,
) -> list[SearchResult]:
    """Filter blog posts by metadata."""
    cfg = config or get_config()
    docs = get_cached_docs(cfg)

    # Parse date strings
    d_from = _parse_date(date_from) if date_from else None
    d_to = _parse_date(date_to) if date_to else None

    # Normalize tags for case-insensitive matching
    tag_set = {t.lower() for t in tags} if tags else None

    results: list[SearchResult] = []
    for doc in docs:
        m = doc.meta

        if tag_set:
            doc_tags = {t.lower() for t in m.tags}
            if not tag_set & doc_tags:
                continue

        if category and m.category.lower() != category.lower():
            continue

        if d_from and m.date and m.date < d_from:
            continue

        if d_to and m.date and m.date > d_to:
            continue

        results.append(SearchResult(
            path=m.path,
            title=m.title,
            score=1.0,
            snippet=m.description or f"Tags: {', '.join(m.tags)}" if m.tags else "",
            source="metadata",
        ))

    # Sort by date descending
    results.sort(key=lambda r: _get_date(r.path, docs), reverse=True)
    return results[:cfg.max_results]


def _get_date(path: str, docs: list) -> date:
    for d in docs:
        if d.meta.path == path:
            return d.meta.date or date.min
    return date.min


def _parse_date(val: str | date | None) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
