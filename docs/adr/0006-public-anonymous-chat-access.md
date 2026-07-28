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
updated: "2026-07-28"
owners: ["@syshin0116"]
refs: [../research/public-exposure.md, ../plans/rag-restack.md, 0004-adopt-aegra.md, 0007-postgres-on-neon-split-projects.md]
template: adr
---

# ADR-0006: The chatbot is public, with Turnstile-gated anonymous subjects

> **status: accepted for the access model; the hardening it requires is not yet built.**
> The decision to go public is made. Going public **before** plan phase P3 lands would
> ship two known content leaks and no rate limiting - the ADR is accepted, the rollout
> is gated.

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

Both paid guest methods pass the strict guest wire validator before taking a mutation
claim. Native-valid but guest-invalid `run.start` and `input.respond` bodies therefore
reach the canonical guest 400 after the foreign-thread hiding check, without consuming
capacity, rate, or budget and without reading graph state or dispatching. Valid guest
commands require an already-created owned thread; a command waiting behind retention GC
cannot resurrect the deleted identifier as a new thread. Owner commands keep Aegra's
native behavior and do not take the guest lock.

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

**Rollout is gated on plan phase P3.** Nothing in that phase is optional.

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
- [ ] Turnstile-gated anonymous token minting (P3.3).
- [ ] `anon` scope route allowlist; strip `configurable.model`; force
      `multitask_strategy="reject"`; fix the seeded default model (P3.4).
- [ ] Rate limiting registered at or before `main.py:102`, plus provider spend caps (P3.5).
- [ ] `expires_at` + GC that calls `checkpointer.adelete_thread` first (P3.6).
- [ ] Prompt hardening, `read_post` truncation, AI-generated disclaimer, privacy note (P3.7).
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
