---
title: "Retrieval method registry"
description: >
  The living catalogue of retrieval methods: what is planned, implemented,
  evaluated, or rejected, and what each one is meant to teach.
when_to_read: >
  Before implementing a retrieval method, before adding one to an evaluation run,
  or when looking for what has already been tried and what it scored.
tags: [reference, retrieval, rag, evaluation, registry]
status: draft
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [../adr/0008-chatbot-is-a-rag-evaluation-testbed.md, ../plans/rag-restack.md]
template: reference
---

# Retrieval method registry

The method catalogue for the evaluation testbed described in
[ADR-0008](../adr/0008-chatbot-is-a-rag-evaluation-testbed.md). **This is a registry, not
a decision record** - it changes continuously and is meant to be edited in place. When a
method's outcome becomes load-bearing for a later choice, that gets its own ADR.

Every entry carries **what it is meant to teach**. A method that cannot answer that
question does not belong here, however fashionable it is. A method that loses stays in the
table with its result: "it lost on this corpus" is a finding worth keeping, and deleting it
invites re-implementing it in six months.

## Status vocabulary

| Status | Meaning |
|---|---|
| `planned` | On the list, not written |
| `building` | In progress |
| `implemented` | Works, not yet evaluated |
| `evaluated` | Has numbers in an eval run |
| `rejected` | Tried or assessed and dropped - **the reason is the point** |
| `blocked` | Waiting on something named |

## Prerequisites

Two things gate every entry in this table, both from
[ADR-0008](../adr/0008-chatbot-is-a-rag-evaluation-testbed.md):

