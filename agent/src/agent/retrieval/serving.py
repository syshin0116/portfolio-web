"""Fail-closed serving facade over the generated published corpus artifacts."""

from __future__ import annotations

import json
import math
import os
import posixpath
import re
import unicodedata
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath

from agent.retrieval import registry
from agent.retrieval.corpus import (
    CATALOG_SCHEMA,
    WIKILINK_SCHEMA,
    PublishedCorpus,
    content_checksum,
)
from agent.retrieval.exact import EXACT_METHOD_ID
from agent.retrieval.protocol import DocId, Retrieval

DEFAULT_RETRIEVER_METHOD = "bm25"
_AGENT_ROOT = Path(__file__).parents[3]
DEFAULT_INDEX_ROOT = _AGENT_ROOT / ".index"
_CATALOG_KEYS = frozenset(
    {"corpus_fingerprint", "document_count", "documents", "schema"}
)
_CATALOG_ENTRY_KEYS = frozenset(
    {
        "category",
        "date",
        "description",
        "doc_id",
        "metadata",
        "tags",
        "title",
    }
)
_GRAPH_KEYS = frozenset(
    {
        "adjacency",
        "ambiguous_names",
        "corpus_fingerprint",
        "edge_count",
        "excluded_links",
        "isolated_node_count",
        "links",
        "node_count",
        "nodes_with_edges",
        "schema",
        "unresolved",
    }
)
_LINK_KEYS = frozenset({"alias", "source_doc_id", "target", "target_doc_id"})
_UNRESOLVED_KEYS = frozenset({"alias", "source_doc_id", "target"})
_AMBIGUOUS_NAME_KEYS = frozenset({"candidates", "name"})
_AMBIGUOUS_EXCLUSION_KEYS = frozenset(
    {"alias", "candidates", "reason", "source_doc_id", "target"}
)
_SELF_LINK_EXCLUSION_KEYS = frozenset(
    {"alias", "reason", "source_doc_id", "target", "target_doc_id"}
)
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-(.+)$")
_DATE_LIKE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:[ T]\d{1,2}:\d{2}"
    r"(?::\d{2}(?:\.\d+)?)?"
    r"(?: ?(?:Z|[+-]\d{2}:?\d{2}))?"
    r")?$"
)
_MAX_GRAPH_RESULTS = 50


