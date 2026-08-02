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

Both Vercel public flags stay exactly `false` until the final browser rollout.
Preview also remains fail closed. The repository now records the separately
approved Production agent launch values, but merging this configuration does not
apply Terraform, create a secret version, or enable the browser gate. Enabling the
browser gate before the agent's public-safe state/history/SSE projection is
verified violates ADR-0005 even if the visible UI appears sanitized.

## Cloud Run repository-owned launch contract

The repository-owned Cloud Run template and delivery verifier require these exact
Preview values:

- `AGENT_ANONYMOUS_ACCESS_ENABLED=false`
- `GUEST_MODEL=` (empty)
- `GUEST_DAILY_BUDGET_MICRO_USD=` (empty)
- `GUEST_RUN_RESERVATION_MICRO_USD=` (empty)

Production alone carries the owner-approved launch tuple:

- `AGENT_ANONYMOUS_ACCESS_ENABLED=true`
- `GUEST_MODEL=openai:gpt-5.6-luna`
- `GUEST_DAILY_BUDGET_MICRO_USD=500000` ($0.50 per UTC day for the durable
  generation reservation ledger)
- `GUEST_RUN_RESERVATION_MICRO_USD=6892`

Do not make these values apply-time Terraform variables or change them in the
console. An ordinary image delivery verifies and preserves the reviewed values;
it must refuse a revision with console or out-of-band drift. Preview and Production
have separate repository-owned runtime maps, and Preview must not inherit the paid
model, budget, credential, or access flag unless it receives its own reviewed
public-test contract. Do not replace the reviewed constants with apply-time launch
variables or a generic runtime toggle.

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
does not support the API Free tier. The owner approved the exact non-zero
500,000 µUSD UTC-day generation ceiling above, and the Production template now
requires `OPENAI_API_KEY` from a reviewed positive numeric Secret Manager version.
That approval and wiring still do **not** authorize the final browser launch: the
input-count endpoint's billing semantics remain outside the generation ledger and
must be confirmed, the separately reviewed Scheduler rollout must pass, the secret
payload/version must be injected out of band, and all operational proofs below must
succeed before either Vercel public flag becomes `true`.

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

1. Keep both Vercel public flags false. Inject the reviewed Production OpenAI payload and
   record only its positive numeric version alongside the other exact secret versions.
2. After both environments' migration, grant-probe, and maintenance jobs pass, review
   and apply the exact services-stage plan. It must combine the active Production
   maintenance Scheduler with only Production's `true / openai:gpt-5.6-luna / 500000 /
   6892` tuple and numeric `OPENAI_API_KEY`; Preview stays disabled and OpenAI-free.
3. Verify Terraform read-back and the first bounded checkpoint-first scheduled
   maintenance execution. A paused or unverified Scheduler blocks launch.
4. Release the exact reviewed revision, then run owner, PostgreSQL, public raw-wire,
   rate, concurrency, spend, retention, input-count billing, and provider-cap proofs
   while Vercel still cannot mint or display anonymous access.
5. Set both Vercel anonymous flags to exactly `true`, redeploy, and complete a
   real browser challenge, Korean message, reload/history, rate-limit, and
   expired-session smoke.

The production maintenance Scheduler is repository-configured active after the separate
owner approval. Do not pause or activate it with an untracked console-only toggle, and do
not interpret the configuration change as proof that step 3 completed: the exact plan,
apply, and first bounded execution remain required before either public flag is enabled.

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
