---
title: "Execution plans"
description: >
  Index of sequenced plans decomposed into work packets that can be handed to
  separate agents.
when_to_read: >
  Before picking up multi-phase work, or before dispatching an agent onto a packet.
tags: [index, plan]
status: stable
updated: "2026-07-27"
owners: ["@syshin0116"]
refs: [../adr/README.md, ../research/README.md]
template: index
---

# Execution plans

Sequenced plans for work too large for a single change. A plan differs from an ADR: an
ADR records *what was decided and why*, a plan records *what to do, in what order, and
how to know a step is done*. Plans go stale and get deleted once delivered; ADRs do not.

Each plan decomposes into **work packets** - a goal, the files in scope, acceptance
criteria, and what it would break. A packet should be handable to an agent on its own,
with the plan's phase section plus its linked research, rather than the whole file.

## Index

| Plan | Covers | Status |
|---|---|---|
| [rag-restack.md](rag-restack.md) | Rebuild on Aegra and assistant-ui, prove basic chat, evaluate retrieval plus bounded QuickJS/subagent capabilities, harden, then open anonymous testing to every visitor | in progress |
