from __future__ import annotations

import re

from .document_query import extract_identifiers
from ..models import DocumentEvidence


def unsupported_question(question: str) -> bool:
    normalized = question.lower()
    no_evidence_terms = ("delay reason", "delayed a payment", "why was payment delayed")
    return (
        is_future_payment_question(question)
        or is_structured_budget_question(question)
        or is_structured_invoice_status_question(question)
        or is_out_of_domain_question(question)
        or any(term in normalized for term in no_evidence_terms)
    )


def is_out_of_domain_question(question: str) -> bool:
    """Reject clearly unrelated questions before spending retrieval work."""
    normalized = question.lower()
    finance_terms = (
        "invoice", "payment", "finance", "approval", "budget", "vendor",
        "purchase order", "po", "project", "property", "cost", "contract",
        "procedure", "policy", "compliance", "receipt", "paid", "unpaid",
        "account", "bank", "due", "expense", "document", "record",
    )
    identifiers = extract_identifiers(question)
    has_identifier = any(
        value is not None
        for value in (
            identifiers.document_id,
            identifiers.property_id,
            identifiers.project_id,
            identifiers.vendor_id,
            identifiers.invoice_id,
            identifiers.po_id,
            identifiers.cost_code,
        )
    )
    return not any(term in normalized for term in finance_terms) and not has_identifier


def is_future_payment_question(question: str) -> bool:
    normalized = question.lower()
    future_terms = ("definitely", "guarantee", "tomorrow", "will be paid")
    return any(term in normalized for term in future_terms)


def is_structured_budget_question(question: str) -> bool:
    normalized = question.lower()
    return (
        "budget" in normalized
        and ("cost code" in normalized or "cost codes" in normalized)
        and ("above" in normalized or "over" in normalized or "variance" in normalized)
    )


def is_structured_invoice_status_question(question: str) -> bool:
    normalized = question.lower()
    return (
        ("invoice" in normalized or "invoices" in normalized)
        and ("unpaid" in normalized or "partially paid" in normalized or "paid" in normalized)
        and ("project" in normalized or "pr" in normalized)
    )


def sources_support_question(
    question: str,
    sources: tuple[DocumentEvidence, ...],
) -> bool:
    required_groups = required_evidence_terms(question)
    if not required_groups:
        return True

    evidence_text = "\n".join(source.text.lower() for source in sources)
    return all(any(contains_evidence_term(evidence_text, term) for term in group) for group in required_groups)


def required_evidence_terms(question: str) -> tuple[tuple[str, ...], ...]:
    normalized = question.lower()
    required_groups: list[tuple[str, ...]] = []

    if "bank account" in normalized or "account number" in normalized:
        required_groups.append(("bank account", "account number", "iban", "ifsc"))

    if "phone" in normalized or "call" in normalized or "verbally" in normalized:
        required_groups.append(("phone", "call", "verbal", "verbally"))

    return tuple(required_groups)


def contains_evidence_term(evidence_text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", evidence_text) is not None


def answer_from_sources(question: str, sources: tuple[DocumentEvidence, ...]) -> str:
    normalized = question.lower()

    if "procedure" in normalized and "approval" in normalized:
        procedure = next(
            (source for source in sources if source.metadata.document_type == "Finance Procedure"),
            sources[0],
        )
        passage = " ".join(procedure.text.split())
        return (
            f"The finance procedure in {procedure.metadata.document_id} states: {passage}"
        )

    # Prefer the passage whose metadata carries the invoice_id named in the question;
    # otherwise use the highest-ranked retrieved passage.
    invoice_id = extract_identifiers(question).invoice_id
    primary = next(
        (source for source in sources if invoice_id and source.metadata.invoice_id == invoice_id),
        sources[0],
    )
    passage = " ".join(primary.text.split())
    return f"Based on the retrieved document evidence in {primary.metadata.document_id}: {passage}"
