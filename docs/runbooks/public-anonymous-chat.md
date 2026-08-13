---
title: "Public anonymous chat rollout"
description: >
  Configure and safely enable the Vercel BotID Basic-gated anonymous assistant-ui
  experience after the agent-side wire, spend, and retention gates pass.
when_to_read: >
  Before enabling Vercel BotID Basic, setting Vercel anonymous-chat variables,
  enabling either public flag, or closing public access during an incident.
tags: [runbook, web, botid, anonymous, assistant-ui, vercel]
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
  provider-request accounting ledger)
- `GUEST_RUN_RESERVATION_MICRO_USD=19892`

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
Responses input-token count endpoint before every generation. Before provider I/O, the
runtime captures the final token-bearing payload locally and computes a defense-in-depth
admission reservation `U` from its canonical UTF-8 bytes plus per-node and fixed framing
margins. Under one lock, `RunBudget` reserves `U` in a separate count-risk ledger and the
call's 512-token output ceiling in the 16,000-token generation ledger. Count risk is
capped at 48,000 per attempt and 48,000 in aggregate per run; concurrent calls cannot
observe or reuse the same remaining capacity. The prepared canonical count payload is
sent exactly once and the same request is recaptured before generation. Only a valid
exact count `n <= U` with matching payload parity settles count risk from `U` to `n` and
adds `n` to the generation ledger. Count errors, cancellation, `n > U`, payload drift, or
failure to admit `n` under the generation cap retain `U` and exhaust the run. The framing
margin is a local heuristic, not a provider-documented hidden-token maximum or a
last-mile wire proof.

Signed-in tokens carry `model:select` and may select only `gpt-5.6-luna`,
`gpt-5.6-terra`, or `gpt-5.6-sol` through `config.configurable.model`. All three use the
same server-held OpenAI key and bounded Responses client contract. Unknown values,
top-level model overrides, and model selection without that permission fail before model
construction. Guest commands continue to strip `configurable` entirely and always use
Luna, so this adds no guest-controlled provider choice or cloud secret.

Independently, the durable spend ledger reserves the accepted provider accounting case
before the first count request. The configured per-run reservation may never be below
19,892 µUSD, the sum of the reviewed generation and count-risk floors below.

At eight calls, the per-call output ceiling is 512 tokens, for a maximum of 4,096
output tokens. The 16,000-token generation ceiling leaves 11,904 generation input
tokens. Its worst allocation is
`11,904 × $0.25/M + 4,096 × $1.20/M = 7,891.2 µUSD`, rounded up to 7,892 µUSD.
Until OpenAI documents otherwise, separately price the entire 48,000-token aggregate
count-risk ledger at the most expensive Luna input bucket:
`48,000 × $0.25/M = 12,000 µUSD`. The repository floor is therefore
`7,892 + 12,000 = 19,892 µUSD`. Luna's
ordinary uncached input is $0.20/M, implicit cache writes are $0.25/M, and cache reads
are $0.02/M; a cheaper observed bucket never lowers the pre-dispatch reservation.
Provider settlement accepts and records exact cache-read and cache-write buckets.
Every generation also carries a stable 64-character, `guest_`-prefixed,
SHA-256-derived safety identifier made with a domain separator from the canonical
random anonymous subject; the raw subject and any account data never cross the
provider boundary. OpenAI still does not document the count endpoint's billing semantics
or hidden framing maximum. The repository therefore prices the whole heuristic count-risk
budget instead of assuming the endpoint is free, but that conservative choice does not
remove the launch ambiguity or create a provider hard bound.

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
any payload bytes. The root model's direct retrieval tools must equal, in this literal order,
`keyword_search`, `semantic_search`, `metadata_filter`, `graph_traverse`, `list_posts`,
and `read_post`; startup and graph creation must reject duplicates, reordering, or a
seventh direct retrieval tool. Canonical guests additionally receive the native `task`
tool for the existing server-declared specialists. The guest root mounts no skill,
filesystem, persistent memory, todo, or QuickJS capability; children are stateless,
read-only, depth one, and cannot delegate. Task calls share up to eight model calls,
16,000-token, 45-second, rate, concurrency, and daily spend ceilings, with 512 output
tokens per call. The separate
one-task limit is removed, but at most two tasks may run concurrently. Public projection
keeps child transcripts and task arguments and results private while exposing root task
lifecycle. A forged filesystem, todo, QuickJS, nested task, or undeclared specialist call
must fail before execution.

