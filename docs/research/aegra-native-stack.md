---
title: "Research: the native Aegra + LangGraph + assistant-ui stack"
description: >
  What Aegra 0.9.24 and assistant-ui 0.14.27 actually do, how to be native to them,
  and what the existing code becomes - verified against upstream source.
when_to_read: >
  Before writing aegra.json, an auth handler, or any assistant-ui wiring; before
  bumping any pin in this stack.
tags: [research, aegra, assistant-ui, langgraph, deepagents, auth, anonymous]
status: draft
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [../adr/0004-adopt-aegra.md, ../adr/0005-adopt-assistant-ui.md, ../plans/rag-restack.md]
template: research
---

# Research: the native Aegra + LangGraph + assistant-ui stack

> **Not a decision.** Input to [ADR-0004](../adr/0004-adopt-aegra.md) and
> [ADR-0005](../adr/0005-adopt-assistant-ui.md).

> **Evaluated at** `aegra-api` **0.9.24** (2026-07-05) with the repo cloned at main
> (`d142457`, 2026-07-11), `@assistant-ui/react` **0.14.27**, `@assistant-ui/react-langgraph`
> **0.14.12**, `@langchain/langgraph-sdk` **1.9.28**, investigated 2026-07-26. Claims are
> from reading upstream source and published `dist`, not from docs prose.

## Bottom line

The rebuild is overwhelmingly subtractive: ~9,300 LOC out, ~1,400 in. The two things that
looked hardest are non-issues. The thing that is genuinely hard is that **Aegra's auth
handlers do not run on the streaming path**, which is the only path the frontend uses - so
authorization has to be layered rather than centralised.

## Solved by construction

**Graph registration.** `LangGraphService.get_graph()` does
`graph.copy(update={"checkpointer": ..., "store": ...})` per request. A
`create_deep_agent(...)` result registers as-is; the "CompiledStateGraph cannot be rebound"
problem does not exist here.

**Anonymous isolation.** Aegra hard-codes `WHERE user_id = <identity>` on every
threads/runs/assistants query, independent of any handler. A synthetic `anon:<uuid4>`
identity from `@auth.authenticate` is isolated from other visitors automatically. Nothing
downstream requires a user record.

**Wire format.** `/threads/{id}/runs/stream` emits `messages/partial` /
`messages/complete` / `updates` (`services/graph_streaming.py:204-205,412`) - exactly what
`@assistant-ui/react-langgraph`'s `LangChainEvent` type and the SDK's default
`streamProtocol: "legacy"` parse. P0 later verified that Aegra 0.9.24's Agent Protocol v2
content-block format lives on `POST /threads/{id}/stream/events`, not the upstream
`/threads/{id}/stream`; `FF_V2_EVENT_STREAMING=true` enables that endpoint and does not
change `/runs/stream`.

**Adapter surface is tiny.** `@assistant-ui/react-langgraph` makes exactly one SDK call -
`client.runs.stream(...)` inside `unstable_createLangGraphStream`. Grepping its dist for
`threads.`, `getHistory`, `Location` returns nothing. `load`, `create`, `delete`,
`getCheckpointId`, and the thread-list adapter are all callbacks you supply, so Aegra
compatibility is mostly under your control rather than upstream's.

## The governing constraint

`build_auth_context` appears at `runs.py:63` (non-streaming `create_run`), `runs.py:156`,
`runs.py:530`, and in threads/store/crons. It appears **nowhere** in `stateless_runs.py` or
`event_streaming.py`.

So `@auth.on.*` handlers are not dispatched on `/threads/{id}/runs/stream`, `/runs/wait`,
any stateless `/runs*` variant, or `/threads/{id}/events`. PR #385 patches two of those and
is still open (last touched 2026-07-25). This is broader than the caveat carried in.

`GHSA-m98r-6667-4wq7` (HIGH, fixed 0.9.7) was exactly a cross-tenant IDOR arising from this
default-allow handler model plus a missing SQL filter. That incident is the reason to treat
the SQL predicate as the boundary. Hard floor: `aegra-api >= 0.9.7`.

Handlers remain useful for `/store`, `/crons`, and `/assistants`, which do dispatch.

## The third content-leak bug

`inject_user_context` (`services/langgraph_service.py:681,684`):

```python
configurable.setdefault("user_id", user.identity)   # client can win
configurable["langgraph_auth_user"] = user          # server-authoritative
```

Client config beats assistant config in a shallow merge, so a caller-supplied
`configurable.user_id` survives. `agent/src/agent/graph.py:32` reads exactly that key.

Under public traffic an anonymous visitor sets `user_id` to the owner's Auth.js id and gets
the owner's `/memories/` namespace. **Only `langgraph_auth_user` is trustworthy.** The HTTP
`/store` API is unaffected - it scopes off `user.identity` directly.

## Two features that have never worked

Found while reading the graph, unrelated to Aegra:

- **`/memories/` has never been mounted.** `_lazy_graph()` calls `create_graph()` with no
  arguments, so `store is None`, so the route is skipped (`graph.py:52-55`).
- **Skills have never loaded.** `skills=[SKILLS_DIR]` passes an absolute host path into
  `SkillsMiddleware`, which resolves sources *through the backend*. `CompositeBackend`
  longest-prefix-matches it against `/blog/` and `/memories/`, misses both, and falls
  through to `StateBackend` - a virtual in-state filesystem. The native fix is a `/skills/`
  route on a read-only FilesystemBackend plus `skills=["/skills/"]`.

