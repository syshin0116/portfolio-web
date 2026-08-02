---
title: "Public anonymous chat rollout"
description: >
  Configure and safely enable the Turnstile-gated anonymous assistant-ui
  experience after the agent-side wire, spend, and retention gates pass.
when_to_read: >
  Before creating the Cloudflare Turnstile widget, setting Vercel anonymous-chat
  variables, enabling either public flag, or closing public access during an incident.
tags: [runbook, web, turnstile, anonymous, assistant-ui, vercel]
status: accepted
date: "2026-07-28"
owners: ["@syshin0116"]
refs:
  - ../adr/0005-adopt-assistant-ui.md
  - ../adr/0006-public-anonymous-chat-access.md
  - cloud-run-delivery.md
template: runbook
---

# Public anonymous chat rollout

Both public flags stay exactly `false` in repository examples. Enabling the
browser gate before the agent's public-safe state/history/SSE projection is
verified violates ADR-0005 even if the visible UI appears sanitized.

## Cloud Run fail-closed baseline

The repository-owned Cloud Run template and delivery verifier require this exact
pre-launch environment:

- `AGENT_ANONYMOUS_ACCESS_ENABLED=false`
- `GUEST_MODEL=` (empty)
- `GUEST_DAILY_BUDGET_MICRO_USD=` (empty)
- `GUEST_RUN_RESERVATION_MICRO_USD=` (empty)

Do not make these values apply-time Terraform variables or change them in the
console. Selecting a guest model and its worst-case per-run and UTC-day
micro-dollar ceilings is a paid public-launch decision. Land those three exact
values and the `true` opt-in together in a separate reviewed PR, then apply its
exact plan. An ordinary image delivery verifies and preserves the reviewed
values; it must refuse a revision with console or out-of-band drift.
The pre-launch map is shared only because both environments are disabled; that
launch PR must split Preview and Production configuration and keep Preview
disabled unless its own model, budget, and public-test gate are approved.

The runtime accepts only `openai:gpt-5.6-luna` as the eventual non-empty
`GUEST_MODEL`. It uses the OpenAI Responses API with reasoning disabled,
`reasoning.context=current_turn` fixed explicitly to preserve the earlier
stateless behavior, provider-side response storage disabled, and the official
Responses input-token count endpoint before every generation. The run ledger
atomically consumes a model-call slot and reserves that call's 1,024-token
output ceiling before the remote count; only then may it extend the reservation
by the exact counted input. The configured per-run reservation may never be below
6,892 µUSD, the integer-ceiling generation cost for the
12,000-token/four-call policy at
$0.20/M uncached input and $1.20/M output. GPT-5.6 implicit cache writes cost
1.25 times uncached input ($0.25/M), while cache reads cost $0.02/M, so the
pre-dispatch floor conservatively prices all possible input as cache writes.
Provider settlement accepts and records exact cache-read and cache-write buckets.
Every generation also carries a stable 64-character, `guest_`-prefixed,
SHA-256-derived safety identifier made with a domain separator from the canonical
random anonymous subject; the raw subject and any account data never cross the
provider boundary.
This is a generation-only floor, not a claim about the count endpoint's currently
undocumented billing.

Both generation and input-count SDK clients are pinned to
`https://api.openai.com/v1` and must have no organization, project, custom header, or
OpenAI-specific proxy route. The runtime fails before reading `OPENAI_API_KEY` when any
of `OPENAI_ADMIN_KEY`, `OPENAI_API_BASE`, `OPENAI_BASE_URL`,
`OPENAI_CUSTOM_HEADERS`, `OPENAI_ORGANIZATION`, `OPENAI_ORG_ID`,
`OPENAI_PROJECT_ID`, or `OPENAI_PROXY` is present, including an empty value. Keep all
eight absent from Cloud Run; standard platform HTTPS proxy policy remains a separate
infrastructure decision.

The agent's repository-owned production order is exact:
`GuestIngressGuard -> NativeThreadGuard -> GuestRunGuard`. After authentication, the
outer guard charges before route lookup, query/body parsing, or database access:

