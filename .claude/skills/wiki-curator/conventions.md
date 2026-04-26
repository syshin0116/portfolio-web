# wiki-curator: Conventions

Frontmatter, tags, naming, organization, and link rules for `content/wiki/`.

These are invariants (what must be present), not taxonomies (how to categorize). Categorization emerges from observing the actual content.

## Wiki page frontmatter

```yaml
---
title: "Page title"
type: <free-form, see below>
tags:
  - <free-form, see below>
sources:
  - content/AI/2026-04-19-LLM-Text-to-SQL-실전-가이드.md
summary: "1–3 sentence rich summary. Single source for callout rendering, search snippets, OG meta, RSS."
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: wiki-curator
draft: false
---
```

| Field | Rule |
|-------|------|
| `title` | Korean or English. Short and search-friendly. Kebab-case version becomes the filename. |
| `type` | Free-form. Reuse existing values across the wiki when possible (consistency emerges over time). Don't invent parallel terms (e.g., `tool` vs `tooling` vs `utility`). When in doubt, omit. |
| `tags` | 5–10 per page, drawn from multiple dimensions (domain, language, technique, concept, meta). Reuse existing vocabulary first; new tags are OK when nothing fits. |
| `sources` | Required. Every source post that contributed to this page. Append on update; never remove unless the source is deleted. |
| `summary` | Required. 1–3 sentences. The single canonical summary used for callout rendering, index.md descriptions, search snippets. No `## Summary` section in body. |
| `created` | First write. Never change. |
| `updated` | Bump on every edit. |
| `author` | `wiki-curator` for pages this skill produces. |
| `draft` | Default `false`. `true` only when content is incomplete or under review. |

`coverage` (high/medium/low based on source count) is **not** stored — it's derived in `index.md` rendering.

## Page organization

ingest writes every new page to `content/wiki/<slug>.md` at root. Folders are [migrate](./migrate.md)'s domain — restructuring happens in one operation, never piecemeal during ingest.

When migrate introduces folders or changes type/tag vocabulary, its PR justifies the pattern observed.

**Slugs stay stable.** Folder moves don't break wikilinks (resolution is by basename); slug renames do — backlinks must be updated in the same operation.

## Page structure

Every wiki page follows this section template. Mandatory sections must be present even if short.

```markdown
## Key Claims

- Bullets. Each claim cites its source via footnote.
- Source: paraphrase the claim faithfully; do not embellish.[^1]

## Examples / Code

Verbatim quotes from sources. Code blocks must be copy-pasteable.

```python
# from content/AI/2026-04-19-LLM-Text-to-SQL-실전-가이드.md
def example(): ...
```

## Connections

Verified `[[wikilinks]]` to other wiki pages. One-line context per link.

- [[zettelkasten]] — note-linking method that inspired this approach
- [[obsidian-graph-view]] — visual interface for the same idea

## Contradictions

Optional. When sources disagree, list both with attribution. Do not resolve.

## Footnotes

[^1]: content/AI/2026-04-19-LLM-Text-to-SQL-실전-가이드.md
[^2]: content/Tools/2024-07-29-Zettelkasten.md
```

