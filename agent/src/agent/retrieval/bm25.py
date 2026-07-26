"""Deterministic Korean BM25 build artifacts and runtime retriever."""

from __future__ import annotations

import json
import re
import tomllib
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from agent.retrieval.corpus import PublishedCorpus, content_checksum
from agent.retrieval.fingerprint import canonical_config, retriever_fingerprint
from agent.retrieval.protocol import Corpus, DocId, Hit, Retrieval
from agent.retrieval.registry import registry

if TYPE_CHECKING:
    from agent.retrieval.corpus_build import CorpusSnapshot, SourceDocument

BM25_METHOD_ID = "bm25"
BM25_IMPLEMENTATION_ID = "agent.retrieval.bm25:create@1"
BM25_MANIFEST_SCHEMA = "kiwi-bm25-manifest-v1"
BM25_TOKEN_SCHEMA = "bm25-token-corpus-v1"
DICTIONARY_SCHEMA = "kiwi-user-dictionary-v1"
DICTIONARY_POLICY_SCHEMA_VERSION = 1
EXPECTED_KIWI_VERSION = "0.23.2"
EXPECTED_RANK_BM25_VERSION = "0.2.2"
MORPHEME_NAMESPACE = "m:"
SURFACE_NAMESPACE = "s:"
SURFACE_PATTERN = r"[0-9A-Za-z가-힣]+"
INDEXED_FIELDS = ("title", "description", "tags", "body")

BM25_CONFIG: dict[str, object] = {
    "artifact_schema": BM25_MANIFEST_SCHEMA,
    "dictionary_schema": DICTIONARY_SCHEMA,
    "fields": list(INDEXED_FIELDS),
    "ranker": {
        "algorithm": "BM25Okapi",
        "b": 0.75,
        "epsilon": 0.25,
        "k1": 1.5,
        "package": "rank-bm25",
        "version": EXPECTED_RANK_BM25_VERSION,
    },
    "tokenizer": {
        "keep_pos": ["NN*", "SL"],
        "morpheme_namespace": MORPHEME_NAMESPACE,
        "normalization": "NFC+casefold",
        "num_workers": 1,
        "package": "kiwipiepy",
        "surface_namespace": SURFACE_NAMESPACE,
        "surface_pattern": SURFACE_PATTERN,
        "user_dictionary_pos": "NNP",
        "version": EXPECTED_KIWI_VERSION,
    },
}

_SURFACE_RE = re.compile(SURFACE_PATTERN)
_HANGUL_TERM_RE = re.compile(r"^[가-힣]{2,}$")
_ALIAS_RE = re.compile(
    r"(?<![가-힣])(?P<hangul>[가-힣]{2,})\s*"
    r"\(\s*(?P<latin>[A-Za-z][A-Za-z0-9+._/# -]{0,127})\s*\)"
)
_CHECKSUM_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MANIFEST_KEYS = frozenset(
    {
        "config",
        "corpus_fingerprint",
        "dictionary",
        "document_count",
        "implementation_id",
        "method_id",
        "schema",
        "tokens",
    }
)
_DICTIONARY_KEYS = frozenset(
    {
        "entries",
        "entry_count",
        "path",
        "policy_id",
        "policy_sha256",
        "schema",
        "sha256",
    }
)
_DICTIONARY_ENTRY_KEYS = frozenset({"pos", "sources", "term"})
_DICTIONARY_SOURCE_KEYS = frozenset({"evidence", "kind", "source"})
_TOKENS_REFERENCE_KEYS = frozenset({"path", "schema", "sha256"})
_TOKEN_ROOT_KEYS = frozenset(
    {
        "corpus_fingerprint",
        "dictionary_sha256",
        "document_count",
        "documents",
        "schema",
    }
)
_TOKEN_DOCUMENT_KEYS = frozenset({"doc_id", "tokens"})


class Bm25ArtifactError(ValueError):
    """A BM25 policy, generated artifact, or runtime dependency is invalid."""


