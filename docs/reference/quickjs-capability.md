---
title: "Bounded QuickJS capability contract"
description: >
  Authorization, sandbox, resource, result, and persistence boundaries for the
  owner/evaluation JavaScript capability.
when_to_read: >
  Before changing langchain-quickjs, the eval tool, RunBudget, agent middleware
  ordering, capability tiers, or QuickJS execution-detail UI.
tags: [agent, quickjs, langchain, deep-agents, security, evaluation]
status: stable
updated: "2026-07-28"
owners: ["@syshin0116"]
refs:
  - ../adr/0006-public-anonymous-chat-access.md
  - ../adr/0008-chatbot-is-a-rag-evaluation-testbed.md
  - ../plans/rag-restack.md
template: reference
---

# Bounded QuickJS capability contract

This is a P4.5 agent-capability experiment, not a retrieval method. It must not
change which corpus or retriever ordinary chat uses, and its measurements stay
out of the retrieval leaderboard.

## Version and framework boundary

- `langchain-quickjs==0.3.4` is pinned directly. The reviewed upstream release
  is tag
  [`langchain-quickjs==0.3.4`](https://github.com/langchain-ai/deepagents/tree/langchain-quickjs%3D%3D0.3.4/libs/partners/quickjs)
  at commit `196a0870fcf8a7f29d1fb37886dd323b190f9c16`.
- `BoundedQuickJSMiddleware` subclasses the native
  `CodeInterpreterMiddleware`. It retains the single native registry and calls
  only the native tool's async coroutine.
- Deep Agents remains the planner and subagent layer. LangChain middleware
  supplies QuickJS, and LangGraph/Aegra owns graph execution and persistence.
- The replacement `StructuredTool` has no synchronous function. A synchronous
  graph call never advertises `eval`; direct synchronous tool invocation fails
  before guest code runs.

## Authorization and topology

`QUICKJS_ENABLED=false` is the deployment default. Enabling it is a server
operation and accepts only the exact values `true` and `false`. A run then also
requires `admin` or `eval` in `ServerRuntime.user.permissions`.

Client context, metadata, configurable fields, model output, and checkpoint
state cannot grant the capability. Reserved client keys such as `quickjs`,
`code_interpreter`, and `capability_*` fail closed.

The middleware and tool node remain topology-stable across Aegra access
contexts. When unauthorized, both the QuickJS middleware and shared budget
middleware remove `eval` before model binding, omit its system prompt, and
reject a forged tool call before reserving or executing it. Anonymous and
ordinary signed-in users therefore cannot observe or execute the capability.

QuickJS middleware precedes `RunBudgetMiddleware`. This ordering is
load-bearing: the budget must estimate input tokens after the bounded QuickJS
prompt has been appended.

## Sandbox

Every call uses native `mode="call"` with:

- `ptc=None`;
- `subagents=False`;
- `capture_console=False`;
- no filesystem, environment, network, module loader, import source, Python
  callable, LangChain tool, or `task` bridge;
- only the guest's data-oriented JavaScript built-ins.

Declarative children have no `eval` tool or QuickJS middleware. Their shared
budget middleware also explicitly denies the tool name, so a child capability
cannot grow through inherited configuration.

The regression suite runs real guest code—not a mocked sandbox—to probe host
secret, environment, filesystem, metadata-network, dynamic-module, console,
Python, PTC, and task access. Raw guest errors, Wasmtime traps, source text,
stacks, and host exception details are never returned.

## Bounds

| Resource | Per run/call |
|---|---:|
| Guest heap | 16 MiB per native runtime |
| Guest stack | 1 MiB (`quickjs-rs==0.2.5` runtime default) |
| Native execution deadline | 1.0 s per execution |
| Outer async timeout | 1.5 s |
| Source | 16 KiB UTF-8 |
| Serialized tool result | 4 KiB UTF-8 |
| Executions | 4 per run |
| Concurrent interpreter sessions | 1 per run |
| Cumulative measured output | 16 KiB per run |
| Snapshot payload | none (`mode="call"`); defensive constructor cap 64 KiB |

`RunBudget.reserve_quickjs()` reserves the ordinary tool count, QuickJS
execution count, concurrency slot, and maximum output tranche under the same
lock. Settlement releases the concurrency slot and refunds only measured
unused output. Cancellation or an unmeasurable response retains the full output
reservation, preventing cancellation from becoming a budget bypass.

The interpreter is deliberately in-process. Native timeout interruption covers
ordinary compute loops, but Python cancellation cannot forcibly kill a host
call while Wasmtime is unwinding or resetting the runtime. Therefore these
deadlines are not a process-isolation guarantee: public enablement requires a
separate killable worker boundary and an adversarial allocation-loop gate. The
deployment default and permission gate must remain in place until then.

## Result contract

Every normal tool result is canonical JSON bounded after serialization:

```json
{
  "output": "42",
  "schema": "syshin.quickjs.result.v1",
  "status": "ok",
  "truncated": false
}
```

Allowed statuses are `ok`, `truncated`, `timeout`, `out_of_memory`,
`invalid_input`, and `invalid_result`. Only successful pure-data output is
copied into `output`. All failure statuses have an empty output. Truncation is
performed against the complete UTF-8 JSON envelope without splitting a Unicode
sequence or JSON escape.

## Persistence and evaluation

The Aegra async graph factory constructs a fresh middleware/native registry and
one non-serializable `RunBudget` for every access. Call mode ignores snapshot
input, evicts the native slot after the agent turn, and never writes
`_quickjs_snapshot_payload` to checkpoints.

P4.5 evaluates QuickJS as an independent on/off axis. Public enablement remains
out of scope until the capability dataset shows a material gain and the P5/P6
deployed abuse and budget gates pass.
