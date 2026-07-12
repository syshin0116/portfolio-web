# Decisions

One line per decision. Append-only, newest last.

Cheap by design: a bullet here, not an ADR. Promote an entry to a full ADR in
[`docs/adr/`](docs/adr/) only once the decision proves durable.

Format: `YYYY-MM-DD: <decision>, because <reason>. Revisit if <condition>. [→ link]`

---

- 2026-07-11: Capture decisions as one-line entries here by default, not as ADRs, because ADR-0001's own trade-off ("needs the discipline to write") is exactly what happened: `docs/adr/` has held only ADR-0001 since 2026-05-22 and no decision was ever recorded after it. Revisit if entries here also go unwritten. → [docs/adr/0001](docs/adr/0001-record-architecture-decisions.md)
