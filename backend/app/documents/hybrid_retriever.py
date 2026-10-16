from __future__ import annotations

import math
from collections import Counter
import logging
from time import perf_counter
from typing import Iterable

from .document_query import tokens
from .document_types import DocumentChunk, RetrievedChunk
from .document_vector_index import DocumentVectorIndex


# RAG configuration defaults. Tune these only after measuring retrieval quality
# and latency; normal deployments should use these defaults.
DEFAULT_CANDIDATE_COUNT = 100
DEFAULT_RERANK_COUNT = 30
DEFAULT_RESULT_LIMIT = 8
# Use the cross-encoder when its model is already available locally; fall back
# to fused retrieval automatically when it is unavailable.
CROSS_ENCODER_ENABLED = True
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
logger = logging.getLogger(__name__)


class HybridDocumentRetriever:
    """BM25 + dense retrieval, RRF fusion, and optional cross-encoder reranking."""

    def __init__(
        self,
        chunks: tuple[DocumentChunk, ...],
        searchable_texts: tuple[str, ...],
    ) -> None:
        self.chunks = chunks
        self.searchable_texts = searchable_texts
        self.documents = [tuple(tokens(text)) for text in searchable_texts]
        self.term_frequency = [Counter(document) for document in self.documents]
        self.document_frequency: Counter[str] = Counter()
        for document in self.documents:
            self.document_frequency.update(set(document))
        self.average_length = sum(map(len, self.documents)) / max(len(self.documents), 1)
        embedding_started_at = perf_counter()
        self.dense = DocumentVectorIndex(searchable_texts)
        logger.info(
            "document_embedding_index_ready texts=%d duration_ms=%d",
            len(searchable_texts),
            round((perf_counter() - embedding_started_at) * 1000),
        )
        self.cross_encoder = self._load_cross_encoder()

    def search(
        self,
        question: str,
        *,
        allowed_indices: set[int] | None = None,
        candidate_count: int = 100,
        rerank_count: int = 30,
        result_limit: int = 8,
    ) -> tuple[RetrievedChunk, ...]:
        started_at = perf_counter()
        allowed = allowed_indices or set(range(len(self.chunks)))
        if not allowed:
            return ()

        query_tokens = tuple(tokens(question))
        bm25_indices = self._bm25_candidates(query_tokens, allowed, candidate_count)
        dense_scores, dense_indices = self.dense.search(question, min(candidate_count, len(self.chunks)))
        dense_ranked = [int(index) for index in dense_indices[0] if int(index) in allowed]
        dense_ranked = dense_ranked[:candidate_count]

        fused: dict[int, float] = {}
        for rank, index in enumerate(bm25_indices, start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (60 + rank)
        for rank, index in enumerate(dense_ranked, start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (60 + rank)

        candidates = sorted(fused, key=lambda index: fused[index], reverse=True)[:rerank_count]
        reranked = self._rerank(question, candidates)
        if reranked is None:
            ordered = [(index, fused[index], "hybrid") for index in candidates]
        else:
            ordered = [(index, score, "cross_encoder") for index, score in reranked]

        results = tuple(
            RetrievedChunk(
                chunk=self.chunks[index],
                score=round(float(score), 4),
                retrieval_method=method,
                rank=rank,
            )
            for rank, (index, score, method) in enumerate(ordered[:result_limit], start=1)
        )
        logger.info(
            "document_hybrid_search_complete chunks=%d candidates=%d returned=%d duration_ms=%d reranked=%s",
            len(self.chunks),
            len(candidates),
            len(results),
            round((perf_counter() - started_at) * 1000),
            reranked is not None,
        )
        return results

    def _bm25_candidates(
        self,
        query_tokens: tuple[str, ...],
        allowed: set[int],
        candidate_count: int,
    ) -> list[int]:
        document_count = len(self.documents)
        scored: list[tuple[float, int]] = []
        for index in allowed:
            length = len(self.documents[index]) or 1
            score = 0.0
            for term in query_tokens:
                frequency = self.term_frequency[index].get(term, 0)
                if not frequency:
                    continue
                document_frequency = self.document_frequency.get(term, 0)
                idf = math.log(1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))
                denominator = frequency + 1.5 * (0.25 + 0.75 * length / max(self.average_length, 1))
                score += idf * frequency * 2.5 / denominator
            scored.append((score, index))
        scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        return [index for score, index in scored[:candidate_count] if score > 0]

    def _load_cross_encoder(self):
        if not CROSS_ENCODER_ENABLED:
            return None
        model_name = CROSS_ENCODER_MODEL
        try:
            from sentence_transformers import CrossEncoder

            return CrossEncoder(model_name, local_files_only=True)
        except Exception:
            return None

    def _rerank(self, question: str, candidates: Iterable[int]):
        if self.cross_encoder is None:
            return None
        indices = tuple(candidates)
        pairs = [(question, self.chunks[index].text) for index in indices]
        scores = self.cross_encoder.predict(pairs)
        ranked = sorted(zip(indices, scores), key=lambda item: float(item[1]), reverse=True)
        return [
            (index, 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, float(score))))))
            for index, score in ranked
        ]
