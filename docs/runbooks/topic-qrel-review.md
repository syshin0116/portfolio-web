---
title: "Topic qrel owner-review workflow"
description: >
  Generate a deterministic blind candidate pool, record the blog owner's topic-level
  relevance judgements, and materialize `topic-smoke-v1` without promoting retrieval
  output into relevance gold.
when_to_read: >
  Before creating or editing topic-smoke qrels, changing the candidate methods, sealing
  an owner review, or dispatching a topic evaluation publication candidate.
tags: [runbook, rag, evaluation, qrels, retrieval, publication]
status: stable
updated: "2026-08-01"
owners: ["@syshin0116"]
refs:
  - ../adr/0008-chatbot-is-a-rag-evaluation-testbed.md
  - ../plans/rag-restack.md
  - ../reference/retrieval-methods.md
  - ../../eval/README.md
  - ../../eval/querysets/topic-smoke-v1.seed.json
  - ../../.github/workflows/eval-publication.yml
template: runbook
---

# Topic qrel owner-review workflow

`topic-smoke-v1` is not relevance gold yet. The repository contains a versioned query
seed and the tooling below, but it intentionally contains neither
`topic-smoke-v1.review.json` nor `topic-smoke-v1.json`. Only the blog owner can supply the
missing judgements.

The six seed queries are transcribed from the topic and cross-lingual examples in the
owner-authored [blog search experiment plan](../../content/AI/2026-04-04-블로그-검색-실험-1-실험설계.md).
That authorship makes the queries useful candidates; it does not make any document
relevant by default.

## Files and states

| File | State | Meaning |
| --- | --- | --- |
| `eval/querysets/topic-smoke-v1.seed.json` | committed | Versioned queries and exact candidate method/limit policy; contains no labels |
| `eval/querysets/topic-smoke-v1.review.json` | initially `pending-owner-review` | Deterministic blind pool plus owner-editable judgements |
| `eval/querysets/topic-smoke-v1.review.json` | later `owner-reviewed` | Every candidate judged, each pool declared complete, and exact decisions checksum-sealed with review provenance |
| `eval/querysets/topic-smoke-v1.json` | generated only from the sealed review | `blogeval-queryset-v3` topic qrels with exact candidate-pooling provenance, accepted by the harness and publication verifier |

Never hand-create the final query-set and never set either `owner-reviewed` status by
editing JSON. `seal-topic-review` is the only transition into the reviewed state, and
`finalize-topic-review` is the only transition from reviewed decisions to qrels.

## 1. Build the exact published mirror

From a clean feature worktree:

```bash
uv lock --check
uv sync --frozen --package syshin0116-dev-agent --all-extras --dev
uv sync --frozen --package syshin0116-dev-eval --extra dense --all-groups
uv run --frozen --package syshin0116-dev-agent \
  python scripts/build_index.py --expect-document-count 335
content_tree_sha="$(git rev-parse HEAD:content)"
```

The tooling reads only the verified generated mirror. It never reads live `content/` to
derive candidates or qrels.

## 2. Generate the blind candidate pool

Generate only after every seed-pinned method is registered. The seed deliberately pins
the sparse arms `bm25`, `bm25-field-weighted`, and `char-ngram`; the dense arm
`dense-multilingual-e5-small`; and the fusion arms `rrf-bm25-char-ngram` and
`rrf-bm25-dense-multilingual-e5-small`, each at a limit of 20. Do not start the final
owner review until both dense registry IDs have landed. A sparse-only pool would bias
the relevance set toward the sparse methods it is meant to evaluate, so the command
offers no method or limit override:

```bash
uv run --frozen --package syshin0116-dev-eval blogeval generate-topic-review \
  --index-root agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --seed eval/querysets/topic-smoke-v1.seed.json \
  --output eval/querysets/topic-smoke-v1.review.json
```

The manifest records sorted method IDs and exact fingerprints, but each candidate shows
only a deterministic blind ID and `DocId`; it does not reveal which method retrieved the
document or at what rank. Re-running with the same seed, corpus, and registry is
byte-stable. Generation creates a missing file or accepts identical bytes but refuses to
overwrite any existing manual progress. `--check` replays the seed-pinned pool while
preserving completed judgement fields.

## 3. Perform the owner review

For every query, the owner must do all of the following in the pending review JSON:

1. Open each pooled `DocId` from `agent/.index/posts/` and change `judgement` from
   `pending` to exactly `relevant` or `not-relevant`.
