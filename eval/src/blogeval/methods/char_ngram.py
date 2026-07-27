"""Pure-stdlib character n-gram BM25 lexical baseline."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping

from agent.retrieval.fingerprint import canonical_config, retriever_fingerprint
from agent.retrieval.protocol import Corpus, DocId, Hit, Retrieval

CHAR_NGRAM_METHOD_ID = "char-ngram"
CHAR_NGRAM_IMPLEMENTATION_ID = "blogeval.methods.char_ngram:create@2"
CHAR_NGRAM_CONFIG: dict[str, object] = {
    "algorithm": "bm25-lucene-idf",
    "b": 0.75,
    "comparison_scope": "compound-document-representation-and-ranker",
    "document_representation": "raw-published-markdown",
    "idf_variant": "lucene-positive",
    "k1": 1.5,
    "max_n": 3,
    "min_n": 2,
    "normalization": "NFC+casefold",
    "positive_scores_only": True,
    "token_pattern": "[0-9A-Za-z가-힣]+",
}
_TOKEN_RE = re.compile(str(CHAR_NGRAM_CONFIG["token_pattern"]))


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _grams(value: str) -> tuple[str, ...]:
    min_n = int(CHAR_NGRAM_CONFIG["min_n"])
    max_n = int(CHAR_NGRAM_CONFIG["max_n"])
    grams: list[str] = []
    for token in _TOKEN_RE.findall(_normalize(value)):
        if len(token) < min_n:
            grams.append(token)
            continue
        for size in range(min_n, min(max_n, len(token)) + 1):
            grams.extend(
                token[start : start + size] for start in range(len(token) - size + 1)
            )
    return tuple(grams)


class CharNgramRetriever:
    """Rank verified published documents with deterministic char-gram BM25."""

    def __init__(self, corpus: Corpus) -> None:
        fingerprint = getattr(corpus, "fingerprint", None)
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("CharNgramRetriever requires a fingerprinted Corpus")
        self._corpus = corpus
        self._doc_ids = tuple(DocId(value) for value in corpus.doc_ids())
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        doc_lengths: list[int] = []
        for doc_index, doc_id in enumerate(self._doc_ids):
            frequencies = Counter(_grams(corpus.read(doc_id)))
            doc_lengths.append(sum(frequencies.values()))
            for gram, frequency in sorted(frequencies.items()):
                postings[gram].append((doc_index, frequency))
        self._postings = {
            gram: tuple(values) for gram, values in sorted(postings.items())
        }
        self._doc_lengths = tuple(doc_lengths)
        self._average_document_length = (
            sum(doc_lengths) / len(doc_lengths) if doc_lengths else 0.0
        )

    @property
    def identity_config(self) -> dict[str, object]:
        return json.loads(canonical_config(CHAR_NGRAM_CONFIG))

    @property
    def fingerprint(self) -> str:
        return retriever_fingerprint(
            method_id=CHAR_NGRAM_METHOD_ID,
            implementation_id=CHAR_NGRAM_IMPLEMENTATION_ID,
            config=CHAR_NGRAM_CONFIG,
            corpus_fingerprint=self._corpus.fingerprint,
        )

    def retrieve(self, query: str, *, limit: int = 10) -> Retrieval:
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0 or not self._doc_ids:
            return Retrieval(query=query)
        query_grams = Counter(_grams(query))
        if not query_grams:
            return Retrieval(query=query)

        scores: dict[int, float] = defaultdict(float)
        document_count = len(self._doc_ids)
        k1 = float(CHAR_NGRAM_CONFIG["k1"])
        b = float(CHAR_NGRAM_CONFIG["b"])
        for gram, query_frequency in sorted(query_grams.items()):
            postings = self._postings.get(gram, ())
            if not postings:
                continue
            document_frequency = len(postings)
            inverse_document_frequency = math.log(
                1.0
                + (document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            for doc_index, term_frequency in postings:
                length_ratio = (
                    self._doc_lengths[doc_index] / self._average_document_length
                    if self._average_document_length
                    else 0.0
                )
                denominator = term_frequency + k1 * (1.0 - b + b * length_ratio)
                scores[doc_index] += (
                    query_frequency
                    * inverse_document_frequency
                    * (term_frequency * (k1 + 1.0) / denominator)
                )
        ordered = sorted(
            (
                (score, self._doc_ids[doc_index])
                for doc_index, score in scores.items()
                if score > 0.0
            ),
            key=lambda item: (-item[0], str(item[1])),
        )
        return Retrieval(
            query=query,
            hits=tuple(
                Hit(
                    doc_id=doc_id,
                    rank=rank,
                    score=score,
                    metadata={"matched_query_grams": len(query_grams)},
                )
                for rank, (score, doc_id) in enumerate(ordered[:limit], start=1)
            ),
        )


def create(
    corpus: Corpus,
    config: Mapping[str, object],
) -> CharNgramRetriever:
    if canonical_config(config) != canonical_config(CHAR_NGRAM_CONFIG):
        raise ValueError("registered char-ngram config does not match implementation")
    return CharNgramRetriever(corpus)


__all__ = [
    "CHAR_NGRAM_CONFIG",
    "CHAR_NGRAM_IMPLEMENTATION_ID",
    "CHAR_NGRAM_METHOD_ID",
    "CharNgramRetriever",
    "create",
]
