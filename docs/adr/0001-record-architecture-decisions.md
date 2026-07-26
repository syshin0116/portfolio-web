---
title: "ADR-0001: Record architecture decisions"
description: >
  Record significant decisions as MADR files in docs/adr/, versioned with the code,
  so future work does not lose the rationale.
when_to_read: >
  Before changing how decisions are recorded, or when unsure whether something
  belongs in DECISIONS.md or in an ADR.
tags: [adr, process, documentation]
status: accepted
date: "2026-05-22"
deciders: ["@syshin0116"]
supersedes:
superseded_by:
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [../conventions/frontmatter.md, ../../DECISIONS.md]
template: adr
---

# ADR-0001: Record architecture decisions

## Context

This repo (blog + RAG chatbot + LLM-wiki testbed) is increasingly built and
operated with AI agents. Decisions made in chat or commits get lost; without a
durable record, future work (human or AI) loses the rationale and drifts.

## Considered options

| Option | Pros | Cons |
|---|---|---|
| A. MADR ADRs in `docs/adr/` | versioned with code, lightweight, standard | needs the discipline to write |
| B. Notes in commit messages only | zero overhead | not discoverable, no structure |
| C. External doc (Notion etc.) | rich editor | drifts from repo, not co-located |

## Decision

Record significant decisions as **MADR ADRs in `docs/adr/`**, one file per
decision, 4-digit sequential numbering. Accepted ADRs are immutable - superseded,
never deleted or rewritten.

## Consequences

- Positive: decision history lives in git next to the code; AI agents can read
  the "why" before changing established patterns.
- Trade-offs: small authoring overhead per decision.

## Revisit when

If ADRs go unmaintained and stop reflecting reality.

## Changelog

- 2026-07-11: partially amended in practice - `DECISIONS.md` became the default tier
  and ADRs the exception, because this ADR's own stated trade-off ("needs the
  discipline to write") is what happened: no decision was recorded here for seven
  weeks. Recorded as a `DECISIONS.md` entry rather than a superseding ADR.
- 2026-07-26: frontmatter migrated to
  [`conventions/frontmatter.md`](../conventions/frontmatter.md) (`id` dropped - the
  path is the identifier; `description`, `when_to_read`, `refs`, `template` added).
  Decision text unchanged.
