---
name: blog-search
description: Search strategy guidance for blog content retrieval using semantic, keyword, metadata, and graph tools
---

# Blog Search Skill

## Overview

Guide the agent on effective search strategies for the blog knowledge base.

## When to Use

When the user asks questions about blog content, projects, or technical topics covered in the blog.

## Strategy

1. **Simple factual queries** -> `semantic_search` first, `read_file` for details
2. **Keyword-specific queries** -> `keyword_search` (especially for Korean terms, code names)
3. **Topic exploration** -> `semantic_search` + `graph_traverse` for related content
4. **Filtered queries** (by date, tag) -> `metadata_filter` first, then `semantic_search` within results
5. **Comprehensive research** -> Combine multiple tools: semantic + keyword + graph traverse
