---
title: "Research: Aegra, assistant-ui, langchain-quickjs, and GCP hosting"
description: >
  What the three requested stack changes actually cost, what the existing code
  already does, and what it takes to host the agent on GCP.
when_to_read: >
  Before adopting Aegra or assistant-ui, before adding a code interpreter, or
  when revisiting the deploy target.
tags: [research, aegra, assistant-ui, quickjs, langgraph, gcp, deploy]
status: draft
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [public-exposure.md, ../plans/rag-restack.md]
template: research
---

# Research: Aegra, assistant-ui, langchain-quickjs, and GCP hosting

> 🕑 **Historical snapshot, superseded the same day.** This note recommended *against*
> Aegra and assistant-ui, on the premise that existing agent data had to be migrated. The
> owner then decided the agent data is disposable, which removes that premise. The
> canonical decisions are [ADR-0004](../adr/0004-adopt-aegra.md) and
> [ADR-0005](../adr/0005-adopt-assistant-ui.md); the current research is
> [`aegra-native-stack.md`](aegra-native-stack.md). **Kept unedited** - a research note
> records what was believed at the time, and rewriting it to match hindsight destroys the
> only thing it is good for.
>
> Two claims here are also simply wrong, and were corrected elsewhere: the adapter
> recommendation (`react-langchain` targets LangChain.js runnables, not an Agent Protocol
> server) and the fresh-database refuse-to-start claim.

> **Not a decision.** Input to [ADR-0004](../adr/0004-adopt-aegra.md) and
> [ADR-0005](../adr/0005-adopt-assistant-ui.md).

> **Investigated** 2026-07-26 against the repo at `09a29a9` and installed
> `node_modules` / `.venv`, plus current upstream docs. Versions are what was observed
> on that date.

## Bottom line

Three requests, three different answers. **langchain-quickjs is straightforwardly good**
and the cheapest of the three. **assistant-ui rests on a false premise** - the
LangGraph compatibility it was wanted for is already there - though a narrower case
survives. **Aegra would replace 5,947 LOC you already wrote and tested**, and carries one
guarantee regression plus an unquantified data-migration risk.

None of them is the highest-value action. Nothing is deployed anywhere.

## What exists today

| | |
|---|---|
| `agent/src` total | **5,947 LOC**, of which ~4,700 is the hand-rolled Agent Protocol server |
| Agent Protocol surface | **41 routes** across assistants, threads, runs, store, crons, models |
| The graph itself | ~96 LOC (`agent/src/agent/graph.py`) - a plain compiled deepagents graph, host-agnostic |
| Authorization | Every resource owner-scoped; checkpoints keyed `uuid5(ns, user_id + NUL + thread_id)` (`resource_scope.py:8-12`) |
| Tests | 1,572 LOC, largely pinning cross-owner isolation |
| Retrieval | BM25 (kiwipiepy) + ripgrep + frontmatter + wikilink graph. **No vector store** |
| Deploy config | **None.** No Dockerfile, no `langgraph.json`, no manifest |

Two dependency-level findings worth acting on regardless of any migration:

- **`chromadb>=0.6` has zero call sites** (`pyproject.toml:22`). `semantic_search` is
  BM25, not embeddings. It drags onnxruntime into every image layer.
- **Crons are stored but never fire.** No scheduler exists and nothing computes
  `next_run_date` - only the DDL column (`db.py:63`), the schema field
  (`schemas.py:221`), and a response mapping.

## Aegra

`github.com/aegra/aegra`, Apache-2.0, **v0.9.24** (2026-07-05), ~1.1k stars, last commit
2026-07-10. A genuine self-hosted LangGraph Platform / Agent Protocol implementation with
a deep test suite. Dependency compatibility with this repo is good: installed langgraph
1.2.9 against Aegra's declared >=1.0.3, langgraph-sdk 0.4.2 exactly matching, Python >=3.12.

**What it would give:** ~2,500 LOC of protocol plumbing deleted, Alembic migrations, real
cron execution, cross-instance cancellation, time-travel.

**What it would cost:**

