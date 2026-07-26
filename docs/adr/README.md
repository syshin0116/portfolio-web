---
title: "Architecture decision records"
description: >
  Index of decisions. One decision per file, superseded rather than rewritten.
when_to_read: >
  When looking for why an established pattern is the way it is, or before adding
  an ADR.
tags: [index, adr]
status: stable
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [template.md, ../conventions/frontmatter.md, ../../DECISIONS.md]
template: index
---

# Architecture decision records

MADR format. One decision per file, 4-digit sequential number.
**Accepted ADRs are never deleted - only superseded** (write a new ADR that links back).

Write an ADR for significant, hard-to-reverse, or non-obvious decisions where the
alternatives are worth writing down. Everything else gets one line in
[`DECISIONS.md`](../../DECISIONS.md), which is the default tier - see
[ADR-0001](0001-record-architecture-decisions.md) and the 2026-07-11 entry explaining
why. Use a code comment for local "why this line" notes and an issue for transient task
tracking.

An ADR's `status` answers *"is this decision still in force?"* - never *"has the work
shipped?"*. Track delivery in the Follow-ups checklist.

New ADR: copy [`template.md`](template.md). Frontmatter schema:
[`../conventions/frontmatter.md`](../conventions/frontmatter.md).

> **Read [ADR-0008](0008-chatbot-is-a-rag-evaluation-testbed.md) first if you are touching
> the agent.** It states the project's purpose and outranks every other agent-side decision -
> simplification arguments that reason from corpus size are correct for a product and
> backwards here.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | accepted |
| [0002](0002-content-immutable-source-curated-wiki.md) | Content model: immutable source posts + curated wiki (LLM-wiki) | accepted (partially amended by 0003) |
| [0003](0003-agent-code-changes-via-pr.md) | Agent changes to `web/` and `agent/` go through a branch and PR | accepted |
| [0004](0004-adopt-aegra.md) | Adopt Aegra and delete the hand-rolled Agent Protocol server | accepted |
| [0005](0005-adopt-assistant-ui.md) | Rebuild the chat UI on assistant-ui with the react-langgraph adapter | accepted |
| [0006](0006-public-anonymous-chat-access.md) | The chatbot is public, with Turnstile-gated anonymous subjects | accepted (rollout gated) |
| [0007](0007-postgres-on-neon-split-projects.md) | Postgres stays on Neon, split into two projects | accepted |
| [0008](0008-chatbot-is-a-rag-evaluation-testbed.md) | **The chatbot is a RAG evaluation testbed, not a search product** | accepted |

0004 and 0005 were first written as **proposed** recommending the opposite, then decided
the other way the same day once the owner confirmed the existing agent data is disposable.
Both keep that history in their changelog rather than pretending the first draft never
happened - the reversal is the useful part.
