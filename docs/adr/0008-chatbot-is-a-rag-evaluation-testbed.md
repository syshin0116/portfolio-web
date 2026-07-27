---
title: "ADR-0008: The chatbot is a RAG evaluation testbed, not a search product"
description: >
  The purpose of the agent is to build many retrieval methods and compare them.
  The blog is the corpus because the owner knows it best; answering blog questions
  well is a side effect, not the goal.
when_to_read: >
  Before simplifying the retrieval layer, before judging a design as over-built,
  or before adding anything to the agent. Read this before any other agent ADR.
tags: [adr, purpose, rag, evaluation, agent, retrieval]
status: accepted
date: "2026-07-26"
deciders: ["@syshin0116"]
supersedes:
superseded_by:
updated: "2026-07-26"
owners: ["@syshin0116"]
refs:
  - ../reference/retrieval-methods.md
  - ../plans/rag-restack.md
  - 0006-public-anonymous-chat-access.md
template: adr
---

# ADR-0008: The chatbot is a RAG evaluation testbed, not a search product

> **status: accepted.** This ADR states the project's purpose. **It outranks every other
> agent-side decision** - when a design argument and this document disagree, this document
> wins, and the argument was probably built on the wrong goal.

## Context

The agent looks like a blog search chatbot, and everyone who reads the code - including
the AI agents working on it - assumes that is what it is for. It is not.

The purpose is to **build many different retrieval methods and evaluate them against each
other**. The blog is the corpus for two practical reasons: the owner knows its content
better than any public dataset, so relevance judgements are cheap and trustworthy; and it
is already preprocessed as markdown with frontmatter and a `[[wikilink]]` graph.
Answering blog questions well is a side effect.

Writing this down is not bookkeeping. The goal was unstated for most of this project's
design work, and the resulting advice was confidently wrong in a specific, repeatable way:

> *"336 files is a small corpus. A `path|title|date|tags` catalogue of the whole thing is
> ~25k tokens and fits in a cached system prompt, which makes `list_posts` and
> `metadata_filter` redundant. Collapse six retrieval tools into two or three."*

That reasoning is correct for a product and **backwards for a testbed**, where method
breadth is the deliverable. The same inversion applies to nearly every simplification
argument someone will make about this repo. An ADR is the right home for the purpose
precisely because it is the thing that makes those arguments evaluable.

## Considered options

| Option | Pros | Cons |
|---|---|---|
| A. Record the purpose as an ADR that outranks other agent decisions | Discoverable; forces "which goal does this serve?" before simplification arguments land; `when_to_read` puts it in front of an agent early | An ADR usually records a choice between alternatives, and this is closer to a charter |
| B. A line in `CLAUDE.md` / `README.md` | Zero ceremony | Gets skimmed. `CLAUDE.md` is already dense with rules, and a purpose statement reads as flavour text next to hard rules |
| C. Leave it implicit | Nothing to maintain | Already demonstrably failed - see the Context |

## Decision

Adopt **A**, and state the purpose as:

**The agent exists to implement and compare retrieval methods. The blog is the corpus.
The chat interface is a manual-inspection surface for whichever method is loaded. Search
quality on this specific blog is a side effect, not a target.**

Three consequences follow directly and are binding:

1. **Breadth of retrieval methods is a feature, not bloat.** Simplification arguments that
   reason from corpus size are rejected by default. Simplicity still applies to the
   *harness*, and to anything not on the method axis.
2. **A correct baseline is a prerequisite, not a nice-to-have.** A broken baseline does not
   merely answer questions badly, it **invalidates every comparison drawn against it**. The
   current BM25 is broken in exactly this way: `_tokenize("도커")` returns `['크']`, so the
   top hit for a Docker query is an unrelated coding-test post scored 1.0 while 13 files
   containing the term are missed, and the score normalisation forces a 1.0 top hit for any
   query at all, including nonsense. Under a product goal this is a bug to schedule. Under
   this goal it is a **blocker**.
3. **Retrievers are plugs, not tools.** The chat must consume retrieval through the
   shared interface that the evaluation harness will also consume. Chat wiring is complete;
   that does not count as an evaluation harness, which remains separate follow-up work.

The living catalogue of methods lives in
[`../reference/retrieval-methods.md`](../reference/retrieval-methods.md) - a registry, not
an ADR, because it changes continuously.

## Consequences

**Positive**

- Design arguments become evaluable: "is this serving the method axis or the harness?"
- The `[[wikilink]]` graph stops being an odd extra tool and becomes the most
  differentiated axis available - most RAG comparisons cannot test link-based retrieval
  because their corpora have no links.
- Results are publishable. The owner writes a technical blog, and a method comparison over
  a corpus the author knows intimately is a better post than another vendor benchmark.

**Trade-offs**

- **The blog's actual visitors are not the customer.** [ADR-0006](0006-public-anonymous-chat-access.md)
  opens the chatbot publicly, so real people will use a surface tuned for inspection rather
  than for them. Accepted, but it means UX complaints are not automatically bugs.
- Method breadth costs money and time. Every method is an implementation, an evaluation
  run, and a maintenance surface, and some will teach nothing.
- Carrying methods that lose keeps dead code alive, because "it lost" is a result worth
  preserving rather than a reason to delete.

**Follow-ups**

- [x] Create `docs/reference/retrieval-methods.md` as the living registry.
- [x] Point `CLAUDE.md`'s "What this repo is" at this ADR.
- [x] Fix or rebuild the BM25 baseline **before** any comparison is run.
- [x] Define the retriever interface once and wire the chat serving path to it.
- [ ] Build the evaluation harness against that same retriever interface.
- [x] Select the deployed method through server-owned config and the servable registry.

## Revisit when

- The comparison work finishes and the project becomes a product - at which point the
  simplification arguments this ADR rejects all become correct, and it should be superseded
  rather than quietly ignored.
- Method breadth stops teaching anything, i.e. new methods land within noise of existing
  ones on this corpus. That is a signal the corpus is exhausted, not that the goal changed.
- The public chatbot's real usage becomes valuable enough that serving it well starts to
  compete with the evaluation goal.

## Changelog

- 2026-07-26: created. Recorded after the unstated goal produced a confidently wrong
  recommendation to collapse the retrieval surface.
