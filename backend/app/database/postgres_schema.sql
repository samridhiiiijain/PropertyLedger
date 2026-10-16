CREATE TABLE IF NOT EXISTS properties (
    property_id TEXT PRIMARY KEY,
    property_name TEXT NOT NULL,
    city TEXT NOT NULL,
    property_type TEXT NOT NULL,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendors (
    vendor_id TEXT PRIMARY KEY,
    vendor_name TEXT NOT NULL,
    category TEXT NOT NULL,
    city TEXT NOT NULL,
    tax_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cost_codes (
    cost_code TEXT PRIMARY KEY,
    cost_category TEXT NOT NULL,
    description TEXT NOT NULL,
    budget_owner TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id TEXT PRIMARY KEY,
    property_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    po_date DATE NOT NULL,
    cost_code TEXT NOT NULL,
    description TEXT NOT NULL,
    po_quantity INTEGER NOT NULL,
    po_unit_rate NUMERIC(20, 4) NOT NULL,
    po_total NUMERIC(20, 2) NOT NULL,
    approval_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id TEXT PRIMARY KEY,
    property_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    po_id TEXT NOT NULL,
    invoice_date DATE NOT NULL,
    due_date DATE NOT NULL,
    cost_code TEXT NOT NULL,
    description TEXT NOT NULL,
    invoice_amount NUMERIC(20, 2) NOT NULL,
    paid_amount NUMERIC(20, 2) NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    property_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    payment_date DATE NOT NULL,
    amount NUMERIC(20, 2) NOT NULL,
    payment_reference TEXT NOT NULL,
    payment_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS budgets (
    budget_id TEXT PRIMARY KEY,
    property_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    cost_code TEXT NOT NULL,
    budget_amount NUMERIC(20, 2) NOT NULL,
    committed_amount NUMERIC(20, 2) NOT NULL,
    actual_amount NUMERIC(20, 2) NOT NULL,
    remaining_budget NUMERIC(20, 2) NOT NULL
);

CREATE INDEX IF NOT EXISTS invoices_project_id_idx ON invoices (project_id);
CREATE INDEX IF NOT EXISTS invoices_vendor_id_idx ON invoices (vendor_id);
CREATE INDEX IF NOT EXISTS invoices_po_id_idx ON invoices (po_id);
CREATE INDEX IF NOT EXISTS invoices_status_idx ON invoices (status);
CREATE INDEX IF NOT EXISTS purchase_orders_project_id_idx ON purchase_orders (project_id);
CREATE INDEX IF NOT EXISTS budgets_project_id_idx ON budgets (project_id);
CREATE INDEX IF NOT EXISTS budgets_cost_code_idx ON budgets (cost_code);
CREATE UNIQUE INDEX IF NOT EXISTS budgets_scope_cost_code_uidx
    ON budgets (property_id, project_id, cost_code);
CREATE INDEX IF NOT EXISTS payments_invoice_id_idx ON payments (invoice_id);
