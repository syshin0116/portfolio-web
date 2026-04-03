---
name: graph-traverse
description: Discover related blog posts by following [[wikilink]] connections. Use when the user asks "what else is related to this post?", "show me connected topics", "recommend similar articles", or wants to explore the knowledge network from a known starting point. Especially effective after finding a post via search — expand outward to discover related content the author explicitly linked.
---

# Graph Traverse

Builds a bidirectional graph from `[[wikilink]]` references across all blog posts, then performs BFS (breadth-first search) from a starting post to find connected content.

This skill surfaces a different kind of relevance than text search — it follows connections the author explicitly created, revealing the blog's knowledge network structure.

## Tool

`graph_traverse(slug, depth)`

## Examples

**Example 1: Related posts**
Input: "What's related to the Agent Architecture post?"
→ `graph_traverse(slug="AI/2025-06-04-Agent Architecture Comparison.md", depth=1)`

**Example 2: Search by title**
Input: "Posts connected to MCP"
→ `graph_traverse(slug="MCP(Model Context Protocol)", depth=1)`

**Example 3: Wider exploration**
Input: "Everything connected to LangGraph within 2 hops"
→ `graph_traverse(slug="LangGraph", depth=2)`

## How It Works

- Extracts `[[Target]]` and `[[Target|Alias]]` patterns from all posts
- Builds bidirectional adjacency graph (A→B link means B→A is also traversable)
- Slug resolves via: exact file path → title match → filename stem match
- Score: closer = higher (depth 1 = 0.5, depth 2 = 0.33, depth 3 = 0.25)

## Typical Workflow

1. Find a starting post via `semantic_search`, `keyword_search`, or `list_posts`
2. Use `graph_traverse` to expand into related posts
3. Use `read_post` on interesting discoveries

You need a starting point (slug). If you don't have one, search first.

## When NOT to Use

- No starting point known → search first with other skills
- Not all posts have wikilinks — posts without links return empty results
- Text-based search → `keyword_search` or `semantic_search`
