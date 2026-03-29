"""Blog RAG tools.

Tools for searching and retrieving blog content. Each tool is decorated with
@tool so it can be bound to the chat model via deepagents.
"""

from langchain_core.tools import tool


@tool
def semantic_search(query: str, top_k: int = 10) -> str:
    """Search blog posts by semantic similarity using vector embeddings.

    Args:
        query: The search query in natural language.
        top_k: Number of results to return.
    """
    # TODO: Implement with ChromaDB vector store
    return f"[semantic_search] No results for '{query}' (not yet implemented)"


@tool
def keyword_search(query: str, top_k: int = 10) -> str:
    """Search blog posts by keyword matching using BM25 ranking. Korean-aware.

    Args:
        query: The keyword search query.
        top_k: Number of results to return.
    """
    # TODO: Implement with rank-bm25 + kiwipiepy tokenizer
    return f"[keyword_search] No results for '{query}' (not yet implemented)"


@tool
def metadata_filter(
    tags: list[str] | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Filter blog posts by metadata (tags, category, date range).

    Args:
        tags: List of tags to filter by.
        category: Category name (e.g. "AI", "Dev", "Projects").
        date_from: Start date in YYYY-MM-DD format.
        date_to: End date in YYYY-MM-DD format.
    """
    # TODO: Implement metadata filtering
    return "[metadata_filter] Not yet implemented"


@tool
def graph_traverse(slug: str, depth: int = 1) -> str:
    """Traverse wikilink connections from a given blog post.

    Args:
        slug: The blog post slug/path to start traversal from.
        depth: How many levels of links to follow.
    """
    # TODO: Implement wikilink graph traversal
    return f"[graph_traverse] No results for '{slug}' (not yet implemented)"


@tool
def read_file(path: str) -> str:
    """Read the full content of a specific blog post by its file path.

    Args:
        path: Relative path to the blog post (e.g. "AI/my-post.md").
    """
    # TODO: Implement file reading from content directory
    return f"[read_file] Cannot read '{path}' (not yet implemented)"


TOOLS = [semantic_search, keyword_search, metadata_filter, graph_traverse, read_file]
