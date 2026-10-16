from __future__ import annotations

from dataclasses import dataclass

from .hybrid_retriever import HybridDocumentRetriever


@dataclass(frozen=True)
class RetrievalJudgment:
    question: str
    relevant_chunk_ids: frozenset[str]


@dataclass(frozen=True)
class RetrievalEvaluation:
    cases: int
    recall_at_k: float
    mean_reciprocal_rank: float
    reranker_cases: int
    reranker_top_rank_changes: int


def evaluate_retrieval(
    retriever: HybridDocumentRetriever,
    judgments: tuple[RetrievalJudgment, ...],
    *,
    k: int = 5,
) -> RetrievalEvaluation:
    if not judgments:
        return RetrievalEvaluation(0, 0.0, 0.0, 0, 0)

    hits = 0
    reciprocal_ranks: list[float] = []
    reranker_changes = 0
    reranker_cases = 0
    for judgment in judgments:
        results = retriever.search(judgment.question, result_limit=k)
        result_ids = [item.chunk.chunk_id for item in results]
        hit_positions = [
            index + 1
            for index, chunk_id in enumerate(result_ids)
            if chunk_id in judgment.relevant_chunk_ids
        ]
        if hit_positions:
            hits += 1
            reciprocal_ranks.append(1.0 / min(hit_positions))
        else:
            reciprocal_ranks.append(0.0)
        if any(item.retrieval_method == "cross_encoder" for item in results):
            reranker_cases += 1
            if result_ids and result_ids[0] in judgment.relevant_chunk_ids:
                reranker_changes += 1

    return RetrievalEvaluation(
        cases=len(judgments),
        recall_at_k=round(hits / len(judgments), 4),
        mean_reciprocal_rank=round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4),
        reranker_cases=reranker_cases,
        reranker_top_rank_changes=reranker_changes,
    )
