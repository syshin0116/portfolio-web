"""Blog RAG tools — thin wrappers delegating to lib/ search modules."""

from langchain_core.tools import tool

from agent.lib.bm25_search import bm25_search as _bm25
from agent.lib.config import get_config
from agent.lib.content_loader import get_cached_docs, load_one
from agent.lib.frontmatter_index import metadata_filter as _metadata
from agent.lib.result_formatter import format_results
from agent.lib.ripgrep_search import ripgrep_search as _ripgrep
from agent.lib.wikilink_graph import graph_traverse as _graph


@tool
def keyword_search(query: str, top_k: int = 10) -> str:
    """Search blog posts by keyword/regex using ripgrep. Fast exact matching.

    Args:
        query: The keyword or regex pattern to search for.
        top_k: Number of results to return.
    """
    results = _ripgrep(query, max_results=top_k)
    return format_results(results, source="keyword_search", query=query)


@tool
def semantic_search(query: str, top_k: int = 10) -> str:
    """Search blog posts by semantic relevance using BM25 ranking. Korean-aware.

    Args:
        query: The search query in natural language.
        top_k: Number of results to return.
    """
    results = _bm25(query, top_k=top_k)
    return format_results(results, source="semantic_search", query=query)


@tool
def metadata_filter(
    tags: list[str] | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Filter blog posts by metadata (tags, category, date range).

    Args:
        tags: List of tags to filter by (e.g. ["AI", "LangChain"]).
        category: Category folder name (AI, Dev, Study, Projects, Tools, Events, Others).
        date_from: Start date in YYYY-MM-DD format.
        date_to: End date in YYYY-MM-DD format.
    """
    results = _metadata(tags=tags, category=category, date_from=date_from, date_to=date_to)
    return format_results(results, source="metadata_filter")


@tool
def graph_traverse(slug: str, depth: int = 1) -> str:
    """Find related blog posts by following wikilink connections.

    Args:
        slug: The blog post path or title to start from.
        depth: How many levels of links to follow (1-3).
    """
    results = _graph(slug, depth=min(depth, 3))
    return format_results(results, source="graph_traverse", query=slug)


@tool
def list_posts(category: str | None = None, limit: int = 20) -> str:
    """List recent blog posts, optionally filtered by category.

    Args:
        category: Optional category to filter (AI, Dev, Study, Projects, Tools, Events, Others).
        limit: Maximum number of posts to return.
    """
    docs = get_cached_docs()
    if category:
        docs = [d for d in docs if d.meta.category.lower() == category.lower()]

    # Sort by date descending
    docs.sort(key=lambda d: d.meta.date or __import__("datetime").date.min, reverse=True)

    lines = [f"Blog posts ({len(docs)} total):\n"]
    for d in docs[:limit]:
        date_str = str(d.meta.date) if d.meta.date else "no date"
        tags = ", ".join(d.meta.tags[:5]) if d.meta.tags else ""
        lines.append(f"- [{d.meta.path}] \"{d.meta.title}\" ({date_str}) {tags}")

    return "\n".join(lines)


@tool
def read_post(path: str) -> str:
    """Read the full content of a specific blog post.

    Args:
        path: Relative path to the blog post (e.g. "AI/2024-my-post.md").
    """
    doc = load_one(path)
    if not doc:
        return f"[read_post] File not found: '{path}'"

    header = (
        f"# {doc.meta.title}\n"
        f"Date: {doc.meta.date or 'unknown'}\n"
        f"Category: {doc.meta.category}\n"
        f"Tags: {', '.join(doc.meta.tags)}\n"
        f"---\n"
    )
    return header + doc.body


TOOLS = [keyword_search, semantic_search, metadata_filter, graph_traverse, list_posts, read_post]
