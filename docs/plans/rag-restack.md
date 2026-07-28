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
updated: "2026-07-28"
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

> **Status: in progress.** The P0 native runtime mechanics, P1 owner-auth boundary,
> repository-side Cloud Run delivery automation, and P3 native assistant-ui
> implementation are implemented or in review. The external GCP/Neon bootstrap, first
> live deployment, provider-backed Korean chat, evaluation, and public-access phases
> remain. Phases are written to be dispatched to separate agents. Read
> [How to dispatch](#how-to-dispatch) first.

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
| `@assistant-ui/react` | `0.15.0` | |
| `@assistant-ui/react-langgraph` | `0.14.15` | native `useLangGraphRuntime`; **not** `react-langchain` |
| `@langchain/langgraph-sdk` | `1.9.28` | |

**Already dropped:** `chromadb` (zero call sites).

**Drop during the Aegra replacement:** direct `uvicorn`/`sse-starlette`, the `arq` extra,
`@langchain/react`, and `@langchain/langgraph`. Retain FastAPI only for Aegra's supported
`http.app` extension; it owns no Agent Protocol endpoint.

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
│   │   ├── dictionary-evidence.json
│   │   ├── fitted.sqlite3
│   │   └── manifest.json
│   ├── wikilinks.json
│   └── kiwi-user-dictionary.txt
├── src/agent/
│   ├── graph.py                   # create_deep_agent entrypoint
│   ├── auth.py                    # Aegra identity/auth hooks
│   ├── http.py                    # minimal native-route guard; no protocol facade
│   ├── preflight.py               # fail-closed Aegra registration checks
│   ├── migrate.py                 # one-shot Aegra + LangGraph DB setup
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
web/
└── components/assistant/
    ├── chat-section.tsx           # owner-preview entry and configuration boundary
    ├── chat-shell.tsx             # assistant-ui primitives + responsive shell
    ├── agent-runtime-provider.tsx # native useLangGraphRuntime composition
    └── runtime/
        ├── native-client.ts        # official AP v2 ThreadStream + MessageAssembler
        ├── thread-adapter.ts       # official SDK metadata/state/history adapter
        ├── inspection.ts           # bounded live-only retrieval projection
        ├── interrupt-projection.ts # bounded HITL UI schema
        ├── token-broker.ts         # identity-scoped token/cancellation lifecycle
        ├── ime.ts                  # native + ref Korean composition guard
        ├── focus-restoration.ts
        └── error-state.ts
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

The repository implements the following application, protocol, delivery, and dependency
workflows. The three stable required-check contexts are a separate branch contract below;
workflow files and reusable-workflow boundaries are also reviewed delivery inputs.

```text
.github/workflows/
├── ci.yml                    # web + agent + eval + index/security checks
├── protocol-compat.yml       # AP v2 schema/codegen/fixture drift
├── agent-image-build.yml     # reusable secretless isolated image builder
├── agent-release.yml         # reusable owner-gated release + pre-traffic smoke
├── preview-agent.yml         # same-repository PR caller -> fixed preview service
├── deploy-agent.yml          # reviewed main caller -> production or rollback
└── dependency-audit.yml      # scheduled latest-release/security report
```

### Pull requests

- `ci/web` currently runs a frozen Bun install, generated-content prebuild, unit tests,
  lint, typecheck, and the production build. P3 acceptance adds Playwright chat tests
  against committed AP v2 fixtures and the Korean-IME journey; those browser gates are
  not claimed by the current workflow.
- `ci/agent`: root `uv sync --frozen`, Ruff, unit/contract/security tests, and the
  published-only mirror build. Its PostgreSQL 17 service runs the host integration
  suite, then CI builds the real Linux amd64 image, runs that same image's
  `python -m agent.migrate` against the same database, boots the image, verifies `/live`
  and `/ready`, and requires an unauthenticated AP v2 command to return 401. This bounded
  container smoke never sends a provider or model request.
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
- Required checks are exactly `ci/check`, `protocol/compat`, and `wiki/verify`. Component
  work remains path-aware behind the stable aggregate contexts. Never merge on red CI or
  let a path filter suppress one of those three contexts.

### Preview and production

- Vercel continues to create the web preview. When the repository variable
  `AGENT_CLOUD_RUN_ENABLED=true`, `preview-agent.yml` handles `opened`, `reopened`, and
  `synchronize` events from same-repository, non-Dependabot pull requests. It builds the
  exact PR head in the isolated secretless builder, then waits for an owner approval in
  `Agent Preview` before releasing to the fixed shared `agent-preview` service. One global
  caller concurrency group serializes that shared target with `cancel-in-progress=false`.
  There is no trusted-label trigger, per-PR service, URL comment, or automatic expiry.
- GitHub authenticates to GCP through Workload Identity Federation; no long-lived service
  account JSON key is stored. Preview and production use isolated builders and Artifact
  Registry repositories. Each delivery attempt pushes a fresh git-SHA/run/attempt tag,
  records its digest/SBOM in that builder job, and deploys only that digest—never trust a
  pre-existing tag or rebuild between migration, smoke, and promotion.
- `deploy-agent.yml` releases only the current reviewed `main` candidate whose exact
  `ci/check`, `protocol/compat`, and `wiki/verify` check-runs succeeded. Before P6 it
  deploys the owner-only service; after P6 it uses the same digest-bound path for the
  reviewed public revision.
- The full authenticated AP v2 smoke is integrated into `agent-release.yml`: it targets
  the exact newly tagged revision while that revision still has 0% traffic, alongside
  `/live`, `/ready`, and the unauthenticated 401 boundary. Only a successful pre-traffic
  smoke permits promotion. Post-promotion checks are intentionally limited to health and
  the cheap unauthenticated AP v2 boundary; there is no separate
  `smoke-production.yml`.
- The PR container smoke proves packaging, migration, startup, health, and fail-closed
  routing without provider spend. It does not replace the P2/P3 deployed gates against
  real Neon, a real model provider, the browser Korean-IME journey, or capability-policy
  evidence.
- Cloud Run keeps the previous healthy revision at zero traffic. Rollback is traffic
  reassignment to that known digest, not a rebuild. Database migrations must be backward
  compatible with one previous application revision; destructive migrations require a
  separate ADR and backup/restore rehearsal.
- Use dedicated GitHub environments `Agent Preview` and `Agent Production`; the Vercel
  environments remain `Preview` and `Production`. Reviewers, self-review, and deployment
  branches are defined only in `.github/repository-governance.json` and checked by
  `scripts/verify_repository_governance.py`. The central contract keeps both production
  branch sets at exactly `{main}`.

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

- `aegra.json` at the repo root registers the static compiled graph, mandatory
  `agent.auth:auth`, and minimal `agent.http:app`. The custom FastAPI object becomes
  Aegra's application before native routers are included, so its pure-ASGI guard wraps
  native AP v2 commands without reimplementing them.
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
- Run `uv run --project agent --frozen --env-file .env python -m agent.migrate` against a
  direct local/Neon Postgres endpoint, twice, then start with
  `uv run --project agent --frozen aegra serve --config aegra.json`. Production keeps
  `RUN_MIGRATIONS_ON_STARTUP=false`.
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
no visible content is duplicated or lost. Separately close every database/checkpointer
pool, recreate the Aegra service graph objects, and prove checkpoint/thread state restores.
This local gate is a pool-recreation test, not a process-restart claim; a fresh deployed
process remains a P2 smoke requirement. Do not claim broker event replay survives a process
restart unless a test demonstrates it. Verify store/memory namespace isolation and that a
client-supplied `configurable.user_id` cannot change the trusted identity used by the backend:
Aegra preserves that forged field but separately injects
`langgraph_auth_user`/`server_info.user.identity`, which must be authoritative. With P0's
owner-auth server, prove resistance to the forged field and genuine cross-user isolation.
Exercise `run.start` and `input.respond` through `/threads/{thread_id}/commands`.

**Implemented evidence (2026-07-27):** Python 3.12 tests run the real Aegra
`LangGraphService` static-graph path with PostgreSQL 17, interrupt two identities, close
all pools, reinitialize, resume one identity, and prove the other checkpoint plus both real
`/memories/` namespaces survive unchanged despite a forged `configurable.user_id`. The
actual custom app returns 409 from the guard on the native command route and hides legacy
run/state/cron mutations with 404. Native thread DELETE returns 403 and leaves its
checkpoint unchanged. The provider-backed two-turn Korean smoke remains a deployment
acceptance check, not something the deterministic fixture claims to replace.

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
  that mirror becomes the container's only content root. At content tree
  `71c5bbda097cc20be0cb15ca4666fd6917f89d5f`, the source has 336 Markdown files but the
  Nuartz-published set has **335**: basename-leading `_` files are excluded, including
  `AI/pdf-parser/_index.md`. The mirror, catalogue, graph, dictionary, and every fitted
  index must all use the same 335-document set.
- This is the draft boundary, and it is the whole reason it cannot be bypassed. Today the
  boundary is a runtime predicate that three code paths must each remember; two forget and
  the third is wrong. **In the rebuild a draft is not filtered, it is absent from the
  image.**
- Fail closed: `draft` and `private` must be booleans when present; either `true` excludes
  the document and cannot be overridden. `published: false` also excludes, but the
  existing date/date-like-string `published` values are legacy publication timestamps,
  not booleans; preserve them as metadata. Reject other `published` types, and fail on an
  `unlisted` key until its semantics are explicitly decided. YAML parse errors, duplicate
  keys, and non-mapping frontmatter are build failures, not silent skips.
- Preserve the three currently public no-frontmatter documents through exact
  content-relative POSIX DocIds in owner-reviewed `agent/corpus-policy.toml`; a new
  no-frontmatter document or a stale allowlist entry is a build failure. Reject broken and
  out-of-tree symlinks. Preserve original Unicode paths, including U+200B, while rejecting
  NFC/case-fold collisions that would be ambiguous on another filesystem.
- P1.2 emits the mirror, `catalog.json`, corpus manifest/fingerprint, and resolved
  wikilink graph. P1.3 extends the same deterministic build with the Kiwi dictionary and
  fitted BM25 artifacts; it does not introduce a second corpus scan.
- CI test: build from fixtures containing public, draft, private, malformed, missing-
  frontmatter, legacy `published` dates, `published: false`, `_hidden.md`, unknown
  `unlisted`, Unicode/case collisions, and out-of-tree symlink cases; assert only the
  explicitly published fixture reaches `agent/.index/posts/`. Then walk the real mirror,
  require exactly 335 Markdown files, and fail if any excluded source appears. This makes
  the boundary auditable rather than aspirational.

> The corpus currently has zero `draft: true`, `private`, or boolean `published` values,
> but it already has one Nuartz-hidden `_index.md` that the Python agent indexes and three
> public no-frontmatter legacy files. The boundary fixes a present 336-vs-335 drift as well
> as future leaks.

### P1.3 The corrected BM25 baseline `BLOCKER for everything in P4`
A broken baseline invalidates every comparison drawn against it. Three independent fixes,
all needed - see [the registry](../reference/retrieval-methods.md#the-korean-tokenizer-problem):

1. **Reviewed user dictionary with a complete candidate audit.** `add_user_word("도커",
   "NNP")` restores `['도커']`, verified, but tags alone do not: the corpus has `Docker`
   and no `도커` tag. Preserve every Hangul tag and corpus-attested `한글(ASCII)` alias as
   a sorted candidate with provenance in `dictionary-evidence.json`, but activate only
   owner-reviewed seeds after applying deny-wins policy. Never promote a candidate merely
   because it was collected: doing so turns grammatical forms such as `크다`, `없다`, and
   `검증하고` into NNPs and collapses useful compounds such as `개발+도구`. Include the
   policy, canonical dictionary bytes, evidence checksum, and exact Kiwi configuration in
   the method fingerprint. Pin Kiwi 0.23.2, its separately distributed model data 0.23.0,
   and the CoNg model with the default dictionary enabled and typo/Wikidata multiword
   dictionaries disabled; the exact `s:` channel preserves surface matches while
   component morphemes remain available. If Kiwi is unavailable, fail the build rather
   than silently serving a fallback under the same method ID.
2. **Drop `VV` and `VA` from the keep-list.** They are what survives when an unknown noun
   is mis-analysed, which is what turns a tokenization failure into a confident wrong
   answer instead of an empty result.
3. **Index a namespaced surface-form channel alongside morphemes**, so a term the
   dictionary has not caught up with still matches exactly without colliding with
   morphological tokens.
4. **Fit once at build time.** Persist document lengths, first-seen term-order IDFs, and
   sparse postings in deterministic SQLite. At runtime, re-verify the fitted artifact
   bytes at access time against the checksum and byte count pinned by the validated root
   manifest, then deserialize those verified bytes into one private in-memory SQLite
   connection. Never reopen the mutable fitted path after verification: an initialized
   retriever has no post-init file dependency, while a new runtime fails closed if the
   artifact drifts. Do not ship raw token documents or construct `BM25Okapi` while
   serving. The registry identity path may reread and checksum the artifact bytes, but it
   neither deserializes the database nor creates a tokenizer; creating one registered
   retriever creates exactly one SQLite snapshot and one Kiwi tokenizer instead of
   fitting/loading the method twice.

Also remove the `score / max(scores)` normalisation: it forces the top hit to exactly 1.000
for **any** query including nonsense.

**Accept:** executable tests, not inspection, against a committed literal-term qrel
manifest pinned to the corpus tree. On the published 335-document corpus, current
`도커` recall@13 is 3/13 and the corrected method reaches 13/13; raw scores match
`BM25Okapi` without normalisation, ties are stable by DocId, serialized/load-time results
are identical, the fitted DB is byte-deterministic within the pinned build target, clean
Linux registry runtime `VmHWM` stays below 550 MiB, and absent, zero-score, and
negative-score terms produce no hit under the documented positive-score-only contract.
Build and evaluate the deployable artifact in the same pinned Linux x86_64 image; Kiwi's
optimized kernels can produce small cross-architecture floating-point differences even
when package and model versions match. The previously quoted macro
recall 0.323 → 0.605 has no versioned queryset or qrels in the repository and is **not a
gate**. Add a macro gate only with owner-reviewed `topic-smoke-v1` in P4.

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
- Disable native thread deletion with `@auth.on.threads.delete`. Aegra 0.9.24 deletes
  metadata without checkpoints and exposes no supported atomic extension, so there is no
  honest user-facing delete operation yet. A later admin GC/retention job is separate.
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
- Set `RUN_MIGRATIONS_ON_STARTUP=false` on every Cloud Run revision. Before deployment, run
  a separate one-shot job from the same immutable image digest with a separately held
  elevated direct Neon `DATABASE_URL` and the command `python -m agent.migrate`; require
  success before creating or updating the service revision. That entrypoint upgrades Aegra
  metadata and creates the LangGraph checkpointer/store tables. Never expose the migration
  credential to the runtime.
- Give the service a separate least-privileged direct Neon URL. Reject `-pooler` hostnames
  before startup in accordance with ADR-0007, and exercise both async and synchronous
  database paths in preview. Aegra 0.9.24 still invokes the LangGraph saver/store
  `setup()` methods during lifespan startup, so the separated runtime role temporarily
  needs the exact schema-local idempotent DDL those calls exercise in addition to narrow
  DML. Treat the grant shape as a real-Neon deployment gate: startup/restart and
  checkpoint/store operations must succeed while cross-schema, role-management, and
  administrative operations fail. Tighten the role to DML-only when Aegra exposes a
  supported no-DDL startup.
- Deploy initially with 1 GiB memory, `cpu_idle=true`, `startup_cpu_boost=true`, a
  300-second timeout, `max_instances=1`, concurrency 8, a **dedicated minimal service
  account**, and an application entrypoint fixed to one server worker. Keep
  `REDIS_BROKER_ENABLED=false` and `BG_JOB_MAX_RETRIES=0`. Turn Postgres pool knobs down
  (Aegra opens up to ~50 connections by default). Cloud Run's 512 MiB default is too close
  to the measured ~373 MiB clean Linux x86_64 BM25 runtime before Aegra, API, database
  pools, and concurrent requests are loaded.
- Verify the owner token succeeds and an anonymous or forged token receives 401/403 on the
  exact streaming route used by the frontend, not only on a metadata route.
- `max_instances=1` and one application worker are both load-bearing: either setting
  exceeding one splits P5's in-process guard.
- Set the Anthropic organization spend cap. Grep startup logs for Aegra's
  data-not-isolated warning.

**Accept:** the same-digest direct-URL `python -m agent.migrate` job succeeds before deployment;
the service starts with `RUN_MIGRATIONS_ON_STARTUP=false`, rejects `-pooler` hostnames, and
proves its separate direct runtime URL and the required grant/denial matrix against real
Neon across the exercised async/sync database paths;
`/live` returns 200, `/ready` is healthy, and `scripts/smoke.py` passes with owner preview
credentials. The same streaming requests without credentials or with a forged subject
receive 401/403; cold-start-to-first-token and full-image cold-start plus concurrency-8
memory are measured and recorded without approaching the 1 GiB limit. Starting a fresh
revision from the same image digest restores persisted checkpoint/thread/memory state. Do
not continue if graph routes are anonymously reachable, a pooler endpoint is configured,
the process settings split the guard, or measured memory leaves inadequate headroom.

---

## P3 - assistant-ui `~3 days`

Preview URL first. The native implementation is WEB-A owner-only until the WEB-B public
state/input network boundary below is satisfied.

### P3.1 UI contract

The chatbot remains part of the home-page experience, but gets a full-height focused mode
instead of trying to fit every control into the hero. Desktop uses a three-zone shell;
mobile uses one conversation surface with sheets for threads and run detail.

```text
web/components/assistant/
├── chat-section.tsx               # owner-preview gate
├── chat-shell.tsx                 # assistant-ui Thread/ThreadList primitives
├── agent-runtime-provider.tsx     # native runtime + thread adapter
└── runtime/
    ├── native-client.ts           # official SDK ThreadStream/MessageAssembler
    ├── thread-adapter.ts          # official SDK metadata/state/history
    ├── inspection.ts              # exact syshin.rag.inspection.v1 projection
    ├── interrupt-projection.ts    # bounded HITL projection
    ├── token-broker.ts            # refresh, identity disposal, cancellation snapshot
    ├── ime.ts
    ├── focus-restoration.ts
    └── error-state.ts
```

- WEB-A signed-out view explains that the preview is owner-only. WEB-B later replaces this
  with anonymous testing, example prompts, privacy/AI copy, and a clear new-conversation
  action only after P5/P6 gates pass.
- Message answers render citations inline and a source list below. Retrieval method and
  corpus revision are visible in a compact run-details disclosure, not mixed into prose.
- Tool activity collapses into a timeline by default. Retrieval shows the exact bounded
  query/method/hit/stage/source fields emitted by the server. QuickJS or subagent-specific
  cards appear only after a reviewed protocol event exists; generic tool/nested lifecycle
  must not be relabelled as a capability the run did not prove. Internal chain-of-thought
  is never displayed. This is only a UI guarantee: root `messages` events may already
  have carried reasoning/thinking blocks to the browser.
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

- Use assistant-ui's native `useLangGraphRuntime`, but do **not** use
  `unstable_createLangGraphStream`: it calls legacy `client.runs.stream`. Supply a stream
  callback backed by the official `@langchain/langgraph-sdk` 1.9.28
  `Client.threads.stream`, `ThreadStream`, and `MessageAssembler`.
- Call `ThreadStream.submitRun/respondInput`. These emit Aegra's supported
  `run.start`/`input.respond` wire commands without the older SDK methods' implicit
  wildcard `values` projection.
- Open exactly one application content subscription:
  `channels=[messages,lifecycle,input,tools,custom]`, `namespaces=[[]]`, `depth=0`.
  Never subscribe to `values` or `updates`, and never union nested messages into this
  connection. The SDK separately opens a physical lifecycle watcher connection with only
  `channels=[lifecycle,input]`; it is outside the content union.
- Use bounded local projections for root messages, citations, inspection events, and HITL.
  The local reducer drops system/tool/reasoning/open-state fields from UI state. Inspection detail is
  `delivery=live-run-only`; reload must say the exact detail is unavailable.
- Use the official SDK client for cancellation, metadata, state, and history. Do not add a
  custom REST facade. Keep Edit/Regenerate/branch mutation/delete visibly disabled until
  the backend supports their required semantics.
- **WEB-B network gate:** `threads.getState/getHistory` currently returns open checkpoint
  state to browser JavaScript before local reduction. The SDK lifecycle watcher's wildcard
  `input` can also carry a future sensitive nested interrupt payload. Root `messages` can
  carry provider reasoning/thinking blocks before the local reducer hides them.
  Owner-only WEB-A may accept these limitations; anonymous access may not. Before WEB-B,
  require a server-side safe state/history projection plus a root-filterable watcher, or a
  separately proven public endpoint whose graph-level HITL/state schemas are bounded;
  also require upstream/server-side reasoning suppression/redaction or a separately proven
  model path that emits no reasoning on the browser wire.
- In `load()`, read `state.interrupts` **first** - Aegra returns interrupts as a top-level
  field, so the quickstart's `state.tasks[0].interrupts` is the wrong read here.
- Async `onRequest` token hook with a 60s margin. Capturing the token once at mount 401s
  mid-conversation.
- `remarkPlugins={[remarkGfm, remarkBreaks]}` with components memoised at module scope.
  **remark-breaks is load-bearing for Korean.**
- **Korean IME: verify with a Playwright test, do not assume.** Highest-risk regression.
- Cut over and delete the named legacy browser transport modules and vendored prompt-kit.
  Do not use an LOC target as deletion scope. Explicitly retain
  `agent/src/agent/retrieval/**`, the rebuilt graph, auth/identity code, and their tests.

**Accept:** a full multi-turn Korean conversation against deployed owner-authenticated
Aegra over AP v2; reload restores visible messages while truthfully marking prior
inspection detail unavailable; the two SSE connections match the exact channel filters
above; the actual JavaScript SDK ↔ Aegra ↔ isolated PostgreSQL 17 fixture proves
`rawPrivateStateObserved=false`, canonical inspection, HITL, tool/nested lifecycle,
message assembly, persistence, and connection return. This sentinel assertion is a
state-channel regression, not a general proof that future input payloads are public-safe
or that chain-of-thought cannot traverse a root message event.
Desktop, 768 px, 390 px, and 320 px browser evidence covers console/network/a11y,
reduced-motion, focus restoration, and Korean IME. No production import or network call
uses legacy `/runs/stream`; unsupported mutations are visibly disabled. WEB-B remains
blocked on safe state/history, the input watcher, and reasoning-wire suppression or proof.

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
- **Bootstrap qrel candidates from the 164 aliased `[[target|alias]]` occurrences in the
  published corpus.** The alias is the author's own Korean surface form for a target
  document - free known-item evidence that no public corpus has. Resolve, deduplicate, and
  record exclusions before calling them gold; use them before spending anything on
  LLM-generated queries.
- Keep two versioned query-set contracts rather than mixing their metrics:
  `known-item-alias-v1` maps each alias to one target and headlines Hit@k and MRR;
  `topic-smoke-v1` contains manually reviewed multi-document qrels and headlines recall@k.
  Each committed manifest records its generator/version, corpus tree SHA, qrels, and
  exclusions. The BM25 macro-recall regression uses `topic-smoke-v1`.
- Pin the corpus by **git tree sha of `content/`**. The harness never reads live `content/`.
- **Report `coverage` alongside recall@k, always.** The published-corpus wikilink graph is
  sparse, so a graph method that declines to answer on most queries would otherwise look
  strong only where it fires. Record its exact node/edge coverage in the generated corpus
  manifest rather than copying statistics from the former 336-document agent corpus.
- **Do not headline nDCG.** On four smoke queries nDCG@10 read 1.000 for every one while
  recall@10 ranged 0.23 to 0.77. It saturates when relevant-sets are large and ungraded.
- Local `results/<tree-sha>/` JSON is the **system of record**; LangSmith's free tier keeps
  traces 14 days and caps at ~3 full sweeps a month. Use it as a comparison UI, not storage.
- A committed pytest regression gate on macro recall@10, added only after
  `topic-smoke-v1` qrels receive owner relevance review. Until then, the literal-term
  Docker qrel and synthetic tokenizer contracts are the P1.3 regression gates.
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
- Treat `snapshot()` as observation only. Capability evaluation must call the atomic
  `finalize()` boundary, which terminalizes the run, rejects any open model or task
  reservation, enforces `elapsed < limit`, and returns an immutable frozen snapshot.
  Provider usage comes only from middleware-parsed Anthropic metadata, never executor
  observations. The pricing buckets are uncached input, output, cache-read input, and
  cache-write input; cache-write combines Anthropic's five-minute and one-hour creation
  buckets when those TTL details are present. If a required usage/detail field is absent,
  negative, unknown, or internally inconsistent, `provider_usage_complete` is false and
  every aggregate provider bucket is `null`; no zero-valued usage is fabricated.
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
This run-local finalization evidence does not replace P5's lower guest policy,
per-identity/global daily dollar ledger, rate limit, or provider-side spend cap.

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
- Confirm the separate administrative retention/GC job measurably reduces orphaned
  checkpoint row count; it does not enable user-facing thread deletion.
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
| `HIGH` | Aegra thread deletion strands checkpoints and cannot commit both stores atomically | Native DELETE is fail-closed with 403. Do not expose a faux-safe route; design admin GC separately |
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
