from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import logging
from time import perf_counter

from .document_answering import (
    answer_from_sources,
    is_future_payment_question,
    is_structured_budget_question,
    is_structured_invoice_status_question,
    sources_support_question,
    unsupported_question,
)
from .document_parser import DOCUMENTS_DIR, load_document_chunks
from .document_query import (
    extract_identifiers,
    metadata_match_boost,
    tokens,
)
from .document_search_store import DocumentSearchStore, FaissDocumentSearchStore
from .document_types import DocumentChunk, RetrievedChunk
from .hybrid_retriever import (
    DEFAULT_CANDIDATE_COUNT,
    DEFAULT_RERANK_COUNT,
    DEFAULT_RESULT_LIMIT,
)
from .postgres_document_store import PostgresDocumentSearchStore
from ..models import DocumentAnswerResponse, DocumentEvidence, DocumentMetadata
from ..runtime_config import RuntimeSettings, load_runtime_settings

logger = logging.getLogger(__name__)


class DocumentProcessingTimeout(TimeoutError):
    """Raised when document indexing or retrieval exceeds its work budget."""


class DocumentRepository:
    def __init__(
        self,
        documents_dir: Path = DOCUMENTS_DIR,
        settings: RuntimeSettings | None = None,
        search_store: DocumentSearchStore | None = None,
    ) -> None:
        self.documents_dir = documents_dir
        self.settings = settings or load_runtime_settings()
        self.search_store = search_store or self._create_search_store()

    def _current_source_fingerprint(self) -> tuple[tuple[str, int, int], ...]:
        supported = {".txt", ".md", ".markdown", ".pdf", ".docx"}
        files = (
            path
            for path in self.documents_dir.iterdir()
            if path.is_file() and path.suffix.lower() in supported
        )
        return tuple(
            sorted((path.name, path.stat().st_mtime_ns, path.stat().st_size) for path in files)
        )

    def _create_search_store(self) -> DocumentSearchStore:
        if self.settings.document_search_backend == "postgres":
            assert self.settings.document_database_url is not None
            return PostgresDocumentSearchStore(self.settings.document_database_url)

        started_at = perf_counter()
        deadline = started_at + self.settings.rag_indexing_timeout_ms / 1000
        fingerprint = self._current_source_fingerprint()
        self._check_deadline(deadline, "document indexing")
        parsing_started_at = perf_counter()
        chunks, searchable_texts = load_document_chunks(self.documents_dir)
        logger.info(
            "document_parsing_complete files=%d chunks=%d duration_ms=%d",
            len(fingerprint),
            len(chunks),
            round((perf_counter() - parsing_started_at) * 1000),
        )
        self._check_deadline(deadline, "document parsing")
        index_version = sha256(repr(fingerprint).encode("utf-8")).hexdigest()[:16]
        search_store = FaissDocumentSearchStore(
            chunks,
            searchable_texts,
            index_version=index_version,
        )
        self._check_deadline(deadline, "embedding and index construction")
        logger.info(
            "document_index_ready documents=%d chunks=%d duration_ms=%d",
            len({chunk.metadata.document_id for chunk in chunks}),
            len(chunks),
            round((perf_counter() - started_at) * 1000),
        )
        return search_store

    @property
    def index_version(self) -> str | None:
        return self.search_store.index_version

    def readiness(self) -> dict[str, object]:
        return self.search_store.readiness()

    def all_chunks(self) -> tuple[DocumentChunk, ...]:
        return self.search_store.all_chunks()

    def _check_deadline(self, deadline: float, stage: str) -> None:
        if perf_counter() > deadline:
            logger.error("document_stage_timeout stage=%s", stage)
            raise DocumentProcessingTimeout(f"{stage} exceeded its configured time budget.")

    def answer_question(
        self,
        question: str,
        project_id: str | None = None,
        limit: int = 5,
    ) -> DocumentAnswerResponse:
        started_at = perf_counter()
        request_deadline = started_at + self.settings.rag_request_timeout_ms / 1000
        self._check_deadline(request_deadline, "document request")
        normalized_question = question.strip()
        identifiers = extract_identifiers(normalized_question)

        if unsupported_question(normalized_question):
            answer = (
                "Available evidence cannot guarantee future payment timing."
                if is_future_payment_question(normalized_question)
                else "Budget variance questions require structured records. Use the project structured checks for exact cost-code results."
                if is_structured_budget_question(normalized_question)
                else "Invoice status questions require structured records. Use the project structured checks for exact invoice status results."
                if is_structured_invoice_status_question(normalized_question)
                else "The available documents do not provide enough evidence to safely answer this question."
            )
            return self._response(
                question=normalized_question,
                answer=answer,
                status="no_evidence",
                confidence=0,
                started_at=started_at,
                sources=(),
            )

        explicit_document = self._document_by_id(identifiers.document_id)
        requested_project_id = identifiers.project_id or project_id
        if (
            explicit_document
            and requested_project_id
            and explicit_document.metadata.project_id
            and explicit_document.metadata.project_id != requested_project_id
        ):
            evidence = self._evidence_from_retrieved(
                (RetrievedChunk(chunk=explicit_document, score=1.0),)
            )
            return self._response(
                question=normalized_question,
                answer=(
                    f"No. {explicit_document.metadata.document_id} belongs to "
                    f"{explicit_document.metadata.project_id}, so it should not be used as "
                    f"evidence for {requested_project_id}."
                ),
                status="answered",
                confidence=0.95,
                started_at=started_at,
                sources=evidence,
            )

        retrieved = self.search(normalized_question, project_id=project_id, limit=limit)
        self._check_deadline(request_deadline, "document request")
        if not retrieved:
            return self._response(
                question=normalized_question,
                answer="The available documents do not provide enough evidence to safely answer this question.",
                status="no_evidence",
                confidence=0,
                started_at=started_at,
                sources=(),
            )

        sources = self._evidence_from_retrieved(retrieved)
        if not sources_support_question(normalized_question, sources):
            return self._response(
                question=normalized_question,
                answer="The retrieved documents are related, but they do not contain evidence for the specific detail requested.",
                status="no_evidence",
                confidence=0,
                started_at=started_at,
                sources=sources,
            )

        confidence = min(0.95, max(0.35, retrieved[0].score))
        return self._response(
            question=normalized_question,
            answer=answer_from_sources(normalized_question, sources),
            status="answered",
            confidence=round(confidence, 2),
            started_at=started_at,
            sources=sources,
        )

    def search(
        self,
        question: str,
        project_id: str | None = None,
        limit: int = 5,
    ) -> tuple[RetrievedChunk, ...]:
        request_deadline = perf_counter() + self.settings.rag_retrieval_timeout_ms / 1000
        identifiers = extract_identifiers(question)
        query_tokens = set(tokens(question))
        retrieved = self.search_store.search(
            question,
            identifiers=identifiers,
            project_id=project_id,
            candidate_count=max(DEFAULT_CANDIDATE_COUNT, limit),
            rerank_count=max(DEFAULT_RERANK_COUNT, limit),
            result_limit=max(DEFAULT_RESULT_LIMIT, limit),
        )
        self._check_deadline(request_deadline, "document retrieval")
        results: list[RetrievedChunk] = []
        for item in retrieved:
            chunk = item.chunk
            lexical_overlap = len(query_tokens.intersection(chunk.tokens)) / max(len(query_tokens), 1)
            metadata_boost = metadata_match_boost(question, chunk.metadata, identifiers, project_id)
            # Keep semantic matches, but do not turn an entirely unrelated dense hit
            # into evidence when neither terms nor stable metadata support it.
            if lexical_overlap == 0 and metadata_boost == 0:
                continue
            raw_score = float(item.score) + lexical_overlap + metadata_boost
            score = min(1.0, max(0.0, raw_score / 2.0))
            results.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=round(score, 4),
                    retrieval_method=item.retrieval_method,
                    rank=item.rank,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        logger.info(
            "document_retrieval_complete candidates=%d returned=%d duration_ms=%d",
            len(retrieved),
            len(results[:limit]),
            round((perf_counter() - (request_deadline - self.settings.rag_retrieval_timeout_ms / 1000)) * 1000),
        )
        return tuple(results[:limit])

    def _document_by_id(self, document_id: str | None) -> DocumentChunk | None:
        if document_id is None:
            return None
        return self.search_store.document_by_id(document_id)

    def close(self) -> None:
        self.search_store.close()

    def _evidence_from_retrieved(
        self, retrieved: tuple[RetrievedChunk, ...]
    ) -> tuple[DocumentEvidence, ...]:
        return tuple(
            DocumentEvidence(
                chunk_id=item.chunk.chunk_id,
                score=item.score,
                text=item.chunk.text,
                metadata=item.chunk.metadata,
                source_location=item.chunk.source_location,
                retrieval_method=item.retrieval_method,
            )
            for item in retrieved
        )

    def _response(
        self,
        question: str,
        answer: str,
        status: str,
        confidence: float,
        started_at: float,
        sources: tuple[DocumentEvidence, ...],
    ) -> DocumentAnswerResponse:
        return DocumentAnswerResponse(
            question=question,
            answer=answer,
            status=status,
            confidence=confidence,
            latency_ms=round((perf_counter() - started_at) * 1000),
            sources=sources,
        )
