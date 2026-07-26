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
updated: "2026-07-26"
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

- [ ] Fix the `/blog/` filesystem route and the `ripgrep_search` draft fallback (P3.1).
- [ ] Add draft-exclusion regression tests through all six tools (P3.2) - the existing
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
