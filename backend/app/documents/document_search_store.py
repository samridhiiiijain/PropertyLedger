from __future__ import annotations

from typing import Protocol

from .document_query import has_identifier_conflict
from .document_types import DocumentChunk, QueryIdentifiers, RetrievedChunk
from .hybrid_retriever import HybridDocumentRetriever


class DocumentSearchStore(Protocol):
    @property
    def index_version(self) -> str | None: ...

    def readiness(self) -> dict[str, object]: ...

    def all_chunks(self) -> tuple[DocumentChunk, ...]: ...

    def document_by_id(self, document_id: str) -> DocumentChunk | None: ...

    def search(
        self,
        question: str,
        *,
        identifiers: QueryIdentifiers,
        project_id: str | None,
        candidate_count: int,
        rerank_count: int,
        result_limit: int,
    ) -> tuple[RetrievedChunk, ...]: ...

    def close(self) -> None: ...


class FaissDocumentSearchStore:
    def __init__(
        self,
        chunks: tuple[DocumentChunk, ...],
        searchable_texts: tuple[str, ...],
        *,
        index_version: str,
    ) -> None:
        self._chunks = chunks
        self._index_version = index_version
        self.retriever = HybridDocumentRetriever(chunks, searchable_texts)

    @property
    def index_version(self) -> str:
        return self._index_version

    def readiness(self) -> dict[str, object]:
        return {
            "status": "ready",
            "backend": "faiss",
            "index_version": self.index_version,
            "chunks": len(self._chunks),
        }

    def all_chunks(self) -> tuple[DocumentChunk, ...]:
        return self._chunks

    def document_by_id(self, document_id: str) -> DocumentChunk | None:
        return next(
            (
                chunk
                for chunk in self._chunks
                if chunk.metadata.document_id == document_id
            ),
            None,
        )

    def search(
        self,
        question: str,
        *,
        identifiers: QueryIdentifiers,
        project_id: str | None,
        candidate_count: int,
        rerank_count: int,
        result_limit: int,
    ) -> tuple[RetrievedChunk, ...]:
        allowed_indices = {
            index
            for index, chunk in enumerate(self._chunks)
            if not has_identifier_conflict(
                chunk.metadata,
                identifiers,
                project_id,
            )
        }
        return self.retriever.search(
            question,
            allowed_indices=allowed_indices,
            candidate_count=candidate_count,
            rerank_count=rerank_count,
            result_limit=result_limit,
        )

    def close(self) -> None:
        return None