- exact `POST /threads`: 6 per anonymous identity and 60 globally per hour;
- every other path, including paid commands, malformed routes, and unknown routes:
  30 per anonymous identity and 180 globally per minute;
- a valid `run.start` or `input.respond` that passes Native ownership/status: an
  additional paid token at 4 per identity and 24 globally per minute, followed by the
  durable daily spend reservation.

A valid command against a foreign thread consumes only the outer request token and
returns the same hidden 404; it cannot consume the paid bucket or ledger. Invalid guest
wires can perform at most the database work allowed by the outer bucket and never reach
paid reservation or dispatch. Non-spending exhaustion neither charges nor resets the
paid ledger.

The process-local identity table is capped at 1,024 SHA-256 subject digests. An entry may
be pruned only after the longest configured identity window, when every used bucket is
fully refilled and no stream lease remains. Each guest SSE response holds one
`finally`-released lease, capped at 2 per identity and 4 globally. These traffic controls
authorize only the reviewed single-instance deployment; cold starts do not make them a
durable limit. The durable spend ledger, four PostgreSQL execution slots, and stored-thread
admission below are independent controls.

`POST /threads` also takes a domain-separated global PostgreSQL transaction advisory lock,
counts all stored rows for that identity and all exact canonical `anon:<uuid>` subjects,
and holds the lock through the downstream response/commit. The durable caps are 6 stored
threads per identity and 256 globally. Expired rows count until checkpoint-first GC removes
them. An existing owned ID is idempotent even at cap; a foreign collision is hidden; lock
or count failure returns 503. Before launch, the real-PostgreSQL proof must demonstrate
that a concurrent second admission sees the first committed create before deciding.

Guest `run.start` carries exactly one `user` message containing plain UTF-8 text or only
assistant-ui text blocks. It must reject client assistant/tool history and non-text
content before any paid rate or spend consumption. Each accepted client message ID is
wrapped in a server-unique checkpoint ID; public state/SSE projection restores the safe
client ID for native assistant-ui correlation. Bodyless guest GET and cancel routes reject
any payload bytes. The root model's bound tools must equal, in this literal order,
`keyword_search`, `semantic_search`, `metadata_filter`, `graph_traverse`, `list_posts`,
and `read_post`; startup and graph creation must reject duplicates, reordering, or a
seventh tool. The guest prompt contains this retrieval workflow inline and mounts no
skill. A forged filesystem/todo/task/QuickJS call must fail before execution.

