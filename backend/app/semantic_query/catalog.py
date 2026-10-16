from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryObject:
    name: str
    table: str
    alias: str
    synonyms: tuple[str, ...]
    default_fields: tuple[str, ...]
    allowed_fields: tuple[str, ...]


@dataclass(frozen=True)
class QueryMetric:
    name: str
    synonyms: tuple[str, ...]
    base_object: str
    kind: str
    related_table: str
    related_alias: str
    join_condition: str
    condition_sql: str
    required_tables: tuple[str, ...] = ()
    comparison_predicate: bool = False


TABLE_ALIASES: dict[str, str] = {
    "properties": "p",
    "invoices": "i",
    "vendors": "v",
    "budgets": "b",
    "purchase_orders": "po",
    "payments": "pmt",
}

JOIN_SPECS: dict[str, dict[str, str]] = {
    "invoice": {
        "properties": "JOIN properties p ON p.property_id = i.property_id",
        "vendors": "JOIN vendors v ON v.vendor_id = i.vendor_id",
        "purchase_orders": "JOIN purchase_orders po ON po.po_id = i.po_id",
        "budgets": (
            "LEFT JOIN budgets b ON b.property_id = i.property_id "
            "AND b.project_id = i.project_id AND b.cost_code = i.cost_code"
        ),
    },
    "purchase_order": {
        "properties": "JOIN properties p ON p.property_id = po.property_id",
        "vendors": "JOIN vendors v ON v.vendor_id = po.vendor_id",
    },
    "payment": {
        "invoices": "JOIN invoices i ON i.invoice_id = pmt.invoice_id",
        "properties": "JOIN properties p ON p.property_id = pmt.property_id",
        "vendors": "JOIN vendors v ON v.vendor_id = pmt.vendor_id",
    },
}

FIELD_EXPRESSIONS: dict[str, str] = {
    "budgets.budget_variance_amount": "b.committed_amount - b.budget_amount",
    "invoices.outstanding_amount": "i.invoice_amount - i.paid_amount",
    "invoices.po_variance_amount": "i.invoice_amount - po.po_total",
}

FIELD_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "invoices.po_variance_amount": ("purchase_orders",),
}

FIELD_RESULT_ALIASES: dict[str, str] = {
    "properties.property_name": "property_name",
    "properties.city": "property_city",
    "properties.property_type": "property_type",
    "properties.status": "property_status",
    "vendors.vendor_name": "vendor_name",
    "vendors.category": "vendor_category",
    "vendors.city": "vendor_city",
    "vendors.tax_id": "vendor_tax_id",
}

VALUE_LOOKUP_FIELDS: tuple[str, ...] = (
    "properties.city",
    "properties.property_name",
    "properties.property_type",
    "properties.status",
    "properties.project_id",
    "invoices.project_id",
    "invoices.invoice_id",
    "invoices.property_id",
    "invoices.vendor_id",
    "invoices.status",
    "vendors.vendor_id",
    "vendors.vendor_name",
    "vendors.category",
    "vendors.city",
    "vendors.tax_id",
    "budgets.project_id",
    "budgets.property_id",
    "budgets.cost_code",
    "purchase_orders.po_id",
    "purchase_orders.project_id",
    "purchase_orders.property_id",
    "purchase_orders.vendor_id",
    "purchase_orders.cost_code",
    "purchase_orders.approval_status",
    "payments.payment_id",
    "payments.invoice_id",
    "payments.project_id",
    "payments.property_id",
    "payments.vendor_id",
    "payments.payment_status",
)


