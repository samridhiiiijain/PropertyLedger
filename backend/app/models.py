from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class InvoiceStatus(StrEnum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    ON_HOLD = "ON_HOLD"


class PropertySummary(FrozenModel):
    property_id: str = Field(pattern=r"^P\d{3}$")
    name: str
    city: str
    property_type: str
    status: str


class ProjectSummary(FrozenModel):
    project_id: str = Field(pattern=r"^PR\d{3}$")
    name: str


class VendorSummary(FrozenModel):
    vendor_id: str = Field(pattern=r"^V\d{3}$")
    name: str
    category: str
    city: str
    tax_id: str


class PurchaseOrderSummary(FrozenModel):
    po_id: str = Field(pattern=r"^PO\d{4}$")
    committed_amount: Decimal = Field(ge=0, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class PaymentSummary(FrozenModel):
    payment_id: str = Field(pattern=r"^PAY\d{4}$")
    amount: Decimal = Field(gt=0, decimal_places=2)
    payment_date: date


class BudgetSummary(FrozenModel):
    budget_id: str | None = Field(default=None, pattern=r"^B\d{4}$")
    cost_code: str = Field(pattern=r"^CC\d{3}$")
    approved_amount: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class InvoiceRecord(FrozenModel):
    invoice_id: str = Field(pattern=r"^INV\d{4}$")
    invoice_number: str
    property: PropertySummary
    project: ProjectSummary
    vendor: VendorSummary
    purchase_order: PurchaseOrderSummary
    budget: BudgetSummary
    payments: tuple[PaymentSummary, ...]
    invoice_date: date
    due_date: date
    amount: Decimal = Field(gt=0, decimal_places=2)
    paid_amount: Decimal = Field(ge=0, decimal_places=2)
    outstanding_amount: Decimal = Field(ge=0, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    status: InvoiceStatus


class AppliedFilters(FrozenModel):
    project_id: str | None = None


class InvoiceListResponse(FrozenModel):
    items: tuple[InvoiceRecord, ...]
    count: int = Field(ge=0)
    filters: AppliedFilters


class HealthResponse(FrozenModel):
    status: str
    version: str


class UnpaidInvoiceRecord(FrozenModel):
    invoice_id: str = Field(pattern=r"^INV\d{4}$")
    vendor_id: str = Field(pattern=r"^V\d{3}$")
    vendor_name: str
    status: InvoiceStatus
    invoice_amount: Decimal = Field(ge=0, decimal_places=2)
    paid_amount: Decimal = Field(ge=0, decimal_places=2)
    outstanding_amount: Decimal = Field(ge=0, decimal_places=2)
    due_date: date


class PurchaseOrderVarianceRecord(FrozenModel):
    invoice_id: str = Field(pattern=r"^INV\d{4}$")
    po_id: str = Field(pattern=r"^PO\d{4}$")
    vendor_name: str
    invoice_amount: Decimal = Field(ge=0, decimal_places=2)
    po_total: Decimal = Field(ge=0, decimal_places=2)
    variance_amount: Decimal = Field(gt=0, decimal_places=2)
    cost_code: str = Field(pattern=r"^CC\d{3}$")


class BudgetVarianceRecord(FrozenModel):
    budget_id: str = Field(pattern=r"^B\d{4}$")
    cost_code: str = Field(pattern=r"^CC\d{3}$")
    cost_category: str
    budget_amount: Decimal = Field(ge=0, decimal_places=2)
    committed_amount: Decimal = Field(ge=0, decimal_places=2)
    variance_amount: Decimal = Field(gt=0, decimal_places=2)


class StructuredCheckResponse(FrozenModel):
    project_id: str = Field(pattern=r"^PR\d{3}$")
    items: tuple[
        UnpaidInvoiceRecord | PurchaseOrderVarianceRecord | BudgetVarianceRecord,
        ...,
    ]
    count: int = Field(ge=0)


class BusinessDefinition(FrozenModel):
    slug: str
    term: str
    definition: str
    grain: str
    calculation: str | None
    applies_when: str
    fields: tuple[str, ...]
    relationships: tuple[str, ...]
    used_by: tuple[str, ...]
    synonyms: tuple[str, ...] = ()
    owner: str
    version: str


class BusinessDefinitionListResponse(FrozenModel):
    items: tuple[BusinessDefinition, ...]
    count: int = Field(ge=0)


class DocumentMetadata(FrozenModel):
    document_id: str
    document_type: str
    document_date: date | None = None
    source_file: str
    property_id: str | None = Field(default=None, pattern=r"^P\d{3}$")
    project_id: str | None = Field(default=None, pattern=r"^PR\d{3}$")
    vendor_id: str | None = Field(default=None, pattern=r"^V\d{3}$")
    invoice_id: str | None = Field(default=None, pattern=r"^INV\d{4}$")
    po_id: str | None = Field(default=None, pattern=r"^PO\d{4}$")
    cost_code: str | None = Field(default=None, pattern=r"^CC\d{3}$")
    source_location: str | None = None
    content_hash: str | None = None


class DocumentEvidence(FrozenModel):
    chunk_id: str
    score: float = Field(ge=0)
    text: str
    metadata: DocumentMetadata
    source_location: str | None = None
    retrieval_method: str | None = None


class DocumentAnswerResponse(FrozenModel):
    question: str
    answer: str
    status: str
    confidence: float = Field(ge=0, le=1)
    latency_ms: int = Field(ge=0)
    sources: tuple[DocumentEvidence, ...]


class LinkedInvoiceFacts(FrozenModel):
    invoice_id: str = Field(pattern=r"^INV\d{4}$")
    property_id: str = Field(pattern=r"^P\d{3}$")
    project_id: str = Field(pattern=r"^PR\d{3}$")
    vendor_id: str = Field(pattern=r"^V\d{3}$")
    po_id: str = Field(pattern=r"^PO\d{4}$")
    cost_code: str = Field(pattern=r"^CC\d{3}$")
    status: InvoiceStatus
    invoice_amount: Decimal = Field(ge=0, decimal_places=2)
    po_amount: Decimal = Field(ge=0, decimal_places=2)
    po_variance_amount: Decimal = Field(decimal_places=2)
    paid_amount: Decimal = Field(ge=0, decimal_places=2)
    outstanding_amount: Decimal = Field(ge=0, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class LinkedDocumentEvidence(DocumentEvidence):
    link_type: str
    matched_identifiers: tuple[str, ...]


class LinkedInvoiceEvidenceResponse(FrozenModel):
    invoice_id: str = Field(pattern=r"^INV\d{4}$")
    status: str
    answer: str
    structured_facts: LinkedInvoiceFacts
    sources: tuple[LinkedDocumentEvidence, ...]


class RelationshipNode(FrozenModel):
    label: str
    id: str
    display: str


class RelationshipEdge(FrozenModel):
    type: str
    from_: str = Field(alias="from")
    to: str


class RelationshipPathRecord(FrozenModel):
    finding: str
    status: str
    invoice_id: str = Field(pattern=r"^INV\d{4}$")
    property_id: str = Field(pattern=r"^P\d{3}$")
    project_id: str = Field(pattern=r"^PR\d{3}$")
    po_id: str = Field(pattern=r"^PO\d{4}$")
    vendor_id: str = Field(pattern=r"^V\d{3}$")
    cost_code: str = Field(pattern=r"^CC\d{3}$")
    document_id: str | None = None
    invoice_amount: Decimal = Field(ge=0, decimal_places=2)
    po_amount: Decimal = Field(ge=0, decimal_places=2)
    variance_amount: Decimal = Field(gt=0, decimal_places=2)
    nodes: tuple[RelationshipNode, ...]
    edges: tuple[RelationshipEdge, ...]


class RelationshipPathResponse(FrozenModel):
    property_id: str = Field(pattern=r"^P\d{3}$")
    question: str
    answer: str
    count: int = Field(ge=0)
    paths: tuple[RelationshipPathRecord, ...]
