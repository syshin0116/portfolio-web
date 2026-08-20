"""Curated blog tools over the verified published-corpus serving facade."""

from __future__ import annotations

import re
import time
from datetime import date

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from agent.inspection import emit_retrieval_inspection, validate_retrieval_query
from agent.retrieval.protocol import DocId, Retrieval
from agent.retrieval.serving import (
    CatalogEntry,
    ServingRuntime,
    get_serving_runtime,
)

_MAX_RESULTS = 50
_CANONICAL_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
READ_POST_MAX_OUTPUT_BYTES = 16 * 1024
SITE_BASE_URL = "https://syshin0116.vercel.app"
READ_POST_TRUNCATION_MARKER = (
    f"\n\n[read_post truncated at the {READ_POST_MAX_OUTPUT_BYTES} "
    "UTF-8 byte output limit]"
)


def _limit(value: int, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if not 1 <= value <= _MAX_RESULTS:
        raise ValueError(f"{field} must be between 1 and {_MAX_RESULTS}")
    return value


def _date(value: str | None, *, field: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str) or _CANONICAL_DATE.fullmatch(value) is None:
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc


def _snippet(runtime: ServingRuntime, entry: CatalogEntry) -> str:
    if entry.description:
        return entry.description
    body = runtime.body(entry.doc_id).strip()
    paragraph = body.split("\n\n", 1)[0].replace("\n", " ").strip()
    return paragraph[:297] + "..." if len(paragraph) > 300 else paragraph


def _cap_read_post_output(output: str) -> str:
    encoded = output.encode("utf-8")
    if len(encoded) <= READ_POST_MAX_OUTPUT_BYTES:
        return output
    marker_bytes = READ_POST_TRUNCATION_MARKER.encode("utf-8")
    prefix = encoded[: READ_POST_MAX_OUTPUT_BYTES - len(marker_bytes)].decode(
        "utf-8", errors="ignore"
    )
    return f"{prefix}{READ_POST_TRUNCATION_MARKER}"


def post_url(doc_id: DocId) -> str:
    """Build the published URL for a document.

    The site serves each post at its content path minus the ``.md`` suffix.
    Only the characters that would break the link are escaped: a space stops a
    URL from parsing, and parentheses end a Markdown link early. Hangul is left
    as it is - the browser encodes it on navigation, and escaping it here
    tripled the size of every tool result and pushed guest runs over their
    token budget.
    """

    slug = str(doc_id)
    slug = slug[: -len(".md")] if slug.endswith(".md") else slug
    for char, escape in ((" ", "%20"), ("(", "%28"), (")", "%29")):
        slug = slug.replace(char, escape)
    return f"{SITE_BASE_URL}/blog/{slug}"


def _format_retrieval(
    runtime: ServingRuntime,
    retrieval: Retrieval,
    *,
    method_id: str,
) -> str:
    if not retrieval.hits:
        return f"[{method_id}] No results found for {retrieval.query!r}."
    lines = [
        f"Found {len(retrieval.hits)} result(s) via {method_id} "
        f"for {retrieval.query!r}:",
        "",
    ]
    for hit in retrieval.hits:
        entry = runtime.entry(hit.doc_id)
        score = "none" if hit.score is None else format(hit.score, ".12g")
        lines.append(
            f'{hit.rank}. [{entry.doc_id}] "{entry.title}" (raw score: {score})'
        )
        lines.append(f"   {post_url(entry.doc_id)}")
        snippet = hit.text or _snippet(runtime, entry)
        if snippet:
            lines.append(f"   {snippet.replace(chr(10), ' ').strip()}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_entries(
    entries: tuple[CatalogEntry, ...],
    *,
    source: str,
) -> str:
    if not entries:
        return f"[{source}] No results found."
    lines = [f"Found {len(entries)} result(s) via {source}:", ""]
    for rank, entry in enumerate(entries, start=1):
        published = entry.published_label or "unknown date"
        tags = ", ".join(entry.tags[:5])
        suffix = f" — {tags}" if tags else ""
        lines.append(f'{rank}. [{entry.doc_id}] "{entry.title}" ({published}){suffix}')
        lines.append(f"   {post_url(entry.doc_id)}")
    return "\n".join(lines)


@tool
def keyword_search(
    query: str,
    top_k: int = 10,
    runtime: ToolRuntime = None,  # type: ignore[assignment]
) -> str:
    """Rank published posts by literal substring occurrence count.

    Args:
        query: A literal keyword or phrase. Regular expressions are not accepted.
        top_k: Number of results to return, from 1 to 50.
    """

    validate_retrieval_query(query)
    serving_runtime = get_serving_runtime()
    started_ns = time.perf_counter_ns()
    result = serving_runtime.exact(query, limit=_limit(top_k, field="top_k"))
    elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    emit_retrieval_inspection(
        tool_runtime=runtime,
        runtime=serving_runtime,
        retriever=serving_runtime.exact_retriever,
        retrieval=result,
        elapsed_ms=elapsed_ms,
    )
    return _format_retrieval(
        serving_runtime,
        result,
        method_id=serving_runtime.exact_retriever.method_id,
    )


@tool
def semantic_search(
    query: str,
    top_k: int = 10,
    runtime: ToolRuntime = None,  # type: ignore[assignment]
) -> str:
    """Rank published posts with the configured registry retriever (BM25 by default).

    Args:
        query: The natural-language retrieval query.
        top_k: Number of results to return, from 1 to 50.
    """

    validate_retrieval_query(query)
    serving_runtime = get_serving_runtime()
    started_ns = time.perf_counter_ns()
    result = serving_runtime.retrieve(query, limit=_limit(top_k, field="top_k"))
    elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
    emit_retrieval_inspection(
        tool_runtime=runtime,
        runtime=serving_runtime,
        retriever=serving_runtime.retriever,
        retrieval=result,
        elapsed_ms=elapsed_ms,
    )
    return _format_retrieval(
        serving_runtime,
        result,
        method_id=serving_runtime.retriever.method_id,
    )


@tool
def metadata_filter(
    tags: list[str] | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Filter the published catalogue by tags, category, and inclusive date range.

    Args:
        tags: Tags matched with OR semantics.
        category: Exact top-level category, case-insensitive.
        date_from: Inclusive lower date in YYYY-MM-DD format.
        date_to: Inclusive upper date in YYYY-MM-DD format.
    """

    runtime = get_serving_runtime()
    lower = _date(date_from, field="date_from")
    upper = _date(date_to, field="date_to")
    if lower and upper and lower > upper:
        raise ValueError("date_from cannot be after date_to")
    entries = runtime.filter(
        tags=tags,
        category=category,
        date_from=lower,
        date_to=upper,
    )
    return _format_entries(entries[:_MAX_RESULTS], source="metadata_filter")


@tool
def graph_traverse(slug: str, depth: int = 1) -> str:
    """Find related published posts through the built-time wikilink graph.

    Args:
        slug: An exact path, title, or unique filename stem.
        depth: Number of graph hops, from 1 to 3.
    """

    runtime = get_serving_runtime()
    results = runtime.traverse(slug, depth=depth)
    if not results:
        return f"[graph_traverse] No results found for {slug!r}."
    lines = [
        f"Found {len(results)} related post(s) via graph_traverse for {slug!r}:",
        "",
    ]
    for rank, (doc_id, distance) in enumerate(results, start=1):
        entry = runtime.entry(doc_id)
        lines.append(f'{rank}. [{entry.doc_id}] "{entry.title}" (distance: {distance})')
        lines.append(f"   {post_url(doc_id)}")
    return "\n".join(lines)


@tool
def list_posts(category: str | None = None, limit: int = 20) -> str:
    """List recent published posts, optionally within one category.

    Args:
        category: Optional exact top-level category, case-insensitive.
        limit: Number of posts to return, from 1 to 50.
    """

    runtime = get_serving_runtime()
    entries = runtime.filter(category=category)
    return _format_entries(
        entries[: _limit(limit, field="limit")],
        source="list_posts",
    )


@tool
def read_post(path: str) -> str:
    """Read one verified published Markdown document with a 16 KiB output cap.

    Args:
        path: Canonical content-relative Markdown path returned by another tool.
    """

    runtime = get_serving_runtime()
    try:
        entry = runtime.entry(path)
        body = runtime.body(entry.doc_id)
    except (KeyError, TypeError, ValueError):
        return _cap_read_post_output(f"[read_post] Published file not found: {path!r}")
    output = (
        f"# {entry.title}\n"
        f"Date: {entry.published_label or 'unknown'}\n"
        f"Category: {entry.category}\n"
        f"Tags: {', '.join(entry.tags)}\n"
        "---\n"
        f"{body}"
    )
    return _cap_read_post_output(output)


TOOLS = [
    keyword_search,
    semantic_search,
    metadata_filter,
    graph_traverse,
    list_posts,
    read_post,
]

__all__ = [
    "READ_POST_MAX_OUTPUT_BYTES",
    "READ_POST_TRUNCATION_MARKER",
    "TOOLS",
    "graph_traverse",
    "keyword_search",
    "list_posts",
    "metadata_filter",
    "read_post",
    "semantic_search",
]
