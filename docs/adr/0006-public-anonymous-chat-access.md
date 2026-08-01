---
title: "ADR-0006: The chatbot is public, with Turnstile-gated anonymous subjects"
description: >
  Open the chatbot to visitors with no login, minting short-lived tokens with random
  anon:<uuid> subjects so every existing owner-scoping path keeps working unchanged.
when_to_read: >
  Before changing the chatbot's access model, the token-minting route, anonymous
  retention, or the capability tiers.
tags: [adr, auth, security, anonymous, public, rate-limiting]
status: accepted
date: "2026-07-26"
deciders: ["@syshin0116"]
supersedes:
superseded_by:
updated: "2026-08-02"
owners: ["@syshin0116"]
refs: [../research/public-exposure.md, ../plans/rag-restack.md, 0004-adopt-aegra.md, 0007-postgres-on-neon-split-projects.md]
template: adr
---

# ADR-0006: The chatbot is public, with Turnstile-gated anonymous subjects

> **status: accepted; the application hardening is implemented, but public rollout is
> still gated.** The production guest flags and recurring retention Scheduler remain
> disabled until the launch, billing, browser, and exact-project operational gates in the
> public rollout runbook pass.

## Context

The chatbot currently fails closed: `web/lib/allowed-user.ts` gates sign-in on
`AUTH_ALLOWED_EMAILS`, `/api/agent-token` mints only for an allowed session, and the
agent rejects every path except `/ok` and `/info` without a valid HS256 JWT. Every
resource is scoped to the token subject, which is an Auth.js `users.id` - a decision
recorded in `DECISIONS.md` on 2026-07-11.

The goal is now a chatbot any blog visitor can use without signing in. That contradicts
the recorded design, so it needs a record of its own.

The structurally important finding: **nothing in `agent/src` cares where a subject came
from.** `auth.py:174` reads `claims["sub"]`, and from there `deps.get_user_id`,
`resource_scope`, every `owner_id` filter in `db.py`, and `graph._memory_namespace` all
operate on an opaque string. So anonymous access does not require touching the
owner-scoping code at all - only the one file that mints tokens.

Investigation also surfaced two **live content-leak bugs** and several route-level gaps
that are latent today and become exploitable the moment the gate comes off. Those are
detailed in [`public-exposure.md`](../research/public-exposure.md) and are the reason
this ADR carries a rollout gate.

## Considered options

| Option | Pros | Cons |
|---|---|---|
| A. Random per-session `anon:<uuid4>` subject, Turnstile-gated, short TTL | Reuses every existing owner filter unchanged; per-visitor isolation for free; one file changes | Needs a Turnstile integration and a cookie; anonymous threads need retention |
| B. One shared `public` owner id | Trivial | **Unsafe.** `db.search_threads` filters on `owner_id` alone, so a shared owner is a full cross-visitor read of every conversation |
| C. Client-supplied identity header | No infrastructure | **Unsafe.** Forgeable - an attacker sets a real Auth.js `users.id` and reads the owner's threads |
| D. Separate unscoped code path for anonymous | Avoids minting tokens | Two authorization paths, twice the places to get it wrong, and the scoped one is already tested |
| E. Stay private | No new surface | Does not meet the goal |

## Decision

Adopt **A**. `web/app/api/agent-token/route.ts` gains an anonymous branch: verify a
Cloudflare Turnstile token via siteverify, then mint with subject `anon:<uuid4>`, scope
`anon`, and a 300s TTL, persisting the uuid in an httpOnly `SameSite=Lax` cookie so a
visitor keeps history on that device. The allowed-email and admin-scope paths are
unchanged. **No owner-scoping code changes.**

Capabilities are tiered:

