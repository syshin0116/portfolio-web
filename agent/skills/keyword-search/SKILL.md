---
name: keyword-search
description: Fast keyword and regex search over blog content using ripgrep. Use this skill whenever the user mentions a specific technology name, library, code snippet, error message, or exact phrase — e.g. "LangGraph posts", "FastAPI examples", "import torch", "ChromaDB setup". Faster than BM25 for exact matches. Supports regex patterns like "React|Vue" to match multiple terms.
---

# Keyword Search

Searches the blog content directory using ripgrep (`rg`) subprocess for fast, exact keyword and regex matching. Results are scored by match count per file.

## Tool

`keyword_search(query, top_k)`

## When This Skill Shines

This skill is most effective when the user knows **a specific name or keyword** they're looking for. For broad topic exploration ("tell me about agents"), prefer `semantic_search` (BM25). For exact terms ("LangGraph"), this is faster and more precise.

Combine with `semantic_search` for best coverage — keyword catches exact hits that BM25 might rank lower, while BM25 catches semantically related content that keyword misses.

## Examples

**Example 1: Technology name**
Input: "Any posts about LangGraph?"
→ `keyword_search(query="LangGraph", top_k=10)`

**Example 2: Regex for multiple terms**
Input: "Posts mentioning React or Vue"
→ `keyword_search(query="React|Vue", top_k=10)`

**Example 3: Code pattern**
Input: "Find examples using create_deep_agent"
→ `keyword_search(query="create_deep_agent", top_k=5)`

## How It Works

- ripgrep scans all .md files in the content directory
- JSON output mode for structured result parsing
- Up to 5 matches per file; score = match_count / 5 (normalized 0–1)
- Case-insensitive by default
- Falls back to Python `re` module if ripgrep binary is not available

## When NOT to Use

- Broad topic exploration → `semantic_search` ranks by relevance
- Filtering by tags, category, or date → `metadata_filter`
- User doesn't know the exact keyword → start with `semantic_search`