| Risk | Detail |
|---|---|
| Checkpoint identity migration | Your checkpoints are keyed `uuid5(ns, user_id + NUL + thread_id)`. **How Aegra derives its key was not established** - only that it filters tenancy via a `user_id` SQL column, which is an orthogonal mechanism. A naive cutover could orphan all history; a careless un-scoping could leak across owners |
| No same-thread run serialization | Aegra validates, stores, and threads `multitask_strategy` to the worker, then **never reads it**. This directly reverses the 2026-07-11 `DECISIONS.md` entry, and the chat UI ships a queue feature, which is double-texting by construction. Fix exists only as **unmerged** PR #462 |
| deepagents unverified | The string `deepagent` appears **nowhere** in the Aegra repo - no examples, tests, or docs. Aegra injects checkpointer/store via per-request `Pregel.copy(...)`, and issue #305 shows that copy failing with warning-then-continue when non-copyable callbacks are attached |
| Bus factor 1 | `ibbybuilds` holds 629 of ~800 commits. **Zero merges in the ~2.5 weeks to 2026-07-26** with 10 PRs open - including the fixes for all three headline gaps (#462 multitask, #448 run-level interrupts, #385 stream/wait auth handlers) |
| `/models` is not Agent Protocol | Aegra will not serve it. The model selector depends on it |
| Security history | GHSA-m98r-6667-4wq7, a HIGH-severity cross-user run injection, patched in 0.9.7. Pin `aegra-cli` >= 0.9.22, never the unpinnable `aegra` meta-package |

Prior art worth reading: a separate team evaluated Aegra in depth in 2026-05 (at 0.9.17)
and accepted it as a base, while flagging pre-1.0 risk, a `LeaseReaper` queue-routing
defect, and a single-process API+worker scaling limit. Their conclusion turned on
**standard-compliance being the top value**, which is a different weighting than a
single-user blog has.

## assistant-ui

`@assistant-ui/react` 0.14.x, MIT, 11.2k stars, actively developed.

**The stated reason does not hold.** `@langchain/react` 1.0.26 *is* LangChain's own
React integration, and assistant-ui's recommended adapter for a `useStream` app,
`@assistant-ui/react-langchain` 0.0.19 (`useStreamRuntime`), wraps that same hook.
Switching buys component ergonomics, not connectivity.

**The real diagnosis of "the chat feels broken":** `chat-section.tsx:72-85` declares a
`StreamHandle` type casting a v0.2-era API onto the v1 hook, applied at `:663` with
`as unknown as StreamHandle`. That cast is also what keeps `bunx tsc --noEmit` green in CI.

Verified against the **nested `@langchain/langgraph-sdk` 1.9.25** that `@langchain/react`
hard-pins - *not* the stale hoisted 1.2.0 copy, which is a different (legacy) entrypoint
and produced a wrong answer on the first pass:

| Feature | v1 |
|---|---|
| `getMessagesMetadata` | ✅ `useMessageMetadata` (`selectors.d.ts:216`) |
| `queue` | ✅ `useSubmissionQueue` (`:231`) → `{entries, size, cancel, clear}` |
| HITL resume | ✅ `respond` / `respondAll` (`use-stream.d.ts:261,295`) |
| thread switching | ✅ controlled `threadId` + `onThreadId` |
| edit / regenerate | ✅ `submit(input, {forkFrom: parentCheckpointId})` |
| **branch switching** | ❌ v1 `MessageMetadata` carries only `parentCheckpointId` and `optimisticStatus` |
| **stream rejoin** | ❌ `reconnectOnMount` is not on the v1 hook. The server implements rejoin (`run_manager.py:332-404`); the client cannot ask for it |

So repairing the drift is ~200 LOC in one file and restores most of it. **The two
features it cannot restore - branch switching and rejoin - are the honest remaining case
for assistant-ui**, alongside a thread-list UI that does not exist today.

Against that: assistant-ui **owns runtime state**, so it is an architecture change.
`chat-section.tsx` (1,054 LOC) plus a ~1,769-LOC vendored prompt-kit layer gets rebuilt,
with **zero frontend test coverage**, on the landing-page hero. Roughly 893 LOC of that
vendored layer is already dead or near-dead (`loader.tsx` 499 LOC with 1 of 12 variants
used; `source.tsx` 130 LOC and `blog-search-result.tsx` 134 LOC with zero importers).

Two things that must survive any composer or markdown swap, both load-bearing for Korean:
the IME composition guard (`prompt-input.tsx:158`, `!e.nativeEvent.isComposing`) and
`remark-breaks` (`markdown.tsx:70`).

If adopted, use `@assistant-ui/react-langchain`, **not** `@assistant-ui/react-langgraph`:
the latter's resume type is `{resume: string}` - string only - which the HitlCard's
`{decision, args}` payload cannot express.

## langchain-quickjs

**The premise that a Python agent cannot use it is wrong**, and that is the most important
finding here. `langchain-quickjs` **0.3.4** is an official LangChain package on **PyPI**
(published 2026-07-24), source in `langchain-ai/deepagents` at `libs/partners/quickjs`.
Python >=3.11. Only the *sandboxed language* is JavaScript.

- Drops in as `CodeInterpreterMiddleware()`. Install path is the first-class extra
  `deepagents[quickjs]` - and `pyproject.toml:10` already pins `deepagents>=0.6.12`, which
  declares `quickjs = ["langchain-quickjs>=0.3.3"]`.
- Needs `langchain>=1.3.14`; installed is 1.3.13, one patch below.
- ~25 MB of wheels (wasmtime 23 MB + quickjs_rs 2 MB), in-process. No Deno, no Docker, no
  JS toolchain. **wasmtime is the actual escape surface** and must be kept patched.
- 13 releases in ~4 months, API in beta. Pin exactly.

**Isolation.** QuickJS-in-WASM is a better fit for a public endpoint than any container
sandbox: the threats that dominate a GCP container - metadata-server SSRF at
`169.254.169.254` minting a real service-account token, env-var exfiltration, network
egress - are *structurally absent*, not configured away. Residual risks are CPU exhaustion
and token spend.

**Hardening that is not optional:** sync `ctx.eval()` has **no timeout parameter**, so an
infinite loop hangs the worker forever, and sync `invoke()` on a REPL with async PTC
bridges raises `ConcurrentEvalError`. Every execution path must be async. `memory_limit`
below the 64 MB default produces a garbled negative-pointer error instead of a clean
`MemoryLimitError`.

**"Dynamic subagents" is a separate feature.** A JS sandbox does not create subagents;
the two got bundled in the original framing. deepagents exposes `subagents=True` on the
middleware, but `task()` dispatches from *inside* a running eval and does **not** go
through the tool-calling path - so a HITL approval flow is not enforced per dispatch, and
`max_ptc_calls` does not cover it. The model can fan out with `Promise.all` inside one
eval, which is the real token-spend lever.

## GCP hosting

For this workload the 90-day $300 credit is a buffer, not the mechanism - **the Always
Free tier is what carries it**, and that does not expire. Steady state after the trial is
roughly **$1-4/month**.

Recommended shape: Cloud Run, `us-central1`, instance-based billing
(`--no-cpu-throttling`, required because in-process streaming needs CPU outside request
handling), `--min-instances 0`, **`--max-instances 1`**, `--execution-environment gen2`,
a **dedicated minimal service account**, Postgres staying on Neon.

Three things the first-pass analysis got wrong and that matter:

1. **`--max-instances 2` with the in-process queue is self-defeating.** The FIFO is
   process-local (`run_manager.py:57-61`). Two instances share no state, so two runs on
   one thread execute against the same checkpoint concurrently - verbatim the defect that
   disqualifies Aegra above. Either 1 instance, or keep Redis/ARQ.
2. **You are already on Neon** - verified live at `ep-flat-sky-a1k7fna6.ap-southeast-1`,
   Postgres 17.10, 11 MB, shared by web and agent. `web/lib/auth.ts:4-11` builds a Pool
   from `DATABASE_URL`. **Correction to an earlier claim here:** a fresh empty database
   does *not* refuse to start - `legacy_migration.py:309` guards the `users` lookup behind
   `needs_fallback_owner`, and `test_legacy_migration.py:157-186` pins that an all-tables-
   absent database migrates fine. Splitting the agent database off is therefore cheap.
3. **The build context is the repo root.** `content/` sits outside `agent/`, and
   `config.py:11-20` resolves it as `_AGENT_DIR/../content`.

Also: `content/` has **two consumers on independent pipelines** (Vercel rebuilds on push;
the Cloud Run image only updates on redeploy), so a baked corpus silently goes stale.
And SSE keepalive already exists via `sse-starlette`'s `EventSourceResponse` default 15s
ping (`routes/runs.py:145,222,297`) - confirm and tune, do not write new code.

**Four cost traps**, each more expensive than the entire rest of the stack: Cloud SQL
db-f1-micro + 10 GiB SSD minimum ~$9.4/mo; Memorystore Redis Basic 1 GiB $35.77/mo billed
on provisioned capacity; a global external ALB for a custom domain $18.25/mo standing; a
Serverless VPC Access connector ~$12/mo floor.

**Not Seoul.** `asia-northeast3` is Cloud Run Tier 2 ($0.0000336/vCPU-s vs $0.000024), and
because the free tier is a spending-based discount computed at Tier 1 pricing, deploying
there burns the allowance ~40% faster. Latency is largely moot - every request already
round-trips to Anthropic in the US.

**Trial expiry is destructive.** At day 90 the billing account closes and all projects are
stopped, with a 30-day recovery window. Keeping Postgres off trial-only infrastructure is
what makes that survivable.

## Unverified

- How Aegra derives its checkpoint `thread_id`. The migration-risk conclusion is sound but
  the mechanism was inferred, not read.
- Whether deepagents works under Aegra at all.
- Whether the hand-rolled `POST /threads/{id}/history` returns a shape v1's
  `useMessageMetadata` can consume - it was written against the v0.2 client.
- Whether `mode='call'` fully releases the QuickJS Runtime between calls.
- Real RAM/CPU footprint of an idle Aegra container. No published sizing; open issue #208
  reports high CPU after service start, unresolved.
- Cold-start latency for this specific image, against the hard 4-minute startup timeout.
- Whether anyone has run assistant-ui against Aegra. Not on Aegra's integration list.
