---
title: "Upstream framework version audit runbook"
description: >
  The read-only scheduled check that compares exact agent, protocol, and native chat
  pins with stable releases from allowlisted official registries.
when_to_read: >
  When the dependency/upstream-versions job fails, before changing its targets or
  release semantics, or when adding a pinned framework such as QuickJS.
tags:
  [operations, dependencies, github-actions, aegra, agent-protocol, langgraph, quickjs]
status: stable
updated: "2026-07-31"
owners: ["@syshin0116"]
refs:
  - ../../.github/workflows/dependency-audit.yml
  - ../../scripts/upstream_version_audit.py
  - ../../protocol/agent-protocol.lock.json
  - ../reference/github-governance.md
  - ../plans/rag-restack.md
template: spec
---

# Upstream framework version audit runbook

## Contract

[`upstream_version_audit.py`](../../scripts/upstream_version_audit.py) is a read-only
compatibility alert. It never resolves, installs, or updates a package. The scheduled and
manual [Dependency audit workflow](../../.github/workflows/dependency-audit.yml) fails
visibly when an allowlisted exact pin is behind a newer stable release or when the answer
cannot be established safely.

The required targets are:

| Target | Exact repository sources | Official release source |
| --- | --- | --- |
| `aegra-api` | `agent/pyproject.toml`, `uv.lock`, Aegra tag in `protocol/agent-protocol.lock.json` | `https://pypi.org/pypi/aegra-api/json` |
| `aegra-cli` | `agent/pyproject.toml`, `uv.lock` | `https://pypi.org/pypi/aegra-cli/json` |
| Agent Protocol | release, tag, commit, and generated-binding package fields in `protocol/agent-protocol.lock.json` | `https://api.github.com/repos/langchain-ai/agent-protocol/releases?per_page=100` |
| `deepagents` | `agent/pyproject.toml`, `uv.lock` | `https://pypi.org/pypi/deepagents/json` |
| `langgraph` | `agent/pyproject.toml`, `uv.lock` | `https://pypi.org/pypi/langgraph/json` |
| Python `langgraph-sdk` | `agent/pyproject.toml`, `uv.lock` | `https://pypi.org/pypi/langgraph-sdk/json` |
| `langchain-openai` | `agent/pyproject.toml`, `uv.lock` | `https://pypi.org/pypi/langchain-openai/json` |
| OpenAI Python SDK | `agent/pyproject.toml`, `uv.lock` | `https://pypi.org/pypi/openai/json` |
| `langchain-quickjs` | `agent/pyproject.toml`, `uv.lock` | `https://pypi.org/pypi/langchain-quickjs/json` |
| direct `quickjs-rs` | `agent/pyproject.toml`, `uv.lock` | `https://pypi.org/pypi/quickjs-rs/json` |

The allowlist is compiled from typed target records. There is no CLI URL, package, or
repository override. Requests use HTTPS, a 15-second timeout, a 4 MiB response ceiling,
strict JSON parsing, and an exact canonical final URL. A redirect to another host,
package, or repository fails before its payload is trusted. HTTP, timeout, malformed,
oversized, pagination, and schema errors fail closed.

### OpenAI serialization pins

The GPT-5.6 Luna guest Responses payload, including its explicit
`reasoning.context=current_turn` override, is serialized by exact
`langchain-openai==1.3.5` and `openai==2.50.0` pins. Both dependencies remain
required manifest/lock audit targets and isolated from routine grouped
Dependabot updates. `langchain-openai` is audited
against the latest stable release below the reviewed exclusive `1.4.0`
compatibility ceiling: 1.4.x requires `langchain-core>=1.5.1`, while this
repository remains on 1.4.9. The report exposes that ceiling explicitly.
Changing or removing it requires a focused compatibility PR with capture,
native-stream, provider-usage, and full agent evidence.

### assistant-ui activation

The repository contains both `@assistant-ui/react` and
`@assistant-ui/react-langgraph`, so the `assistant-ui` group is active and every
target below is mandatory.

The activation rule remains fail-closed: if either package appears in
`web/package.json` or `web/bun.lock`, the whole group is mandatory:

- `@assistant-ui/react`;
- `@assistant-ui/react-langgraph`;
- JavaScript `@langchain/langgraph-sdk`.

All three must be exact direct manifest versions, repeated exactly in the Bun root
workspace and resolved by matching Bun lock entries. Their stable releases come only from
`https://registry.npmjs.org/%40assistant-ui%2Freact`,
`https://registry.npmjs.org/%40assistant-ui%2Freact-langgraph`, and
`https://registry.npmjs.org/%40langchain%2Flanggraph-sdk`. A partial group or a range such
as `^1.9.28` fails before any result can be called current.

### QuickJS direct-pin contract

