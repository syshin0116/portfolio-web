---
name: metadata-filter
description: Filter blog posts by tags, category, and date range using frontmatter metadata. Use when the user asks for posts by topic tag ("AI tagged posts"), by category ("show me Dev posts"), by time period ("posts from 2024", "recent posts"), or any combination. Powerful when combined with other search skills — e.g. filter by category first, then search within results.
---

# Metadata Filter

Structured filtering over blog post frontmatter (YAML headers). Filters by tags, category folder, and date range — not by text content.

## Tool

`metadata_filter(tags, category, date_from, date_to)`

All parameters are optional — specify only the conditions you need.

## Categories

Blog posts are organized by top-level folder:

| Category | Content |
|----------|---------|
| `AI` | Artificial intelligence, LLM, agents, RAG |
| `Dev` | General development, frameworks, infrastructure |
| `Study` | Study notes, certifications, lecture summaries |
| `Projects` | Project records, retrospectives |
| `Tools` | Dev tools, configurations, tips |
| `Events` | Seminars, conferences, hackathons |
| `Others` | Miscellaneous |

## Examples

**Example 1: Category filter**
Input: "Show me AI posts"
→ `metadata_filter(category="AI")`

**Example 2: Tag filter**
Input: "Posts tagged with LangChain or LangGraph"
→ `metadata_filter(tags=["LangChain", "LangGraph"])`

**Example 3: Date range**
Input: "What did I write in 2024?"
→ `metadata_filter(date_from="2024-01-01", date_to="2024-12-31")`

**Example 4: Combined with search**
Input: "AI posts about agents from this year"
→ Step 1: `metadata_filter(category="AI", date_from="2026-01-01")`
→ Step 2: `semantic_search("agent")` within those results

## How It Works

- Parses frontmatter from all blog posts into an in-memory index
- Tag matching: OR condition (any match counts), case-insensitive
- Date format: YYYY-MM-DD
- Results sorted by date descending (newest first)

## When NOT to Use

- Text content search → `semantic_search` or `keyword_search`
- Related post discovery → `graph_traverse`
- Don't know exact tags → use `list_posts` first to see available tags
