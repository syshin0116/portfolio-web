"""Bounded RAG inspection events for the native LangGraph/Aegra stream.

The emitter writes one internal envelope through LangGraph's ``StreamWriter``.
``InspectionEventTransformer`` then promotes only a validated envelope to the
named ``custom:syshin.rag.inspection.v1`` v3 channel. Aegra owns the final
Agent Protocol ``custom`` event projection; this module does not implement an
HTTP or SSE transport.

Only retrieval observations are accepted today. QuickJS and subagent variants
remain absent until those capabilities can provide real status, timing, and
budget measurements.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from langgraph.prebuilt import ToolRuntime
from langgraph.stream import ProtocolEvent, StreamTransformer

from agent.retrieval.protocol import Retrieval

if TYPE_CHECKING:
    from agent.retrieval.registry import ResolvedRetriever
    from agent.retrieval.serving import ServingRuntime

INSPECTION_EVENT_NAME = "syshin.rag.inspection.v1"
INSPECTION_SCHEMA_VERSION = 1

MAX_EVENT_BYTES = 65_536
MAX_QUERY_CHARACTERS = 1_000
MAX_SOURCE_COUNT = 50
MAX_SOURCE_DOC_ID_CHARACTERS = 1_000
MAX_SOURCE_TITLE_CHARACTERS = 300
MAX_CHUNK_ID_CHARACTERS = 256
MAX_TOOL_CALL_ID_CHARACTERS = 256
MAX_METHOD_ID_CHARACTERS = 128
MAX_IMPLEMENTATION_ID_CHARACTERS = 256
MAX_FINGERPRINT_CHARACTERS = 256
MAX_STAGE_COUNT = 16
MAX_ELAPSED_MS = 86_400_000.0
MAX_HIT_COUNT = 10_000
MAX_CORPUS_DOCUMENT_COUNT = 1_000_000

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_PAYLOAD_KEYS = frozenset(
    {
        "corpus_document_count",
        "corpus_revision",
        "hit_count",
        "kind",
        "method_id",
        "method_identity",
        "query",
        "query_truncated",
        "schema_version",
        "sources",
        "sources_truncated",
        "stages",
        "tool_call_id",
    }
)
_METHOD_IDENTITY_KEYS = frozenset(
    {"fingerprint", "implementation_id", "method_id"}
)
_SOURCE_REQUIRED_KEYS = frozenset(
    {"doc_id", "provenance", "rank", "title"}
)
_SOURCE_OPTIONAL_KEYS = frozenset({"chunk_id", "score"})
_PROVENANCE_KEYS = frozenset(
    {"corpus_revision", "kind", "retriever_fingerprint"}
)
_STAGE_KEYS = frozenset(
    {
        "application",
        "elapsed_ms",
        "fingerprint",
        "implementation_id",
        "stage_id",
    }
)
_APPLICATION_KEYS = frozenset(
    {"input_count", "output_count", "status"}
)
_ENVELOPE_KEYS = frozenset({"name", "payload"})


class InspectionContractError(ValueError):
    """An inspection payload would violate the public event contract."""


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise InspectionContractError(f"{field} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise InspectionContractError(f"{field} keys must be strings")
    return value


def _exact_keys(
    value: Mapping[str, object],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    field: str,
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing:
        raise InspectionContractError(
            f"{field} is missing required fields: {', '.join(missing)}"
        )
    if unknown:
        raise InspectionContractError(
            f"{field} contains unknown fields: {', '.join(unknown)}"
        )


def _string(
    value: object,
    *,
    field: str,
    maximum: int,
    require_trimmed: bool = True,
) -> str:
    if not isinstance(value, str) or not value:
        raise InspectionContractError(f"{field} must be a non-empty string")
    if require_trimmed and value != value.strip():
        raise InspectionContractError(f"{field} must not contain outer whitespace")
    if len(value) > maximum:
        raise InspectionContractError(
            f"{field} must contain at most {maximum} characters"
        )
    if "\x00" in value:
        raise InspectionContractError(f"{field} must not contain null bytes")
    return value


def _sha256(value: object, *, field: str) -> str:
    fingerprint = _string(
        value,
        field=field,
        maximum=MAX_FINGERPRINT_CHARACTERS,
    )
    if _SHA256.fullmatch(fingerprint) is None:
        raise InspectionContractError(f"{field} must be a sha256 fingerprint")
    return fingerprint


def _integer(
    value: object,
    *,
    field: str,
    minimum: int = 0,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InspectionContractError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise InspectionContractError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def _finite_number(
    value: object,
    *,
    field: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InspectionContractError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise InspectionContractError(f"{field} must be a finite number")
    if minimum is not None and number < minimum:
        raise InspectionContractError(f"{field} must be at least {minimum}")
    if maximum is not None and number > maximum:
        raise InspectionContractError(f"{field} must be at most {maximum}")
    return number


def _normalize_method_identity(
    value: object,
    *,
    method_id: str,
) -> dict[str, object]:
    identity = _mapping(value, field="method_identity")
    _exact_keys(
        identity,
        required=_METHOD_IDENTITY_KEYS,
        field="method_identity",
    )
    identity_method_id = _string(
        identity["method_id"],
        field="method_identity.method_id",
        maximum=MAX_METHOD_ID_CHARACTERS,
    )
    if identity_method_id != method_id:
        raise InspectionContractError(
            "method_identity.method_id must equal method_id"
        )
    return {
        "method_id": identity_method_id,
        "implementation_id": _string(
            identity["implementation_id"],
            field="method_identity.implementation_id",
            maximum=MAX_IMPLEMENTATION_ID_CHARACTERS,
        ),
        "fingerprint": _sha256(
            identity["fingerprint"],
            field="method_identity.fingerprint",
        ),
    }


def _normalize_source(
    value: object,
    *,
    index: int,
    corpus_revision: str,
    retriever_fingerprint: str,
) -> dict[str, object]:
    field = f"sources[{index}]"
    source = _mapping(value, field=field)
    _exact_keys(
        source,
        required=_SOURCE_REQUIRED_KEYS,
        optional=_SOURCE_OPTIONAL_KEYS,
        field=field,
    )
    provenance = _mapping(source["provenance"], field=f"{field}.provenance")
    _exact_keys(
        provenance,
        required=_PROVENANCE_KEYS,
        field=f"{field}.provenance",
    )
    if provenance["kind"] != "published-corpus":
        raise InspectionContractError(
            f"{field}.provenance.kind must be 'published-corpus'"
        )
    source_corpus_revision = _sha256(
        provenance["corpus_revision"],
        field=f"{field}.provenance.corpus_revision",
    )
    if source_corpus_revision != corpus_revision:
        raise InspectionContractError(
            f"{field}.provenance.corpus_revision must equal corpus_revision"
        )
    source_retriever_fingerprint = _sha256(
        provenance["retriever_fingerprint"],
        field=f"{field}.provenance.retriever_fingerprint",
    )
    if source_retriever_fingerprint != retriever_fingerprint:
        raise InspectionContractError(
            f"{field}.provenance.retriever_fingerprint must equal "
            "method_identity.fingerprint"
        )

    normalized: dict[str, object] = {
        "doc_id": _string(
            source["doc_id"],
            field=f"{field}.doc_id",
            maximum=MAX_SOURCE_DOC_ID_CHARACTERS,
        ),
        "title": _string(
            source["title"],
            field=f"{field}.title",
            maximum=MAX_SOURCE_TITLE_CHARACTERS,
        ),
        "rank": _integer(
            source["rank"],
            field=f"{field}.rank",
            minimum=1,
            maximum=MAX_HIT_COUNT,
        ),
        "provenance": {
            "kind": "published-corpus",
            "corpus_revision": source_corpus_revision,
            "retriever_fingerprint": source_retriever_fingerprint,
        },
    }
    if "score" in source:
        normalized["score"] = _finite_number(
            source["score"],
            field=f"{field}.score",
        )
    if "chunk_id" in source:
        normalized["chunk_id"] = _string(
            source["chunk_id"],
            field=f"{field}.chunk_id",
            maximum=MAX_CHUNK_ID_CHARACTERS,
        )
    return normalized


def _normalize_stage(
    value: object,
    *,
    index: int,
    method_identity: Mapping[str, object],
    hit_count: int,
) -> dict[str, object]:
    field = f"stages[{index}]"
    stage = _mapping(value, field=field)
    _exact_keys(stage, required=_STAGE_KEYS, field=field)
    stage_id = _string(
        stage["stage_id"],
        field=f"{field}.stage_id",
        maximum=MAX_METHOD_ID_CHARACTERS,
    )
    if stage_id != method_identity["method_id"]:
        raise InspectionContractError(f"{field}.stage_id must equal method_id")
    implementation_id = _string(
        stage["implementation_id"],
        field=f"{field}.implementation_id",
        maximum=MAX_IMPLEMENTATION_ID_CHARACTERS,
    )
    if implementation_id != method_identity["implementation_id"]:
        raise InspectionContractError(
            f"{field}.implementation_id must equal method identity"
        )
    fingerprint = _sha256(
        stage["fingerprint"],
        field=f"{field}.fingerprint",
    )
    if fingerprint != method_identity["fingerprint"]:
        raise InspectionContractError(
            f"{field}.fingerprint must equal method identity"
        )

    application = _mapping(
        stage["application"],
        field=f"{field}.application",
    )
    _exact_keys(
        application,
        required=_APPLICATION_KEYS,
        field=f"{field}.application",
    )
    if application["status"] != "applied":
        raise InspectionContractError(
            f"{field}.application.status must be 'applied'"
        )
    input_count = _integer(
        application["input_count"],
        field=f"{field}.application.input_count",
        maximum=MAX_HIT_COUNT,
    )
    output_count = _integer(
        application["output_count"],
        field=f"{field}.application.output_count",
        maximum=MAX_HIT_COUNT,
    )
    if input_count != 1:
        raise InspectionContractError(
            f"{field}.application.input_count must be 1"
        )
    if output_count != hit_count:
        raise InspectionContractError(
            f"{field}.application.output_count must equal hit_count"
        )
    return {
        "stage_id": stage_id,
        "implementation_id": implementation_id,
        "fingerprint": fingerprint,
        "elapsed_ms": _finite_number(
            stage["elapsed_ms"],
            field=f"{field}.elapsed_ms",
            minimum=0.0,
            maximum=MAX_ELAPSED_MS,
        ),
        "application": {
            "status": "applied",
            "input_count": input_count,
            "output_count": output_count,
        },
    }


def normalize_retrieval_inspection(
    value: object,
) -> dict[str, object]:
    """Validate and copy one exact public retrieval-inspection payload.

    Unknown fields fail closed instead of being passed through. This is the
    boundary that prevents prompts, raw document text, credentials, arbitrary
    hit metadata, and reasoning traces from reaching the public custom event.
    """

    payload = _mapping(value, field="inspection payload")
    _exact_keys(payload, required=_PAYLOAD_KEYS, field="inspection payload")
    if payload["schema_version"] != INSPECTION_SCHEMA_VERSION:
        raise InspectionContractError(
            f"schema_version must be {INSPECTION_SCHEMA_VERSION}"
        )
    if payload["kind"] != "retrieval":
        raise InspectionContractError("kind must be 'retrieval'")
    tool_call_id = _string(
        payload["tool_call_id"],
        field="tool_call_id",
        maximum=MAX_TOOL_CALL_ID_CHARACTERS,
    )
    query = _string(
        payload["query"],
        field="query",
        maximum=MAX_QUERY_CHARACTERS,
        require_trimmed=False,
    )
    if not query.strip():
        raise InspectionContractError("query must contain non-whitespace text")
    if not isinstance(payload["query_truncated"], bool):
        raise InspectionContractError("query_truncated must be a boolean")
    method_id = _string(
        payload["method_id"],
        field="method_id",
        maximum=MAX_METHOD_ID_CHARACTERS,
    )
    method_identity = _normalize_method_identity(
        payload["method_identity"],
        method_id=method_id,
    )
    hit_count = _integer(
        payload["hit_count"],
        field="hit_count",
        maximum=MAX_HIT_COUNT,
    )
    corpus_revision = _sha256(
        payload["corpus_revision"],
        field="corpus_revision",
    )
    corpus_document_count = _integer(
        payload["corpus_document_count"],
        field="corpus_document_count",
        maximum=MAX_CORPUS_DOCUMENT_COUNT,
    )
    if not isinstance(payload["sources_truncated"], bool):
        raise InspectionContractError("sources_truncated must be a boolean")

    raw_sources = payload["sources"]
    if not isinstance(raw_sources, (list, tuple)):
        raise InspectionContractError("sources must be an array")
    if len(raw_sources) > MAX_SOURCE_COUNT:
        raise InspectionContractError(
            f"sources must contain at most {MAX_SOURCE_COUNT} items"
        )
    sources = [
        _normalize_source(
            source,
            index=index,
            corpus_revision=corpus_revision,
            retriever_fingerprint=str(method_identity["fingerprint"]),
        )
        for index, source in enumerate(raw_sources)
    ]
    ranks = [source["rank"] for source in sources]
    if ranks != list(range(1, len(sources) + 1)):
        raise InspectionContractError("source ranks must be contiguous 1..N")
    expected_source_count = min(hit_count, MAX_SOURCE_COUNT)
    if len(sources) != expected_source_count:
        raise InspectionContractError(
            "sources must include the bounded prefix of all ranked hits"
        )
    expected_sources_truncated = hit_count > MAX_SOURCE_COUNT
    if payload["sources_truncated"] is not expected_sources_truncated:
        raise InspectionContractError(
            "sources_truncated must reflect the source-count bound"
        )

    raw_stages = payload["stages"]
    if not isinstance(raw_stages, (list, tuple)):
        raise InspectionContractError("stages must be an array")
    if not 1 <= len(raw_stages) <= MAX_STAGE_COUNT:
        raise InspectionContractError(
            f"stages must contain between 1 and {MAX_STAGE_COUNT} items"
        )
    stages = [
        _normalize_stage(
            stage,
            index=index,
            method_identity=method_identity,
            hit_count=hit_count,
        )
        for index, stage in enumerate(raw_stages)
    ]
    normalized: dict[str, object] = {
        "schema_version": INSPECTION_SCHEMA_VERSION,
        "kind": "retrieval",
        "tool_call_id": tool_call_id,
        "query": query,
        "query_truncated": payload["query_truncated"],
        "method_id": method_id,
        "method_identity": method_identity,
        "hit_count": hit_count,
        "corpus_revision": corpus_revision,
        "corpus_document_count": corpus_document_count,
        "sources": sources,
        "sources_truncated": payload["sources_truncated"],
        "stages": stages,
    }
    encoded = json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_EVENT_BYTES:
        raise InspectionContractError(
            f"inspection payload must be at most {MAX_EVENT_BYTES} bytes"
        )
    return normalized


def _bounded_display_text(value: str, *, maximum: int) -> tuple[str, bool]:
    normalized = value.replace("\x00", "").strip()
    if not normalized:
        return "", False
    if len(normalized) <= maximum:
        return normalized, False
    return normalized[:maximum], True


def build_retrieval_inspection(
    *,
    runtime: ServingRuntime,
    retriever: ResolvedRetriever,
    retrieval: Retrieval,
    tool_call_id: str,
    elapsed_ms: float,
) -> dict[str, object]:
    """Build one whitelisted observation from a completed ranked retrieval."""

    query, query_truncated = _bounded_display_text(
        retrieval.query,
        maximum=MAX_QUERY_CHARACTERS,
    )
    implementation_id = retriever.registration.implementation_id
    method_fingerprint = retriever.fingerprint
    corpus_revision = runtime.corpus.fingerprint
    sources: list[dict[str, object]] = []
    for hit in retrieval.hits[:MAX_SOURCE_COUNT]:
        entry = runtime.entry(hit.doc_id)
        title, _title_truncated = _bounded_display_text(
            entry.title,
            maximum=MAX_SOURCE_TITLE_CHARACTERS,
        )
        if not title:
            title = str(hit.doc_id)
        source: dict[str, object] = {
            "doc_id": str(hit.doc_id),
            "title": title,
            "rank": hit.rank,
            "provenance": {
                "kind": "published-corpus",
                "corpus_revision": corpus_revision,
                "retriever_fingerprint": method_fingerprint,
            },
        }
        if hit.score is not None:
            source["score"] = hit.score
        if (
            hit.chunk_id is not None
            and len(hit.chunk_id) <= MAX_CHUNK_ID_CHARACTERS
            and "\x00" not in hit.chunk_id
        ):
            source["chunk_id"] = hit.chunk_id
        sources.append(source)

    hit_count = len(retrieval.hits)
    payload = {
        "schema_version": INSPECTION_SCHEMA_VERSION,
        "kind": "retrieval",
        "tool_call_id": tool_call_id,
        "query": query,
        "query_truncated": query_truncated,
        "method_id": retriever.method_id,
        "method_identity": {
            "method_id": retriever.method_id,
            "implementation_id": implementation_id,
            "fingerprint": method_fingerprint,
        },
        "hit_count": hit_count,
        "corpus_revision": corpus_revision,
        "corpus_document_count": len(runtime.corpus.doc_ids()),
        "sources": sources,
        "sources_truncated": hit_count > MAX_SOURCE_COUNT,
        "stages": [
            {
                "stage_id": retriever.method_id,
                "implementation_id": implementation_id,
                "fingerprint": method_fingerprint,
                "elapsed_ms": elapsed_ms,
                "application": {
                    "status": "applied",
                    "input_count": 1,
                    "output_count": hit_count,
                },
            }
        ],
    }
    return normalize_retrieval_inspection(payload)


def emit_retrieval_inspection(
    tool_runtime: ToolRuntime | None,
    *,
    runtime: ServingRuntime,
    retriever: ResolvedRetriever,
    retrieval: Retrieval,
    elapsed_ms: float,
) -> bool:
    """Write a validated event when a trusted LangGraph tool context exists."""

    tool_call_id = tool_runtime.tool_call_id if tool_runtime is not None else None
    if not isinstance(tool_call_id, str) or not tool_call_id:
        return False
    try:
        payload = build_retrieval_inspection(
            runtime=runtime,
            retriever=retriever,
            retrieval=retrieval,
            tool_call_id=tool_call_id,
            elapsed_ms=elapsed_ms,
        )
    except InspectionContractError:
        return False
    tool_runtime.stream_writer(
        {
            "name": INSPECTION_EVENT_NAME,
            "payload": payload,
        }
    )
    return True


class InspectionEventTransformer(StreamTransformer):
    """Promote only exact inspection envelopes to a named custom channel."""

    required_stream_modes = ("custom",)

    def init(self) -> dict[str, object]:
        return {}

    def process(self, event: ProtocolEvent) -> bool:
        if event["method"] != "custom":
            return True
        data = event["params"]["data"]
        if not isinstance(data, Mapping) or data.get("name") != INSPECTION_EVENT_NAME:
            return True
        try:
            _exact_keys(
                data,
                required=_ENVELOPE_KEYS,
                field="inspection envelope",
            )
            payload = normalize_retrieval_inspection(data["payload"])
        except InspectionContractError:
            # Suppress malformed marked envelopes entirely so a generic custom
            # subscriber cannot observe fields rejected by the public contract.
            return False
        event["method"] = f"custom:{INSPECTION_EVENT_NAME}"
        event["params"]["data"] = payload
        return True


__all__ = [
    "INSPECTION_EVENT_NAME",
    "INSPECTION_SCHEMA_VERSION",
    "InspectionContractError",
    "InspectionEventTransformer",
    "build_retrieval_inspection",
    "emit_retrieval_inspection",
    "normalize_retrieval_inspection",
]
