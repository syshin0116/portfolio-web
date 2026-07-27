---
title: "ADR-NNNN: Title"
description: >
  One or two sentences: what was decided and the load-bearing reason.
when_to_read: >
  The condition under which someone should open this file - usually "before
  changing X" or "before adopting Y".
tags: [adr]
status: proposed          # proposed | accepted | rejected | superseded | deprecated
date: "YYYY-MM-DD"        # decision date - immutable
deciders: ["@syshin0116"]
supersedes:               # e.g. 0003-some-earlier-decision.md
superseded_by:
updated: "YYYY-MM-DD"
owners: ["@syshin0116"]
refs: []                  # relative paths to related docs / research
template: adr
---

# ADR-NNNN: Title

> Copy this file for a new ADR. 4-digit number, next in sequence.
> Accepted ADRs are never deleted - only superseded by a new one that links back.
> Schema: [`../conventions/frontmatter.md`](../conventions/frontmatter.md).

> **status: proposed.** Add a one-line callout here whenever the status is anything
> other than a clean `accepted` - a partial acceptance, a decision that depends on a
> pending verification, or a scope limit. Say what is settled and what is not.

## Context

The problem, the forces, and why it has to be decided now. Include the constraints
that actually bind (cost, a free tier, a hard rule elsewhere in the repo) and link
the research that fed this. Two or three paragraphs is usually enough - push the
comparison detail into `docs/research/` rather than inlining it.

## Considered options

| Option | Pros | Cons |
|---|---|---|
| A. ... | | |
| B. ... | | |
| C. Do nothing / keep what exists | | |

Always include the do-nothing option. An ADR's value is answering *"why not the
other way"* later, and "keep what we had" is the option most often skipped and most
often right.

## Decision

What was chosen, in the imperative. Then the one load-bearing reason. If the
decision has parts that are settled and parts that are not, split them explicitly -
do not let a hedge read as a commitment.

## Consequences

**Positive**

- What gets easier or becomes possible.

**Trade-offs**

- What is being given up. Never write "none" - if you cannot find one, you have not
  understood the decision yet.

**Follow-ups**

- [ ] Concrete work this decision creates. Checkboxes, because this list is the
      delivery record and it outlives the decision itself.

## Revisit when

Named triggers, not vibes. Each one should be observable: a version release, a
metric crossing a threshold, a cost ceiling, an upstream project going quiet. If you
cannot state how you would notice, it is not a trigger.

## Changelog

- YYYY-MM-DD: created.
