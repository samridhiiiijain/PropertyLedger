from __future__ import annotations

from dataclasses import dataclass

from ..models import DocumentMetadata


@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    text: str
    metadata: DocumentMetadata
    tokens: frozenset[str]
    source_location: str | None = None
    section: str | None = None
    token_count: int = 0


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: DocumentChunk
    score: float
    retrieval_method: str = "hybrid"
    rank: int = 0


@dataclass(frozen=True)
class QueryIdentifiers:
    document_id: str | None = None
    property_id: str | None = None
    project_id: str | None = None
    vendor_id: str | None = None
    invoice_id: str | None = None
    po_id: str | None = None
    cost_code: str | None = None
