"""Manifest-backed access to the generated published corpus."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent.retrieval.protocol import DocId

MANIFEST_SCHEMA = "published-corpus-manifest-v2"
_FINGERPRINT_SCHEMA = "published-corpus-fingerprint-v1"
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
DERIVED_ARTIFACT_PATHS = ("catalog.json", "wikilinks.json")
_EXPECTED_TOP_LEVEL_ENTRIES = frozenset(
    {"manifest.json", "posts", *DERIVED_ARTIFACT_PATHS}
)
_MANIFEST_KEYS = frozenset(
    {
        "artifacts",
        "corpus_fingerprint",
        "document_count",
        "documents",
        "excluded_documents",
        "policy_schema_version",
        "schema",
        "source_markdown_count",
    }
)
_ARTIFACT_KEYS = frozenset({"bytes", "path", "sha256"})
_DOCUMENT_KEYS = frozenset({"bytes", "doc_id", "sha256"})
_EXCLUDED_DOCUMENT_KEYS = frozenset({"doc_id", "reason"})
_EXCLUSION_REASONS = frozenset(
    {
        "basename-leading-underscore",
        "draft",
        "private",
        "published-false",
    }
)


class CorpusManifestError(ValueError):
    """The generated corpus does not match its manifest."""


@dataclass(frozen=True, slots=True)
class _ManifestDocument:
    doc_id: DocId
    byte_count: int
    checksum: str


@dataclass(frozen=True, slots=True)
class _ManifestArtifact:
    path: str
    byte_count: int
    checksum: str


def content_checksum(payload: bytes) -> str:
    """Return the portable checksum representation used in corpus manifests."""

    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def corpus_fingerprint(
    documents: Iterable[tuple[DocId | str, str]],
) -> str:
    """Identify an exact sorted set of document paths and content checksums."""

    normalized = sorted(
        ((DocId(doc_id), checksum) for doc_id, checksum in documents),
        key=lambda item: str(item[0]),
    )
    doc_ids = [doc_id for doc_id, _ in normalized]
    if len(doc_ids) != len(set(doc_ids)):
        raise ValueError("corpus fingerprint documents must have unique DocIds")
    for _, checksum in normalized:
        if _SHA256_PATTERN.fullmatch(checksum) is None:
            raise ValueError(f"invalid document checksum: {checksum!r}")

    payload = {
        "schema": _FINGERPRINT_SCHEMA,
        "documents": [
            {"doc_id": str(doc_id), "sha256": checksum}
            for doc_id, checksum in normalized
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CorpusManifestError(f"duplicate JSON key in manifest: {key!r}")
        result[key] = value
    return result


def _load_manifest(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise CorpusManifestError(f"corpus manifest must not be a symlink: {path}")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_json_object,
        )
    except CorpusManifestError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorpusManifestError(f"cannot read corpus manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CorpusManifestError("corpus manifest root must be a JSON object")
    return payload


def _require_exact_keys(
    value: dict[str, object],
    *,
    expected: frozenset[str],
    location: str,
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise CorpusManifestError(
            f"{location} is missing required keys: {', '.join(missing)}"
        )
    if unknown:
        raise CorpusManifestError(
            f"{location} contains unknown keys: {', '.join(unknown)}"
        )


def _parse_manifest_document(value: object, *, index: int) -> _ManifestDocument:
    location = f"manifest.documents[{index}]"
    if not isinstance(value, dict):
        raise CorpusManifestError(f"{location} must be an object")
    _require_exact_keys(value, expected=_DOCUMENT_KEYS, location=location)
    doc_id_value = value["doc_id"]
    byte_count = value["bytes"]
    checksum = value["sha256"]
    if not isinstance(doc_id_value, str):
        raise CorpusManifestError(f"{location}.doc_id must be a string")
    try:
        doc_id = DocId(doc_id_value)
    except (TypeError, ValueError) as exc:
        raise CorpusManifestError(f"{location}.doc_id is invalid: {exc}") from exc
    if not str(doc_id).endswith(".md"):
        raise CorpusManifestError(f"{location}.doc_id must identify a Markdown file")
    if (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count < 0
    ):
        raise CorpusManifestError(f"{location}.bytes must be a non-negative integer")
    if not isinstance(checksum, str) or _SHA256_PATTERN.fullmatch(checksum) is None:
        raise CorpusManifestError(f"{location}.sha256 must be a sha256 checksum")
    return _ManifestDocument(doc_id, byte_count, checksum)


def _parse_manifest_artifact(value: object, *, index: int) -> _ManifestArtifact:
    location = f"manifest.artifacts[{index}]"
    if not isinstance(value, dict):
        raise CorpusManifestError(f"{location} must be an object")
    _require_exact_keys(value, expected=_ARTIFACT_KEYS, location=location)
    path = value["path"]
    byte_count = value["bytes"]
    checksum = value["sha256"]
    if not isinstance(path, str):
        raise CorpusManifestError(f"{location}.path must be a string")
    if (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count < 0
    ):
        raise CorpusManifestError(f"{location}.bytes must be a non-negative integer")
    if not isinstance(checksum, str) or _SHA256_PATTERN.fullmatch(checksum) is None:
        raise CorpusManifestError(f"{location}.sha256 must be a sha256 checksum")
    return _ManifestArtifact(path, byte_count, checksum)


def _parse_excluded_document(value: object, *, index: int) -> tuple[DocId, str]:
    location = f"manifest.excluded_documents[{index}]"
    if not isinstance(value, dict):
        raise CorpusManifestError(f"{location} must be an object")
    _require_exact_keys(
        value,
        expected=_EXCLUDED_DOCUMENT_KEYS,
        location=location,
    )
    doc_id_value = value["doc_id"]
    reason = value["reason"]
    if not isinstance(doc_id_value, str):
        raise CorpusManifestError(f"{location}.doc_id must be a string")
    try:
        doc_id = DocId(doc_id_value)
    except (TypeError, ValueError) as exc:
        raise CorpusManifestError(f"{location}.doc_id is invalid: {exc}") from exc
    if not str(doc_id).endswith(".md"):
        raise CorpusManifestError(f"{location}.doc_id must identify a Markdown file")
    if not isinstance(reason, str) or reason not in _EXCLUSION_REASONS:
        raise CorpusManifestError(
            f"{location}.reason is not a supported exclusion reason"
        )
    return doc_id, reason


class PublishedCorpus:
    """Read-only ``Corpus`` implementation over ``agent/.index/posts``.

    Initialization verifies the complete mirror, not just the manifest syntax. This makes
    a partial Docker copy, a stale build, and post-build tampering fail before retrieval.
    """

    def __init__(self, index_root: Path | str) -> None:
        self._index_root = Path(index_root)
        if self._index_root.is_symlink():
            raise CorpusManifestError(
                f"corpus index root must not be a symlink: {self._index_root}"
            )
        try:
            resolved_index_root = self._index_root.resolve(strict=True)
            entries = tuple(self._index_root.iterdir())
        except OSError as exc:
            raise CorpusManifestError(
                f"cannot inspect corpus index root {self._index_root}: {exc}"
            ) from exc
        if not resolved_index_root.is_dir():
            raise CorpusManifestError(
                f"corpus index root is not a directory: {self._index_root}"
            )
        for entry in entries:
            if entry.is_symlink():
                raise CorpusManifestError(
                    f"corpus index top-level entry must not be a symlink: {entry.name}"
                )
        actual_top_level = {entry.name for entry in entries}
        unexpected_top_level = sorted(actual_top_level - _EXPECTED_TOP_LEVEL_ENTRIES)
        missing_top_level = sorted(_EXPECTED_TOP_LEVEL_ENTRIES - actual_top_level)
        if unexpected_top_level:
            raise CorpusManifestError(
                "unexpected corpus index entries: " + ", ".join(unexpected_top_level)
            )
        if missing_top_level:
            raise CorpusManifestError(
                "corpus index is missing required entries: "
                + ", ".join(missing_top_level)
            )
        for name in ("manifest.json", *DERIVED_ARTIFACT_PATHS):
            if not (self._index_root / name).is_file():
                raise CorpusManifestError(
                    f"corpus index entry must be a regular file: {name}"
                )
        self._posts_root = self._index_root / "posts"
        manifest = _load_manifest(self._index_root / "manifest.json")
        _require_exact_keys(
            manifest,
            expected=_MANIFEST_KEYS,
            location="manifest",
        )

        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise CorpusManifestError(
                f"unsupported corpus manifest schema: {manifest.get('schema')!r}"
            )
        fingerprint = manifest.get("corpus_fingerprint")
        if (
            not isinstance(fingerprint, str)
            or _SHA256_PATTERN.fullmatch(fingerprint) is None
        ):
            raise CorpusManifestError(
                "manifest corpus_fingerprint must be a sha256 checksum"
            )
        raw_documents = manifest.get("documents")
        if not isinstance(raw_documents, list):
            raise CorpusManifestError("manifest documents must be an array")
        document_count = manifest.get("document_count")
        if (
            isinstance(document_count, bool)
            or not isinstance(document_count, int)
            or document_count != len(raw_documents)
        ):
            raise CorpusManifestError(
                "manifest document_count must equal the documents array length"
            )

        documents = tuple(
            _parse_manifest_document(value, index=index)
            for index, value in enumerate(raw_documents)
        )
        doc_ids = tuple(document.doc_id for document in documents)
        if doc_ids != tuple(sorted(doc_ids, key=str)):
            raise CorpusManifestError("manifest documents must be sorted by DocId")
        if len(doc_ids) != len(set(doc_ids)):
            raise CorpusManifestError("manifest contains duplicate DocIds")

        raw_artifacts = manifest.get("artifacts")
        if not isinstance(raw_artifacts, list):
            raise CorpusManifestError("manifest artifacts must be an array")
        artifacts = tuple(
            _parse_manifest_artifact(value, index=index)
            for index, value in enumerate(raw_artifacts)
        )
        artifact_paths = tuple(artifact.path for artifact in artifacts)
        if artifact_paths != DERIVED_ARTIFACT_PATHS:
            raise CorpusManifestError(
                "manifest artifacts must list exactly, in order: "
                + ", ".join(DERIVED_ARTIFACT_PATHS)
            )
        for artifact in artifacts:
            self._read_verified_artifact(
                artifact,
                index_root=resolved_index_root,
            )

        policy_schema_version = manifest.get("policy_schema_version")
        if type(policy_schema_version) is not int or policy_schema_version != 1:
            raise CorpusManifestError("manifest policy_schema_version must be 1")
        raw_excluded = manifest.get("excluded_documents")
        if not isinstance(raw_excluded, list):
            raise CorpusManifestError("manifest excluded_documents must be an array")
        excluded = tuple(
            _parse_excluded_document(value, index=index)
            for index, value in enumerate(raw_excluded)
        )
        excluded_doc_ids = tuple(doc_id for doc_id, _ in excluded)
        if excluded_doc_ids != tuple(sorted(excluded_doc_ids, key=str)):
            raise CorpusManifestError(
                "manifest excluded_documents must be sorted by DocId"
            )
        if len(excluded_doc_ids) != len(set(excluded_doc_ids)):
            raise CorpusManifestError(
                "manifest excluded_documents contains duplicate DocIds"
            )
        overlap = set(doc_ids) & set(excluded_doc_ids)
        if overlap:
            raise CorpusManifestError(
                "manifest published and excluded DocIds overlap: "
                + ", ".join(map(str, sorted(overlap, key=str)))
            )
        source_markdown_count = manifest.get("source_markdown_count")
        if (
            isinstance(source_markdown_count, bool)
            or not isinstance(source_markdown_count, int)
            or source_markdown_count != len(documents) + len(excluded)
        ):
            raise CorpusManifestError(
                "manifest source_markdown_count must equal published plus excluded "
                "documents"
            )

        if self._posts_root.is_symlink():
            raise CorpusManifestError(
                f"published mirror directory must not be a symlink: {self._posts_root}"
            )
        try:
            posts_root = self._posts_root.resolve(strict=True)
        except OSError as exc:
            raise CorpusManifestError(
                f"published mirror directory is missing: {self._posts_root}"
            ) from exc
        if not posts_root.is_dir():
            raise CorpusManifestError(
                f"published mirror is not a directory: {self._posts_root}"
            )

        actual_doc_ids: set[DocId] = set()
        for path in self._posts_root.rglob("*"):
            if path.is_symlink():
                raise CorpusManifestError(
                    f"published mirror must not contain symlinks: {path}"
                )
            if path.is_dir():
                continue
            if not path.is_file():
                raise CorpusManifestError(
                    f"published mirror contains an unsupported entry: {path}"
                )
            relative = path.relative_to(self._posts_root).as_posix()
            if path.suffix != ".md":
                raise CorpusManifestError(f"unexpected mirror regular file: {relative}")
            try:
                actual_doc_ids.add(DocId(relative))
            except (TypeError, ValueError) as exc:
                raise CorpusManifestError(
                    f"published mirror contains an invalid DocId: {relative!r}"
                ) from exc
        expected_doc_ids = set(doc_ids)
        unexpected = sorted(actual_doc_ids - expected_doc_ids, key=str)
        missing = sorted(expected_doc_ids - actual_doc_ids, key=str)
        if unexpected:
            raise CorpusManifestError(
                f"unexpected mirror Markdown files: {', '.join(map(str, unexpected))}"
            )
        if missing:
            raise CorpusManifestError(
                f"manifested mirror files are missing: {', '.join(map(str, missing))}"
            )

        checksums: list[tuple[DocId, str]] = []
        for document in documents:
            payload = self._read_verified_bytes(document, posts_root=posts_root)
            checksums.append((document.doc_id, content_checksum(payload)))
        actual_fingerprint = corpus_fingerprint(checksums)
        if actual_fingerprint != fingerprint:
            raise CorpusManifestError(
                "corpus fingerprint does not match the manifested document set"
            )

        self._documents = documents
        self._by_doc_id = {document.doc_id: document for document in documents}
        self._doc_ids = doc_ids
        self._fingerprint = fingerprint
        self._resolved_posts_root = posts_root

    def _read_verified_artifact(
        self,
        artifact: _ManifestArtifact,
        *,
        index_root: Path,
    ) -> bytes:
        path = self._index_root / artifact.path
        if path.is_symlink():
            raise CorpusManifestError(
                f"derived corpus artifact must not be a symlink: {artifact.path}"
            )
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(index_root) or not resolved.is_file():
                raise CorpusManifestError(
                    f"derived corpus artifact escapes the index: {artifact.path}"
                )
            payload = path.read_bytes()
        except CorpusManifestError:
            raise
        except OSError as exc:
            raise CorpusManifestError(
                f"cannot read derived corpus artifact {artifact.path}: {exc}"
            ) from exc
        if len(payload) != artifact.byte_count:
            raise CorpusManifestError(
                f"{artifact.path} artifact checksum/byte count mismatch"
            )
        if content_checksum(payload) != artifact.checksum:
            raise CorpusManifestError(f"{artifact.path} artifact checksum mismatch")
        return payload

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def index_root(self) -> Path:
        """Return the verified artifact root paired with this corpus mirror."""

        return self._index_root

    def doc_ids(self) -> Sequence[DocId]:
        return self._doc_ids

    def read(self, doc_id: DocId) -> str:
        requested = DocId(doc_id)
        document = self._by_doc_id.get(requested)
        if document is None:
            raise KeyError(f"{requested!s} is not in the published corpus")
        payload = self._read_verified_bytes(
            document,
            posts_root=self._resolved_posts_root,
        )
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CorpusManifestError(
                f"published document is not valid UTF-8: {requested}"
            ) from exc

    def _read_verified_bytes(
        self,
        document: _ManifestDocument,
        *,
        posts_root: Path,
    ) -> bytes:
        path = self._posts_root / str(document.doc_id)
        if path.is_symlink():
            raise CorpusManifestError(
                f"published mirror must not contain symlinks: {document.doc_id}"
            )
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(posts_root) or not resolved.is_file():
                raise CorpusManifestError(
                    f"published document escapes the mirror: {document.doc_id}"
                )
            payload = path.read_bytes()
        except CorpusManifestError:
            raise
        except OSError as exc:
            raise CorpusManifestError(
                f"cannot read published document {document.doc_id}: {exc}"
            ) from exc
        if len(payload) != document.byte_count:
            raise CorpusManifestError(
                f"checksum/byte count mismatch for published document {document.doc_id}"
            )
        if content_checksum(payload) != document.checksum:
            raise CorpusManifestError(
                f"checksum mismatch for published document {document.doc_id}"
            )
        return payload


__all__ = [
    "CorpusManifestError",
    "DERIVED_ARTIFACT_PATHS",
    "MANIFEST_SCHEMA",
    "PublishedCorpus",
    "content_checksum",
    "corpus_fingerprint",
]
