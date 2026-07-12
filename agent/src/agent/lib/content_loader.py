"""Blog content loader — frontmatter parsing, caching, wikilink extraction."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path

import yaml

from agent.lib.config import SearchConfig, get_config
from agent.lib.types import ContentDoc, PostMeta

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# Module-level cache
_cache: list[ContentDoc] = []
_cache_mtime: float = 0.0


def _parse_date(val: object) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M %z", "%Y-%m-%d %H:%M:%S %z"):
        try:
            return datetime.strptime(
                s[:19] if len(s) > 19 else s, fmt[: len(s) + 1].rstrip()
            ).date()
        except (ValueError, IndexError):
            continue
    # Try just the date portion
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_one(path: Path, content_dir: Path) -> ContentDoc | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Cannot read %s: %s", path, e)
        return None

    rel = str(path.relative_to(content_dir))
    parts = rel.split("/")
    category = parts[0] if len(parts) > 1 else ""

    # Parse frontmatter
    fm_match = _FRONTMATTER_RE.match(raw)
    if fm_match:
        try:
            fm = yaml.safe_load(fm_match.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        body = raw[fm_match.end() :]
    else:
        fm = {}
        body = raw

    # Skip drafts
    if fm.get("draft", False) and not fm.get("published"):
        return None

    meta = PostMeta(
        path=rel,
        title=fm.get("title", path.stem),
        date=_parse_date(fm.get("date") or fm.get("published")),
        tags=[str(t) for t in (fm.get("tags") or [])],
        category=category,
        description=str(fm.get("summary") or fm.get("description") or ""),
        draft=bool(fm.get("draft", False)),
    )

    wikilinks = _WIKILINK_RE.findall(body)

    return ContentDoc(meta=meta, body=body, wikilinks=wikilinks)


def _get_latest_mtime(content_dir: Path) -> float:
    latest = 0.0
    for p in content_dir.rglob("*.md"):
        try:
            mt = p.stat().st_mtime
            if mt > latest:
                latest = mt
        except OSError:
            pass
    return latest


def load_all(config: SearchConfig | None = None) -> list[ContentDoc]:
    """Load and parse all markdown files from content directory."""
    cfg = config or get_config()
    docs: list[ContentDoc] = []
    for p in sorted(cfg.content_dir.rglob("*.md")):
        doc = _parse_one(p, cfg.content_dir)
        if doc is not None:
            docs.append(doc)
    logger.info("Loaded %d blog posts from %s", len(docs), cfg.content_dir)
    return docs


def get_cached_docs(config: SearchConfig | None = None) -> list[ContentDoc]:
    """Return cached docs, rebuilding if any file changed."""
    global _cache, _cache_mtime
    cfg = config or get_config()
    latest = _get_latest_mtime(cfg.content_dir)
    if not _cache or latest > _cache_mtime:
        _cache = load_all(cfg)
        _cache_mtime = latest
    return _cache


def load_one(path: str, config: SearchConfig | None = None) -> ContentDoc | None:
    """Load a single blog post by relative path."""
    cfg = config or get_config()
    try:
        content_dir = cfg.content_dir.resolve()
        requested = Path(path)
        if requested.is_absolute() or requested.suffix != ".md":
            return None
        full = (content_dir / requested).resolve()
    except (OSError, RuntimeError, ValueError):
        return None

    if not full.is_relative_to(content_dir) or not full.is_file():
        return None
    return _parse_one(full, content_dir)
