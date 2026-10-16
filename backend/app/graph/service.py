from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..models import (
    RelationshipEdge,
    RelationshipNode,
    RelationshipPathRecord,
    RelationshipPathResponse,
)
from ..semantic_query.service import SemanticQueryService
from ..semantics.definitions import has_po_variance
from .repository import Neo4jGraphRepository


class GraphTraversalService:
    def __init__(
        self,
        semantic_query_service: SemanticQueryService,
        graph_repository: Neo4jGraphRepository | None = None,
    ) -> None:
        self.graph_repository = graph_repository
        self.semantic_query_service = semantic_query_service

    def trace_po_variance_paths(self, property_id: str) -> RelationshipPathResponse:
        repository = self.graph_repository or Neo4jGraphRepository()
        owns_repository = self.graph_repository is None
        try:
            rows = repository.trace_po_variance_paths(property_id=property_id)
            paths = tuple(
                path_record_from_neo4j(row, self._authoritative_invoice(row["invoice_id"]))
                for row in rows
                if self._is_po_variance(row["invoice_id"])
            )
        finally:
            if owns_repository:
                repository.close()
        return RelationshipPathResponse(
            property_id=property_id,
            question=f"Trace PO variance invoice paths for property {property_id}.",
            answer=answer_from_paths(property_id, paths),
            count=len(paths),
            paths=paths,
        )

    def close(self) -> None:
        if self.graph_repository is not None:
            self.graph_repository.close()

    def _authoritative_invoice(self, invoice_id: str) -> dict[str, Any]:
        response = self.semantic_query_service.answer(f"show invoice {invoice_id}")
        if not response.is_successful or not response.rows:
            raise RuntimeError(f"Structured invoice {invoice_id} was not found for graph enrichment.")
        return response.rows[0]

    def _is_po_variance(self, invoice_id: str) -> bool:
        row = self._authoritative_invoice(invoice_id)
        return has_po_variance(row["invoice_amount"], row["po_total"])


def path_record_from_neo4j(row: dict[str, Any], invoice: dict[str, Any]) -> RelationshipPathRecord:
    return RelationshipPathRecord(
        finding=row["finding"],
        status=row["status"],
        invoice_id=row["invoice_id"],
        property_id=row["property_id"],
        project_id=row["project_id"],
        po_id=row["po_id"],
        vendor_id=row["vendor_id"],
        cost_code=row["cost_code"],
        document_id=row.get("document_id"),
        invoice_amount=Decimal(str(invoice["invoice_amount"])).quantize(Decimal("0.01")),
        po_amount=Decimal(str(invoice["po_total"])).quantize(Decimal("0.01")),
        variance_amount=(
            Decimal(str(invoice["invoice_amount"])) - Decimal(str(invoice["po_total"]))
        ).quantize(Decimal("0.01")),
        nodes=tuple(RelationshipNode(**node) for node in row["path_nodes"]),
        edges=tuple(RelationshipEdge(**edge) for edge in row["path_edges"]),
    )


def answer_from_paths(
    property_id: str, paths: tuple[RelationshipPathRecord, ...]
) -> str:
    if not paths:
        return f"No PO variance relationship paths were found for property {property_id}."

    supported = sum(1 for path in paths if path.status == "supported")
    missing = len(paths) - supported
    return (
        f"Neo4j traced {len(paths)} PO variance path"
        f"{'' if len(paths) == 1 else 's'} for property {property_id}: "
        f"{supported} with linked document evidence and {missing} missing explicit document evidence."
    )
