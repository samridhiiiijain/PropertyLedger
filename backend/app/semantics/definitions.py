from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BusinessTermDefinition:
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
    owner: str = "Finance Operations"
    version: str = "v0.6"


UNPAID_INVOICE_STATUSES = ("UNPAID", "ON_HOLD")

UNPAID_INVOICE_SQL_CONDITION = (
    "i.paid_amount = 0 "
    "AND UPPER(REPLACE(i.status, ' ', '_')) IN ('UNPAID', 'ON_HOLD')"
)

PO_VARIANCE_SQL_CONDITION = "i.invoice_amount > po.po_total"
PO_VARIANCE_SQL_EXPRESSION = "i.invoice_amount - po.po_total"

PO_VARIANCE_CYPHER_CONDITION = "invoice.invoice_amount > po.committed_amount"
PO_VARIANCE_CYPHER_EXPRESSION = "invoice.invoice_amount - po.committed_amount"

COST_CODE_OVER_BUDGET_SQL_CONDITION = "b.committed_amount > b.budget_amount"
COST_CODE_OVER_BUDGET_SQL_EXPRESSION = "b.committed_amount - b.budget_amount"


BUSINESS_DEFINITIONS: tuple[BusinessTermDefinition, ...] = (
    BusinessTermDefinition(
        slug="po-variance",
        term="PO variance",
        definition=(
            "An invoice has a PO variance when the invoice amount is greater than the "
            "committed purchase order amount for the same PO."
        ),
        grain="One invoice matched to one purchase order.",
        calculation="invoice_amount - po_total",
        applies_when="invoice_amount > po_total",
        fields=(
            "invoices.invoice_amount",
            "invoices.po_id",
            "purchase_orders.po_id",
            "purchase_orders.po_total",
        ),
        relationships=("Invoice -[:AGAINST_PO]-> PurchaseOrder",),
        used_by=(
            "GET /api/projects/{project_id}/po-variances",
            "GET /api/properties/{property_id}/po-variance-paths",
            "backend/app/semantic_query",
            "backend/app/graph/queries.py",
        ),
        synonyms=(
            "po variance",
            "purchase order variance",
            "invoice over po",
            "invoice exceeds po",
            "invoice amount greater than po amount",
            "invoice amounts greater than po amounts",
            "invoice amount greater than its po amount",
            "invoice amounts greater than their po amounts",
            "invoice amount exceeds po amount",
            "invoice amounts exceed po amounts",
            "over purchase order",
        ),
    ),
    BusinessTermDefinition(
        slug="unpaid-invoice",
        term="Unpaid invoice",
        definition=(
            "An invoice is unpaid when no payment has been recorded and the invoice "
            "status is UNPAID or ON_HOLD. Partially paid invoices have an outstanding "
            "balance but are not classified as unpaid under this definition."
        ),
        grain="One invoice.",
        calculation="invoice_amount - paid_amount",
        applies_when="paid_amount = 0 and status is UNPAID or ON_HOLD",
        fields=(
            "invoices.invoice_amount",
            "invoices.paid_amount",
            "invoices.status",
            "invoices.due_date",
        ),
        relationships=("Invoice -[:ISSUED_BY]-> Vendor",),
        used_by=(
            "GET /api/projects/{project_id}/unpaid-invoices",
            "backend/app/semantic_query",
        ),
        synonyms=(
            "unpaid invoice",
            "unpaid invoices",
            "unpaid",
            "not paid",
            "on hold invoice",
            "on hold invoices",
        ),
    ),
    BusinessTermDefinition(
        slug="cost-code-over-budget",
        term="Cost code over budget",
        definition=(
            "A project cost code is over budget when committed spend is greater than the "
            "approved budget amount for the same project, property, and cost code."
        ),
        grain="One project-property-cost-code budget line.",
        calculation="committed_amount - budget_amount",
        applies_when="committed_amount > budget_amount",
        fields=(
            "budgets.project_id",
            "budgets.property_id",
            "budgets.cost_code",
            "budgets.budget_amount",
            "budgets.committed_amount",
        ),
        relationships=("Budget line belongs to project, property, and cost code.",),
        used_by=(
            "GET /api/projects/{project_id}/budget-variances",
            "backend/app/semantic_query",
        ),
        synonyms=(
            "cost code over budget",
            "cost codes over budget",
            "budget variance",
            "budget variances",
            "above budget",
            "over budget",
        ),
    ),
)


def normalize_invoice_status(status: str) -> str:
    return status.strip().upper().replace(" ", "_")


def is_unpaid_invoice(status: str, paid_amount: Decimal) -> bool:
    return paid_amount == Decimal("0") and normalize_invoice_status(status) in UNPAID_INVOICE_STATUSES


def has_po_variance(invoice_amount: Decimal, po_amount: Decimal) -> bool:
    return invoice_amount > po_amount


def po_variance_amount(invoice_amount: Decimal, po_amount: Decimal) -> Decimal:
    return invoice_amount - po_amount


def is_cost_code_over_budget(committed_amount: Decimal, budget_amount: Decimal) -> bool:
    return committed_amount > budget_amount


def cost_code_budget_variance_amount(committed_amount: Decimal, budget_amount: Decimal) -> Decimal:
    return committed_amount - budget_amount
