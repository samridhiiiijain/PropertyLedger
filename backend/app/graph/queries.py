from __future__ import annotations


UPSERT_GRAPH_QUERY = """
UNWIND $invoices AS row
MERGE (property:Property {property_id: row.property_id, projection_version: $projection_version})
MERGE (project:Project {project_id: row.project_id, projection_version: $projection_version})
MERGE (vendor:Vendor {vendor_id: row.vendor_id, projection_version: $projection_version})
MERGE (po:PurchaseOrder {po_id: row.po_id, projection_version: $projection_version})
MERGE (costCode:CostCode {cost_code: row.cost_code, projection_version: $projection_version})
MERGE (invoice:Invoice {invoice_id: row.invoice_id, projection_version: $projection_version})
MERGE (property)-[:HAS_PROJECT]->(project)
MERGE (project)-[:HAS_INVOICE]->(invoice)
MERGE (invoice)-[:FOR_PROPERTY]->(property)
MERGE (invoice)-[:ISSUED_BY]->(vendor)
MERGE (invoice)-[:AGAINST_PO]->(po)
MERGE (po)-[:ORDERED_FROM]->(vendor)
MERGE (invoice)-[:USES_COST_CODE]->(costCode)
MERGE (po)-[:USES_COST_CODE]->(costCode)
"""

UPSERT_DOCUMENTS_QUERY = """
UNWIND $documents AS row
MERGE (document:Document {document_id: row.document_id, projection_version: $projection_version})
"""

UPSERT_DOCUMENT_LINKS_QUERY = """
UNWIND $links AS row
MATCH (invoice:Invoice {invoice_id: row.invoice_id, projection_version: $projection_version})
MATCH (document:Document {document_id: row.document_id, projection_version: $projection_version})
MERGE (invoice)-[relationship:SUPPORTED_BY]->(document)
SET relationship.link_type = row.link_type,
    relationship.matched_identifiers = row.matched_identifiers
"""

CREATE_PROJECTION_VERSION_QUERY = """
MERGE (version:GraphProjectionVersion {projection_version: $projection_version})
SET version.projection_name = $projection_name,
    version.status = 'building',
    version.source_fingerprint = $source_fingerprint,
    version.started_at = datetime(),
    version.completed_at = null,
    version.expected_counts = $expected_counts
"""

PROJECTION_COUNTS_QUERY = """
CALL () { MATCH (node:Property {projection_version: $projection_version}) RETURN count(node) AS properties }
CALL () { MATCH (node:Project {projection_version: $projection_version}) RETURN count(node) AS projects }
CALL () { MATCH (node:Vendor {projection_version: $projection_version}) RETURN count(node) AS vendors }
CALL () { MATCH (node:PurchaseOrder {projection_version: $projection_version}) RETURN count(node) AS purchase_orders }
CALL () { MATCH (node:CostCode {projection_version: $projection_version}) RETURN count(node) AS cost_codes }
CALL () { MATCH (node:Invoice {projection_version: $projection_version}) RETURN count(node) AS invoices }
CALL () { MATCH (node:Document {projection_version: $projection_version}) RETURN count(node) AS documents }
CALL () {
  MATCH (:Invoice {projection_version: $projection_version})-[edge:SUPPORTED_BY]->
        (:Document {projection_version: $projection_version})
  RETURN count(edge) AS document_links
}
RETURN properties, projects, vendors, purchase_orders, cost_codes,
       invoices, documents, document_links
"""

ACTIVATE_PROJECTION_QUERY = """
MATCH (version:GraphProjectionVersion {
  projection_version: $projection_version,
  projection_name: $projection_name
})
WHERE version.status IN ['building', 'complete']
SET version.status = 'complete',
    version.completed_at = coalesce(version.completed_at, datetime()),
    version.actual_counts = $actual_counts
MERGE (projection:GraphProjection {name: $projection_name})
SET projection.active_version = $projection_version,
    projection.activated_at = datetime()
RETURN projection.active_version AS active_version
"""

