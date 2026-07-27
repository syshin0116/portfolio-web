# Retrieval evaluation harness

`eval/` compares retrieval methods against the same dependency-free
`agent.retrieval.protocol.Retriever` contract used by chat serving. It is an
independent workspace member, while the repository root owns the one reviewed `uv.lock`.
Package-selective sync/export keeps evaluation-only dependencies out of the Cloud Run
agent install. `eval` imports the workspace `agent` package; `agent` never imports `eval`.

The harness consumes only a verified generated `agent/.index` mirror. It never reads
live `content/`. Every committed query-set manifest pins both the `content/` git tree SHA
and the generated corpus fingerprint. Index construction rejects tracked modifications
and untracked files under `content/`; the builder, index manifest, query-set CLI argument,
and query-set identity must all agree on the same full Git tree SHA.

## Query sets

- `querysets/known-item-alias-v1.json` is generated from the published
  `wikilinks.json` artifact. The source has 164 aliased-link occurrences: 140 included
  occurrences collapse to 90 unique, single-target known-item qrels and 24 occurrences
  are retained as explicit exclusions (conflicting alias targets, ambiguous targets,
  self-links, or unresolved targets). Its label status is
  `generated-owner-authored`, not `owner-reviewed`; it is useful for comparisons but
  cannot be published as relevance gold.
- A `topic-smoke-v1` gold set is deliberately not committed yet. Topic recall is a
  separate contract and requires owner-reviewed multi-document qrels. The synthetic
  `tests/fixtures/topic-contract-v1.json` exercises its schema and metrics without
  claiming relevance gold or enabling a macro gate.

Each source artifact records its canonical SHA-256 checksum and upstream data
dependencies. An `owner-reviewed` label claim additionally binds the exact canonical
qrels checksum plus reviewer, review date, and review reference. The parser rejects a
stale checksum or review metadata on an unreviewed set.

Methods declare their own namespaced data dependencies. Every run and report classifies
each comparison as `oracle-overlap` (the method reads a qrel source artifact),
`in-sample-overlap` (it reads an ancestor of that artifact), or `clean-holdout`.

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
uv run --frozen --package syshin0116-dev-eval blogeval validate \
  --index-root agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --dataset eval/querysets/known-item-alias-v1.json
uv run --frozen --package syshin0116-dev-eval blogeval sweep \
  --index-root agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --dataset eval/querysets/known-item-alias-v1.json \
  --output-root eval/results
run_directory="$(
  dirname "$(find eval/results -name run.json -type f -print -quit)"
)"
uv run --frozen --package syshin0116-dev-eval blogeval verify-run \
  --index-root agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --dataset eval/querysets/known-item-alias-v1.json \
  --run-directory "$run_directory"
```

The default sweep runs `bm25`, `char-ngram`, and `rrf-bm25-char-ngram`, with no model,
embedding, network, or provider cost. It writes:

```text
results/<content-tree-sha>/<run-id>/
├── leaderboard.md    # derived summary
├── manifest.json     # exact inventory, checksums, and canonical result digest
├── metrics.svg       # derived plot
├── per-query.md      # derived rankings
└── run.json          # canonical system of record
```

`results/` is generated and gitignored. The run ID automatically binds the agent and eval
source-tree digests, root lock digest, runtime platform, and Python runtime in addition
to the dataset, corpus, method fingerprints/data dependencies, and cutoffs. The result
digest binds the exact four result payloads. `verify-run` rejects partial or extra files,
checksum resealing, unregistered or registration-drifted method identities, changed
rankings or metrics, and Markdown/SVG projection drift. Verification resolves every
method fingerprint from the reviewed registry and the same checksummed corpus artifacts,
then replays every canonical qrel through that implementation at the largest cutoff and
requires an exact ranking match. A staging directory plus an exclusive lock makes
concurrent identical writers converge on one complete immutable result directory.

## Publication boundary

Every local process is publication-ineligible, including Linux x86_64 and any process
given a caller-controlled image-digest environment variable. `--require-publishable`
therefore always fails locally after first rejecting synthetic or unreviewed labels. A
process cannot prove which container launched it.

`.github/workflows/eval-publication.yml` is the only candidate-producing boundary. It is
manual, main-only, gated by the dedicated `Evaluation Publication` environment, builds a
pinned Linux amd64 image, derives its immutable image ID from Docker, executes by that
exact ID, compares the image-built content tree to `HEAD:content`, verifies the result,
and attests the sealed candidate archive with GitHub OIDC. The uploaded archive remains
explicitly non-published. This environment is deliberately separate from `Production`,
whose OIDC identity can reach GCP deployment resources.

Promotion into the retrieval-method catalogue requires all of these external checks:

1. The repository `Evaluation Publication` environment exists with the exact governance
   policy (main branch only, `syshin0116` required reviewer,
   `prevent_self_review=false`, no admin bypass). On 2026-07-28, the frozen live
   repository-governance verifier passed for those policy fields and its fail-closed
   secret/variable inventory count checks. An independent direct GitHub API check also
   confirmed zero environment secrets and zero variables. The verifier ignores and
   never logs inventory entries; it only validates that both `total_count` and the
   returned list length are zero.
2. The reviewer approves the manual workflow for the intended main commit.
3. Download the `blogeval-publication-candidate-<sha>` artifact. In a clean worktree
   checked out at that exact main commit, rebuild the verified corpus index before
   running the verifier:

   ```bash
   expected_commit=<40-character-main-commit>
   test "$(git rev-parse HEAD)" = "$expected_commit"
   uv run --frozen --package syshin0116-dev-agent \
     python scripts/build_index.py --expect-document-count 335
   content_tree_sha="$(git rev-parse HEAD:content)"
   uv run --frozen --package syshin0116-dev-eval \
     blogeval verify-publication \
     --archive blogeval-candidate.tar.gz \
     --index-root agent/.index \
     --content-tree-sha "$content_tree_sha" \
     --dataset eval/querysets/known-item-alias-v1.json \
     --expected-commit "$expected_commit" \
     --workspace-root .
   ```

   This command directly requires `gh attestation verify` with the exact repository,
   signer workflow, main ref, source/signer commit, and GitHub-hosted runner policy. It
   then requires `HEAD` to equal that commit, rejects dirty agent/eval source or
   `uv.lock`, and matches their measured digests to the attested run. Finally it checks
   the archive inventory, canonical candidate metadata, owner-reviewed label/checksum,
   content tree, image/result digests, Linux x86_64 runtime, run ID, reviewed registry
   identity, and every regenerated result projection.
4. Only after that command succeeds may its result digest be copied into the catalogue.

The currently committed 90-query set intentionally fails step 3 until its qrels receive
an explicit owner review. As of 2026-07-28, the manual publication workflow has not been
dispatched and no evaluation result is claimed as published gold.

## Development gates

```bash
uv lock --check
uv sync --frozen --package syshin0116-dev-eval --all-groups
uv run --frozen --package syshin0116-dev-eval ruff check eval/src eval/tests
uv run --frozen --package syshin0116-dev-eval \
  ruff format --check eval/src eval/tests
uv run --frozen --package syshin0116-dev-eval pytest
```
