---
name: list-posts
description: Browse blog post listings by date and category. Use when the user asks "what posts are there?", "show me recent posts", "what's in the AI category?", "give me an overview of the blog". Good starting point before detailed search — helps understand what content is available.
---

# List Posts

Returns a date-sorted list of blog posts with title, date, tags, and file path. Optionally filtered by category.

## Tool

`list_posts(category, limit)`

## Examples

**Example 1: Recent posts**
Input: "What have you written recently?"
→ `list_posts(limit=20)`

**Example 2: Category browsing**
Input: "Show me project posts"
→ `list_posts(category="Projects")`

**Example 3: Full category**
Input: "List all AI posts"
→ `list_posts(category="AI", limit=50)`

## Output Format

Each entry includes the file path (usable directly in `read_post` or `graph_traverse`):
```
- [AI/2025-06-04-Agent Architecture.md] "LLM Agent Architecture Comparison" (2025-06-04) AI, LLM, agent
```

## Typical Workflow

1. `list_posts` to see what's available
2. Pick an interesting post's path
3. `read_post` for full content, or `graph_traverse` for related posts

## When NOT to Use

- Searching for specific content → `semantic_search` or `keyword_search`
- Complex tag + date filtering → `metadata_filter` is more precise
