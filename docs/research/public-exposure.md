---
title: "Research: making the chatbot public without a login"
description: >
  What breaks, what leaks, and what it costs if the RAG chatbot is opened to
  anonymous visitors - plus the identity, abuse, and budget controls that would
  have to exist first.
when_to_read: >
  Before removing the sign-in gate on the chatbot, before adding a code
  interpreter, or when revisiting anonymous retention and rate limits.
tags: [research, security, cost, auth, anonymous, sandbox, rate-limiting]
status: draft
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [../adr/README.md]
template: research
---

# Research: making the chatbot public without a login

> **Not a decision.** Input to the public-access and code-interpreter ADRs.

> **Investigated** 2026-07-26 against the repo at `09a29a9`, plus current vendor
> docs. Every code claim below was re-verified by reading the file, and the
> `file:line` references are the evidence - not a summary of someone's summary.

## Bottom line

The chatbot can go public, but not as it stands. Two **live content-leak bugs** put
unpublished drafts in reach of any caller, and three route-level gaps turn a valid
token into an unbounded write, model-selection, and queueing primitive. Separately,
the honest answer on the code interpreter is that anonymous visitors should not get
one - not as a hedge, but because a blog visitor asking about blog posts gets nothing
from it while it costs a permanent security surface.

The cheap news: **anonymous access does not require touching the owner-scoping
code at all.** Everything downstream reads only `claims["sub"]`, so minting tokens
with a random `anon:<uuid4>` subject keeps every existing filter working unchanged.

## Live bugs, verified

These are exploitable today by any allowed user and by anyone at all the moment the
sign-in gate comes off. Both concern `draft: true` posts, which `get_cached_docs`
filters out and which the site's own build already excludes.

### 1. Generic filesystem tools bypass every content filter

[`agent/src/agent/graph.py`](../../agent/src/agent/graph.py) `_build_backend` mounts
a `ReadOnlyFilesystemBackend` at `/blog/` rooted at the whole `content/` directory.
deepagents' `FilesystemMiddleware` then hangs generic `ls`, `glob`, `grep`, and
`read_file` off that route, and **none of them know what a draft is**. The six
curated tools in `tools.py` do their filtering in Python; this route goes around all
of it. A hostile visitor does not need an exploit, only a request: *glob the
directory, then read the file*.

Fixing the ripgrep bug below without removing this route fixes nothing.

### 2. `ripgrep_search` returns draft body text

[`agent/src/agent/lib/ripgrep_search.py:45`](../../agent/src/agent/lib/ripgrep_search.py)
runs `rg` over `cfg.content_dir` - the raw directory, unfiltered. The results loop
at lines 82-100 then looks each matched file up in the draft-filtered cache:

```python
doc = doc_by_path.get(fpath)                                   # None for a draft
title = doc.meta.title if doc else fpath.split("/")[-1]        # falls back to filename
rel_path = doc.meta.path if doc else fpath.replace(...)        # falls back to raw path
snippet = "\n".join(match_lines[:3])                           # ALWAYS the matched lines
results.append(SearchResult(path=rel_path, title=title, ..., snippet=snippet))
```

A cache miss means *"this file is not published"*, and the code treats it as
*"this file has no metadata"*. It degrades gracefully instead of refusing, and
returns the matched body lines verbatim. `_python_fallback`, in the same file,
filters correctly - so the two search paths disagree, which is the classic shape of a
bug that survives review.

`tests/unit_tests/test_content_security.py` covers path traversal and write-blocking
well, and **never tests draft exclusion**, which is why this survived.

## Route-level gaps, verified

| Gap | Evidence | Why it matters when public |
|---|---|---|
| `PUT /store/items` takes an arbitrary namespace, key, and JSONB value from any valid token | [`routes/store.py:23-26`](../../agent/src/api/routes/store.py) - only `get_user_id`, no size or shape bound | An unbounded write vector into a capped free-tier Postgres |
| `configurable.model` passes straight through to the graph | [`run_manager_base.py:116-119`](../../agent/src/api/run_manager_base.py) strips only `thread_id`, `user_id`, `checkpoint_*` | Caller picks the model |
| The seeded default model is OpenAI's most expensive | [`db.py:96`](../../agent/src/db.py) - `("openai", "openai/gpt-5.4", "GPT-5.4", True)`, with `claude-opus-4-6` and two Gemini models also seeded | Combined with the row above, an anonymous visitor selects the priciest option. OpenAI is in the threat model, which a cost analysis scoped to Anthropic would miss |
| `GET /models` has no admin dependency | [`routes/models.py`](../../agent/src/api/routes/models.py) | Any token enumerates the configured providers |
| `multitask_strategy` defaults to `enqueue` and the request body wins | [`schemas.py:119`](../../agent/src/schemas.py); the run managers default to `reject` but the body overrides | One subject piles unbounded queued runs on a thread against a shared ARQ `max_jobs` of 10 with a 600s timeout, starving everyone else for an hour |

## Anonymous identity: the cheap path

The important structural finding: **nothing in `agent/src` cares where a subject came
from.** `auth.py` reads `claims["sub"]`, and from there `deps.get_user_id`,
`resource_scope.scoped_checkpoint_thread_id`, every `owner_id` filter in `db.py`, and
`graph._memory_namespace` all operate on an opaque string.

So the whole perimeter is one file: `web/app/api/agent-token/route.ts` gains an
anonymous branch that verifies a Cloudflare Turnstile token, then mints with subject
`anon:<uuid4>`, scope `anon`, and a short TTL, persisting the uuid in an httpOnly
`SameSite=Lax` cookie so a visitor keeps history on that device. **No owner-scoping
code changes.**

