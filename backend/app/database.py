from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRUCTURED_DATA_DIR = PROJECT_ROOT / "data" / "structured"


TABLES: dict[str, tuple[str, ...]] = {
    "properties": (
        "property_id TEXT PRIMARY KEY",
        "property_name TEXT NOT NULL",
        "city TEXT NOT NULL",
        "property_type TEXT NOT NULL",
        "project_id TEXT NOT NULL",
        "status TEXT NOT NULL",
    ),
    "vendors": (
        "vendor_id TEXT PRIMARY KEY",
        "vendor_name TEXT NOT NULL",
        "category TEXT NOT NULL",
        "city TEXT NOT NULL",
        "tax_id TEXT NOT NULL",
    ),
    "cost_codes": (
        "cost_code TEXT PRIMARY KEY",
        "cost_category TEXT NOT NULL",
        "description TEXT NOT NULL",
        "budget_owner TEXT NOT NULL",
    ),
    "purchase_orders": (
        "po_id TEXT PRIMARY KEY",
        "property_id TEXT NOT NULL",
        "project_id TEXT NOT NULL",
        "vendor_id TEXT NOT NULL",
        "po_date TEXT NOT NULL",
        "cost_code TEXT NOT NULL",
        "description TEXT NOT NULL",
        "po_quantity INTEGER NOT NULL",
        "po_unit_rate NUMERIC NOT NULL",
        "po_total NUMERIC NOT NULL",
        "approval_status TEXT NOT NULL",
    ),
    "invoices": (
        "invoice_id TEXT PRIMARY KEY",
        "property_id TEXT NOT NULL",
        "project_id TEXT NOT NULL",
        "vendor_id TEXT NOT NULL",
        "po_id TEXT NOT NULL",
        "invoice_date TEXT NOT NULL",
        "due_date TEXT NOT NULL",
        "cost_code TEXT NOT NULL",
        "description TEXT NOT NULL",
        "invoice_amount NUMERIC NOT NULL",
        "paid_amount NUMERIC NOT NULL",
        "status TEXT NOT NULL",
    ),
    "payments": (
        "payment_id TEXT PRIMARY KEY",
        "invoice_id TEXT NOT NULL",
        "property_id TEXT NOT NULL",
        "project_id TEXT NOT NULL",
        "vendor_id TEXT NOT NULL",
        "payment_date TEXT NOT NULL",
        "amount NUMERIC NOT NULL",
        "payment_reference TEXT NOT NULL",
        "payment_status TEXT NOT NULL",
    ),
    "budgets": (
        "budget_id TEXT PRIMARY KEY",
        "property_id TEXT NOT NULL",
        "project_id TEXT NOT NULL",
        "cost_code TEXT NOT NULL",
        "budget_amount NUMERIC NOT NULL",
        "committed_amount NUMERIC NOT NULL",
        "actual_amount NUMERIC NOT NULL",
        "remaining_budget NUMERIC NOT NULL",
    ),
}


def create_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    _create_schema(connection)
    _load_csv_data(connection)
    return connection


def _create_schema(connection: sqlite3.Connection) -> None:
    for table_name, columns in TABLES.items():
        connection.execute(f"CREATE TABLE {table_name} ({', '.join(columns)})")


def _load_csv_data(connection: sqlite3.Connection) -> None:
    for table_name in TABLES:
        csv_path = STRUCTURED_DATA_DIR / f"{table_name}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"Missing structured data file: {csv_path}")

        with csv_path.open(newline="", encoding="utf-8") as csv_file:
            rows = tuple(csv.DictReader(csv_file))

        if not rows:
            continue

        columns = tuple(rows[0].keys())
        placeholders = ", ".join("?" for _ in columns)
        column_list = ", ".join(columns)
        values = [tuple(row[column] for column in columns) for row in rows]
        connection.executemany(
            f"INSERT INTO {table_name} ({column_list}) VALUES ({placeholders})",
            values,
        )

    connection.commit()
