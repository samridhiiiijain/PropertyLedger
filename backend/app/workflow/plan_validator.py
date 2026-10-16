from __future__ import annotations

from ..selection.selection_models import (
    EntityType,
    EvidenceSelectionPlan,
    EvidenceSource,
    QuestionIntent,
    SelectionStatus,
)
from .workflow_models import WorkflowValidationResult


class WorkflowPlanValidator:
    """Validate a source-selection plan before any evidence source is executed."""

    def validate(self, plan: EvidenceSelectionPlan) -> WorkflowValidationResult:
        missing_requirements = self._missing_requirements(plan)

        if plan.status != SelectionStatus.ANSWERED:
            return WorkflowValidationResult(
                is_valid=False,
                message=plan.message,
                missing_requirements=missing_requirements,
            )

        if missing_requirements:
            return WorkflowValidationResult(
                is_valid=False,
                message=(
                    "The workflow cannot safely execute because the source-selection plan "
                    "is missing required evidence or identifiers."
                ),
                missing_requirements=missing_requirements,
            )

        return WorkflowValidationResult(
            is_valid=True,
            message="The source-selection plan is valid and can be executed.",
        )

    def _missing_requirements(self, plan: EvidenceSelectionPlan) -> tuple[str, ...]:
        missing: list[str] = []

        if not plan.selected_sources:
            missing.append("at least one selected evidence source")

        requirement_sources = {requirement.source for requirement in plan.evidence_requirements}
        missing.extend(
            f"evidence requirement for {source.value}"
            for source in plan.selected_sources
            if source not in requirement_sources
        )

        entity_types = {entity.entity_type for entity in plan.entities}

        if plan.intent == QuestionIntent.STRUCTURED_CHECK and EntityType.PROJECT_ID not in entity_types:
            missing.append("project_id for structured checks")

        if plan.intent == QuestionIntent.RELATIONSHIP_PATH and EntityType.PROPERTY_ID not in entity_types:
            missing.append("property_id for relationship graph traversal")

        if plan.intent == QuestionIntent.LINKED_EVIDENCE:
            if EntityType.INVOICE_ID not in entity_types:
                missing.append("invoice_id for linked evidence")

        if (
            plan.intent == QuestionIntent.COMBINED_EVIDENCE
            and EvidenceSource.LINKED_EVIDENCE in plan.selected_sources
            and EntityType.INVOICE_ID not in entity_types
        ):
            missing.append("invoice_id for linked evidence")

        if (
            plan.intent == QuestionIntent.COMBINED_EVIDENCE
            and EvidenceSource.STRUCTURED_STORE in plan.selected_sources
            and EvidenceSource.DOCUMENT_INDEX in plan.selected_sources
            and EntityType.PROJECT_ID not in entity_types
            and EntityType.INVOICE_ID not in entity_types
        ):
            missing.append("project_id or invoice_id for combined evidence")

        if plan.intent == QuestionIntent.DOCUMENT_ANSWER:
            if EvidenceSource.DOCUMENT_INDEX not in plan.selected_sources:
                missing.append("document_index source for document answers")

        return tuple(dict.fromkeys(missing))
