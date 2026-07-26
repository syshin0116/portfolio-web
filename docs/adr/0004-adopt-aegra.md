---
title: "ADR-0004: Adopt Aegra and delete the hand-rolled Agent Protocol server"
description: >
  Replace the 4,700-LOC hand-written Agent Protocol server with Aegra 0.9.24, keeping
  the graph, and discard the existing agent data rather than migrating it.
when_to_read: >
  Before changing the agent runtime, before pinning or bumping Aegra, or when
  wondering why run serialization is weaker than it used to be.
tags: [adr, agent, runtime, aegra, langgraph, deploy]
status: accepted
date: "2026-07-26"
deciders: ["@syshin0116"]
supersedes:
superseded_by:
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [../research/aegra-native-stack.md, ../plans/rag-restack.md, ../../DECISIONS.md]
template: adr
---

# ADR-0004: Adopt Aegra and delete the hand-rolled Agent Protocol server

> **status: accepted.** An earlier draft of this ADR, written the same day, proposed the
> opposite (keep the custom server, hold Aegra behind a spike). It was recorded as
> `proposed` precisely so the owner could decide, and the owner decided. **The premise
> that changed is that the existing agent data may be discarded** - which removes the
> blocker the earlier draft was built around.

## Context

`agent/src` is 5,947 LOC, of which roughly 4,700 is a hand-written
LangGraph-Platform-compatible Agent Protocol server - 41 routes, owner-scoped
authorization, a dual-mode run queue, 1,572 LOC of tests. The graph itself is ~96 LOC and
is host-agnostic. Aegra replaces the server, not LangGraph.

The earlier analysis rated the migration as XL and gated it on a checkpoint-identity
migration: local checkpoints are keyed `uuid5(ns, user_id + NUL + thread_id)`, Aegra keys
them differently, and getting that wrong would either orphan every conversation or leak
across owners. **That gate is gone.** The owner confirmed the agent data is disposable,
keeping only Auth.js accounts, and the live database holds 25 threads and 394 checkpoints
of personal test data - genuinely disposable. `threads` does not even have an `owner_id`
column yet, so the ownership migration has never run there.

Two further things were verified against Aegra 0.9.24 source and turned out to be
non-issues:

- A `CompiledStateGraph` needs no rebinding. `LangGraphService.get_graph()` does
  `graph.copy(update={"checkpointer": ..., "store": ...})` per request, so
  `create_deep_agent(...)` registers as-is.
- Anonymous per-visitor isolation is free: Aegra hard-codes `WHERE user_id = <identity>`
  on every threads/runs/assistants query, independent of any auth handler.

Nothing is deployed today, so there is no working production system to regress.

## Considered options

| Option | Pros | Cons |
|---|---|---|
| A. Adopt Aegra, discard agent data | Deletes ~4,500 LOC; Alembic migrations; real cron execution; cross-instance cancellation; upstream fixes arrive for free | Loses same-thread run serialization outright; pre-1.0 dependency with bus factor 1; `/models` must be rebuilt |
| B. Keep the custom server | Every recorded guarantee stays true; no new dependency | 4,700 LOC of protocol plumbing stays a personal maintenance burden; crons stay permanently dead; every upstream improvement has to be reimplemented |
| C. Adopt Aegra but migrate the existing checkpoints | Keeps conversation history | The highest-risk item in the whole plan, for 25 threads of test data |

## Decision

Adopt **A**. Register the existing deepagents graph with Aegra 0.9.24, delete the
hand-rolled server, and **discard the existing agent data** rather than migrating it.

Pin exactly: `aegra-api==0.9.24`, `aegra-cli==0.9.24`. **Never install the `aegra`
meta-package** - it is stuck at 0.2.0 (2026-02-11) and cannot be version-pinned
meaningfully. Hard floor `>=0.9.7`, because GHSA-m98r-6667-4wq7 was a HIGH-severity
cross-tenant IDOR fixed there.

Being native is the governing constraint: prefer Aegra's idioms over porting the existing
implementation. The point of adopting it is to stop maintaining a parallel one.

## Consequences

**Positive**

- ~4,500 LOC deleted; `agent/src` goes from 5,947 to roughly 1,450. The RAG layer, which
  is where the value is, survives 96% unchanged.
- Alembic migrations replace unreviewed boot-time DDL. Today `main.py:47-54` and
  `legacy_migration.py:346-347` run `CREATE`/`ALTER` against production on every container
  boot with no migration framework.
- Crons actually fire. The current ones are stored and never execute - there is no
  scheduler and nothing computes `next_run_date`.
- The spike (plan phase P0) turned "deepagents under Aegra is unverified" from a caveat
  into a gate with an acceptance test.

**Trade-offs**

- **Same-thread run serialization is lost outright.** `run_queue.py` gave owner-scoped
  FIFO with Redis leases and heartbeat crash recovery, chosen deliberately on 2026-07-11
  because "LangGraph checkpoints must not execute concurrently". Aegra parses
  `multitask_strategy`, stores it in `execution_params`, and **never reads it**. PR #462 is
  open. The stand-in is an in-process busy set that is correct only at
  `--max-instances 1`, and is a check rather than a lock. **This ADR reverses that part of
  the 2026-07-11 entry.**
- `@auth.on.*` handlers are **not dispatched** consistently across legacy streaming paths,
  and P0 found Aegra's AP v2 path/commands differ from upstream. The production frontend
  uses `/threads/{id}/stream/events`, but authorization still cannot depend on handler
  dispatch: the SQL predicate and outer ASGI middleware are the real boundary.
- Aegra with no auth file is **fail-open** (one shared `anonymous` identity), where the
  current server is fail-closed. A typo in `aegra.json` degrades an outage into an open door.
- Pre-1.0 with bus factor 1: `ibbybuilds` holds 629 of ~800 commits, three releases shipped
  in three weeks, and `server.py` will import `aegra_api.*` internals with no stability
  guarantee.
- `/models` is not Agent Protocol, so it must be rebuilt as a custom route or a static list.
- All existing conversation history is deleted. Accepted knowingly.

**Follow-ups**

- [ ] P0 spike: two-turn Korean conversation over `/runs/stream`, skills loading verified.
- [ ] `scripts/smoke.py` as the permanent gate for every version bump.
- [ ] Assert `len(AGENT_AUTH_SECRET) >= 32` at import so the process refuses to start.
- [ ] Confine `aegra_api.*` imports to one file with a comment listing them, so a version
      bump has a checklist rather than a surprise.
- [ ] Amend the 2026-07-11 `DECISIONS.md` run-serialization entry to record the reversal.
- [ ] Watch PR #462 and PR #385; if either merges, delete the corresponding stand-in.

## Revisit when

- PR #462 merges - the in-process run guard becomes dead weight and should be replaced by
  `multitask_strategy: "reject"`.
- Aegra goes quiet for a quarter, or the maintainer stops responding to a
  production-affecting bug. The fallback stays in the LangChain family (LangSmith
  Deployments), not back to a bespoke server.
- Traffic requires `--max-instances > 1`, at which point the in-process guard silently
  degrades to advisory and Redis becomes necessary.
- Aegra reaches 1.0 with a stated stability policy - revisit the exact-pin ritual.

## Changelog

- 2026-07-26: created as `proposed` recommending against Aegra; replaced the same day with
  this `accepted` decision after the owner confirmed the agent data is disposable.
