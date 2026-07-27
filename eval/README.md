# Retrieval evaluation harness

`eval/` compares retrieval methods against the same dependency-free
`agent.retrieval.protocol.Retriever` contract used by chat serving. It is an
independently locked uv project so evaluation-only packages and later lab methods cannot
enter the Cloud Run agent install. Its local path dependency imports `agent`; `agent`
never imports `eval`.

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
cd agent
uv sync --frozen --all-extras --dev
uv run --frozen python ../scripts/build_index.py --expect-document-count 335

cd ../eval
uv sync --frozen --all-groups
content_tree_sha="$(git -C .. rev-parse HEAD:content)"
uv run --frozen blogeval generate-known-item \
  --index-root ../agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --output querysets/known-item-alias-v1.json \
  --check
uv run --frozen blogeval sweep \
  --index-root ../agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --dataset querysets/known-item-alias-v1.json
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

`results/` is generated and gitignored. A repeated run over identical dataset, corpus,
method/config fingerprints, and cutoffs produces the same run ID and the same bytes.

## Development gates

```bash
uv lock --check
uv sync --frozen --all-groups
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
uv run --frozen pytest
```