Mandatory sections: `## Key Claims`, `## Footnotes`. Other sections may be omitted if they would be empty (don't leave empty headings).

The Summary content lives in **frontmatter `summary:`** — the web template renders it as a callout above the body. Don't repeat it as a `## Summary` section.

## Tags

Lowercase, hyphenated, no prefixes. 5–10 per page, sampled from multiple dimensions:

| Dimension | Examples |
|-----------|----------|
| Domain | `ai`, `backend`, `frontend`, `infra`, `data`, `devops`, `mobile` |
| Language/framework | `python`, `rust`, `typescript`, `react`, `nextjs` |
| Technique | `bm25`, `edit-distance`, `prompt-engineering`, `caching`, `vector-search` |
| Concept | `knowledge-graph`, `zettelkasten`, `retrieval`, `agent-loop` |
| Meta | `cli`, `library`, `pattern`, `experiment`, `comparison` |

Reuse existing vocabulary first:

```bash
# See current tags + frequency
grep -h "^  - " content/wiki/**/*.md \
  | grep -v "^  - content/" \
  | sed 's/^  - //' | sort | uniq -c | sort -rn
```

Tag drift (parallel synonyms like `note-taking` vs `notes`) is the [migrate](./migrate.md) operation's problem to consolidate. Day-to-day, prefer the most common existing form.

## Filename rules

- Lowercase + hyphens.
- Korean OK (URL-safe via Vercel).
- No date prefix (the `created` frontmatter holds that).
- Matches `title` slugified.

| Title | Filename |
|-------|----------|
| "Zettelkasten Method" | `zettelkasten.md` |
| "PDF 파서 비교" | `pdf-파서-비교.md` |
| "LLM Text-to-SQL Patterns" | `llm-text-to-sql-patterns.md` |

If folders are introduced, append the folder: `concepts/zettelkasten.md`. The slug used in `[[wikilinks]]` is still just `zettelkasten` — Nuartz/Obsidian resolve by filename regardless of folder.

## sources vs wikilinks

| | Where | Targets | Purpose |
|---|---|---|---|
| `sources:` | frontmatter | source paths (`content/AI/...md`) | Provenance |
| `[[wikilink]]` | body | wiki page slugs (`[[zettelkasten]]`) | Conceptual connection |

- `[[wikilinks]]` only point to `content/wiki/` pages. Never wikilink to a source post.
- Targets must exist or be created in the same operation.
- Verify with the script (LLMs hallucinate links):
  ```bash
  bun .claude/skills/wiki-curator/scripts/verify-wikilinks.ts
  ```
- Each link in `## Connections` gets a one-line context.
- Zero links is valid output. Don't pad.

## log.md

Every operation appends one line:

```
## [YYYY-MM-DD HH:MM UTC] <operation> | <summary>
```

Use `date -u +'%Y-%m-%d %H:%M UTC'` to generate the timestamp.

Examples:
```
## [2026-04-25 04:30 UTC] ingest | 5 posts → 3 new pages, 2 page updates
## [2026-04-25 09:00 UTC] lint | 0 broken links, 1 contradiction surfaced in zettelkasten.md
## [2026-04-26 02:00 UTC] reflect | added 7 cross-links across 4 pages
## [2026-05-01 12:00 UTC] migrate | introduced concepts/ folder, moved 8 pages, consolidated 3 tags
```

Append-only. Never edit past entries.

## index.md

Single-file catalog at `content/wiki/index.md`. Auto-generated; rebuilt fresh on every ingest. Never hand-edit.

Format:

```markdown
# Wiki Index

## All pages

| Page | Summary | Type | Tags | Sources | Updated |
|------|---------|------|------|---------|---------|
| [[zettelkasten]] | Note-linking system focused on connection over collection. | concept | pkm, note-taking, zettelkasten | 5 | 2026-04-25 |
| [[clidex]] | Rust CLI for tool discovery with BM25-based search. | tool | cli, rust, ai, bm25 | 2 | 2026-04-25 |

## Sources catalog

| Source | Wiki pages |
|--------|------------|
| content/AI/2026-04-19-LLM-Text-to-SQL-실전-가이드.md | [[text-to-sql]], [[llm-prompting]] |
```

This is the **L1 cache for the LLM** — every ingest reads it first to find candidate pages without reading every wiki file.

## Provenance tags (optional, for ambiguous claims)

When a claim is not directly stated but inferred, mark it inline:

```markdown
- LLM-based wikis prevent context rot[^1]
- This pattern likely scales beyond 1000 pages [inferred]
- Performance characteristics at scale [ambiguous — sources disagree]
```

Three tiers: implicit (no tag = directly extracted), `[inferred]`, `[ambiguous]`. Use sparingly — most claims should be directly extracted.