The serialization boundary is pinned to `langchain-openai==1.3.5` and
`openai==2.53.0`; the dependency audit isolates both and keeps
`langchain-openai` below the reviewed exclusive 1.4.0 compatibility ceiling
until `langchain-core` moves beyond 1.4.9. The model's
[official catalogue entry](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
does not support the API Free tier. The owner approved the exact non-zero
500,000 µUSD UTC-day accounting ceiling above, and the Production template now
requires `OPENAI_API_KEY` from a reviewed positive numeric Secret Manager version.
That approval and wiring still do **not** authorize the final browser launch: input-count
billing and observed framing behavior must be verified, the separately reviewed Scheduler
rollout must pass, the secret payload/version must be injected out of band,
provider-account spend protection must be verified, and all operational proofs below must
succeed before either Vercel public flag becomes `true`.

## Provider spend stop and rollback boundary

The 19,892 µUSD calculation combines the worst 16,000-token generation allocation with
the whole 48,000-token count-risk budget priced at the highest Luna input bucket. The
atomic local `U` reservation blocks attempts above 48,000 and aggregate or overlapping
count risk above 48,000 before provider I/O, and retains the reservation on failure.
However, OpenAI does not publish a hard hidden-framing maximum or count-endpoint billing
rate; a provider count could exceed the heuristic `U`, and the count request has already
reached OpenAI when that is learned. The application ledger is therefore not the sole hard
stop for that edge, and 19,892 µUSD is not a provider-wide mathematical ceiling.

Before either Vercel public flag becomes `true`, isolate the guest API key in its reviewed
OpenAI project and verify a provider-enforced hard usage/spend stop that bounds count and
generation together within the owner's approved exposure. A dashboard alert, emailed
budget, or other soft notification does not qualify. Record only non-secret read-back
evidence; never place the key or provider credential in a report. If the provider cannot
enforce the reviewed stop, public issuance remains disabled.

If provider telemetry exceeds the conservative reservation, the hard stop cannot be
verified, or count behavior changes, close both Vercel flags first, revoke the guest key or
set its provider stop to zero, and follow the exact-project emergency-close sequence below.
Do not increase the cap to restore service. Do not roll back to a 6,892, 8,868, or 18,892 µUSD
revision: startup and delivery verification intentionally reject both superseded
contracts. A Cloud Run rollback target must retain the exact 19,892 µUSD tuple;
otherwise keep guest access closed and land a reviewed replacement.

## Vercel BotID Basic

Enable Vercel BotID Basic protection for the anonymous bootstrap route only:
`POST /api/anonymous-agent-token`. The browser registers that exact path with
`botid/client/core`, using `checkLevel: "basic"`; the server calls
`checkBotId({ advancedOptions: { checkLevel: "basic" } })`. Do not add a challenge
widget, site key, or BotID secret to the application.

The bootstrap request is bodyless: it has no `Content-Type`, `Transfer-Encoding`, or
non-zero `Content-Length`. BotID runs before cookie lookup, so both a new visitor and
an existing cookie resume receive the same Basic check. A passing request creates or
resumes the httpOnly anonymous-session cookie and returns a five-minute agent token.
The cookie is the only retained visitor credential; no BotID verdict or bootstrap body
is stored.

## Vercel variables

Set these server-only Production values:

- `AGENT_AUTH_SECRET`: the exact secret used by the production Cloud Run agent.
- `AGENT_ANONYMOUS_TOKEN_ENABLED=false` until the final enable deployment.
- `ANONYMOUS_SESSION_SECRET`: an independent random value of at least 32 bytes.

Set these browser-visible Production values:

- `NEXT_PUBLIC_AGENT_API_URL`: the production Cloud Run service origin.
- `NEXT_PUBLIC_AGENT_ASSISTANT_ID=agent`.
- `NEXT_PUBLIC_AGENT_ANONYMOUS_ENABLED=false` until the final enable deployment.

Do not copy secrets into any `NEXT_PUBLIC_*` value. Preview uses its own BotID,
hostname, agent origin, database, and secrets; it must not share production
guest identity or spend state.

## Enable order

1. Keep both Vercel public flags false. Inject the reviewed Production OpenAI payload and
   record only its positive numeric version alongside the other exact secret versions.
2. After both environments' migration, grant-probe, and maintenance jobs pass, review
   and apply the exact services-stage plan. It must combine the active Production
   maintenance Scheduler with only Production's `true / openai:gpt-5.6-luna / 500000 /
   19892` tuple and numeric `OPENAI_API_KEY`; Preview stays disabled and OpenAI-free.
3. Verify Terraform read-back and the first bounded checkpoint-first scheduled
   maintenance execution. A paused or unverified Scheduler blocks launch.
4. Release the exact reviewed revision, then run owner, PostgreSQL, public raw-wire,
   rate, concurrency, spend, retention, input-count billing, and provider-cap proofs
   while Vercel BotID still cannot mint or display anonymous access.
5. Set both Vercel anonymous flags to exactly `true`, redeploy, and complete a
   real browser challenge, Korean message, reload/history, rate-limit, and
   expired-session smoke.

The production maintenance Scheduler is repository-configured active after the separate
owner approval. Do not pause or activate it with an untracked console-only toggle, and do
not interpret the configuration change as proof that step 3 completed: the exact plan,
apply, and first bounded execution remain required before either public flag is enabled.

The web gate first attempts the bodyless `/api/anonymous-agent-token` cookie resume.
A missing or expired cookie still passes Vercel BotID Basic before the server creates a
new subject. The response injects its five-minute credential into the existing
`AgentTokenBroker`; all later AP v2 operations use the same native assistant-ui/LangGraph
runtime.

The bodyless BotID bootstrap and every later `AgentTokenBroker` remint carry the exact
`X-Agent-Token-Intent: anonymous` request header. The
intent is immutable for that native runtime's lifetime, including expiry-margin
refreshes, forced 401 retries, and refreshes retained by a run-scoped
cancellation snapshot after the general broker is sealed. Owner runtimes are
constructed without an intent and remain headerless. The token route dispatches
only the exactly marked branch before invoking Auth.js, so an Auth.js, Neon, or
OAuth outage cannot prevent a valid anonymous cookie remint or BotID Basic check. The
header is routing metadata, not authority: the server-side public feature flag and the
cookie or BotID verification remain mandatory.
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
