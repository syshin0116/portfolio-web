---
name: blog-search
description: Search strategy for blog content — when to use keyword, BM25, metadata, or wikilink graph search
---

# Blog Search Skill

## Available Tools

| Tool | Engine | Best For |
|------|--------|----------|
| `keyword_search` | ripgrep (regex) | Exact terms, code snippets, error messages, specific names |
| `semantic_search` | BM25 + kiwipiepy | Natural language queries, Korean text, topic exploration |
| `metadata_filter` | Frontmatter index | Filtering by tags, category, date range |
| `graph_traverse` | Wikilink graph | Finding related/connected posts from a known post |
| `list_posts` | Content loader | Browsing recent posts, category overview |
| `read_post` | File reader | Reading full content of a specific post |

## Categories

Posts are organized by folder: `AI`, `Dev`, `Study`, `Projects`, `Tools`, `Events`, `Others`

## Search Strategy

1. **Simple factual queries** → `semantic_search` first, then `read_post` for details
2. **Exact keyword/code** → `keyword_search` (ripgrep is faster and more precise for exact matches)
3. **Korean natural language** → `semantic_search` (BM25 with morphological analysis)
4. **By tag or date** → `metadata_filter` first, then search within results
5. **"What else is related to X?"** → `graph_traverse` from a known post
6. **Browsing/overview** → `list_posts` to see what's available
7. **Comprehensive research** → Combine: `semantic_search` + `keyword_search` + `graph_traverse`

## Tips

- Korean queries work best with `semantic_search` (kiwipiepy tokenization)
- `keyword_search` supports regex: `"LangGraph|LangChain"` matches either
- Combine `metadata_filter(tags=["AI"])` + `semantic_search("agent architecture")` for scoped search
- `graph_traverse` requires a known post path — use `list_posts` or search first to find one
