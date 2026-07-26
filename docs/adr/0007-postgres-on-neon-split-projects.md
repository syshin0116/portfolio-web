---
title: "ADR-0007: Postgres stays on Neon, split into two projects"
description: >
  Keep Neon rather than moving to Supabase, and separate the agent's database from
  the Auth.js database before the chatbot goes public.
when_to_read: >
  Before changing the database provider, creating a Neon project, choosing a
  region, or wiring a connection pooler.
tags: [adr, database, postgres, neon, supabase, cost, deploy]
status: accepted
date: "2026-07-26"
deciders: ["@syshin0116"]
supersedes:
superseded_by:
updated: "2026-07-26"
owners: ["@syshin0116"]
refs: [0004-adopt-aegra.md, 0006-public-anonymous-chat-access.md, ../plans/rag-restack.md]
template: adr
---

# ADR-0007: Postgres stays on Neon, split into two projects

> **status: accepted.** The provider decision is settled. The region move and the split
> are scheduled for plan phase P2 (the Cloud Run deploy) and must land before P6 (going
> public).

## Context

The question raised was whether to adopt Supabase, on the worry that it "gets expensive
later", and whether Neon plus Auth.js removes the need for it.

Both premises were wrong. **The project is already on Neon** - verified live at
`ep-flat-sky-a1k7fna6.ap-southeast-1.aws.neon.tech`, Postgres 17.10, 11 MB, shared by
`web/` and `agent/`. **Supabase is not used at all**: authentication is Auth.js v5 with
`@auth/pg-adapter` against that same Neon database (`web/lib/auth.ts:4-8`). The only
Supabase traces in the repo are a skills list on the About page and some stale branches.

So the real question is whether Neon remains right, given that the chatbot is about to be
opened to anonymous visitors and the agent is moving to Cloud Run.

Measured, not estimated - a throwaway Postgres ran this repo's actual graph against a real
`AsyncPostgresSaver`:

| Conversation | Logical | Checkpoints |
|---|---|---|
| light (3 searches) | 43.6 KB | 15 |
| typical (8 searches + 1 post) | 97.3 KB | 30 |
| heavy (12 searches, 4 posts) | 159.2 KB | 42 |

Physical is ~1.3x logical. That matches the live database independently: 25 threads and 394
checkpoints occupy ~3.1 MB, i.e. ~127 KB per thread. **0.5 GB therefore holds roughly
4,200 typical conversations** - a number anonymous traffic can reach.

## Considered options

| Option | Free tier | First paid tier | Verdict |
|---|---|---|---|
| A. Neon (current) | 0.5 GB/project, 100 CU-hours/month, autosuspend at 5 min | **$0 floor**, usage-based. ~$3.50/mo with scale-to-zero, ~$19.70/mo pinned awake 24/7 | **Chosen** |
| B. Supabase | 500 MB, **pauses after 7 days of inactivity**, manual unpause | **$25/mo flat from day one** | Rejected |
| C. Self-hosted on a GCP e2-micro Always Free VM | 30 GB disk - removes the storage cliff entirely | ~$6-8/mo beyond Always Free | Rejected |

The Supabase fear was inverted. It does not get expensive later - $25/mo covers this
workload essentially forever. The problem is that its **floor** is $25 while Neon's is $0,
and Supabase repays that $25 through Auth, Storage, Realtime, and Edge Functions, **none of
which this project uses**. Crossover: Neon only exceeds $25 once sustained compute passes
~0.32 CU; at the 0.25 CU floor pinned awake around the clock Neon is still ~$19.70.

The 7-day inactivity pause is disqualifying on its own for a public chatbot - it is a
silent outage requiring a manual click.

Option C is free in dollars and expensive in the currency actually lacking: 1 GB RAM must
host Postgres with no headroom, there is no restore button, and backups, patching, and
monitoring land on the one person also writing the blog.

Ruled out on facts rather than taste: Tembo shut down managed Postgres in May 2025 with
~1 month notice; Xata deleted its free tier; Koyeb was acquired and cut to 5 compute-hours;
Render's free Postgres self-deletes after 44 days; CockroachDB is Postgres-wire-compatible
rather than Postgres, which all three schema owners here assume; Prisma Postgres bills per
operation, which is hostile to a checkpointer making many small writes per turn.

## Decision

**Stay on Neon.** Create **two** free projects, split the agent's database from the
Auth.js database, and move both to a US region co-located with Cloud Run.

The split is **not** about storage - the Auth.js tables are kilobytes. It is about blast
radius, and the coupling turns out to be almost nothing: no foreign key, no join, and
exactly one runtime query against the Auth.js schema in the entire agent
(`legacy_migration.py:310-312`), on a one-shot startup path that
[ADR-0004](0004-adopt-aegra.md) deletes outright. The token subject is an Auth.js user id
only by convention, and nothing ever dereferences it.

**The split costs zero code changes.** Both sides already read the same env var name, so
"split" means giving Vercel one value and Cloud Run another.

**Connections: use the direct endpoint, not `-pooler`.** The current URLs already have no
`-pooler` infix, which is correct. `checkpointer.setup()` issues `CREATE INDEX
CONCURRENTLY`, which Neon documents as direct-connection-only, and psycopg3 prepared
statements conflict with a transaction-mode pooler.

## Consequences

**Positive**

- $0 today and a $0 floor tomorrow, versus $25/mo from day one.
- Anonymous chat traffic filling the agent's storage cap can no longer break sign-in.
- Unreviewed boot-time DDL stops running against the credential store. (Adopting Aegra
  makes this milder anyway - Alembic replaces it.)
- The agent database can sit next to Cloud Run while auth stays near Vercel. Neon project
  regions are **fixed at creation**, so this is only available now.

**Trade-offs**

- Two projects to manage, against an unverified free-plan project limit.
- A future "delete this user and all their threads" operation loses the single transaction.
  Irrelevant at one real user.
- The current Singapore project has to be recreated rather than moved.

**Follow-ups**

- [ ] Verify Neon's free-plan project-count limit before assuming two fit.
- [ ] Create both projects in a US region and set the two `DATABASE_URL` values (P3).
- [ ] **Ship checkpoint GC before going public.** There is no GC anywhere in this repo
      today, deleting a thread does not delete its checkpoints, and **Neon's storage cliff
      fails `DELETE`s as well as `INSERT`s** - so filling the cap means being unable to
      delete your way out.
- [ ] Turn the Aegra connection-pool knobs down; it opens up to ~50 connections by default.
- [ ] Record the region choice - it interacts with the Cloud Run region decision still open
      in the plan.

## Revisit when

- Sustained compute approaches 0.32 CU, where Supabase Pro's flat $25 starts to win.
- Storage approaches 0.5 GB despite GC - the signal to store less in checkpoint state, not
  to change provider.
- Neon changes its free tier or is acquired. It is the kind of dependency worth re-checking
  yearly; several competitors cut or killed free tiers within the last 18 months.

## Changelog

- 2026-07-26: created.
