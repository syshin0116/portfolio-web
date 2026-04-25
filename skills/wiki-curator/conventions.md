# wiki-curator: Conventions

Frontmatter, tags, naming, and link rules for `content/wiki/` pages. All operations in this skill must comply.

## Wiki page frontmatter

```yaml
---
title: "Page title"
type: concept | pattern | tool | reference
tags:
  - <from existing vocabulary>
sources:
  - content/AI/2026-04-19-LLM-Text-to-SQL-실전-가이드.md
  - content/Tools/2024-07-29-Zettelkasten.md
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: wiki-curator
draft: false
coverage: high | medium | low
---
```

| Field | Rule |
|-------|------|
| `title` | Korean or English. Short and search-friendly. Kebab-case version becomes the filename. |
| `type` | One of `concept`, `pattern`, `tool`, `reference`. Pick the closest. |
| `tags` | 1–5. Reuse existing vocabulary first. See [Tag vocabulary](#tag-vocabulary). |
| `sources` | Required. Every source post that contributed to this page. Add as the page is updated; never remove unless the source is deleted. |
| `created` | First write. Never change. |
| `updated` | Bump on every edit. |
| `author` | Always `wiki-curator` for pages this skill produces. |
| `draft` | Default `false`. Set `true` only when content is incomplete or under review. |
| `coverage` | `high` (5+ sources), `medium` (2–4), `low` (1). Compute from `sources` length. |

## Page structure

Every wiki page follows this section template. Sections may be empty but the headings stay.

```markdown
## Summary

2–4 sentences. Synthesize, don't quote.

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

Sections that are empty for a given page can be omitted, except `## Summary` and `## Key Claims` which are mandatory.

## Tag vocabulary

Lowercase, hyphenated, no prefixes. Reuse existing tags before creating new ones. Use `grep -r "^- " content/wiki/*.md | grep -i <tag>` to check.

**Domains**: `ai`, `backend`, `frontend`, `infra`, `data`, `devops`, `mobile`

**LLM/AI**: `llm`, `rag`, `langchain`, `langgraph`, `prompt-engineering`, `embeddings`, `vector-db`

**Tooling**: `obsidian`, `note-taking`, `pkm`, `zettelkasten`, `claude-code`

**Languages/Frameworks**: `python`, `typescript`, `nextjs`, `react`, `tailwind`

**Infra**: `docker`, `kubernetes`, `vercel`, `git`, `github`

**Topical**: `pdf-parser`, `text-to-sql`, `semantic-search`

When a new tag is genuinely needed: prefer narrowing an existing tag over inventing a parallel one. (e.g., `pdf-parsing` not `document-extraction-pdf-only`.)

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

## sources vs wikilinks

Two different link systems. Never mix them.

| | Where | Targets | Purpose |
|---|---|---|---|
| `sources:` | frontmatter | source paths (`content/AI/...md`) | Provenance, update propagation |
| `[[wikilink]]` | body | wiki page slugs (`[[zettelkasten]]`) | Conceptual connection |

**Rules:**

- `[[wikilinks]]` only point to `content/wiki/` pages. Never wikilink to a source post in the body.
- Every body wikilink must resolve. Run a verification pass before commit:
  ```bash
  grep -roE '\[\[[^]]+\]\]' content/wiki/ | sort -u
  # cross-check against actual wiki filenames
  ```
- Targets must already exist or be created in the same operation. No forward references to imagined pages.
- Use one-line context next to each link in `## Connections` so the reader knows why it's there.

## log.md

Every operation appends one line:

```
## [YYYY-MM-DD HH:MM] <operation> | <summary>
```

Examples:
```
## [2026-04-25 04:30] ingest | 5 posts → 3 new pages, 2 page updates
## [2026-04-25 09:00] lint | 0 broken links, 1 contradiction surfaced in zettelkasten.md
## [2026-04-26 02:00] reflect | added 7 cross-links across 4 pages
```

Append-only. Never edit past entries.

## index.md

Single-file catalog at `content/wiki/index.md`. Updated on every ingest.

```markdown
# Wiki Index

## Pages by type

### Concepts
- [[zettelkasten]] — note-linking method (5 sources)
- [[knowledge-graph]] — concept (3 sources)

### Patterns
- [[rag-pattern]] — retrieval-augmented generation (8 sources)

### Tools
- [[obsidian]] — markdown editor (12 sources)

## Sources catalog

| Source | Wiki pages |
|--------|------------|
| content/AI/2026-04-19-LLM-Text-to-SQL-실전-가이드.md | [[text-to-sql]], [[llm-prompting]] |
```

This file is rebuilt from scratch each ingest — never hand-edit.

## Provenance tags (optional, for ambiguous claims)

When a claim is not directly stated but inferred, mark it inline:

```markdown
- LLM-based wikis prevent context rot[^1]
- This pattern likely scales beyond 1000 pages [inferred]
- Performance characteristics at scale [ambiguous — sources disagree]
```

Three tiers: implicit (no tag = directly extracted), `[inferred]`, `[ambiguous]`. Use sparingly — most claims should be directly extracted.
