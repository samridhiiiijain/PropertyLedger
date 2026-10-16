from __future__ import annotations

from ..semantics.definitions import BUSINESS_DEFINITIONS, BusinessTermDefinition
from .question_analyzer import QuestionAnalyzer
from .selection_models import (
    AnalyzedQuestion,
    EntityType,
    EvidenceRequirement,
    EvidenceSelectionPlan,
    EvidenceSource,
    QuestionIntent,
    SelectionStatus,
)


class EvidencePlanner:
    """Convert analyzed questions into minimum-source evidence plans."""

    def __init__(
        self,
        analyzer: QuestionAnalyzer | None = None,
        definitions: tuple[BusinessTermDefinition, ...] = BUSINESS_DEFINITIONS,
    ) -> None:
        self._analyzer = analyzer or QuestionAnalyzer(definitions=definitions)
        self._definitions_by_slug = {definition.slug: definition for definition in definitions}

    def plan(self, question: str) -> EvidenceSelectionPlan:
        analyzed = self._analyzer.analyze(question)
        return self.plan_from_analysis(analyzed)

    def plan_from_analysis(self, analyzed: AnalyzedQuestion) -> EvidenceSelectionPlan:
        if analyzed.intent == QuestionIntent.UNSUPPORTED:
            return EvidenceSelectionPlan(
                question=analyzed.question,
                status=SelectionStatus.UNSUPPORTED,
                intent=analyzed.intent,
                entities=analyzed.entities,
                approved_terms=analyzed.approved_terms,
                message=self._unsupported_message(analyzed),
            )

        if analyzed.intent == QuestionIntent.AMBIGUOUS:
            return EvidenceSelectionPlan(
                question=analyzed.question,
                status=SelectionStatus.NEEDS_CLARIFICATION,
                intent=analyzed.intent,
                entities=analyzed.entities,
                approved_terms=analyzed.approved_terms,
                message=(
                    "The question mentions variance, but the approved meaning is ambiguous. "
                    "Choose the finance definition before fetching evidence."
                ),
                clarification_options=(
                    "PO variance",
                    "Cost code over budget",
                ),
            )

        requirements = self._requirements_for(analyzed)
        selected_sources = self._ordered_sources(requirements)

        return EvidenceSelectionPlan(
            question=analyzed.question,
            status=SelectionStatus.ANSWERED,
            intent=analyzed.intent,
            entities=analyzed.entities,
            approved_terms=analyzed.approved_terms,
            selected_sources=selected_sources,
            evidence_requirements=requirements,
            message=self._supported_message(analyzed, selected_sources),
        )

    def _requirements_for(self, analyzed: AnalyzedQuestion) -> tuple[EvidenceRequirement, ...]:
        if analyzed.intent == QuestionIntent.STRUCTURED_CHECK:
            return self._structured_requirements(analyzed)

        if analyzed.intent == QuestionIntent.DOCUMENT_ANSWER:
            return (
                EvidenceRequirement(
                    need="Retrieve supporting document passages.",
                    source=EvidenceSource.DOCUMENT_INDEX,
                    reason=(
                        "The question asks for document meaning or procedural context, "
                        "which is owned by the document index."
                    ),
                    fields=(
                        "Document.text",
                        "DocumentMetadata.document_id",
                        "DocumentMetadata.source_file",
                    ),
                ),
            )

        if analyzed.intent == QuestionIntent.RELATIONSHIP_PATH:
            return self._relationship_requirements(analyzed)

        if analyzed.intent == QuestionIntent.LINKED_EVIDENCE:
            return self._linked_evidence_requirements(analyzed)

        if analyzed.intent == QuestionIntent.COMBINED_EVIDENCE:
            entity_types = {entity.entity_type for entity in analyzed.entities}
            if EntityType.PROJECT_ID in entity_types:
                return (
                    EvidenceRequirement(
                        need="Read structured invoice and purchase-order values for the project.",
                        source=EvidenceSource.STRUCTURED_STORE,
                        reason=(
                            "The reconciliation result must be checked against exact invoice "
                            "and purchase-order values from structured records."
                        ),
                        fields=(
                            "project_id",
                            "invoice_id",
                            "po_id",
                            "invoices.invoice_amount",
                            "purchase_orders.po_total",
                        ),
                    ),
                    EvidenceRequirement(
                        need="Retrieve reconciliation and invoice document passages for the project.",
                        source=EvidenceSource.DOCUMENT_INDEX,
                        reason=(
                            "The answer must cite the reconciliation note and supporting "
                            "invoice or exception documents for the same project."
                        ),
                        fields=(
                            "project_id",
                            "document_id",
                            "invoice_id",
                            "po_id",
                            "Document.text",
                        ),
                    ),
                )

            return (
                *self._term_requirements(analyzed),
                EvidenceRequirement(
                    need="Read exact structured invoice facts for the requested record.",
                    source=EvidenceSource.STRUCTURED_STORE,
                    reason="The invoice ID identifies one structured finance record.",
                    fields=self._entity_fields(analyzed),
                ),
                EvidenceRequirement(
                    need="Retrieve linked document evidence for the same invoice.",
                    source=EvidenceSource.LINKED_EVIDENCE,
                    reason=(
                        "The answer needs document support constrained by stable identifiers, "
                        "not a broad document search."
                    ),
                    fields=(
                        "invoice_id",
                        "po_id",
                        "project_id",
                        "property_id",
                        "vendor_id",
                        "cost_code",
                        "document_id",
                    ),
                ),
            )

        return ()

    def _structured_requirements(self, analyzed: AnalyzedQuestion) -> tuple[EvidenceRequirement, ...]:
        return (
            *self._term_requirements(analyzed),
            EvidenceRequirement(
                need="Run the approved structured check against typed finance records.",
                source=EvidenceSource.STRUCTURED_STORE,
                reason=(
                    "The question asks for exact amounts, counts, statuses, filters, "
                    "or calculations owned by SQL-backed structured data."
                ),
                fields=self._fields_for_terms(analyzed) or self._entity_fields(analyzed),
            ),
        )

    def _relationship_requirements(self, analyzed: AnalyzedQuestion) -> tuple[EvidenceRequirement, ...]:
        requirements: list[EvidenceRequirement] = [
            *self._term_requirements(analyzed),
            EvidenceRequirement(
                need="Trace the requested multi-hop relationship path.",
                source=EvidenceSource.RELATIONSHIP_GRAPH,
                reason=(
                    "The question asks for a path or relationship trace, so Neo4j/Cypher "
                    "is the minimum sufficient relationship source."
                ),
                fields=(
                    *self._entity_fields(analyzed),
                    "HAS_PROJECT",
                    "HAS_INVOICE",
                    "AGAINST_PO",
                    "ORDERED_FROM",
                    "SUPPORTED_BY",
                ),
            ),
        ]

        entity_types = {entity.entity_type for entity in analyzed.entities}
        if EntityType.INVOICE_ID in entity_types:
            requirements.append(
                EvidenceRequirement(
                    need="Retrieve linked document evidence for the invoice in the traced path.",
                    source=EvidenceSource.LINKED_EVIDENCE,
                    reason=(
                        "The path identifies an invoice and the question asks for explanation, "
                        "so the workflow needs the document linked to that same invoice."
                    ),
                    fields=(
                        "invoice_id",
                        "po_id",
                        "project_id",
                        "property_id",
                        "vendor_id",
                        "cost_code",
                        "document_id",
                    ),
                )
            )

        return tuple(requirements)

    def _linked_evidence_requirements(self, analyzed: AnalyzedQuestion) -> tuple[EvidenceRequirement, ...]:
        return (
            EvidenceRequirement(
                need="Read the structured record identified by the invoice ID.",
                source=EvidenceSource.STRUCTURED_STORE,
                reason="Linked evidence starts from a known structured invoice record.",
                fields=self._entity_fields(analyzed),
            ),
            EvidenceRequirement(
                need="Find document passages linked to that structured record.",
                source=EvidenceSource.LINKED_EVIDENCE,
                reason="Evidence must share stable identifiers with the invoice record.",
                fields=(
                    "invoice_id",
                    "po_id",
                    "project_id",
                    "property_id",
                    "vendor_id",
                    "cost_code",
                    "document_id",
                ),
            ),
        )

    def _term_requirements(self, analyzed: AnalyzedQuestion) -> tuple[EvidenceRequirement, ...]:
        requirements: list[EvidenceRequirement] = []
        for term in analyzed.approved_terms:
            definition = self._definitions_by_slug[term.slug]
            requirements.append(
                EvidenceRequirement(
                    need=f"Apply approved meaning: {term.term} {term.version}.",
                    source=EvidenceSource.BUSINESS_DEFINITIONS,
                    reason=(
                        "The question uses an approved finance term, so the answer must "
                        "use its governed grain, rule, calculation, and fields."
                    ),
                    fields=definition.fields,
                )
            )
        return tuple(requirements)

    def _fields_for_terms(self, analyzed: AnalyzedQuestion) -> tuple[str, ...]:
        fields: list[str] = []
        for term in analyzed.approved_terms:
            definition = self._definitions_by_slug[term.slug]
            fields.extend(definition.fields)
        return tuple(dict.fromkeys(fields))

    def _entity_fields(self, analyzed: AnalyzedQuestion) -> tuple[str, ...]:
        if not analyzed.entities:
            return ()
        return tuple(dict.fromkeys(entity.entity_type.value for entity in analyzed.entities))

    def _ordered_sources(self, requirements: tuple[EvidenceRequirement, ...]) -> tuple[EvidenceSource, ...]:
        preferred_order = (
            EvidenceSource.BUSINESS_DEFINITIONS,
            EvidenceSource.STRUCTURED_STORE,
            EvidenceSource.RELATIONSHIP_GRAPH,
            EvidenceSource.LINKED_EVIDENCE,
            EvidenceSource.DOCUMENT_INDEX,
        )
        present = {requirement.source for requirement in requirements}
        return tuple(source for source in preferred_order if source in present)

    def _unsupported_message(self, analyzed: AnalyzedQuestion) -> str:
        if analyzed.unsupported_terms:
            return (
                "The question uses a term that is not in the approved business-definition set: "
                f"{', '.join(analyzed.unsupported_terms)}."
            )
        return "The application cannot identify a supported evidence route for this question."

    def _supported_message(
        self,
        analyzed: AnalyzedQuestion,
        selected_sources: tuple[EvidenceSource, ...],
    ) -> str:
        source_names = ", ".join(source.value for source in selected_sources)
        entity_values = ", ".join(entity.value for entity in analyzed.entities)
        if entity_values:
            return f"Selected {source_names} for {analyzed.intent.value} using {entity_values}."
        return f"Selected {source_names} for {analyzed.intent.value}."
