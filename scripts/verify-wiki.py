#!/usr/bin/env python3
"""Dependency-free CI implementation of the wiki-curator verify gate."""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
WIKI_ROOT = ROOT / "content" / "wiki"

REQUIRED_FRONTMATTER = [
    "title",
    "type",
    "tags",
    "sources",
    "summary",
    "created",
    "updated",
    "author",
    "draft",
]
FORBIDDEN_FRONTMATTER = ["coverage"]
MANDATORY_SECTIONS = ["## Key Claims", "## Footnotes"]
SUMMARY_MIN = 1
SUMMARY_MAX = 500
SKIP_FILES = {"index.md", "log.md"}
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
URL_SCHEME_RE = re.compile(r"^[a-z][a-z\d+.-]*:", re.IGNORECASE)
HOST_LABEL_RE = re.compile(r"^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$", re.IGNORECASE)


def walk_wiki() -> list[Path]:
    return sorted(
        path
        for path in WIKI_ROOT.rglob("*.md")
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(WIKI_ROOT).parts)
    )


def split_frontmatter(raw: str) -> tuple[str, str] | None:
    if not raw.startswith("---\n"):
        return None
    end = raw.find("\n---\n", 4)
    if end == -1:
        return None
    return raw[4:end], raw[end + 5 :]


def fm_has_field(frontmatter: str, key: str) -> bool:
    return re.search(rf"^{re.escape(key)}:", frontmatter, re.MULTILINE) is not None


def fm_get_scalar(frontmatter: str, key: str) -> str | None:
    lines = frontmatter.splitlines()
    for index, line in enumerate(lines):
        match = re.match(rf"^{re.escape(key)}:\s*(.*)$", line)
        if match is None:
            continue

        inline = match.group(1).strip()
        if inline in {"|", ">", "|-", ">-"}:
            collected: list[str] = []
            cursor = index + 1
            while cursor < len(lines) and (lines[cursor][:1].isspace() or not lines[cursor]):
                if lines[cursor]:
                    collected.append(lines[cursor].strip())
                cursor += 1
            separator = " " if inline.startswith(">") else "\n"
            return separator.join(collected).strip()

        if len(inline) >= 2 and inline[0] == inline[-1] and inline[0] in {'"', "'"}:
            inline = inline[1:-1]
        return inline
    return None


def fm_get_list(frontmatter: str, key: str) -> list[str]:
    values: list[str] = []
    inside = False
    for line in frontmatter.splitlines():
        if re.match(rf"^{re.escape(key)}:", line):
            inside = True
            continue
        if not inside:
            continue

        match = re.match(r"^\s+-\s+(.*)$", line)
        if match:
            value = match.group(1).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            values.append(value)
        elif line and not line[0].isspace():
            break
    return values


def fm_has_non_empty_tags(frontmatter: str) -> bool:
    lines = frontmatter.splitlines()
    inside = False
    for line in lines:
        if re.match(r"^tags:", line):
            inside = True
            continue
        if not inside:
            continue
        if re.match(r"^\s+-\s+\S", line):
            return True
        if line and not line[0].isspace():
            return False
    return False


def validate_https_source(source: str) -> str | None:
    try:
        parsed = urlsplit(source)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return "must be an absolute HTTPS URL"
        if any(character.isspace() or ord(character) < 32 for character in source):
            return "is not a valid HTTPS URL"
        parsed.port

        hostname = parsed.hostname
        if ":" in hostname:
            ip_address(hostname)
        else:
            ascii_hostname = hostname.encode("idna").decode("ascii").rstrip(".")
            if len(ascii_hostname) > 253 or any(
                HOST_LABEL_RE.fullmatch(label) is None
                for label in ascii_hostname.split(".")
            ):
                return "is not a valid HTTPS URL"
    except ValueError:
        return "is not a valid HTTPS URL"
    except UnicodeError:
        return "is not a valid HTTPS URL"
    return None


def validate_local_source(source: str) -> str | None:
    path = Path(source)
    if path.is_absolute():
        return "must be a repository-relative path"

    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT) or resolved == ROOT:
        return "must stay inside the repository"
    if not resolved.exists():
        return "does not exist"
    if not resolved.is_file():
        return "does not point to a file"
    return None


def main() -> int:
    failures: list[tuple[str, str, str]] = []
    files = walk_wiki()
    slugs = {path.stem for path in files}
    page_count = 0

    for path in files:
        if path.name in SKIP_FILES:
            continue

        relative = path.relative_to(ROOT).as_posix()
        raw = path.read_text(encoding="utf-8")
        split = split_frontmatter(raw)
        if split is None:
            failures.append(("frontmatter", relative, "no frontmatter block"))
            continue

        frontmatter, body = split
        page_count += 1

        for key in REQUIRED_FRONTMATTER:
            if not fm_has_field(frontmatter, key):
                failures.append(
                    ("frontmatter-missing", relative, f"missing required field: {key}")
                )

        for key in FORBIDDEN_FRONTMATTER:
            if fm_has_field(frontmatter, key):
                failures.append(
                    ("frontmatter-legacy", relative, f"legacy field present: {key}")
                )

        if re.search(r"^##\s+Summary\b", body, re.MULTILINE):
            failures.append(
                (
                    "body-summary-section",
                    relative,
                    "body contains `## Summary` - summary belongs in frontmatter",
                )
            )

        if re.search(r"^\s*>\s*\[!summary\]", body, re.IGNORECASE | re.MULTILINE):
            failures.append(
                (
                    "body-callout-summary",
                    relative,
                    "body contains legacy `> [!summary]` callout - move to frontmatter",
                )
            )

        for section in MANDATORY_SECTIONS:
            if re.search(rf"^{re.escape(section)}\b", body, re.MULTILINE) is None:
                failures.append(
                    ("missing-section", relative, f"missing mandatory section: {section}")
                )

        sources = fm_get_list(frontmatter, "sources")
        if not sources:
            failures.append(("sources-empty", relative, "sources frontmatter is empty"))
        for source in sources:
            if source.lower().startswith("https://"):
                detail = validate_https_source(source)
            elif URL_SCHEME_RE.match(source):
                detail = "uses an unsupported URL scheme; only HTTPS is allowed"
            else:
                detail = validate_local_source(source)
            if detail:
                failures.append(("source-invalid", relative, f"{source} {detail}"))

        summary = fm_get_scalar(frontmatter, "summary")
        if summary is not None:
            if len(summary) < SUMMARY_MIN:
                failures.append(("summary-empty", relative, "summary is empty"))
            elif len(summary) > SUMMARY_MAX:
                failures.append(
                    (
                        "summary-too-long",
                        relative,
                        f"summary is {len(summary)} chars (max {SUMMARY_MAX})",
                    )
                )

        if not fm_has_non_empty_tags(frontmatter):
            failures.append(("tags-empty", relative, "tags frontmatter is empty"))

        for line_number, line in enumerate(body.splitlines(), 1):
            for match in WIKILINK_RE.finditer(line):
                target = match.group(1).strip()
                if target not in slugs:
                    failures.append(
                        (
                            "wikilink-broken",
                            relative,
                            f"line {line_number}: [[{target}]] does not resolve",
                        )
                    )

    if not failures:
        print(f"OK - {page_count} pages, all checks pass.")
        return 0

    by_check: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for check, file, detail in failures:
        by_check[check].append((file, detail))

    print(f"FAIL - {len(failures)} issue(s) across {page_count} pages:\n")
    for check in sorted(by_check):
        items = by_check[check]
        print(f"### {check} ({len(items)})")
        for file, detail in items:
            print(f"  {file}: {detail}")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
