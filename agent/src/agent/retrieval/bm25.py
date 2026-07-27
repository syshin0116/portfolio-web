"""Deterministic Korean BM25 build artifacts and load-only runtime retrieval."""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import sqlite3
import tempfile
import threading
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
from agent.retrieval.protocol import Corpus, Hit, Retrieval
from agent.retrieval.registry import registry

if TYPE_CHECKING:
    from agent.retrieval.corpus_build import CorpusSnapshot, SourceDocument

BM25_METHOD_ID = "bm25"
BM25_IMPLEMENTATION_ID = "agent.retrieval.bm25:create@2"
BM25_MANIFEST_SCHEMA = "kiwi-bm25-manifest-v2"
BM25_FITTED_SCHEMA = "bm25-okapi-sqlite-v1"
DICTIONARY_SCHEMA = "kiwi-user-dictionary-v1"
DICTIONARY_EVIDENCE_SCHEMA = "kiwi-dictionary-evidence-v1"
DICTIONARY_POLICY_SCHEMA_VERSION = 1
EXPECTED_KIWI_VERSION = "0.23.2"
EXPECTED_KIWI_MODEL_VERSION = "0.23.0"
EXPECTED_RANK_BM25_VERSION = "0.2.2"
EXPECTED_NUMPY_VERSION = "2.4.4"
SQLITE_APPLICATION_ID = 0x424D3235
SQLITE_USER_VERSION = 1
SQLITE_PAGE_SIZE = 4096
MORPHEME_NAMESPACE = "m:"
SURFACE_NAMESPACE = "s:"
SURFACE_PATTERN = r"[0-9A-Za-z가-힣]+"
INDEXED_FIELDS = ("title", "description", "tags", "body")
K1 = 1.5
B = 0.75
EPSILON = 0.25