class ServingArtifactError(ValueError):
    """A published serving artifact is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    doc_id: DocId
    title: str
    published_on: date | None
    published_label: str | None
    tags: tuple[str, ...]
    category: str
    description: str
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ValidatedWikilinkGraph:
    """Serving-strength validation result shared with offline evaluation."""

    adjacency: Mapping[DocId, tuple[DocId, ...]]
    links: tuple[Mapping[str, object], ...]
    unresolved: tuple[Mapping[str, object], ...]
    excluded_links: tuple[Mapping[str, object], ...]
    artifact_checksum: str


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ServingArtifactError(
                f"duplicate JSON key in serving artifact: {key!r}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ServingArtifactError(f"non-finite JSON constant in serving artifact: {value}")


def _load_json(corpus: PublishedCorpus, path: str) -> dict[str, object]:
    try:
        payload = json.loads(
            corpus.read_artifact(path).decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except ServingArtifactError:
        raise
    except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise ServingArtifactError(
            f"cannot read serving artifact {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ServingArtifactError(f"serving artifact {path} must be a JSON object")
    return payload


def _exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    location: str,
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise ServingArtifactError(
            f"{location} is missing required keys: {', '.join(missing)}"
        )
    if unknown:
        raise ServingArtifactError(
            f"{location} contains unknown keys: {', '.join(unknown)}"
        )


def _date(value: object, *, location: str) -> tuple[date | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, str):
        raise ServingArtifactError(f"{location} must be a string or null")
    if value != value.strip() or _DATE_LIKE.fullmatch(value) is None:
        raise ServingArtifactError(f"{location} is not a supported ISO date")
    try:
        if len(value) == 10:
            return date.fromisoformat(value), value
        normalized = re.sub(
            r"^(\d{4}-\d{2}-\d{2}[ T])(\d):",
            r"\g<1>0\2:",
            value,
        )
        return datetime.fromisoformat(normalized).date(), value
    except ValueError as exc:
        raise ServingArtifactError(f"{location} is not a supported ISO date") from exc


def _validate_json_value(value: object, *, location: str) -> None:
    if value is None or type(value) in {bool, int, str}:
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ServingArtifactError(f"{location} must be a finite JSON number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, location=f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_json_value(item, location=f"{location}.{key}")
        return
    raise ServingArtifactError(
        f"{location} contains unsupported JSON type {type(value).__name__}"
    )


def _catalog(corpus: PublishedCorpus) -> tuple[CatalogEntry, ...]:
    payload = _load_json(corpus, "catalog.json")
    _exact_keys(payload, _CATALOG_KEYS, location="catalog")
    if payload["schema"] != CATALOG_SCHEMA:
        raise ServingArtifactError("unsupported catalog schema")
    if payload["corpus_fingerprint"] != corpus.fingerprint:
        raise ServingArtifactError("catalog corpus fingerprint mismatch")
    documents = payload["documents"]
    if not isinstance(documents, list):
        raise ServingArtifactError("catalog.documents must be an array")
    if _non_negative_integer(
        payload["document_count"],
        location="catalog.document_count",
    ) != len(documents):
        raise ServingArtifactError("catalog document_count mismatch")

    entries: list[CatalogEntry] = []
    for index, raw in enumerate(documents):
        location = f"catalog.documents[{index}]"
        if not isinstance(raw, dict):
            raise ServingArtifactError(f"{location} must be an object")
        _exact_keys(raw, _CATALOG_ENTRY_KEYS, location=location)
        try:
            doc_id = DocId(raw["doc_id"])
        except (TypeError, ValueError) as exc:
            raise ServingArtifactError(f"{location}.doc_id is invalid") from exc
        for field in ("title", "category", "description"):
            if not isinstance(raw[field], str):
                raise ServingArtifactError(f"{location}.{field} must be a string")
        tags = raw["tags"]
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ServingArtifactError(f"{location}.tags must be a string array")
        metadata = raw["metadata"]
        if not isinstance(metadata, dict):
            raise ServingArtifactError(f"{location}.metadata must be an object")
        _validate_json_value(metadata, location=f"{location}.metadata")
        published_on, published_label = _date(
            raw["date"],
            location=f"{location}.date",
        )
        path = PurePosixPath(str(doc_id))
        expected_title = metadata.get("title")
        if not isinstance(expected_title, str):
            expected_title = path.stem
        expected_date = metadata.get("date", metadata.get("published"))
        if not isinstance(expected_date, str):
            expected_date = None
        expected_tags = metadata.get("tags")
        if not (
            isinstance(expected_tags, list)
            and all(isinstance(tag, str) for tag in expected_tags)
        ):
            expected_tags = []
        expected_description = metadata.get(
            "summary",
            metadata.get("description"),
        )
        if not isinstance(expected_description, str):
            expected_description = ""
        expected_category = path.parts[0] if len(path.parts) > 1 else ""
        expected_values = {
            "category": expected_category,
            "date": expected_date,
            "description": expected_description,
            "tags": expected_tags,
            "title": expected_title,
        }
        for field, expected in expected_values.items():
            if raw[field] != expected:
                raise ServingArtifactError(
                    f"{location}.{field} is inconsistent with DocId/metadata"
                )
        entries.append(
            CatalogEntry(
                doc_id=doc_id,
                title=raw["title"],
                published_on=published_on,
                published_label=published_label,
                tags=tuple(tags),
                category=raw["category"],
                description=raw["description"],
                metadata=metadata,
            )
        )

    doc_ids = tuple(entry.doc_id for entry in entries)
    if doc_ids != tuple(corpus.doc_ids()):
        raise ServingArtifactError(
            "catalog DocIds do not exactly match the published corpus"
        )
    return tuple(entries)


def _non_negative_integer(value: object, *, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ServingArtifactError(f"{location} must be a non-negative integer")
    return value


def _text(value: object, *, location: str, non_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ServingArtifactError(f"{location} must be a string")
    if non_empty and (not value or value != value.strip()):
        raise ServingArtifactError(f"{location} must be a non-empty trimmed string")
    return value


def _alias(value: object, *, location: str) -> str | None:
    if value is None:
        return None
    alias = _text(value, location=location)
    if alias != alias.strip():
        raise ServingArtifactError(f"{location} must not contain outer whitespace")
    return alias


def _graph_doc_id(
    value: object,
    *,
    location: str,
    expected: set[DocId],
) -> DocId:
    try:
        doc_id = DocId(value)
    except (TypeError, ValueError) as exc:
        raise ServingArtifactError(f"{location} is not a valid DocId") from exc
    if doc_id not in expected:
        raise ServingArtifactError(f"{location} is outside the published corpus")
    return doc_id


def _candidate_doc_ids(
    value: object,
    *,
    location: str,
    expected: set[DocId],
) -> tuple[DocId, ...]:
    if not isinstance(value, list):
        raise ServingArtifactError(f"{location} must be an array")
    candidates = tuple(
        _graph_doc_id(
            item,
            location=f"{location}[{index}]",
            expected=expected,
        )
        for index, item in enumerate(value)
    )
    if len(candidates) < 2:
        raise ServingArtifactError(f"{location} must contain at least two DocIds")
    if candidates != tuple(sorted(set(candidates), key=str)):
        raise ServingArtifactError(f"{location} must be sorted and unique")
    return candidates


def _graph_lookups(
    entries: Sequence[CatalogEntry],
) -> tuple[dict[str, DocId], dict[str, tuple[DocId, ...]]]:
    path_lookup: dict[str, DocId] = {}
    name_sets: dict[str, set[DocId]] = {}
    for entry in entries:
        raw_doc_id = str(entry.doc_id)
        no_suffix = raw_doc_id[:-3]
        for value in (
            raw_doc_id,
            no_suffix,
            f"content/{raw_doc_id}",
            f"content/{no_suffix}",
            f"/{raw_doc_id}",
            f"/{no_suffix}",
        ):
            path_lookup[_normalize_lookup(value)] = entry.doc_id

        path = PurePosixPath(raw_doc_id)
        stem = path.stem
        date_match = _DATE_PREFIX.match(stem)
        metadata_title = entry.metadata.get("title")
        names = (
            metadata_title if isinstance(metadata_title, str) else None,
            stem,
            date_match.group(1) if date_match else stem,
        )
        for name in names:
            if name:
                name_sets.setdefault(_normalize_lookup(name), set()).add(entry.doc_id)
    return path_lookup, {
        key: tuple(sorted(values, key=str)) for key, values in name_sets.items()
    }


def _resolve_graph_target(
    source: DocId,
    target: str,
    *,
    path_lookup: Mapping[str, DocId],
    name_candidates: Mapping[str, tuple[DocId, ...]],
) -> tuple[DocId | None, tuple[DocId, ...]]:
    direct = path_lookup.get(_normalize_lookup(target))
    if direct is not None:
        return direct, ()
    if not target.startswith("/") and not target.startswith("content/"):
        source_parent = PurePosixPath(str(source)).parent.as_posix()
        relative = posixpath.normpath(posixpath.join(source_parent, target))
        if (
            relative != ".."
            and not relative.startswith("../")
            and not relative.startswith("/")
        ):
            direct = path_lookup.get(_normalize_lookup(relative))
            if direct is not None:
                return direct, ()
    candidates = name_candidates.get(_normalize_lookup(target), ())
    return (candidates[0], candidates) if len(candidates) == 1 else (None, candidates)


def _validated_wikilinks(
    corpus: PublishedCorpus,
    entries: Sequence[CatalogEntry],
) -> ValidatedWikilinkGraph:
    payload = _load_json(corpus, "wikilinks.json")
    _exact_keys(payload, _GRAPH_KEYS, location="wikilinks")
    if payload["schema"] != WIKILINK_SCHEMA:
        raise ServingArtifactError("unsupported wikilink graph schema")
    if payload["corpus_fingerprint"] != corpus.fingerprint:
        raise ServingArtifactError("wikilink graph corpus fingerprint mismatch")
    raw_adjacency = payload["adjacency"]
    if not isinstance(raw_adjacency, dict):
        raise ServingArtifactError("wikilinks.adjacency must be an object")

    expected = set(corpus.doc_ids())
    path_lookup, name_candidates = _graph_lookups(entries)
    graph: dict[DocId, tuple[DocId, ...]] = {}
    for raw_doc_id, raw_neighbors in raw_adjacency.items():
        doc_id = _graph_doc_id(
            raw_doc_id,
            location="wikilinks.adjacency key",
            expected=expected,
        )
        if not isinstance(raw_neighbors, list):
            raise ServingArtifactError(
                f"wikilinks.adjacency[{doc_id!s}] must be an array"
            )
        neighbors = tuple(
            _graph_doc_id(
                value,
                location=f"wikilinks.adjacency[{doc_id!s}][{index}]",
                expected=expected,
            )
            for index, value in enumerate(raw_neighbors)
        )
        if neighbors != tuple(sorted(neighbors, key=str)):
            raise ServingArtifactError("wikilink adjacency lists must be sorted")
        if len(neighbors) != len(set(neighbors)):
            raise ServingArtifactError("wikilink adjacency lists must be unique")
        if doc_id in neighbors:
            raise ServingArtifactError("wikilink adjacency cannot contain self edges")
        if not set(neighbors) <= expected:
            raise ServingArtifactError("wikilink adjacency points outside the corpus")
        graph[doc_id] = neighbors

    if set(graph) != expected:
        raise ServingArtifactError(
            "wikilink graph nodes do not exactly match the published corpus"
        )
    for source, neighbors in graph.items():
        for target in neighbors:
            if source not in graph[target]:
                raise ServingArtifactError("wikilink adjacency must be bidirectional")

    graph_edges = {
        tuple(sorted((source, target), key=str))
        for source, neighbors in graph.items()
        for target in neighbors
    }
    edge_count = len(graph_edges)
    nodes_with_edges = sum(bool(neighbors) for neighbors in graph.values())
    node_count = len(graph)
    expected_counts = {
        "edge_count": edge_count,
        "isolated_node_count": node_count - nodes_with_edges,
        "node_count": node_count,
        "nodes_with_edges": nodes_with_edges,
    }
    for field, expected_count in expected_counts.items():
        actual = _non_negative_integer(payload[field], location=f"wikilinks.{field}")
        if actual != expected_count:
            raise ServingArtifactError(f"wikilinks.{field} mismatch")

    raw_ambiguous_names = payload["ambiguous_names"]
    if not isinstance(raw_ambiguous_names, list):
        raise ServingArtifactError("wikilinks.ambiguous_names must be an array")
    ambiguous_names: dict[str, tuple[DocId, ...]] = {}
    ordered_names: list[str] = []
    for index, raw in enumerate(raw_ambiguous_names):
        location = f"wikilinks.ambiguous_names[{index}]"
        if not isinstance(raw, dict):
            raise ServingArtifactError(f"{location} must be an object")
        _exact_keys(raw, _AMBIGUOUS_NAME_KEYS, location=location)
        name = _text(raw["name"], location=f"{location}.name", non_empty=True)
        if name != _normalize_lookup(name):
            raise ServingArtifactError(f"{location}.name must be NFC-casefolded")
        candidates = _candidate_doc_ids(
            raw["candidates"],
            location=f"{location}.candidates",
            expected=expected,
        )
        if name in ambiguous_names:
            raise ServingArtifactError("wikilinks.ambiguous_names contains duplicates")
        ambiguous_names[name] = candidates
        ordered_names.append(name)
    if ordered_names != sorted(ordered_names):
        raise ServingArtifactError("wikilinks.ambiguous_names must be sorted by name")
    expected_ambiguous_names = {
        name: candidates
        for name, candidates in name_candidates.items()
        if len(candidates) > 1
    }
    if ambiguous_names != expected_ambiguous_names:
        raise ServingArtifactError(
            "wikilinks.ambiguous_names disagrees with catalog names"
        )

    raw_links = payload["links"]
    if not isinstance(raw_links, list):
        raise ServingArtifactError("wikilinks.links must be an array")
    linked_edges: set[tuple[DocId, DocId]] = set()
    for index, raw in enumerate(raw_links):
        location = f"wikilinks.links[{index}]"
        if not isinstance(raw, dict):
            raise ServingArtifactError(f"{location} must be an object")
        _exact_keys(raw, _LINK_KEYS, location=location)
        _alias(raw["alias"], location=f"{location}.alias")
        target_text = _text(
            raw["target"],
            location=f"{location}.target",
            non_empty=True,
        )
        source = _graph_doc_id(
            raw["source_doc_id"],
            location=f"{location}.source_doc_id",
            expected=expected,
        )
        target = _graph_doc_id(
            raw["target_doc_id"],
            location=f"{location}.target_doc_id",
            expected=expected,
        )
        if source == target:
            raise ServingArtifactError(f"{location} cannot be a self-link")
        resolved, candidates = _resolve_graph_target(
            source,
            target_text,
            path_lookup=path_lookup,
            name_candidates=name_candidates,
        )
        if resolved != target or len(candidates) > 1:
            raise ServingArtifactError(
                f"{location}.target does not resolve to target_doc_id"
            )
        edge = tuple(sorted((source, target), key=str))
        if edge not in graph_edges:
            raise ServingArtifactError(f"{location} is absent from adjacency")
        linked_edges.add(edge)
    if linked_edges != graph_edges:
        raise ServingArtifactError(
            "wikilinks.links and adjacency describe different edge sets"
        )

    raw_unresolved = payload["unresolved"]
    if not isinstance(raw_unresolved, list):
        raise ServingArtifactError("wikilinks.unresolved must be an array")
    for index, raw in enumerate(raw_unresolved):
        location = f"wikilinks.unresolved[{index}]"
        if not isinstance(raw, dict):
            raise ServingArtifactError(f"{location} must be an object")
        _exact_keys(raw, _UNRESOLVED_KEYS, location=location)
        _alias(raw["alias"], location=f"{location}.alias")
        target_text = _text(
            raw["target"],
            location=f"{location}.target",
            non_empty=True,
        )
        source = _graph_doc_id(
            raw["source_doc_id"],
            location=f"{location}.source_doc_id",
            expected=expected,
        )
        resolved, candidates = _resolve_graph_target(
            source,
            target_text,
            path_lookup=path_lookup,
            name_candidates=name_candidates,
        )
        if resolved is not None or len(candidates) > 1:
            raise ServingArtifactError(f"{location}.target is not actually unresolved")

    raw_excluded = payload["excluded_links"]
    if not isinstance(raw_excluded, list):
        raise ServingArtifactError("wikilinks.excluded_links must be an array")
    for index, raw in enumerate(raw_excluded):
        location = f"wikilinks.excluded_links[{index}]"
        if not isinstance(raw, dict):
            raise ServingArtifactError(f"{location} must be an object")
        reason = raw.get("reason")
        if reason == "ambiguous-target":
            _exact_keys(raw, _AMBIGUOUS_EXCLUSION_KEYS, location=location)
            _alias(raw["alias"], location=f"{location}.alias")
            target = _text(
                raw["target"],
                location=f"{location}.target",
                non_empty=True,
            )
            source = _graph_doc_id(
                raw["source_doc_id"],
                location=f"{location}.source_doc_id",
                expected=expected,
            )
            candidates = _candidate_doc_ids(
                raw["candidates"],
                location=f"{location}.candidates",
                expected=expected,
            )
            if ambiguous_names.get(_normalize_lookup(target)) != candidates:
                raise ServingArtifactError(
                    f"{location}.candidates disagree with ambiguous_names"
                )
            resolved, resolved_candidates = _resolve_graph_target(
                source,
                target,
                path_lookup=path_lookup,
                name_candidates=name_candidates,
            )
            if resolved is not None or resolved_candidates != candidates:
                raise ServingArtifactError(
                    f"{location}.target is not actually ambiguous"
                )
        elif reason == "self-link":
            _exact_keys(raw, _SELF_LINK_EXCLUSION_KEYS, location=location)
            _alias(raw["alias"], location=f"{location}.alias")
            target_text = _text(
                raw["target"],
                location=f"{location}.target",
                non_empty=True,
            )
            source = _graph_doc_id(
                raw["source_doc_id"],
                location=f"{location}.source_doc_id",
                expected=expected,
            )
            target = _graph_doc_id(
                raw["target_doc_id"],
                location=f"{location}.target_doc_id",
                expected=expected,
            )
            if source != target:
                raise ServingArtifactError(
                    f"{location}.target_doc_id must equal source_doc_id"
                )
            resolved, candidates = _resolve_graph_target(
                source,
                target_text,
                path_lookup=path_lookup,
                name_candidates=name_candidates,
            )
            if resolved != source or len(candidates) > 1:
                raise ServingArtifactError(
                    f"{location}.target does not resolve to the self-link source"
                )
        else:
            raise ServingArtifactError(f"{location}.reason is unsupported")
    return ValidatedWikilinkGraph(
        adjacency=graph,
        links=tuple(raw_links),
        unresolved=tuple(raw_unresolved),
        excluded_links=tuple(raw_excluded),
        artifact_checksum=content_checksum(corpus.read_artifact("wikilinks.json")),
    )


def load_validated_wikilink_graph(
    corpus: PublishedCorpus,
) -> ValidatedWikilinkGraph:
    """Validate the complete graph exactly as serving does and return its entries."""

    return _validated_wikilinks(corpus, _catalog(corpus))


def _normalize_lookup(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _body(markdown: str) -> str:
    if not markdown.startswith("---\n"):
        return markdown
    boundary = markdown.find("\n---\n", 4)
    return markdown[boundary + 5 :] if boundary >= 0 else markdown


class ServingRuntime:
    """One immutable corpus snapshot and its registry-resolved serving methods."""

    def __init__(
        self,
        index_root: Path | str,
        *,
        method_id: str = DEFAULT_RETRIEVER_METHOD,
    ) -> None:
        if not isinstance(method_id, str) or not method_id.strip():
            raise ValueError("serving retriever method must be a non-empty string")
        if method_id != method_id.strip():
            raise ValueError("serving retriever method cannot contain outer whitespace")
        self.corpus = PublishedCorpus(index_root)
        self.entries = _catalog(self.corpus)
        self._entry_by_id = {entry.doc_id: entry for entry in self.entries}
        self.adjacency = _validated_wikilinks(
            self.corpus,
            self.entries,
        ).adjacency
        self.retriever = registry.servable.create(method_id, self.corpus)
        self.exact_retriever = (
            self.retriever
            if method_id == EXACT_METHOD_ID
            else registry.servable.create(EXACT_METHOD_ID, self.corpus)
        )
        self._lookup = self._build_lookup()

    def _build_lookup(self) -> Mapping[str, tuple[DocId, ...]]:
        candidates: dict[str, set[DocId]] = {}
        for entry in self.entries:
            path = PurePosixPath(str(entry.doc_id))
            stem = path.stem
            date_match = _DATE_PREFIX.match(stem)
            values = (
                str(entry.doc_id),
                str(entry.doc_id)[:-3],
                entry.title,
                stem,
                date_match.group(1) if date_match else stem,
            )
            for value in values:
                candidates.setdefault(_normalize_lookup(value), set()).add(entry.doc_id)
        return {
            key: tuple(sorted(values, key=str)) for key, values in candidates.items()
        }

    def entry(self, doc_id: DocId | str) -> CatalogEntry:
        requested = DocId(doc_id)
        try:
            return self._entry_by_id[requested]
        except KeyError:
            raise KeyError(f"{requested!s} is not in the published corpus") from None

    def read(self, doc_id: DocId | str) -> str:
        requested = DocId(doc_id)
        self.entry(requested)
        return self.corpus.read(requested)

    def body(self, doc_id: DocId | str) -> str:
        return _body(self.read(doc_id))

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        return self.retriever.retrieve(query, limit=limit)

    def exact(self, query: str, *, limit: int = 10) -> Retrieval:
        return self.exact_retriever.retrieve(query, limit=limit)

    def filter(
        self,
        *,
        tags: Sequence[str] | None = None,
        category: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> tuple[CatalogEntry, ...]:
        tag_set = {_normalize_lookup(tag) for tag in tags or ()}
        category_key = _normalize_lookup(category) if category else None
        matches: list[CatalogEntry] = []
        for entry in self.entries:
            if tag_set and not tag_set.intersection(
                _normalize_lookup(tag) for tag in entry.tags
            ):
                continue
            if category_key and _normalize_lookup(entry.category) != category_key:
                continue
            if date_from and (
                entry.published_on is None or entry.published_on < date_from
            ):
                continue
            if date_to and (entry.published_on is None or entry.published_on > date_to):
                continue
            matches.append(entry)
        return tuple(
            sorted(
                matches,
                key=lambda entry: (
                    -(entry.published_on or date.min).toordinal(),
                    str(entry.doc_id),
                ),
            )
        )

    def resolve(self, slug: str) -> DocId | None:
        if not isinstance(slug, str) or not slug:
            return None
        candidates = self._lookup.get(_normalize_lookup(slug), ())
        return candidates[0] if len(candidates) == 1 else None

    def traverse(self, slug: str, *, depth: int = 1) -> tuple[tuple[DocId, int], ...]:
        if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 3:
            raise ValueError("depth must be an integer from 1 to 3")
        start = self.resolve(slug)
        if start is None:
            return ()
        visited: dict[DocId, int] = {start: 0}
        queue: deque[DocId] = deque([start])
        while queue:
            source = queue.popleft()
            distance = visited[source]
            if distance >= depth:
                continue
            for target in self.adjacency[source]:
                if target not in visited:
                    visited[target] = distance + 1
                    queue.append(target)
        ordered = sorted(
            (
                (doc_id, distance)
                for doc_id, distance in visited.items()
                if doc_id != start
            ),
            key=lambda item: (item[1], str(item[0])),
        )
        return tuple(ordered[:_MAX_GRAPH_RESULTS])

    def close(self) -> None:
        """Release any retriever-owned serving resources."""

        implementations = {
            id(resolved.implementation): resolved.implementation
            for resolved in (self.retriever, self.exact_retriever)
        }
        for implementation in implementations.values():
            close = getattr(implementation, "close", None)
            if callable(close):
                close()


def _absolute_without_resolving(path: Path) -> Path:
    if path.is_absolute():
        return path
    return Path(os.path.abspath(path))


@lru_cache(maxsize=8)
def _cached_runtime(index_root: str, method_id: str) -> ServingRuntime:
    return ServingRuntime(Path(index_root), method_id=method_id)


def get_serving_runtime() -> ServingRuntime:
    """Resolve server-owned environment configuration and cache one immutable runtime."""

    index_root = _absolute_without_resolving(
        Path(os.environ.get("BLOG_INDEX_PATH", str(DEFAULT_INDEX_ROOT)))
    )
    method_id = os.environ.get("RAG_RETRIEVER_METHOD", DEFAULT_RETRIEVER_METHOD)
    return _cached_runtime(str(index_root), method_id)


def reset_serving_runtime_cache() -> None:
    """Clear process-local serving state for tests and controlled reloads."""

    _cached_runtime.cache_clear()


__all__ = [
    "CatalogEntry",
    "DEFAULT_INDEX_ROOT",
    "DEFAULT_RETRIEVER_METHOD",
    "ServingArtifactError",
    "ServingRuntime",
    "ValidatedWikilinkGraph",
    "get_serving_runtime",
    "load_validated_wikilink_graph",
    "reset_serving_runtime_cache",
]
