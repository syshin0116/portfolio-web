"""Shared data types for blog search modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class PostMeta:
    """Parsed frontmatter metadata for a blog post."""

    path: str  # relative to content dir, e.g. "AI/2024-my-post.md"
    title: str
    date: date | None = None
    tags: list[str] = field(default_factory=list)
    category: str = ""  # top-level folder: AI, Dev, Study, ...
    description: str = ""
    draft: bool = False


@dataclass
class ContentDoc:
    """Full blog document with metadata and body."""

    meta: PostMeta
    body: str  # markdown without frontmatter
    wikilinks: list[str] = field(default_factory=list)  # [[Target]] targets


@dataclass
class SearchResult:
    """Uniform search result returned by all search modules."""

    path: str
    title: str
    score: float
    snippet: str
    source: str  # which module produced this: "bm25", "metadata", "wikilink"
