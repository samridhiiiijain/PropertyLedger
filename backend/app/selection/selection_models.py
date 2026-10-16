from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from ..models import FrozenModel


class EvidenceSource(StrEnum):
    STRUCTURED_STORE = "structured_store"
    DOCUMENT_INDEX = "document_index"
    LINKED_EVIDENCE = "linked_evidence"
    RELATIONSHIP_GRAPH = "relationship_graph"
    BUSINESS_DEFINITIONS = "business_definitions"


class SelectionStatus(StrEnum):
    ANSWERED = "answered"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"
    SERVICE_UNAVAILABLE = "service_unavailable"


class QuestionIntent(StrEnum):
    STRUCTURED_CHECK = "structured_check"
    DOCUMENT_ANSWER = "document_answer"
    RELATIONSHIP_PATH = "relationship_path"
    LINKED_EVIDENCE = "linked_evidence"
    COMBINED_EVIDENCE = "combined_evidence"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class QuestionSignal(StrEnum):
    EXACT_STRUCTURED_FACT = "exact_structured_fact"
    DOCUMENT_MEANING = "document_meaning"
    RELATIONSHIP_TRACE = "relationship_trace"
    LINKED_RECORD_EVIDENCE = "linked_record_evidence"
    APPROVED_BUSINESS_TERM = "approved_business_term"
    UNAPPROVED_TERM = "unapproved_term"
    AMBIGUOUS_VARIANCE = "ambiguous_variance"


class EntityType(StrEnum):
    PROPERTY_ID = "property_id"
    PROJECT_ID = "project_id"
    VENDOR_ID = "vendor_id"
    INVOICE_ID = "invoice_id"
    PO_ID = "po_id"
    COST_CODE = "cost_code"
    DOCUMENT_ID = "document_id"


class DetectedEntity(FrozenModel):
    entity_type: EntityType
    value: str


class ApprovedTermReference(FrozenModel):
    slug: str
    term: str
    version: str


class EvidenceRequirement(FrozenModel):
    need: str
    source: EvidenceSource
    reason: str
    fields: tuple[str, ...] = ()


class EvidenceSelectionPlan(FrozenModel):
    question: str = Field(min_length=8, max_length=300)
    status: SelectionStatus
    intent: QuestionIntent
    entities: tuple[DetectedEntity, ...] = ()
    approved_terms: tuple[ApprovedTermReference, ...] = ()
    selected_sources: tuple[EvidenceSource, ...] = ()
    evidence_requirements: tuple[EvidenceRequirement, ...] = ()
    message: str
    clarification_options: tuple[str, ...] = ()


class AnalyzedQuestion(FrozenModel):
    question: str = Field(min_length=8, max_length=300)
    normalized_question: str
    intent: QuestionIntent
    entities: tuple[DetectedEntity, ...] = ()
    approved_terms: tuple[ApprovedTermReference, ...] = ()
    signals: tuple[QuestionSignal, ...] = ()
    unsupported_terms: tuple[str, ...] = ()


class SourceSelectionAnswerResponse(FrozenModel):
    question: str = Field(min_length=8, max_length=300)
    status: SelectionStatus
    intent: QuestionIntent
    selected_sources: tuple[EvidenceSource, ...]
    evidence_requirements: tuple[EvidenceRequirement, ...]
    entities: tuple[DetectedEntity, ...]
    approved_terms: tuple[ApprovedTermReference, ...]
    answer: str
    supporting_references: tuple[str, ...] = ()
