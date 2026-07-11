"""Uniform result formatting for LLM consumption."""

from __future__ import annotations

from agent.lib.types import SearchResult


def format_results(
    results: list[SearchResult],
    *,
    source: str,
    query: str = "",
) -> str:
    if not results:
        return (
            f"[{source}] No results found" + (f" for '{query}'" if query else "") + "."
        )

    lines = [
        f"Found {len(results)} result(s) via {source}"
        + (f" for '{query}'" if query else "")
        + ":\n"
    ]

    for i, r in enumerate(results, 1):
        lines.append(f'{i}. [{r.path}] "{r.title}" (score: {r.score:.2f})')
        if r.snippet:
            snippet = r.snippet.replace("\n", " ").strip()
            if len(snippet) > 300:
                snippet = snippet[:297] + "..."
            lines.append(f"   {snippet}")
        lines.append("")

    return "\n".join(lines).rstrip()
