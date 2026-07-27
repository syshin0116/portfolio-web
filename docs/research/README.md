---
title: "Research notes"
description: >
  Index of investigations that feed decisions. Each one is a snapshot, not a
  commitment.
when_to_read: >
  When looking for the comparison behind an ADR, or before starting a new
  investigation that may already exist here.
tags: [index, research]
status: stable
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [../adr/README.md, template.md]
template: index
---

# Research notes

Investigations that feed a decision. **None of these is a decision.** Once the ADR
they feed is accepted, that ADR is canonical and the research file becomes a
historical snapshot - it keeps its original claims and gets a note at the top saying
so, rather than being edited to match what turned out to be true.

Every non-obvious claim carries a URL or a `file:line`. A research note whose claims
cannot be re-checked is worth less than no note, because it launders a guess into
something that looks verified.

New note: copy [`template.md`](template.md).

## Index

| Note | Feeds | Status |
|---|---|---|
| [aegra-native-stack.md](aegra-native-stack.md) | [ADR-0004](../adr/0004-adopt-aegra.md), [ADR-0005](../adr/0005-adopt-assistant-ui.md) | draft |
| [public-exposure.md](public-exposure.md) | [ADR-0006](../adr/0006-public-anonymous-chat-access.md) | draft |
| [restack-options.md](restack-options.md) | superseded - historical snapshot | draft |
