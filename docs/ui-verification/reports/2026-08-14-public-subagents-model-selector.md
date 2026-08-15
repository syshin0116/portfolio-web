---
title: "Public subagents and model selector verification"
description: >
  Records local assistant-ui verification and the bounded Production follow-up for
  public specialists and signed-in model selection.
when_to_read: >
  Before claiming deployed public-specialist or signed-in model-selector browser evidence.
tags: [ui-verification, assistant-ui, subagents, models]
status: stable
updated: "2026-08-15"
owners: ["@syshin0116"]
refs:
  - ../../adr/0005-adopt-assistant-ui.md
  - ../../adr/0006-public-anonymous-chat-access.md
template: spec
---

# Public subagents and model selector verification

## Candidate

- Revision: `e503a8729385ffa501fb8cc72ca4c12d47f40d99`
- Environment: local Chromium against the isolated APv2 fixture
- Authority: authoritative for the committed UI candidate, not the Vercel deployment

## Result

Passed. Anonymous chat remains Luna-fixed with no selector. Signed-in chat exposes the
reviewed Luna, Terra, and Sol choices, snapshots the selection when a run starts, and
sends the exact model key through APv2. Dynamic task activity renders without exposing
child arguments, results, or transcript content.

## Checks

- Web unit suite: 490 passed
- Lint, typecheck, and production build: passed
- Native assistant browser suite: 12 passed
- Supported-width overflow and reduced-motion checks: passed
- Browser console and page errors: none

## Evidence

- Playwright report: `web/playwright-report/e503a8729385ffa501fb8cc72ca4c12d47f40d99/index.html`
- Screenshot attachments: 17

No live provider request, login, cloud mutation, or paid API call was used for the local
candidate verification. Production observations are recorded below. Preview and the
signed-in selector were not browser-verified in deployed environments.

## Production follow-up, 2026-08-15

### Logged-out specialist journey

- Revision: `bff8eb1d5708ef0955888dc1af1cd3da0df3da33`
- Environment: `https://syshin0116.vercel.app`
- Actor: logged-out visitor
- Authority: authoritative for this revision's logged-out specialist journey
- Result: specialist execution passed; final-answer completion failed

The Production browser journey accepted an anonymous Luna message, rendered task and
retrieval activity, but the provider response ended before a complete final answer. That
failure led to the output-ceiling and completion-state fix in the final deployed revision.

### Final deployed revision

- Repository revision: `2a5c8ef0629670dc792b6baf2b928f1d0894a7c7`
- Cloud Run revision: `agent-00030-jex`
- Environment: `https://syshin0116.vercel.app`
- Actor: logged-out visitor
- Authority: non-authoritative passive observation
- Scope: passive desktop and mobile observation
- Result: passed for bootstrap, composer availability, and horizontal overflow only

Both viewports bootstrapped public chat, displayed `공개 체험 · Luna`, and exposed an
enabled composer without requiring login or causing horizontal overflow. No message was
submitted in this follow-up, so provider execution and the specialist journey were not
re-verified on this revision. The final-answer fix has code and CI evidence but no retained
post-deploy provider journey.

### Signed-in model selector

The Luna, Terra, and Sol selector has deterministic fixture evidence only from the local
candidate above. It has no Production browser proof and must not be reported as verified
in Production.