The native QuickJS capability makes both `langchain-quickjs` and its `quickjs-rs` runtime
required audit targets. `quickjs-rs` remains an exact direct project dependency even
though `langchain-quickjs` also depends on it: the reviewed native runtime version must
not move only because an upstream transitive range changed. Each package must appear
exactly once with the same stable `==` version in `agent/pyproject.toml`, its official
PyPI resolution in `uv.lock`, and the root project's `requires-dist` metadata.

Removing both packages, leaving only one, using a range, resolving from a non-PyPI
source, or allowing either manifest/lock record to drift fails closed before that target
makes a network request. Release checks are allowlisted only to
`https://pypi.org/pypi/langchain-quickjs/json` and
`https://pypi.org/pypi/quickjs-rs/json`.

At implementation time, the official stable versions were Aegra API/CLI `0.9.24`, Agent
Protocol `langchain-protocol==0.0.18`, Deep Agents `0.6.12`, LangGraph `1.2.9`, Python
LangGraph SDK `0.4.2`, LangChain QuickJS `0.3.4`, QuickJS Rust binding `0.2.5`,
assistant-ui React `0.15.0`, its LangGraph adapter `0.14.15`, and JavaScript LangGraph
SDK `1.9.28`. This dated snapshot is evidence, not the audit input; each run reads the
official endpoint again and exposes normalized `installed`, `latest`, `source`, and
`releaseUrl` fields for every active target.

## Stable-release semantics

- PyPI releases must parse as PEP 440, have at least one non-yanked file, and exclude
  alpha, beta, release-candidate, and dev releases. `info.version` must identify the
  highest remaining release.
- npm versions must parse as semantic versions. Pre-release identifiers and versions
  carrying npm's string-valued `deprecated` field are excluded, every version record
  must repeat the canonical package and version, and the `latest` dist-tag must identify
  the highest remaining stable version.
- Agent Protocol uses only non-draft, non-prerelease GitHub Releases whose tag begins
  `langchain-protocol==`. The suffix follows the package's PEP 440 final-release
  semantics. Other release families in the same repository are ignored.
- Booleans are not accepted as integers, including lock versions, HTTP status, GitHub
  release IDs, and schema flags. Registry boolean fields must be actual booleans.

The GitHub endpoint is intentionally bounded to 100 releases. A pagination link fails
closed instead of silently claiming that the first page contains the highest release.

## Run and interpret

Run the same dependency-free command from the repository root:

```bash
python3 scripts/upstream_version_audit.py \
  --output /tmp/syshin0116-upstream-version-audit.json
```

The canonical JSON is also printed to stdout. `--summary <path>` writes the bounded
Markdown table used by GitHub Actions.

| Exit | Report status | Meaning |
| --- | --- | --- |
| `0` | `current` | Every active exact pin equals the latest stable official release |
| `1` | `outdated` | At least one newer stable release exists |
| `2` | `error` | A pin, transport, canonical target, size, JSON, or upstream schema check failed |

An inactive optional group does not affect the exit code. A network error for any active
target is never converted to a skip or a cached success.

## Triage

1. Read the JSON target's exact `installed`, `latest`, `source`, and `releaseUrl`.
2. Re-run once to distinguish a transient outage from reproducible drift. Repeated
   transport failure is still a red audit, not permission to weaken the check.
3. Create a dedicated worktree and focused compatibility PR. Do not update a manifest
   from the scheduled job.
4. For Aegra or Agent Protocol, update the protocol lock, generated bindings, support
   matrix, fixtures, runtime integration, and live protocol evidence together.
5. For Deep Agents or LangGraph, run the agent, PostgreSQL, retrieval, RunBudget, and
   capability suites appropriate to the changed surface.
6. For either QuickJS package, update both direct manifest/lock pins deliberately and
   rerun the native runtime, sandbox hardening, lifecycle, RunBudget, and graph-topology
   suites.
7. For assistant-ui or the JavaScript SDK, update `web/package.json` and `web/bun.lock`
   together and rerun unit, browser, responsive, IME, and Aegra transport evidence.
8. Merge only after the focused PR's normal required checks pass. The scheduled audit
   remains red until the reviewed exact pin reaches `main`.

## Extending the target set

QuickJS is now part of the required typed target set. Its focused official-response
fixtures prove prerelease and yanked filtering, schema drift, missing or partial pins,
and newer stable releases. The local governance verifier binds the complete audit script
by reviewed SHA-256, so changing or removing a target also requires an explicit
governance-baseline update and mutation test.

For another capability, add a typed required target or an `OptionalTargetGroup` beside
`OPTIONAL_TARGET_GROUPS`; either form automatically extends the compiled URL allowlist.
Require exact manifest and lock evidence, add a minimal official-response fixture, and
test absence, partial presence or activation, prerelease filtering, malformed responses,
and a newer stable release. Update this table and the governance digest in the same PR.

Never accept a package name, registry URL, GitHub repository, tag prefix, timeout, or
response limit from workflow input. A new source is a reviewed code change.
