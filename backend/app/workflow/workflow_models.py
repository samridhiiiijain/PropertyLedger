from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from ..models import FrozenModel
from ..selection.selection_models import (
    EvidenceSelectionPlan,
    EvidenceSource,
    QuestionIntent,
)


class WorkflowStatus(StrEnum):
    ANSWERED = "answered"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"
    SERVICE_UNAVAILABLE = "service_unavailable"


class WorkflowStepStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class WorkflowStepName(StrEnum):
    RECEIVE_QUESTION = "receive_question"
    ANALYZE_QUESTION = "analyze_question"
    BUILD_SOURCE_SELECTION_PLAN = "build_source_selection_plan"
    VALIDATE_PLAN = "validate_plan"
    EXECUTE_SELECTED_SOURCE = "execute_selected_source"
    RETURN_ANSWER = "return_answer"
    SHOW_TRACE = "show_trace"
    REJECT_REQUEST = "reject_request"


class WorkflowTraceStep(FrozenModel):
    step: WorkflowStepName
    label: str
    status: WorkflowStepStatus
    message: str
    selected_sources: tuple[EvidenceSource, ...] = ()


class WorkflowValidationResult(FrozenModel):
    is_valid: bool
    message: str
    missing_requirements: tuple[str, ...] = ()


class WorkflowEvidence(FrozenModel):
    source: EvidenceSource
    summary: str
    references: tuple[str, ...] = ()


class WorkflowExecutionResult(FrozenModel):
    answer: str
    evidence: tuple[WorkflowEvidence, ...] = ()


class WorkflowStateSnapshot(FrozenModel):
    question: str = Field(min_length=8, max_length=300)
    intent: QuestionIntent | None = None
    plan: EvidenceSelectionPlan | None = None
    validation: WorkflowValidationResult | None = None
    selected_sources: tuple[EvidenceSource, ...] = ()
    evidence: tuple[WorkflowEvidence, ...] = ()
    answer: str | None = None
    status: WorkflowStatus | None = None
    trace: tuple[WorkflowTraceStep, ...] = ()


class WorkflowAnswerResponse(FrozenModel):
    question: str = Field(min_length=8, max_length=300)
    status: WorkflowStatus
    intent: QuestionIntent
    answer: str
    plan: EvidenceSelectionPlan
    validation: WorkflowValidationResult
    evidence: tuple[WorkflowEvidence, ...]
    trace: tuple[WorkflowTraceStep, ...]