| | Anonymous | Signed-in | Owner (`admin`) |
|---|---|---|---|
| The six curated search tools | yes, published posts only | yes | yes, drafts included |
| Generic filesystem tools (`ls`/`glob`/`grep`/`read_file`) | **no** | **no** | **no** - route removed for everyone |
| Persistent `/memories/` | no (thread-scoped only) | yes | yes |
| Model selection | no - server-pinned | limited | yes |
| `/store`, `/crons`, `/assistants`, `/models` | denied | limited | yes |
| Code interpreter | off by default; enable only if P4.5 gain and P5 budget/abuse gates pass | owner/eval experiment first | owner first |
| Dynamic subagents | off by default; bounded tier only after P4.5/P5 gates | owner/eval experiment first | bounded |
| Thread retention | ~14 days, GC'd | persistent | persistent |

The anonymous root model is bound, in literal order, to exactly
`keyword_search`, `semantic_search`, `metadata_filter`, `graph_traverse`, `list_posts`,
and `read_post`. Startup and every graph creation assert that this list is unique and
unchanged; adding a seventh root tool fails closed. The guest prompt carries the complete
retrieval workflow inline and mounts no skill. Deep Agents' filesystem, todo, skills,
QuickJS, and `task` schemas are removed from the guest model request, and the same
middleware rejects a forged or hallucinated call before tool execution. Hiding a schema
alone is not treated as an authorization boundary.

The production HTTP stack is pinned outer-to-inner as `GuestIngressGuard ->
NativeThreadGuard -> GuestRunGuard`. After authentication, the outer boundary charges
every guest request before route lookup, query parsing, body parsing, or a database read:
exact `POST /threads` uses the process-local creation bucket (6 per identity and 60
globally per hour), while every other path uses the request bucket (30 per identity and
180 globally per minute). Invalid, malformed, and unknown requests therefore consume
cheap ingress capacity. Only a valid paid command that survives Native ownership/status
checks reaches the inner paid bucket (4 per identity and 24 globally per minute) and
durable daily ledger. A valid foreign-thread command returns the hidden 404 after spending
only its outer request token; it spends neither a paid token nor ledger reservation.
Non-spending requests never reserve the paid ledger, and exhausting one class cannot
consume or reset another.

All process-local identity state uses only a SHA-256 digest of the canonical subject and
is bounded to 1,024 entries. At the cardinality boundary, an entry is prunable only when
it has no active stream lease, has been inactive for at least the longest configured
identity window, and every bucket it ever used is fully replenished. Guest SSE subscriptions
hold a `finally`-released process-local lease for their entire downstream response, capped
at two per identity and four globally. Owner traffic bypasses these guest controls.

Thread creation additionally has a durable storage admission boundary: at most six stored
canonical guest threads per identity and 256 globally. One domain-separated global
PostgreSQL transaction advisory lock covers the existing-owner lookup, exact canonical
`anon:<uuid>` regex counts, and the complete downstream `POST /threads` response, so a
concurrent process observes the first committed row before deciding. Retention-expired
rows continue to count until checkpoint-first GC actually removes the parent. Reusing an
existing owned ID is idempotent even at a cap; a foreign collision is hidden as 404. A
lock or count failure returns 503 instead of admitting optimistically.

`run.start` accepts exactly one client-supplied `user` message. Its content is either one
non-empty bounded UTF-8 string or one to eight exact assistant-ui
`{"type":"text","text":"..."}` blocks with a 16 KiB aggregate text ceiling. Client
assistant/tool history, tool-call fields, system roles, files, images, and every other
content-part shape are rejected before paid rate, spend, or dispatch (after the cheap
outer ingress charge). The server replaces the accepted client message ID with a unique
checkpoint ID for every submission, while state and SSE public projection restore the
original safe client ID so assistant-ui correlation remains native. Server checkpoint
state remains the only source of prior conversation history. Bodyless guest reads and
run-cancel routes reject any actual payload bytes, including bodies sent without a
`Content-Length` header.

Both paid guest methods pass the strict guest wire validator before taking a mutation
claim. Native-valid but guest-invalid `run.start` and `input.respond` bodies reach the
canonical guest 400 after the foreign-thread hiding check, without consuming the paid
bucket or budget and without reading graph state or dispatching; the already-consumed
outer request token bounds repeated database ownership reads. Valid guest commands
require an already-created owned thread; a command waiting behind retention GC cannot
resurrect the deleted identifier as a new thread. Owner commands keep Aegra's native
behavior and do not take the guest lock.

