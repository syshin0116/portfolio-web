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
- `querysets/topic-smoke-v1.seed.json` contains six versioned topic and cross-lingual
  queries transcribed from the owner's published experiment plan and pins the exact
  sparse, dense, and fusion candidate methods plus per-method limit, but contains no
  relevance labels. The deterministic blind-pool, validation, owner seal, and
  finalization workflow is documented in `docs/runbooks/topic-qrel-review.md`. The
  review and final gold files remain deliberately absent until the owner judges every
  candidate and attests pool completeness. The synthetic
  `tests/fixtures/topic-contract-v1.json` exercises the topic schema and metrics without
  claiming relevance gold or enabling a macro gate.

Each source artifact records its canonical SHA-256 checksum and upstream data
dependencies. An `owner-reviewed` label claim additionally binds the exact canonical
qrels checksum plus reviewer, review date, and review reference. The parser rejects a
stale checksum or review metadata on an unreviewed set.

Methods declare their own namespaced data dependencies. Every run and report classifies
each comparison as `oracle-overlap` (the method reads a qrel source artifact),
`in-sample-overlap` (it reads an ancestor of that artifact),
`candidate-pool-overlap` (the exact method fingerprint contributed documents to a topic
judgement pool), or `clean-holdout`. Query-set schema v3 retains the blind-pool method
fingerprints and sealed review/seed checksums so a pooled method cannot be mislabeled as
a clean holdout after finalization.

Known-item reports headline Hit@k, MRR@k, and coverage. Topic reports headline recall@k
and coverage. The report generator does not calculate a headline nDCG score.

## Reproduce the offline sweep

From the repository root:

```bash
uv lock --check
uv sync --frozen --package syshin0116-dev-agent --all-extras --dev
uv run --frozen --package syshin0116-dev-agent \
  python scripts/build_index.py

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

The default sweep runs `bm25`, `bm25-field-weighted`, `char-ngram`, and
`rrf-bm25-char-ngram`, with no model, embedding, network, or provider cost. It writes:

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

## Opt-in first dense experiment

The first dense arm is `dense-multilingual-e5-small`: an exact in-memory cosine scan of
the frozen published corpus using `intfloat/multilingual-e5-small` at commit
`d1d99a1efae6779390caba937d92c54b5bc70e51`. Its runtime is an optional eval-only
dependency and never enters the agent image:

```bash
uv sync --frozen --package syshin0116-dev-eval --extra dense --all-groups
```

The dense extra pins `torch==2.13.0` to PyTorch's explicit CPU-only wheel index and
`transformers==5.14.1` to the reviewed runtime. Linux must not resolve the CUDA/Triton
wheel graph for this CPU experiment.

Model loading is deliberately offline-only (`local_files_only=true`) and fails closed
unless that exact revision is already present in the Hugging Face cache. Cache population
is a separate, explicit operator action; `blogeval` never downloads a model. This bounded
command fetches only the files needed by the PyTorch sentence-transformers path at the
immutable revision (roughly 500 MB), excluding the repository's ONNX, OpenVINO, and
duplicate PyTorch-bin weights:

```bash
uv run --frozen --package syshin0116-dev-eval --extra dense python - <<'PY'
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="intfloat/multilingual-e5-small",
    revision="d1d99a1efae6779390caba937d92c54b5bc70e51",
    allow_patterns=(
        "1_Pooling/config.json",
        "config.json",
        "config_sentence_transformers.json",
        "model.safetensors",
        "modules.json",
        "sentence_bert_config.json",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ),
)
PY
```

E5's exact `query: ` and `passage: ` prefixes, 384 dimensions, 512-token truncation,
CPU float32 runtime, exact NumPy/sentence-transformers/Torch/Transformers versions, model
revision, and normalization policy are all part of the retriever fingerprint. The
current corpus scale does not justify adding a vector database before measurements show a
need.

After caching the pinned snapshot, run the planned three-arm comparison explicitly:

```bash
uv run --frozen --package syshin0116-dev-eval --extra dense blogeval sweep \
  --index-root agent/.index \
  --content-tree-sha "$content_tree_sha" \
  --dataset eval/querysets/known-item-alias-v1.json \
  --output-root eval/results \
  --method bm25 \
  --method dense-multilingual-e5-small \
  --method rrf-bm25-dense-multilingual-e5-small
