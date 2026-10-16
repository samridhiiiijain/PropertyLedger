"""Generate entirely fictional demo inputs; never reads company data."""
from pathlib import Path
import csv

ROOT = Path(__file__).resolve().parent


def write_csv(name, header, rows):
    folder = ROOT / "structured"
    folder.mkdir(exist_ok=True)
    with (folder / f"{name}.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header.split(","))
        writer.writerows(rows)


def document(filename, metadata, body):
    folder = ROOT / "documents"
    folder.mkdir(exist_ok=True)
    lines = [f"{key}: {value}" for key, value in metadata.items()]
    text = "\n".join(lines) + "\n\nSYNTHETIC DEMO DOCUMENT. All entities and amounts are fictional.\n\n" + body + "\n"
    (folder / filename).write_text(text, encoding="utf-8")


def generate():
    write_csv("properties", "property_id,property_name,city,property_type,project_id,status", [
        ("P901", "Demo Orchard Tower", "Sample City A", "Residential Tower", "PR901", "Active"),
        ("P902", "Demo Lantern Arcade", "Sample City B", "Commercial", "PR902", "Active"),
        ("P903", "Demo Meadow Court", "Sample City C", "Residential", "PR903", "On Hold"),
    ])
    write_csv("vendors", "vendor_id,vendor_name,category,city,tax_id", [
        ("V901", "Demo Pebble Materials", "Construction Materials", "Sample City A", "DEMO-TAX-901"),
        ("V902", "Demo Spark Wiring", "Electrical", "Sample City A", "DEMO-TAX-902"),
        ("V903", "Demo Breeze Mechanical", "HVAC", "Sample City B", "DEMO-TAX-903"),
        ("V904", "Demo Mosaic Interiors", "Interior Finishes", "Sample City C", "DEMO-TAX-904"),
        ("V905", "Demo Foundation Works", "Civil Works", "Sample City B", "DEMO-TAX-905"),
    ])
    write_csv("cost_codes", "cost_code,cost_category,description,budget_owner", [
        ("CC901", "Civil & Concrete", "Demo structural materials and civil works", "Demo Project Lead"),
        ("CC902", "Electrical", "Demo cables and distribution equipment", "Demo Services Lead"),
        ("CC903", "HVAC", "Demo ventilation equipment and installation", "Demo Services Lead"),
        ("CC904", "Interior Finishes", "Demo tiles and interior materials", "Demo Design Lead"),
    ])
    # property, project, vendor, cost code, description, quantity, rate, invoice, paid, status
    scenarios = [
        ("P901", "PR901", "V901", "CC901", "Demo structural blocks", 100, 1000, 112000, 0, "Unpaid"),
        ("P901", "PR901", "V902", "CC902", "Demo cable installation", 200, 300, 66000, 22000, "Partially Paid"),
        ("P901", "PR901", "V903", "CC903", "Demo ventilation advance", 1, 95000, 95000, 0, "Unpaid"),
        ("P901", "PR901", "V904", "CC904", "Demo lobby tiles", 100, 400, 45000, 0, "On Hold"),
        ("P902", "PR902", "V905", "CC901", "Demo foundation work", 1, 80000, 80000, 80000, "Paid"),
        ("P902", "PR902", "V901", "CC901", "Demo paving blocks", 60, 500, 30000, 0, "Unpaid"),
        ("P903", "PR903", "V904", "CC904", "Demo corridor tiles", 100, 250, 28000, 0, "On Hold"),
        ("P901", "PR901", "V901", "CC901", "Demo extra structural blocks", 20, 1000, 23000, 0, "Unpaid"),
    ]
    pos, invoices, payments = [], [], []
    for index, row in enumerate(scenarios, 1):
        prop, project, vendor, code, description, quantity, rate, amount, paid, status = row
        inv, po = f"INV{9100 + index}", f"PO{9200 + index}"
        pos.append((po, prop, project, vendor, "2026-01-05", code, description, quantity, rate, quantity * rate, "Approved"))
        invoices.append((inv, prop, project, vendor, po, "2026-01-15", "2026-02-14", code, description, amount, paid, status))
        if paid:
            payments.append((f"PAY{9300 + len(payments) + 1}", inv, prop, project, vendor, "2026-01-25", paid, f"DEMO-PAYMENT-{index}", "Completed"))
    write_csv("purchase_orders", "po_id,property_id,project_id,vendor_id,po_date,cost_code,description,po_quantity,po_unit_rate,po_total,approval_status", pos)
    write_csv("invoices", "invoice_id,property_id,project_id,vendor_id,po_id,invoice_date,due_date,cost_code,description,invoice_amount,paid_amount,status", invoices)
    write_csv("payments", "payment_id,invoice_id,property_id,project_id,vendor_id,payment_date,amount,payment_reference,payment_status", payments)
    budgets = []
    for index, (project, code, limit) in enumerate([
        ("PR901", "CC901", 120000), ("PR901", "CC902", 70000),
        ("PR901", "CC903", 110000), ("PR901", "CC904", 42000),
        ("PR902", "CC901", 130000), ("PR903", "CC904", 35000),
    ], 1):
        selected = [r for r in scenarios if r[1] == project and r[3] == code]
        committed = sum(r[7] for r in selected)
        actual = sum(r[8] for r in selected)
        budgets.append((f"B{9400 + index}", selected[0][0], project, code, limit, committed, actual, limit - committed))
    write_csv("budgets", "budget_id,property_id,project_id,cost_code,budget_amount,committed_amount,actual_amount,remaining_budget", budgets)

    def doc(name, kind, body, **scope):
        metadata = {"Document ID": name, "Document Type": kind, "Document Date": "2026-01-20"}
        metadata.update({key.replace("_", " "): value for key, value in scope.items()})
        document(f"{name}.txt", metadata, body)

    for index in (1, 2, 4, 7):
        prop, project, vendor, code, description, quantity, rate, amount, paid, status = scenarios[index - 1]
        body = f"Invoice INV{9100 + index} covers {description}. Total: INR {amount:,}. Purchase order PO{9200 + index}: INR {quantity * rate:,}."
        if index in (4, 7):
            body += f" Payment is on hold. Obtain a corrected invoice or written approval for the INR {amount - quantity * rate:,} variance before release."
        doc(f"DOC-DEMO-INV{9100 + index}", "Vendor Invoice" if index in (1, 2, 7) else "Reconciliation Note", body,
            Invoice_ID=f"INV{9100 + index}", PO_ID=f"PO{9200 + index}", Property_ID=prop, Project_ID=project, Vendor_ID=vendor, Cost_Code=code)
    doc("DOC-DEMO-CONTRACT-V903", "Contract",
        "Demo Breeze Mechanical supplies ventilation equipment for Demo Orchard Tower. An advance requires an approved purchase order, a signed advance request and current vendor registration documentation.",
        Property_ID="P901", Project_ID="PR901", Vendor_ID="V903")
    doc("DOC-DEMO-APP-9103", "Approval Email",
        "The INR 95,000 ventilation advance for INV9103 against PO9203 is conditionally approved. The signed advance request and current vendor registration documentation have not been received. Do not release payment until both are received.",
        Property_ID="P901", Project_ID="PR901", Vendor_ID="V903", Invoice_ID="INV9103", PO_ID="PO9203")
    doc("DOC-DEMO-PROCEDURE", "Finance Procedure",
        "Demo invoice approval procedure: verify project and vendor; match the invoice to its approved purchase order; check budget availability; collect required supporting approvals; reconcile completed payments. Escalate discrepancies for review.")
    doc("DOC-DEMO-CHECK-PR901", "Finance Checklist",
        "Before payment, require a readable invoice, approved purchase order, valid cost code, current vendor documentation and any advance approval. An invoice exceeding its purchase order requires written variance approval.",
        Property_ID="P901", Project_ID="PR901")
    doc("DOC-DEMO-RECON-PR901", "Reconciliation Note",
        "INV9101 exceeds PO9201 by INR 12,000. INV9102 exceeds PO9202 by INR 6,000 and has a completed payment of INR 22,000. INV9104 exceeds PO9204 by INR 5,000. INV9103 matches PO9203 but supporting advance documents remain missing.",
        Property_ID="P901", Project_ID="PR901")
    doc("DOC-DEMO-DRAW-PR901", "Draw Package",
        "The demo draw package groups costs under CC901, CC902, CC903 and CC904. Resolve invoice-to-PO variances and missing advance documents before including affected invoices in a payment run.",
        Property_ID="P901", Project_ID="PR901")


if __name__ == "__main__":
    generate()
    print("Generated 7 synthetic CSV tables and 10 synthetic documents in sample_data/.")