## Gotchas worth knowing before writing code

- **Aegra with no auth file is fail-open**: every caller shares one `anonymous` identity and
  Aegra logs that data is not isolated. The current server is fail-closed (503 on a short
  secret). Assert the secret length at import so the process refuses to start.
- **`is_authenticated: False` breaks everything** - `auth_deps.get_current_user` 401s on it
  and every route depends on that. Guests must return `True`; put the distinction in
  `permissions`.
- **`@auth.on.runs` raises `AttributeError` at import.** `runs` is in `_On.__slots__` but
  never assigned in `_On.__init__` (langgraph-sdk 0.4.2). Use the callable form.
- **Handlers cannot delete a config key**, only overwrite one - `create_run` merges. To
  strip `configurable`, assign the whole key.
- **Handler filter dicts compile to SQL for assistants only.** In `api/threads.py::list_threads`
  the filter branch is literally `pass`. Returning an owner filter from
  `@auth.on.threads.search` does nothing; the SQL predicate is what isolates.
- **Threads are auto-created by the run path**, bypassing `@auth.on.threads.create`, so a
  per-identity thread cap needs a custom count check.
- **Deleting a thread strands its checkpoints forever** - `api/threads.py::delete_thread`
  says so in its own docstring. `runs` cascades via FK; `checkpoints`, `checkpoint_blobs`,
  and `checkpoint_writes` carry `thread_id TEXT` with no FK. Sweep by absence, children
  before parents.
- **Do not use `BaseHTTPMiddleware`** for the guard - it wraps the response in an extra
  anyio task group and interferes with sse-starlette's client-disconnect detection, which is
  how `on_disconnect="cancel"` works. Write pure ASGI.
- **`enable_custom_route_auth: true` breaks health checks.** `_apply_auth_to_routes`
  (`main.py:199-224`) walks every `APIRoute` with no exclusion list, so `/health`, `/live`,
  and `/ready` would 401 and the Cloud Run startup probe fails. Use per-route `Depends`.
- **Factory graphs must keep identical topology** across access contexts (stated in the
  `ServerRuntime` docstring). Vary the model instance and backend routes, not the middleware
  list.
- **`config["configurable"]` is not schema-filtered**; run `context` is.
- Aegra's own source carries an unresolved `TODO(orphan-thread-sweeper)` in
  `api/stateless_runs.py`.

## assistant-ui specifics

- Aegra returns `interrupts` as a **top-level field** on thread state
  (`models/threads.py:127`), so the quickstart's `state.tasks[0].interrupts` is the wrong
  read.
- **Omitting `getCheckpointId` silently hides Edit and Regenerate.** It reads as a missing
  feature rather than missing config.
- When `unstable_threadListAdapter` is set, `cloud`, `create`, and `delete` are **silently
  ignored** - stamp metadata in `initialize()`.
- **No branch support at all**: zero `branch` references in the dist, so
  `BranchPickerPrimitive` renders and always shows 1/1.
- `LangGraphCommand` is typed `{resume: string}`, but that is compile-time only -
  `config.command` is spread verbatim with no runtime validation, so a richer payload works.
- The native composer guards Enter with both `e.nativeEvent.isComposing` and a
  `compositionRef` from `onCompositionStart`/`onCompositionEnd`. **Verify with a test
  anyway** - this is the highest-risk regression for Korean input.
- Four `unstable_` APIs sit on the recommended happy path.

## Inventory

`agent/src` 5,947 LOC → ~1,450.

- **Delete 4,489 (75%)** - the whole `api/` tree, `db.py`, `schemas.py`, `worker.py`, the
  run queue and ARQ machinery, `legacy_migration.py`.
- **Rebuild native 355 → ~60 LOC + a 22-line `aegra.json`** - `api/auth.py` 176 → ~85 with
  PyJWT replacing 130 LOC of hand-rolled base64url and HMAC; `api/main.py` 134 → config;
  `lib/read_only_backend.py` 45 → one `FilesystemPermission` rule.
- **Keep 1,031** - 96% of `agent/src/agent/`.
- Tests: 777 delete, 614 rebuild as black-box, 181 keep.

Frontend: delete 1,769 LOC of vendored prompt-kit plus `chat-section.tsx` (1,054). Keep
`web/lib/agent-auth.ts` (54 LOC) unchanged.

## Unverified

- Whether deepagents actually runs under Aegra. Aegra's repo has zero mentions of it. Plan
  phase P0 is the test; issues #224 (fixed 0.7.5) and #352 (fixed 0.9.14) were both
  deepagents multi-turn bugs, which is why the smoke test needs a **second turn**.
- Whether issue #468 reproduces.
- Whether the assistant-ui adapter surfaces 409 and 429 as usable error states or as a
  generic stream failure.
- Cold-start-to-first-token for this image, against the hard 4-minute Cloud Run startup
  timeout.
- Real RAM/CPU footprint of an idle Aegra container. No published sizing; open issue #208
  reports high CPU after start, unresolved.
- Whether anyone has run assistant-ui against Aegra. Aegra lists Agent Chat UI, LangGraph
  Studio, and CopilotKit.
- `langgraph==1.2.9` and `langgraph-checkpoint-postgres==3.1.0` are both **above** what
  Aegra's own lock resolves (1.2.6 / 3.0.4), so they are permitted but untested by Aegra CI.
