---
id: 0001-record-architecture-decisions
title: "ADR-0001: Record architecture decisions"
status: accepted
date: "2026-05-22"
deciders: ["@syshin0116"]
supersedes:
superseded_by:
tags: [adr, process]
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