- **A correct BM25 baseline.** The current one indexes `도커` as `크` ("big"), so every
  comparison drawn against it is invalid, not merely pessimistic. See
  [the tokenizer note](#the-korean-tokenizer-problem).
- **One retriever interface**, used by both the chat and the harness. Methods are plugs.

## The corpus, and what it affords

336 source Markdown files, of which **335 are published by Nuartz** at content tree
`71c5bbda097cc20be0cb15ca4666fd6917f89d5f`; basename-leading `_` files are excluded.
The evaluation corpus follows that published set. It is Korean-language technical writing
with heavy English loanwords and code, YAML frontmatter (title, date, tags, categories),
and a `[[wikilink]]` graph between posts.

Three things make this corpus worth evaluating on, in the order measurement says they
matter:

1. **164 aliased `[[target|alias]]` occurrences in the published corpus.** The alias is
   the author's own Korean surface form for a target document - free known-item evidence
   that no public benchmark corpus has. See
   [below](#aliased-wikilinks---free-known-item-ground-truth).
2. **Mixed script.** Korean prose with English technical terms is where sparse and dense
   methods diverge most sharply, and it is under-tested in English-only benchmarks.
3. **The link graph** - but it is thinner than it looks (63% of files are isolated), so it
   supports expansion stages rather than standalone graph retrieval. Measured numbers are
   [below](#graph-and-link-structure).

An earlier draft of this file claimed the link topology was the headline differentiator
and should be over-represented. Measurement said otherwise, and the aliases hiding inside
those same links turned out to be the better prize.

## Methods

### Sparse

| Method | Status | Meant to teach |
|---|---|---|
| BM25 + Kiwi morphological tokenization | `blocked` | The baseline everything else is measured against. Blocked on the tokenizer fix below |
| BM25 + character n-grams | `planned` | Whether morphological analysis earns its complexity, or n-grams match it on mixed-script Korean |
| BM25 field weighting (title/tags/body) | `planned` | How much of retrieval quality is just "the title said so" |
| Exact substring / regex | `planned` | The floor. If a method cannot beat grep, it is not earning its cost |
| SPLADE or learned sparse | `planned` | Whether learned sparse transfers to Korean at all |

### Dense

| Method | Status | Meant to teach |
|---|---|---|
| Dense retrieval, open multilingual embeddings | `planned` | The headline sparse-vs-dense comparison on Korean technical text. Model choice pending research |
| Dense retrieval, hosted embeddings | `planned` | Whether paying for embeddings buys anything over open models here |
| Late interaction (ColBERT family) | `planned` | Whether token-level matching helps mixed-script content, and whether it is affordable at this scale |

### Fusion

| Method | Status | Meant to teach |
|---|---|---|
| Reciprocal rank fusion (sparse + dense) | `planned` | The standard hybrid. Expected to win; the interesting part is by how much and where |
| Weighted score fusion | `planned` | Whether score-level fusion beats rank-level once normalisation is done correctly |

> **Normalisation is a trap here.** The existing BM25 forces the top hit to 1.0 for *any*
> query, including nonsense, which destroys score-level fusion silently. Any fusion entry
> must state how it normalises and be tested with a query that should return nothing.

### Graph and link structure

> **Measured, and weaker than assumed.** The graph over the published corpus:
> **122 of 335 files have any edge, 213 are isolated (63.58%)**, and non-singleton
> components are `[94, 11, 4, 3, 3, 3, 2, 2]`. The `wiki/index.md` hub is degree **29**,
> not the ~100 an
> earlier pass estimated. Fixing the link parser barely helps: stripping code fences
> changes the resolved edge count by **zero**, and path-form resolution adds **8** edges
> (218 to 226). Neither changes node coverage at all.
>
> Two consequences, both binding. **A graph method is a `Stage` over a first-stage
> retriever, never a standalone retriever** - on two-thirds of queries it has nothing to
> say. And **`coverage` is a mandatory reported metric** alongside recall@k, or a method
> that declines to answer on 63% of the corpus looks strong on the third where it fires.

| Method | Status | Meant to teach |
|---|---|---|
| Wikilink one-hop expansion (as a `Stage`) | `planned` | Whether one hop from a good hit beats ranking deeper - the cheapest graph method, and the only one whose coverage limit is tolerable |
| Link-weighted reranking (PageRank-ish) | `planned` | Whether "well-connected" predicts "relevant". With 8 non-singleton components and a 94-node giant, expect this to be mostly a prior on one cluster |
| Bidirectional traversal (links + backlinks) | `planned` | Whether backlinks carry different signal from forward links |
| Hierarchical summarisation (RAPTOR-style) | `planned` | Whether a synthesised tree beats the author's hand-made links. **Now more interesting than before**, because the hand-made graph turns out to cover only a third of the corpus |
| GraphRAG-style entity graph | `planned` | Whether an inferred entity graph beats an explicit link graph that is 63% empty. A likely-positive result rather than the likely-negative one assumed earlier |

### Aliased wikilinks - free known-item ground truth

The published corpus contains **164 aliased-link occurrences** of the form
`[[target|alias]]`, where the alias is often the author's own Korean surface form for a
target document. Each resolved, unambiguous occurrence is a candidate labelled
query-to-document pair written by the person who knows the corpus best. Extraction must
deduplicate pairs and record unresolved or conflicting exclusions before treating the set
as gold.

This, not the link topology, is the genuinely novel thing this corpus offers. It is a
seed set for the qrels *and* a retrieval signal in its own right.

| Method | Status | Meant to teach |
|---|---|---|
| Alias-derived known-item query set | `planned` | Up to 164 owner-authored candidates to resolve, deduplicate, and review before any LLM-generated queries |
| Alias text as an indexed field | `planned` | Whether the author's own paraphrases beat title and body text as a match target |

### Chunking (an axis, not a method)

Chunking may matter more than retriever choice on long-form technical posts. Every
retriever above is evaluated against a chunking choice, which makes this a cross-cutting
dimension rather than a row.

| Strategy | Status | Meant to teach |
|---|---|---|
| Whole document | `planned` | The baseline. 336 documents is small enough that this is viable, unlike most corpora |
| Markdown-header-aware | `planned` | Whether the author's own structure is the right unit |
| Fixed-size with overlap | `planned` | The generic default, as a control |
| Semantic / embedding-based | `planned` | Whether inferred boundaries beat authored ones |
| Parent-document (small-to-big) | `planned` | Retrieve precisely, read broadly |
| Contextual retrieval (prepended context) | `planned` | Cost-versus-benefit of an LLM pass over every chunk at this corpus size |

### Query transformation

| Method | Status | Meant to teach |
|---|---|---|
| HyDE | `planned` | Whether a hypothetical answer helps when the corpus is one person's voice |
| Multi-query expansion | `planned` | Whether query diversity beats retriever sophistication |
| Ko/En bilingual expansion | `planned` | **Corpus-specific and high-value.** `도커`/`Docker` are the same concept in the same corpus. Whether expanding across scripts beats fixing the tokenizer |
| Step-back / decomposition | `planned` | Whether multi-hop questions need explicit decomposition |

### Reranking

| Method | Status | Meant to teach |
|---|---|---|
| Cross-encoder reranker | `planned` | The standard second stage. Whether Korean-capable cross-encoders exist and work |
| LLM-as-reranker | `planned` | Quality ceiling versus cost floor |
| Hosted rerank API | `planned` | Whether a hosted reranker beats a local one enough to justify per-query cost |

### Agentic

| Method | Status | Meant to teach |
|---|---|---|
| Iterative / multi-hop retrieval | `planned` | Whether letting the agent search repeatedly beats one good retrieval - and how to evaluate a variable number of retrievals fairly |
| Self-correcting retrieval (CRAG-style) | `planned` | Whether the agent can tell a bad retrieval from a good one, which the current scoring cannot |

### Rejected

| Method | Reason |
|---|---|
| ripgrep subprocess search | Shells out for a 2.4 MB corpus while its own in-process Python fallback does the same job correctly. Kept as an idea (see "exact substring" above), deleted as an implementation |
| Chroma vector store | Declared in `pyproject.toml` with **zero call sites**. Never wired. Dropped rather than adopted by default - the vector-store choice should follow the embedding decision, not precede it |

## The Korean tokenizer problem

Reproduced against the installed `kiwipiepy`:

```
'도커'   → [('도','JX'), ('크','VA'), ('어','EF')]   → kept: ['크']
'랭그래프' → [('랭','NNP'), ('그래프','NNG')]          → kept: ['랭','그래프']
'쿠버네티스' → [('쿠버네티스','NNG')]                    → kept: ['쿠버네티스']  ✅
```

Kiwi does not know `도커`, so it parses it as the particle 도 + the adjective 크다 + an
ending. The keep-filter (`NN`, `VV`, `VA`, `SL`) then retains only `크`. **Docker is
indexed as the word "big."** That is why a Docker query returns coding-test posts about
큰 수. `랭그래프` collapses into 그래프 the same way. Terms already in Kiwi's dictionary
are fine, so the failure is silent and selective.

Three independent fixes, all needed:

1. **A user dictionary.** `add_user_word("도커", "NNP")` restores `['도커']`, verified.
   Build it from high-precision corpus evidence: Hangul tags, the Hangul side of
   corpus-attested `한글(ASCII)` aliases, and a reviewed seed/deny list. Tags alone are
   insufficient: the current corpus has `Docker`, `LangGraph`, and `Kubernetes` tags but
   none of their Korean forms. Record each term's provenance and checksum.
2. **Drop `VV` and `VA` from the keep-list.** Verb and adjective stems are noise for
   retrieval, and worse, they are exactly what survives when an unknown noun is
   mis-analysed. Dropping them turns this failure into an empty result instead of a
   confident wrong one.
3. **Index a namespaced surface-form channel alongside morphemes**, so a term the
   dictionary has not caught up with still matches exactly instead of silently becoming a
   different word or colliding with a morphological token.

The second fix is the structural one: it converts a silent failure into a loud one. The
first two alone would fix `도커` and leave the next unknown term to fail the same way.

**Measured effect of the fix** on the published 335-document corpus, with the 13 files
containing the literal term as the qrel:

| Variant | `도커` recall@13 | raw top score |
|---|---:|---:|
| current implementation | **3 / 13** | 0.969823 |
| explicit `도커` dictionary entry | **13 / 13** | 7.397427 |
| plus `VV`/`VA` removal | **13 / 13** | 7.407296 |
| plus namespaced surface channel | **13 / 13** | 14.907699 |

The former 0/13 baseline was not reproducible on the pinned tree: three literal matches
leak into the ranking, while the top result is still an unrelated coding-test post about
`큰 수`. The former macro recall 0.323 → 0.605 is also not reproducible because no
versioned queryset or qrels exist yet. Do not use it as a gate until `topic-smoke-v1`
lands with owner-reviewed relevance labels.

Score normalisation remains a separate bug: `score / max(scores)` forces every non-empty
query's top result to 1.000 and destroys method-native magnitude. Do not normalise inside
a retriever - `rank` is authoritative, `score` stays raw, and an absent nonsense term
should produce no hit.

## Results

Populated once the harness runs. Until then this section is empty on purpose - an empty
results table is honest, and a table of guesses is not.

> **Do not headline nDCG yet.** On four smoke queries nDCG@10 read **1.000 for every one**
> while recall@10 ranged 0.23 to 0.77. With large, ungraded relevant-sets nDCG saturates
> and stops discriminating. Lead with recall@k and coverage until the qrels are small and
> genuinely graded.

| Run | Date | Methods | Dataset | Metrics | Result |
|---|---|---|---|---|---|
| _(none yet)_ | | | | | |
