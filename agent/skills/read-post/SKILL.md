---
name: read-post
description: Read the full markdown content of a specific blog post. Use when the user wants detailed content from a known post, needs to quote or summarize an article, or asks "show me the full post", "read this article", "what does that post say?". Requires a file path — find it first with search or list_posts.
---

# Read Post

Returns the complete markdown content of a specific blog post, including a metadata header (title, date, category, tags) and the full body text.

## Tool

`read_post(path)`

## Examples

**Example 1: Read search result**
Input: "Show me the Agent Architecture post in detail"
→ `read_post(path="AI/2025-06-04-Agent Architecture Comparison.md")`

**Example 2: Summarize a post**
Input: "Summarize the LangGraph seminar post"
→ First: `keyword_search("LangGraph 세미나")` to find the path
→ Then: `read_post(path="the/found/path.md")`

## Output Format

```markdown
# Post Title
Date: 2025-06-04
Category: AI
Tags: LLM, agent, architecture
---
(full markdown body)
```

## Important Notes

- **Path required**: Relative path format (e.g. `AI/2025-06-04-Title.md`). Search first if unknown.
- **Token cost**: Long posts consume thousands of tokens. Only use when you genuinely need the full content — search result snippets may suffice for quick answers.
- **One at a time**: If multiple posts are needed, start with the most relevant one.

## Typical Workflow

1. Find posts via `semantic_search` / `keyword_search` / `list_posts`
2. Check if search result snippets already answer the question
3. If more detail needed, `read_post` for the full content
4. Quote, summarize, or analyze from the source text
