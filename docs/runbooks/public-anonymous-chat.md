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
3. Enable `AGENT_ANONYMOUS_ACCESS_ENABLED=true` in the production agent release
   while Vercel still cannot mint or display anonymous access.
4. Set both Vercel anonymous flags to exactly `true`, redeploy, and complete a
   real browser challenge, Korean message, reload/history, rate-limit, and
   expired-session smoke.
5. Keep the production maintenance Scheduler paused until the owner separately approves
   public launch and recurring billing. Then land the repository change that activates
   the Terraform-owned schedule, review its exact dedicated-project plan, apply it, and
   verify the first bounded maintenance execution. Do not activate it with an
   untracked console-only toggle.

The web gate first attempts a bodyless cookie resume. A missing or expired
cookie returns to Turnstile. A successful challenge injects its returned
credential into the existing `AgentTokenBroker`; all later AP v2 operations use
the same native assistant-ui/LangGraph runtime.

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
