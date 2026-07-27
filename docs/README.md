---
title: "Project docs"
description: >
  Index of the engineering record for syshin0116.dev - decisions, the research
  behind them, execution plans, and conventions.
when_to_read: >
  When looking for why something is built the way it is, or before adding a
  document to docs/.
tags: [index, documentation]
status: stable
updated: "2026-07-28"
owners: ["@syshin0116"]
refs:
  - adr/README.md
  - research/README.md
  - conventions/frontmatter.md
  - runbooks/upstream-version-audit.md
template: index
---

# Project docs

Internal documentation for **how syshin0116.dev is built and decided** - architecture
decisions, the research behind them, execution plans, and conventions.

> This is **not** published blog content. Blog posts live in `content/`.
> This `docs/` folder is the project's own engineering record.

## Layout

| Folder | Holds | Canonical? |
|---|---|---|
| [`adr/`](adr/) | Decision records (MADR). One decision per file | **Yes** - the decision lives here |
| [`research/`](research/) | Investigations that feed a decision | No - snapshots, superseded by the ADR they feed |
| [`plans/`](plans/) | Sequenced execution plans decomposed into work packets | Until delivered |
| [`conventions/`](conventions/) | Rules about how we write code and docs | Yes |
| [`reference/`](reference/) | Living registries and lookup data - edited in place, not superseded | Yes, while current |
| [`runbooks/`](runbooks/) | Operational verification, rollout, recovery, and triage procedures | Yes, while current |

The `adr/` ↔ `research/` split is the important one. A research doc compares options
and is allowed to be wrong later; an ADR commits and is never rewritten to match
hindsight, only superseded. Keeping comparison detail out of ADRs is what keeps them
short enough to actually read.

## Where a decision gets recorded

Two tiers, by cost of being wrong:

- [`DECISIONS.md`](../DECISIONS.md) at the repo root - **the default.** One line,
  append-only. Most decisions stop here.
- `docs/adr/` - only once a decision proves durable, or when it is expensive enough
  to reverse that the alternatives need to be written down. See
  [ADR-0001](adr/0001-record-architecture-decisions.md) and the 2026-07-11
  `DECISIONS.md` entry explaining why the default is the cheap tier.

Use a code comment for local "why this line" notes and an issue for transient task
tracking.

## Frontmatter

Every file here carries YAML frontmatter - see
[`conventions/frontmatter.md`](conventions/frontmatter.md). New documents start from
the matching template: [`adr/template.md`](adr/template.md),
[`research/template.md`](research/template.md).
