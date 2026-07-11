"""Ripgrep-based keyword/regex search over blog content."""

from __future__ import annotations

import json
import logging
import subprocess
from collections import defaultdict

from agent.lib.config import SearchConfig, get_config
from agent.lib.content_loader import get_cached_docs
from agent.lib.types import SearchResult

logger = logging.getLogger(__name__)


def ripgrep_search(
    query: str,
    *,
    glob: str = "*.md",
    case_insensitive: bool = True,
    context_lines: int = 2,
    max_results: int = 20,
    config: SearchConfig | None = None,
) -> list[SearchResult]:
    """Search blog content using ripgrep subprocess."""
    cfg = config or get_config()

    cmd = [
        cfg.rg_binary,
        "--no-config",
        "--json",
        "--max-count",
        "5",  # max matches per file
        "--glob",
        glob,
    ]
    if case_insensitive:
        cmd.append("-i")
    if context_lines > 0:
        cmd.extend(["-C", str(context_lines)])

    # `-e` forces query to be parsed as a pattern even when it starts with `-`.
    # `--` prevents the content path from being interpreted as another option.
    cmd.extend(["-e", query, "--", str(cfg.content_dir)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        logger.warning(
            "ripgrep (%s) not found, falling back to Python search", cfg.rg_binary
        )
        return _python_fallback(query, case_insensitive, max_results, cfg)
    except subprocess.TimeoutExpired:
        logger.warning("ripgrep timed out for query: %s", query)
        return []

    # Parse JSON lines output
    matches_by_file: dict[str, list[str]] = defaultdict(list)
    for line in result.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if obj.get("type") == "match":
            data = obj["data"]
            path = data["path"]["text"]
            text = data["lines"]["text"].strip()
            matches_by_file[path].append(text)

    # Build results with match-count scoring
    docs = get_cached_docs(cfg)
    doc_by_path = {str(cfg.content_dir / d.meta.path): d for d in docs}

    results: list[SearchResult] = []
    for fpath, match_lines in matches_by_file.items():
        doc = doc_by_path.get(fpath)
        title = doc.meta.title if doc else fpath.split("/")[-1]
        rel_path = (
            doc.meta.path if doc else fpath.replace(str(cfg.content_dir) + "/", "")
        )

        snippet = "\n".join(match_lines[:3])
        score = min(len(match_lines) / 5.0, 1.0)  # normalize by max matches

        results.append(
            SearchResult(
                path=rel_path,
                title=title,
                score=score,
                snippet=snippet,
                source="ripgrep",
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:max_results]


def _python_fallback(
    query: str,
    case_insensitive: bool,
    max_results: int,
    config: SearchConfig,
) -> list[SearchResult]:
    """Pure Python fallback when ripgrep is not available."""
    import re

    flags = re.IGNORECASE if case_insensitive else 0
    try:
        pattern = re.compile(query, flags)
    except re.error:
        pattern = re.compile(re.escape(query), flags)

    docs = get_cached_docs(config)
    results: list[SearchResult] = []

    for doc in docs:
        matches = pattern.findall(doc.body)
        if not matches:
            continue

        # Extract snippet around first match
        m = pattern.search(doc.body)
        if m:
            start = max(0, m.start() - 100)
            end = min(len(doc.body), m.end() + 100)
            snippet = doc.body[start:end].strip()
        else:
            snippet = ""

        results.append(
            SearchResult(
                path=doc.meta.path,
                title=doc.meta.title,
                score=min(len(matches) / 5.0, 1.0),
                snippet=snippet,
                source="ripgrep-fallback",
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:max_results]
