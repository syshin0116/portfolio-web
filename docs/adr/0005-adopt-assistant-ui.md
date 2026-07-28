---
title: "ADR-0005: Rebuild the chat UI on assistant-ui with an Agent Protocol v2 transport"
description: >
  Replace chat-section.tsx and the vendored prompt-kit layer with assistant-ui's native
  LangGraph runtime over the official Agent Protocol v2 ThreadStream SDK.
when_to_read: >
  Before changing the chat frontend, picking an assistant-ui adapter, or wondering
  why the branch picker always shows 1/1.
tags: [adr, web, chat, assistant-ui, prompt-kit, langgraph, aegra]
status: accepted
date: "2026-07-26"
deciders: ["@syshin0116"]
supersedes:
superseded_by:
updated: "2026-07-28"
owners: ["@syshin0116"]
refs: [../research/aegra-native-stack.md, ../plans/rag-restack.md, 0004-adopt-aegra.md]
template: adr
---

# ADR-0005: Rebuild the chat UI on assistant-ui with an Agent Protocol v2 transport

> **status: accepted.** An earlier draft the same day proposed repairing the existing UI
> and deferring assistant-ui. It was `proposed` so the owner could decide; the owner chose
> assistant-ui, and to be as native to it as possible. That draft also recommended the
> **wrong adapter** - see the decision below.

## Context

The chat is `web/components/chat-section.tsx` (1,054 LOC) over a ~1,769-LOC vendored
prompt-kit layer, driving `@langchain/react` `useStream`. Roughly 893 LOC of the vendored
layer is already dead (`loader.tsx` 499 with 1 of 12 variants used; `source.tsx` 130 and
`blog-search-result.tsx` 134 with zero importers).

The originally stated reason for moving - "assistant-ui has LangGraph compatibility" - does
not survive contact with the code: `@langchain/react` *is* LangChain's own React
integration. The features that feel broken are broken because `chat-section.tsx:72-85`
casts a v0.2-era API onto a v1 hook.

But the backend is now becoming Aegra ([ADR-0004](0004-adopt-aegra.md)), and the owner's
constraint is to be native to Aegra, LangGraph, and assistant-ui together. That changes the
comparison: the question is no longer "repair or replace" but "which client is native to an
Agent Protocol server".

Three findings de-risked this substantially:

- `@assistant-ui/react-langgraph` exposes `useLangGraphRuntime({ stream, load, ... })`, so
  assistant-ui can own the UI/runtime while the application supplies an official
  thread-centric Agent Protocol v2 stream callback. The legacy
  `unstable_createLangGraphStream` helper is not required.
- `@langchain/langgraph-sdk` 1.9.28 has the required native pieces:
  `Client.threads.stream`, `ThreadStream.submitRun/respondInput`, `MessageAssembler`, and
  a dedicated lifecycle watcher connection.
- Aegra's AP v2 stream filter is security-relevant. Client-side projection is too late if
  open LangGraph `values` or nested messages already crossed the browser network boundary.

## Considered options

| Option | Pros | Cons |
|---|---|---|
| A. `useLangGraphRuntime` + official SDK `ThreadStream` | Native assistant-ui runtime and official AP v2 client/assembler; no hand-written SSE parser | A small, security-sensitive SDK-event-to-runtime projection remains local |
| B. `unstable_createLangGraphStream` | Small adapter surface | Calls legacy `runs.stream`; does not exercise the latest AP v2 thread-centric protocol |
| C. `@assistant-ui/react-langchain` | Wraps the existing `useStream` | **Wrong tool.** It targets LangChain.js runnables, not an Agent Protocol server |
| D. Repair `@langchain/react` v1 drift, keep prompt-kit | ~200 LOC in one file | Keeps a 1,769-LOC vendored layer; no native AP v2 UI contract or thread list |

## Decision

