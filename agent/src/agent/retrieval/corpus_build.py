"""Deterministic one-scan build of the Nuartz-published corpus mirror."""

from __future__ import annotations

import json
import math
import os
import posixpath
import re
import shutil
import stat
import tempfile
import tomllib
import unicodedata
import uuid
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath

import yaml

from agent.retrieval.corpus import (
    DERIVED_ARTIFACT_PATHS,
    MANIFEST_SCHEMA,
    PublishedCorpus,
    content_checksum,
    corpus_fingerprint,
)
from agent.retrieval.protocol import DocId

CATALOG_SCHEMA = "published-corpus-catalog-v1"
WIKILINK_SCHEMA = "published-wikilinks-v2"
POLICY_SCHEMA_VERSION = 1
DEFAULT_BM25_POLICY = Path(__file__).resolve().parents[3] / "bm25-policy.toml"

_DATE_LIKE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:[ T]\d{1,2}:\d{2}"
    r"(?::\d{2}(?:\.\d+)?)?"
    r"(?: ?(?:Z|[+-]\d{2}:?\d{2}))?"
    r")?$"
)
_DATE_PREFIX_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-(.+)$")
_FENCE_PATTERN = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_WIKILINK_PATTERN = re.compile(r"(?<!!)\[\[([^\[\]|]+?)(?:\|([^\[\]]*?))?\]\]")
_YAML_1_2_BOOLEAN_PATTERN = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")


class CorpusBuildError(ValueError):
    """Source content cannot be safely represented as a published corpus."""


class _DuplicateKeyError(ValueError):
    pass


class _StrictSafeLoader(yaml.SafeLoader):
    pass