2. Search the verified `agent/.index/catalog.json` and published mirror for relevant
   documents missed by every candidate method. Add those DocIds to the sorted,
   duplicate-free `additional_relevant_doc_ids` list. Do not add a pooled candidate to
   that list.
3. Set `candidate_pool_complete` to `true` only after deciding that the relevant set is
   complete enough to support recall. Pooling is an acknowledged evaluation limitation;
   this boolean is an explicit owner attestation, not an automatic inference.
4. Leave `candidate_generation`, `corpus`, `seed_checksum`, blind IDs, query text, and the
   entire `labels` object unchanged.

Validate at any point. Pending work is valid, but the JSON summary reports its exact
pending-judgement and incomplete-pool counts:

```bash
uv run --frozen --package syshin0116-dev-eval blogeval validate-topic-review \
  --index-root agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --seed eval/querysets/topic-smoke-v1.seed.json \
  --review eval/querysets/topic-smoke-v1.review.json
```

Candidate, seed, corpus, or method drift fails because validation reconstructs the pool
from the reviewed registry. A manual DocId outside the exact published mirror also fails.

## 4. Owner-only seal and finalization

First commit the fully judged but still-pending manifest. That commit is the immutable
input referenced by the owner's seal:

```bash
review_commit="$(git rev-parse HEAD)"
uv run --frozen --package syshin0116-dev-eval blogeval seal-topic-review \
  --index-root agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --seed eval/querysets/topic-smoke-v1.seed.json \
  --review eval/querysets/topic-smoke-v1.review.json \
  --output eval/querysets/topic-smoke-v1.review.json \
  --reviewer @syshin0116 \
  --reviewed-at YYYY-MM-DD \
  --review-ref "git:$review_commit" \
  --workspace-root .

uv run --frozen --package syshin0116-dev-eval blogeval finalize-topic-review \
  --index-root agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --seed eval/querysets/topic-smoke-v1.seed.json \
  --review eval/querysets/topic-smoke-v1.review.json \
  --output eval/querysets/topic-smoke-v1.json

uv run --frozen --package syshin0116-dev-eval blogeval validate \
  --index-root agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --dataset eval/querysets/topic-smoke-v1.json
```

Sealing refuses a pending judgement, an incomplete pool, a query with no relevant
document, any reviewer other than the exact repository owner, or a review reference that
is not an ancestor commit containing byte-for-byte the pending manifest being sealed. It
checksums the exact seed, corpus, method fingerprints, blind pool, manual additions,
completeness decisions, and judgements. Finalization replays the candidate methods again
and gives the final qrels their own exact checksum. Any later edit makes one of those
checks fail. The Git binding makes provenance reproducible; GitHub's protected
owner-reviewed PR and `Evaluation Publication` approval remain the authentication
boundary for the owner claim because an unsigned local commit alone is not identity
proof.

An agent may prepare the pool and validate it, but it must not execute the seal using
invented owner metadata. The `reviewer`, date, reference, and relevance judgements are
owner actions.

## 5. Publication

After the sealed review and generated query-set merge to `main`, the remaining dense
method gate must also provide the exact pinned E5 snapshot inside the immutable
publication image; the retriever is deliberately `local_files_only` and an Actions host
cache is not evidence. The image already installs all eval extras, but this branch does
not invent or download that model artifact. Until its separately reviewed packaging
lands, a topic dispatch must fail closed at dense model creation.

Once that gate lands, manually dispatch `Evaluation publication candidate` with
`dataset=topic-smoke-v1`. The workflow has a closed two-value choice, regenerates and
checks the final query-set from the sealed review, explicitly sweeps the same six
seed-pinned sparse/dense/fusion arms (while the provider-free CI default remains four
lightweight arms), and emits publication candidate schema v2. Candidate metadata binds
both the dataset ID and exact dataset checksum in addition to the content tree, image,
run, result, workflow, and commit identities.

The artifact is named
`blogeval-publication-candidate-topic-smoke-v1-<commit-sha>`. External verification uses
the topic dataset:

```bash
uv run --frozen --package syshin0116-dev-eval blogeval verify-publication \
  --archive blogeval-candidate.tar.gz \
  --index-root agent/.index \
  --content-tree-sha "$(git rev-parse HEAD:content)" \
  --dataset eval/querysets/topic-smoke-v1.json \
  --expected-commit "$(git rev-parse HEAD)" \
  --workspace-root .
```

No catalogue score, macro-recall gate, or `evaluated` method status may be claimed until
that external verifier succeeds. A local sweep, a pending review, and a GitHub candidate
artifact are each explicitly insufficient.
