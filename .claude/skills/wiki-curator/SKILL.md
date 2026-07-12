---
name: wiki-curator
description: Curates the knowledge wiki at content/wiki/ by ingesting source material from blog posts, maintaining cross-links, and ensuring quality. Use when the user asks to update the wiki, ingest new posts, lint wiki health, find connections between pages, or perform any maintenance on content/wiki/.
---

# wiki-curator

Curates the knowledge layer at `content/wiki/`. Treats every `.md` outside `content/wiki/` as immutable source material.

## Operations

| Op | Purpose | Trigger phrases |
|----|---------|-----------------|
| [ingest](./ingest.md) | source post → wiki page | "ingest the latest N posts", "process this post" |
| [lint](./lint.md) | health report (read-only) | "lint the wiki", "check broken links", "find orphans" |
| [reflect](./reflect.md) | add cross-links across existing pages | "find connections", "cross-link related pages" |
| [migrate](./migrate.md) | restructure folders / type / tag vocabulary | "reorganize", "consolidate tags", "introduce folders" |

ingest and migrate have conflicting goals (preserve vs. restructure). Don't mix them in one routine session.

For frontmatter, naming, tags, summary, sources/wikilink - see [conventions.md](./conventions.md).

## Hard rules

These are the only rules every operation must enforce. Operation-specific rules live in their own files.

1. **`raw/` is immutable.** Every `.md` outside `content/wiki/` is read-only. If something looks wrong in a source, surface it to the user.
2. **Extract, don't invent.** Every claim in a wiki page must trace to a verbatim span in a cited source.
3. **Preserve and extend.** When updating an existing page, refine - don't rewrite. >30% body change = stop and escalate.

## Verify gate

Every operation ends with this verification gate before commit/push:

```bash
bun .claude/skills/wiki-curator/scripts/verify.ts
```

**Behavior on exit code:**
- **0** - all checks pass. Proceed to commit + push + PR.
- **1** - at least one check failed. Read the per-check failures from stdout, fix them in place (Edit tool), re-run verify. Maximum **3 retry attempts**.
- After 3 failed retries - abort. Do not commit. Surface the remaining failures to the user in the routine's final message.

The script enforces (deterministically - don't try to verify by eye):
- wikilinks resolve by basename
- required frontmatter fields present (`title`, `type`, `tags`, `sources`, `summary`, `created`, `updated`, `author`, `draft`)
- no legacy `coverage:` field
- body has no `## Summary` section (lives in frontmatter)
- body has no `> [!summary]` callout (legacy)
- body has mandatory sections (`## Key Claims`, `## Footnotes`)
- every `sources:` entry is either a valid HTTPS URL or an existing repo-local file
- summary length 1–500 chars
- tags non-empty

## Gotchas

Non-obvious things that bite:

- **Routine pushes are restricted to `claude/*` branches by default.** Open a PR to `main`; don't try to push to `main` directly. Settings → "Allow unrestricted branch pushes" lifts this if needed.
- **Wikilinks resolve by basename.** `[[zettelkasten]]` finds `concepts/zettelkasten.md` and `zettelkasten.md` equally. Folder moves don't break links; **slug renames do** - backlinks must be migrated atomically.
- **Run `verify.ts` after every change, not just at the end.** It catches wikilink hallucinations, missing required frontmatter, leftover legacy fields, and body sections that should have moved. See [Verify gate](#verify-gate) below.
- **Summary lives in frontmatter, not body.** Web template renders `frontmatter.summary` as a callout. Don't author a `## Summary` section; it would render twice.
- **`stat -f '%m %N'` is macOS; use `stat -c '%Y %n'` on Linux.** ingest's "recent N" command differs by OS.
- **`gh pr create` requires the Claude GitHub App installed on the repo with write permission.** First-time setup, not the routine's job to fix.
- **Body `[!summary]` callouts are legacy** (from before frontmatter migration). Don't recreate them.

## Mirrored skill trees

`.claude/skills/wiki-curator/` and `.agents/skills/wiki-curator/` are byte-for-byte mirrors. Commands use the `.claude/` path because the existing routine invokes it. Apply every skill-contract change to both trees and verify with:

```bash
diff -ru .agents/skills/wiki-curator .claude/skills/wiki-curator
```

## Output style

- Wiki pages are persistent artifacts, not chat replies. Substantive.
- Use mermaid diagrams when 3+ entities have explicit relations. Tables when 3+ items have attributes.
- Code/commands quoted verbatim from source.
- No chat preamble ("Here's…", "I've created…").