The serialization boundary is pinned to `langchain-openai==1.3.5` and
`openai==2.50.0`; the dependency audit isolates both and keeps
`langchain-openai` below the reviewed exclusive 1.4.0 compatibility ceiling
until `langchain-core` moves beyond 1.4.9. The model's
[official catalogue entry](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
does not support the API Free tier. Therefore this code contract does **not**
authorize launch: Production remains disabled until the owner explicitly
approves a non-zero provider budget, the input-count endpoint's billing
semantics are confirmed, and the separately reviewed launch PR supplies the
OpenAI secret and all spend ceilings atomically.

## Cloudflare Turnstile

Create separate production and preview widgets. Configure the exact canonical
deployment hostname and use action `agent-token`. The browser receives only the
site key; the secret remains a Vercel server variable. Local and browser CI use
Cloudflare's documented dummy key, never a production secret.

Turnstile is rendered explicitly from Cloudflare's canonical script URL. Its
single-use token is posted once to same-origin `/api/agent-token`, is never
stored, and is replaced by an httpOnly anonymous-session cookie plus a
five-minute agent credential.

## Vercel variables

Set these server-only Production values:

- `AGENT_AUTH_SECRET`: the exact secret used by the production Cloud Run agent.
- `AGENT_ANONYMOUS_TOKEN_ENABLED=false` until the final enable deployment.
- `ANONYMOUS_SESSION_SECRET`: an independent random value of at least 32 bytes.
- `TURNSTILE_SECRET_KEY`: the production widget secret.
- `TURNSTILE_EXPECTED_HOSTNAME`: the exact canonical production hostname.
- `TURNSTILE_EXPECTED_ACTION=agent-token`.

Set these browser-visible Production values:

- `NEXT_PUBLIC_AGENT_API_URL`: the production Cloud Run service origin.
- `NEXT_PUBLIC_AGENT_ASSISTANT_ID=agent`.
- `NEXT_PUBLIC_TURNSTILE_SITE_KEY`: the production widget site key.
- `NEXT_PUBLIC_AGENT_ANONYMOUS_ENABLED=false` until the final enable deployment.

Do not copy secrets into any `NEXT_PUBLIC_*` value. Preview uses its own widget,
hostname, agent origin, database, and secrets; it must not share production
guest identity or spend state.

## Enable order

1. Deploy and verify the agent with anonymous access still false.
2. Run owner, PostgreSQL, public raw-wire, rate, concurrency, spend, retention,
   and maintenance proofs against the exact revision.
3. While both public surfaces remain disabled, obtain the separate owner approval for
   recurring billing, land the repository change that activates the currently paused
   Terraform-owned production maintenance Scheduler, review its exact dedicated-project
   plan, apply it, and verify the first bounded checkpoint-first maintenance execution.
   A paused or unverified Scheduler blocks launch.
4. Land the separately approved repository change that selects the guest model,
   fixes both reviewed micro-dollar ceilings, splits Preview from Production,
   and sets the Production `AGENT_ANONYMOUS_ACCESS_ENABLED=true`; apply it while
   Vercel still cannot mint or display anonymous access.
5. Set both Vercel anonymous flags to exactly `true`, redeploy, and complete a
   real browser challenge, Korean message, reload/history, rate-limit, and
   expired-session smoke.

This repository change intentionally leaves the production maintenance Scheduler paused.
Do not activate it with an untracked console-only toggle, and do not interpret application
hardening as approval to enable either public flag before step 3 completes.

The web gate first attempts a bodyless cookie resume. A missing or expired
cookie returns to Turnstile. A successful challenge injects its returned
credential into the existing `AgentTokenBroker`; all later AP v2 operations use
the same native assistant-ui/LangGraph runtime.

The bodyless resume, Turnstile submission, and every later `AgentTokenBroker`
remint carry the exact `X-Agent-Token-Intent: anonymous` request header. The
intent is immutable for that native runtime's lifetime, including expiry-margin
refreshes, forced 401 retries, and refreshes retained by a run-scoped
cancellation snapshot after the general broker is sealed. Owner runtimes are
constructed without an intent and remain headerless. The token route dispatches
only the exactly marked branch before invoking Auth.js, so an Auth.js, Neon, or
OAuth outage cannot prevent a valid anonymous cookie remint or challenge
exchange. The header is routing metadata, not authority: the server-side public
feature flag and the cookie or Turnstile verification remain mandatory.
Missing, unknown, or unrecognized intent values stay on the existing owner path,
where session lookup failures remain a generic fail-closed `503`.

## Emergency close

Disable `AGENT_ANONYMOUS_TOKEN_ENABLED` and
`NEXT_PUBLIC_AGENT_ANONYMOUS_ENABLED` in Vercel and redeploy first so no new
guest credential can be minted. Then disable
`AGENT_ANONYMOUS_ACCESS_ENABLED` in Cloud Run. Rotate the anonymous session
secret only when every existing guest cookie must be invalidated; rotate the
shared agent secret only as a broader incident response because it also
invalidates owner credentials.

For infrastructure spend containment, follow the delivery runbook's exact project-scoped
order: freeze future delivery and ordinary Terraform applies, perform this emergency
close, remove the public invoker and stop the service through a separately approved exact
project action, then pause Scheduler. Land the matching reviewed Terraform configuration
before allowing another apply so desired state cannot restore exposure.
`AGENT_CLOUD_RUN_ENABLED=false` alone is not a kill switch, and no step by itself proves
zero cost.
