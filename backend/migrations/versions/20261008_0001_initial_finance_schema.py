"""Create the initial finance query schema.

Revision ID: 20261008_0001
Revises: None
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261008_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "properties",
        sa.Column("property_id", sa.Text(), primary_key=True),
        sa.Column("property_name", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("property_type", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
    )
    op.create_table(
        "vendors",
        sa.Column("vendor_id", sa.Text(), primary_key=True),
        sa.Column("vendor_name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("tax_id", sa.Text(), nullable=False),
    )
    op.create_table(
        "cost_codes",
        sa.Column("cost_code", sa.Text(), primary_key=True),
        sa.Column("cost_category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("budget_owner", sa.Text(), nullable=False),
    )
    op.create_table(
        "purchase_orders",
        sa.Column("po_id", sa.Text(), primary_key=True),
        sa.Column("property_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.Text(), nullable=False),
        sa.Column("po_date", sa.Date(), nullable=False),
        sa.Column("cost_code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("po_quantity", sa.Integer(), nullable=False),
        sa.Column("po_unit_rate", sa.Numeric(20, 4), nullable=False),
        sa.Column("po_total", sa.Numeric(20, 2), nullable=False),
        sa.Column("approval_status", sa.Text(), nullable=False),
    )
    op.create_table(
        "invoices",
        sa.Column("invoice_id", sa.Text(), primary_key=True),
        sa.Column("property_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.Text(), nullable=False),
        sa.Column("po_id", sa.Text(), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("cost_code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("invoice_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("paid_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
    )
    op.create_table(
        "payments",
        sa.Column("payment_id", sa.Text(), primary_key=True),
        sa.Column("invoice_id", sa.Text(), nullable=False),
        sa.Column("property_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("vendor_id", sa.Text(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("payment_reference", sa.Text(), nullable=False),
        sa.Column("payment_status", sa.Text(), nullable=False),
    )
    op.create_table(
        "budgets",
        sa.Column("budget_id", sa.Text(), primary_key=True),
        sa.Column("property_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("cost_code", sa.Text(), nullable=False),
        sa.Column("budget_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("committed_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("actual_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("remaining_budget", sa.Numeric(20, 2), nullable=False),
        sa.UniqueConstraint(
            "property_id",
            "project_id",
            "cost_code",
            name="budgets_scope_cost_code_uidx",
        ),
    )
    op.create_index("invoices_project_id_idx", "invoices", ["project_id"])
    op.create_index("invoices_vendor_id_idx", "invoices", ["vendor_id"])
    op.create_index("invoices_po_id_idx", "invoices", ["po_id"])
    op.create_index("invoices_status_idx", "invoices", ["status"])
    op.create_index("purchase_orders_project_id_idx", "purchase_orders", ["project_id"])
    op.create_index("budgets_project_id_idx", "budgets", ["project_id"])
    op.create_index("budgets_cost_code_idx", "budgets", ["cost_code"])
    op.create_index("payments_invoice_id_idx", "payments", ["invoice_id"])


def downgrade() -> None:
    for table in (
        "budgets",
        "payments",
        "invoices",
        "purchase_orders",
        "cost_codes",
        "vendors",
        "properties",
    ):
        op.drop_table(table)
