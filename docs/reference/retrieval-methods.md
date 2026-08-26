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
updated: "2026-08-20"
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
| `implemented` | Works and passes its repository contracts; deterministic synthetic/CI evidence may exist, but no accepted publication result is claimed |
| `evaluated` | Has retained numbers from an accepted, publication-qualified run against the named dataset/corpus/method fingerprints |
| `rejected` | Tried or assessed and dropped - **the reason is the point** |
| `blocked` | Waiting on something named |

The distinction is deliberate. PR CI runs provider-free sweeps to prove reproducibility,
metrics, and report generation, but those numbers do not promote a method to `evaluated`.
Promotion requires the repository's publication gate, including acceptable label status,
attested Linux image/source provenance, and a retained result digest.

## Prerequisites

Two things gate every entry in this table, both from
[ADR-0008](../adr/0008-chatbot-is-a-rag-evaluation-testbed.md):

- **A correct BM25 baseline.** The legacy implementation indexed `도커` as `크` ("big"),
  so comparisons drawn against it were invalid, not merely pessimistic. The corrected
  fitted baseline below is now the comparison floor. See
  [the tokenizer note](#the-korean-tokenizer-problem).
- **One retriever interface**, intended for both the chat and the harness. The chat now
  resolves its configured method from the shared servable registry; the evaluation
  harness extends a copy of that registry and executes the same Protocol.

## The corpus, and what it affords

337 source Markdown files, of which **336 are published by Nuartz**; basename-leading
`_` files are excluded.
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
3. **The link graph** - but it is thinner than it looks (**65.77%** of files are
   isolated), so it supports expansion stages rather than standalone graph retrieval.
   Measured numbers are [below](#graph-and-link-structure).

An earlier draft of this file claimed the link topology was the headline differentiator
and should be over-represented. Measurement said otherwise, and the aliases hiding inside
those same links turned out to be the better prize.

## Methods

### Sparse

| Method | Status | Meant to teach |
|---|---|---|
| BM25 + Kiwi morphological tokenization | `implemented` | The fitted, raw-score baseline everything else is measured against |
| Character n-grams over raw Markdown + positive-IDF BM25 variant | `implemented` | A compound lexical alternative; it changes document representation and IDF/ranker behavior, so it is not a tokenizer-only morphology ablation |
| BM25 field weighting (title/tags/body) | `implemented` | How much of retrieval quality is just "the title said so" |
| Exact substring | `implemented` | The safe literal-match floor. If a method cannot beat it, it is not earning its cost |
| Bounded regex | `planned` | Whether regex expressiveness adds useful recall without exposing unbounded query execution |
| SPLADE or learned sparse | `planned` | Whether learned sparse transfers to Korean at all |

The field-weighted arm is a BM25F comparison, not a second baseline: it reuses the
verified fitted BM25 term IDFs and exact Kiwi/dictionary tokenizer, then changes only
field-aware term-frequency saturation. Its fingerprinted configuration fixes title,
tags, and body boosts at 3:2:1, applies length normalisation only to body, and groups the
frontmatter description with Markdown body. It is registered once in the agent's
servable registry, which the evaluation registry copies unchanged. Field statistics are
derived deterministically at runtime from the checksum-verified published mirror and
catalog; the method identity binds the catalog checksum and fitted-baseline fingerprint.
`implemented` means the shared contract and synthetic harness evidence pass; no
publication-qualified score exists yet.

### Dense

| Method | Status | Meant to teach |
|---|---|---|
| `dense-multilingual-e5-small` (open multilingual embeddings) | `implemented` | The headline sparse-vs-dense comparison on Korean technical text, using one pinned provider-free arm |
| Dense retrieval, hosted embeddings | `planned` | Whether paying for embeddings buys anything over open models here |
| Late interaction (ColBERT family) | `planned` | Whether token-level matching helps mixed-script content, and whether it is affordable at this scale |

The first dense arm pins
[`intfloat/multilingual-e5-small`](https://huggingface.co/intfloat/multilingual-e5-small)
to immutable revision
[`d1d99a1efae6779390caba937d92c54b5bc70e51`](https://huggingface.co/intfloat/multilingual-e5-small/tree/d1d99a1efae6779390caba937d92c54b5bc70e51).
Its fingerprint fixes the E5 `query: ` / `passage: ` asymmetric prefixes,
384-dimensional normalized embeddings, 512-token truncation, CPU float32 execution,
exact NumPy/sentence-transformers/Torch/Transformers versions, PyTorch's CPU-only wheel
source, and an offline-only local-cache policy. The frozen 336-document corpus is embedded
once per retriever instance and searched by exact in-memory cosine similarity; there is
no vector database whose index policy could become an accidental second experimental
variable. Torch and the model runtime remain an optional `eval/` extra and never enter the
serving agent package.

Deterministic fake-embedding contracts cover ordering, ties, normalization, malformed
vectors, prompt prefixes, and model-loader policy. A separately opt-in smoke exercises
the already-cached real checkpoint without network access. This is repository evidence
for `implemented`, not a retained quality result: no accepted dense sweep or
publication-qualified result digest exists yet.

### Fusion

| Method | Status | Meant to teach |
|---|---|---|
| `rrf-bm25-dense-multilingual-e5-small` (BM25 + dense) | `implemented` | The standard hybrid; its exact component fingerprints make the first three-arm experiment executable without comparing incompatible raw scores |
| Reciprocal rank fusion (BM25 + character n-grams) | `implemented` | A provider-free fusion control that proves composition and fingerprints before a dense method lands |
| Weighted score fusion | `planned` | Whether score-level fusion beats rank-level once normalisation is done correctly |

> **Normalisation is a trap here.** The deleted legacy BM25 forced the top hit to 1.0 for
> *any* non-empty query, including nonsense, which destroyed score-level fusion silently.
> The corrected methods retain raw native scores. Any future score-fusion entry must state
> how it normalises and be tested with a query that should return nothing.

### Graph and link structure

> **Measured, and weaker than assumed.** The graph over the published corpus:
> **115 of 336 files have any edge, 221 are isolated (65.77%)**, and non-singleton
> components are `[48, 39, 11, 4, 3, 3, 3, 2, 2]`. The `wiki/index.md` hub is degree
> **29**, not the ~100 an earlier pass estimated. The ambiguity-safe resolver emits
> **213 edges** after content-relative and source-relative resolution and excludes seven
> remaining multi-candidate occurrences instead of silently connecting the
> lexicographically first document.
>
> Two consequences, both binding. **A graph method is a `Stage` over a first-stage
> retriever, never a standalone retriever** - on two-thirds of queries it has nothing to
> say. And **`coverage` is a mandatory reported metric** alongside recall@k, or a method
> that declines to answer on 65.77% of the corpus looks strong on the third where it fires.

| Method | Status | Meant to teach |
|---|---|---|
| Wikilink one-hop expansion (as a `Stage`) | `planned` | Whether one hop from a good hit beats ranking deeper - the cheapest graph method, and the only one whose coverage limit is tolerable |
| Link-weighted reranking (PageRank-ish) | `planned` | Whether "well-connected" predicts "relevant". With 9 non-singleton components and a 48-node largest component, expect this to be mostly a prior on one cluster |
| Bidirectional traversal (links + backlinks) | `planned` | Whether backlinks carry different signal from forward links |
| Hierarchical summarisation (RAPTOR-style) | `planned` | Whether a synthesised tree beats the author's hand-made links. **Now more interesting than before**, because the hand-made graph turns out to cover only a third of the corpus |
| GraphRAG-style entity graph | `planned` | Whether an inferred entity graph beats an explicit link graph that is 65.77% empty. A likely-positive result rather than the likely-negative one assumed earlier |

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
| Alias-derived known-item query set | `implemented` | 164 owner-authored occurrences resolve to 90 single-target qrels; 24 conflicting, ambiguous, self-link, or unresolved occurrences remain recorded exclusions |
| Alias text as an indexed field | `planned` | Whether the author's own paraphrases beat title and body text as a match target |

### Chunking (an axis, not a method)

Chunking may matter more than retriever choice on long-form technical posts. Every run
must record its chunking choice, which makes this a cross-cutting dimension rather than a
retrieval method. All current implementations use one whole published document per hit.

| Strategy | Status | Meant to teach |
|---|---|---|
| Whole document | `implemented` | The current baseline over 336 published documents; hits and qrels resolve to content-relative document IDs |
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
| Chroma vector store | Previously declared in `pyproject.toml` with **zero call sites** and removed after an unpatched critical advisory. Never wired. Dropped rather than adopted by default - the vector-store choice should follow the embedding decision, not precede it |

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

1. **A reviewed user dictionary plus candidate evidence.** `add_user_word("도커", "NNP")`
   restores `['도커']`, verified. Hangul tags and the Hangul side of corpus-attested
   `한글(ASCII)` aliases are valuable candidate evidence, but they are not automatically
   safe NNPs: the corpus also yields grammatical forms (`크다`, `없다`, `검증하고`) and
   compounds whose components aid recall (`개발+도구`). Store all candidates and sorted
   provenance in `dictionary-evidence.json`; activate only owner-reviewed seeds, with
   deny taking precedence. Tags alone are insufficient: the corpus has `Docker`,
   `LangGraph`, and `Kubernetes` tags but none of their Korean forms.
2. **Drop `VV` and `VA` from the keep-list.** Verb and adjective stems are noise for
   retrieval, and worse, they are exactly what survives when an unknown noun is
   mis-analysed. Dropping them turns this failure into an empty result instead of a
   confident wrong one.
3. **Index a namespaced surface-form channel alongside morphemes**, so a term the
   dictionary has not caught up with still matches exactly instead of silently becoming a
   different word or colliding with a morphological token.

The second fix is the structural one: it converts a silent failure into a loud one. The
first two alone would fix `도커` and leave the next unknown term to fail the same way.

The deployed tokenizer pins Kiwi 0.23.2, the separate `kiwipiepy-model` 0.23.0 data
package, and the `cong` model; it keeps the default dictionary and disables the typo and
Wikidata multiword dictionaries. The latter avoids a roughly 150 MiB runtime cost and
preserves component tokens; the exact `s:` channel still covers a full surface form. The
active real dictionary is exactly `도커` and `랭그래프`.

**Measured effect of the fix** on the published 335-document corpus, with the 13 files
containing the literal term as the qrel:

| Variant | `도커` recall@13 | raw top score |
|---|---:|---:|
| legacy pre-fix tokenizer | **3 / 13** | ≈ 0.9698 |
| explicit `도커` dictionary entry | **13 / 13** | 7.397427 |
| plus `VV`/`VA` removal | **13 / 13** | 7.407296 |
| reviewed seeds + namespaced surface channel + pinned CoNg config | **13 / 13** | ≈ 14.908 |

The raw-score values in this comparison are observations, not cross-platform golden
constants. Kiwi's optimized kernels produce small architecture-specific floating-point
differences even with pinned package and model versions. The qrel therefore gates the
portable behavior (literal set and recall), while a separate differential test requires
the fitted artifact to match `rank-bm25` exactly on the platform that built it. Production
artifacts are built and evaluated in the pinned Linux x86_64 deployment image.

The former 0/13 baseline was not reproducible on the pinned tree: three literal matches
leak into the ranking, while the top result is still an unrelated coding-test post about
`큰 수`. The former macro recall 0.323 → 0.605 is also not reproducible. A versioned
`topic-smoke-v1` query seed and fail-closed owner-review workflow now exist. The seed
pins the exact sparse, dense, and fusion candidate methods so agents cannot silently
change the judgement pool, but no reviewed query-set or qrels exist. Do not use the old
number as a gate until the owner seals the relevance labels and the final dataset passes
publication qualification.

Score normalisation was a separate legacy bug: `score / max(scores)` forced every
non-empty query's top result to 1.000 and destroyed method-native magnitude. The corrected
implementations do not normalise inside a retriever: `rank` is authoritative, `score`
stays raw, and an absent nonsense term produces no hit.

The corrected implementation fits `rank-bm25` exactly once during the one-scan corpus
build, then stores document lengths, first-seen-order IDFs, and sparse postings in a
deterministic SQLite artifact. Runtime opens it read-only and immutable and queries only
the postings needed for the query; it neither retains raw token documents nor constructs
`BM25Okapi`. Scores at or below zero are intentionally omitted, including common-term
negative IDFs and the exact half-corpus zero-IDF boundary.

The current `char-ngram` method reads raw published Markdown (including frontmatter) and
uses Lucene's always-positive BM25 IDF, while the Kiwi baseline uses structured fields
and `rank-bm25`'s Okapi IDF behavior. Its fingerprint declares both differences. Treat
its result as a compound lexical baseline; a tokenizer-only morphology experiment still
needs a shared field extractor and ranker.

## Results

Populated once the harness runs inside the digest-pinned Linux x86_64 deployment image.
The earlier macOS ARM bootstrap run is intentionally unpublished: its run identity did
not bind source trees, the shared lock, or execution image provenance. An empty results
table is honest, and a table of non-comparable numbers is not.

> **Do not headline nDCG yet.** On four smoke queries nDCG@10 read **1.000 for every one**
> while recall@10 ranged 0.23 to 0.77. With large, ungraded relevant-sets nDCG saturates
> and stops discriminating. Lead with recall@k and coverage until the qrels are small and
> genuinely graded.

No publication-qualified run exists yet.