Adopt `@assistant-ui/react` 0.15.0 and
`@assistant-ui/react-langgraph` 0.14.15 through native `useLangGraphRuntime`.
The runtime callback uses the official `@langchain/langgraph-sdk` 1.9.28
`Client.threads.stream` / `ThreadStream` / `MessageAssembler` surface with
`streamProtocol: "v2"`. `submitRun` and `respondInput` still send Aegra's supported
`run.start` and `input.respond` wire commands, but avoid the older SDK methods' implicit
wildcard `values` projection. There is no hand-written SSE parser, generated TypeScript
transport facade, or production `runs.stream` call.

The browser opens these two physically separate SSE connections:

| Connection | Channels | Namespace/depth | Consumer |
|---|---|---|---|
| root content pump | `messages`, `lifecycle`, `input`, `tools`, `custom` | `namespaces: [[]]`, `depth: 0` | local assistant-ui projection |
| SDK lifecycle watcher | `lifecycle`, `input` only | wildcard, managed by `ThreadStream` outside the content union | SDK lifecycle/interrupt bookkeeping |

The application calls `subscribe()` exactly once. The second connection is
`ThreadStream`'s dedicated `openEventStream` watcher, not a second subscription whose
filters could union nested messages into the content pump. The root content pump never
subscribes to `values` or `updates`; nested answer text and open Deep Agents
todo/file/scratch state therefore do not cross that stream boundary. Retrieval inspection
is a bounded root `custom` event and is explicitly live-run-only; reload shows that past
inspection detail is unavailable rather than reconstructing it from tool output.

The local message reducer never displays system/tool content or internal
chain-of-thought. For owner traffic that remains a presentation guarantee. Canonical
guest traffic now also has a server-side network guarantee: `GuestRunGuard` forces both
SDK connections to `namespaces: [[]]` and `depth: 0` and buffers and rebuilds every
allowlisted JSON response before sending it. State/history contain public human/assistant
text plus bounded root interrupt identity; thread create/search/read/update contain only
curated public metadata; run list/get/cancel contain identifiers, status, timestamps, and
the validated submit nonce needed for native run correlation; command success/error
envelopes have exact bounded shapes and fixed error copy. Each complete SSE frame is also
parsed and rebuilt before sending it. Reasoning/thinking blocks and system messages are
dropped; tool arguments, tool output, tool deltas, raw errors, and unreviewed interrupt
payloads are removed; the one retrieval-inspection custom event is revalidated against its
public schema. A single frame may use the full bounded 512 KiB connection budget so the
inspection contract's legal 64 KiB payload still fits after AP/SSE framing. Unknown or
malformed responses fail closed without forwarding the offending body bytes. Owner
responses remain unprojected.

One pinned compatibility edge is explicit. Aegra 0.9.24 can observe a nested copy of an
interrupt before its root copy, mark the identifier as sent, then remove the nested event
for a root/depth-zero subscription and suppress the root event as a duplicate. The public
wire does not widen either browser subscription to compensate. On a root `interrupted`
lifecycle without a matching input event, the client must instead read the official,
already-projected thread state, accept exactly one schema-valid root interrupt, and resume
that exact identifier with `namespace: []`; absence, ambiguity, or malformed state fails
closed. Projected `input.requested` events carry the same sanitized schema under both the
pinned SDK's `payload` field and Aegra's direct-event `value` field. WEB-B stays disabled
until that SDK/state fallback is merged and browser-verified.

Run cancellation, thread metadata, history, and state use the official SDK clients. Edit,
Regenerate, branch mutation, and delete remain visibly unavailable where Aegra cannot
perform them with the required atomicity; this implementation does not add a custom REST
facade to imitate missing AP v2 commands.

The server-side public-wire prerequisites for WEB-B are implemented, but that does not
turn anonymous access on by itself. WEB-B remains rollout-gated by ADR-0006's identity,
durable spend, retention, deployment, and browser-verification requirements. The boundary
is intentionally guest-only: a signed owner can still inspect complete checkpoints and
native events, while a canonical `anon:<uuid4>` subject receives only the public
projection. UI sanitization remains defense in depth rather than the network boundary.

The PostgreSQL integration's `rawPrivateStateObserved=false` assertion proves that the
current fixture sentinel does not appear on either AP v2 SSE connection. It is a regression
proof for this state-channel leak, not a claim that every future input payload is safe or
that provider chain-of-thought cannot reach the browser.