_StrictSafeLoader.yaml_implicit_resolvers = {
    key: [
        (tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_StrictSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    _YAML_1_2_BOOLEAN_PATTERN,
    list("tTfF"),
)


def _construct_unique_mapping(
    loader: _StrictSafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise _DuplicateKeyError(f"unhashable YAML mapping key {key!r}") from exc
        if duplicate:
            raise _DuplicateKeyError(f"duplicate YAML key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, slots=True)
class ExcludedDocument:
    doc_id: DocId
    reason: str


@dataclass(frozen=True, slots=True)
class SourceDocument:
    doc_id: DocId
    raw: bytes
    text: str
    body: str
    metadata: Mapping[str, object]
    checksum: str


@dataclass(frozen=True, slots=True)
class CorpusSnapshot:
    documents: tuple[SourceDocument, ...]
    excluded: tuple[ExcludedDocument, ...]
    source_markdown_count: int
    policy_schema_version: int


@dataclass(frozen=True, slots=True)
class BuildReport:
    document_count: int
    source_markdown_count: int
    fingerprint: str
    bm25_fingerprint: str
    output_root: Path


@dataclass(frozen=True, slots=True)
class _SourceCandidate:
    doc_id: DocId
    path: Path
    read_path: Path
    logical_version: tuple[int, int, int, int, int, int]
    resolved_version: tuple[int, int, int, int, int, int]


def _portable_path_key(doc_id: str) -> str:
    return unicodedata.normalize("NFC", doc_id).casefold()


def validate_portable_doc_ids(doc_ids: Iterable[DocId | str]) -> None:
    """Reject paths that collapse together on case-folding/NFC filesystems."""

    seen_files: dict[tuple[str, ...], DocId] = {}
    required_directories: dict[tuple[str, ...], DocId] = {}
    for value in doc_ids:
        doc_id = DocId(value)
        key = tuple(
            _portable_path_key(part) for part in PurePosixPath(str(doc_id)).parts
        )
        previous = seen_files.get(key)
        if previous is not None and previous != doc_id:
            raise CorpusBuildError(
                f"NFC/case-fold collision between {previous!s} and {doc_id!s}"
            )
        directory_owner = required_directories.get(key)
        if directory_owner is not None:
            raise CorpusBuildError(
                "NFC/case-fold file/directory collision between "
                f"{doc_id!s} and {directory_owner!s}"
            )
        for length in range(1, len(key)):
            prefix = key[:length]
            file_owner = seen_files.get(prefix)
            if file_owner is not None:
                raise CorpusBuildError(
                    "NFC/case-fold file/directory collision between "
                    f"{file_owner!s} and {doc_id!s}"
                )
            required_directories.setdefault(prefix, doc_id)
        seen_files[key] = doc_id


def _load_policy(path: Path) -> tuple[int, frozenset[DocId]]:
    try:
        policy = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise CorpusBuildError(f"cannot read corpus policy {path}: {exc}") from exc
    if not isinstance(policy, dict):
        raise CorpusBuildError("corpus policy root must be a TOML table")
    unknown = set(policy) - {"schema_version", "no_frontmatter_allowlist"}
    if unknown:
        raise CorpusBuildError(
            f"unknown corpus policy keys: {', '.join(sorted(unknown))}"
        )
    schema_version = policy.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != POLICY_SCHEMA_VERSION
    ):
        raise CorpusBuildError(
            f"corpus policy schema_version must be {POLICY_SCHEMA_VERSION}"
        )
    raw_allowlist = policy.get("no_frontmatter_allowlist")
    if not isinstance(raw_allowlist, list) or not all(
        isinstance(value, str) for value in raw_allowlist
    ):
        raise CorpusBuildError(
            "corpus policy no_frontmatter_allowlist must be an array of DocIds"
        )
    try:
        allowlist = tuple(DocId(value) for value in raw_allowlist)
    except (TypeError, ValueError) as exc:
        raise CorpusBuildError(
            f"invalid no-frontmatter allowlist entry: {exc}"
        ) from exc
    if len(allowlist) != len(set(allowlist)):
        raise CorpusBuildError("no-frontmatter allowlist contains duplicate DocIds")
    if any(not str(doc_id).endswith(".md") for doc_id in allowlist):
        raise CorpusBuildError(
            "no-frontmatter allowlist entries must identify Markdown files"
        )
    if allowlist != tuple(sorted(allowlist, key=str)):
        raise CorpusBuildError("no-frontmatter allowlist must be sorted by DocId")
    validate_portable_doc_ids(allowlist)
    return schema_version, frozenset(allowlist)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _stat_version(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _source_candidate(
    *,
    doc_id: DocId,
    path: Path,
    resolved_root: Path,
) -> _SourceCandidate:
    try:
        logical_stat = path.lstat()
        read_path = path.resolve(strict=True)
        if not _is_within(read_path, resolved_root):
            raise CorpusBuildError(f"out-of-tree symlink in content tree: {doc_id}")
        resolved_stat = read_path.stat(follow_symlinks=False)
    except CorpusBuildError:
        raise
    except OSError as exc:
        raise CorpusBuildError(
            f"source changed during corpus scan: {doc_id}: {exc}"
        ) from exc
    if not stat.S_ISREG(resolved_stat.st_mode):
        raise CorpusBuildError(
            f"source changed during corpus scan: {doc_id} is not a regular file"
        )
    return _SourceCandidate(
        doc_id=doc_id,
        path=path,
        read_path=read_path,
        logical_version=_stat_version(logical_stat),
        resolved_version=_stat_version(resolved_stat),
    )


def _discover_markdown(content_root: Path) -> tuple[_SourceCandidate, ...]:
    try:
        resolved_root = content_root.resolve(strict=True)
    except OSError as exc:
        raise CorpusBuildError(f"content root does not exist: {content_root}") from exc
    if not resolved_root.is_dir():
        raise CorpusBuildError(f"content root is not a directory: {content_root}")

    candidates: list[_SourceCandidate] = []

    def walk(
        directory: Path,
        logical_parts: tuple[str, ...],
        ancestors: frozenset[Path],
    ) -> None:
        try:
            resolved_directory = directory.resolve(strict=True)
        except OSError as exc:
            raise CorpusBuildError(
                f"broken symlink in content tree: {directory}"
            ) from exc
        if resolved_directory in ancestors:
            raise CorpusBuildError(f"symlink cycle in content tree: {directory}")
        descendants = ancestors | {resolved_directory}
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise CorpusBuildError(
                f"cannot scan content directory {directory}: {exc}"
            ) from exc
        for entry in entries:
            logical = logical_parts + (entry.name,)
            logical_path = PurePosixPath(*logical)
            entry_path = Path(entry.path)
            if entry.is_symlink():
                try:
                    target = entry_path.resolve(strict=True)
                except OSError as exc:
                    raise CorpusBuildError(
                        f"broken symlink in content tree: {logical_path}"
                    ) from exc
                if not _is_within(target, resolved_root):
                    raise CorpusBuildError(
                        f"out-of-tree symlink in content tree: {logical_path}"
                    )
                if target.is_dir():
                    walk(target, logical, descendants)
                    continue
                if target.is_file() and logical_path.suffix == ".md":
                    candidates.append(
                        _source_candidate(
                            doc_id=DocId(logical_path.as_posix()),
                            path=entry_path,
                            resolved_root=resolved_root,
                        )
                    )
                continue
            if entry.is_dir(follow_symlinks=False):
                walk(entry_path, logical, descendants)
            elif entry.is_file(follow_symlinks=False) and logical_path.suffix == ".md":
                candidates.append(
                    _source_candidate(
                        doc_id=DocId(logical_path.as_posix()),
                        path=entry_path,
                        resolved_root=resolved_root,
                    )
                )

    walk(content_root, (), frozenset())
    candidates.sort(key=lambda candidate: str(candidate.doc_id))
    validate_portable_doc_ids(candidate.doc_id for candidate in candidates)
    return tuple(candidates)


def _read_source(candidate: _SourceCandidate) -> bytes:
    try:
        if _stat_version(candidate.path.lstat()) != candidate.logical_version:
            raise CorpusBuildError(
                f"{candidate.doc_id}: source changed during corpus scan"
            )
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(candidate.read_path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened_version = _stat_version(os.fstat(source.fileno()))
            if opened_version != candidate.resolved_version:
                raise CorpusBuildError(
                    f"{candidate.doc_id}: source changed during corpus scan"
                )
            payload = source.read()
            if _stat_version(os.fstat(source.fileno())) != opened_version:
                raise CorpusBuildError(
                    f"{candidate.doc_id}: source changed while being read"
                )
        if _stat_version(candidate.path.lstat()) != candidate.logical_version:
            raise CorpusBuildError(
                f"{candidate.doc_id}: source changed during corpus scan"
            )
    except CorpusBuildError:
        raise
    except OSError as exc:
        raise CorpusBuildError(
            f"{candidate.doc_id}: source changed during corpus scan: {exc}"
        ) from exc
    return payload


def _split_frontmatter(
    text: str,
    *,
    doc_id: DocId,
) -> tuple[str, str] | None:
    parse_text = text.removeprefix("\ufeff")
    lines = parse_text.splitlines(keepends=True)
    if not lines:
        return None
    opener = lines[0].rstrip("\r\n")
    if not opener.startswith("---") or opener.startswith("----"):
        return None
    language = opener[3:].strip()
    if language not in {"", "yaml"}:
        raise CorpusBuildError(
            f"{doc_id}: unsupported gray-matter frontmatter language {language!r}"
        )
    for index, line in enumerate(lines[1:], start=1):
        delimiter = line.rstrip("\r\n")
        if delimiter.startswith("---"):
            if delimiter[3:].strip():
                raise CorpusBuildError(
                    f"{doc_id}: unsupported YAML closing delimiter {delimiter!r}"
                )
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    raise CorpusBuildError(f"{doc_id}: YAML frontmatter has no closing delimiter")


def _normalize_metadata(
    value: object,
    *,
    location: str,
    ancestors: frozenset[int] = frozenset(),
) -> object:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CorpusBuildError(f"{location}: metadata number must be finite")
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        identity = id(value)
        if identity in ancestors:
            raise CorpusBuildError(f"{location}: cyclic YAML values are not supported")
        return [
            _normalize_metadata(
                item,
                location=f"{location}[{index}]",
                ancestors=ancestors | {identity},
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        identity = id(value)
        if identity in ancestors:
            raise CorpusBuildError(f"{location}: cyclic YAML values are not supported")
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CorpusBuildError(f"{location}: YAML keys must be strings")
            normalized[key] = _normalize_metadata(
                item,
                location=f"{location}.{key}",
                ancestors=ancestors | {identity},
            )
        return normalized
    raise CorpusBuildError(
        f"{location}: unsupported YAML value type {type(value).__name__}"
    )


def _parse_frontmatter(raw: str, *, doc_id: DocId) -> dict[str, object]:
    try:
        value = yaml.load(raw, Loader=_StrictSafeLoader)
    except _DuplicateKeyError as exc:
        raise CorpusBuildError(f"{doc_id}: duplicate YAML key: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CorpusBuildError(f"{doc_id}: YAML parse error: {exc}") from exc
    if not isinstance(value, dict):
        raise CorpusBuildError(f"{doc_id}: YAML frontmatter must be a mapping")
    normalized = _normalize_metadata(value, location=f"{doc_id} frontmatter")
    if not isinstance(normalized, dict):
        raise CorpusBuildError(f"{doc_id}: YAML frontmatter must be a mapping")
    return normalized


def _is_date_like(value: str) -> bool:
    candidate = value.strip()
    if candidate != value or _DATE_LIKE_PATTERN.fullmatch(candidate) is None:
        return False
    try:
        if len(candidate) == 10:
            date.fromisoformat(candidate)
            return True
        # Python's ISO parser accepts the corpus's legacy " +0900" form, but
        # requires a zero-padded hour.
        normalized = re.sub(
            r"^(\d{4}-\d{2}-\d{2}[ T])(\d):",
            r"\g<1>0\2:",
            candidate,
        )
        datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return True


def _publication_exclusion(
    metadata: Mapping[str, object],
    *,
    doc_id: DocId,
) -> str | None:
    if "unlisted" in metadata:
        raise CorpusBuildError(
            f"{doc_id}: unlisted is unsupported until its semantics are decided"
        )
    for field in ("draft", "private"):
        if field in metadata and type(metadata[field]) is not bool:
            raise CorpusBuildError(
                f"{doc_id}: {field} must be a strict boolean when present"
            )
    published = metadata.get("published", ...)
    if published is not ...:
        if type(published) is bool:
            pass
        elif isinstance(published, str):
            if not _is_date_like(published):
                raise CorpusBuildError(f"{doc_id}: published string must be date-like")
        else:
            raise CorpusBuildError(
                f"{doc_id}: published must be a boolean or date/date-like string"
            )
    if metadata.get("draft") is True:
        return "draft"
    if metadata.get("private") is True:
        return "private"
    if published is False:
        return "published-false"
    return None


def scan_corpus(
    *,
    content_root: Path | str,
    policy_path: Path | str,
) -> CorpusSnapshot:
    """Scan source Markdown once and return the complete validated publication snapshot."""

    content = Path(content_root)
    policy_schema_version, allowlist = _load_policy(Path(policy_path))
    candidates = _discover_markdown(content)
    documents: list[SourceDocument] = []
    excluded: list[ExcludedDocument] = []
    seen_no_frontmatter: set[DocId] = set()

    for candidate in candidates:
        doc_id = candidate.doc_id
        if PurePosixPath(str(doc_id)).name.startswith("_"):
            excluded.append(ExcludedDocument(doc_id, "basename-leading-underscore"))
            continue
        try:
            raw = _read_source(candidate)
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CorpusBuildError(f"{doc_id}: source is not valid UTF-8") from exc

        frontmatter = _split_frontmatter(text, doc_id=doc_id)
        if frontmatter is None:
            if doc_id not in allowlist:
                raise CorpusBuildError(
                    f"{doc_id}: no frontmatter and DocId is not allowlisted"
                )
            seen_no_frontmatter.add(doc_id)
            metadata: dict[str, object] = {}
            body = text
        else:
            metadata = _parse_frontmatter(frontmatter[0], doc_id=doc_id)
            body = frontmatter[1]

        reason = _publication_exclusion(metadata, doc_id=doc_id)
        if reason is not None:
            excluded.append(ExcludedDocument(doc_id, reason))
            continue
        documents.append(
            SourceDocument(
                doc_id=doc_id,
                raw=raw,
                text=text,
                body=body,
                metadata=metadata,
                checksum=content_checksum(raw),
            )
        )

    stale = sorted(allowlist - seen_no_frontmatter, key=str)
    if stale:
        raise CorpusBuildError(
            "stale no-frontmatter allowlist entries: " + ", ".join(map(str, stale))
        )
    documents.sort(key=lambda document: str(document.doc_id))
    excluded.sort(key=lambda document: str(document.doc_id))
    return CorpusSnapshot(
        documents=tuple(documents),
        excluded=tuple(excluded),
        source_markdown_count=len(candidates),
        policy_schema_version=policy_schema_version,
    )


def _catalog_entry(document: SourceDocument) -> dict[str, object]:
    metadata = dict(document.metadata)
    path = PurePosixPath(str(document.doc_id))
    title = metadata.get("title")
    if not isinstance(title, str):
        title = path.stem
    date_value = metadata.get("date", metadata.get("published"))
    if not isinstance(date_value, str):
        date_value = None
    tags = metadata.get("tags")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        tags = []
    description = metadata.get("summary", metadata.get("description"))
    if not isinstance(description, str):
        description = ""
    return {
        "category": path.parts[0] if len(path.parts) > 1 else "",
        "date": date_value,
        "description": description,
        "doc_id": str(document.doc_id),
        "metadata": metadata,
        "tags": tags,
        "title": title,
    }


def _without_fenced_code(text: str) -> str:
    kept: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines(keepends=True):
        match = _FENCE_PATTERN.match(line)
        if fence_character is None:
            if match is None:
                kept.append(line)
                continue
            marker = match.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            continue
        if (
            match is not None
            and match.group(1)[0] == fence_character
            and len(match.group(1)) >= fence_length
        ):
            fence_character = None
            fence_length = 0
    return "".join(kept)


def _lookup_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _source_relative_target(
    source_doc_id: DocId,
    target: str,
    *,
    path_lookup: Mapping[str, DocId],
) -> DocId | None:
    if target.startswith("/") or target.startswith("content/"):
        return None
    source_parent = PurePosixPath(str(source_doc_id)).parent.as_posix()
    relative = posixpath.normpath(posixpath.join(source_parent, target))
    if relative == ".." or relative.startswith("../") or relative.startswith("/"):
        return None
    return path_lookup.get(_lookup_key(relative))


def _wikilink_graph(
    documents: tuple[SourceDocument, ...],
    *,
    fingerprint: str,
) -> dict[str, object]:
    path_lookup: dict[str, DocId] = {}
    name_candidates: dict[str, list[DocId]] = {}

    for document in documents:
        doc_id = str(document.doc_id)
        no_suffix = doc_id[:-3]
        for value in (
            doc_id,
            no_suffix,
            f"content/{doc_id}",
            f"content/{no_suffix}",
            f"/{doc_id}",
            f"/{no_suffix}",
        ):
            path_lookup[_lookup_key(value)] = document.doc_id

        stem = PurePosixPath(doc_id).stem
        date_match = _DATE_PREFIX_PATTERN.match(stem)
        title = document.metadata.get("title")
        names = [
            value
            for value in (
                title if isinstance(title, str) else None,
                stem,
                date_match.group(1) if date_match else stem,
            )
            if value
        ]
        for name in names:
            key = _lookup_key(name)
            candidates = name_candidates.setdefault(key, [])
            if document.doc_id not in candidates:
                candidates.append(document.doc_id)

    adjacency: dict[DocId, set[DocId]] = {
        document.doc_id: set() for document in documents
    }
    edges: set[tuple[DocId, DocId]] = set()
    links: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    excluded_links: list[dict[str, object]] = []
    for document in documents:
        body = _without_fenced_code(document.body)
        for match in _WIKILINK_PATTERN.finditer(body):
            raw_target = match.group(1).strip()
            target = raw_target.split("#", 1)[0].strip()
            alias_value = match.group(2)
            alias = alias_value.strip() if alias_value is not None else None
            target_doc_id = path_lookup.get(_lookup_key(target))
            if target_doc_id is None:
                target_doc_id = _source_relative_target(
                    document.doc_id,
                    target,
                    path_lookup=path_lookup,
                )
            candidates = name_candidates.get(_lookup_key(target), [])
            if target_doc_id is None and len(candidates) == 1:
                target_doc_id = candidates[0]
            if target_doc_id is None and len(candidates) > 1:
                excluded_links.append(
                    {
                        "alias": alias,
                        "candidates": [
                            str(candidate) for candidate in sorted(candidates, key=str)
                        ],
                        "reason": "ambiguous-target",
                        "source_doc_id": str(document.doc_id),
                        "target": target,
                    }
                )
                continue
            if target_doc_id is None:
                unresolved.append(
                    {
                        "alias": alias,
                        "source_doc_id": str(document.doc_id),
                        "target": target,
                    }
                )
                continue
            if target_doc_id == document.doc_id:
                excluded_links.append(
                    {
                        "alias": alias,
                        "reason": "self-link",
                        "source_doc_id": str(document.doc_id),
                        "target": target,
                        "target_doc_id": str(target_doc_id),
                    }
                )
                continue
            edge = tuple(sorted((document.doc_id, target_doc_id), key=str))
            edges.add(edge)
            adjacency[document.doc_id].add(target_doc_id)
            adjacency[target_doc_id].add(document.doc_id)
            links.append(
                {
                    "alias": alias,
                    "source_doc_id": str(document.doc_id),
                    "target": target,
                    "target_doc_id": str(target_doc_id),
                }
            )

    ambiguous_names = [
        {
            "candidates": [str(candidate) for candidate in sorted(candidates, key=str)],
            "name": name,
        }
        for name, candidates in sorted(name_candidates.items())
        if len(candidates) > 1
    ]
    serialized_adjacency = {
        str(doc_id): [str(neighbor) for neighbor in sorted(neighbors, key=str)]
        for doc_id, neighbors in adjacency.items()
    }
    nodes_with_edges = sum(bool(neighbors) for neighbors in adjacency.values())
    return {
        "adjacency": serialized_adjacency,
        "ambiguous_names": ambiguous_names,
        "corpus_fingerprint": fingerprint,
        "edge_count": len(edges),
        "excluded_links": excluded_links,
        "isolated_node_count": len(documents) - nodes_with_edges,
        "links": links,
        "node_count": len(documents),
        "nodes_with_edges": nodes_with_edges,
        "schema": WIKILINK_SCHEMA,
        "unresolved": unresolved,
    }


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.write_bytes(_json_bytes(payload))


def _write_snapshot(
    snapshot: CorpusSnapshot,
    output_root: Path,
    *,
    bm25_policy_path: Path | str,
) -> tuple[str, str]:
    posts_root = output_root / "posts"
    posts_root.mkdir(parents=True)
    fingerprint = corpus_fingerprint(
        (document.doc_id, document.checksum) for document in snapshot.documents
    )
    manifest_documents: list[dict[str, object]] = []
    for document in snapshot.documents:
        destination = posts_root / str(document.doc_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(document.raw)
        manifest_documents.append(
            {
                "bytes": len(document.raw),
                "doc_id": str(document.doc_id),
                "sha256": document.checksum,
            }
        )

    catalog = {
        "corpus_fingerprint": fingerprint,
        "document_count": len(snapshot.documents),
        "documents": [_catalog_entry(document) for document in snapshot.documents],
        "schema": CATALOG_SCHEMA,
    }
    graph = _wikilink_graph(snapshot.documents, fingerprint=fingerprint)
    artifact_payloads = {
        "catalog.json": _json_bytes(catalog),
        "wikilinks.json": _json_bytes(graph),
    }
    for artifact_path in DERIVED_ARTIFACT_PATHS:
        (output_root / artifact_path).write_bytes(artifact_payloads[artifact_path])
    # P1.3 consumes this exact immutable snapshot; it never scans source content again.
    from agent.retrieval.bm25 import build_bm25_artifacts

    try:
        bm25_build_fingerprint = build_bm25_artifacts(
            snapshot,
            index_root=output_root,
            policy_path=bm25_policy_path,
            corpus_fingerprint=fingerprint,
        )
    except ValueError as exc:
        raise CorpusBuildError(f"BM25 artifact build failed: {exc}") from exc
    artifact_paths = sorted(
        path.relative_to(output_root).as_posix()
        for path in output_root.rglob("*")
        if path.is_file() and not path.is_relative_to(posts_root)
    )
    manifest = {
        "artifacts": [
            {
                "bytes": len(payload),
                "path": path,
                "sha256": content_checksum(payload),
            }
            for path in artifact_paths
            for payload in [(output_root / path).read_bytes()]
        ],
        "corpus_fingerprint": fingerprint,
        "document_count": len(snapshot.documents),
        "documents": manifest_documents,
        "excluded_documents": [
            {"doc_id": str(document.doc_id), "reason": document.reason}
            for document in snapshot.excluded
        ],
        "policy_schema_version": snapshot.policy_schema_version,
        "schema": MANIFEST_SCHEMA,
        "source_markdown_count": snapshot.source_markdown_count,
    }
    # The root manifest inventories every finalized artifact, so it is always written last.
    _write_json(output_root / "manifest.json", manifest)
    return fingerprint, bm25_build_fingerprint


def _install_atomically(staged: Path, output_root: Path) -> None:
    if output_root.is_symlink():
        raise CorpusBuildError(f"output root must not be a symlink: {output_root}")
    if output_root.exists() and not output_root.is_dir():
        raise CorpusBuildError(f"output root is not a directory: {output_root}")
    backup = output_root.parent / f".{output_root.name}.backup-{uuid.uuid4().hex}"
    moved_previous = False
    try:
        if output_root.exists():
            os.replace(output_root, backup)
            moved_previous = True
        os.replace(staged, output_root)
    except OSError as exc:
        if moved_previous and backup.exists() and not output_root.exists():
            os.replace(backup, output_root)
        raise CorpusBuildError(
            f"cannot atomically install corpus index at {output_root}: {exc}"
        ) from exc
    if moved_previous:
        # The new complete index is already installed. A stale hidden backup is
        # preferable to reporting a failed build after a successful cutover.
        with suppress(OSError):
            shutil.rmtree(backup)


def build_index(
    *,
    content_root: Path | str,
    policy_path: Path | str,
    output_root: Path | str,
    expected_document_count: int | None = None,
    bm25_policy_path: Path | str = DEFAULT_BM25_POLICY,
) -> BuildReport:
    """Build the corpus mirror and BM25 artifacts from one validated snapshot."""

    if expected_document_count is not None and (
        isinstance(expected_document_count, bool)
        or not isinstance(expected_document_count, int)
        or expected_document_count < 0
    ):
        raise CorpusBuildError("expected document count must be a non-negative integer")
    snapshot = scan_corpus(content_root=content_root, policy_path=policy_path)
    document_count = len(snapshot.documents)
    if (
        expected_document_count is not None
        and document_count != expected_document_count
    ):
        raise CorpusBuildError(
            f"expected {expected_document_count} published documents, "
            f"built {document_count}"
        )
    output = Path(output_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.staged-",
            dir=output.parent,
        )
    )
    try:
        fingerprint, bm25_build_fingerprint = _write_snapshot(
            snapshot,
            staged,
            bm25_policy_path=bm25_policy_path,
        )
        corpus = PublishedCorpus(staged)
        from agent.retrieval.bm25 import Bm25Retriever

        try:
            bm25_fingerprint = Bm25Retriever(corpus).fingerprint
        except ValueError as exc:
            raise CorpusBuildError(f"BM25 artifact audit failed: {exc}") from exc
        if bm25_fingerprint != bm25_build_fingerprint:
            raise CorpusBuildError(
                "BM25 builder/runtime fingerprint mismatch: "
                f"{bm25_build_fingerprint} != {bm25_fingerprint}"
            )
        _install_atomically(staged, output)
    except Exception:
        if staged.exists():
            shutil.rmtree(staged)
        raise
    return BuildReport(
        document_count=document_count,
        source_markdown_count=snapshot.source_markdown_count,
        fingerprint=fingerprint,
        bm25_fingerprint=bm25_fingerprint,
        output_root=output,
    )


__all__ = [
    "BuildReport",
    "CATALOG_SCHEMA",
    "CorpusBuildError",
    "CorpusSnapshot",
    "DEFAULT_BM25_POLICY",
    "SourceDocument",
    "WIKILINK_SCHEMA",
    "build_index",
    "scan_corpus",
    "validate_portable_doc_ids",
]
