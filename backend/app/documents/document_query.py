from __future__ import annotations

import re

from ..models import DocumentMetadata
from .document_types import QueryIdentifiers


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?")
PROJECT_PATTERN = re.compile(r"\bPR\d{3}\b", re.IGNORECASE)
PROPERTY_PATTERN = re.compile(r"\bP\d{3}\b", re.IGNORECASE)
VENDOR_PATTERN = re.compile(r"\bV\d{3}\b", re.IGNORECASE)
INVOICE_PATTERN = re.compile(r"\bINV\d{4}\b", re.IGNORECASE)
PO_PATTERN = re.compile(r"\bPO\d{4}\b", re.IGNORECASE)
COST_CODE_PATTERN = re.compile(r"\bCC\d{3}\b", re.IGNORECASE)
DOCUMENT_ID_PATTERN = re.compile(r"\bDOC-[A-Z0-9-]+\b", re.IGNORECASE)


def first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(0).upper() if match else None


def tokens(text: str) -> tuple[str, ...]:
    return tuple(token.lower() for token in TOKEN_PATTERN.findall(text))


def extract_identifiers(question: str) -> QueryIdentifiers:
    return QueryIdentifiers(
        document_id=first_match(DOCUMENT_ID_PATTERN, question),
        property_id=first_match(PROPERTY_PATTERN, question),
        project_id=first_match(PROJECT_PATTERN, question),
        vendor_id=first_match(VENDOR_PATTERN, question),
        invoice_id=first_match(INVOICE_PATTERN, question),
        po_id=first_match(PO_PATTERN, question),
        cost_code=first_match(COST_CODE_PATTERN, question),
    )


def has_identifier_conflict(
    metadata: DocumentMetadata,
    identifiers: QueryIdentifiers,
    project_id: str | None,
) -> bool:
    requested_project_id = identifiers.project_id or project_id
    checks = {
        "property_id": identifiers.property_id,
        "project_id": requested_project_id,
        "vendor_id": identifiers.vendor_id,
        "invoice_id": identifiers.invoice_id,
        "po_id": identifiers.po_id,
        "cost_code": identifiers.cost_code,
    }

    for field_name, requested_value in checks.items():
        if requested_value is None:
            continue
        metadata_value = getattr(metadata, field_name)
        if metadata_value is not None and metadata_value != requested_value:
            return True

    return False


def metadata_match_boost(
    question: str,
    metadata: DocumentMetadata,
    identifiers: QueryIdentifiers,
    project_id: str | None,
) -> float:
    normalized = question.lower()
    boost = 0.0

    exact_checks = {
        "document_id": identifiers.document_id,
        "property_id": identifiers.property_id,
        "project_id": identifiers.project_id or project_id,
        "vendor_id": identifiers.vendor_id,
        "invoice_id": identifiers.invoice_id,
        "po_id": identifiers.po_id,
        "cost_code": identifiers.cost_code,
    }
    for field_name, requested_value in exact_checks.items():
        if requested_value is not None and getattr(metadata, field_name) == requested_value:
            boost += 0.35

    document_type = metadata.document_type.lower()
    if "procedure" in normalized and "procedure" in document_type:
        boost += 0.55
    if "approval" in normalized and "approval" in document_type:
        boost += 0.35
    if "contract" in normalized and "contract" in document_type:
        boost += 0.35
    if "reconciliation" in normalized and "reconciliation" in document_type:
        boost += 0.35
    if "invoice" in normalized and "invoice" in document_type:
        boost += 0.2

    return boost