Each valid guest command opens a dedicated, unpooled PostgreSQL transaction and takes a
deterministic per-thread transaction-scoped advisory lock before ownership, status, and
graph-state validation. The lock remains held through the local capacity claim, the
inner rate/budget guard, and Aegra's downstream scheduling response. Cancellation drains
rollback and connection cleanup even after another cancellation request. Guest resumes
additionally require an interrupted thread and root namespace. Their exact 32-character
lowercase-hex ID must equal the sole pending interrupt returned by LangGraph's latest
official root `aget_state(..., subgraphs=False)` snapshot; checking only the ID format or
only `Thread.status == "interrupted"` is insufficient because a client can retain an ID
from an earlier interrupted run.

The state read is bracketed by fresh owner-scoped thread reads and is accepted only when
status, graph ID, and `updated_at` are unchanged. A row that disappears or changes owner
during validation returns the same hidden 404; a changed or ambiguous state is a 409,
and a failed or five-second timed-out state read is a 503. None reaches rate consumption,
durable reservation, or dispatch. A PostgreSQL row lock is deliberately not held across
command scheduling because Aegra must update that same row before returning.

Retention GC first performs a plain bounded candidate read. For each candidate it tries
the same per-thread advisory key in the GC session's outer transaction, then performs an
exact owner/policy/expiry/status recheck with `FOR UPDATE SKIP LOCKED`, deletes checkpoint
children, and deletes the thread parent. The transaction-scoped lock is released only
when that outer transaction commits the parent deletion; an advisory- or row-contended
candidate is skipped for a later sweep. This order prevents GC from row-locking a
command's thread while that command is trying to commit Aegra's busy state, and prevents
a command from observing the MVCC-visible old parent between deletion and commit.

This is cross-process coordination, not a claim that command scheduling and retention
are one atomic transaction. PostgreSQL releases the command advisory lock if its
dedicated backend connection is lost; the downstream request could theoretically
continue without that lock because there is not yet a durable command claim or shared
transactional scheduling queue. Production therefore keeps the existing single-instance
deployment and process-local limiter, and multi-instance rollout remains gated on that
stronger boundary. Owner resumes remain under Aegra's native behavior unchanged.
Ordinary guest `run.start` is rejected while its thread is waiting for input.

Once accepted, the guest guard canonicalizes the request, consumes the process-local
rate token, reserves the durable worst-case amount, and calls Aegra immediately;
post-dispatch failures remain intentionally charged.

**Rollout remains gated.** The code boundary does not activate guest flags, inject an
OpenAI credential, approve a paid budget, or unpause recurring GC. The Scheduler must be
reviewed and proven active before anonymous token issuance is enabled; leaving it paused
is a launch blocker, not an alternative retention policy.

## Consequences

**Positive**

- The chatbot becomes usable by the audience the blog actually has.
- The perimeter is one file, so the change is small and reviewable.
- Forcing this decision surfaced two live content-leak bugs and a missing rate limiter
  that were latent under the private gate. Those get fixed either way.

**Trade-offs**

- **This partially reverses the 2026-07-11 owner-scoping entry**, whose wording assumes
  every subject is an authenticated Auth.js user. The mechanism survives; the premise
  does not.
- Anonymous threads accumulate in a capped free-tier Postgres and need a GC that deletes
  checkpoints explicitly - `runs` cascade from `threads`, **checkpoints do not**, and the
  checkpoint tables are what actually consume the cap.
- Redis-off local execution has no native crash reaper. Each guest graph execution
  therefore owns a dedicated unpooled PostgreSQL physical connection and deterministic
  session advisory lock plus one of four global session-advisory execution slots until
  Aegra commits terminal run/thread state or its owning execution task ends. Both locks
  live on the same physical connection and are acquired before graph compilation. This
  caps guest graph execution across instances and overlapping revisions, while a
  process-local four-attempt acquisition semaphore bounds transient connection pressure.
  It does not authorize lifting the single-instance deployment boundary because the
  process-local traffic limiter remains a separate constraint.
