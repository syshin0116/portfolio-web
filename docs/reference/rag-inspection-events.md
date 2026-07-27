---
title: "RAG inspection event contract"
description: >
  Backend contract for bounded retrieval-method observations carried through
  LangGraph and Aegra on the Agent Protocol custom channel.
when_to_read: >
  Before changing retrieval tool output, the assistant execution-details UI,
  LangGraph stream transformers, or the syshin.rag.inspection extension.
tags: [reference, rag, inspection, langgraph, aegra, agent-protocol]
status: draft
updated: "2026-07-28"
owners: ["@syshin0116"]
refs:
  - ../adr/0008-chatbot-is-a-rag-evaluation-testbed.md
  - ../plans/rag-restack.md
template: reference
---

# RAG inspection event contract

`syshin.rag.inspection.v1` is a product extension carried by the standard
Agent Protocol `custom` event. It is not a new endpoint or an SSE facade:

```text
ranked retrieval tool
  -> ToolRuntime.stream_writer
  -> LangGraph custom event
  -> InspectionEventTransformer
  -> LangGraph custom:syshin.rag.inspection.v1
  -> Aegra native v3 stream
  -> Agent Protocol custom event {name, payload}
```

The transformer is compiled into the registered graph. Aegra remains the only
owner of HTTP, thread streams, sequence IDs, and channel filtering. This
extension does not add a persistence or replay layer.

## Retrieval payload

The first version accepts only `kind: "retrieval"` and
`delivery: "live-run-only"`. It includes:

- the trusted LangGraph `tool_call_id` used to correlate the tool timeline;
- the bounded retrieval query, method ID, versioned implementation ID, and
  method/config/corpus fingerprint;
- the verified published-corpus revision and document count;
- at most 50 ranked sources with public DocId, title, method-native score when
  present, optional chunk ID, and corpus/retriever provenance;
- exactly one measured serving-retriever stage, with its elapsed time and
  actual input/output counts.

The v1 stage is the observed registered method invocation. For today's exact
and BM25 serving methods that is truthful as one stage. A later dense, hybrid,
or RRF implementation must not invent component timings beneath that aggregate
observation. Exposing separately measured dense, sparse, fusion, or reranking
components requires a versioned contract such as `syshin.rag.inspection.v2`.

`rank` is the cross-method ordering contract. `score` remains method-native and
must not be compared across methods. `elapsed_ms` is measured execution data and
is intentionally not deterministic; identities, source order, and application
counts are deterministic for the same corpus, method, query, and artifacts.

The canonical producer fixture is
[`protocol/fixtures/inspection-events-v1.json`](../../protocol/fixtures/inspection-events-v1.json).
It contains one retrieval event and no synthetic QuickJS or subagent variants.
TypeScript consumers should project that fixture and ignore safe additive
fields they do not render.

## Delivery and reload behavior

Inspection v1 is best-effort live-run data. The current Aegra custom stream is
distributed by an in-memory broker and is not a durable event journal. Sequence
IDs can order events observed on the active stream, but this contract makes no
promise that an inspection event can be replayed after disconnect, process
restart, or UI reload. The canonical fixture therefore has no replay
expectation and explicitly records `durable_replay: false`.

This is intentional for a public testbed: the query must be visible to the
currently authorized UI so a visitor can understand the retrieval run, but
inspection metadata and visitor queries are not retained merely to rebuild the
execution panel later. On reload, the persisted answer may remain while its
inspection panel is absent. The UI must show inspection as unavailable for that
past run; it must not infer method, timing, or provenance from answer text or
formatted tool output.

## Bounds and disclosure

- The canonical payload is at most 65,536 UTF-8 bytes. If the 50-source count
  prefix would exceed that limit, the producer deterministically removes
  lowest-ranked sources until the longest fitting contiguous prefix remains
  and sets `sources_truncated: true`.
- The exact executed query is intentionally disclosed, including outer
  whitespace. Only a real prefix truncation at 1,000 characters sets
  `query_truncated: true`; NUL and non-scalar surrogate input is rejected before
  retrieval. Titles are public catalog metadata, limited to 300 characters.
- Opaque tool, method, implementation, and chunk IDs are bounded ASCII-safe
  identifiers. Sources remain a contiguous rank prefix of at most 50.
- Identifiers, fingerprints, stages, counts, finite numbers, provenance, and
  source ranks are validated before the named event can leave the graph.
- Every object has an exact allowlist. Unknown fields suppress the marked
  event, so system prompts, credentials, owner identity, arbitrary hit metadata,
  raw document text, and reasoning traces cannot pass through by accident.
- Formatted tool output is not parsed to reconstruct inspection data.
- Inspection failures are fail-open for retrieval. Suppression telemetry
  contains only a fixed reason and count—never query, title, payload, method
  identity, exception text, prompt, or credentials.

The event contains no subject or owner identifier. Aegra's existing
owner-scoped thread authorization remains the visibility boundary.

## Optional capabilities

QuickJS and dynamic subagent observations are deliberately absent from the
backend v1 union. Absence means “not observed,” not “completed with zero cost.”
Their future variants must be added only with real status, latency, evidence,
and shared-budget measurements and must pass the same bounded allowlist. The
retrieval emitter does not synthesize placeholder capability results.

## Change rule

Adding a capability kind or changing the single-stage meaning requires a new
event name such as `syshin.rag.inspection.v2`. Additive fields that remain safe
for older consumers still require fixture, backend contract, native stream, and
UI projector coverage in one integration sequence.
