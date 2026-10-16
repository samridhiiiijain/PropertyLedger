from __future__ import annotations

import re

from ..documents.document_repository import DocumentRepository
from ..evidence.linked_evidence_service import LinkedEvidenceService
from ..graph.service import GraphTraversalService
from ..selection.selection_models import (
    EntityType,
    EvidenceSelectionPlan,
    EvidenceSource,
    QuestionIntent,
)
from ..semantic_query.models import SemanticQueryResponse
from ..semantic_query.service import SemanticQueryService
from .workflow_models import WorkflowEvidence, WorkflowExecutionResult


class WorkflowSourceExecutor:
    """Execute only the evidence sources selected by a validated plan."""

    def __init__(
        self,
        document_repository: DocumentRepository,
        linked_evidence_service: LinkedEvidenceService,
        graph_service: GraphTraversalService,
        semantic_query_service: SemanticQueryService,
    ) -> None:
        self.document_repository = document_repository
        self.linked_evidence_service = linked_evidence_service
        self.graph_service = graph_service
        self.semantic_query_service = semantic_query_service

    def execute(self, plan: EvidenceSelectionPlan) -> WorkflowExecutionResult:
        evidence: list[WorkflowEvidence] = []

        for source in plan.selected_sources:
            if source == EvidenceSource.BUSINESS_DEFINITIONS:
                evidence.append(self._business_definition_evidence(plan))
            elif source == EvidenceSource.STRUCTURED_STORE:
                evidence.append(self._structured_evidence(plan))
            elif source == EvidenceSource.DOCUMENT_INDEX:
                evidence.append(self._document_evidence(plan))
            elif source == EvidenceSource.LINKED_EVIDENCE:
                evidence.append(self._linked_evidence(plan))
            elif source == EvidenceSource.RELATIONSHIP_GRAPH:
                evidence.append(self._relationship_evidence(plan))

        return WorkflowExecutionResult(
            answer=self._compose_answer(plan, tuple(evidence)),
            evidence=tuple(evidence),
        )

    def _business_definition_evidence(self, plan: EvidenceSelectionPlan) -> WorkflowEvidence:
        terms = tuple(f"{term.term} {term.version}" for term in plan.approved_terms)
        summary = (
            "No approved business term was needed."
            if not terms
            else f"Applied approved meaning: {', '.join(terms)}."
        )
        return WorkflowEvidence(
            source=EvidenceSource.BUSINESS_DEFINITIONS,
            summary=summary,
            references=tuple(term.slug for term in plan.approved_terms),
        )

    def _structured_evidence(self, plan: EvidenceSelectionPlan) -> WorkflowEvidence:
        invoice_id = self._entity_value(plan, EntityType.INVOICE_ID)
        project_id = self._entity_value(plan, EntityType.PROJECT_ID)
        scope_entities = tuple(
            (entity.entity_type.value, entity.value)
            for entity in plan.entities
            if entity.entity_type != EntityType.DOCUMENT_ID
        )
        response = self.semantic_query_service.answer(
            plan.question,
            scope_entities=scope_entities,
        )
        if not response.is_successful:
            return WorkflowEvidence(
                source=EvidenceSource.STRUCTURED_STORE,
                summary=response.answer,
                references=(),
            )

        return WorkflowEvidence(
            source=EvidenceSource.STRUCTURED_STORE,
            summary=self._semantic_structured_summary(plan, response, project_id, invoice_id),
            references=self._semantic_references(response),
        )

    def _semantic_structured_summary(
        self,
        plan: EvidenceSelectionPlan,
        response: SemanticQueryResponse,
        project_id: str | None,
        invoice_id: str | None,
    ) -> str:
        rows = response.rows
        if invoice_id is not None:
            if not rows:
                return f"No structured invoice record was found for {invoice_id}."
            row = rows[0]
            return (
                f"{row['invoice_id']} is {str(row['status']).upper().replace(' ', '_')} "
                f"with invoice amount INR {float(row['invoice_amount']):,.2f}, "
                f"paid amount INR {float(row['paid_amount']):,.2f}, and outstanding amount "
                f"INR {float(row['outstanding_amount']):,.2f}."
            )

        project_label = project_id or "the requested scope"
        if "reconciliation" in plan.question.lower():
            return self._semantic_reconciliation_summary(project_label, rows)

        term_slugs = {term.slug for term in plan.approved_terms}
        if "po-variance" in term_slugs:
            return self._semantic_po_variance_summary(project_label, rows)

        if "unpaid-invoice" in term_slugs:
            return self._semantic_unpaid_invoice_summary(project_label, rows)

        if "cost-code-over-budget" in term_slugs:
            return self._semantic_budget_variance_summary(project_label, rows)

        identifiers = tuple(str(row["invoice_id"]) for row in rows if row.get("invoice_id"))
        identifier_text = ", ".join(identifiers) if identifiers else "none"
        return f"Structured records found {len(identifiers)} structured invoices for {project_label}: {identifier_text}."

    def _semantic_references(self, response: SemanticQueryResponse) -> tuple[str, ...]:
        references: list[str] = []
        for row in response.rows:
            for key in ("invoice_id", "cost_code", "budget_id", "property_id", "vendor_id"):
                value = row.get(key)
                if value is not None:
                    references.append(str(value))
                    break
        return tuple(dict.fromkeys(references))

    def _semantic_po_variance_summary(self, project_id: str, rows: tuple[dict, ...]) -> str:
        if not rows:
            return f"Structured records found 0 PO variance invoices for {project_id}."
        details = self._join_details(
            tuple(
                (
                    f"{row['invoice_id']}: invoice INR {float(row['invoice_amount']):,.2f} "
                    f"vs PO INR {float(row['po_total']):,.2f}"
                )
                for row in rows
            )
        )
        return f"Structured records found {len(rows)} PO variance invoices for {project_id}: {details}."

    def _semantic_unpaid_invoice_summary(self, project_id: str, rows: tuple[dict, ...]) -> str:
        if not rows:
            return f"Structured records found 0 unpaid invoices for {project_id}."
        details = self._join_details(
            tuple(
                f"{row['invoice_id']} with INR {float(row['outstanding_amount']):,.2f} outstanding"
                for row in rows
            )
        )
        return f"Structured records found {len(rows)} unpaid invoices for {project_id}: {details}."

    def _semantic_budget_variance_summary(self, project_id: str, rows: tuple[dict, ...]) -> str:
        if not rows:
            return f"Structured records found 0 cost codes over budget for {project_id}."
        details = self._join_details(
            tuple(
                f"{row['cost_code']} by INR {float(row['budget_variance_amount']):,.2f}"
                for row in rows
            )
        )
        return f"Structured records found {len(rows)} cost codes over budget for {project_id}: {details}."

    def _semantic_reconciliation_summary(self, project_id: str, rows: tuple[dict, ...]) -> str:
        if not rows:
            return f"Structured records found no invoices to reconcile for {project_id}."

        details = self._join_details(
            tuple(
                (
                    f"{row['invoice_id']} links to {row['po_id']}: "
                    f"invoice INR {float(row['invoice_amount']):,.2f}, PO INR "
                    f"{float(row['po_total']):,.2f}, difference INR "
                    f"{float(row['po_variance_amount']):,.2f}"
                )
                for row in rows
            )
        )
        return f"Structured reconciliation values for {project_id}: {details}."

    def _document_evidence(self, plan: EvidenceSelectionPlan) -> WorkflowEvidence:
        project_id = self._entity_value(plan, EntityType.PROJECT_ID)
        response = self.document_repository.answer_question(
            question=plan.question,
            project_id=project_id,
        )
        return WorkflowEvidence(
            source=EvidenceSource.DOCUMENT_INDEX,
            summary=response.answer,
            references=tuple(source.metadata.document_id for source in response.sources),
        )

    def _linked_evidence(self, plan: EvidenceSelectionPlan) -> WorkflowEvidence:
        invoice_id = self._entity_value(plan, EntityType.INVOICE_ID)
        if invoice_id is None:
            return WorkflowEvidence(
                source=EvidenceSource.LINKED_EVIDENCE,
                summary="Linked evidence requires a stable invoice_id.",
                references=(),
            )

        result = self.linked_evidence_service.invoice_evidence(invoice_id)
        references = tuple(match.chunk.metadata.document_id for match in result.matches)
        return WorkflowEvidence(
            source=EvidenceSource.LINKED_EVIDENCE,
            summary=result.answer,
            references=references,
        )

    def _relationship_evidence(self, plan: EvidenceSelectionPlan) -> WorkflowEvidence:
        property_id = self._entity_value(plan, EntityType.PROPERTY_ID)
        if property_id is None:
            return WorkflowEvidence(
                source=EvidenceSource.RELATIONSHIP_GRAPH,
                summary="Relationship graph execution requires a stable property_id.",
                references=(),
            )

        response = self.graph_service.trace_po_variance_paths(property_id)
        invoice_id = self._entity_value(plan, EntityType.INVOICE_ID)
        if invoice_id is not None:
            for path in response.paths:
                if path.invoice_id == invoice_id:
                    support_text = (
                        f" and is supported by {path.document_id}"
                        if path.document_id
                        else " and has no linked document evidence"
                    )
                    return WorkflowEvidence(
                        source=EvidenceSource.RELATIONSHIP_GRAPH,
                        summary=(
                            f"Neo4j traced the requested path for {path.invoice_id} on {path.property_id}: "
                            f"{path.invoice_id} exceeds {path.po_id} by INR {path.variance_amount:,.2f}"
                            f"{support_text}."
                        ),
                        references=tuple(node.id for node in path.nodes),
                    )

        return WorkflowEvidence(
            source=EvidenceSource.RELATIONSHIP_GRAPH,
            summary=response.answer,
            references=tuple(path.invoice_id for path in response.paths),
        )

    def _compose_answer(
        self,
        plan: EvidenceSelectionPlan,
        evidence: tuple[WorkflowEvidence, ...],
    ) -> str:
        if not evidence:
            return "The workflow did not execute any evidence source."

        if plan.intent == QuestionIntent.COMBINED_EVIDENCE and "reconciliation" in plan.question.lower():
            document_references = tuple(
                reference
                for item in evidence
                if item.source == EvidenceSource.DOCUMENT_INDEX
                for reference in item.references
            )
            reference_text = (
                f" Document sources reviewed: {', '.join(document_references)}."
                if document_references
                else ""
            )
            return " ".join(item.summary for item in evidence) + reference_text

        if plan.intent == QuestionIntent.COMBINED_EVIDENCE:
            return " ".join(item.summary for item in evidence)

        if (
            plan.intent == QuestionIntent.RELATIONSHIP_PATH
            and EvidenceSource.LINKED_EVIDENCE in plan.selected_sources
        ):
            concise_answer = self._compose_relationship_with_linked_evidence(evidence)
            if concise_answer:
                return concise_answer
            return " ".join(
                item.summary
                for item in evidence
                if item.source in {EvidenceSource.RELATIONSHIP_GRAPH, EvidenceSource.LINKED_EVIDENCE}
            )

        return evidence[-1].summary

    def _compose_relationship_with_linked_evidence(
        self,
        evidence: tuple[WorkflowEvidence, ...],
    ) -> str | None:
        graph_evidence = self._evidence_by_source(evidence, EvidenceSource.RELATIONSHIP_GRAPH)
        linked_evidence = self._evidence_by_source(evidence, EvidenceSource.LINKED_EVIDENCE)
        if graph_evidence is None or linked_evidence is None:
            return None

        variance_match = re.search(
            r"(?P<invoice>INV\d{4}) exceeds (?P<po>PO\d{4}) by INR (?P<amount>[\d,]+(?:\.\d{2})?)",
            graph_evidence.summary,
        )
        document_id = self._first_reference_with_prefix(linked_evidence.references, "DOC-")
        if variance_match is None or document_id is None:
            return None

        support_sentence = self._supporting_action_sentence(linked_evidence.summary)
        support_text = f" The linked document says {support_sentence}" if support_sentence else ""
        return (
            f"Payment is on hold because {variance_match.group('invoice')} exceeds "
            f"{variance_match.group('po')} by INR {variance_match.group('amount')}. "
            f"The relationship graph traced the support to {document_id}."
            f"{support_text}"
        )

    def _supporting_action_sentence(self, summary: str) -> str | None:
        sentences = tuple(
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", summary)
            if sentence.strip()
        )
        action_terms_by_priority = (
            "requested",
            "required",
            "requires",
            "subject to",
            "no payment",
            "approved",
            "on hold",
        )
        for term in action_terms_by_priority:
            for sentence in sentences:
                normalized_sentence = sentence.lower()
                if term in normalized_sentence:
                    return sentence[0].lower() + sentence[1:] if sentence else sentence
        return None

    def _evidence_by_source(
        self,
        evidence: tuple[WorkflowEvidence, ...],
        source: EvidenceSource,
    ) -> WorkflowEvidence | None:
        for item in evidence:
            if item.source == source:
                return item
        return None

    def _first_reference_with_prefix(
        self,
        references: tuple[str, ...],
        prefix: str,
    ) -> str | None:
        for reference in references:
            if reference.startswith(prefix):
                return reference
        return None

    def _join_details(self, values: tuple[str, ...]) -> str:
        if len(values) <= 1:
            return values[0] if values else "none"
        return f"{', '.join(values[:-1])} and {values[-1]}"

    def _entity_value(
        self,
        plan: EvidenceSelectionPlan,
        entity_type: EntityType,
    ) -> str | None:
        for entity in plan.entities:
            if entity.entity_type == entity_type:
                return entity.value
        return None