BM25_CONFIG: dict[str, object] = {
    "artifact_schema": BM25_MANIFEST_SCHEMA,
    "dictionary_evidence_schema": DICTIONARY_EVIDENCE_SCHEMA,
    "dictionary_schema": DICTIONARY_SCHEMA,
    "fields": list(INDEXED_FIELDS),
    "fitted_schema": BM25_FITTED_SCHEMA,
    "ranker": {
        "algorithm": "BM25Okapi",
        "b": B,
        "epsilon": EPSILON,
        "k1": K1,
        "package": "rank-bm25",
        "positive_scores_only": True,
        "version": EXPECTED_RANK_BM25_VERSION,
    },
    "tokenizer": {
        "keep_pos": ["NN*", "SL"],
        "load_default_dict": True,
        "load_multi_dict": False,
        "load_typo_dict": False,
        "model_package": "kiwipiepy-model",
        "model_type": "cong",
        "model_version": EXPECTED_KIWI_MODEL_VERSION,
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
BM25_CONFIG_SHA256 = content_checksum(canonical_config(BM25_CONFIG).encode("utf-8"))

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
        "evidence",
        "fitted",
        "implementation_id",
        "method_id",
        "schema",
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
_REFERENCE_KEYS = frozenset({"path", "schema", "sha256"})
_FITTED_REFERENCE_KEYS = frozenset({"path", "schema", "sha256", "sqlite_version"})
_EVIDENCE_KEYS = frozenset(
    {"candidate_count", "candidates", "corpus_fingerprint", "schema"}
)
_DICTIONARY_ENTRY_KEYS = frozenset({"pos", "sources", "term"})
_DICTIONARY_SOURCE_KEYS = frozenset({"evidence", "kind", "source"})
_EXPECTED_TABLE_COLUMNS = {
    "documents": (
        ("doc_index", "INTEGER", 0, 1),
        ("doc_id", "TEXT", 1, 0),
        ("doc_len", "INTEGER", 1, 0),
    ),
    "meta": (("key", "TEXT", 1, 1), ("value", "TEXT", 1, 0)),
    "postings": (
        ("term_id", "INTEGER", 1, 1),
        ("doc_index", "INTEGER", 1, 2),
        ("tf", "INTEGER", 1, 0),
    ),
    "terms": (
        ("term_id", "INTEGER", 0, 1),
        ("token", "TEXT", 1, 0),
        ("idf", "REAL", 1, 0),
    ),
}
_EXPECTED_INDEXES = {
    "documents": frozenset({(1, "u", 0, ("doc_id",))}),
    "meta": frozenset({(1, "pk", 0, ("key",))}),
    "postings": frozenset({(1, "pk", 0, ("term_id", "doc_index"))}),
    "terms": frozenset({(1, "u", 0, ("token",))}),
}
_EXPECTED_POSTING_FOREIGN_KEYS = frozenset(
    {
        ("documents", "doc_index", "doc_index", "NO ACTION", "NO ACTION", "NONE"),
        ("terms", "term_id", "term_id", "NO ACTION", "NO ACTION", "NONE"),
    }
)
_META_KEYS = frozenset(
    {
        "average_document_length",
        "average_idf",
        "b",
        "config_sha256",
        "corpus_fingerprint",
        "dictionary_sha256",
        "document_count",
        "epsilon",
        "evidence_sha256",
        "kiwi_model_version",
        "k1",
        "numpy_version",
        "policy_sha256",
        "posting_count",
        "rank_bm25_version",
        "schema",
        "sqlite_version",
        "term_count",
    }
)


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


@dataclass(frozen=True, slots=True)
class _Bm25Descriptor:
    dictionary_payload: bytes
    evidence_payload: bytes
    fitted_payload: bytes
    entries: tuple[DictionaryEntry, ...]
    identity: dict[str, object]


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


def _reject_json_constant(value: str) -> object:
    raise Bm25ArtifactError(f"non-finite JSON constant in BM25 artifact: {value}")


def _read_json_payload(payload: bytes, *, location: str) -> dict[str, object]:
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except Bm25ArtifactError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Bm25ArtifactError(f"cannot read BM25 artifact {location}: {exc}") from exc
    if not isinstance(value, dict):
        raise Bm25ArtifactError(f"BM25 artifact root must be an object: {location}")
    return value


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise Bm25ArtifactError(f"cannot checksum BM25 artifact {path}: {exc}") from exc
    return f"sha256:{digest.hexdigest()}"


def _require_checksum(value: object, *, location: str) -> str:
    if not isinstance(value, str) or _CHECKSUM_RE.fullmatch(value) is None:
        raise Bm25ArtifactError(f"{location} must be a sha256 checksum")
    return value


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
        type(schema_version) is not int
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
    return DictionaryPolicy(
        policy_id=policy_id,
        seeds=_policy_terms(value["seeds"], field="seeds"),
        deny=frozenset(_policy_terms(value["deny"], field="deny")),
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


def collect_dictionary_candidates(
    snapshot: CorpusSnapshot,
) -> tuple[DictionaryEntry, ...]:
    """Collect all tag/alias candidates for audit without activating them."""

    evidence: dict[str, set[DictionarySource]] = {}
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
            for match in _ALIAS_RE.finditer(unicodedata.normalize("NFC", text)):
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
    )


def select_dictionary_entries(
    candidates: Sequence[DictionaryEntry],
    policy: DictionaryPolicy,
) -> tuple[DictionaryEntry, ...]:
    """Activate only reviewed seeds, with deny taking precedence."""

    by_term = {entry.term: entry for entry in candidates}
    entries: list[DictionaryEntry] = []
    for term in policy.seeds:
        if term in policy.deny:
            continue
        candidate_sources = by_term.get(term)
        sources = set(candidate_sources.sources if candidate_sources else ())
        sources.add(
            DictionarySource(
                kind="seed",
                source=policy.policy_id,
                evidence=term,
            )
        )
        entries.append(DictionaryEntry(term=term, sources=tuple(sorted(sources))))
    return tuple(entries)


def collect_dictionary_evidence(
    snapshot: CorpusSnapshot,
    policy: DictionaryPolicy,
) -> tuple[DictionaryEntry, ...]:
    """Backward-compatible name for the reviewed active dictionary entries."""

    return select_dictionary_entries(collect_dictionary_candidates(snapshot), policy)


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


def _require_runtime_dependencies() -> None:
    _installed_version("kiwipiepy", expected=EXPECTED_KIWI_VERSION)
    _installed_version("kiwipiepy-model", expected=EXPECTED_KIWI_MODEL_VERSION)
    _installed_version("rank-bm25", expected=EXPECTED_RANK_BM25_VERSION)
    _installed_version("numpy", expected=EXPECTED_NUMPY_VERSION)


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


def _import_numpy() -> object:
    try:
        import numpy
    except ImportError as exc:
        raise Bm25ArtifactError("NumPy is unavailable") from exc
    return numpy


class _KiwiTokenizer:
    def __init__(
        self,
        dictionary_payload: bytes,
        entries: Sequence[DictionaryEntry] = (),
    ) -> None:
        _require_runtime_dependencies()
        try:
            kiwi_class = _import_kiwi_class()
            self._kiwi = kiwi_class(
                num_workers=1,
                model_type="cong",
                load_default_dict=True,
                load_typo_dict=False,
                load_multi_dict=False,
            )
            with tempfile.NamedTemporaryFile(
                prefix="verified-kiwi-dictionary-",
                suffix=".txt",
            ) as dictionary_file:
                dictionary_file.write(dictionary_payload)
                dictionary_file.flush()
                loaded = self._kiwi.load_user_dictionary(dictionary_file.name)
        except Bm25ArtifactError:
            raise
        except Exception as exc:
            raise Bm25ArtifactError(f"Kiwi user dictionary load failed: {exc}") from exc
        if type(loaded) is not int or loaded < 0:
            raise Bm25ArtifactError(
                "Kiwi user dictionary returned an invalid load count"
            )
        for entry in entries:
            try:
                analyzed = self._kiwi.tokenize(entry.term)
            except Exception as exc:
                raise Bm25ArtifactError(
                    f"Kiwi approved seed verification failed: {entry.term}: {exc}"
                ) from exc
            if (
                len(analyzed) != 1
                or _normalize(analyzed[0].form) != entry.term
                or analyzed[0].tag != "NNP"
            ):
                raise Bm25ArtifactError(
                    f"Kiwi approved seed must tokenize as one exact NNP: {entry.term}"
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


def _sqlite_float(value: float) -> str:
    if not math.isfinite(value):
        raise Bm25ArtifactError("BM25 fitted metadata cannot contain non-finite floats")
    return repr(float(value))


def _build_fitted_sqlite(
    path: Path,
    *,
    snapshot: CorpusSnapshot,
    token_documents: Sequence[Sequence[str]],
    corpus_fingerprint: str,
    dictionary_checksum: str,
    evidence_checksum: str,
    policy_checksum: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ranker = None
    if token_documents and any(token_documents):
        bm25_class = _import_bm25_class()
        ranker = bm25_class(
            list(token_documents),
            k1=K1,
            b=B,
            epsilon=EPSILON,
        )
        doc_lengths = tuple(int(value) for value in ranker.doc_len)
        average_document_length = float(ranker.avgdl)
        average_idf = float(ranker.average_idf)
        ordered_terms = tuple(ranker.idf.items())
        doc_frequencies = ranker.doc_freqs
    else:
        doc_lengths = tuple(len(tokens) for tokens in token_documents)
        average_document_length = 0.0
        average_idf = 0.0
        ordered_terms = ()
        doc_frequencies = tuple({} for _ in token_documents)

    term_ids = {token: term_id for term_id, (token, _) in enumerate(ordered_terms)}
    postings = sorted(
        (
            term_ids[token],
            doc_index,
            int(tf),
        )
        for doc_index, frequencies in enumerate(doc_frequencies)
        for token, tf in frequencies.items()
    )
    metadata = {
        "average_document_length": _sqlite_float(average_document_length),
        "average_idf": _sqlite_float(average_idf),
        "b": _sqlite_float(B),
        "config_sha256": BM25_CONFIG_SHA256,
        "corpus_fingerprint": corpus_fingerprint,
        "dictionary_sha256": dictionary_checksum,
        "document_count": str(len(snapshot.documents)),
        "epsilon": _sqlite_float(EPSILON),
        "evidence_sha256": evidence_checksum,
        "kiwi_model_version": EXPECTED_KIWI_MODEL_VERSION,
        "k1": _sqlite_float(K1),
        "numpy_version": EXPECTED_NUMPY_VERSION,
        "policy_sha256": policy_checksum,
        "posting_count": str(len(postings)),
        "rank_bm25_version": EXPECTED_RANK_BM25_VERSION,
        "schema": BM25_FITTED_SCHEMA,
        "sqlite_version": sqlite3.sqlite_version,
        "term_count": str(len(ordered_terms)),
    }
    try:
        connection = sqlite3.connect(path)
        connection.execute(f"PRAGMA page_size={SQLITE_PAGE_SIZE}")
        connection.execute("PRAGMA auto_vacuum=NONE")
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute(f"PRAGMA application_id={SQLITE_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version={SQLITE_USER_VERSION}")
        connection.executescript(
            """
            CREATE TABLE meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            ) WITHOUT ROWID;
            CREATE TABLE documents (
                doc_index INTEGER PRIMARY KEY
                    CHECK (typeof(doc_index) = 'integer' AND doc_index >= 0),
                doc_id TEXT NOT NULL UNIQUE,
                doc_len INTEGER NOT NULL
                    CHECK (typeof(doc_len) = 'integer' AND doc_len >= 0)
            );
            CREATE TABLE terms (
                term_id INTEGER PRIMARY KEY
                    CHECK (typeof(term_id) = 'integer' AND term_id >= 0),
                token TEXT NOT NULL UNIQUE,
                idf REAL NOT NULL
                    CHECK (typeof(idf) = 'real')
            );
            CREATE TABLE postings (
                term_id INTEGER NOT NULL,
                doc_index INTEGER NOT NULL,
                tf INTEGER NOT NULL CHECK (typeof(tf) = 'integer' AND tf > 0),
                PRIMARY KEY (term_id, doc_index),
                FOREIGN KEY (term_id) REFERENCES terms(term_id),
                FOREIGN KEY (doc_index) REFERENCES documents(doc_index)
            ) WITHOUT ROWID;
            """
        )
        connection.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            sorted(metadata.items()),
        )
        connection.executemany(
            "INSERT INTO documents(doc_index, doc_id, doc_len) VALUES (?, ?, ?)",
            (
                (index, str(document.doc_id), doc_lengths[index])
                for index, document in enumerate(snapshot.documents)
            ),
        )
        connection.executemany(
            "INSERT INTO terms(term_id, token, idf) VALUES (?, ?, ?)",
            (
                (term_id, token, float(idf))
                for term_id, (token, idf) in enumerate(ordered_terms)
            ),
        )
        connection.executemany(
            "INSERT INTO postings(term_id, doc_index, tf) VALUES (?, ?, ?)",
            postings,
        )
        connection.commit()
        connection.execute("VACUUM")
        connection.close()
    except (OSError, sqlite3.Error) as exc:
        raise Bm25ArtifactError(
            f"cannot build fitted BM25 SQLite artifact: {exc}"
        ) from exc
    finally:
        if "connection" in locals():
            connection.close()


def _identity_config(
    *,
    corpus_fingerprint: str,
    policy_checksum: str,
    dictionary_checksum: str,
    evidence_checksum: str,
    fitted_checksum: str,
    manifest_checksum: str,
    sqlite_version: str,
) -> dict[str, object]:
    return {
        "bm25_manifest_sha256": manifest_checksum,
        "config": BM25_CONFIG,
        "config_sha256": BM25_CONFIG_SHA256,
        "corpus_fingerprint": corpus_fingerprint,
        "dictionary_policy_sha256": policy_checksum,
        "dictionary_sha256": dictionary_checksum,
        "evidence_sha256": evidence_checksum,
        "fitted_sha256": fitted_checksum,
        "kiwi_model_version": EXPECTED_KIWI_MODEL_VERSION,
        "kiwi_version": EXPECTED_KIWI_VERSION,
        "numpy_version": EXPECTED_NUMPY_VERSION,
        "rank_bm25_version": EXPECTED_RANK_BM25_VERSION,
        "sqlite_version": sqlite_version,
    }


def build_bm25_artifacts(
    snapshot: CorpusSnapshot,
    *,
    index_root: Path,
    policy_path: Path | str,
    corpus_fingerprint: str,
) -> str:
    """Fit BM25 once from one snapshot and emit deterministic safe artifacts."""

    _require_runtime_dependencies()
    policy = load_dictionary_policy(policy_path)
    candidates = collect_dictionary_candidates(snapshot)
    entries = select_dictionary_entries(candidates, policy)

    evidence_payload = {
        "candidate_count": len(candidates),
        "candidates": [entry.as_dict() for entry in candidates],
        "corpus_fingerprint": corpus_fingerprint,
        "schema": DICTIONARY_EVIDENCE_SCHEMA,
    }
    evidence_path = index_root / "bm25" / "dictionary-evidence.json"
    _write_json(evidence_path, evidence_payload)
    evidence_checksum = content_checksum(evidence_path.read_bytes())

    dictionary_path = index_root / "kiwi-user-dictionary.txt"
    dictionary_payload = _dictionary_bytes(
        entries,
        corpus_fingerprint=corpus_fingerprint,
    )
    dictionary_path.write_bytes(dictionary_payload)
    dictionary_checksum = content_checksum(dictionary_payload)
    tokenizer = _KiwiTokenizer(dictionary_payload, entries)
    token_documents = [
        _document_tokens(document, tokenizer=tokenizer)
        for document in snapshot.documents
    ]

    fitted_path = index_root / "bm25" / "fitted.sqlite3"
    _build_fitted_sqlite(
        fitted_path,
        snapshot=snapshot,
        token_documents=token_documents,
        corpus_fingerprint=corpus_fingerprint,
        dictionary_checksum=dictionary_checksum,
        evidence_checksum=evidence_checksum,
        policy_checksum=policy.checksum,
    )
    fitted_checksum = _file_checksum(fitted_path)
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
        "evidence": {
            "path": "bm25/dictionary-evidence.json",
            "schema": DICTIONARY_EVIDENCE_SCHEMA,
            "sha256": evidence_checksum,
        },
        "fitted": {
            "path": "bm25/fitted.sqlite3",
            "schema": BM25_FITTED_SCHEMA,
            "sha256": fitted_checksum,
            "sqlite_version": sqlite3.sqlite_version,
        },
        "implementation_id": BM25_IMPLEMENTATION_ID,
        "method_id": BM25_METHOD_ID,
        "schema": BM25_MANIFEST_SCHEMA,
    }
    manifest_path = index_root / "bm25" / "manifest.json"
    _write_json(manifest_path, manifest)
    identity = _identity_config(
        corpus_fingerprint=corpus_fingerprint,
        policy_checksum=policy.checksum,
        dictionary_checksum=dictionary_checksum,
        evidence_checksum=evidence_checksum,
        fitted_checksum=fitted_checksum,
        manifest_checksum=_file_checksum(manifest_path),
        sqlite_version=sqlite3.sqlite_version,
    )
    return retriever_fingerprint(
        method_id=BM25_METHOD_ID,
        implementation_id=BM25_IMPLEMENTATION_ID,
        config=identity,
        corpus_fingerprint=corpus_fingerprint,
    )


def _parse_dictionary_sources(
    value: object,
    *,
    location: str,
    allowed_kinds: frozenset[str],
) -> tuple[DictionarySource, ...]:
    if not isinstance(value, list) or not value:
        raise Bm25ArtifactError(f"{location} must be a non-empty array")
    sources: list[DictionarySource] = []
    for index, raw_source in enumerate(value):
        source_location = f"{location}[{index}]"
        if not isinstance(raw_source, dict):
            raise Bm25ArtifactError(f"{source_location} must be an object")
        _require_exact_keys(
            raw_source,
            expected=_DICTIONARY_SOURCE_KEYS,
            location=source_location,
        )
        kind = raw_source["kind"]
        source = raw_source["source"]
        evidence = raw_source["evidence"]
        if kind not in allowed_kinds:
            raise Bm25ArtifactError(f"{source_location}.kind is invalid")
        if not isinstance(source, str) or not source:
            raise Bm25ArtifactError(f"{source_location}.source must be non-empty")
        if not isinstance(evidence, str) or not evidence:
            raise Bm25ArtifactError(f"{source_location}.evidence must be non-empty")
        sources.append(DictionarySource(kind=kind, source=source, evidence=evidence))
    result = tuple(sources)
    if result != tuple(sorted(set(result))):
        raise Bm25ArtifactError(f"{location} must be sorted and unique")
    return result


def _parse_dictionary_entries(
    value: object,
    *,
    location: str,
    allowed_kinds: frozenset[str],
) -> tuple[DictionaryEntry, ...]:
    if not isinstance(value, list):
        raise Bm25ArtifactError(f"{location} must be an array")
    entries: list[DictionaryEntry] = []
    for index, raw_entry in enumerate(value):
        entry_location = f"{location}[{index}]"
        if not isinstance(raw_entry, dict):
            raise Bm25ArtifactError(f"{entry_location} must be an object")
        _require_exact_keys(
            raw_entry,
            expected=_DICTIONARY_ENTRY_KEYS,
            location=entry_location,
        )
        term = raw_entry["term"]
        if (
            not isinstance(term, str)
            or term != _normalize(term)
            or _HANGUL_TERM_RE.fullmatch(term) is None
        ):
            raise Bm25ArtifactError(f"{entry_location}.term is invalid")
        if raw_entry["pos"] != "NNP":
            raise Bm25ArtifactError(f"{entry_location}.pos must be NNP")
        entries.append(
            DictionaryEntry(
                term=term,
                sources=_parse_dictionary_sources(
                    raw_entry["sources"],
                    location=f"{entry_location}.sources",
                    allowed_kinds=allowed_kinds,
                ),
            )
        )
    result = tuple(entries)
    terms = tuple(entry.term for entry in result)
    if terms != tuple(sorted(set(terms))):
        raise Bm25ArtifactError(
            f"{location} must have sorted unique normalized Hangul terms"
        )
    return result


def _parse_reference(
    value: object,
    *,
    location: str,
    expected_path: str,
    expected_schema: str,
) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise Bm25ArtifactError(f"{location} must be an object")
    _require_exact_keys(value, expected=_REFERENCE_KEYS, location=location)
    if value["path"] != expected_path:
        raise Bm25ArtifactError(f"{location}.path must be {expected_path!r}")
    if value["schema"] != expected_schema:
        raise Bm25ArtifactError(f"{location}.schema is unsupported")
    return expected_path, _require_checksum(
        value["sha256"],
        location=f"{location}.sha256",
    )


def _load_descriptor(corpus: Corpus) -> _Bm25Descriptor:
    if not isinstance(corpus, PublishedCorpus):
        raise TypeError("Bm25Retriever requires a PublishedCorpus")
    manifest_payload = corpus.read_artifact("bm25/manifest.json")
    manifest = _read_json_payload(
        manifest_payload,
        location="bm25/manifest.json",
    )
    _require_exact_keys(manifest, expected=_MANIFEST_KEYS, location="BM25 manifest")
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
    if type(manifest["document_count"]) is not int or manifest["document_count"] != len(
        corpus.doc_ids()
    ):
        raise Bm25ArtifactError("BM25 manifest document_count mismatch")

    raw_dictionary = manifest["dictionary"]
    if not isinstance(raw_dictionary, dict):
        raise Bm25ArtifactError("BM25 manifest dictionary must be an object")
    _require_exact_keys(
        raw_dictionary,
        expected=_DICTIONARY_KEYS,
        location="dictionary",
    )
    if raw_dictionary["schema"] != DICTIONARY_SCHEMA:
        raise Bm25ArtifactError("unsupported BM25 dictionary schema")
    if (
        not isinstance(raw_dictionary["policy_id"], str)
        or not raw_dictionary["policy_id"]
    ):
        raise Bm25ArtifactError("dictionary.policy_id must be non-empty")
    policy_checksum = _require_checksum(
        raw_dictionary["policy_sha256"],
        location="dictionary.policy_sha256",
    )
    dictionary_checksum = _require_checksum(
        raw_dictionary["sha256"],
        location="dictionary.sha256",
    )
    entries = _parse_dictionary_entries(
        raw_dictionary["entries"],
        location="dictionary.entries",
        allowed_kinds=frozenset({"alias", "seed", "tag"}),
    )
    if type(raw_dictionary["entry_count"]) is not int or raw_dictionary[
        "entry_count"
    ] != len(entries):
        raise Bm25ArtifactError("dictionary.entry_count must match dictionary.entries")
    expected_seed_sources = tuple(
        DictionarySource(
            kind="seed",
            source=raw_dictionary["policy_id"],
            evidence=entry.term,
        )
        for entry in entries
    )
    for entry, seed_source in zip(entries, expected_seed_sources, strict=True):
        actual_seed_sources = {
            source for source in entry.sources if source.kind == "seed"
        }
        if actual_seed_sources != {seed_source}:
            raise Bm25ArtifactError(
                "dictionary entry must have exactly one reviewed seed provenance: "
                f"{entry.term}"
            )
    if raw_dictionary["path"] != "kiwi-user-dictionary.txt":
        raise Bm25ArtifactError("BM25 artifact path must be 'kiwi-user-dictionary.txt'")
    dictionary_payload = corpus.read_artifact("kiwi-user-dictionary.txt")
    if content_checksum(dictionary_payload) != dictionary_checksum:
        raise Bm25ArtifactError("BM25 dictionary checksum mismatch")
    if dictionary_payload != _dictionary_bytes(
        entries,
        corpus_fingerprint=corpus.fingerprint,
    ):
        raise Bm25ArtifactError(
            "BM25 dictionary bytes do not match canonical manifest entries"
        )

    evidence_relative, evidence_checksum = _parse_reference(
        manifest["evidence"],
        location="evidence",
        expected_path="bm25/dictionary-evidence.json",
        expected_schema=DICTIONARY_EVIDENCE_SCHEMA,
    )
    evidence_payload = corpus.read_artifact(evidence_relative)
    if content_checksum(evidence_payload) != evidence_checksum:
        raise Bm25ArtifactError("BM25 evidence checksum mismatch")

    fitted = manifest["fitted"]
    if not isinstance(fitted, dict):
        raise Bm25ArtifactError("fitted must be an object")
    _require_exact_keys(fitted, expected=_FITTED_REFERENCE_KEYS, location="fitted")
    if fitted["path"] != "bm25/fitted.sqlite3":
        raise Bm25ArtifactError("fitted.path must be 'bm25/fitted.sqlite3'")
    if fitted["schema"] != BM25_FITTED_SCHEMA:
        raise Bm25ArtifactError("unsupported BM25 fitted schema")
    fitted_checksum = _require_checksum(
        fitted["sha256"],
        location="fitted.sha256",
    )
    if fitted["sqlite_version"] != sqlite3.sqlite_version:
        raise Bm25ArtifactError(
            "BM25 fitted SQLite version differs from the runtime version"
        )
    fitted_payload = corpus.read_artifact("bm25/fitted.sqlite3")
    if content_checksum(fitted_payload) != fitted_checksum:
        raise Bm25ArtifactError("BM25 fitted artifact checksum mismatch")
    identity = _identity_config(
        corpus_fingerprint=corpus.fingerprint,
        policy_checksum=policy_checksum,
        dictionary_checksum=dictionary_checksum,
        evidence_checksum=evidence_checksum,
        fitted_checksum=fitted_checksum,
        manifest_checksum=content_checksum(manifest_payload),
        sqlite_version=fitted["sqlite_version"],
    )
    return _Bm25Descriptor(
        dictionary_payload=dictionary_payload,
        evidence_payload=evidence_payload,
        fitted_payload=fitted_payload,
        entries=entries,
        identity=identity,
    )


def _validate_evidence(descriptor: _Bm25Descriptor, *, corpus: Corpus) -> None:
    evidence = _read_json_payload(
        descriptor.evidence_payload,
        location="bm25/dictionary-evidence.json",
    )
    if descriptor.evidence_payload != _json_bytes(evidence):
        raise Bm25ArtifactError("BM25 dictionary evidence is not canonical JSON")
    _require_exact_keys(
        evidence,
        expected=_EVIDENCE_KEYS,
        location="dictionary evidence",
    )
    if evidence["schema"] != DICTIONARY_EVIDENCE_SCHEMA:
        raise Bm25ArtifactError("unsupported BM25 dictionary evidence schema")
    if evidence["corpus_fingerprint"] != corpus.fingerprint:
        raise Bm25ArtifactError("BM25 evidence corpus fingerprint mismatch")
    candidates = _parse_dictionary_entries(
        evidence["candidates"],
        location="dictionary evidence.candidates",
        allowed_kinds=frozenset({"alias", "tag"}),
    )
    if type(evidence["candidate_count"]) is not int or evidence[
        "candidate_count"
    ] != len(candidates):
        raise Bm25ArtifactError(
            "dictionary evidence candidate_count must match candidates"
        )
    candidate_sources = {entry.term: set(entry.sources) for entry in candidates}
    for entry in descriptor.entries:
        non_seed_sources = {source for source in entry.sources if source.kind != "seed"}
        if non_seed_sources != candidate_sources.get(entry.term, set()):
            raise Bm25ArtifactError(
                f"dictionary provenance differs from evidence: {entry.term}"
            )


def _snapshot_connection(payload: bytes) -> sqlite3.Connection:
    """Deserialize verified fitted bytes into one private immutable snapshot."""

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.enable_load_extension(False)
        connection.deserialize(payload)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA mmap_size=0")
        connection.execute("PRAGMA cache_size=-2048")
        return connection
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise Bm25ArtifactError(
            f"cannot deserialize fitted BM25 SQLite artifact: {exc}"
        ) from exc


def _canonical_int(value: str, *, location: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise Bm25ArtifactError(f"{location} must be a canonical integer") from exc
    if parsed < 0 or str(parsed) != value:
        raise Bm25ArtifactError(f"{location} must be a canonical non-negative integer")
    return parsed


def _canonical_float(value: str, *, location: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise Bm25ArtifactError(f"{location} must be a canonical float") from exc
    if not math.isfinite(parsed) or repr(parsed) != value:
        raise Bm25ArtifactError(f"{location} must be a canonical finite float")
    return parsed


def _validate_fitted(
    descriptor: _Bm25Descriptor,
    *,
    corpus: Corpus,
    connection: sqlite3.Connection,
) -> tuple[object, float]:
    numpy = _import_numpy()
    try:
        if (
            connection.execute("PRAGMA application_id").fetchone()[0]
            != SQLITE_APPLICATION_ID
        ):
            raise Bm25ArtifactError("BM25 fitted application_id mismatch")
        if (
            connection.execute("PRAGMA user_version").fetchone()[0]
            != SQLITE_USER_VERSION
        ):
            raise Bm25ArtifactError("BM25 fitted user_version mismatch")
        if connection.execute("PRAGMA page_size").fetchone()[0] != SQLITE_PAGE_SIZE:
            raise Bm25ArtifactError("BM25 fitted page_size mismatch")
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise Bm25ArtifactError("BM25 fitted SQLite integrity check failed")
        objects = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT type, name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        expected_objects = {("table", name) for name in _EXPECTED_TABLE_COLUMNS}
        if objects != expected_objects:
            raise Bm25ArtifactError(
                "BM25 fitted SQLite schema contains unknown objects"
            )
        for table, expected_columns in _EXPECTED_TABLE_COLUMNS.items():
            columns = tuple(
                (row[1], row[2], row[3], row[5])
                for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if columns != expected_columns:
                raise Bm25ArtifactError(f"BM25 fitted SQLite {table} columns mismatch")
            indexes = set()
            for row in connection.execute(f"PRAGMA index_list({table})"):
                _, index_name, unique, origin, partial = row
                escaped_name = index_name.replace('"', '""')
                indexed_columns = tuple(
                    index_row[2]
                    for index_row in connection.execute(
                        f'PRAGMA index_info("{escaped_name}")'
                    )
                )
                indexes.add((unique, origin, partial, indexed_columns))
            if indexes != _EXPECTED_INDEXES[table]:
                raise Bm25ArtifactError(
                    f"BM25 fitted SQLite {table} index constraints mismatch"
                )
            foreign_keys = {
                (row[2], row[3], row[4], row[5], row[6], row[7])
                for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            }
            expected_foreign_keys = (
                _EXPECTED_POSTING_FOREIGN_KEYS if table == "postings" else frozenset()
            )
            if foreign_keys != expected_foreign_keys:
                raise Bm25ArtifactError(
                    f"BM25 fitted SQLite {table} foreign keys mismatch"
                )

        metadata_rows = connection.execute(
            "SELECT key, value, typeof(key), typeof(value) FROM meta ORDER BY key"
        ).fetchall()
        if not all(row[2:] == ("text", "text") for row in metadata_rows):
            raise Bm25ArtifactError("BM25 fitted metadata values must be text")
        metadata = {row[0]: row[1] for row in metadata_rows}
        if set(metadata) != _META_KEYS or len(metadata) != len(metadata_rows):
            raise Bm25ArtifactError("BM25 fitted metadata keys mismatch")
        expected_metadata = {
            "config_sha256": BM25_CONFIG_SHA256,
            "corpus_fingerprint": corpus.fingerprint,
            "dictionary_sha256": descriptor.identity["dictionary_sha256"],
            "evidence_sha256": descriptor.identity["evidence_sha256"],
            "kiwi_model_version": EXPECTED_KIWI_MODEL_VERSION,
            "numpy_version": EXPECTED_NUMPY_VERSION,
            "policy_sha256": descriptor.identity["dictionary_policy_sha256"],
            "rank_bm25_version": EXPECTED_RANK_BM25_VERSION,
            "schema": BM25_FITTED_SCHEMA,
            "sqlite_version": sqlite3.sqlite_version,
        }
        for key, expected in expected_metadata.items():
            if metadata[key] != expected:
                raise Bm25ArtifactError(f"BM25 fitted metadata {key} mismatch")
        document_count = _canonical_int(
            metadata["document_count"],
            location="fitted document_count",
        )
        term_count = _canonical_int(
            metadata["term_count"],
            location="fitted term_count",
        )
        posting_count = _canonical_int(
            metadata["posting_count"],
            location="fitted posting_count",
        )
        average_document_length = _canonical_float(
            metadata["average_document_length"],
            location="fitted average_document_length",
        )
        stored_average_idf = _canonical_float(
            metadata["average_idf"],
            location="fitted average_idf",
        )
        if _canonical_float(metadata["k1"], location="fitted k1") != K1:
            raise Bm25ArtifactError("BM25 fitted k1 mismatch")
        if _canonical_float(metadata["b"], location="fitted b") != B:
            raise Bm25ArtifactError("BM25 fitted b mismatch")
        if _canonical_float(metadata["epsilon"], location="fitted epsilon") != EPSILON:
            raise Bm25ArtifactError("BM25 fitted epsilon mismatch")
        if document_count != len(corpus.doc_ids()):
            raise Bm25ArtifactError("BM25 fitted document_count mismatch")

        document_rows = connection.execute(
            "SELECT doc_index, doc_id, doc_len, "
            "typeof(doc_index), typeof(doc_id), typeof(doc_len) "
            "FROM documents ORDER BY doc_index"
        ).fetchall()
        if len(document_rows) != document_count:
            raise Bm25ArtifactError("BM25 fitted documents count mismatch")
        if not all(row[3:] == ("integer", "text", "integer") for row in document_rows):
            raise Bm25ArtifactError("BM25 fitted document types are invalid")
        if tuple(row[0] for row in document_rows) != tuple(range(document_count)):
            raise Bm25ArtifactError("BM25 fitted document indices must be contiguous")
        if tuple(row[1] for row in document_rows) != tuple(map(str, corpus.doc_ids())):
            raise Bm25ArtifactError(
                "BM25 fitted DocIds do not exactly match the published corpus"
            )
        duplicate_doc_id = connection.execute(
            "SELECT 1 FROM documents GROUP BY doc_id HAVING COUNT(*) != 1 LIMIT 1"
        ).fetchone()
        if duplicate_doc_id is not None:
            raise Bm25ArtifactError("BM25 fitted document DocIds must be unique")
        if any(row[2] < 0 for row in document_rows):
            raise Bm25ArtifactError("BM25 fitted doc_len must be non-negative")
        doc_lengths = numpy.array([row[2] for row in document_rows])
        expected_avgdl = (
            float(sum(row[2] for row in document_rows)) / document_count
            if document_count
            else 0.0
        )
        if average_document_length != expected_avgdl:
            raise Bm25ArtifactError("BM25 fitted average document length mismatch")

        term_query = (
            "SELECT t.term_id, t.token, t.idf, typeof(t.term_id), "
            "typeof(t.token), typeof(t.idf), COUNT(p.doc_index) "
            "FROM terms AS t LEFT JOIN postings AS p USING(term_id) "
            "GROUP BY t.term_id ORDER BY t.term_id"
        )
        idf_sum = 0.0
        seen_terms = 0
        for index, row in enumerate(connection.execute(term_query)):
            term_id, token, idf, id_type, token_type, idf_type, doc_frequency = row
            if term_id != index or (id_type, token_type, idf_type) != (
                "integer",
                "text",
                "real",
            ):
                raise Bm25ArtifactError("BM25 fitted term indices/types are invalid")
            valid_token = isinstance(token, str) and token == _normalize(token)
            if valid_token and token.startswith(MORPHEME_NAMESPACE):
                valid_token = bool(token.removeprefix(MORPHEME_NAMESPACE))
            elif valid_token and token.startswith(SURFACE_NAMESPACE):
                valid_token = (
                    _SURFACE_RE.fullmatch(token.removeprefix(SURFACE_NAMESPACE))
                    is not None
                )
            else:
                valid_token = False
            if not valid_token or not math.isfinite(idf):
                raise Bm25ArtifactError(f"BM25 fitted token/idf is invalid: {token!r}")
            if doc_frequency <= 0 or doc_frequency > document_count:
                raise Bm25ArtifactError(
                    f"BM25 fitted token has invalid document frequency: {token!r}"
                )
            raw_idf = math.log(document_count - doc_frequency + 0.5) - math.log(
                doc_frequency + 0.5
            )
            # rank-bm25 0.2.2 uses sequential ``+=`` in first-seen term order.
            idf_sum += raw_idf
            seen_terms += 1
        if seen_terms != term_count:
            raise Bm25ArtifactError("BM25 fitted term count mismatch")
        duplicate_token = connection.execute(
            "SELECT 1 FROM terms GROUP BY token HAVING COUNT(*) != 1 LIMIT 1"
        ).fetchone()
        if duplicate_token is not None:
            raise Bm25ArtifactError("BM25 fitted term tokens must be unique")
        average_idf = idf_sum / seen_terms if seen_terms else 0.0
        if average_idf != stored_average_idf:
            raise Bm25ArtifactError("BM25 fitted average IDF mismatch")
        for _, _, stored_idf, _, _, _, doc_frequency in connection.execute(term_query):
            raw_idf = math.log(document_count - doc_frequency + 0.5) - math.log(
                doc_frequency + 0.5
            )
            expected_idf = EPSILON * average_idf if raw_idf < 0 else raw_idf
            if stored_idf != expected_idf:
                raise Bm25ArtifactError("BM25 fitted term IDF mismatch")

        actual_posting_count = connection.execute(
            "SELECT COUNT(*) FROM postings"
        ).fetchone()[0]
        if actual_posting_count != posting_count:
            raise Bm25ArtifactError("BM25 fitted posting count mismatch")
        duplicate_posting = connection.execute(
            "SELECT 1 FROM postings GROUP BY term_id, doc_index "
            "HAVING COUNT(*) != 1 LIMIT 1"
        ).fetchone()
        if duplicate_posting is not None:
            raise Bm25ArtifactError("BM25 fitted postings must be unique")
        invalid_postings = connection.execute(
            "SELECT COUNT(*) FROM postings AS p "
            "LEFT JOIN terms AS t ON t.term_id = p.term_id "
            "LEFT JOIN documents AS d ON d.doc_index = p.doc_index "
            "WHERE typeof(p.term_id) != 'integer' "
            "OR typeof(p.doc_index) != 'integer' "
            "OR typeof(p.tf) != 'integer' OR p.tf <= 0 "
            "OR t.term_id IS NULL OR d.doc_index IS NULL"
        ).fetchone()[0]
        if invalid_postings:
            raise Bm25ArtifactError("BM25 fitted postings are invalid")
        length_rows = dict(
            connection.execute(
                "SELECT doc_index, SUM(tf) FROM postings GROUP BY doc_index"
            )
        )
        if any(
            length_rows.get(doc_index, 0) != doc_len
            for doc_index, _, doc_len, *_ in document_rows
        ):
            raise Bm25ArtifactError(
                "BM25 fitted document lengths do not match posting frequencies"
            )
        return doc_lengths, average_document_length
    except sqlite3.Error as exc:
        raise Bm25ArtifactError(f"cannot validate fitted BM25 SQLite: {exc}") from exc


class Bm25Retriever:
    """Load-only Retriever over fitted Korean Kiwi/BM25 artifacts."""

    def __init__(self, corpus: Corpus) -> None:
        _require_runtime_dependencies()
        descriptor = _load_descriptor(corpus)
        _validate_evidence(descriptor, corpus=corpus)
        connection = _snapshot_connection(descriptor.fitted_payload)
        try:
            doc_lengths, average_document_length = _validate_fitted(
                descriptor,
                corpus=corpus,
                connection=connection,
            )
            tokenizer = _KiwiTokenizer(
                descriptor.dictionary_payload,
                descriptor.entries,
            )
        except BaseException:
            connection.close()
            raise
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = connection
        self._tokenizer = tokenizer
        self._corpus = corpus
        self._doc_ids = tuple(corpus.doc_ids())
        self._doc_lengths = doc_lengths
        self._average_document_length = average_document_length
        self._identity_config = descriptor.identity

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

        with self._lock:
            self._require_open()
            return self._tokenizer.tokenize(text)

    def _require_open(self) -> sqlite3.Connection:
        connection = self._connection
        if connection is None:
            raise RuntimeError("BM25 retriever is closed")
        return connection

    def close(self) -> None:
        """Release the private SQLite snapshot; repeated closes are harmless."""

        with self._lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                connection.close()

    def __enter__(self) -> Bm25Retriever:
        self._require_open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.close()

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        with self._lock:
            connection = self._require_open()
            if limit == 0 or not self._doc_ids:
                return Retrieval(query=query)
            query_tokens = self._tokenizer.tokenize(query)
            if not query_tokens:
                return Retrieval(query=query)
            numpy = _import_numpy()
            scores = numpy.zeros(len(self._doc_ids))
            try:
                for token in query_tokens:
                    rows = connection.execute(
                        "SELECT t.idf, p.doc_index, p.tf "
                        "FROM terms AS t JOIN postings AS p USING(term_id) "
                        "WHERE t.token = ? ORDER BY p.doc_index",
                        (token,),
                    ).fetchall()
                    if not rows:
                        continue
                    idf = rows[0][0]
                    q_freq = numpy.zeros(len(self._doc_ids), dtype=numpy.int_)
                    for row_idf, doc_index, tf in rows:
                        if row_idf != idf:
                            raise Bm25ArtifactError(
                                "BM25 fitted postings contain inconsistent IDF values"
                            )
                        q_freq[doc_index] = tf
                    scores += idf * (
                        q_freq
                        * (K1 + 1)
                        / (
                            q_freq
                            + K1
                            * (
                                1
                                - B
                                + B * self._doc_lengths / self._average_document_length
                            )
                        )
                    )
                ordered = sorted(
                    (
                        (float(score), doc_id)
                        for doc_id, score in zip(self._doc_ids, scores, strict=True)
                        if float(score) > 0.0
                    ),
                    key=lambda item: (-item[0], str(item[1])),
                )
            except sqlite3.Error as exc:
                raise Bm25ArtifactError(f"BM25 fitted query failed: {exc}") from exc
        return Retrieval(
            query=query,
            hits=tuple(
                Hit(doc_id=doc_id, rank=rank, score=score)
                for rank, (score, doc_id) in enumerate(ordered[:limit], start=1)
            ),
        )


def create(
    corpus: Corpus,
    config: Mapping[str, object],
) -> Bm25Retriever:
    """Registry factory with an explicit portable implementation configuration."""

    if canonical_config(config) != canonical_config(BM25_CONFIG):
        raise Bm25ArtifactError("registered BM25 config does not match implementation")
    return Bm25Retriever(corpus)


create_bm25 = create


def bm25_identity(
    corpus: Corpus,
    config: Mapping[str, object],
) -> Mapping[str, object]:
    """Resolve checksummed artifact identity without constructing a retriever."""

    if canonical_config(config) != canonical_config(BM25_CONFIG):
        raise Bm25ArtifactError("registered BM25 config does not match implementation")
    return _load_descriptor(corpus).identity


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
    "BM25_FITTED_SCHEMA",
    "BM25_IMPLEMENTATION_ID",
    "BM25_MANIFEST_SCHEMA",
    "BM25_METHOD_ID",
    "Bm25ArtifactError",
    "Bm25Retriever",
    "DICTIONARY_EVIDENCE_SCHEMA",
    "DictionaryEntry",
    "DictionaryPolicy",
    "DictionarySource",
    "build_bm25_artifacts",
    "bm25_identity",
    "collect_dictionary_candidates",
    "collect_dictionary_evidence",
    "create",
    "create_bm25",
    "load_dictionary_policy",
    "select_dictionary_entries",
]
