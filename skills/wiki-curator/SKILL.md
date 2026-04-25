---
name: wiki-curator
description: Curates the knowledge wiki at content/wiki/ by ingesting source material from blog posts, maintaining cross-links, and ensuring quality. Use when the user asks to update the wiki, ingest new posts, lint wiki health, find connections between pages, or perform any maintenance on content/wiki/.
---

# wiki-curator

Curates the knowledge layer at `content/wiki/`. Treats existing blog posts (`content/AI/`, `content/Dev/`, `content/Tools/`, etc.) as immutable source material and produces a polished, cross-linked wiki on top.

## When to use

Trigger this skill for any of these:

- "Ingest the latest N posts" → run [ingest](./ingest.md)
- "Process this specific post: ..." → run [ingest](./ingest.md) with a single source
- "Lint the wiki" / "check broken links" / "find orphan pages" → run [lint](./lint.md)
- "Find connections" / "cross-link related pages" → run [reflect](./reflect.md)
- "Backfill all posts" → batch [ingest](./ingest.md) with throttling

For frontmatter, tags, naming, and source/wikilink rules see [conventions.md](./conventions.md).

## Hard rules (apply to every operation)

These are non-negotiable. They protect the wiki from corruption and drift.

1. **`raw/` is immutable.** "Raw" here = every `.md` outside `content/wiki/`. Never modify a blog post, even to fix a typo. If something needs to change in the source, surface it to the user.
2. **Extract, don't invent.** Every claim in a wiki page must trace back to a verbatim span in a source. If it isn't in the source, it doesn't go in the wiki.
3. **Preserve and extend, never discard.** When updating an existing wiki page, add to or refine — do not rewrite. If you find yourself wanting to change >30% of a page, stop and ask the user.
4. **No silent overwrites on conflict.** When a new source contradicts an existing claim, append to a `## Contradictions` section. Do not pick a winner.
5. **Cite via `sources` frontmatter.** Every wiki page must list every source path under `sources:`.
6. **Cross-link only verified targets.** Never write `[[wikilink]]` to a page that doesn't exist or isn't being created in this same operation. Run a final pass to verify every link resolves.
7. **No forced links.** Zero links is a valid output. Don't pad with weak associations.
8. **No preamble.** Wiki page content starts with a heading or paragraph — never with "Here is a summary…", "I've created…", or similar chat-style intros.

## Output discipline

- Wiki pages must be substantially richer than a chat answer — they're persistent artifacts.
- Use mermaid diagrams for any structured relationship (>2 connected entities).
- Use tables for any 3+ items with attributes.
- Code/commands quoted verbatim from source (never paraphrase code).

## Workflow boundaries

- This skill writes only to `content/wiki/`.
- Never touches `web/`, `agent/`, `vercel.json`, package files, or any infrastructure.
- Logs every operation as a one-liner appended to `content/wiki/log.md` (date-prefixed).

## Operation files

- [ingest.md](./ingest.md) — convert source(s) to wiki page(s)
- [lint.md](./lint.md) — health check
- [reflect.md](./reflect.md) — cross-source connection pass
- [conventions.md](./conventions.md) — frontmatter, tags, naming, sources/wikilink
