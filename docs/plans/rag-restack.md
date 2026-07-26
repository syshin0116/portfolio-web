---
title: "Plan: rebuild the agent on Aegra, get basic chat working, then evaluate"
description: >
  Rebuild the agent natively on Aegra + deepagents + assistant-ui, ship a working
  private chat end to end, then fork the evaluation harness off the same retriever
  interface, then harden and go public.
when_to_read: >
  Before picking up any restack work, before dispatching an agent onto a phase,
  or when deciding what comes next.
tags: [plan, aegra, assistant-ui, deepagents, retrieval, evaluation, deploy]
status: draft
updated: "2026-07-26"
owners: ["@syshin0116"]
refs:
  - ../adr/0008-chatbot-is-a-rag-evaluation-testbed.md
  - ../reference/retrieval-methods.md
  - ../research/aegra-native-stack.md
  - ../research/public-exposure.md
  - ../adr/0003-agent-code-changes-via-pr.md
  - ../adr/0004-adopt-aegra.md
  - ../adr/0005-adopt-assistant-ui.md
  - ../adr/0006-public-anonymous-chat-access.md
template: plan
---

# Plan: rebuild the agent on Aegra, get basic chat working, then evaluate

> **Status: draft, not started.** Phases are written to be dispatched to separate agents.
> Read [How to dispatch](#how-to-dispatch) first.

> **Read [ADR-0008](../adr/0008-chatbot-is-a-rag-evaluation-testbed.md) before touching
> anything here.** The purpose is comparing retrieval methods; the chat is an inspection
> surface. Simplification arguments that reason from corpus size are backwards.

## What changed since the first draft

This plan has been rewritten twice, both times because a premise turned out to be wrong.
Recording that, because the corrections are the useful part:

1. The first version was "deploy the existing stack, then decide about Aegra and
   assistant-ui." Superseded when the owner confirmed **the existing agent data is
   disposable**, which removed the checkpoint-migration blocker.
2. The second version kept the agent layer at 96% unchanged. Superseded when the owner
   scoped it in as a rebuild too, and then again when the actual goal turned out to be
   **method evaluation, not blog search**.

The sequencing rule now is the owner's: **get basic chat working first.** Not because
chat is the product, but because it is the only thing that proves the whole infrastructure
chain actually connects.

## Sequence

```
P0  Aegra spike (local)              gates everything
P1  Rebuild the agent layer          retriever Protocol + correct BM25 + build-time mirror
P2  Deploy to Cloud Run              still owner-only auth
P3  assistant-ui, preview then cut over
    ─────────────────────────────────  ✅ basic chat works end to end
P4  Evaluation harness (eval/)       forks off P1's Protocol; can run in parallel from here
P5  Public hardening                 anonymous identity, guard, GC, budget caps
P6  Go public                        IRREVERSIBLE
```

**The old P1 "close three content leaks" is deleted, not rescheduled.** All three fixes
patched files that P1 now deletes. Doing both would be the same work twice.

## Versions

Exact `==` pins. No `^` on Aegra or assistant-ui.

| Package | Pin | Note |
|---|---|---|
| `aegra-api`, `aegra-cli` | `==0.9.24` | **Never `pip install aegra`** - that meta-package is stuck at 0.2.0 |
| `langgraph` | `==1.2.9` | Aegra's own lock resolves 1.2.6. Rollback pin documented |
| `langgraph-sdk` | `==0.4.2` | `Auth`, `AuthContext`, `ServerRuntime` |
| `langgraph-checkpoint-postgres` | `==3.1.0` | Above Aegra's locked 3.0.4, so untested by Aegra CI. Rollback: `==3.0.4` |
| `deepagents` | `==0.6.12` | `permissions=` is new in 0.6.0 |
| `langchain` | `==1.3.14` | |
| `pyjwt` | `>=2.10` | replaces 130 LOC of hand-rolled base64url + HMAC |
| `@assistant-ui/react` | `0.14.27` | |
| `@assistant-ui/react-langgraph` | `0.14.12` | **not** `react-langchain` |
| `@langchain/langgraph-sdk` | `1.9.28` | |

**Drop:** `chromadb` (zero call sites), `fastapi`, `uvicorn`, `sse-starlette`, the `arq`
extra, `@langchain/react`, `@langchain/langgraph`.

---

## P0 - Aegra spike, local `~1 day` `GATES EVERYTHING`

Turn "deepagents under Aegra is unverified" into a step. Aegra's repo has zero mentions of
deepagents.

- `aegra.json` at the repo root: `dependencies: ["./agent/src"]`,
  `graphs: {"agent": "./agent/src/agent/graph.py:graph"}`. No `auth` or `http` block yet.
- Install `aegra-api==0.9.24 aegra-cli==0.9.24`; confirm no resolver conflict.
- Minimal `graph.py` rewrite: drop `checkpointer=`/`store=` and `_lazy_graph`. Aegra does
  `graph.copy(update={checkpointer, store})` per request, so a compiled graph registers
  as-is. **The `backend=` factory form is deprecated** (0.5.0, removal 0.7.0) - pass a
  `BackendProtocol` instance.
- `aegra serve` against local Postgres; confirm the Alembic tables appear.
- `scripts/smoke.py` on `langgraph_sdk.get_client`. **This becomes the permanent gate for
  every version bump.**

**Accept:** a **two-turn** Korean conversation completes over `/runs/stream`; stream events
are `messages/partial` / `messages/complete` / `updates`.

> The second turn is not decoration - it is the exact regression from Aegra issues #224
> (fixed 0.7.5) and #352 (fixed 0.9.14), both deepagents multi-turn bugs. If it fails,
> **stop and report**.

---

## P1 - Rebuild the agent layer `~3 days`

From scratch, native to deepagents 0.6.12. Absorbs the old leak-fix phase.

### P1.1 The retriever Protocol - do this first
- `agent/src/agent/retrieval/protocol.py`, **stdlib only, zero dependencies**. `Hit`,
  `Retrieval`, `Corpus`, `Retriever`, `Stage`, `Pipeline`.
- **It lives in `agent/`, not in `eval/`.** That is what makes it physically impossible for
  the chat and the harness to drift onto different interfaces - the failure ADR-0008
  follow-up 4 exists to prevent.
- `DocId` is **always** the content-relative posix path. `Retrieval.doc_ids()` collapses
  chunk hits to a deduped document ranking, which is the single place chunk-vs-document
  asymmetry is resolved so one qrel scores every method.
- `rank` is authoritative; `score` stays **raw and method-native**. Never normalise inside
  a retriever.
- `Stage` has the same shape as `Retriever`, so reranking, fusion, and graph expansion
  compose without special cases.
- `agent/src/agent/retrieval/registry.py`: `name -> factory`. **The chat and the eval sweep
  both read this**, so they cannot enumerate different method sets.

### P1.2 The build-time published-only mirror
- `scripts/build_index.py` copies **only published posts** into `agent/.index/posts/`, and
  that mirror becomes the container's only content root.
- This is the draft boundary, and it is the whole reason it cannot be bypassed. Today the
  boundary is a runtime predicate that three code paths must each remember; two forget and
  the third is wrong. **In the rebuild a draft is not filtered, it is absent from the
  image.**
- Fail closed: `fm.get("draft") is not True and fm.get("private") is not True`, and a YAML
  parse error is a **build failure**, not a silent skip. Three files parse as non-dict
  today, one of which is a link hub.
- Same step emits `catalog.json`, the fitted BM25 index, the resolved wikilink graph, and
  the Kiwi user dictionary. That moves **6.11s of tokenization** out of the first visitor's
  request.
- CI test: walk `agent/.index/posts/` and fail if any file has `draft: true`. This is what
  makes the boundary auditable rather than aspirational.

> Note the corpus currently has **zero** `draft: true` posts, so all of this guards nothing
> today. That is exactly why the bugs survived review, and exactly why the boundary should
> be structural before it matters.

### P1.3 The corrected BM25 baseline `BLOCKER for everything in P4`
A broken baseline invalidates every comparison drawn against it. Three independent fixes,
all needed - see [the registry](../reference/retrieval-methods.md#the-korean-tokenizer-problem):

1. **User dictionary** built from the corpus. `add_user_word("도커", "NNP")` restores
   `['도커']`, verified. Frontmatter `tags` are the best source - the author has already
   hand-labelled the domain vocabulary.
2. **Drop `VV` and `VA` from the keep-list.** They are what survives when an unknown noun
   is mis-analysed, which is what turns a tokenization failure into a confident wrong
   answer instead of an empty result.
3. **Index the surface form alongside morphemes**, so a term the dictionary has not caught
   up with still matches exactly.

Also remove the `score / max(scores)` normalisation: it forces the top hit to exactly 1.000
for **any** query including nonsense.

**Accept:** executable tests, not inspection. `도커` recall@13 goes 0/13 → 13/13; macro
recall@10 goes 0.323 → 0.605; a nonsense query scores measurably below a real one.

### P1.4 Native composition
- **No content backend route.** `ls`/`glob`/`grep`/`read_file` are in the compiled ToolNode
  **unconditionally**, whatever you pass as `tools=` - they are only dangerous if a backend
  route points them at content. Deleting the `/blog/` route removes the leak class.
- **Mount `/skills/`** on a read-only FilesystemBackend and pass `skills=["/skills/"]`.
  Skills have never loaded: an absolute host path goes into `SkillsMiddleware`, which
  resolves *through the backend*, misses every route, and falls through to `StateBackend`.
  Verified: mounting the route loads all six SKILL.md with zero warnings.
- **Collapse six SKILL.md files into one workflow skill.** Six files each restating one
  tool's docstring is duplication under the upstream model - skills are for task
  instructions too large for the prompt, discovered by progressive disclosure.
- `FilesystemPermission` (new in 0.6.0) replaces the 45-LOC `ReadOnlyFilesystemBackend`
  subclass. **It cannot express "frontmatter lacks draft"** - it is pure path globbing.
  That job belongs to P1.2, not here.
- **Read the trusted identity from `configurable["langgraph_auth_user"]`, never
  `configurable["user_id"]`.** Aegra sets `user_id` with `setdefault`, so a client
  overrides it and reaches another user's memory namespace. Better still,
  `runtime.server_info.user.identity` works inside middleware with no escape hatch.
- Delete: `read_only_backend.py`, `result_formatter.py`, `ripgrep_search.py` (shells out
  for a 2.4 MB corpus while its own in-process fallback is correct), and 32 LOC of dead
  code in `prompts.py`.

**Accept:** a test fails if a spoofed `configurable.user_id` changes the resolved memory
namespace; skills load with zero warnings; the graph compiles with a stable node set.

---

## P2 - Deploy to Cloud Run `~1.5 days`

Still owner-only auth. First time anything has been deployed.

- Dockerfile is greenfield - Aegra's own copies `libs/aegra-api/...` paths that do not
  exist here. `python:3.12-slim-bookworm`.
- **Two Neon free projects in a US region** ([ADR-0007](../adr/0007-postgres-on-neon-split-projects.md)):
  one for the agent, one for Auth.js. Zero code changes - both sides read `DATABASE_URL`.
  **Neon project regions are fixed at creation**, so this is only available now.
- Use the **direct** endpoint, not `-pooler`: `checkpointer.setup()` issues
  `CREATE INDEX CONCURRENTLY`, which Neon documents as direct-connection-only.
- Deploy: `--no-cpu-throttling --timeout 3600 --max-instances 1 --concurrency 20`, a
  **dedicated minimal service account**, Postgres pool knobs turned down (Aegra opens up to
  ~50 connections by default).
- `--max-instances 1` is load-bearing: it is what makes P5's in-process guard correct.
- Set the Anthropic organization spend cap. Grep startup logs for Aegra's
  data-not-isolated warning.

**Accept:** `/health` 200 from the Cloud Run URL; `scripts/smoke.py` passes against it;
cold-start-to-first-token measured and recorded.

---

## P3 - assistant-ui `~3 days`

Preview URL first; `chat-section.tsx` stays live until cutover.

- `npx assistant-ui@latest init` inside `web/`, then `npx shadcn@latest add
  @assistant-ui/thread @assistant-ui/thread-list`.
- `useLangGraphRuntime` + `unstable_createLangGraphStream`. The adapter makes **exactly one
  SDK call** (`client.runs.stream`); `load`, `create`, `delete`, `getCheckpointId`, and the
  thread-list adapter are all your callbacks.
- In `load()`, read `state.interrupts` **first** - Aegra returns interrupts as a top-level
  field, so the quickstart's `state.tasks[0].interrupts` is the wrong read here.
- **Pass `getCheckpointId`.** Omitting it silently hides Edit and Regenerate, which reads
  as a missing feature rather than missing config.
- Async `onRequest` token hook with a 60s margin. Capturing the token once at mount 401s
  mid-conversation.
- `remarkPlugins={[remarkGfm, remarkBreaks]}` with components memoised at module scope.
  **remark-breaks is load-bearing for Korean.**
- **Korean IME: verify with a Playwright test, do not assume.** Highest-risk regression.
- Then cut over and delete: 4,489 LOC from `agent/src`, 777 LOC of tests asserting deleted
  internals, 1,769 LOC of vendored prompt-kit, `chat-section.tsx` (1,054).

**Accept:** a full multi-turn Korean conversation against deployed Aegra; reload restores
the thread; the IME test passes; `rg -n 'from api\.|import api\.|arq|chromadb' agent/src`
returns nothing.

### ✅ Basic chat works end to end here

---

## P4 - Evaluation harness `~4 days` `parallelisable from P1`

The actual deliverable. Forks off P1's Protocol and can proceed alongside P2 and P3.

- **`eval/` as a uv workspace member** next to `agent/`. The split line is **servable vs
  not**: a method that could run on Cloud Run lives in `agent/src/agent/retrieval/`; a
  method needing torch, a 2 GB checkpoint, or a JVM lives in `eval/blogeval/lab/`. Both
  satisfy the same Protocol, so promoting a lab method is moving one file. This is what
  keeps the image slim without forking the interface.
- **Bootstrap the qrels from the 174 aliased `[[target|alias]]` links.** The alias is the
  author's own Korean surface form for a target document - free known-item ground truth in
  quantity, which no public corpus has. Use it before spending anything on LLM-generated
  queries.
- Pin the corpus by **git tree sha of `content/`**. The harness never reads live `content/`.
- **Report `coverage` alongside recall@k, always.** The wikilink graph covers 123 of 336
  files, so a graph method that declines to answer on two-thirds of queries would otherwise
  look strong on the third where it fires.
- **Do not headline nDCG.** On four smoke queries nDCG@10 read 1.000 for every one while
  recall@10 ranged 0.23 to 0.77. It saturates when relevant-sets are large and ungraded.
- Local `results/<tree-sha>/` JSON is the **system of record**; LangSmith's free tier keeps
  traces 14 days and caps at ~3 full sweeps a month. Use it as a comparison UI, not storage.
- A committed pytest regression gate on macro recall@10 - the thing that would have caught
  the tokenizer bug.
- Emit a Markdown leaderboard and SVG plots, so results drop into a blog post without
  retyping. This matches the repo's existing `.mmd` → `.svg` diagram convention.

**Accept:** one full sweep over at least three methods produces a leaderboard, a
per-query table, and plots, reproducibly, from a pinned corpus and a pinned query set.

**First experiment:** corrected BM25 vs one dense method vs their RRF fusion, over the
alias-derived query set, reporting recall@k, MRR, and coverage. Small on purpose - its job
is to prove the harness, not to settle anything.

---

## P5 - Public hardening `~2 days` `GATE for P6`

Nothing here is optional. Full detail in
[`public-exposure.md`](../research/public-exposure.md).

- **The governing constraint:** `@auth.on.*` handlers are **not dispatched** on
  `/threads/{id}/runs/stream`, `/runs/wait`, the stateless `/runs*` variants, or
  `/threads/{id}/events` - which is exactly the path assistant-ui uses. PR #385 is still
  open. **The SQL predicate is the boundary; handlers are hygiene.**
- `agent/src/auth.py` with PyJWT. **Assert `len(AGENT_AUTH_SECRET) >= 32` at import so the
  process refuses to start** - Aegra with no auth file is **fail-open**, where the current
  server is fail-closed.
- Anonymous identity: Turnstile-gated `anon:<uuid4>` minted in
  `web/app/api/agent-token/route.ts`. Aegra's `WHERE user_id = identity` predicate isolates
  them automatically. Return `is_authenticated: True` even for guests.
- `GuestRunGuard` as a **pure ASGI class**, not `BaseHTTPMiddleware` - the latter interferes
  with sse-starlette's disconnect detection, which is how `on_disconnect="cancel"` works.
  Per-identity token bucket (429) and per-`(identity, thread)` busy set (409).
- Tier differences go in **the model instance and backend routes**, never the middleware
  list - Aegra requires identical topology across access contexts. `wrap_model_call` adds
  no nodes, so anything expressible there is free to vary.
- `/admin/gc` plus Cloud Scheduler. **Deleting a thread does not delete its checkpoints** -
  sweep children before parents. Neon free has no `pg_cron`.
- Provider spend cap, per-run call limits, a dollar budget middleware (LangChain ships none).

---

## P6 - Go public `~1 day` `IRREVERSIBLE`

- Verify the P1.2 mirror gate and the P5 guard on the **deployed** service, by actually
  exceeding the rate limit from a browser and firing two concurrent submits on one thread.
- Confirm GC measurably reduces checkpoint row count.
- Add a stale-run sweep: with `REDIS_BROKER_ENABLED=false` there is no lease reaper, so an
  instance killed mid-run leaves a thread busy forever.
- Decide LangSmith tracing **before**, not after - traces carry full prompts and full
  retrieved content.
- Watch Anthropic spend daily for week one.

---

## Risks

| | Risk | Mitigation |
|---|---|---|
| `HIGH` | **Same-thread run serialization is lost.** Aegra parses `multitask_strategy` and never reads it. This reverses the 2026-07-11 decision | P5's busy set. Honest limits: in-process, correct only at `--max-instances 1`, a check rather than a lock |
| `HIGH` | Auth handlers skipped on the streaming path | SQL predicate is the boundary. Pin `aegra-api >= 0.9.7` (GHSA-m98r-6667-4wq7 was exactly this) |
| `HIGH` | Client-supplied `configurable.user_id` wins over the server's | Read `langgraph_auth_user`. Fix in P1, before anything deploys |
| `HIGH` | Unbounded LLM spend from anonymous traffic. Aegra lists rate limiting as "Not yet planned" | Anthropic org spend cap is the only provider-enforced hard stop |
| `MED` | **Evaluating with a broken baseline.** Every number produced against it is invalid, not merely pessimistic | P1.3 is a blocker for P4, with executable acceptance tests |
| `MED` | Pre-1.0 churn. `aegra-api` shipped three releases in three weeks; four `unstable_` assistant-ui APIs on the happy path | Exact pins, committed lockfiles, `smoke.py` as the bump gate |
| `MED` | Eval cost creep - embedding N models × M queries × K retrievers plus judge calls | Cache embeddings by fingerprint; local results as system of record; `upload_results=False` while iterating |
| `MED` | The eval and the chat drift onto different retriever interfaces | The Protocol lives in `agent/`, and one registry feeds both |

## Decisions needed

1. **Cloud Run region.** Seoul (next to you) or a US region (next to Anthropic and, per
   ADR-0007, next to the relocated Neon)? The DB has no Korean client, so the US pairing
   looks right, but the SSE leg is browser-to-Cloud-Run direct.
2. **Guest model tier** once public: same model for everyone, or a cheaper one for guests?
   The largest cost lever, and it changes perceived quality for exactly the new audience.
3. **Guest thread persistence**: httpOnly cookie (durable, pseudonymous identifier on a
   site with no cookie banner) or stateless runs with history client-side?
4. **Version policy**: adopt `langgraph==1.2.9` / `checkpoint-postgres==3.1.0` (above what
   Aegra's CI tests), or match Aegra's lock at 1.2.6 / 3.0.4 for the first deploy?
5. **The skill-restriction chips** in the current UI: rebuild as run config, or drop? Today
   they inject a fake system message that lands in checkpointed history and replays.

## Open questions

- Does Aegra issue #468 reproduce? P0 answers it.
- How does the assistant-ui adapter surface 409 and 429 - a usable error state, or a
  generic stream failure?
- Cold-start-to-first-token for this image. Decides whether `min-instances=1` is worth it.
- PR #462 (multitask) and #385 (stream auth) - if either merges, part of P5 becomes dead
  weight. Watch rather than design around permanently.
- Which embedding model for the first dense arm. Pending the Korean model comparison.

## How to dispatch

- **Read [ADR-0008](../adr/0008-chatbot-is-a-rag-evaluation-testbed.md) and
  [ADR-0003](../adr/0003-agent-code-changes-via-pr.md) first.** Purpose, then process:
  feature branch, PR, never a direct commit to `main`, never merge on red CI.
- One phase per agent. Give it the phase section plus the linked research, not this file.
- **P0 gates everything. P1.3 gates P4. P1.2 and P5 gate P6.**
- **P1.1 first within P1** - the Protocol is what everything else plugs into.
- P4 parallelises with P2 and P3 once P1 lands. Nothing else parallelises cleanly, because
  `graph.py` is touched by P0, P1, and P5.
- Every phase ends with its acceptance check actually run, and the result stated plainly.
