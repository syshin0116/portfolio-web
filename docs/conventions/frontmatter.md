---
title: "Docs frontmatter convention"
description: >
  The YAML frontmatter every file under docs/ carries, and the rules for each field.
when_to_read: >
  Before adding a document to docs/, renaming or moving one, or changing the
  frontmatter schema itself.
tags: [convention, documentation, frontmatter]
status: stable
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [../README.md, ../adr/template.md, ../research/template.md]
template: convention
---

# Docs frontmatter convention

## TL;DR

Every `docs/**/*.md` carries the frontmatter below. The field that earns its keep
most is **`when_to_read`**: it is what lets a human or an agent decide whether to
open the file without reading it first.

## Schema

```yaml
---
title: "<matches the H1>"
description: >              # 1-2 sentences: what this document is
  ...
when_to_read: >             # when someone should open this file
  ...
tags: [<tag>, ...]          # at least one
status: <see below>
updated: "YYYY-MM-DD"       # last meaningful revision
owners: ["@syshin0116"]
refs: [<relative path>, ...]   # related docs, same paths as the body links
template: <enum below>
---
```

ADRs carry three more fields:

```yaml
date: "YYYY-MM-DD"          # decision date - historical fact, never edited
deciders: ["@syshin0116"]
supersedes:                 # e.g. 0004-agent-runtime-aegra.md
superseded_by:
```

## Field rules

| Field | Required | Notes |
|---|---|---|
| `title` | yes | Identical to the body H1 |
| `description` | yes | 1-2 sentences, no marketing |
| `when_to_read` | yes | The navigation field. Write it for a reader who has not seen the doc |
| `tags` | yes | At least one |
| `status` | yes | See lifecycle below |
| `updated` | yes | Bump on meaningful revision. `git log -1 --format=%as <file>` is the fallback truth |
| `owners` | yes | `["@handle"]` |
| `refs` | no | **Relative paths**, not ids. Keep in sync with the body links |
| `template` | yes | Enum below - decides which body skeleton applies |
| `date` | ADR only | Immutable |
| `deciders` | ADR only | Who actually decided |
| `supersedes` / `superseded_by` | ADR only | Relative filename |

## `status` lifecycle

- **Regular docs**: `draft` (being written) → `stable` (settled) → `deprecated`.
  `on_hold` for work parked deliberately.
- **ADRs**: `proposed` → `accepted` → (`superseded` | `deprecated` | `rejected`).

An ADR's `status` answers *"is this decision still in force?"* - not *"is the work
done?"*. Those are separate axes and conflating them misleads the next reader. Track
delivery in the ADR's **Follow-ups** checklist or an issue, never by flipping
`status` to `accepted` because the code shipped.

## `template` enum

| Value | Used for | Lives in |
|---|---|---|
| `index` | README / navigation | anywhere |
| `adr` | A decision record | `docs/adr/` |
| `research` | Investigation feeding a decision. **Not a decision** | `docs/research/` |
| `plan` | Sequenced execution plan, decomposed into work packets | `docs/plans/` |
| `convention` | A rule about how we write code or docs | `docs/conventions/` |
| `spec` | Design of a specific mechanism | `docs/` |

## Deliberately not adopted

The upstream schema this borrows from ([braincrew / skax-aipmo][ref]) also carries
`covers[]` (document → code binding) and `doc_class`. Both are dropped here:
`covers[]` only stays true if a doc-sync automation maintains it, and this repo has
none, so hand-maintaining it would produce a field that quietly lies. `doc_class`
exists mainly to gate `covers[]`. Revisit both if a doc-sync step ever lands in CI.

[ref]: https://github.com/brain-crew

## Example

```yaml
---
title: "ADR-0007: Blog search index is built at deploy time"
description: >
  Build the search index during the deploy step rather than at first request,
  because a cold agent should not pay indexing latency on a user's first message.
when_to_read: >
  Before moving index construction, or when startup time regresses.
tags: [adr, agent, search, deploy]
status: accepted
date: "2026-07-26"
deciders: ["@syshin0116"]
supersedes:
superseded_by:
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [../research/index-build-timing.md]
template: adr
---
```
