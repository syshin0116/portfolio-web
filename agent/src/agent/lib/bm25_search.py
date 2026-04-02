"""BM25 search with Korean morphological analysis."""

from __future__ import annotations

import logging
import re

from rank_bm25 import BM25Okapi

from agent.lib.config import SearchConfig, get_config
from agent.lib.content_loader import get_cached_docs
from agent.lib.types import ContentDoc, SearchResult

logger = logging.getLogger(__name__)

# Module-level BM25 index cache
_bm25: BM25Okapi | None = None
_bm25_docs: list[ContentDoc] = []
_bm25_corpus: list[list[str]] = []
_bm25_mtime: float = 0.0

# Lazy-loaded Kiwi tokenizer
_kiwi = None


def _get_kiwi():
    global _kiwi
    if _kiwi is None:
        try:
            from kiwipiepy import Kiwi
            _kiwi = Kiwi()
            logger.info("kiwipiepy loaded for Korean tokenization")
        except ImportError:
            logger.warning("kiwipiepy not available, falling back to whitespace tokenization")
            _kiwi = False  # sentinel: tried but failed
    return _kiwi if _kiwi is not False else None


def _tokenize(text: str) -> list[str]:
    """Tokenize text using kiwipiepy for Korean, whitespace for rest."""
    kiwi = _get_kiwi()
    if kiwi:
        tokens = []
        for token in kiwi.tokenize(text):
            # Keep nouns (NNG, NNP), verbs (VV), adjectives (VA), foreign (SL)
            if token.tag.startswith(("NN", "VV", "VA", "SL")):
                tokens.append(token.form.lower())
        return tokens if tokens else text.lower().split()

    # Fallback: simple whitespace + punctuation removal
    return re.findall(r"[a-zA-Z가-힣0-9]+", text.lower())


def _build_index(config: SearchConfig) -> None:
    global _bm25, _bm25_docs, _bm25_corpus, _bm25_mtime

    docs = get_cached_docs(config)
    corpus: list[list[str]] = []

    for doc in docs:
        text = f"{doc.meta.title} {doc.meta.description} {' '.join(doc.meta.tags)} {doc.body}"
        tokens = _tokenize(text)
        corpus.append(tokens)

    _bm25 = BM25Okapi(corpus)
    _bm25_docs = docs
    _bm25_corpus = corpus
    _bm25_mtime = max((d.meta.date.toordinal() if d.meta.date else 0) for d in docs) if docs else 0
    logger.info("BM25 index built: %d documents, avg %.0f tokens", len(docs), sum(len(c) for c in corpus) / max(len(corpus), 1))


def _get_snippet(doc: ContentDoc, query_tokens: list[str], max_chars: int = 300) -> str:
    """Extract the most relevant snippet from document body."""
    paragraphs = doc.body.split("\n\n")
    if not paragraphs:
        return doc.meta.description

    best_para = ""
    best_score = -1

    for para in paragraphs:
        para_lower = para.lower()
        score = sum(1 for t in query_tokens if t in para_lower)
        if score > best_score:
            best_score = score
            best_para = para

    snippet = best_para.strip()
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars - 3] + "..."
    return snippet or doc.meta.description


def bm25_search(
    query: str,
    *,
    top_k: int = 10,
    config: SearchConfig | None = None,
) -> list[SearchResult]:
    """Search blog posts using BM25 ranking with Korean tokenization."""
    cfg = config or get_config()

    # Rebuild index if needed
    docs = get_cached_docs(cfg)
    if _bm25 is None or docs is not _bm25_docs:
        _build_index(cfg)

    assert _bm25 is not None

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scores = _bm25.get_scores(query_tokens)

    # Normalize scores
    max_score = max(scores) if max(scores) > 0 else 1.0

    # Rank and return top_k
    scored = [(i, s / max_score) for i, s in enumerate(scores) if s > 0]
    scored.sort(key=lambda x: x[1], reverse=True)

    results: list[SearchResult] = []
    for idx, norm_score in scored[:top_k]:
        doc = _bm25_docs[idx]
        results.append(SearchResult(
            path=doc.meta.path,
            title=doc.meta.title,
            score=round(norm_score, 3),
            snippet=_get_snippet(doc, query_tokens),
            source="bm25",
        ))

    return results
