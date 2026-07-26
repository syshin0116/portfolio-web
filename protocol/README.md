# Agent Protocol v2 contract

This directory pins the streaming contract used by the RAG restack. The lock
points to an immutable upstream commit, and the generated Python and TypeScript
bindings are byte-for-byte copies of that release.

## Provenance

- Agent Protocol: `langchain-ai/agent-protocol`
  `langchain-protocol==0.0.18`,
  commit `0ff7cd3962e8b4b3e347b76203be7dfeba003928`
- Aegra runtime: `ibbybuilds/aegra` `v0.9.24`,
  commit `51cb5a61f0b5e709d423e3d14978619a2a7c3960`
- Canonical schema: upstream `streaming/protocol.cddl`
- Fixture wire profile: the official generated snake_case bindings

The exact OpenAPI, CDDL, binding, and Aegra implementation hashes are in
[`agent-protocol.lock.json`](agent-protocol.lock.json). A future protocol bump
must update the lock, regenerate both bindings from that revision, update the
fixtures, and rerun the complete P0 compatibility gate.

## Offline gate

The fixture validator never fetches the network:

```bash
python scripts/protocol_contract.py
python -m unittest discover -s protocol/tests -v
python scripts/smoke.py
```

Fixtures cover content-block assembly, tool and run lifecycles, nested
namespaces, sequence replay after disconnect, HITL commands, structured errors,
and the Aegra dialect translation. The translation fixture stores both the raw
Aegra wire event and the expected normalized generated-binding event, so the
dialect is never silently presented as upstream-conforming. In addition to
generated-binding validation, the local validator checks ordering, command
correlation, non-interleaved content blocks, and replay deduplication.

## Explicit live gate

No server is contacted unless `--base-url` is present:

```bash
python scripts/smoke.py \
  --base-url http://127.0.0.1:8000 \
  --assistant-id agent \
  --profile aegra-0.9.24
```

Pass `--token-env AGENT_PROTOCOL_TOKEN` when authentication is enabled. The live
gate creates one client-generated thread, runs two Korean turns, deliberately
disconnects during a content delta, reconnects with `since`, requires a tool
lifecycle, reloads the thread, and verifies a structured command error.
`--require-hitl` and `--require-nested` promote those capabilities from fixture
gates to live requirements.

Process restart, trusted identity injection, and store namespace isolation need
runtime orchestration and credentials; they belong to the Aegra runtime/security
PR rather than this transport-only contract.

## Aegra 0.9.24 gaps

Aegra's SSE endpoint is
`POST /threads/{thread_id}/stream/events`; the locked upstream OpenAPI endpoint
is `POST /threads/{thread_id}/stream`. This is why the smoke profile is explicit.
Aegra also lacks the upstream WebSocket endpoint and implements only
`run.start` and `input.respond` from the command catalogue.
The `input.respond` implementation does not forward the `update` or `goto`
fields added by Agent Protocol 0.0.18.

One payload difference is more serious: the generated
`InputRequestedData` binding requires `payload`, while Aegra emits `value` to
match the stock LangGraph SDK. `normalize_aegra_event()` is the one permitted
translation boundary and rewrites only that verified field before official
binding validation. The raw/normalized fixture pair fails if the translation
expands or drifts. A live HITL run remains a compatibility gate, not an assumed
success.