ACTIVATE_EXISTING_PROJECTION_QUERY = """
MATCH (version:GraphProjectionVersion {
  projection_version: $projection_version,
  projection_name: $projection_name,
  status: 'complete'
})
MERGE (projection:GraphProjection {name: $projection_name})
SET projection.active_version = version.projection_version,
    projection.activated_at = datetime()
RETURN projection.active_version AS active_version
"""

LIST_PROJECTION_VERSIONS_QUERY = """
MATCH (version:GraphProjectionVersion {projection_name: $projection_name})
OPTIONAL MATCH (projection:GraphProjection {name: $projection_name})
RETURN version.projection_version AS projection_version,
       version.status AS status,
       version.completed_at AS completed_at,
       projection.active_version = version.projection_version AS active
ORDER BY version.completed_at DESC, version.projection_version DESC
"""

DELETE_PROJECTION_VERSION_QUERY = """
MATCH (node {projection_version: $projection_version})
WHERE NOT node:GraphProjectionVersion
DETACH DELETE node
WITH count(node) AS deleted_nodes
MATCH (version:GraphProjectionVersion {projection_version: $projection_version})
DELETE version
RETURN deleted_nodes
"""

DELETE_LEGACY_GRAPH_QUERY = """
MATCH (node)
WHERE node.projection_version IS NULL
  AND any(label IN labels(node) WHERE label IN $managed_labels)
DETACH DELETE node
RETURN count(node) AS deleted_nodes
"""

TRACE_PO_VARIANCE_PATHS_QUERY = """
MATCH (projection:GraphProjection {name: $projection_name})
WITH projection.active_version AS projection_version
MATCH
  (property:Property {property_id: $property_id, projection_version: projection_version})
    -[:HAS_PROJECT]->(project:Project {projection_version: projection_version})
    -[:HAS_INVOICE]->(invoice:Invoice {projection_version: projection_version})
    -[:AGAINST_PO]->(po:PurchaseOrder {projection_version: projection_version})
    -[:ORDERED_FROM]->(vendor:Vendor {projection_version: projection_version})
MATCH (invoice)-[:USES_COST_CODE]->(costCode:CostCode {projection_version: projection_version})
OPTIONAL MATCH (invoice)-[support:SUPPORTED_BY]->
               (document:Document {projection_version: projection_version})
WITH property, project, invoice, po, vendor, costCode, document, support
ORDER BY invoice.invoice_id, document.document_id
RETURN {
  finding: invoice.invoice_id + " is linked to " + po.po_id,
  status: CASE WHEN document IS NULL THEN "missing_evidence" ELSE "supported" END,
  invoice_id: invoice.invoice_id,
  property_id: property.property_id,
  project_id: project.project_id,
  po_id: po.po_id,
  vendor_id: vendor.vendor_id,
  cost_code: costCode.cost_code,
  document_id: document.document_id,
  path_nodes: [
    {label: "Property", id: property.property_id, display: property.property_id},
    {label: "Project", id: project.project_id, display: project.project_id},
    {label: "Invoice", id: invoice.invoice_id, display: invoice.invoice_id},
    {label: "PurchaseOrder", id: po.po_id, display: po.po_id},
    {label: "Vendor", id: vendor.vendor_id, display: vendor.vendor_id}
  ] + CASE WHEN document IS NULL THEN [] ELSE
    [{label: "Document", id: document.document_id, display: document.document_id}] END,
  path_edges: [
    {type: "HAS_PROJECT", from: property.property_id, to: project.project_id},
    {type: "HAS_INVOICE", from: project.project_id, to: invoice.invoice_id},
    {type: "AGAINST_PO", from: invoice.invoice_id, to: po.po_id},
    {type: "ORDERED_FROM", from: po.po_id, to: vendor.vendor_id}
  ] + CASE WHEN document IS NULL THEN [] ELSE
    [{type: "SUPPORTED_BY", from: invoice.invoice_id, to: document.document_id}] END
} AS path
LIMIT $result_limit
"""
