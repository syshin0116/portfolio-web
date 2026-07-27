---
title: "Research: <topic>"
description: >
  One or two sentences: what was investigated and which decision it feeds.
when_to_read: >
  Before deciding <X>, or when revisiting the decision this fed.
tags: [research]
status: draft             # draft | stable | deprecated
updated: "YYYY-MM-DD"
owners: ["@syshin0116"]
refs: []                  # the ADR this feeds, once it exists
template: research
---

# Research: \<topic\>

> **Not a decision.** Input to `../adr/NNNN-slug.md`. Once that ADR lands,
> the ADR is canonical and this file becomes a historical snapshot - do not update it
> to match later reality, and say so at the top when that happens.

> **Evaluated at**: `<package>` **`<version>`**, investigated `YYYY-MM-DD`.
> Primary sources: official docs, the repo itself. Secondary sources are labelled
> as such and never carry a claim alone.

## Bottom line

Three or four sentences. What is true, and what it means for the decision.

## \<Findings sections\>

Whatever structure the topic needs. Cite a URL or a `file:line` for every non-obvious
claim - a research doc whose claims cannot be re-checked is worth less than no doc.

## Options

| Option | Pros | Cons |
|---|---|---|

## Unverified

What could not be confirmed, stated plainly. This section is load-bearing: the point
of separating research from decisions is that a decision can then say "accepted,
conditional on the unverified item below". Never resolve an unknown by assumption to
make the table look complete.
