# Decisions

One line per decision. Append-only, newest last.

Cheap by design: a bullet here, not an ADR. Promote an entry to a full ADR in
[`docs/adr/`](docs/adr/) only once the decision proves durable.

Format: `YYYY-MM-DD: <decision>, because <reason>. Revisit if <condition>. [→ link]`

---

- 2026-07-11: Capture decisions as one-line entries here by default, not as ADRs, because ADR-0001's own trade-off ("needs the discipline to write") is exactly what happened: `docs/adr/` has held only ADR-0001 since 2026-05-22 and no decision was ever recorded after it. Revisit if entries here also go unwritten. → [docs/adr/0001](docs/adr/0001-record-architecture-decisions.md)
- 2026-07-11: Scope Agent API threads, runs, crons, checkpoints, and persistent stores by authenticated token subject and reserve shared config mutations for an explicit admin scope, because authentication alone does not prevent cross-user resource access. Revisit if authorization moves to database RLS or one immutable admin subject.
- 2026-07-11: Serialize same-thread runs with owner-scoped FIFO queues (in-process locally; Redis lease and heartbeat under ARQ), because LangGraph checkpoints must not execute concurrently or cross owners. Revisit if dispatch moves to a transactional database queue.
- 2026-07-11: Keep external link previews public but bound origin work with request, concurrency, response-size, and cache limits, because hover previews must work without sign-in while arbitrary outbound fetches need abuse containment. Revisit if traffic requires a shared rate-limit store.
- 2026-07-11: Treat the TypeScript wiki verifier as the canonical provenance contract and keep the dependency-free Python verifier behaviorally equivalent, because local skill runs and CI must accept and reject the same sources. Revisit if both environments adopt one shared verifier runtime.
- 2026-07-11: Backfill pre-authorization Agent data at startup only when one Auth.js owner is explicit or unambiguous and legacy writers are stopped, because guessing ownership or racing old writes can expose or hide historical conversations. Revisit if migrations move to an external deployment job.
- 2026-07-26: Start clean in separate US-East Neon projects for the web and agent, enable Neon Auth only for the web project, and retain the mixed Singapore project as a rollback source, because agent checkpoint growth must not share the web authentication failure domain and the sole existing user can re-authenticate without a schema migration. Revisit if Neon removes per-project free quotas or cross-project operation becomes material overhead. → [runbook](docs/runbooks/gcp-neon-foundation.md)