OBJECTS: dict[str, QueryObject] = {
    "property": QueryObject(
        name="property",
        table="properties",
        alias="p",
        synonyms=("property", "properties", "prop", "props", "site", "building"),
        default_fields=(
            "properties.property_id",
            "properties.property_name",
            "properties.city",
            "properties.property_type",
            "properties.status",
            "properties.project_id",
        ),
        allowed_fields=(
            "properties.property_id",
            "properties.property_name",
            "properties.city",
            "properties.property_type",
            "properties.status",
            "properties.project_id",
        ),
    ),
    "invoice": QueryObject(
        name="invoice",
        table="invoices",
        alias="i",
        synonyms=("invoice", "invoices", "inv", "invs", "bill", "bills"),
        default_fields=(
            "invoices.invoice_id",
            "invoices.property_id",
            "invoices.project_id",
            "invoices.vendor_id",
            "invoices.po_id",
            "invoices.cost_code",
            "invoices.invoice_date",
            "invoices.due_date",
            "invoices.invoice_amount",
            "invoices.paid_amount",
            "invoices.outstanding_amount",
            "invoices.status",
            "properties.property_name",
            "properties.city",
            "properties.property_type",
            "properties.status",
            "properties.project_id",
            "vendors.vendor_name",
            "vendors.category",
            "vendors.city",
            "vendors.tax_id",
            "purchase_orders.po_total",
            "invoices.po_variance_amount",
            "budgets.budget_id",
            "budgets.budget_amount",
        ),
        allowed_fields=(
            "invoices.invoice_id",
            "invoices.property_id",
            "invoices.project_id",
            "invoices.vendor_id",
            "invoices.po_id",
            "invoices.cost_code",
            "invoices.invoice_amount",
            "invoices.paid_amount",
            "invoices.outstanding_amount",
            "invoices.status",
            "invoices.due_date",
            "invoices.invoice_date",
            "properties.property_name",
            "properties.city",
            "properties.property_type",
            "properties.status",
            "properties.project_id",
            "vendors.vendor_name",
            "vendors.category",
            "vendors.city",
            "vendors.tax_id",
            "purchase_orders.po_total",
            "invoices.po_variance_amount",
            "budgets.budget_id",
            "budgets.budget_amount",
        ),
    ),
    "vendor": QueryObject(
        name="vendor",
        table="vendors",
        alias="v",
        synonyms=("vendor", "vendors", "supplier", "suppliers", "contractor", "contractors"),
        default_fields=(
            "vendors.vendor_id",
            "vendors.vendor_name",
            "vendors.category",
            "vendors.city",
        ),
        allowed_fields=(
            "vendors.vendor_id",
            "vendors.vendor_name",
            "vendors.category",
            "vendors.city",
        ),
    ),
    "budget": QueryObject(
        name="budget",
        table="budgets",
        alias="b",
        synonyms=("budget", "budgets", "cost code", "cost codes"),
        default_fields=(
            "budgets.budget_id",
            "budgets.project_id",
            "budgets.property_id",
            "budgets.cost_code",
            "budgets.budget_amount",
            "budgets.committed_amount",
            "budgets.budget_variance_amount",
        ),
        allowed_fields=(
            "budgets.budget_id",
            "budgets.project_id",
            "budgets.property_id",
            "budgets.cost_code",
            "budgets.budget_amount",
            "budgets.committed_amount",
            "budgets.budget_variance_amount",
        ),
    ),
    "purchase_order": QueryObject(
        name="purchase_order",
        table="purchase_orders",
        alias="po",
        synonyms=("purchase order", "purchase orders", "po", "pos"),
        default_fields=(
            "purchase_orders.po_id", "purchase_orders.property_id", "purchase_orders.project_id",
            "purchase_orders.vendor_id", "purchase_orders.cost_code", "purchase_orders.po_date",
            "purchase_orders.po_total", "purchase_orders.approval_status",
        ),
        allowed_fields=(
            "purchase_orders.po_id", "purchase_orders.property_id", "purchase_orders.project_id",
            "purchase_orders.vendor_id", "purchase_orders.cost_code", "purchase_orders.po_date",
            "purchase_orders.po_quantity", "purchase_orders.po_unit_rate", "purchase_orders.po_total",
            "purchase_orders.approval_status", "properties.property_name", "vendors.vendor_name",
        ),
    ),
    "payment": QueryObject(
        name="payment",
        table="payments",
        alias="pmt",
        synonyms=("payment", "payments", "settlement", "settlements"),
        default_fields=(
            "payments.payment_id", "payments.invoice_id", "payments.property_id", "payments.project_id",
            "payments.vendor_id", "payments.payment_date", "payments.amount",
            "payments.payment_reference", "payments.payment_status",
        ),
        allowed_fields=(
            "payments.payment_id", "payments.invoice_id", "payments.property_id", "payments.project_id",
            "payments.vendor_id", "payments.payment_date", "payments.amount",
            "payments.payment_reference", "payments.payment_status", "invoices.invoice_id",
            "invoices.project_id", "properties.project_id",
        ),
    ),
}


FILTER_FIELDS: dict[str, tuple[str, ...]] = {
    "properties.city": ("city", "location", "in"),
    "properties.property_name": ("property name", "named", "called"),
    "properties.property_type": ("property type", "type"),
    "properties.status": ("property status", "status"),
    "properties.project_id": ("project", "project id"),
    "invoices.project_id": ("project", "project id"),
    "invoices.invoice_id": ("invoice", "invoice id"),
    "invoices.property_id": ("property id",),
    "invoices.vendor_id": ("vendor id", "vendor"),
    "invoices.status": ("invoice status", "status"),
    "vendors.vendor_id": ("vendor id",),
    "vendors.vendor_name": ("vendor name", "supplier name", "contractor name"),
    "vendors.category": ("vendor category", "supplier category", "category"),
    "vendors.city": ("vendor city", "city", "location"),
    "budgets.project_id": ("project", "project id"),
    "budgets.property_id": ("property id",),
    "budgets.cost_code": ("cost code",),
    "purchase_orders.po_id": ("purchase order", "po", "po id"),
    "purchase_orders.project_id": ("project", "project id"),
    "purchase_orders.vendor_id": ("vendor", "vendor id"),
    "purchase_orders.approval_status": ("approval status",),
    "payments.payment_id": ("payment", "payment id"),
    "payments.invoice_id": ("invoice", "invoice id"),
    "payments.payment_status": ("payment status",),
}