- The owner monitor starts immediately after lock and slot acquisition, before graph
  compilation or yield, and spans both compiled-graph execution and the Aegra finalizer.
  Each monitor races one persistent owner-completion task against a database poll with a
  two-second query deadline. Its deterministic heartbeat is between one and five seconds,
  so four occupied slots produce at most four steady-state liveness queries per second.
  A pending poll is always cancelled and awaited; a poll that does not drain causes the
  physical connection to be invalidated. This cannot consume the bounded ORM pool needed
  by concurrent finalizers, and an owner-task failure cannot leave a permanent polling
  lock.
- The 15-minute recovery threshold selects candidates, but recovery may mutate only a
  candidate whose same-key transactional liveness lock and the shared guest-thread lock
  are both acquired. Its exact `thread`/`runs` recheck uses
  `FOR UPDATE OF t, r SKIP LOCKED`, so one row-locked candidate cannot stop the rest of a
  bounded sweep. The recovery and GC `batch_size` values cap successful mutations rather
  than initial candidates: each materializes at most 2,000 ordered candidates, skips
  contended or changed rows in advisory-lock-before-row-lock order, and stops at the
  requested success count of at most 1,000. The independent materialization cap remains
  finite while leaving room to replace locked head rows even at the maximum success
  batch. If session loss makes the liveness lock acquirable while its owner still exists,
  the atomic marker and trigger below fence every late owner write.
- A terminated PostgreSQL backend necessarily destroys its session lock before the
  monitor can drain its owner. Recovery therefore writes a namespaced marker into that
  run's `execution_params` in the same active-to-error UPDATE. Project schema migration
  `0002_recovered_guest_run_fence` installs a `BEFORE UPDATE` trigger that makes a marked
  run monotonically terminal. Aegra 0.9.24 updates the run before the thread in one
  `finalize_run` transaction, so a late success, error, interrupt, worker, or API writer
  fails before it can overwrite either recovered status. DELETE remains allowed.
- Project migration `0003_guest_execution_quarantine` adds one durable row keyed by
  `(run_id, thread_id, identity)`. Recovery writes `recovered_at = clock_timestamp()` in
  the same transaction as the immutable run marker and released thread; statement time
  is required because transaction-start `CURRENT_TIMESTAMP` would make a long recovery
  transaction appear older than it is. An unresolved row has a non-null `recovered_at`
  and null `drained_at`. Guest `run.start` checks that exact owner/thread boundary while
  holding the same guest-thread advisory lock and rejects it before ownership, capacity,
  spend reservation, or dispatch. Both the initial GC candidate read and its exact
  locked recheck exclude unresolved rows, preventing both deletion and batch starvation.
- The owner monitor has the same durable ordering invariant on normal and abnormal
  exits. On a normal owner exit, it first observes the owner task terminal, cancels and
  awaits any pending database poll, commits `drained_at = clock_timestamp()` through a
  new bounded unpooled connection, and only then unlocks or invalidates the still-live
  fence. On fence loss or abnormal monitor termination, it first boundedly cancels and
  awaits both the Aegra owner and pending poll, then commits the same proof before
  invalidating any surviving fence. A poll that cannot drain may require fence-session
  invalidation first; recovery is then fail-closed by an unresolved quarantine until the
  subsequent proof commits, and a proof-write failure never fabricates resolution. If a
  proof arrived before recovery, the recovery upsert fills only `recovered_at` and
  preserves `drained_at`. If a hard process crash leaves no monitor to write the proof,
  elapsed time never resolves the quarantine: later maintenance sweeps and replacement
  starts remain blocked until an operator establishes equivalent external drain proof.
  Once both timestamps exist, a normal follow-up may use a new unmarked `run_id`, and
  expired-thread GC may again delete checkpoint children before the parent.
  Maintenance imports both identity and recovery-marker contracts from side-effect-free
  modules and does not require the runtime authentication secret.
- LLM spend becomes a function of traffic rather than of one person's usage. The only
  provider-enforced hard stop is the Anthropic org-level spend limit; everything else
  slows the burn.
