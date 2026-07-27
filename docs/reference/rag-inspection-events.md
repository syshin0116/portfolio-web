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
owner of HTTP, thread streams, sequence IDs, replay, and channel filtering.

## Retrieval payload

The first version accepts only `kind: "retrieval"`. It includes:

- the trusted LangGraph `tool_call_id` used to correlate the tool timeline;
- the bounded retrieval query, method ID, versioned implementation ID, and
  method/config/corpus fingerprint;
- the verified published-corpus revision and document count;
- at most 50 ranked sources with public DocId, title, method-native score when
  present, optional chunk ID, and corpus/retriever provenance;
- the measured elapsed time and actual input/output counts for the one serving
  retriever stage that ran.

`rank` is the cross-method ordering contract. `score` remains method-native and
must not be compared across methods. `elapsed_ms` is measured execution data and
is intentionally not deterministic; identities, source order, and application
counts are deterministic for the same corpus, method, query, and artifacts.

The wire keeps the UI fixture's stable fields—`tool_call_id`, `query`,
`method_id`, `hit_count`, `corpus_revision`, and `sources`—while adding backend
identity and provenance fields that older consumers may ignore.

## Bounds and disclosure

- The canonical payload is at most 65,536 UTF-8 bytes.
- Queries are limited to 1,000 characters, titles to 300, and sources to 50.
- Identifiers, fingerprints, stages, counts, finite numbers, provenance, and
  source ranks are validated before the named event can leave the graph.
- Every object has an exact allowlist. Unknown fields suppress the marked
  event, so system prompts, credentials, owner identity, arbitrary hit metadata,
  raw document text, and reasoning traces cannot pass through by accident.
- Formatted tool output is not parsed to reconstruct inspection data.

The event contains no subject or owner identifier. Aegra's existing
owner-scoped thread authorization remains the visibility boundary.

## Optional capabilities

QuickJS and dynamic subagent observations are deliberately absent from the
backend v1 union. Absence means “not observed,” not “completed with zero cost.”
Their future variants must be added only with real status, latency, evidence,
and shared-budget measurements and must pass the same bounded allowlist. The
retrieval emitter does not synthesize placeholder capability results.

## Change rule

Adding or changing a required field is a new event name such as
`syshin.rag.inspection.v2`. Additive fields that remain safe for older
consumers still require fixture, backend contract, native stream, and UI
projector coverage in one integration sequence.
