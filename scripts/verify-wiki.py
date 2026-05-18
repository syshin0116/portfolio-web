#!/usr/bin/env python3
"""Verify the curated wiki layer.

This is intentionally dependency-free so it can run in GitHub Actions with
plain Python. It checks only repository-local Markdown content.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content"
WIKI = CONTENT / "wiki"
INDEX = WIKI / "index.md"

FORBIDDEN_PATTERNS = [
    r"braincrew-lab",
    r"braincrew",
    r"sk-hynix",
    r"hynix",
    r"하이닉스",
    r"SK하이닉스",
    r"github\.com/private-team",
    r"private-team",
]

REQUIRED_FRONTMATTER = {
    "title",
    "type",
    "tags",
    "summary",
    "sources",
    "created",
    "updated",
    "author",
    "draft",
}

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


def iter_markdown_files() -> list[Path]:
    return sorted(p for p in CONTENT.rglob("*.md") if p.is_file())


def parse_frontmatter(text: str) -> dict[str, object] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    block = text[4:end]
    data: dict[str, object] = {}
    current_key: str | None = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            data[current_key] = value.strip()
        elif current_key and line.strip().startswith("-"):
            prev = data.get(current_key)
            if not isinstance(prev, list):
                prev = []
                data[current_key] = prev
            prev.append(line.strip()[1:].strip())
    return data


def check_forbidden_terms(errors: list[str]) -> None:
    combined = re.compile("|".join(FORBIDDEN_PATTERNS), re.IGNORECASE)
    for path in iter_markdown_files():
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if combined.search(line):
                errors.append(f"forbidden term: {rel}:{lineno}: {line.strip()}")


def check_wiki_frontmatter(errors: list[str]) -> None:
    for path in sorted(WIKI.glob("*.md")):
        if path.name in {"index.md", "log.md"}:
            continue
        rel = path.relative_to(ROOT)
        data = parse_frontmatter(path.read_text(errors="ignore"))
        if data is None:
            errors.append(f"missing frontmatter: {rel}")
            continue
        missing = sorted(REQUIRED_FRONTMATTER - set(data))
        if missing:
            errors.append(f"missing frontmatter keys in {rel}: {', '.join(missing)}")
        if data.get("draft") not in {"false", "true", False, True}:
            errors.append(f"invalid draft value in {rel}: {data.get('draft')!r}")


def check_wikilinks(errors: list[str]) -> None:
    """Check wikilinks in curated wiki pages only.

    Legacy source posts contain many Obsidian links, code snippets, and media
    embeds that predate the curated wiki contract. The gate should protect the
    generated/curated wiki layer without making old source posts block every PR.
    """
    wiki_basenames = {p.stem for p in WIKI.glob("*.md")}
    for path in sorted(WIKI.glob("*.md")):
        if path.name in {"index.md", "log.md"}:
            continue
        text = path.read_text(errors="ignore")
        rel = path.relative_to(ROOT)
        for match in WIKILINK_RE.finditer(text):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://")):
                continue
            if target not in wiki_basenames:
                lineno = text[: match.start()].count("\n") + 1
                errors.append(f"unresolved wikilink: {rel}:{lineno}: [[{target}]]")


def check_index_coverage(errors: list[str]) -> None:
    if not INDEX.exists():
        errors.append("missing content/wiki/index.md")
        return
    text = INDEX.read_text(errors="ignore")
    for path in sorted(WIKI.glob("*.md")):
        if path.name in {"index.md", "log.md"}:
            continue
        link = f"[[{path.stem}]]"
        if link not in text:
            errors.append(f"wiki page missing from index: {path.relative_to(ROOT)}")


def main() -> int:
    errors: list[str] = []
    check_forbidden_terms(errors)
    check_wiki_frontmatter(errors)
    check_wikilinks(errors)
    check_index_coverage(errors)

    if errors:
        print("verify-wiki failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("verify-wiki passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