```

The same optional environment can execute a cache-only real-model smoke with
`BLOGEVAL_REAL_DENSE_SMOKE=1`; the test still refuses network access. The ordinary test
suite uses deterministic fake embeddings so CI remains free of model downloads and
provider cost. An opt-in local result is still publication-ineligible and does not
promote either dense method to `evaluated`.

## Publication boundary

Every local process is publication-ineligible, including Linux x86_64 and any process
given a caller-controlled image-digest environment variable. `--require-publishable`
therefore always fails locally after first rejecting synthetic or unreviewed labels. A
process cannot prove which container launched it.

`.github/workflows/eval-publication.yml` is the only candidate-producing boundary. It is
manual, main-only, gated by the dedicated `Evaluation Publication` environment, and has
an exact choice between `known-item-alias-v1` and `topic-smoke-v1`. The latter fails
closed until both the sealed owner review and its deterministically finalized query-set
exist. The workflow builds a pinned Linux amd64 image, derives its immutable image ID
from Docker, executes by that exact ID, compares the image-built content tree to
`HEAD:content`, verifies the result, and attests the sealed candidate archive with GitHub
OIDC. The topic path installs all eval extras and explicitly evaluates the six seed-pinned
sparse/dense/fusion arms; the normal CI default stays at four lightweight provider-free
methods. It remains intentionally blocked until the dense-method PR or a follow-up binds
the exact pinned E5 snapshot into that immutable image—an ephemeral Actions cache is not
accepted. Candidate schema v2 binds the dataset ID and checksum, and the uploaded archive
remains explicitly non-published. This environment is deliberately separate from
`Production`, whose OIDC identity can reach GCP deployment resources.

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
3. Download the
   `blogeval-publication-candidate-<dataset-id>-<sha>` artifact. In a clean worktree
   checked out at that exact main commit, rebuild the verified corpus index before
   running the verifier (the example below uses the currently committed known-item
   dataset; select `topic-smoke-v1.json` for a reviewed topic run):

   ```bash
   expected_commit=<40-character-main-commit>
   test "$(git rev-parse HEAD)" = "$expected_commit"
   uv run --frozen --package syshin0116-dev-agent \
     python scripts/build_index.py
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
an explicit owner review. `topic-smoke-v1` cannot reach the workflow at all until its
owner review is sealed and finalized. No evaluation result is claimed as published gold.

## QuickJS × dynamic-subagent capability experiment

`querysets/capability-tasks-v1.json` is a separate, content-tree-pinned contract for
P4.5. It contains structured direct-answer, ranked-list transform, stateless evidence,
and combined tasks. It is not a retrieval query-set and is never accepted by `sweep` or
rendered into `leaderboard.md`. Its v1 label status is `synthetic-only`; it proves the
harness and capability boundaries but is not owner-reviewed evidence for public
enablement. The runner recognizes two non-public evidence tiers:
`synthetic-provider-free` for the deterministic fixture and
`provider-backed-local-unattested` for a bounded local OpenAI Responses run. Neither can
be relabelled as signed publication evidence or justify enabling a capability for
visitors.

`blogeval.capability_runner.run_capability_experiment` owns the exact four arms:
QuickJS off/on × subagents off/on. A provider adapter implements `CapabilityExecutor`
and receives a server-owned `CapabilityExecutionContext` containing the fixed arm, a
deterministic per-attempt seed, fresh attempt/thread/graph-run identities, an ordinary
Aegra run config with no capability override, and one real non-serializable `RunBudget`.
`build_capability_graph` compiles the native Deep Agents graph from that context. The
server selection may remove an otherwise authorized capability; client config still
cannot grant one. Production owner runs retain all four server-declared specialists,
while this evaluation path compiles only `evidence-checker`; the native system prompt,
bound `task` tool description, execution allowlist, and recorded subtype therefore share
the same one-specialist inventory.

