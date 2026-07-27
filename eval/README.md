# Retrieval evaluation harness

`eval/` compares retrieval methods against the same dependency-free
`agent.retrieval.protocol.Retriever` contract used by chat serving. It is an
independent workspace member, while the repository root owns the one reviewed `uv.lock`.
Package-selective sync/export keeps evaluation-only dependencies out of the Cloud Run
agent install. `eval` imports the workspace `agent` package; `agent` never imports `eval`.

The harness consumes only a verified generated `agent/.index` mirror. It never reads
live `content/`. Every committed query-set manifest pins both the `content/` git tree SHA
and the generated corpus fingerprint.

## Query sets

- `querysets/known-item-alias-v1.json` is generated from the published
  `wikilinks.json` artifact. The source has 164 aliased-link occurrences: 140 included
  occurrences collapse to 90 unique, single-target known-item qrels and 24 occurrences
  are retained as explicit exclusions (conflicting alias targets, ambiguous targets,
  self-links, or unresolved targets).
- A `topic-smoke-v1` gold set is deliberately not committed yet. Topic recall is a
  separate contract and requires owner-reviewed multi-document qrels. The synthetic
  `tests/fixtures/topic-contract-v1.json` exercises its schema and metrics without
  claiming relevance gold or enabling a macro gate.

Known-item reports headline Hit@k, MRR@k, and coverage. Topic reports headline recall@k
and coverage. The report generator does not calculate a headline nDCG score.

## Reproduce the offline sweep

From the repository root:

```bash
uv lock --check
uv sync --frozen --package syshin0116-dev-agent --all-extras --dev
uv run --frozen --package syshin0116-dev-agent \
  python scripts/build_index.py --expect-document-count 335

uv sync --frozen --package syshin0116-dev-eval --all-groups
content_tree_sha="$(git rev-parse HEAD:content)"
uv run --frozen --package syshin0116-dev-eval blogeval generate-known-item \
  --index-root agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --output eval/querysets/known-item-alias-v1.json \
  --check
uv run --frozen --package syshin0116-dev-eval blogeval sweep \
  --index-root agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --dataset eval/querysets/known-item-alias-v1.json \
  --output-root eval/results
```

The default sweep runs `bm25`, `char-ngram`, and `rrf-bm25-char-ngram`, with no model,
embedding, network, or provider cost. It writes:

```text
results/<content-tree-sha>/<run-id>/
├── run.json          # canonical system of record
├── leaderboard.md    # derived summary
├── per-query.md      # derived rankings
└── metrics.svg       # derived plot
```

`results/` is generated and gitignored. The run ID automatically binds the agent and eval
source-tree digests, root lock digest, runtime platform, Python runtime, and optional OCI
image digest in addition to the dataset, corpus, methods, and cutoffs. A repeated run over
identical inputs and execution provenance produces the same run ID and the same bytes.

Local macOS and unpinned runner output is useful for development but is marked
publication-ineligible in `run.json` and the leaderboard. A result may be copied into the
catalogue only after running inside the actual digest-pinned Linux x86_64 image with
`BLOGEVAL_IMAGE_DIGEST=sha256:<64 lowercase hex>` and `--require-publishable`. The
environment value records the image already executing the command; it is not a substitute
for entering that image.

## Development gates

```bash
uv lock --check
uv sync --frozen --package syshin0116-dev-eval --all-groups
uv run --frozen --package syshin0116-dev-eval ruff check eval/src eval/tests
uv run --frozen --package syshin0116-dev-eval \
  ruff format --check eval/src eval/tests
uv run --frozen --package syshin0116-dev-eval pytest
```
