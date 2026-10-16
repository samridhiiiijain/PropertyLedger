from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..documents.document_repository import DocumentRepository
from .evidence_linker import EvidenceLinker, LinkedEvidenceMatch
from ..models import InvoiceStatus
from ..semantic_query.service import SemanticQueryService


@dataclass(frozen=True)
class StructuredInvoiceFacts:
    invoice_id: str
    property_id: str
    project_id: str
    vendor_id: str
    po_id: str
    cost_code: str
    status: InvoiceStatus
    invoice_amount: Decimal
    po_amount: Decimal
    po_variance_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    currency: str


@dataclass(frozen=True)
class LinkedInvoiceEvidenceResult:
    invoice: dict[str, object] | None
    facts: StructuredInvoiceFacts | None
    answer: str
    status: str
    matches: tuple[LinkedEvidenceMatch, ...]


class LinkedEvidenceService:
    def __init__(
        self,
        document_repository: DocumentRepository,
        semantic_query_service: SemanticQueryService,
        evidence_linker: EvidenceLinker | None = None,
    ) -> None:
        self.document_repository = document_repository
        self.evidence_linker = evidence_linker or EvidenceLinker()
        self.semantic_query_service = semantic_query_service

    def invoice_evidence(self, invoice_id: str) -> LinkedInvoiceEvidenceResult:
        normalized_invoice_id = invoice_id.strip().upper()
        response = self.semantic_query_service.answer(f"show invoices for {normalized_invoice_id}")
        if not response.is_successful or not response.rows:
            return LinkedInvoiceEvidenceResult(
                invoice=None,
                facts=None,
                answer=f"No structured invoice record was found for {normalized_invoice_id}.",
                status="not_found",
                matches=(),
            )

        invoice = response.rows[0]
        facts = structured_invoice_facts(invoice)
        matches = self.evidence_linker.link_identifiers_to_documents(
            invoice_identifiers={
                "property_id": facts.property_id,
                "project_id": facts.project_id,
                "vendor_id": facts.vendor_id,
                "invoice_id": facts.invoice_id,
                "po_id": facts.po_id,
                "cost_code": facts.cost_code,
            },
            chunks=self.document_repository.all_chunks(),
        )
        if not matches:
            return LinkedInvoiceEvidenceResult(
                invoice=invoice,
                facts=facts,
                answer=(
                    f"{facts.invoice_id} exists in structured records, but no supporting "
                    "document passage is explicitly linked by stable identifiers."
                ),
                status="missing_link",
                matches=(),
            )

        return LinkedInvoiceEvidenceResult(
            invoice=invoice,
            facts=facts,
            answer=linked_invoice_answer(facts, matches[0]),
            status="linked",
            matches=matches,
        )


def structured_invoice_facts(invoice: dict[str, object]) -> StructuredInvoiceFacts:
    po_variance = _money(invoice["po_variance_amount"])
    return StructuredInvoiceFacts(
        invoice_id=str(invoice["invoice_id"]),
        property_id=str(invoice["property_id"]),
        project_id=str(invoice["project_id"]),
        vendor_id=str(invoice["vendor_id"]),
        po_id=str(invoice["po_id"]),
        cost_code=str(invoice["cost_code"]),
        status=InvoiceStatus(str(invoice["status"]).strip().upper().replace(" ", "_")),
        invoice_amount=_money(invoice["invoice_amount"]),
        po_amount=_money(invoice["po_total"]),
        po_variance_amount=po_variance,
        paid_amount=_money(invoice["paid_amount"]),
        outstanding_amount=_money(invoice["outstanding_amount"]),
        currency="INR",
    )


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def linked_invoice_answer(
    facts: StructuredInvoiceFacts, primary_match: LinkedEvidenceMatch
) -> str:
    variance_text = ""
    if facts.po_variance_amount > 0:
        variance_text = (
            f" The structured record shows {facts.invoice_id} is {facts.currency} "
            f"{facts.po_variance_amount:,.2f} above {facts.po_id}."
        )
    elif facts.po_variance_amount == 0:
        variance_text = (
            f" The structured record shows {facts.invoice_id} matches {facts.po_id}."
        )
    else:
        variance_text = (
            f" The structured record shows {facts.invoice_id} is {facts.currency} "
            f"{abs(facts.po_variance_amount):,.2f} below {facts.po_id}."
        )

    source = primary_match.chunk.metadata
    passage = " ".join(primary_match.chunk.text.split())
    return (
        f"{facts.invoice_id} is connected to {source.document_id} by stable business IDs."
        f"{variance_text} The linked document says: {passage}"
    )