Each sweep requires a fresh UUIDv4 execution ID. A deterministic four-row Williams
schedule counterbalances arm position per task while artifacts retain one canonical arm
and task order. Every zero-spend preflight retry receives a different attempt, thread,
graph-run ID, and seed; a failure after any model/tool/capability spend is never retried
or omitted from generation-token accounting. `max_attempts` is bounded to three. The run boundary measures
`HEAD:content` from the required local workspace, rejects tracked, staged, or untracked
`content/` drift, and requires the measured tree to equal both the dataset and executor
identity. The paid adapter additionally requires the verified published-index manifest
tree to equal the task-set tree before provider identity or credentials are touched. It
also caps the task set and every `RunBudgetPolicy` field, and rejects the
experiment before its first executor call unless a conservative four-arm worst-case
generation-token cost fits the explicit micro-dollar ceiling. OpenAI does not document
whether `/responses/input_tokens` requests are billed, so those bounded auxiliary calls
are not represented as part of a provider-wide dollar ceiling. Run schema v5 records
this as `cost_accounting.scope=generation-token-usage-only` and lists the endpoint,
undocumented billing status, exclusion flag, and maximum request count structurally.

The executor returns only a redacted structured outcome plus verified-empty persistence
and the exact recorded cache mode. It cannot report tokens or cost. The runner wraps the
entire executor in the remaining run deadline, atomically calls `RunBudget.finalize()`,
and accepts only a terminal snapshot with no model, QuickJS, or task reservation in
flight. Every model call must have complete normalized provider usage metadata. The
fixture exercises the Anthropic shape; the local adapter requires the exact OpenAI
Responses model identity and pricing buckets. The
canonical token and cost fields come only from the finalized uncached-input, output,
cache-read-input, and cache-write-input buckets; their exact sum must equal the ledger
charge. Cost applies the four recorded integer micro-US-dollar rates and rounds up once
per task.

The runner rejects usage in a disabled arm and derives task-level capability evidence
from the same ledger. Server activation is task-scoped: an enabled arm exposes QuickJS or
`task` only when the canonical task requires it and every required peer is present. A
fully available task must execute each required capability; a task missing a required
peer receives no tool surface and must stop with the exact `capability_unavailable`
result. Every required subagent task must delegate exactly once to `evidence-checker`;
the actual subtype sequence is recorded per task in `run.json`, and another specialist,
no delegation, or a second delegation fails closed. Unexpected capability use and false
availability claims are rejected. Each task also records the ordered root `AIMessage`
call and matching `ToolMessage` completion boundaries, including their root-message
indexes and call IDs. A required QuickJS task must contain exactly one completed `eval`
pair; a task that does not require QuickJS must contain none. The combined cell must be
exactly `eval call → eval completion → task call → task completion`, with the `task`
request in a later model turn. This proves that the QuickJS completion was available
before delegation; it does not claim that a trace can prove semantic use of the returned
value. The root trace call count must equal `quickjs_calls + task_calls`. Run schema v5
also records the non-negative derived child count
`delegated_tool_calls = tool_calls - quickjs_calls - task_calls`; it must be zero when
there was no `task`, while every delegated evidence-checker must spend at least one call
on its exact compiled child tool surface. The deterministic proof uses the assigned-skill
call for that boundary. Any external root call still fails closed.
Missing,
duplicate, reordered, nonterminal, unsettled, cache-drifted, persistence-contaminated,
provider-incomplete, or otherwise malformed data aborts the sweep. Latency uses monotonic
elapsed nanoseconds rounded to the nearest millisecond.

Artifacts are written atomically and immutably beneath a distinct namespace:

```text
results/capabilities/<dataset-id>/<run-id>/
├── capability-report.md
├── manifest.json
└── run.json
```