**Not `@assistant-ui/react-langchain`.** An earlier draft recommended it on the basis that
it wraps `useStream`; that reasoning applied to keeping the old backend, and the package is
for LangChain.js runnables rather than an Agent Protocol server.

Delete `chat-section.tsx` and the vendored prompt-kit layer. Keep `web/lib/agent-auth.ts`
unchanged - it is the only place that knows the Auth.js session, and it becomes the
anonymous-identity minter too.

Exact pins, no `^`.

## Consequences

**Positive**

- The bespoke prompt-kit and custom SSE/Agent Protocol transport are deleted.
- A thread list and thread persistence across reload, neither of which exists today.
- AP v2 content blocks are assembled by the official `MessageAssembler`.
- Root-only stream filters prevent open graph state and nested transcript text from
  traversing the primary browser SSE connection.
- HITL, cancellation, error routing, identity disposal, Korean IME, citations, responsive
  layout, reduced motion, and focus restoration are fixture- or browser-testable seams.

**Trade-offs**

- **Branch switching, Edit, Regenerate, and delete are disabled**, not emulated over a
  partially compatible mutation surface.
- Four `unstable_` APIs sit on the recommended happy path.
- The application still owns a bounded AP v2-to-assistant-ui projection until an upstream
  adapter exists.
- Guest state/history and both SSE connections are a deliberately smaller wire contract
  than the owner protocol surface; a future Aegra event variant fails closed until
  reviewed.
- `unstable_threadListAdapter` means metadata must be stamped in `initialize()`.

**Follow-ups**

- [ ] Build and verify on a deployed owner preview URL before merging.
- [ ] **Verify the Korean IME guard in a real browser**, do not assume it. The native
      composer guards Enter with both `e.nativeEvent.isComposing` and a `compositionRef`,
      but this is the single highest-risk regression for a Korean-language chat.
- [ ] Keep `remark-breaks` in the markdown pipeline - the agent's Korean prose relies on
      single-newline line breaks - and memoize components at module scope for streaming.
- [ ] `load()` must read `state.interrupts` first: Aegra returns interrupts as a top-level
      field (`models/threads.py:127`), so the quickstart's `state.tasks[0].interrupts` is
      the wrong read here.
- [ ] Async `onRequest` token hook with a 60s margin. Capturing the token once at mount
      401s mid-conversation.
- [x] Pin the SDK/protocol dependencies and replay committed plus actual Aegra AP v2
      fixtures, including an isolated PostgreSQL 17 integration.
- [x] Add a public-safe state/history projection, force the SDK input watcher to the root,
      and suppress/redact reasoning plus unsafe tool/input payloads before guest response
      bytes leave the server.

## Revisit when

- `@assistant-ui/react-langgraph` ships branch support - the one capability being given up.
- The `unstable_` APIs stabilise or break; either is a reason to re-read this.
- assistant-ui appears on Aegra's integration list, or vice versa - it would mean someone
  else is carrying the compatibility risk.
- assistant-ui ships a stable native Agent Protocol v2 transport, at which point delete the
  local reducer after fixture parity passes.

## Changelog

- 2026-07-26: created as `proposed` recommending repair-and-defer with the
  `react-langchain` adapter; replaced the same day with this `accepted` decision, which
  also corrects the adapter choice to `react-langgraph`.
- 2026-07-26: amended the production transport from the legacy react-langgraph stream
  adapter to typed Agent Protocol v2 thread streaming after “latest Agent Protocol” became
  an explicit project requirement.
- 2026-07-28: replaced the proposed hand-written AP v2 transport with native
  `useLangGraphRuntime` over the official SDK `ThreadStream`/`MessageAssembler`, constrained
  the content pump to root-only channels, and recorded the owner-only WEB-A boundary.
- 2026-07-28: added the guest-only server public-wire projection for every allowlisted
  thread/run/command/state/history JSON response and complete AP v2 SSE frame, forced the
  SDK watcher to root depth zero, and closed the reasoning plus raw entity/tool/input/error
  network blockers without changing owner traffic.
