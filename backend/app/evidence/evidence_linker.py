from __future__ import annotations

from dataclasses import dataclass

from ..documents.document_types import DocumentChunk
from ..models import DocumentMetadata, InvoiceRecord


IDENTIFIER_FIELDS = (
    "property_id",
    "project_id",
    "vendor_id",
    "invoice_id",
    "po_id",
    "cost_code",
)


@dataclass(frozen=True)
class LinkedEvidenceMatch:
    chunk: DocumentChunk
    link_type: str
    matched_identifiers: tuple[str, ...]
    score: float


def invoice_identifier_map(invoice: InvoiceRecord) -> dict[str, str]:
    return {
        "property_id": invoice.property.property_id,
        "project_id": invoice.project.project_id,
        "vendor_id": invoice.vendor.vendor_id,
        "invoice_id": invoice.invoice_id,
        "po_id": invoice.purchase_order.po_id,
        "cost_code": invoice.budget.cost_code,
    }


def row_identifier_map(row: dict[str, object]) -> dict[str, str]:
    return {
        field: str(row[field])
        for field in IDENTIFIER_FIELDS
        if row.get(field)
    }


def metadata_identifier_map(metadata: DocumentMetadata) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in IDENTIFIER_FIELDS:
        value = getattr(metadata, field)
        if value:
            values[field] = value
    return values


def has_identifier_conflict(
    invoice_identifiers: dict[str, str], metadata: DocumentMetadata
) -> bool:
    for field, invoice_value in invoice_identifiers.items():
        document_value = getattr(metadata, field)
        if document_value and document_value != invoice_value:
            return True
    return False


def matched_identifier_fields(
    invoice_identifiers: dict[str, str], metadata: DocumentMetadata
) -> tuple[str, ...]:
    return tuple(
        field
        for field, invoice_value in invoice_identifiers.items()
        if getattr(metadata, field) == invoice_value
    )


def classify_link(matched_fields: tuple[str, ...]) -> tuple[str, float] | None:
    matched = set(matched_fields)
    scoped_to_record_context = {"project_id", "property_id"}.issubset(matched)

    if "invoice_id" in matched:
        return "invoice_id", 1.0
    if "po_id" in matched and scoped_to_record_context:
        return "purchase_order_id", 0.9
    if {"vendor_id", "cost_code"}.issubset(matched) and scoped_to_record_context:
        return "project_vendor_cost_code", 0.8
    if "vendor_id" in matched and scoped_to_record_context:
        return "project_vendor_id", 0.7
    if "cost_code" in matched and scoped_to_record_context:
        return "project_cost_code", 0.65

    return None


class EvidenceLinker:
    def link_identifiers_to_documents(
        self,
        invoice_identifiers: dict[str, str],
        chunks: tuple[DocumentChunk, ...],
        limit: int = 5,
    ) -> tuple[LinkedEvidenceMatch, ...]:
        matches: list[LinkedEvidenceMatch] = []

        for chunk in chunks:
            if has_identifier_conflict(invoice_identifiers, chunk.metadata):
                continue

            matched_fields = matched_identifier_fields(invoice_identifiers, chunk.metadata)
            classification = classify_link(matched_fields)
            if classification is None:
                continue

            link_type, score = classification
            matches.append(
                LinkedEvidenceMatch(
                    chunk=chunk,
                    link_type=link_type,
                    matched_identifiers=matched_fields,
                    score=score,
                )
            )

        matches.sort(
            key=lambda item: (item.score, len(item.matched_identifiers), item.chunk.metadata.document_id),
            reverse=True,
        )
        return tuple(matches[:limit])

    def link_invoice_to_documents(
        self,
        invoice: InvoiceRecord,
        chunks: tuple[DocumentChunk, ...],
        limit: int = 5,
    ) -> tuple[LinkedEvidenceMatch, ...]:
        invoice_identifiers = invoice_identifier_map(invoice)
        return self.link_identifiers_to_documents(invoice_identifiers, chunks, limit=limit)