@dataclass(frozen=True, order=True, slots=True)
class DictionarySource:
    kind: str
    source: str
    evidence: str

    def as_dict(self) -> dict[str, str]:
        return {
            "evidence": self.evidence,
            "kind": self.kind,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    term: str
    sources: tuple[DictionarySource, ...]
    pos: str = "NNP"

    def as_dict(self) -> dict[str, object]:
        return {
            "pos": self.pos,
            "sources": [source.as_dict() for source in self.sources],
            "term": self.term,
        }


@dataclass(frozen=True, slots=True)
class DictionaryPolicy:
    policy_id: str
    seeds: tuple[str, ...]
    deny: frozenset[str]
    checksum: str


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _require_exact_keys(
    value: Mapping[str, object],
    *,
    expected: frozenset[str],
    location: str,
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise Bm25ArtifactError(
            f"{location} is missing required keys: {', '.join(missing)}"
        )
    if unknown:
        raise Bm25ArtifactError(
            f"{location} contains unknown keys: {', '.join(unknown)}"
        )


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Bm25ArtifactError(f"duplicate JSON key in BM25 artifact: {key!r}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise Bm25ArtifactError(f"BM25 artifact must not be a symlink: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_json_object,
        )
    except Bm25ArtifactError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Bm25ArtifactError(f"cannot read BM25 artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Bm25ArtifactError(f"BM25 artifact root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _policy_terms(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise Bm25ArtifactError(f"BM25 policy {field} must be an array of strings")
    normalized = tuple(_normalize(item) for item in value)
    if any(_HANGUL_TERM_RE.fullmatch(item) is None for item in normalized):
        raise Bm25ArtifactError(
            f"BM25 policy {field} must contain only two-or-more-syllable Hangul terms"
        )
    if len(normalized) != len(set(normalized)):
        raise Bm25ArtifactError(f"BM25 policy {field} contains duplicate terms")
    if normalized != tuple(sorted(normalized)):
        raise Bm25ArtifactError(f"BM25 policy {field} must be sorted")
    return normalized


def load_dictionary_policy(path: Path | str) -> DictionaryPolicy:
    """Load the versioned owner-reviewed seed/deny policy exactly."""

    policy_path = Path(path)
    try:
        raw = policy_path.read_bytes()
        value = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise Bm25ArtifactError(
            f"cannot read BM25 dictionary policy {policy_path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise Bm25ArtifactError("BM25 dictionary policy root must be a table")
    _require_exact_keys(
        value,
        expected=frozenset({"deny", "policy_id", "schema_version", "seeds"}),
        location="BM25 dictionary policy",
    )
    schema_version = value["schema_version"]
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != DICTIONARY_POLICY_SCHEMA_VERSION
    ):
        raise Bm25ArtifactError(
            "BM25 dictionary policy schema_version must be "
            f"{DICTIONARY_POLICY_SCHEMA_VERSION}"
        )
    policy_id = value["policy_id"]
    if (
        not isinstance(policy_id, str)
        or not policy_id
        or policy_id != policy_id.strip()
    ):
        raise Bm25ArtifactError("BM25 dictionary policy_id must be non-empty")
    seeds = _policy_terms(value["seeds"], field="seeds")
    deny = _policy_terms(value["deny"], field="deny")
    overlap = sorted(set(seeds) & set(deny))
    if overlap:
        raise Bm25ArtifactError(
            "BM25 dictionary policy seed/deny overlap: " + ", ".join(overlap)
        )
    return DictionaryPolicy(
        policy_id=policy_id,
        seeds=seeds,
        deny=frozenset(deny),
        checksum=content_checksum(raw),
    )


def _source_fields(document: SourceDocument) -> tuple[tuple[str, str], ...]:
    title = document.metadata.get("title")
    if not isinstance(title, str):
        title = PurePosixPath(str(document.doc_id)).stem
    description = document.metadata.get(
        "summary",
        document.metadata.get("description", ""),
    )
    if not isinstance(description, str):
        description = ""
    tags = document.metadata.get("tags")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        tags = []
    return (
        ("title", title),
        ("description", description),
        *(("tags", tag) for tag in tags),
        ("body", document.body),
    )


def collect_dictionary_evidence(
    snapshot: CorpusSnapshot,
    policy: DictionaryPolicy,
) -> tuple[DictionaryEntry, ...]:
    """Collect seeds, pure-Hangul tags, and attested ``한글(ASCII)`` aliases."""

    evidence: dict[str, set[DictionarySource]] = {}
    for term in policy.seeds:
        evidence.setdefault(term, set()).add(
            DictionarySource(
                kind="seed",
                source=policy.policy_id,
                evidence=term,
            )
        )

    for document in snapshot.documents:
        source = str(document.doc_id)
        tags = document.metadata.get("tags")
        if isinstance(tags, list):
            for tag in tags:
                if not isinstance(tag, str):
                    continue
                term = _normalize(tag)
                if _HANGUL_TERM_RE.fullmatch(term):
                    evidence.setdefault(term, set()).add(
                        DictionarySource(
                            kind="tag",
                            source=source,
                            evidence=tag,
                        )
                    )
        for field, text in _source_fields(document):
            normalized_text = unicodedata.normalize("NFC", text)
            for match in _ALIAS_RE.finditer(normalized_text):
                term = _normalize(match.group("hangul"))
                evidence.setdefault(term, set()).add(
                    DictionarySource(
                        kind="alias",
                        source=source,
                        evidence=f"{field}:{match.group('latin').strip()}",
                    )
                )

    return tuple(
        DictionaryEntry(term=term, sources=tuple(sorted(sources)))
        for term, sources in sorted(evidence.items())
        if term not in policy.deny
    )


def _installed_version(package: str, *, expected: str) -> str:
    try:
        actual = distribution_version(package)
    except PackageNotFoundError as exc:
        raise Bm25ArtifactError(
            f"required BM25 package {package} is unavailable"
        ) from exc
    if actual != expected:
        raise Bm25ArtifactError(
            f"{package} version drift: expected {expected}, installed {actual}"
        )
    return actual


def _import_kiwi_class() -> type:
    try:
        from kiwipiepy import Kiwi
    except ImportError as exc:
        raise Bm25ArtifactError("Kiwi tokenizer is unavailable") from exc
    return Kiwi


def _import_bm25_class() -> type:
    try:
        from rank_bm25 import BM25Okapi
    except ImportError as exc:
        raise Bm25ArtifactError("rank_bm25 is unavailable") from exc
    return BM25Okapi


def _require_runtime_dependencies() -> None:
    _installed_version("kiwipiepy", expected=EXPECTED_KIWI_VERSION)
    _installed_version("rank-bm25", expected=EXPECTED_RANK_BM25_VERSION)


class _KiwiTokenizer:
    def __init__(self, dictionary_path: Path) -> None:
        _require_runtime_dependencies()
        try:
            kiwi_class = _import_kiwi_class()
            self._kiwi = kiwi_class(num_workers=1)
            loaded = self._kiwi.load_user_dictionary(str(dictionary_path))
        except Bm25ArtifactError:
            raise
        except Exception as exc:
            raise Bm25ArtifactError(
                f"Kiwi user dictionary load failed: {dictionary_path}: {exc}"
            ) from exc
        if isinstance(loaded, bool) or not isinstance(loaded, int) or loaded < 0:
            raise Bm25ArtifactError(
                "Kiwi user dictionary returned an invalid load count"
            )

    def tokenize(self, text: str) -> list[str]:
        if not isinstance(text, str):
            raise TypeError("BM25 tokenizer input must be a string")
        normalized = _normalize(text)
        try:
            analyzed = self._kiwi.tokenize(normalized)
        except Exception as exc:
            raise Bm25ArtifactError(f"Kiwi tokenization failed: {exc}") from exc
        morphemes = [
            MORPHEME_NAMESPACE + _normalize(token.form)
            for token in analyzed
            if token.tag.startswith("NN") or token.tag == "SL"
        ]
        surfaces = [
            SURFACE_NAMESPACE + match.group(0)
            for match in _SURFACE_RE.finditer(normalized)
        ]
        return morphemes + surfaces


def _dictionary_bytes(
    entries: Sequence[DictionaryEntry],
    *,
    corpus_fingerprint: str,
) -> bytes:
    lines = [
        f"# schema: {DICTIONARY_SCHEMA}",
        f"# corpus_fingerprint: {corpus_fingerprint}",
        *(f"{entry.term}\t{entry.pos}" for entry in entries),
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _document_tokens(
    document: SourceDocument,
    *,
    tokenizer: _KiwiTokenizer,
) -> list[str]:
    tokens: list[str] = []
    for _, text in _source_fields(document):
        tokens.extend(tokenizer.tokenize(text))
    return tokens


def build_bm25_artifacts(
    snapshot: CorpusSnapshot,
    *,
    index_root: Path,
    policy_path: Path | str,
    corpus_fingerprint: str,
) -> str:
    """Extend one existing corpus snapshot with deterministic BM25 artifacts."""

    policy = load_dictionary_policy(policy_path)
    entries = collect_dictionary_evidence(snapshot, policy)
    dictionary_path = index_root / "kiwi-user-dictionary.txt"
    dictionary_payload = _dictionary_bytes(
        entries,
        corpus_fingerprint=corpus_fingerprint,
    )
    dictionary_path.write_bytes(dictionary_payload)
    dictionary_checksum = content_checksum(dictionary_payload)
    tokenizer = _KiwiTokenizer(dictionary_path)

    token_payload = {
        "corpus_fingerprint": corpus_fingerprint,
        "dictionary_sha256": dictionary_checksum,
        "document_count": len(snapshot.documents),
        "documents": [
            {
                "doc_id": str(document.doc_id),
                "tokens": _document_tokens(document, tokenizer=tokenizer),
            }
            for document in snapshot.documents
        ],
        "schema": BM25_TOKEN_SCHEMA,
    }
    tokens_path = index_root / "bm25" / "documents.json"
    _write_json(tokens_path, token_payload)
    tokens_checksum = content_checksum(tokens_path.read_bytes())
    manifest = {
        "config": BM25_CONFIG,
        "corpus_fingerprint": corpus_fingerprint,
        "dictionary": {
            "entries": [entry.as_dict() for entry in entries],
            "entry_count": len(entries),
            "path": "kiwi-user-dictionary.txt",
            "policy_id": policy.policy_id,
            "policy_sha256": policy.checksum,
            "schema": DICTIONARY_SCHEMA,
            "sha256": dictionary_checksum,
        },
        "document_count": len(snapshot.documents),
        "implementation_id": BM25_IMPLEMENTATION_ID,
        "method_id": BM25_METHOD_ID,
        "schema": BM25_MANIFEST_SCHEMA,
        "tokens": {
            "path": "bm25/documents.json",
            "schema": BM25_TOKEN_SCHEMA,
            "sha256": tokens_checksum,
        },
    }
    manifest_path = index_root / "bm25" / "manifest.json"
    _write_json(manifest_path, manifest)
    identity = {
        "config": BM25_CONFIG,
        "corpus_fingerprint": corpus_fingerprint,
        "dictionary_policy_sha256": policy.checksum,
        "dictionary_sha256": dictionary_checksum,
        "kiwi_version": EXPECTED_KIWI_VERSION,
        "rank_bm25_version": EXPECTED_RANK_BM25_VERSION,
        "tokens_sha256": tokens_checksum,
    }
    return retriever_fingerprint(
        method_id=BM25_METHOD_ID,
        implementation_id=BM25_IMPLEMENTATION_ID,
        config=identity,
        corpus_fingerprint=corpus_fingerprint,
    )


def _artifact_path(index_root: Path, value: object, *, expected: str) -> Path:
    if value != expected:
        raise Bm25ArtifactError(f"BM25 artifact path must be {expected!r}")
    path = index_root / expected
    if path.is_symlink():
        raise Bm25ArtifactError(f"BM25 artifact must not be a symlink: {path}")
    try:
        resolved_root = index_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise Bm25ArtifactError(f"BM25 artifact is missing: {path}") from exc
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise Bm25ArtifactError(f"BM25 artifact escapes index root: {path}")
    return path


def _require_checksum(value: object, *, location: str) -> str:
    if not isinstance(value, str) or _CHECKSUM_RE.fullmatch(value) is None:
        raise Bm25ArtifactError(f"{location} must be a sha256 checksum")
    return value


def _validate_dictionary_manifest(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise Bm25ArtifactError("bm25 manifest dictionary must be an object")
    _require_exact_keys(value, expected=_DICTIONARY_KEYS, location="dictionary")
    if value["schema"] != DICTIONARY_SCHEMA:
        raise Bm25ArtifactError("unsupported BM25 dictionary schema")
    if (
        isinstance(value["entry_count"], bool)
        or not isinstance(value["entry_count"], int)
        or value["entry_count"] < 0
    ):
        raise Bm25ArtifactError("dictionary.entry_count must be non-negative")
    entries = value["entries"]
    if not isinstance(entries, list) or len(entries) != value["entry_count"]:
        raise Bm25ArtifactError("dictionary.entries must match dictionary.entry_count")
    previous = ""
    for index, entry in enumerate(entries):
        location = f"dictionary.entries[{index}]"
        if not isinstance(entry, dict):
            raise Bm25ArtifactError(f"{location} must be an object")
        _require_exact_keys(
            entry,
            expected=_DICTIONARY_ENTRY_KEYS,
            location=location,
        )
        term = entry["term"]
        if (
            not isinstance(term, str)
            or _HANGUL_TERM_RE.fullmatch(term) is None
            or term <= previous
        ):
            raise Bm25ArtifactError(
                "dictionary entries must have sorted unique Hangul terms"
            )
        previous = term
        if entry["pos"] != "NNP":
            raise Bm25ArtifactError(f"{location}.pos must be NNP")
        sources = entry["sources"]
        if not isinstance(sources, list) or not sources:
            raise Bm25ArtifactError(f"{location}.sources must be non-empty")
        for source_index, source in enumerate(sources):
            source_location = f"{location}.sources[{source_index}]"
            if not isinstance(source, dict):
                raise Bm25ArtifactError(f"{source_location} must be an object")
            _require_exact_keys(
                source,
                expected=_DICTIONARY_SOURCE_KEYS,
                location=source_location,
            )
            if source["kind"] not in {"alias", "seed", "tag"}:
                raise Bm25ArtifactError(f"{source_location}.kind is invalid")
            if not all(
                isinstance(source[field], str) and source[field]
                for field in ("evidence", "source")
            ):
                raise Bm25ArtifactError(
                    f"{source_location} evidence/source must be non-empty strings"
                )
    _require_checksum(value["sha256"], location="dictionary.sha256")
    _require_checksum(value["policy_sha256"], location="dictionary.policy_sha256")
    if not isinstance(value["policy_id"], str) or not value["policy_id"]:
        raise Bm25ArtifactError("dictionary.policy_id must be non-empty")
    return value


def _load_token_documents(
    index_root: Path,
    reference: object,
    *,
    corpus: Corpus,
    dictionary_checksum: str,
) -> tuple[tuple[DocId, ...], tuple[list[str], ...], str]:
    if not isinstance(reference, dict):
        raise Bm25ArtifactError("bm25 manifest tokens must be an object")
    _require_exact_keys(
        reference,
        expected=_TOKENS_REFERENCE_KEYS,
        location="tokens",
    )
    if reference["schema"] != BM25_TOKEN_SCHEMA:
        raise Bm25ArtifactError("unsupported BM25 token schema reference")
    expected_checksum = _require_checksum(
        reference["sha256"],
        location="tokens.sha256",
    )
    tokens_path = _artifact_path(
        index_root,
        reference["path"],
        expected="bm25/documents.json",
    )
    if content_checksum(tokens_path.read_bytes()) != expected_checksum:
        raise Bm25ArtifactError("BM25 token artifact checksum mismatch")
    payload = _read_json(tokens_path)
    _require_exact_keys(
        payload,
        expected=_TOKEN_ROOT_KEYS,
        location="BM25 token artifact",
    )
    if payload["schema"] != BM25_TOKEN_SCHEMA:
        raise Bm25ArtifactError("unsupported BM25 token artifact schema")
    if payload["corpus_fingerprint"] != corpus.fingerprint:
        raise Bm25ArtifactError("BM25 token artifact corpus fingerprint mismatch")
    if payload["dictionary_sha256"] != dictionary_checksum:
        raise Bm25ArtifactError("BM25 token artifact dictionary checksum mismatch")
    raw_documents = payload["documents"]
    if not isinstance(raw_documents, list):
        raise Bm25ArtifactError("BM25 token artifact documents must be an array")
    if isinstance(payload["document_count"], bool) or payload["document_count"] != len(
        raw_documents
    ):
        raise Bm25ArtifactError("BM25 token artifact document_count mismatch")
    doc_ids: list[DocId] = []
    token_documents: list[list[str]] = []
    for index, raw_document in enumerate(raw_documents):
        location = f"BM25 token artifact documents[{index}]"
        if not isinstance(raw_document, dict):
            raise Bm25ArtifactError(f"{location} must be an object")
        _require_exact_keys(
            raw_document,
            expected=_TOKEN_DOCUMENT_KEYS,
            location=location,
        )
        try:
            doc_id = DocId(raw_document["doc_id"])
        except (TypeError, ValueError) as exc:
            raise Bm25ArtifactError(f"{location}.doc_id is invalid") from exc
        tokens = raw_document["tokens"]
        if not isinstance(tokens, list) or not all(
            isinstance(token, str)
            and token
            and token.startswith((MORPHEME_NAMESPACE, SURFACE_NAMESPACE))
            for token in tokens
        ):
            raise Bm25ArtifactError(f"{location}.tokens are invalid")
        doc_ids.append(doc_id)
        token_documents.append(tokens)
    if tuple(doc_ids) != tuple(corpus.doc_ids()):
        raise Bm25ArtifactError(
            "BM25 token artifact DocIds do not exactly match the published corpus"
        )
    return tuple(doc_ids), tuple(token_documents), expected_checksum


class Bm25Retriever:
    """Load-only Retriever over the built Korean Kiwi/BM25 artifacts."""

    def __init__(self, corpus: Corpus) -> None:
        if not isinstance(corpus, PublishedCorpus):
            raise TypeError("Bm25Retriever requires a PublishedCorpus")
        _require_runtime_dependencies()
        index_root = corpus.index_root
        manifest_path = _artifact_path(
            index_root,
            "bm25/manifest.json",
            expected="bm25/manifest.json",
        )
        manifest = _read_json(manifest_path)
        _require_exact_keys(
            manifest,
            expected=_MANIFEST_KEYS,
            location="BM25 manifest",
        )
        if manifest["schema"] != BM25_MANIFEST_SCHEMA:
            raise Bm25ArtifactError("unsupported BM25 manifest schema")
        if manifest["method_id"] != BM25_METHOD_ID:
            raise Bm25ArtifactError("BM25 manifest method_id mismatch")
        if manifest["implementation_id"] != BM25_IMPLEMENTATION_ID:
            raise Bm25ArtifactError("BM25 manifest implementation_id mismatch")
        if canonical_config(manifest["config"]) != canonical_config(BM25_CONFIG):
            raise Bm25ArtifactError("BM25 manifest config mismatch")
        if manifest["corpus_fingerprint"] != corpus.fingerprint:
            raise Bm25ArtifactError("BM25 manifest corpus fingerprint mismatch")
        if isinstance(manifest["document_count"], bool) or manifest[
            "document_count"
        ] != len(corpus.doc_ids()):
            raise Bm25ArtifactError("BM25 manifest document_count mismatch")

        dictionary = _validate_dictionary_manifest(manifest["dictionary"])
        dictionary_checksum = _require_checksum(
            dictionary["sha256"],
            location="dictionary.sha256",
        )
        dictionary_path = _artifact_path(
            index_root,
            dictionary["path"],
            expected="kiwi-user-dictionary.txt",
        )
        if content_checksum(dictionary_path.read_bytes()) != dictionary_checksum:
            raise Bm25ArtifactError("BM25 dictionary checksum mismatch")
        self._tokenizer = _KiwiTokenizer(dictionary_path)
        doc_ids, token_documents, tokens_checksum = _load_token_documents(
            index_root,
            manifest["tokens"],
            corpus=corpus,
            dictionary_checksum=dictionary_checksum,
        )
        self._doc_ids = doc_ids
        self._token_documents = token_documents
        bm25_class = _import_bm25_class()
        self._ranker = (
            bm25_class(
                list(token_documents),
                k1=1.5,
                b=0.75,
                epsilon=0.25,
            )
            if token_documents
            else None
        )
        self._corpus = corpus
        self._identity_config = {
            "config": BM25_CONFIG,
            "corpus_fingerprint": corpus.fingerprint,
            "dictionary_policy_sha256": dictionary["policy_sha256"],
            "dictionary_sha256": dictionary_checksum,
            "kiwi_version": EXPECTED_KIWI_VERSION,
            "rank_bm25_version": EXPECTED_RANK_BM25_VERSION,
            "tokens_sha256": tokens_checksum,
        }

    @property
    def identity_config(self) -> dict[str, object]:
        return json.loads(canonical_config(self._identity_config))

    @property
    def fingerprint(self) -> str:
        return retriever_fingerprint(
            method_id=BM25_METHOD_ID,
            implementation_id=BM25_IMPLEMENTATION_ID,
            config=self._identity_config,
            corpus_fingerprint=self._corpus.fingerprint,
        )

    def tokenize(self, text: str) -> list[str]:
        """Expose the identical build/query token rule for audit tests."""

        return self._tokenizer.tokenize(text)

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0 or self._ranker is None:
            return Retrieval(query=query)
        query_tokens = self.tokenize(query)
        if not query_tokens:
            return Retrieval(query=query)
        scores = self._ranker.get_scores(query_tokens)
        ordered = sorted(
            (
                (float(score), doc_id)
                for doc_id, score in zip(self._doc_ids, scores, strict=True)
                if float(score) > 0.0
            ),
            key=lambda item: (-item[0], str(item[1])),
        )
        hits = tuple(
            Hit(doc_id=doc_id, rank=rank, score=score)
            for rank, (score, doc_id) in enumerate(ordered[:limit], start=1)
        )
        return Retrieval(query=query, hits=hits)


def create(
    corpus: Corpus,
    config: Mapping[str, object],
) -> Bm25Retriever:
    """Registry factory with an explicit, portable implementation configuration."""

    if canonical_config(config) != canonical_config(BM25_CONFIG):
        raise Bm25ArtifactError("registered BM25 config does not match implementation")
    return Bm25Retriever(corpus)


create_bm25 = create


def bm25_identity(
    corpus: Corpus,
    config: Mapping[str, object],
) -> Mapping[str, object]:
    """Resolve the same artifact identity used by an instantiated retriever."""

    return create(corpus, config).identity_config


registry.register(
    BM25_METHOD_ID,
    create,
    implementation_id=BM25_IMPLEMENTATION_ID,
    config=BM25_CONFIG,
    servable=True,
    identity_factory=bm25_identity,
)

__all__ = [
    "BM25_CONFIG",
    "BM25_IMPLEMENTATION_ID",
    "BM25_MANIFEST_SCHEMA",
    "BM25_METHOD_ID",
    "BM25_TOKEN_SCHEMA",
    "Bm25ArtifactError",
    "Bm25Retriever",
    "DictionaryEntry",
    "DictionaryPolicy",
    "DictionarySource",
    "build_bm25_artifacts",
    "bm25_identity",
    "collect_dictionary_evidence",
    "create",
    "create_bm25",
    "load_dictionary_policy",
]
