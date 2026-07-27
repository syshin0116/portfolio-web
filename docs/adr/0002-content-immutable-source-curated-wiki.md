---
title: "ADR-0002: Content model - immutable source posts + curated wiki (LLM-wiki)"
description: >
  Blog posts outside content/wiki/ are read-only source material; the curated
  knowledge layer that feeds the RAG chatbot is built additively in content/wiki/.
when_to_read: >
  Before letting anything write to content/, or when deciding where curated
  knowledge should live.
tags: [adr, content, llm-wiki, rag]
status: accepted
date: "2026-05-22"
deciders: ["@syshin0116"]
supersedes:
superseded_by:
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [0003-agent-code-changes-via-pr.md, ../conventions/frontmatter.md]
template: adr
---

# ADR-0002: Content model - immutable source posts + curated wiki (LLM-wiki)

> **Partially amended.** The third decision bullet - `web/` and `agent/` as
> off-limits "human territory" - is superseded by
> [ADR-0003](0003-agent-code-changes-via-pr.md), which replaces the blanket ban with
> a branch-and-PR requirement. **The content rules (bullets one and two) are
> unchanged and still in force**: source posts remain immutable.

## Context

The blog has years of Obsidian posts under `content/AI`, `content/Dev`,
`content/Tools`, etc. The repo is also a testbed for the **LLM-wiki pattern**: a
curated, queryable knowledge layer feeding the RAG chatbot. Letting AI agents
edit original posts risks corrupting source material that should stay authentic.

## Considered options

| Option | Pros | Cons |
|---|---|---|
| A. Source immutable + curated `content/wiki/` (skills only) | originals safe, clean curation layer | two layers to reason about |
| B. Let agents edit posts in place | simplest | destroys source authenticity, hard to audit |
| C. Curate in an external store | decoupled | drifts from posts, extra infra |

## Decision

- **Source posts are immutable.** Every `.md` outside `content/wiki/` is read-only;
  if a post looks wrong, surface it to the human, do not edit.
- **A curated knowledge layer lives in `content/wiki/`**, built only through skills
  (each skill carries the full contract) - no ad-hoc writes.
- `web/`, `agent/`, and build/deploy config are human territory; agents do not modify them.

(Operational rules mirror this repo's `AGENTS.md`.)

## Consequences

- Positive: source integrity preserved; curation is additive and auditable; the
  RAG layer can be rebuilt from source without risking originals.
- Trade-offs: contributors must know which layer they're in; wiki edits must go
  through skills rather than direct editing.

## Revisit when

The LLM-wiki testbed graduates to a different content/curation architecture.
