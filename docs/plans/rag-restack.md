---
title: "Plan: rebuild the agent on Aegra, get basic chat working, then evaluate"
description: >
  Rebuild the agent natively on Aegra + deepagents + assistant-ui, ship a working
  private chat end to end, then fork the evaluation harness off the same retriever
  interface, then harden and go public.
when_to_read: >
  Before picking up any restack work, before dispatching an agent onto a phase,
  or when deciding what comes next.
tags: [plan, aegra, assistant-ui, deepagents, retrieval, evaluation, deploy]
status: draft
updated: "2026-07-26"
owners: ["@syshin0116"]
refs:
  - ../adr/0008-chatbot-is-a-rag-evaluation-testbed.md
  - ../reference/retrieval-methods.md
  - ../research/aegra-native-stack.md
  - ../research/public-exposure.md
  - ../adr/0003-agent-code-changes-via-pr.md
  - ../adr/0004-adopt-aegra.md
  - ../adr/0005-adopt-assistant-ui.md
  - ../adr/0006-public-anonymous-chat-access.md
template: plan
---

# Plan: rebuild the agent on Aegra, get basic chat working, then evaluate

> **Status: draft, not started.** Phases are written to be dispatched to separate agents.
> Read [How to dispatch](#how-to-dispatch) first.

> **Read [ADR-0008](../adr/0008-chatbot-is-a-rag-evaluation-testbed.md) before touching
> anything here.** The purpose is comparing retrieval methods; the chat is an inspection
> surface. Simplification arguments that reason from corpus size are backwards.

## What changed since the first draft

This plan has been rewritten twice, both times because a premise turned out to be wrong.
Recording that, because the corrections are the useful part:

1. The first version was "deploy the existing stack, then decide about Aegra and
   assistant-ui." Superseded when the owner confirmed **the existing agent data is
   disposable**, which removed the checkpoint-migration blocker.
2. The second version kept the agent layer at 96% unchanged. Superseded when the owner
   scoped it in as a rebuild too, and then again when the actual goal turned out to be
   **method evaluation, not blog search**.

The sequencing rule now is the owner's: **get basic chat working first.** Not because
chat is the product, but because it is the only thing that proves the whole infrastructure
chain actually connects.

## Sequence

```
P0  Aegra spike (local)              gates everything
P1  Rebuild the agent layer          retriever Protocol + correct BM25 + build-time mirror
P2  Deploy a restricted preview      fail-closed owner auth; not public yet
P3  assistant-ui, preview then cut over
    ─────────────────────────────────  ✅ basic chat works end to end
P4  Evaluation harness (eval/)       forks off P1's Protocol; can run in parallel from here
P4.5 QuickJS + subagent capability lab independent axes first, then bounded combination
P5  Public hardening                 anonymous identity, guard, GC, budget caps
P6  Go public                        PUBLICATION GATE
```

**The old P1 "close three content leaks" is deleted, not rescheduled.** All three fixes
patched files that P1 now deletes. Doing both would be the same work twice.

## Versions

Exact `==` pins. No `^` on Aegra or assistant-ui.

| Package | Pin | Note |
|---|---|---|
| `aegra-api`, `aegra-cli` | `==0.9.24` | Latest release verified 2026-07-26; includes feature-flagged Agent Protocol v2 streaming via native v3. **Never `pip install aegra`** |
| `langgraph` | `==1.2.9` | Aegra's own lock resolves 1.2.6. Rollback pin documented |
| `langgraph-sdk` | `==0.4.2` | `Auth`, `AuthContext`, `ServerRuntime` |
| `langgraph-checkpoint-postgres` | `==3.1.0` | Above Aegra's locked 3.0.4, so untested by Aegra CI. Rollback: `==3.0.4` |
| `deepagents` | `==0.6.12` | `permissions=` is new in 0.6.0 |
| `langchain` | `==1.3.14` | |
| `langchain-quickjs` | `==0.3.4` | async execution only; owner/eval tier first |
| `pyjwt` | `==2.13.0` | replaces 130 LOC of hand-rolled base64url + HMAC |
| `@assistant-ui/react` | `0.14.27` | |
| `@assistant-ui/react-langgraph` | `0.14.12` | **not** `react-langchain` |
| `@langchain/langgraph-sdk` | `1.9.28` | |

**Drop:** `chromadb` (zero call sites), `fastapi`, `uvicorn`, `sse-starlette`, the `arq`
extra, `@langchain/react`, `@langchain/langgraph`.

## Target AI project tree

This is the target ownership map, not an exhaustive list of every test or retriever.
Phase PRs may add files beneath these boundaries, but moving a boundary requires updating
this tree first. Generated directories are shown for clarity and are never committed.

```text
aegra.json                         # graph/auth/http registration
Dockerfile                         # one deployable agent image
pyproject.toml                     # uv workspace: agent + eval
uv.lock                            # one lock for the workspace
protocol/
├── agent-protocol.lock.json       # upstream commit/schema hash + Aegra dialect/support matrix
└── fixtures/                      # committed AP v2 event/replay/HITL streams
scripts/
├── build_index.py                 # content/ -> published-only generated mirror
└── smoke.py                       # local and deployed compatibility gate
agent/
├── pyproject.toml
├── skills/
│   └── blog-retrieval/SKILL.md    # one mounted workflow skill
├── .index/                        # GENERATED, gitignored, image input only
│   ├── posts/
│   ├── catalog.json
│   ├── bm25/
│   ├── wikilinks.json
│   └── kiwi-user-dictionary.txt
├── src/agent/
│   ├── graph.py                   # create_deep_agent entrypoint
│   ├── auth.py                    # Aegra identity/auth hooks
│   ├── middleware.py              # identity, tier, budget/run policy
│   ├── capabilities/
│   │   ├── quickjs.py             # bounded async CodeInterpreterMiddleware config
│   │   ├── subagents.py           # named agents + dynamic dispatch policy
│   │   └── budget.py              # shared model/tool/task reservations
│   ├── prompts.py
│   ├── tools.py                   # thin tool adapters over Retriever
│   └── retrieval/
│       ├── protocol.py            # stdlib-only shared contract
│       ├── registry.py            # servable methods only
│       ├── corpus.py              # reads only agent/.index
│       ├── bm25.py                # corrected baseline
│       ├── graph.py
│       ├── fusion.py
│       └── fingerprint.py         # method/config identity
└── tests/
    ├── contract/                  # every registered Retriever
    ├── security/                  # publication and identity boundaries
    └── integration/               # Aegra graph/stream/restart smoke
eval/
├── pyproject.toml                 # uv workspace member; depends on agent
├── src/blogeval/
│   ├── registry.py                # servable registry + lab extensions
│   ├── datasets.py
│   ├── metrics.py
│   ├── runner.py
│   ├── report.py
│   ├── capability_runner.py       # QuickJS/subagent factorial experiments
│   └── lab/                       # torch/JVM/large-checkpoint methods
├── querysets/
│   ├── known-item-alias-v1.json
│   ├── topic-smoke-v1.json
│   └── capability-tasks-v1.json
├── tests/
└── results/                       # GENERATED/local system of record, gitignored
```

Explicitly deleted rather than carried forward: `agent/src/api/`, top-level `db.py`,
`schemas.py`, and `worker.py`; ARQ/run-queue modules; legacy migration code; six one-tool
skills; and superseded `agent/src/agent/lib/` implementations after their replacement
tests pass. `content/` remains an immutable build input and is never moved under `agent/`.

## CI/CD and release contract

The repository already has application and wiki CI, but no agent deployment workflow.
The restack adds the following workflows. Workflow names are required checks and therefore
part of the contract; renaming one requires updating branch protection in the same PR.

```text
.github/workflows/
├── ci.yml                    # web + agent + eval + index/security tests
├── protocol-compat.yml       # AP v2 schema/codegen/fixture drift
├── preview-agent.yml         # opt-in PR Cloud Run preview
├── deploy-agent.yml          # main -> immutable image -> Cloud Run
├── smoke-production.yml      # post-deploy protocol/security/browser gate
└── dependency-audit.yml      # scheduled latest-release/security report
```

### Pull requests

- `ci/web`: frozen Bun install, generated-content prebuild, unit tests, lint, typecheck,
  production build, and Playwright chat tests against committed AP v2 fixtures.
- `ci/agent`: root `uv sync --frozen`, Ruff, typecheck, unit/contract/security tests,
  published-only mirror build, Docker build, and container smoke against ephemeral
  Postgres.
- `ci/eval`: dataset-schema validation, deterministic metric fixtures, registry/fingerprint
  contract, and a tiny no-provider-cost sweep. Full paid sweeps are never a PR requirement.
- `protocol-compat`: fetch the Agent Protocol CDDL/OpenAPI revision recorded in
  `protocol/agent-protocol.lock.json`, regenerate bindings in a temporary directory, and
  fail on a diff. Replay committed content-block, tool, nested namespace, replay, error,
  and HITL fixtures through both Python and TypeScript consumers.
- The lock records both upstream Agent Protocol and the Aegra tag. Aegra 0.9.24 implements
  the current v2 event model as a draft dialect at
  `POST /threads/{thread_id}/stream/events`, while upstream documents
  `POST /threads/{thread_id}/stream`. This path difference is explicit compatibility data,
  not hidden behind a misleading “fully conformant” label. Record wire differences too:
  Aegra has no v2 WebSocket route, implements only `run.start` and `input.respond`
  commands, and its HITL input event uses `value` where the pinned upstream binding expects
  `payload`. Dialect translation happens in one tested transport boundary.
- Path filters include root `pyproject.toml`, `uv.lock`, `aegra.json`, `Dockerfile`,
  `protocol/**`, `scripts/**`, `content/**`, `agent/**`, `eval/**`, and `web/**`. A
  `content/**` change must rebuild both the web artifacts and the agent mirror.
- Required checks: `ci/web`, `ci/agent`, `ci/eval`, `protocol-compat`, and wiki verification
  when its paths match. Never merge on red CI; never let a path-filtered workflow report no
  status for a required check.

### Preview and production

- Vercel continues to create the web preview. `preview-agent.yml` is opt-in through an
  explicit trusted label/environment approval because every preview can spend model tokens.
  It builds the exact PR SHA, deploys a separate Cloud Run preview service with owner-only
  auth and `max-instances=1`, posts the URL to the PR, and expires the service automatically.
- GitHub authenticates to GCP through Workload Identity Federation; no long-lived service
  account JSON key is stored. Build once, push an immutable Artifact Registry image tagged
  with the git SHA, record its digest/SBOM, and deploy that digest—never rebuild between
  preview, smoke, and promotion.
- `deploy-agent.yml` runs only after required main-branch CI succeeds. Before P6 it deploys
  the owner-only service. After P6, the same workflow deploys the public revision but does
  not shift traffic until `smoke-production` passes.
- `smoke-production` verifies `/live` and `/ready`, owner and anonymous auth boundaries,
  AP v2 two-turn/replay/HITL fixtures, publication exclusions, concurrent-submit rejection,
  QuickJS/subagent tier limits, and one Playwright Korean-IME conversation.
- Cloud Run keeps the previous healthy revision at zero traffic. Rollback is traffic
  reassignment to that known digest, not a rebuild. Database migrations must be backward
  compatible with one previous application revision; destructive migrations require a
  separate ADR and backup/restore rehearsal.
- Use GitHub environments `preview` and `production`. Production holds secrets and requires
  owner approval for the first public release, auth/schema changes, or a migration; routine
  content-only releases may promote automatically after all gates once that policy is
  explicitly enabled.

### Staying current without surprise upgrades

- `dependency-audit.yml` runs weekly and on manual dispatch. It compares pinned Aegra,
  Agent Protocol schema revision, assistant-ui, LangGraph SDK, deepagents, and QuickJS
  against their latest upstream releases and reports compatibility/security changes.
- “Use latest” means **latest version proven by this repository's compatibility suite**,
  not an unpinned install. A version/protocol bump is its own PR: update pins and the
  protocol lock, regenerate fixtures/bindings, run P0 plus UI replay tests, then deploy by
  digest. Dependabot may open the PR but never auto-merge pre-1.0 runtime changes.

---

## P0 - Aegra spike, local `~1 day` `GATES EVERYTHING`

Turn "deepagents under Aegra is unverified" into a step. Aegra's repo has zero mentions of
deepagents.

- `aegra.json` at the repo root: `dependencies: ["./agent/src"]`,
  `graphs: {"agent": "./agent/src/agent/graph.py:graph"}`. No `auth` or `http` block yet.
- Set `FF_V2_EVENT_STREAMING=true`; Aegra 0.9.24 returns 503 from its AP v2 event route
  without this feature flag. Probe capabilities before starting the conversation.
- Install `aegra-api==0.9.24 aegra-cli==0.9.24`; confirm no resolver conflict.
- Minimal `graph.py` rewrite: drop `checkpointer=`/`store=` and `_lazy_graph`. Aegra does
  `graph.copy(update={checkpointer, store})` per request, so a compiled graph registers
  as-is. **The `backend=` factory form is deprecated** (0.5.0, removal 0.7.0) - pass a
  `BackendProtocol` instance.
- The instance migration includes the current `StoreBackend(runtime, ...)` construction and
  namespace callback: both the runtime constructor and `context.runtime.config` access are
  deprecated for removal in deepagents 0.7. Resolve the namespace from the authoritative
  Aegra identity/config without any deprecated backend warnings; changing only
  `_build_backend` is incomplete.
- `aegra serve` against local Postgres; confirm the Alembic tables appear.
- `scripts/smoke.py` on `langgraph_sdk.get_client`. **This becomes the permanent gate for
  every version bump.**
- Register a deterministic fixture graph alongside the real graph for CI only. It always
  emits one tool lifecycle, one nested namespace, and one interrupt, so protocol/HITL tests
  do not depend on a model choosing a particular action. The optional live Korean smoke is
  a separate check that may spend provider tokens.

**Accept:** a **two-turn** Korean conversation with at least one tool call completes over
Aegra 0.9.24's AP v2 `POST /threads/{thread_id}/stream/events`, using content-block
deltas, tool and run lifecycle events, and nested namespaces where applicable. Within one
server lifetime, persist the last event/replay cursor, disconnect, reconnect, and prove that
no visible content is duplicated or lost. Separately restart the process and prove
checkpoint/thread state restores; do not claim broker event replay survives a process
restart unless a test demonstrates it. Verify store/memory namespace isolation and that a
client-supplied `configurable.user_id` cannot change the trusted identity used by the
backend: Aegra preserves that forged field but separately injects
`langgraph_auth_user`/`server_info.user.identity`, which must be authoritative. With P0's
no-auth local server, prove resistance to the forged field but defer genuine cross-user
isolation to P1's owner auth. Exercise `run.start` and `input.respond` through
`/threads/{thread_id}/commands`.

> The second turn is not decoration - it is the exact regression from Aegra issues #224
> (fixed 0.7.5) and #352 (fixed 0.9.14), both deepagents multi-turn bugs. If it fails,
> **stop and report**.

---

## P1 - Rebuild the agent layer `~3 days`

From scratch, native to deepagents 0.6.12. Absorbs the old leak-fix phase.

### P1.1 The retriever Protocol - do this first
- `agent/src/agent/retrieval/protocol.py`, **stdlib only, zero dependencies**. `Hit`,
  `Retrieval`, `Corpus`, `Retriever`, `Stage`, `Pipeline`.
- **It lives in `agent/`, not in `eval/`.** That is what makes it physically impossible for
  the chat and the harness to drift onto different interfaces - the failure ADR-0008
  follow-up 4 exists to prevent.
- `DocId` is **always** the content-relative posix path. `Retrieval.doc_ids()` collapses
  chunk hits to a deduped document ranking, which is the single place chunk-vs-document
  asymmetry is resolved so one qrel scores every method.
- `rank` is authoritative; `score` stays **raw and method-native**. Never normalise inside
  a retriever.
- `Stage` has the same shape as `Retriever`, so reranking, fusion, and graph expansion
  compose without special cases.
- `agent/src/agent/retrieval/registry.py`: `name -> factory` for **servable methods**.
  The chat reads this registry. The eval registry imports it, then adds heavyweight lab
  methods from `eval/blogeval/lab/`. The two registries may enumerate different sets, but
  a shared method ID must resolve to the same implementation/config fingerprint. CI checks
  that invariant.

### P1.2 The build-time published-only mirror
- `scripts/build_index.py` copies **only published posts** into `agent/.index/posts/`, and
  that mirror becomes the container's only content root.
- This is the draft boundary, and it is the whole reason it cannot be bypassed. Today the
  boundary is a runtime predicate that three code paths must each remember; two forget and
  the third is wrong. **In the rebuild a draft is not filtered, it is absent from the
  image.**
- Fail closed: `draft` and `private` must be booleans when present; unexpected types are a
  **build failure**. A document is published only when neither flag is `true`. YAML parse
  errors and non-mapping frontmatter are build failures, not silent skips. Documents with
  no frontmatter follow one explicit corpus policy, covered by fixtures, rather than being
  published accidentally. Reject symlinks that resolve outside `content/`.
- Same step emits `catalog.json`, the fitted BM25 index, the resolved wikilink graph, and
  the Kiwi user dictionary. That moves **6.11s of tokenization** out of the first visitor's
  request.
- CI test: build from fixtures containing public, draft, private, malformed, missing-
  frontmatter, and out-of-tree symlink cases; assert only the explicitly published fixture
  reaches `agent/.index/posts/`. Then walk the real mirror and fail if any excluded source
  appears. This makes the boundary auditable rather than aspirational.

> Note the corpus currently has **zero** `draft: true` posts, so all of this guards nothing
> today. That is exactly why the bugs survived review, and exactly why the boundary should
> be structural before it matters.

### P1.3 The corrected BM25 baseline `BLOCKER for everything in P4`
A broken baseline invalidates every comparison drawn against it. Three independent fixes,
all needed - see [the registry](../reference/retrieval-methods.md#the-korean-tokenizer-problem):

1. **User dictionary** built from the corpus. `add_user_word("도커", "NNP")` restores
   `['도커']`, verified. Frontmatter `tags` are the best source - the author has already
   hand-labelled the domain vocabulary.
2. **Drop `VV` and `VA` from the keep-list.** They are what survives when an unknown noun
   is mis-analysed, which is what turns a tokenization failure into a confident wrong
   answer instead of an empty result.
3. **Index the surface form alongside morphemes**, so a term the dictionary has not caught
   up with still matches exactly.

Also remove the `score / max(scores)` normalisation: it forces the top hit to exactly 1.000
for **any** query including nonsense.

**Accept:** executable tests, not inspection. `도커` recall@13 goes 0/13 → 13/13; macro
recall@10 goes 0.323 → 0.605; a nonsense query scores measurably below a real one.

### P1.4 Native composition
- **No content backend route.** `ls`/`glob`/`grep`/`read_file` are in the compiled ToolNode
  **unconditionally**, whatever you pass as `tools=` - they are only dangerous if a backend
  route points them at content. Deleting the `/blog/` route removes the leak class.
- **Mount `/skills/`** on a read-only FilesystemBackend and pass `skills=["/skills/"]`.
  Skills have never loaded: an absolute host path goes into `SkillsMiddleware`, which
  resolves *through the backend*, misses every route, and falls through to `StateBackend`.
  Verified: mounting the route loads all six SKILL.md with zero warnings.
- **Collapse six SKILL.md files into one workflow skill.** Six files each restating one
  tool's docstring is duplication under the upstream model - skills are for task
  instructions too large for the prompt, discovered by progressive disclosure.
- `FilesystemPermission` (new in 0.6.0) replaces the 45-LOC `ReadOnlyFilesystemBackend`
  subclass. **It cannot express "frontmatter lacks draft"** - it is pure path globbing.
  That job belongs to P1.2, not here.
- **Read the trusted identity from `configurable["langgraph_auth_user"]`, never
  `configurable["user_id"]`.** Aegra sets `user_id` with `setdefault`, so a client
  overrides it and reaches another user's memory namespace. Better still,
  `runtime.server_info.user.identity` works inside middleware with no escape hatch. The
  static StoreBackend namespace callable reads this trusted runtime identity directly.
- Add `agent/src/agent/auth.py` here with the existing owner token flow and a mandatory
  `AGENT_AUTH_SECRET` length check. P1 authentication is fail-closed and owner-only; P5
  extends it with the anonymous tier. Never deploy an Aegra graph with no auth file.
- Delete: `read_only_backend.py`, `result_formatter.py`, `ripgrep_search.py` (shells out
  for a 2.4 MB corpus while its own in-process fallback is correct), and 32 LOC of dead
  code in `prompts.py`.

**Accept:** a test fails if a spoofed `configurable.user_id` changes the resolved memory
namespace; skills load with zero warnings; the graph compiles with a stable node set.
The new retrieval, graph, and auth modules are explicitly listed as retained files for the
later server deletion, so a LOC-based cleanup cannot remove them accidentally.

---

## P2 - Deploy a restricted Cloud Run preview `~1.5 days`

First deployment, but **not yet a public chatbot**. P1's fail-closed owner auth is the
application boundary so the browser preview can reach Cloud Run without creating a second
IAM-token exchange. IAM and ingress restriction may be added where compatible, but an
unlisted URL is never an access-control boundary. Aegra without the registered auth file
is fail-open under one shared `anonymous` identity, so deployment must refuse to proceed
if auth registration or its secret is missing.

- Dockerfile is greenfield - Aegra's own copies `libs/aegra-api/...` paths that do not
  exist here. `python:3.12-slim-bookworm`.
- **Two Neon free projects in a US region** ([ADR-0007](../adr/0007-postgres-on-neon-split-projects.md)):
  one for the agent, one for Auth.js. Zero code changes - both sides read `DATABASE_URL`.
  **Neon project regions are fixed at creation**, so this is only available now.
- Use the **direct** endpoint, not `-pooler`: `checkpointer.setup()` issues
  `CREATE INDEX CONCURRENTLY`, which Neon documents as direct-connection-only.
- Deploy: `--no-cpu-throttling --timeout 3600 --max-instances 1 --concurrency 20`, a
  **dedicated minimal service account**, Postgres pool knobs turned down (Aegra opens up to
  ~50 connections by default).
- Verify the owner token succeeds and an anonymous or forged token receives 401/403 on the
  exact streaming route used by the frontend, not only on a metadata route.
- `--max-instances 1` is load-bearing: it is what makes P5's in-process guard correct.
- Set the Anthropic organization spend cap. Grep startup logs for Aegra's
  data-not-isolated warning.

**Accept:** `/health` 200 and `scripts/smoke.py` pass with owner preview credentials; the
same streaming requests without credentials or with a forged subject receive 401/403;
cold-start-to-first-token is measured and recorded. Do not continue if graph routes are
anonymously reachable.

---

## P3 - assistant-ui `~3 days`

Preview URL first; `chat-section.tsx` stays live until cutover.

### P3.1 UI contract

The chatbot remains part of the home-page experience, but gets a full-height focused mode
instead of trying to fit every control into the hero. Desktop uses a three-zone shell;
mobile uses one conversation surface with sheets for threads and run detail.

```text
web/components/chat/
├── chat-entry.tsx                 # home-page compact entry + open focused mode
├── chat-shell.tsx                 # desktop/mobile responsive layout
├── thread-list.tsx                # create, rename, delete, retention state
├── conversation.tsx              # assistant-ui Thread
├── composer.tsx                  # Korean IME, stop, retry, attachments policy
├── capability-bar.tsx            # active retrieval/mode; no fake system messages
├── run-timeline.tsx              # retrieval/tool/QuickJS/subagent lifecycle
├── source-card.tsx               # title, excerpt, path, open post
├── quickjs-card.tsx              # code, bounded output, timeout/truncation
├── subagent-card.tsx             # specialist, status, evidence, cost/latency
├── interrupt-card.tsx            # approve/reject/edit
├── error-state.tsx               # 401/403/409/429/5xx/reconnect mapping
└── runtime/
    ├── agent-protocol-v2.ts       # typed transport + reducer
    ├── aegra-rest.ts              # cancel/state/history compatibility bridge
    ├── thread-adapter.ts
    ├── auth.ts
    └── protocol-types.ts          # generated; schema lock identifies source
```

- Default visitor view: short explanation that this is a RAG evaluation testbed, two or
  three Korean example prompts, privacy/AI disclaimer, and a clear “new conversation”
  action. No sign-in prompt is shown for anonymous testing.
- Message answers render citations inline and a source list below. Retrieval method and
  corpus revision are visible in a compact run-details disclosure, not mixed into prose.
- Tool activity collapses into a timeline by default. Retrieval shows query/method/hit
  count; QuickJS shows code and bounded output; each subagent shows its name, purpose,
  status, evidence count, latency, and budget usage. Internal chain-of-thought is never
  displayed.
- Capability controls reflect server-authorized tier. Anonymous users cannot reveal hidden
  owner controls. Changing retrieval/capability settings creates explicit run config and
  never injects a fake system message into checkpoint history.
- Required states: empty, token minting, ready, streaming, tool running, subagents in
  parallel, interrupted, reconnecting/replaying, stopped, rate-limited, busy-thread,
  expired anonymous thread, server error, and offline. Every state has Korean copy and a
  single safe next action.
- Desktop target: thread rail 280 px, flexible conversation, optional 320 px run-detail
  drawer. Under 1024 px the detail drawer becomes a sheet; under 768 px the thread rail is
  also a sheet. Composer remains visible above the mobile keyboard and safe-area inset.
- Accessibility gate: full keyboard operation, visible focus, semantic live regions without
  announcing every token, reduced-motion support, contrast compliance, labelled icon
  buttons, and focus restoration after sheets/dialogs/HITL.

### P3.2 Runtime implementation

- `npx assistant-ui@latest init` inside `web/`, then `npx shadcn@latest add
  @assistant-ui/thread @assistant-ui/thread-list`.
- Keep assistant-ui as the component/runtime layer, but do **not** make
  `unstable_createLangGraphStream` the production transport: it calls legacy
  `client.runs.stream`. Implement `AgentProtocolV2Transport` over the generated Agent
  Streaming Protocol TypeScript bindings and Aegra's
  `POST /threads/{thread_id}/stream/events`, with the HTTP commands sidecar for
  `run.start` and `input.respond`; run cancellation continues through the run-cancel API.
  Translate the documented Aegra HITL `value` field to upstream `payload` at this boundary.
  Keep the upstream `/stream` path in the compatibility matrix so a future conformant
  Aegra release is a transport switch, not a rediscovery. The legacy adapter is permitted
  only as a temporary comparison fixture during P3.
- Isolate operations missing from Aegra's v2 command dispatcher in `aegra-rest.ts`:
  cancellation uses `POST /threads/{thread_id}/runs/{run_id}/cancel`; checkpoint
  state/fork and Edit/Regenerate use the `/state` and `/state/checkpoint` routes; branch
  history/load uses `/history`. These are an explicit Aegra compatibility bridge, not AP v2
  commands. Fixture-test their response mapping and delete each fallback when Aegra adds
  the corresponding command.
- The transport maps content-block deltas, tool lifecycle, run lifecycle, checkpoints,
  tasks, nested-agent namespaces, replay cursors, and structured errors into assistant-ui
  runtime state. Unknown event kinds are logged and ignored without corrupting known state;
  schema drift fails CI before deploy.
- In `load()`, read `state.interrupts` **first** - Aegra returns interrupts as a top-level
  field, so the quickstart's `state.tasks[0].interrupts` is the wrong read here.
- **Pass `getCheckpointId`.** Omitting it silently hides Edit and Regenerate, which reads
  as a missing feature rather than missing config.
- Async `onRequest` token hook with a 60s margin. Capturing the token once at mount 401s
  mid-conversation.
- `remarkPlugins={[remarkGfm, remarkBreaks]}` with components memoised at module scope.
  **remark-breaks is load-bearing for Korean.**
- **Korean IME: verify with a Playwright test, do not assume.** Highest-risk regression.
- Then cut over and delete the named legacy server modules and tests asserting those
  internals, plus the vendored prompt-kit and `chat-section.tsx`. Do not use an LOC target
  as deletion scope. Explicitly retain `agent/src/agent/retrieval/**`, the rebuilt graph,
  auth/identity code, and their tests.

**Accept:** a full multi-turn Korean conversation against deployed Aegra over AP v2;
reload and a forced mid-stream reconnect restore the thread without duplicate text; tool,
QuickJS, and nested-subagent events render from committed protocol fixtures; HITL
resume uses `input.respond`, cancellation uses the run-cancel endpoint, and both are
fixture-tested; desktop and 390 px mobile visual snapshots cover every required state;
keyboard/a11y and Korean IME tests pass; no production import or network call uses the
legacy `/runs/stream` transport. Edit/Regenerate and history either pass against the
documented REST compatibility bridge or are visibly disabled; they never silently render
and fail.

### ✅ Basic chat works end to end here

---

## P4 - Evaluation harness `~4 days` `parallelisable from P1`

The actual deliverable. Forks off P1's Protocol and can proceed alongside P2 and P3.

- **`eval/` as a uv workspace member** next to `agent/`. The split line is **servable vs
  not**: a method that could run on Cloud Run lives in `agent/src/agent/retrieval/`; a
  method needing torch, a 2 GB checkpoint, or a JVM lives in `eval/blogeval/lab/`. Both
  satisfy the same Protocol. The eval registry extends the agent registry; the agent never
  imports `eval/`. Promoting a lab method means moving its implementation and registering
  the same method ID/fingerprint in the servable registry. This keeps the image slim
  without forking the interface.
- **Bootstrap the qrels from the 174 aliased `[[target|alias]]` links.** The alias is the
  author's own Korean surface form for a target document - free known-item ground truth in
  quantity, which no public corpus has. Use it before spending anything on LLM-generated
  queries.
- Keep two versioned query-set contracts rather than mixing their metrics:
  `known-item-alias-v1` maps each alias to one target and headlines Hit@k and MRR;
  `topic-smoke-v1` contains manually reviewed multi-document qrels and headlines recall@k.
  Each committed manifest records its generator/version, corpus tree SHA, qrels, and
  exclusions. The BM25 macro-recall regression uses `topic-smoke-v1`.
- Pin the corpus by **git tree sha of `content/`**. The harness never reads live `content/`.
- **Report `coverage` alongside recall@k, always.** The wikilink graph covers 123 of 336
  files, so a graph method that declines to answer on two-thirds of queries would otherwise
  look strong on the third where it fires.
- **Do not headline nDCG.** On four smoke queries nDCG@10 read 1.000 for every one while
  recall@10 ranged 0.23 to 0.77. It saturates when relevant-sets are large and ungraded.
- Local `results/<tree-sha>/` JSON is the **system of record**; LangSmith's free tier keeps
  traces 14 days and caps at ~3 full sweeps a month. Use it as a comparison UI, not storage.
- A committed pytest regression gate on macro recall@10 - the thing that would have caught
  the tokenizer bug.
- Emit a Markdown leaderboard and SVG plots, so results drop into a blog post without
  retyping. This matches the repo's existing `.mmd` → `.svg` diagram convention.

**Accept:** one full sweep over at least three methods produces a leaderboard, a
per-query table, and plots, reproducibly, from a pinned corpus and a versioned query-set
manifest. Reports label known-item and topic metrics separately.

**First experiment:** corrected BM25 vs one dense method vs their RRF fusion, over the
`known-item-alias-v1` query set, reporting Hit@k, MRR, and coverage. Small on purpose -
its job is to prove the harness, not to settle anything.

---

## P4.5 - QuickJS and dynamic-subagent capability lab `~3 days`

These are **agent-capability experiments, not retrieval methods**. Keep their results out
of the retrieval leaderboard so orchestration gains cannot be mistaken for retriever
quality. The framework split is deliberate: Deep Agents owns planning, skills, and dynamic
delegation; LangGraph/Aegra owns persistence and streaming; LangChain middleware supplies
the bounded code interpreter.

### P4.5.1 QuickJS, independently

- Add `CodeInterpreterMiddleware` using `langchain-quickjs==0.3.4`. All execution paths are
  async: never call sync `ctx.eval()` or sync `invoke()`.
- Start in eval and owner tiers only. No environment, filesystem, or network bridge; expose
  only the minimum pure-data helpers needed to inspect and transform retrieved results.
- Enforce wall-clock timeout, memory ceiling, source/input size, output bytes, and one
  interpreter session at a time per run. Truncation and timeout are structured tool results,
  not worker failures.
- Use it for tasks where code is materially useful: aggregate retrieval results, compare
  ranked lists, calculate metrics, transform tables, and validate citations. Do not invoke
  it for ordinary prose questions merely because it exists.

### P4.5.2 Dynamic subagents, independently

- Configure named, read-only specialists such as `retrieval-researcher`,
  `evidence-checker`, and `comparison-synthesizer`, plus the general-purpose subagent for
  genuinely novel decompositions. The main agent chooses at runtime whether and how to
  delegate through `task`.
- Subagents are stateless. Every dispatch must contain the complete question, allowed
  corpus/method scope, expected output schema, and stopping condition. Custom subagents
  receive their skills explicitly; they do not inherit the main agent's skills.
- Give specialists the smallest tool set they need. They return evidence and ranked IDs;
  only the main agent writes the final visitor-facing answer.
- Add an atomic `RunBudget` outside the model loop. Reserve before every model, tool, and
  `task` dispatch; cap task count, fan-out, depth, tokens, and elapsed time. A nested
  subagent shares the parent's remaining budget rather than receiving a fresh allowance.
- Start with max depth 1 and max two subagents per run. Parallel fan-out is permitted only
  after the reservation test proves two concurrent dispatches cannot exceed the cap.

### P4.5.3 Combine only after both standalone gates pass

- Do **not** expose `task()` as a QuickJS bridge initially. Dispatch from inside an eval
  bypasses the normal tool-calling/HITL path, and `max_ptc_calls` does not cover it.
- The first combined experiment may let the main agent delegate to specialists and let an
  individual specialist use QuickJS, but every reservation still goes through the shared
  `RunBudget`. No `Promise.all(task(...))` bridge.
- Run a 2×2 experiment over `capability-tasks-v1`: QuickJS off/on × subagents off/on. Report
  task success, citation correctness, latency, model/tool/task calls, tokens, and estimated
  cost. This determines where each capability helps instead of enabling both by default.

**Accept:** deterministic fixtures prove timeout/memory/output limits, stateless subagent
instructions, explicit skill assignment, shared nested budgets, max depth/fan-out, and
failure propagation. The 2×2 report is reproducible. Owner preview can exercise both
capabilities, while anonymous access remains off until P5 budgets and P6 abuse tests pass.

---

## P5 - Public hardening `~2 days` `GATE for P6`

Nothing here is optional. Full detail in
[`public-exposure.md`](../research/public-exposure.md).

- **The governing constraint:** authorization must not depend on `@auth.on.*` dispatch.
  Legacy streaming paths skip handlers, and AP v2 thread-stream/commands coverage must be
  proven by protocol fixtures rather than assumed. The SQL identity predicate plus outer
  ASGI guard is the boundary; handlers are defence in depth.
- Extend P1's `agent/src/agent/auth.py` with PyJWT anonymous claims; keep the import-time
  `len(AGENT_AUTH_SECRET) >= 32` assertion. Aegra with no auth file is **fail-open**, where
  this deployment must remain fail-closed.
- Anonymous identity: Turnstile-gated `anon:<uuid4>` minted in
  `web/app/api/agent-token/route.ts`. Aegra's `WHERE user_id = identity` predicate isolates
  them automatically. Return `is_authenticated: True` even for guests.
- `GuestRunGuard` as a **pure ASGI class**, not `BaseHTTPMiddleware` - the latter interferes
  with sse-starlette's disconnect detection, which is how `on_disconnect="cancel"` works.
  Per-identity token bucket (429) and per-`(identity, thread)` busy set (409).
- Tier differences go in **the model instance and backend routes**, never the middleware
  list - Aegra requires identical topology across access contexts. `wrap_model_call` adds
  no nodes, so anything expressible there is free to vary.
- `/admin/gc` plus Cloud Scheduler. **Deleting a thread does not delete its checkpoints** -
  sweep children before parents. Neon free has no `pg_cron`.
- Provider spend cap, per-run call limits, a dollar budget middleware (LangChain ships none).
- Public capability policy is evidence-based: retrieval is always available; QuickJS and
  dynamic subagents remain owner-only unless P4.5 shows a material quality gain and the
  deployed anonymous abuse tests prove the shared budget cannot be bypassed. If enabled
  for visitors, use lower limits than the owner tier and expose neither arbitrary subagent
  definitions nor a QuickJS-to-`task` bridge.

---

## P6 - Go public `~1 day` `PUBLICATION GATE`

- Remove the P2 preview restriction only after every P5 gate passes. The intended surface
  is a personal-blog testbed that **any visitor can try without signing in**: Turnstile
  establishes an isolated anonymous subject; it is an abuse gate, not an account wall.
- Verify the P1.2 mirror gate and the P5 guard on the **deployed** service, by actually
  exceeding the rate limit from a browser and firing two concurrent submits on one thread.
- Confirm GC measurably reduces checkpoint row count.
- Add a stale-run sweep: with `REDIS_BROKER_ENABLED=false` there is no lease reaper, so an
  instance killed mid-run leaves a thread busy forever.
- Decide LangSmith tracing **before**, not after - traces carry full prompts and full
  retrieved content.
- Watch Anthropic spend daily for week one.

---

## Risks

| | Risk | Mitigation |
|---|---|---|
| `HIGH` | **Same-thread run serialization is lost.** Aegra parses `multitask_strategy` and never reads it. This reverses the 2026-07-11 decision | P5's busy set. Honest limits: in-process, correct only at `--max-instances 1`, a check rather than a lock |
| `HIGH` | Auth dispatch differs across legacy and AP v2 streaming/commands paths | Protocol fixtures test every production endpoint; SQL identity predicate plus outer ASGI guard is the boundary. Pin `aegra-api >= 0.9.7` |
| `HIGH` | Client-supplied `configurable.user_id` wins over the server's | Read `langgraph_auth_user`. Fix in P1, before anything deploys |
| `HIGH` | Unbounded LLM spend from anonymous traffic. Aegra lists rate limiting as "Not yet planned" | Anthropic org spend cap is the only provider-enforced hard stop |
| `MED` | **Evaluating with a broken baseline.** Every number produced against it is invalid, not merely pessimistic | P1.3 is a blocker for P4, with executable acceptance tests |
| `MED` | Pre-1.0 churn. `aegra-api` shipped three releases in three weeks; four `unstable_` assistant-ui APIs on the happy path | Exact pins, committed lockfiles, `smoke.py` as the bump gate |
| `MED` | Eval cost creep - embedding N models × M queries × K retrievers plus judge calls | Cache embeddings by fingerprint; local results as system of record; `upload_results=False` while iterating |
| `MED` | The eval and the chat drift onto different retriever contracts | The Protocol and method fingerprint contract live in `agent/`; eval extends, rather than replaces, the servable registry |

## Decisions needed

1. **Cloud Run region.** Seoul (next to you) or a US region (next to Anthropic and, per
   ADR-0007, next to the relocated Neon)? The DB has no Korean client, so the US pairing
   looks right, but the SSE leg is browser-to-Cloud-Run direct.
2. **Guest model tier** once public: same model for everyone, or a cheaper one for guests?
   The largest cost lever, and it changes perceived quality for exactly the new audience.
3. **Guest thread persistence**: httpOnly cookie (durable, pseudonymous identifier on a
   site with no cookie banner) or stateless runs with history client-side?
4. **Version policy**: adopt `langgraph==1.2.9` / `checkpoint-postgres==3.1.0` (above what
   Aegra's CI tests), or match Aegra's lock at 1.2.6 / 3.0.4 for the first deploy?
5. **The skill-restriction chips** in the current UI: rebuild as run config, or drop? Today
   they inject a fake system message that lands in checkpointed history and replays.

## Open questions

- Does Aegra issue #468 reproduce? P0 answers it.
- How does the assistant-ui adapter surface 409 and 429 - a usable error state, or a
  generic stream failure?
- Cold-start-to-first-token for this image. Decides whether `min-instances=1` is worth it.
- PR #462 (multitask) and #385 (stream auth) - if either merges, part of P5 becomes dead
  weight. Watch rather than design around permanently.
- Which embedding model for the first dense arm. Pending the Korean model comparison.

## How to dispatch

- **Read [ADR-0008](../adr/0008-chatbot-is-a-rag-evaluation-testbed.md) and
  [ADR-0003](../adr/0003-agent-code-changes-via-pr.md) first.** Purpose, then process:
  feature branch, PR, never a direct commit to `main`, never merge on red CI.
- One phase per agent. Give it the phase section plus the linked research, not this file.
- **P0 gates everything. P1.3 gates P4. P1.2 and P5 gate P6.**
- P4.5 starts only after the P4 harness can record quality, latency, and cost. Its standalone
  QuickJS and subagent arms gate the combined arm.
- **P1.1 first within P1** - the Protocol is what everything else plugs into.
- P4 implementation may parallelise with P2 and P3 once P1 lands, but the first official
  sweep waits until the basic-chat path passes so the documented basic-chat-first gate
  remains meaningful. Nothing else parallelises cleanly, because `graph.py` is touched by
  P0, P1, and P5.
- Every phase ends with its acceptance check actually run, and the result stated plainly.
