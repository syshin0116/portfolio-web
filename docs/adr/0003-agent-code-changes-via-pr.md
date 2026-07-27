---
title: "ADR-0003: Agent changes to web/ and agent/ go through a branch and PR"
description: >
  Replace ADR-0002's blanket ban on agents touching web/ and agent/ with a
  branch-and-PR requirement, so the existing CI gate on those paths actually runs
  against agent-authored work.
when_to_read: >
  Before letting an agent write to web/ or agent/, or when changing the repo's
  hard rules in CLAUDE.md / AGENTS.md.
tags: [adr, process, agents, ci, governance]
status: accepted
date: "2026-07-26"
deciders: ["@syshin0116"]
supersedes:
superseded_by:
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [0002-content-immutable-source-curated-wiki.md, ../../CLAUDE.md, ../../AGENTS.md]
template: adr
---

# ADR-0003: Agent changes to web/ and agent/ go through a branch and PR

> **status: accepted.** Amends the third decision bullet of
> [ADR-0002](0002-content-immutable-source-curated-wiki.md). **The content rules in
> ADR-0002 are untouched** - source posts outside `content/wiki/` stay immutable.

## Context

[ADR-0002](0002-content-immutable-source-curated-wiki.md) declared `web/`, `agent/`,
and build config "human territory; agents do not modify them", and the same rule is
hard-coded in [`CLAUDE.md`](../../CLAUDE.md) and [`AGENTS.md`](../../AGENTS.md) rule 2.
That was the right call when agent work here was wiki curation: an agent had no
reason to touch application code, and the blanket ban cost nothing.

It now costs something. The owner is directing a substantial restack of exactly those
directories - agent runtime, chat UI, and a first deployment - and the rule as written
admits only two outcomes: the agent silently violates a hard rule, or it produces
diffs for a human to retype. Neither is what the rule was for.

The rule's actual purpose was to stop hard-to-review changes landing unnoticed in
code that the wiki tooling had no business editing. That purpose is better served by
a gate than by a ban, and **the gate already exists**:
[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) runs on every pull
request touching `web/**`, `agent/**`, or `content/**`. Under a blanket ban, no
agent-authored change ever reaches that CI run - the ban does not make agent work
safe, it makes it invisible.

## Considered options

| Option | Pros | Cons |
|---|---|---|
| A. Keep the ban; agent proposes diffs, human applies | maximum control; nothing lands unreviewed | human retypes machine output, which is where transcription errors come from; CI still never sees the change before it is applied |
| B. Lift the ban; agents commit to `main` like any other change | fastest | no review surface, no CI gate before the fact, `main` stops being trustworthy |
| C. Branch + PR only, never a direct commit to `main` | CI runs before merge; one reviewable surface; `main` stays deployable; revert is one click | review burden lands on one person at PR time; a rubber-stamped PR still merges |

## Decision

Adopt **C**. Agents may write to `web/` and `agent/`, but **only on a feature branch,
and the change reaches `main` only through a pull request**. No direct commits to
`main`, and no merging a PR whose CI is red.

The load-bearing reason: this is the only option under which the CI that already
guards these paths actually runs against agent-authored code before it lands.

Build and deploy configuration is included - it is the same code by a different name,
and a broken deploy config is not less reviewable than a broken module.

## Consequences

**Positive**

- Agent work on the restack becomes possible at all, which is the point.
- Every agent-authored change hits `ci.yml` before merge instead of after.
- The diff is reviewable in one place, with history, instead of arriving as chat
  output to be applied by hand.
- `main` stays deployable, so "get it deployed" and "restack it" can proceed on
  separate branches without blocking each other.

**Trade-offs**

- Review load concentrates on one person at PR time. The ban distributed that cost by
  making the human write the code; this decision does not remove the cost, it moves
  it. A rubber-stamped PR is now the failure mode, and it is a quieter one than the
  old rule's.
- Parallel agent branches touching the same files will conflict. Partly mitigated for
  the append-only decision log by the `merge=union` driver in
  [`.gitattributes`](../../.gitattributes); not mitigated for source files, which is
  a sequencing problem for the execution plan to solve.

**Follow-ups**

- [ ] Update `CLAUDE.md` and `AGENTS.md` rule 2 from "never modify" to "branch + PR,
      never a direct commit to `main`".
- [ ] Add a one-line `DECISIONS.md` entry pointing here.
- [ ] Decide whether to enforce this with a GitHub branch protection rule on `main`
      rather than by convention alone.

## Revisit when

- A PR merges with red CI, or a regression lands that review should have caught -
  the gate is nominal and needs enforcement, not convention.
- Review latency becomes the bottleneck for the restack, i.e. branches sit unmerged
  long enough to conflict with each other.
- Agent work in these directories stops entirely, in which case the simpler ban costs
  nothing again and should come back.

## Changelog

- 2026-07-26: created. Amends ADR-0002's third decision bullet.