The run ID binds the task-set checksum and content tree, all four arm definitions,
execution/executor/model/seed/cache/retry/pricing identity, `RunBudgetPolicy`, agent/eval
source trees, root lock, and runtime platform. The canonical JSON and Markdown projection
are byte-stable for the same complete observations. A same-ID rerun with different bytes
is rejected, making nondeterministic provider output explicit instead of silently
replacing a result.

PR CI does not call a paid model. The deterministic path remains provider-free, and
`tests/test_capability_runner.py` substitutes only a
deterministic provider-free chat model with exact normalized Anthropic metadata, then
executes the production `create_graph` topology in all four arms. It runs native QuickJS
and native Deep Agents `task`, verifies fresh empty in-memory persistence, proves that the
QuickJS-only root has no task surface, proves the combined task executes both
capabilities in the required completed-root-call chronology, and proves the child has no
QuickJS, task, filesystem, environment, or network surface.

The local-only adapter fixes `gpt-5.6-luna`, OpenAI Responses, no reasoning, no provider
storage, the reviewed SDK versions, and the current uncached/cache-read/cache-write/output
rates of `$0.20/$0.02/$0.25/$1.20` per million tokens. It derives rather than accepts the
provider identity, versioned rates, cache mode, fresh execution UUID, and measured content
tree. Its exact input-token counter replays the final LangChain request through a
no-network transport and calls the provider count endpoint before each reserved
generation. Both generation and count clients pin `https://api.openai.com/v1`, require
empty organization/project/custom-header routing, and validate the SDK's actual sync and
async root clients before a provider request. Provider response metadata then settles the
same shared ledger.

Failed adapter attempts emit only a fixed phase, an allowlisted reason code, finalized
model/tool/QuickJS/task counters, and root events mapped to `eval`, `task`, or `other`.
Provider bodies, prompt/message content, tool arguments, call IDs, credentials, and raw
exception chains are discarded at that boundary. QuickJS cleanup cannot replace a
primary graph failure or cancellation. Failure finalization permits unavailable provider
usage buckets solely for this non-artifact diagnostic; successful observations and every
stored run still require complete exact provider-native usage.

The paid path is intentionally manual and local. It requires an existing
`OPENAI_API_KEY`, an explicit generation-token micro-dollar ceiling, acknowledgement
that Luna is paid, and a separate acknowledgement that official input-token-count
request pricing is undocumented. The request count remains bounded by the model-call
policy, but only a provider-side account limit can cap any undocumented charge. There is
no paid CI workflow or public-enablement side effect:

Before running, unset `OPENAI_ADMIN_KEY`, `OPENAI_API_BASE`, `OPENAI_BASE_URL`,
`OPENAI_CUSTOM_HEADERS`, `OPENAI_ORGANIZATION`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`, and
`OPENAI_PROXY`. Presence is rejected even when the value is empty, before the API key is
read or an SDK client is constructed; the run never inherits alternate host, credential,
organization, project, header, or OpenAI-specific proxy routing.

```bash
uv run --env-file agent/.env --frozen --package syshin0116-dev-eval \
  blogeval capability-openai \
  --dataset eval/querysets/capability-tasks-v1.json \
  --index-root agent/.index \
  --workspace-root . \
  --output-root /tmp/syshin-capability-results \
  --max-generation-token-cost-usd-micros 1000000 \
  --random-seed 20260801 \
  --accept-paid-openai-run \
  --accept-unpriced-input-token-counting
```

Luna has no API Free tier. The command rejects either omitted acknowledgement, an incomplete
or content-tree-mismatched index, dependency-version drift, content drift, a worst-case
generation-token cost above the supplied cap, incomplete provider usage, or a partial
four-arm result. Its artifacts remain
`provider-backed-local-unattested`; a signed publication and owner-reviewed task labels
are still required before any public quality or launch conclusion.

## Development gates

```bash
uv lock --check
uv sync --frozen --package syshin0116-dev-eval --all-groups
uv run --frozen --package syshin0116-dev-eval ruff check eval/src eval/tests
uv run --frozen --package syshin0116-dev-eval \
  ruff format --check eval/src eval/tests
uv run --frozen --package syshin0116-dev-eval pytest eval/tests
```
