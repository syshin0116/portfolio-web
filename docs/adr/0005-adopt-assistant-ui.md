---
title: "ADR-0005: Rebuild the chat UI on assistant-ui with an Agent Protocol v2 transport"
description: >
  Replace chat-section.tsx and the vendored prompt-kit layer with assistant-ui 0.14.27
  and a typed Agent Protocol v2 transport, accepting the loss of branch switching.
when_to_read: >
  Before changing the chat frontend, picking an assistant-ui adapter, or wondering
  why the branch picker always shows 1/1.
tags: [adr, web, chat, assistant-ui, prompt-kit, langgraph, aegra]
status: accepted
date: "2026-07-26"
deciders: ["@syshin0116"]
supersedes:
superseded_by:
updated: "2026-07-26"
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

Two findings de-risked this substantially:

- **`@assistant-ui/react-langgraph` makes exactly one SDK call**, `client.runs.stream(...)`.
  `load`, `create`, `delete`, `getCheckpointId`, and the thread-list adapter are all
  callbacks you supply. So the "unverified against Aegra" surface is much smaller than it
  looks.
- **Aegra's `/runs/stream` emits the legacy event names the adapter parses** -
  `messages/partial` / `messages/complete` / `updates`
  (`services/graph_streaming.py:204-205,412`). Agent Protocol v2's content-block format is
  on a different endpoint and does not affect this one.

## Considered options

| Option | Pros | Cons |
|---|---|---|
| A. `@assistant-ui/react` + typed Agent Protocol v2 transport | Uses Aegra's current thread stream; content blocks, replay, nested agents, tool/run lifecycle, and commands are explicit | Own the protocol-to-runtime reducer until upstream ships one |
| B. `@assistant-ui/react-langgraph` | One legacy SDK call; useful migration fixture | Calls `runs.stream`; does not exercise the latest AP v2 thread-centric protocol |
| C. `@assistant-ui/react-langchain` | Wraps the existing `useStream` | **Wrong tool.** It targets LangChain.js runnables, not an Agent Protocol server |
| D. Repair `@langchain/react` v1 drift, keep prompt-kit | ~200 LOC in one file | Keeps a 1,769-LOC vendored layer; no native AP v2 UI contract or thread list |

## Decision

Adopt assistant-ui as the component/runtime layer, with a typed custom transport over
Aegra's Agent Protocol v2 thread-centric streaming endpoints and generated Agent Streaming
Protocol bindings. `@assistant-ui/react-langgraph` 0.14.12 remains a temporary migration
fixture, not the production transport, because `unstable_createLangGraphStream` calls the
legacy `runs.stream` surface.

**Not `@assistant-ui/react-langchain`.** An earlier draft recommended it on the basis that
it wraps `useStream`; that reasoning applied to keeping the old backend, and the package is
for LangChain.js runnables rather than an Agent Protocol server.

Delete `chat-section.tsx` and the vendored prompt-kit layer. Keep `web/lib/agent-auth.ts`
unchanged - it is the only place that knows the Auth.js session, and it becomes the
anonymous-identity minter too.

Exact pins, no `^`.

## Consequences

**Positive**

- ~2,800 LOC of bespoke UI deleted, including ~893 that was already dead.
- A thread list and thread persistence across reload, neither of which exists today.
- Tool rendering becomes `makeAssistantToolUI` per tool.
  `blog-search-result.tsx` already contains the card markup and was never imported - this
  is its first wiring.
- Edit and Regenerate work server-side via checkpoint forking.

**Trade-offs**

- **Branch switching is lost.** `@assistant-ui/react-langgraph` has zero branch support -
  no `branch` references anywhere in its dist - so `BranchPickerPrimitive` renders but
  always shows 1/1. The current `BranchSwitcher` works today. Rebuilding it means custom
  work on `client.threads.getHistory`.
- A rebuild of the landing-page hero with **zero frontend test coverage** as a safety net.
- Four `unstable_` APIs sit on the recommended happy path.
- Nobody upstream has run assistant-ui against Aegra. Aegra's listed frontends are Agent
  Chat UI, LangGraph Studio, and CopilotKit.
- The application owns a protocol-to-runtime reducer until assistant-ui ships a native
  Agent Protocol v2 adapter. That adds code, but makes replay, nested-agent namespaces,
  content blocks, tool lifecycle, and HITL commands explicit and fixture-testable.
- Two silent-failure traps: omitting `getCheckpointId` makes Edit and Regenerate simply not
  render (reads as a missing feature, not missing config), and when
  `unstable_threadListAdapter` is set, `create` and `delete` are silently ignored so
  metadata must be stamped in `initialize()`.

**Follow-ups**

- [ ] Build on a preview URL first. `chat-section.tsx` stays live until cutover.
- [ ] **Verify the Korean IME guard with a Playwright test**, do not assume it. The native
      composer guards Enter with both `e.nativeEvent.isComposing` and a `compositionRef`,
      but this is the single highest-risk regression for a Korean-language chat.
- [ ] Keep `remark-breaks` in the markdown pipeline - the agent's Korean prose relies on
      single-newline line breaks - and memoize components at module scope for streaming.
- [ ] `load()` must read `state.interrupts` first: Aegra returns interrupts as a top-level
      field (`models/threads.py:127`), so the quickstart's `state.tasks[0].interrupts` is
      the wrong read here.
- [ ] Async `onRequest` token hook with a 60s margin. Capturing the token once at mount
      401s mid-conversation.
- [ ] Pin the upstream Agent Protocol schema revision, generate TypeScript bindings, and
      replay committed AP v2 fixtures in CI.
- [ ] Decide whether to rebuild branch switching or accept the loss.

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