METRICS: dict[str, QueryMetric] = {
    "unpaid_invoice_count": QueryMetric(
        name="unpaid_invoice_count",
        synonyms=(
            "unpaid invoice",
            "unpaid invoices",
            "invoice is unpaid",
            "invoice are unpaid",
            "invoices are unpaid",
            "invoice unpaid",
            "invoices unpaid",
            "not paid invoice",
            "not paid invoices",
            "pending invoice",
            "pending invoices",
            "open invoice",
            "open invoices",
        ),
        base_object="property",
        kind="count",
        related_table="invoices",
        related_alias="i",
        join_condition="i.property_id = p.property_id",
        condition_sql=(
            "i.paid_amount = 0 "
            "AND UPPER(REPLACE(i.status, ' ', '_')) IN ('UNPAID', 'ON_HOLD')"
        ),
    ),
    "unpaid_invoice": QueryMetric(
        name="unpaid_invoice",
        synonyms=(
            "unpaid invoice",
            "unpaid invoices",
            "invoice is unpaid",
            "invoice are unpaid",
            "invoices are unpaid",
            "invoice unpaid",
            "invoices unpaid",
            "not paid invoice",
            "not paid invoices",
            "pending invoice",
            "pending invoices",
            "open invoice",
            "open invoices",
        ),
        base_object="invoice",
        kind="row_filter",
        related_table="invoices",
        related_alias="i",
        join_condition="",
        condition_sql=(
            "i.paid_amount = 0 "
            "AND UPPER(REPLACE(i.status, ' ', '_')) IN ('UNPAID', 'ON_HOLD')"
        ),
    ),
    "po_variance_invoice": QueryMetric(
        name="po_variance_invoice",
        synonyms=(
            "po variance",
            "purchase order variance",
            "invoice over po",
            "invoice exceeds po",
            "invoice amount greater than po amount",
            "invoice amounts greater than po amounts",
            "invoice amounts greater than their po amounts",
            "invoice amount greater than its po amount",
            "invoice amount exceeds po amount",
            "invoice amounts exceed po amounts",
            "invoice amounts exceed their po amounts",
            "over purchase order",
        ),
        base_object="invoice",
        kind="row_filter",
        related_table="purchase_orders",
        related_alias="po",
        join_condition="po.po_id = i.po_id",
        condition_sql="i.invoice_amount > po.po_total",
        required_tables=("purchase_orders",),
        comparison_predicate=True,
    ),
    "vendor_unpaid_invoice_count": QueryMetric(
        name="vendor_unpaid_invoice_count",
        synonyms=(
            "unpaid invoice",
            "unpaid invoices",
            "invoice is unpaid",
            "invoice are unpaid",
            "invoices are unpaid",
            "invoice unpaid",
            "invoices unpaid",
            "not paid invoice",
            "not paid invoices",
            "pending invoice",
            "pending invoices",
            "open invoice",
            "open invoices",
        ),
        base_object="vendor",
        kind="count",
        related_table="invoices",
        related_alias="i",
        join_condition="i.vendor_id = v.vendor_id",
        condition_sql=(
            "i.paid_amount = 0 "
            "AND UPPER(REPLACE(i.status, ' ', '_')) IN ('UNPAID', 'ON_HOLD')"
        ),
    ),
    "cost_code_over_budget": QueryMetric(
        name="cost_code_over_budget",
        synonyms=(
            "cost code over budget",
            "cost codes over budget",
            "budget variance",
            "budget variances",
            "above budget",
            "over budget",
        ),
        base_object="budget",
        kind="row_filter",
        related_table="budgets",
        related_alias="b",
        join_condition="",
        condition_sql="b.committed_amount > b.budget_amount",
        comparison_predicate=True,
    ),
}


ABBREVIATIONS: dict[str, str] = {
    "r": "are",
    "u": "you",
    "prop": "property",
    "props": "properties",
    "inv": "invoice",
    "invs": "invoices",
    "amt": "amount",
    "bal": "balance",
    "pmt": "payment",
    "pmts": "payments",
}