| Option | Verdict |
|---|---|
| Random per-session `anon:<uuid4>` subject, Turnstile-gated | **Recommended.** Reuses every existing filter unchanged |
| One shared `public` owner id | **Unsafe.** `db.search_threads` filters on `owner_id` alone, so a shared owner is a full cross-visitor read of every conversation |
| Client-supplied identity header | **Unsafe.** Forgeable, and an attacker can set a real Auth.js `users.id` and read the owner's threads |
| Separate unscoped code path for anonymous | Two code paths, twice the places to get it wrong |

Two follow-on consequences:

- **Memory.** `_memory_namespace` raises when `user_id` is missing, and `StoreBackend`
  resolves its namespace lazily per file operation - so an anonymous run would fail
  mid-run rather than at the request boundary. Mounting no `/memories/` route for
  `anon:` subjects makes writes fall through to the thread-scoped `StateBackend`
  instead, which is reaped with the thread. Leave the raise in place; it is the
  invariant, not the bug.
- **Retention.** Anonymous threads otherwise accumulate forever. `runs` cascade from
  `threads`; **checkpoints do not**, and the checkpoint tables (a row per superstep,
  carrying full message state) are what actually consume a free-tier storage cap. A GC
  that forgets `checkpointer.adelete_thread(...)` reclaims almost nothing.
  `worker.py`'s `WorkerSettings` currently declares no `cron_jobs`.

## Rate limiting: where it has to live

Enforce in the Python API, not in Next.js. `web/lib/preview-abuse.ts` is a sound
in-process limiter, but every Vercel lambda instance keeps its own `Map`, and it does
not sit in front of Cloud Run at all.

The placement detail is exact and easy to get backwards. Starlette makes the
**last-added middleware outermost**, so [`main.py:102-104`](../../agent/src/api/main.py)
executes as CORS → `AgentAuthMiddleware` → `RequestLoggingMiddleware`. A limiter that
needs `request.state.user_id` must therefore be added **at or before line 102**,
alongside `RequestLoggingMiddleware`. Added after line 103 it runs *before* auth,
sees no subject, and silently degrades to a global limiter - working, wrong, and
quiet about it.

## Code execution: do not self-host it

For anonymous users the recommendation is unambiguous: **no code interpreter, at any
isolation level.** The value to a blog visitor is approximately zero and the surface
is permanent.

For the owner, the finding is that self-hosting the sandbox is the wrong axis. The
threats that matter in a GCP container - metadata-server SSRF at `169.254.169.254`
minting a real service-account token, env-var exfiltration of the API keys, network
egress - are *structurally absent* when the code runs on Anthropic's infrastructure
rather than mitigated by configuration. Anthropic's server-side `code_execution` tool
has no internet access and a standing free monthly allowance.

| Option | Verdict |
|---|---|
| Anthropic server-side `code_execution` | **Recommended for the owner tier.** The isolation problem stops being yours |
| QuickJS via WASM (`langchain-quickjs` family) | Genuinely strong in-process isolation, JS-only. But it answers "how do I sandbox this" - a question worth not asking |
| Deno / Pyodide (`langchain-sandbox`) | Needs Deno in the image; more moving parts on Cloud Run |
| E2B, Daytona | Free tiers are one-time credits that cliff into a three-figure monthly base fee |
| nsjail / gVisor / Cloud Run sandbox launcher | Correct answers to a question you should not be asking |

**On `langchain-quickjs` and "dynamic subagents":** these are two independent things
that got bundled together in the original framing. A JS sandbox does not create
subagents. See [`restack-options.md`](restack-options.md) for what `deepagents`
actually offers for runtime-composed subagents.

## Budget: one real hard stop, everything else is friction

The only provider-enforced cap that a bug in your own code cannot bypass is the
**Anthropic organization-level self-set spend limit** (Console → Settings → Limits).
Set it to a number you would not mind losing. Minting the key inside a dedicated
Workspace additionally makes revocation one click, with no redeploy.

Everything else slows the burn rather than stopping it:

- LangChain ships **no token or cost budget middleware** - only call-count limiters
  (`ModelCallLimitMiddleware`, `ToolCallLimitMiddleware`). A dollar-denominated daily
  cap has to be your own `wrap_model_call` middleware over a Redis counter. Note a
  single call with a 200K-token context is *one call* and passes every built-in limiter.
- GCP budget alerts **do not cap anything** - the docs are explicit that budgets do
  not prevent usage or billing. The disable-billing function is a nuclear option,
  which is the argument for putting the agent in its own GCP project.
- Cloud Run compute is the cheap half of the bill at this traffic. The LLM spend is
  the bill.

## Unverified

- Whether the Anthropic Workspace-scoped key path requires an Organization rather than
  an individual account - the control is only one-click-revocable if it does.
- Actual cache-hit behaviour for prompt caching on the current prompt. The prefix
  looks byte-stable (`build_system_prompt()` is dead code and `{system_time}` is never
  interpolated, so the model currently receives a literal unsubstituted placeholder),
  but minimum cacheable prefix length differs by model and this was not measured.
- Whether Turnstile meaningfully deters a determined scraper, as opposed to raising
  cost. Its real job here is forcing token minting through a browser-shaped flow.
- Korean PIPA exposure from LangSmith tracing on public traffic. Traces carry full
  prompts and full retrieved content, so enabling them stores arbitrary visitor input
  in a third party. Not a legal assessment.