- Reputational surface: content generated under this domain by anonymous prompting.
  Cost controls do nothing about a screenshot.
- `web/lib/allowed-user.ts` **fails open** in non-production when `AUTH_ALLOWED_EMAILS`
  is empty. Harmless for a private chat UI, not harmless now.

**Follow-ups**

- [x] Remove the `/blog/` filesystem route and replace the raw `ripgrep_search` path
      with published-corpus retrieval (P3.1).
- [x] Add draft-exclusion regression tests through all six tools (P3.2) - the existing
      security tests never covered this, which is why the bugs survived.
- [x] Turnstile-gated anonymous token minting (P3.3; launch flags remain off).
- [x] `anon` scope route allowlist; strip `configurable.model`; force
      `multitask_strategy="reject"`; fix the seeded default model (P3.4).
- [x] Outer ingress, inner paid rate limiting, SSE leases, durable storage admission,
      and provider spend caps (P3.5; paid public launch remains separately gated).
- [x] `expires_at` + bounded GC that calls `checkpointer.adelete_thread` first,
      including session-fenced stale Redis-off guest-run reconciliation (P3.6).
- [x] Deterministic 16 KiB UTF-8 `read_post` truncation with an explicit marker
      (P3.7 partial).
- [ ] Prompt hardening, AI-generated disclaimer, and privacy note (remaining P3.7).
- [ ] Amend the 2026-07-11 `DECISIONS.md` entry and rewrite the `README.md` paragraph
      claiming an allowed Auth.js session is required.

## Revisit when

- Monthly LLM spend exceeds what the blog is worth, or the Anthropic cap actually trips.
- Abuse appears that Turnstile plus per-subject rate limiting does not contain - the
  fallback is re-gating to signed-in users, which is cheap because the token route keeps
  both paths.
- Anonymous thread storage approaches the Postgres cap faster than GC reclaims it.
- Korean PIPA exposure from tracing public traffic turns out to be material.

## Changelog

- 2026-07-26: created, accepted for the access model with rollout gated on P3.
- 2026-07-28: fixed the middleware acceptance seam so native same-thread rejection
  precedes the non-refundable guest reservation and accepted commands reserve
  immediately before Aegra scheduling.
- 2026-07-28: required each guest resume ID to match the sole pending interrupt from the
  latest official LangGraph root state, with fresh owner/status/graph/update-stamp reads
  before and after that lookup while a deterministic PostgreSQL per-thread lock stays
  held through scheduling. Retention GC now takes the same key before its exact locked
  recheck and retains it through parent-delete commit; stale, ambiguous, changed,
  unavailable, timed-out, GC-deleted, and contended states fail before reservation or
  conflicting deletion.
- 2026-07-28: recorded durable guest spend/retention delivery, dedicated session-fenced
  Redis-off stale-run reconciliation with an immediate whole-owner monitor,
  cancellation-safe polling, monotonic database-triggered recovery fencing, a 15-minute
  post-recovery GC grace, secret-free maintenance identity validation, and bounded
  `read_post` output; P3.7 remains open for user-facing prompt, AI, and privacy copy.
- 2026-07-29: replaced the time-based post-recovery grace with a durable
  recovery/drain quarantine, added exact thread-lock and row-lock rechecks, bounded
  owner/poll races and proof-writer connections, and capped cross-instance guest graph
  execution with four PostgreSQL session-advisory slots.
- 2026-08-01: bounded thread creation and all other non-spending guest routes in
  independent identity/global buckets, reduced `run.start` to one exact user-text wire,
  and enforced the six-tool guest model allowlist at both binding and execution.
- 2026-08-02: pinned the three-layer production middleware order, charged malformed and
  unknown traffic at the cheap outer ingress, moved paid charging behind native ownership,
  added 2/identity and 4/global SSE leases, and added globally serialized durable stored
  thread caps of 6/identity and 256/canonical guests. Also pinned the literal ordered
  six-tool surface, inline guest retrieval prompt, and server-unique checkpoint message
  IDs with assistant-ui correlation projection. Recurring GC and public flags remain
  launch gates rather than being activated by this application change.
