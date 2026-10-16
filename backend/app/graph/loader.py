from __future__ import annotations

import copy
from hashlib import sha256
import json
from typing import Any

from ..documents.document_repository import DocumentRepository
from ..documents.document_types import DocumentChunk
from ..evidence.evidence_linker import EvidenceLinker
from ..semantic_query.service import SemanticQueryService
from .repository import Neo4jGraphRepository
from .repository import GraphProjectionBuildResult


class GraphLoader:
    def __init__(
        self,
        graph_repository: Neo4jGraphRepository,
        document_repository: DocumentRepository,
        semantic_query_service: SemanticQueryService,
        evidence_linker: EvidenceLinker | None = None,
    ) -> None:
        self.graph_repository = graph_repository
        self.document_repository = document_repository
        self.evidence_linker = evidence_linker or EvidenceLinker()
        self.semantic_query_service = semantic_query_service

    def load(self) -> GraphProjectionBuildResult:
        deterministic_service = copy.copy(self.semantic_query_service)
        deterministic_service.text_to_sql_mode = "off"
        response = deterministic_service.answer("show invoices")
        if not response.is_successful:
            raise RuntimeError(response.answer)
        invoices = response.rows
        chunks = self.document_repository.all_chunks()
        graph_invoices = [invoice_to_graph_row(invoice) for invoice in invoices]
        documents = document_rows(chunks)
        links = document_link_rows(
            invoices=invoices,
            chunks=chunks,
            evidence_linker=self.evidence_linker,
        )
        fingerprint = projection_fingerprint(graph_invoices, documents, links)
        projection_version = f"graph-{fingerprint[:16]}"
        counts = expected_projection_counts(graph_invoices, documents, links)
        self.graph_repository.verify_connection()
        self.graph_repository.ensure_constraints()
        return self.graph_repository.replace_projection(
            projection_version=projection_version,
            source_fingerprint=fingerprint,
            invoices=graph_invoices,
            documents=documents,
            document_links=links,
            expected_counts=counts,
        )


def load_graph() -> GraphProjectionBuildResult:
    from ..application_services import build_application_services

    services = build_application_services()
    try:
        assert services.graph_service.graph_repository is not None
        return GraphLoader(
            graph_repository=services.graph_service.graph_repository,
            document_repository=services.document_repository,
            semantic_query_service=services.semantic_query_service,
        ).load()
    finally:
        services.close()


def invoice_to_graph_row(invoice: dict[str, Any]) -> dict[str, Any]:
    return {
        "invoice_id": invoice["invoice_id"],
        "property_id": invoice["property_id"],
        "project_id": invoice["project_id"],
        "vendor_id": invoice["vendor_id"],
        "po_id": invoice["po_id"],
        "cost_code": invoice["cost_code"],
    }


def document_rows(chunks: tuple[DocumentChunk, ...]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for chunk in chunks:
        metadata = chunk.metadata
        if metadata.document_id in seen:
            continue
        seen.add(metadata.document_id)
        rows.append(
            {
                "document_id": metadata.document_id,
            }
        )
    return rows


def document_link_rows(
    invoices: tuple[dict[str, Any], ...],
    chunks: tuple[DocumentChunk, ...],
    evidence_linker: EvidenceLinker,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for invoice in invoices:
        invoice_identifiers = {
            "property_id": str(invoice["property_id"]),
            "project_id": str(invoice["project_id"]),
            "vendor_id": str(invoice["vendor_id"]),
            "invoice_id": str(invoice["invoice_id"]),
            "po_id": str(invoice["po_id"]),
            "cost_code": str(invoice["cost_code"]),
        }
        matches = evidence_linker.link_identifiers_to_documents(
            invoice_identifiers=invoice_identifiers,
            chunks=chunks,
        )
        for match in matches:
            key = (str(invoice["invoice_id"]), match.chunk.metadata.document_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "invoice_id": invoice["invoice_id"],
                    "document_id": match.chunk.metadata.document_id,
                    "link_type": match.link_type,
                    "matched_identifiers": list(match.matched_identifiers),
                }
            )
    return rows


def projection_fingerprint(
    invoices: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> str:
    payload = {
        "invoices": sorted(invoices, key=lambda item: item["invoice_id"]),
        "documents": sorted(documents, key=lambda item: item["document_id"]),
        "links": sorted(
            links,
            key=lambda item: (item["invoice_id"], item["document_id"]),
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def expected_projection_counts(
    invoices: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "properties": len({row["property_id"] for row in invoices}),
        "projects": len({row["project_id"] for row in invoices}),
        "vendors": len({row["vendor_id"] for row in invoices}),
        "purchase_orders": len({row["po_id"] for row in invoices}),
        "cost_codes": len({row["cost_code"] for row in invoices}),
        "invoices": len({row["invoice_id"] for row in invoices}),
        "documents": len({row["document_id"] for row in documents}),
        "document_links": len(
            {(row["invoice_id"], row["document_id"]) for row in links}
        ),
    }


if __name__ == "__main__":
    result = load_graph()
    print(
        "Neo4j relationship graph loaded successfully: "
        f"{result.projection_version} {result.counts}"
    )
