---
name: bm25-search
description: BM25 relevance ranking with Korean morphological analysis. Use this as the default search skill for natural language queries, topic exploration, and Korean-language questions. Handles queries like "how to build a RAG system", "agent architecture comparison", "도커 공부한 내용". Especially strong with Korean text thanks to kiwipiepy tokenization. Try this first for any search — it provides ranked results by relevance.
---

# BM25 Search (Semantic Search)

BM25Okapi ranking algorithm combined with kiwipiepy Korean morphological analyzer. Unlike exact keyword matching, BM25 quantifies document relevance and returns results sorted by score.

## Tool

`semantic_search(query, top_k)`

## Why BM25 + Korean Tokenization?

Korean is an agglutinative language — "에이전트를", "에이전트의", "에이전트로" are all variations of "에이전트". Simple keyword matching for "에이전트" would miss documents containing "에이전트를". The kiwipiepy morphological analyzer extracts root forms (nouns, verbs, adjectives, foreign words), dramatically improving Korean search quality.

BM25 improves on TF-IDF by accounting for document length and term frequency saturation — a keyword appearing 3 times in a short post scores higher than 3 times in a very long post.

## Examples

**Example 1: Natural language question**
Input: "How do I design a RAG system?"
→ `semantic_search(query="RAG system design", top_k=10)`

**Example 2: Korean topic exploration**
Input: "머신러닝 공부한 거 뭐 있어?"
→ `semantic_search(query="머신러닝 학습", top_k=10)`

**Example 3: Mixed Korean + English**
Input: "LangGraph로 멀티에이전트 만드는 방법"
→ `semantic_search(query="LangGraph 멀티에이전트", top_k=10)`

## How It Works

- First call builds a BM25 index over all 280 blog posts (2–3 seconds)
- Subsequent calls use cached index (instant)
- Indexes title + description + tags + body text combined
- kiwipiepy extracts nouns (NNG, NNP), verbs (VV), adjectives (VA), and foreign words (SL)
- Scores normalized 0–1; automatically extracts the most relevant snippet

## When NOT to Use

- Exact keyword/code search → `keyword_search` is faster and more precise
- Tag/category/date filtering → `metadata_filter`
- Already have the file path → go directly to `read_post`
